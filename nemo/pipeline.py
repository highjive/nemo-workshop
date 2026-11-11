"""The eight stages, each with a gate.

Gates are the reason this works on slow hardware. A model that produces a
plausible-looking enclosure for a part that draws more current than the
supply has wasted twenty minutes. Catching it at stage 2 costs nothing.

Every stage returns a StageResult. A stage with a failing gate does not
advance the pipeline, and says which earlier stage to go back to.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import checks, concept, drawings, enclosure, firmware, harness, schematic
from .checks import FAIL, Result
from .checks import harness as harness_checks
from .checks.runners import TOOLS_FAILED
from .config import Config
from .parts import Part, PartsLibrary
from .project import Brief, Project
from .prompts import load_prompt
from .safety import Policy, blocking, review as safety_review, signoffs
from .router import ModelCallFailed, Router, explain_failure


@dataclass
class StageResult:
    stage: str
    ok: bool
    results: list[Result] = field(default_factory=list)
    artifacts: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    go_back_to: str | None = None
    degraded: bool = False

    def render(self) -> str:
        head = f"=== {self.stage} " + ("=" * max(0, 46 - len(self.stage)))
        body = [head]
        if self.degraded:
            # "remote was unreachable" was printed here even when no remote
            # reviewer is configured at all, which is the default.
            body.append("  (ran on the local model only -- no second opinion "
                        "was had; check its output more carefully)")
        for a in self.artifacts:
            body.append(f"  wrote {a}")
        for n in self.notes:
            body.append(f"  {n}")
        if self.results:
            body.append("")
            body.extend("  " + ln for ln in
                        checks.summarise(self.results)[0].splitlines())
        if not self.ok and self.go_back_to:
            body.append(f"\n  GATE FAILED -- fix at stage '{self.go_back_to}' "
                        "and rerun from there.")
        return "\n".join(body)


def pio_board(mcu: str) -> str:
    """PlatformIO board for a microcontroller ref.

    Matched on the chip family in the name. An earlier revision looked the
    ref up exactly, so 'waveshare_esp32s3_lcd_128' -- the pendant's board --
    fell through to the plain ESP32 default and firmware was built for the
    wrong chip.
    """
    m = (mcu or "").lower().replace("-", "").replace("_", "")
    if "esp32s3" in m:
        return "esp32-s3-devkitc-1"
    if "esp32c3" in m:
        return "esp32-c3-devkitm-1"
    if "rp2040" in m or "pico" in m:
        return "pico"
    return "esp32dev"


def constraints_text(brief) -> str:
    """The brief's constraints, for every model step.

    Only the enclosure step used to receive them; the schematic, wiring and
    firmware steps never saw a constraint the user wrote, nor any fix Nemo
    suggested by adding one.
    """
    items = [c for c in (brief.constraints or []) if c.strip()]
    if not items:
        return ""
    return "\n\nConstraints (must be met):\n" + "\n".join(f"- {c}" for c in items)


def salvage_yaml(raw: str) -> dict:
    """The top-level `key: value` lines of a YAML mapping that will not
    parse as a whole, each parsed on its own (with its indented
    continuation lines); a value that still will not parse is kept as
    text, with list brackets removed. {} if there are no such lines."""
    out: dict = {}
    key, buf = None, []

    def flush():
        if key is None:
            return
        body = "\n".join(buf).strip()
        try:
            out[key] = yaml.safe_load(f"{key}: {body}" if "\n" not in body
                                      else f"{key}:\n{body}")[key]
        except (yaml.YAMLError, TypeError, KeyError):
            out[key] = body.strip("[]").strip()
    for line in raw.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            flush()
            key, buf = m.group(1), [m.group(2)]
        elif key is not None:
            buf.append(line)
    flush()
    return out


def unwrap_brief(data):
    """The brief out of a reply that wrapped it.

    D178. On the AH531 the model answered step 1 with every field inside
    `blocks: [{name: ..., function: ..., ...}]`. The top level had none of
    them, so all five were reported missing. A list holding the brief, or a
    mapping with one entry that is the brief (or a list starting with it),
    is unwrapped; anything else is returned as it came.
    """
    fields = set(Brief.__dataclass_fields__) - {"name"}

    def is_brief(d) -> bool:
        return isinstance(d, dict) and bool(fields & set(d))

    if isinstance(data, list) and data and is_brief(data[0]):
        return data[0]
    if isinstance(data, dict) and not is_brief(data):
        inner = [v[0] if isinstance(v, list) else v for v in data.values()
                 if is_brief(v) or (isinstance(v, list) and v and is_brief(v[0]))]
        if len(inner) == 1:
            return inner[0]
    return data


class Pipeline:
    def __init__(self, project: Project, cfg: Config, router: Router,
                 library: PartsLibrary, policy: Policy | None = None):
        self.p = project
        self.cfg = cfg
        self.router = router
        self.lib = library
        self.policy = policy or Policy()
        self._safety = []

    # ----------------------------------------------------------------
    # helpers
    # ----------------------------------------------------------------

    def _parts(self, brief: Brief) -> list[Part]:
        out, unknown = [], []
        for ref in brief.parts:
            part = self.lib.get(ref)
            if part is None:
                unknown.append(ref)
            else:
                out.append(part)
        if unknown:
            raise KeyError(
                "not in the parts library: " + ", ".join(unknown) +
                ". Add them under parts/ with figures from the datasheet. "
                "Nemo will not guess a pinout.")
        return out

    def _ask(self, task: str, prompt_name: str, user: str,
             schema: dict | None = None, max_tokens: int | None = None,
             **fmt) -> tuple[str, bool]:
        system = load_prompt(prompt_name, cfg=self.cfg, **fmt)
        extra = {}
        if schema is not None:
            extra["schema"] = schema
        if max_tokens is not None:
            extra["max_tokens"] = max_tokens
        # So a review queued while offline knows where its answer belongs.
        stage = {"schematic": "electrical"}.get(prompt_name, prompt_name)
        try:
            self.router.context = {"project": str(self.p.root), "stage": stage}
        except AttributeError:
            pass
        try:
            reply = self.router.ask(task, system, user, **extra)
        except Exception as exc:                             # noqa: BLE001
            # Only what explain_failure recognises as a failed model call;
            # anything else is a bug and should still look like one.
            why = explain_failure(exc, getattr(self.router, "timeout", 0))
            if why is None:
                raise
            raise ModelCallFailed(why) from exc
        return reply.text, reply.degraded

    @staticmethod
    def _extract(text: str, fence: str = "") -> str:
        """Pull the first fenced code block, or return the text as-is."""
        if "```" not in text:
            return text.strip()
        chunks = text.split("```")
        for i in range(1, len(chunks), 2):
            block = chunks[i]
            first, _, rest = block.partition("\n")
            if not fence or first.strip().lower() in (fence, ""):
                return rest.strip() if rest else block.strip()
        return chunks[1].partition("\n")[2].strip()

    # ----------------------------------------------------------------
    # 1. brief
    # ----------------------------------------------------------------

    def stage_brief(self, prompt: str) -> StageResult:
        # The Clerk (nemo/clerk.py): what the owner chose from the Brief
        # tab's lists is decided; the model is told to leave it out, and
        # code puts it back after.
        from . import clerk
        try:
            chosen = clerk.decided(self.p.load_brief()) if self.p.brief_path.exists() else {}
        except Exception:                                        # noqa: BLE001
            chosen = {}
        text, degraded = self._ask("template_fill", "brief", prompt + clerk.note(chosen),
                                   known_parts=", ".join(
                                       sorted(self.lib.parts)))
        def reject(why: str) -> StageResult:
            return StageResult("brief", False, go_back_to="brief", notes=[
                f"The model did not return a usable brief: {why}",
                "Raw output kept at brief.raw.txt. Either rerun, or write "
                "brief.yaml by hand -- the rest of the pipeline only needs "
                "the file, not the model."])

        raw = self._extract(text, "yaml")
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            # D183: one bad line (on the AH531, `open_questions: [Is it
            # compatible?; Is it enough?]`) threw the whole brief away. Read
            # it a field at a time instead; a field that will not parse is
            # kept as its text, which the Brief then splits into a list.
            (self.p.root / "brief.raw.txt").write_text(text, encoding="utf-8")
            data = salvage_yaml(raw)
            if not data:
                return reject(f"invalid YAML ({exc})")

        data = unwrap_brief(data)
        # A small model will sometimes return a bare string, a list, or a
        # dict missing the one field everything else keys off. Catch all
        # three here rather than letting the dataclass raise.
        if not isinstance(data, dict):
            (self.p.root / "brief.raw.txt").write_text(text, encoding="utf-8")
            return reject(f"expected a YAML mapping, got {type(data).__name__}")
        if not data.get("name"):
            data["name"] = self.p.root.name

        allowed = Brief.__dataclass_fields__.keys()
        # D189: the owner's own answers are not the model's to change. A
        # redraft rebuilt the brief from the model's reply, which never has
        # them, and No power / No parts needed, the accepted stops and the
        # other loads went back to their defaults.
        own = ("no_power", "no_parts", "accepted", "extra_loads")
        if self.p.brief_path.exists():
            try:
                before = self.p.load_brief()
                for k in own:
                    data[k] = getattr(before, k)
            except Exception:                                    # noqa: BLE001
                pass
        overruled = clerk.keep(data, chosen)
        if data.get("no_parts"):
            data["parts"], data["mcu"] = [], ""         # the owner said none
        if data.get("no_power"):
            data["power"], data["supply_ma"] = "", 0.0
        try:
            brief = Brief(**{k: v for k, v in data.items() if k in allowed})
        except TypeError as exc:
            (self.p.root / "brief.raw.txt").write_text(text, encoding="utf-8")
            return reject(str(exc))
        # What the request asked for, by code (nemo/requested.py; the blunderbuss
        # through qwen3-8b, 2026-11-05): features the model added are taken out;
        # a printed prop needs no power or parts; its real size is read from the
        # request or asked for. The owner's own ticks are never overruled.
        from . import requested
        said_first = requested.strip_invented(prompt, brief)
        owner_ticked = False
        try:
            if self.p.brief_path.exists():
                old = self.p.load_brief()
                owner_ticked = bool(old.no_power or old.no_parts)
        except Exception:                                        # noqa: BLE001
            pass
        if not owner_ticked and requested.mechanical(prompt, brief):
            brief.no_power = brief.no_parts = True
            brief.parts, brief.mcu, brief.power, brief.supply_ma = [], "", "", 0.0
            said_first.append("Writer: a printed object with nothing electrical asked for, so "
                              "No power and No parts are ticked; untick them on the Brief tab "
                              "if it is to light up, move or make a sound.")
        said_first += requested.shape_notes(prompt, brief)
        if not brief.no_parts:
            said_first += requested.library_refs(brief, self.lib.parts, prompt)
            said_first += requested.unasked_parts(prompt, brief, chosen.get("parts", ()))
            said_first += requested.purposes_from_request(prompt, brief)      # D270
            said_first += requested.board_in_parts(brief, self.lib.parts)
            said_first += requested.asked_cell(prompt, brief, self.lib.parts)
            said_first += requested.asked_charger(prompt, brief, self.lib.parts)
            said_first += requested.envelope_fits(prompt, brief, self.lib.parts)
            said_first += requested.power_figures(prompt, brief)
        complete, missing = brief.complete
        notes = list(said_first)
        # D178: an incomplete answer was saved over the brief whatever was
        # there. On the AH531 a brief that had passed step 2 was replaced by
        # one holding only its name. Keep the better one; the answer is not
        # lost, it is kept beside it.
        kept = None
        if not complete and self.p.brief_path.exists():
            try:
                old = self.p.load_brief()
                if len(old.complete[1]) < len(missing):
                    kept = old
            except Exception:                                    # noqa: BLE001
                kept = None
        if kept is None:
            self.p.save_brief(brief)
        else:
            (self.p.root / "brief.rejected.yaml").write_text(
                yaml.safe_dump(asdict(brief), sort_keys=False), encoding="utf-8")
            notes.append("Your brief was kept: this answer is less complete than "
                         "it. The answer is in brief.rejected.yaml.")
        if not complete:
            notes.append("The brief is incomplete. Nemo will not invent "
                         "these -- answer them and rerun:")
            notes += [f"  - {m}" for m in missing]
        if chosen:
            notes.append("Clerk: kept as you chose: " + ", ".join(chosen)
                         + (f" (the model had changed {', '.join(overruled)})" if overruled else "")
                         + ".")
        if brief.open_questions:
            notes.append("Open questions recorded:")
            notes += [f"  - {q}" for q in brief.open_questions]

        self.p.commit("brief", brief.name)
        return StageResult("brief", complete, artifacts=[self.p.brief_path],
                           notes=notes, degraded=degraded,
                           go_back_to=None if complete else "brief")

    # ----------------------------------------------------------------
    # 2. parts and power
    # ----------------------------------------------------------------

    def stage_parts(self) -> StageResult:
        brief = self.p.load_brief()
        parts = self._parts(brief)

        with self.p.bom_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ref", "name", "category", "supply_v",
                        "typ_mA", "peak_mA", "size_mm", "mount", "source"])
            for p in parts:
                w.writerow([p.ref, p.name, p.category,
                            "/".join(str(v) for v in p.supply_v),
                            p.current_ma, p.peak_ma,
                            "x".join(str(v) for v in p.size_mm),
                            p.mount, p.source])

        from . import named
        extras, bad_extras = named.extra_loads(brief)            # D162
        results = [
            checks.current_sum(parts, brief.supply_ma, extra=extras),
            checks.supply_rails(parts, brief.rails),
            checks.fits_envelope(parts, brief.envelope_mm),
        ]
        if brief.no_power and not any(p.category != "power" and p.draw_ma > 0 for p in parts):
            # Nothing draws current and the owner said none is needed: the
            # supply checks have nothing to check, and say so as a pass.
            results[0] = checks.Result("current_sum", checks.PASS, "no power needed")
            results[1] = checks.Result("supply_rails", checks.PASS, "no power needed")

        # Safety parameters run here, before any CAD or firmware work, so a
        # blocked design costs seconds rather than an afternoon.
        findings = safety_review(brief, parts, self.policy)
        blocks = blocking(findings)
        if blocks:
            results.append(checks.Result(
                "safety", FAIL,
                f"{len(blocks)} safety rule{'s' if len(blocks) > 1 else ''} "
                f"block{'' if len(blocks) > 1 else 's'} this design",
                [f.render() for f in blocks]))
        else:
            results.append(checks.Result(
                "safety", checks.PASS,
                ("no sign-offs needed" if not signoffs(findings) else
                 f"{len(signoffs(findings))} sign-off"
                 f"{'s' if len(signoffs(findings)) > 1 else ''} needed"),
                [f.render() for f in findings]))
        self._safety = findings
        from .results import save_safety
        save_safety(self.p.root, findings)
        total = sum(p.draw_ma for p in parts) + sum(ma for _, ma in extras)
        lines = ["# Power budget", "",
                 f"Supply: {brief.power} ({brief.supply_ma:.0f} mA)",
                 f"Rails: {', '.join(str(r) + ' V' for r in brief.rails)}",
                 "", "| part | rail | typ mA | peak mA |",
                 "|---|---|---|---|"]
        for p in parts:
            lines.append(
                f"| {p.ref} | {'/'.join(str(v) for v in p.supply_v)} "
                f"| {p.current_ma:.0f} | {p.peak_ma:.0f} |")
        lines += [f"| {name} | the brief's own figure | - | {ma:.0f} |" for name, ma in extras]
        lines += ["", f"**Peak total: {total:.0f} mA**", "",
                  "Peak is used deliberately. A design that only works when "
                  "nothing is transmitting is not a design."]
        # D162: what the brief names and this table does not hold.
        absent = named.question(named.named_but_absent(brief, parts))
        notes = [f"In the brief's extra_loads, {b}: it is not counted." for b in bad_extras]
        if absent:
            notes.append(absent[0].upper() + absent[1:] + ".")
            lines += ["", f"**Not in this budget:** {absent}."]
        self.p.power_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok = all(r.ok for r in results)
        self.p.commit("parts", f"{len(parts)} parts, {total:.0f} mA peak")
        return StageResult("parts", ok, results,
                           [self.p.bom_path, self.p.power_path], notes=notes,
                           go_back_to="brief" if not ok else None)

    # ----------------------------------------------------------------
    # 3. electrical
    # ----------------------------------------------------------------

    def _not_needed(self, stage: str, brief) -> StageResult | None:
        """With No parts needed, there is nothing to draw, wire or program:
        the step is passed with that said, not failed (owner, 2026-10-18)."""
        from . import steps
        why = steps.not_needed(stage, brief)
        return StageResult(stage, True, notes=[why]) if why else None

    def stage_electrical(self) -> StageResult:
        brief = self.p.load_brief()
        skip = self._not_needed("electrical", brief)
        if skip:
            return skip
        parts = self._parts(brief)
        facts = "\n".join(
            f"- {p.ref} ({p.name}): logic {p.logic_v} V, supply "
            f"{p.supply_v} V, interfaces {p.interfaces}, "
            f"pins {[x.name for x in p.pins]}. {p.notes.strip()}"
            for p in parts)

        script = self.p.root / "electrical" / "schematic.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        notes: list[str] = []
        connection_results: list[Result] = []
        if self._constrained():
            # The model decides which pin goes to which pin and nothing
            # else; schematic.py writes the SKiDL. See that module for why.
            doc, notes, degraded, failed = self._decide_connections(brief, parts, "electrical")
            if failed is not None:
                return failed
            self.p.connections.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            try:
                script.write_text(schematic.skidl_script(doc, parts), encoding="utf-8")
            except schematic.SchematicError as exc:
                return StageResult("electrical", False, notes=notes + [
                    f"The connections could not be drawn as a schematic: {exc}"],
                    degraded=degraded, go_back_to="electrical")
            connection_results = self._connection_results(doc, parts)
        else:
            text, degraded = self._ask(
                "cad_script", "schematic",
                f"{brief.function}\n\nMCU: {brief.mcu}\n\nParts:\n{facts}"
                f"{constraints_text(brief)}",
                rails=brief.rails)
            script.write_text(self._extract(text, "python"), encoding="utf-8")

        # SKiDL generates the netlist and schematic; kicad-cli checks it.
        generated = checks.generate_schematic(script, self.p.schematic)
        results = connection_results + [generated]
        if generated.ok:
            results.append(checks.erc(self.p.schematic))
        # D153: where the wires themselves were checked (harness_levels), the
        # older comparison of same-named bus pins adds nothing, and on most
        # projects it had nothing to compare and put "unchecked" in the guide.
        if not any(r.name == "harness_levels" for r in connection_results):
            links = self._declared_links(parts)
            results.append(checks.voltage_compatibility(links))

        ok = all(r.ok for r in results)
        self.p.commit("electrical", "schematic generated")
        # Where to go back to depends on what failed. Parts that cannot
        # talk to each other are a parts problem. A script that will not
        # run, or a schematic that fails its rules check, is this step's
        # own output: the first real run sent the owner to 'parts' over a
        # syntax error in the model's script.
        back = None
        if not ok:
            own = any(not r.ok for r in results
                      if r.name in ("schematic", "erc", "harness_covers",
                                    "harness_electrical", "harness_pins",
                                    "harness_signals", "harness_supply",
                                    "harness_levels"))
            back = "electrical" if own else "parts"
        return StageResult("electrical", ok, results, [script],
                           notes=notes, degraded=degraded, go_back_to=back)

    @staticmethod
    def _declared_links(parts: list[Part]) -> list:
        """Pair every bus pin against every other part's matching bus pin.

        Crude, but it catches the case that actually bites: a 5 V module
        talking to 3.3 V logic.
        """
        links = []
        for i, a in enumerate(parts):
            for b in parts[i + 1:]:
                shared = set(a.interfaces) & set(b.interfaces)
                if not shared:
                    continue
                for pa in a.pins:
                    for pb in b.pins:
                        if (pa.function == "bus" and pb.function == "bus"
                                and pa.name == pb.name):
                            links.append((a, pa.name, b, pb.name))
        return links

    # ----------------------------------------------------------------
    # 4. wiring
    # ----------------------------------------------------------------

    def stage_wiring(self) -> StageResult:
        brief = self.p.load_brief()
        skip = self._not_needed("wiring", brief)
        if skip:
            return skip
        parts = self._parts(brief)
        facts = "\n".join(
            f"- {p.ref}: pins {[x.name for x in p.pins]}" for p in parts)

        notes: list[str] = []
        if not self._constrained():
            text, degraded = self._ask("template_fill", "wiring",
                                       f"{brief.function}\n\nParts:\n{facts}"
                                       f"{constraints_text(brief)}")
            self.p.harness.write_text(self._extract(text, "yaml"), encoding="utf-8")
            results = self._harness_results(parts)
        else:
            # The model chooses the connections; code writes the file. See
            # harness.py for why. If the electrical step already chose
            # them, they are used as they are: the schematic and the
            # harness must describe the same circuit, and asking twice
            # would get two different answers.
            self.p.harness.parent.mkdir(parents=True, exist_ok=True)
            doc, degraded = self._saved_connections(parts), False
            if doc is not None:
                notes.append("Wired from the connections chosen in the electrical "
                             "step (electrical/connections.json).")
            elif self._electrical_failed():
                # D165: the same question, to the same model, minutes after
                # it failed. On the real machine that was a second half hour
                # spent waiting for the same timeout.
                return StageResult("wiring", False, notes=[
                    "The electrical step did not produce connections, and this step "
                    "uses the same ones. The model was not asked again. Run the "
                    "electrical step, then this one."], go_back_to="electrical")
            else:
                doc, more, degraded, failed = self._decide_connections(brief, parts, "wiring")
                if failed is not None:
                    return failed
                notes += more
            try:
                written, made = harness.build(doc, parts)
            except harness.HarnessError as exc:
                return StageResult("wiring", False, notes=notes + [
                    f"The saved connections could not be used: {exc}"],
                    degraded=degraded, go_back_to="electrical")
            self.p.harness.write_text(written, encoding="utf-8")
            results = self._harness_results(parts)
            notes = made + notes

        ok = all(r.ok for r in results)
        self.p.commit("wiring", "harness generated")
        # A harness that fails its own checks is this step's to redo. It
        # used to point back at the electrical step for everything. A
        # harness that only disagrees with the schematic is not: the
        # schematic is redrawn from the connections first.
        back = None
        if not ok:
            failed = {r.name for r in results if not r.ok}
            back = "electrical" if failed == {"harness_netlist"} else "wiring"
        return StageResult("wiring", ok, results, [self.p.harness],
                           notes=notes, degraded=degraded, go_back_to=back)

    def _harness_results(self, parts: list[Part]) -> list[Result]:
        results = [checks.wireviz(self.p.harness)]
        results.append(checks.check_wire_gauges(self._harness_runs(self.p.harness, parts)))
        # Pin existence against the library. The earlier comparison of
        # harness names with schematic net names compared two different
        # namespaces and could never pass; harness_netlist (below) compares
        # pin with pin.
        results.append(self.check_harness_pins(self.p.harness, parts))
        results.append(self.check_harness_covers(self.p.harness, parts))
        results.append(self.check_harness_electrical(self.p.harness, parts))
        results.append(self.check_harness_signals(self.p.harness, parts))
        results.append(self.check_harness_supply(self.p.harness, parts))
        results.append(self.check_harness_levels(self.p.harness, parts))
        results.append(self.check_harness_netlist(
            self.p.harness, self.p.schematic,
            self.p.root / "electrical" / "schematic.py"))
        return results

    # The harness checks live in nemo/checks/harness.py; their old names stay
    # here for the steps and tests that call them.
    _schematic_pin_names = staticmethod(harness_checks._schematic_pin_names)
    _harness_groups = staticmethod(harness_checks._harness_groups)
    check_harness_netlist = staticmethod(harness_checks.check_harness_netlist)
    _load_harness = staticmethod(harness_checks._load_harness)
    _topology = staticmethod(harness_checks._topology)
    _match_part = staticmethod(harness_checks._match_part)
    _harness_nets = staticmethod(harness_checks._harness_nets)
    _harness_runs = staticmethod(harness_checks._harness_runs)
    check_harness_pins = staticmethod(harness_checks.check_harness_pins)
    check_harness_covers = staticmethod(harness_checks.check_harness_covers)
    _wire_pairs = staticmethod(harness_checks._wire_pairs)
    check_harness_electrical = staticmethod(harness_checks.check_harness_electrical)
    _pin_nets = staticmethod(harness_checks._pin_nets)
    check_harness_signals = staticmethod(harness_checks.check_harness_signals)
    check_harness_supply = staticmethod(harness_checks.check_harness_supply)
    check_harness_levels = staticmethod(harness_checks.check_harness_levels)
    SURGING = harness_checks.SURGING
    check_pin_current = staticmethod(harness_checks.check_pin_current)

    def _electrical_failed(self) -> bool:
        """Did the electrical step last end in failure? False where it has
        not been run at all: this step may then decide the connections."""
        from .results import load_results
        saved = load_results(self.p.root).get("electrical")
        return isinstance(saved, dict) and saved.get("ok") is False

    def _saved_connections(self, parts: list[Part]) -> dict | None:
        """The electrical step's connections, if they are there and still
        describe these parts. None if not."""
        path = self.p.connections
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            harness.build(doc, parts)
        except (json.JSONDecodeError, harness.HarnessError, OSError):
            return None                 # stale or hand-broken: decide afresh
        return doc

    def _connection_results(self, doc: dict, parts: list[Part]) -> list[Result]:
        """The checks that judge a connection list as a circuit, run on the
        harness code would write from it. No drawing: that is the wiring
        step's business."""
        scratch = self.p.root / ".nemo" / "connections-check.yaml"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        text, _ = harness.build(doc, parts)
        scratch.write_text(text, encoding="utf-8")
        return [self.check_harness_pins(scratch, parts),
                self.check_harness_covers(scratch, parts),
                self.check_harness_electrical(scratch, parts),
                self.check_harness_signals(scratch, parts),
                self.check_harness_supply(scratch, parts),
                self.check_harness_levels(scratch, parts),
                self.check_pin_current(scratch, parts)]

    def _decide_connections(self, brief: Brief, parts: list[Part], stage: str
                            ) -> tuple[dict | None, list[str], bool, StageResult | None]:
        """Ask the model which pin goes to which pin, held to a schema of
        this project's parts. One retry with the faults quoted back, the
        same gate-then-retry as the firmware step; the better answer is
        kept. Returns (connections, notes, degraded, a failed step or None).
        """
        # A level shifter is not offered to the model (D148).
        asked = harness.chosen_by_model(parts)
        # D164: where code wires all the power, the model is asked for the
        # signal wires only, and for nothing code decides anyway.
        compact = harness.power_by_code(parts)
        user = (f"{brief.function}\n\nParts:\n{harness.part_facts(asked, compact)}"
                f"{constraints_text(brief)}")
        schema = harness.harness_schema(asked, compact)
        prompt = "wiring_signals_json" if compact else "wiring_json"
        # D171: shorter still. With one board, every signal wire runs from
        # it to a part, so the model need only name the board pin for each.
        choices = harness.pin_choice_schema(asked) if compact else None
        if choices is not None:
            schema, prompt = choices, "wiring_pins_json"
        notes: list[str] = []
        degraded, feedback, best = False, "", None
        moved: dict[int, list[str]] = {}
        # D177: with no signal pin left for the model to place (a board and
        # a battery, say), the schema's list of cables was empty, and
        # llama-server refuses an empty anyOf with 400 Bad Request. There is
        # nothing to ask; code wires the rest as it always does.
        nothing_to_ask = choices is None and not harness.cable_choices(schema)
        if nothing_to_ask:
            notes.append("No signal wire to choose: power and ground are wired "
                         "by code, and the model was not asked.")
        for attempt in (1, 2):
            if nothing_to_ask:
                text, deg = '{"cables": []}', False
            else:
                text, deg = self._ask("template_fill", prompt, user + feedback,
                                      schema=schema, max_tokens=1200)
            degraded = degraded or deg
            try:
                doc = harness.parse_reply(text)
                if choices is not None:
                    doc = harness.from_pin_choices(doc, asked)
                # Power and ground are known, not chosen (D141, D145).
                doc, stray = harness.without_shifter_wires(doc, parts)
                doc, switched = harness.without_contact_wires(doc, parts)   # D159
                doc, loud = harness.wire_speakers(doc, parts)               # D166
                doc, usb = harness.wire_usb(doc, parts)
                doc, moved[attempt] = harness.wire_power(doc, parts, asked=not compact)
                moved[attempt] = stray + switched + loud + usb + moved[attempt]
                doc, over = harness.drop_overvoltage(doc, parts)
                doc, bus = harness.join_i2c_bus(doc, parts)                 # D269
                doc, apart = harness.spread_shared_pins(doc, parts)
                apart = bus + apart
                doc, via = harness.route_through_shifter(doc, parts)
                doc, hues = harness.recolour_signals(doc, parts)            # D161
                moved[attempt] += over + apart + via + hues
                found = self._connection_results(doc, parts)
            except harness.HarnessError as exc:
                if best is not None:
                    notes.append(f"A second attempt could not be used ({exc}); "
                                 "the first is kept.")
                    break
                raw = self.p.root / stage / "connections.raw.txt"
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(text, encoding="utf-8")
                if attempt == 1:
                    # An answer that cannot be used at all gets the same one
                    # second chance as a faulty one, with the reason (D135).
                    notes.append(f"The first answer could not be used ({exc}), "
                                 "so the model was asked again.")
                    feedback = ("\n\nYour last answer could not be used: "
                                f"{exc}. Give the whole "
                                f"{'answer' if choices is not None else 'cable list'} again.")
                    continue
                return None, notes, degraded, StageResult(
                    stage, False, notes=[
                        f"The model's connections could not be used: {exc}",
                        f"Its reply is kept at {stage}/{raw.name}. Run the step again."],
                    degraded=degraded, go_back_to=stage)
            faults = [i for r in found if r.status == FAIL for i in r.items]
            if best is None or len(faults) < len(best[1]):
                if best is not None:
                    notes.append(f"Connected twice: the first attempt had {len(best[1])} "
                                 f"fault(s), the second has {len(faults)}.")
                best = (doc, faults, attempt)
            else:
                notes.append("A second attempt was no better, so the first is kept.")
            if not faults or attempt == 2 or nothing_to_ask:
                break
            feedback = ("\n\nYour last wiring had these faults. Fix every one and "
                        f"give the whole {'answer' if choices is not None else 'cable list'} "
                        "again:\n"
                        + "\n".join(f"- {f}" for f in faults[:12]))
        spare = harness.left_optional(asked) if compact else []
        if spare:
            notes.append("Left unwired, because the library says each part works without "
                         "them: " + "; ".join(spare) + ". Wire one yourself if the project "
                         "needs what it does.")
        return best[0], notes + moved.get(best[2], []), degraded, None

    def _constrained(self) -> bool:
        """Ask for constrained JSON where code can then do the writing?

        Only with a router that can constrain a reply, and unless the
        owner has switched it off (engine.constrain_output: false), which
        restores the old ask-for-the-whole-file behaviour.
        """
        return bool(self.cfg.get("engine.constrain_output", True)
                    and getattr(self.router, "supports_schema", False))


    # ----------------------------------------------------------------
    # 5. enclosure
    # ----------------------------------------------------------------

    def stage_concept(self) -> StageResult:
        """The Artist: two concepts of the enclosure, drawn from geometry the
        enclosure step can build, for the owner to choose from (and change)
        before the Designer models it. Passes only once a choice is made."""
        brief = self.p.load_brief()
        parts = self._parts(brief)
        from .review import shape_asked
        shaped = shape_asked(brief)
        if shaped:
            return self._painted_concepts(brief, shaped)
        hw = self.cfg.get("hardware", {})
        try:
            box = enclosure.box_for(brief.envelope_mm, hw)
            sig = concept.signature(parts, box)
            drawn = concept.load(self.p.root, sig)
            fresh = not drawn
            if fresh:
                drawn = concept.make(parts, box)
                concept.save(self.p.root, drawn, sig, box, parts)
        except enclosure.EnclosureError as exc:
            return StageResult("concept", False, notes=[
                f"No enclosure can be drawn: {exc}",
                "Change the envelope or the parts in the brief."], go_back_to="brief")
        d = concept.folder(self.p.root)
        results = [Result("concepts", checks.PASS,
                          ("two concepts drawn" if fresh else
                           "two concepts, drawn earlier for these parts and this box"),
                          [f"{c.key}: {c.title}. " + " ".join(c.said) for c in drawn])]
        if fresh or not all((d / f"{c.key}-iso.png").exists() for c in drawn):
            results.append(self._concept_pictures(drawn, parts, box))
        pick = concept.chosen(self.p.root, sig)
        if pick:
            results.append(Result("concept_choice", checks.PASS, concept.describe(pick)))
        else:
            results.append(Result("concept_choice", FAIL, "no concept chosen yet", [
                "Choose A or B, and any changes: Choose a concept, on the Build tab, "
                "or: nemo concept choose A",
                "The Designer models the enclosure only after a choice."]))
        self.p.commit("concept", "concepts drawn")
        files = sorted(d.glob("*.svg")) + sorted(d.glob("*-iso.png"))
        return StageResult("concept", bool(pick), results, files)

    def _painted_concepts(self, brief, shaped: str) -> StageResult:
        """A shaped object (a replica, a prop): two concepts built by code
        from its anatomy (nemo/anatomy.py; owner, 2026-11-04: "remove
        blockout"), each drawn as a blueprint (front, top, side and isometric
        views, dimensioned; pieces and joints where it is too big to print
        whole), for the owner to choose from. The one chosen is built by the
        Art Studio's Designer and checked by its Editor."""
        from . import anatomy
        sig = concept.painted_signature(brief)
        drawn = concept.load(self.p.root, sig)
        fresh = not drawn
        if fresh:
            # Built by code from the object's anatomy (owner, 2026-11-04: "remove
            # blockout"): the model is not asked. An object Nemo's code does not
            # know is said, not guessed.
            try:
                drawn = concept.make_built(brief)
            except anatomy.UnknownObject as exc:
                return StageResult("concept", False, [Result(
                    "concepts", FAIL, "no concept can be built for this object", [
                        str(exc) + ".",
                        "Give the brief's real size (long x wide x high, mm) and, for its "
                        "kind, its own figures; or model the shape in the Art Studio or a "
                        "CAD program and say a tray is fine."])])
            # Anything drawn for this project before is not its concepts now.
            d = concept.folder(self.p.root)
            for old in [*d.glob("*-iso.png"), *d.glob("*-plan.svg"), *d.glob("*-render.txt"),
                        *d.glob("*-painted.png"), *d.glob("*-views.png"),
                        *d.glob("*-sketch.png"), *d.glob("*-blueprint.png"),
                        *d.glob("*-joints.json")]:
                old.unlink(missing_ok=True)
            concept.save_painted(self.p.root, drawn, sig)
        else:
            concept.ensure_blueprints(self.p.root, drawn)
        results = [Result("concepts", checks.PASS,
                          "two blueprints of the object" + ("" if fresh else ", from earlier"),
                          [f"The brief asks for a shape ('{shaped}'). Nemo's code built it "
                           "from the object's parts with the Art Studio's kit of shapes, "
                           "drawn as a blueprint: "
                           "front, top and side at one scale, its size dimensioned, an "
                           "isometric view, and any shape hidden inside another dashed; the "
                           "one you choose is what the Designer builds."]
                          + [f"{c.key}: {c.title}. " + " ".join(c.said) for c in drawn])]
        pick = concept.chosen(self.p.root, sig)
        files = [concept.picture(self.p.root, c) for c in drawn]
        if pick:
            results.append(Result("concept_choice", checks.PASS, concept.describe(pick)))
            chosen = next(c for c in drawn if c.key == pick.concept)
            built = self._build_blockout(brief, chosen, pick)
            results += built[0]
            files += built[1]
        else:
            results.append(Result("concept_choice", FAIL, "no blueprint chosen yet", [
                "Choose A or B, and say what to change: Choose a concept, on the Build "
                "tab, or: nemo concept choose A --changes \"...\""]))
        self.p.commit("concept", "blueprints drawn")
        return StageResult("concept", bool(pick), results,
                           [f for f in files if Path(f).is_file()])

    def _build_blockout(self, brief, chosen, pick) -> tuple[list, list]:
        """The Art Studio's Designer builds the chosen blockout with its kit
        (nemo/modelkit.py) and its Editor checks it; once per choice."""
        from . import blockout, modelkit
        doc = blockout.buildable(chosen.spec)
        doc["name"] = f"{brief.name or 'object'} {pick.concept}"
        out = modelkit.folder(self.cfg, doc["name"])
        same = False
        try:
            same = json.loads((out / "spec.json").read_text(encoding="utf-8"))["shapes"] == doc["shapes"]
        except (OSError, ValueError, KeyError):
            pass
        if same and (out / "checks.json").is_file():
            saved = json.loads((out / "checks.json").read_text(encoding="utf-8"))
            results = [Result(c["name"], c["status"], c["detail"], c.get("items", [])) for c in saved]
        else:
            print(f"Art Studio Designer: building concept {pick.concept}.", flush=True)
            out, results = modelkit.build(self.cfg, {"name": doc["name"], "shapes": doc["shapes"]})
            (out / "split-checks.json").unlink(missing_ok=True)       # made for other shapes
        results = list(results)
        results += self._split_if_too_long(doc["name"], out, results,
                                           concept.joints_plan(self.p.root, pick.concept))
        note = Result("designer_model", checks.PASS, f"built by the Art Studio's Designer: {out}",
                      ["Change it in the Art Studio, or: nemo model build "
                       f"{concept.folder(self.p.root) / (pick.concept + '-spec.json')}"]
                      + ([f"Your changes, for the Designer: {pick.notes}"] if pick.notes else []))
        files = [p for p in (out / "model-iso.png", out / "iso.png", out / "model.stl") if p.is_file()]
        files += [p for p in (out / "pieces" / "ASSEMBLY.txt",) if p.is_file()]
        return [note] + results, files

    def _split_if_too_long(self, name: str, out: Path, results: list, plan=None) -> list:
        """Full size and bigger than the printer: the Designer splits it into
        pieces that fit, pinned (nemo/joints.py), once per build, with the
        concept's own plan where it has one (the pieces and pins its blueprint
        shows); the whole model's fits_printer check then says it is built in
        pieces."""
        from . import joints
        fits = next((r for r in results if r.name == "fits_printer"), None)
        if not fits or fits.status != FAIL or (plan is None and not any("split" in i
                                                                     for i in fits.items)):
            return []
        saved = out / "split-checks.json"
        same_plan = True
        if plan is not None:                       # made with this very plan, or made again
            from dataclasses import asdict
            try:
                same_plan = json.loads((out / "joints.json").read_text(encoding="utf-8")) == \
                    json.loads(json.dumps(asdict(plan)))
            except (OSError, ValueError):
                same_plan = False
        if saved.is_file() and same_plan:
            got = [Result(c["name"], c["status"], c["detail"], c.get("items", []))
                   for c in json.loads(saved.read_text(encoding="utf-8"))]
        else:
            print("Art Studio Designer: too long to print whole; splitting it.", flush=True)
            try:
                got = joints.split(self.cfg, name, given=plan)[1]
            except (OSError, ValueError) as exc:                  # SplitError is a ValueError
                return [Result("pieces_made", FAIL, f"could not be split: {exc}")]
        if got and all(r.status != FAIL for r in got):
            i = results.index(fits)
            results[i] = Result("fits_printer", checks.PASS,
                                f"whole, {fits.detail}; built in pieces that each fit",
                                [f"In {out / 'pieces'}: ASSEMBLY.txt says how they go together."])
        return got

    def _concept_pictures(self, drawn, parts: list[Part], box) -> Result:
        """Each concept built in CadQuery and rendered, so the picture is the
        model. SKIP, saying why, where CadQuery or numpy is missing: the
        floor plans are drawn either way."""
        from . import render
        made, why = [], []
        for c in drawn:
            work = concept.folder(self.p.root) / c.key
            work.mkdir(parents=True, exist_ok=True)
            script = work / "housing.py"
            script.write_text(enclosure.cadquery_script(c.layout(), parts, box, c.corners,
                                                        c.notch_wall), encoding="utf-8")
            built = checks.generate_enclosure(script, work / "housing.stl")
            if built.status != checks.PASS:
                why.append(f"{c.key}: {built.detail}")
                continue
            try:
                render.render_stl(work / "housing.stl", concept.folder(self.p.root),
                                  views=["iso"], size=420, name=c.key)
                made.append(c.key)
            except render.RenderError as exc:
                why.append(f"{c.key}: {exc}")
        if len(made) == len(drawn):
            return Result("concept_pictures", checks.PASS,
                          "each concept built in CadQuery and drawn from the model")
        return Result("concept_pictures", checks.SKIP,
                      "pictures of the model could not be made; the floor plans show "
                      "the layouts", why)

    def _concept_line(self, parts: list[Part], brief) -> str:
        """The build guide's word on which concept was built."""
        pick = concept.chosen(self.p.root, concept.current_signature(brief, parts))
        return (concept.describe(pick) + " (concept/ has its pictures)" if pick else
                "no concept was chosen for these parts and this size")

    def stage_enclosure(self) -> StageResult:
        brief = self.p.load_brief()
        skip = self._not_needed("enclosure", brief)
        if skip:
            return skip
        parts = self._parts(brief)
        hw = self.cfg.get("hardware", {})
        dims = "\n".join(
            f"- {p.ref}: {p.size_mm} mm, mount={p.mount}. {p.notes.strip()}"
            for p in parts)

        notes: list[str] = []
        self.p.housing_script.parent.mkdir(parents=True, exist_ok=True)
        self._drawing = None          # set by _lay_out_enclosure (nemo/drawings.py)
        if self._constrained():
            # The model decides where each part sits and nothing else;
            # enclosure.py checks that and writes the CadQuery.
            written = self._lay_out_enclosure(brief, parts, hw)
            if isinstance(written, StageResult):
                return written
            notes, degraded = written
        else:
            text, degraded = self._ask(
                "cad_script", "enclosure",
                f"{brief.function}\n\nEnvelope: {brief.envelope_mm} mm\n"
                f"Constraints: {brief.constraints}\n\nParts:\n{dims}",
                printer=hw.get("printer"), nozzle=hw.get("nozzle_mm"),
                min_wall=hw.get("min_wall_mm"),
                overhang=hw.get("supportless_overhang_deg"),
                volume=hw.get("build_volume_mm"))
            self.p.housing_script.write_text(self._extract(text, "python"), encoding="utf-8")

        # D131: run it. The mesh checks below only mean something if the
        # mesh is the one this script just made.
        generated = checks.generate_enclosure(self.p.housing_script, self.p.housing_stl)
        results = [generated]
        if generated.status == checks.PASS:
            results += [
                checks.solid(self.p.housing_stl),
                checks.thickness(self.p.housing_stl,
                                 float(hw.get("min_wall_mm", 1.2))),
            ]
        # D153: asked only where there is something to ask about. With no
        # panel-mounted part this was a skip, and so an "unchecked" line in
        # every guide for a check that had nothing it could have checked.
        if any(p.mount == "panel" for p in parts):
            results.append(checks.xref_cutouts(parts,
                                               self._cutouts(self.p.housing_script)))
        if self._drawing is not None:
            results.append(self._drawing)
        layout =self.p.housing_script.parent / "layout.json"
        if enclosure.keep_apart_pairs(parts) and layout.exists():
            results.append(self.check_keep_apart(layout, parts))
        ok = all(r.ok for r in results)
        self.p.commit("enclosure", "housing generated")
        back = None
        if not ok:
            # The script failing, or its mesh failing, is this step's own
            # output. Cut-outs that do not match the parts is a parts matter.
            own = any(not r.ok for r in results
                      if r.name in ("enclosure_script", "solid", "thickness", "drawing"))
            back = "enclosure" if own else "parts"
            if not own and any(not r.ok for r in results if r.name == "keep_apart"):
                back = "brief"             # the envelope is too small for it
        return StageResult("enclosure", ok, results,
                           [self.p.housing_script], notes=notes, degraded=degraded,
                           go_back_to=back)

    @staticmethod
    def check_keep_apart(layout: Path, parts: list[Part]) -> Result:
        """Parts the library says must be kept apart are, in the layout
        that was actually written (enclosure/layout.json). Edge to edge of
        the two footprints, which is the cautious reading of a distance
        between two parts."""
        need = enclosure.keep_apart_pairs(parts)
        if not need:
            return Result("keep_apart", checks.SKIP, "no parts here must be kept apart")
        try:
            placed = enclosure.placed_from(
                json.loads(layout.read_text(encoding="utf-8", errors="replace")), parts)
        except (OSError, json.JSONDecodeError, enclosure.EnclosureError) as exc:
            return Result("keep_apart", checks.SKIP, f"the layout could not be read ({exc})")
        got = {tuple(sorted((a, b))): d for a, b, d in enclosure.gaps(placed)}
        by_ref = {p.ref: p for p in parts}
        bad, fine = [], []
        for a, b, mm in need:
            d = got.get((a, b))
            if d is None:
                continue
            line = f"{a} and {b}: {d:g} mm apart, at least {mm:g} mm needed"
            if d < mm - enclosure.EPS:
                why = next((by_ref[r].notes.strip() for r in (a, b)
                            if by_ref[r].keep_apart and by_ref[r].notes.strip()), "")
                bad.append(line + (f". {why}" if why else ""))
            else:
                fine.append(line)
        if bad:
            return Result("keep_apart", FAIL,
                          f"{len(bad)} pair(s) of parts too close together", bad + fine)
        return Result("keep_apart", checks.PASS,
                      f"{len(fine)} pair(s) far enough apart", fine)

    def _lay_out_enclosure(self, brief: Brief, parts: list[Part], hw: dict):
        """Write housing.py from a layout. Returns (notes, degraded), or a
        failed StageResult when no enclosure can be drawn at all.

        The model is asked for the order of the parts along the box; code
        packs them in that order. If no usable order comes back, or the
        parts will not pack in it, code's own order is used and the step
        says so: that order knows nothing of which part the brief wants
        kept away from which.
        """
        try:
            box = enclosure.box_for(brief.envelope_mm, hw)
            fallback = enclosure.auto_layout(parts, box)   # also proves the parts can fit
        except enclosure.EnclosureError as exc:
            return StageResult("enclosure", False, notes=[
                f"No enclosure can be drawn: {exc}",
                "Change the envelope or the parts in the brief."], go_back_to="brief")

        # The model chooses the order of the parts along the box; code does
        # the geometry. Asked for positions it overlapped all three parts,
        # twice (see enclosure.auto_layout).
        # The owner's pick from the Artist's concepts (nemo/concept.py), if
        # it was made for these parts in this box. Its style is applied as
        # chosen; its layout is used as it is unless the owner asked for a
        # change in where parts go, which is then the model's to weigh.
        sig = concept.signature(parts, box)
        pick = concept.chosen(self.p.root, sig)
        drawn = {c.key: c for c in concept.load(self.p.root, sig)} if pick else {}
        style = (pick.corners, pick.notch_wall) if pick else ("square", "left")
        owner_said = (f"\nThe owner, choosing concept {pick.concept}: {pick.notes}"
                      if pick and pick.notes else "")
        user = (f"{brief.function}\n\n{enclosure.part_facts(parts, box)}"
                f"{constraints_text(brief)}{owner_said}")
        notes: list[str] = []
        degraded, placed = False, None
        used_order: list[str] = []
        if pick:
            notes.append("Built as chosen: " + concept.describe(pick))
            c = drawn.get(pick.concept)
            if c is not None and not pick.notes:
                laid = c.layout()
                if not enclosure.faults(laid, box):
                    placed, used_order = laid, list(c.order)
        # D172. The order is the model's to choose only where the brief
        # says something about it. With no constraint there is nothing for
        # it to weigh: what warms what, and what the library says must be
        # kept apart, are decided by code below either way. On the real
        # machine that question was 485 tokens read at 1.15 a second, seven
        # minutes, for an order code then replaced.
        asked = bool([c for c in (brief.constraints or []) if str(c).strip()]) or bool(owner_said)
        if placed is not None:
            asked = False           # the owner chose this layout, seeing it
        text = ""
        if asked:
            text, degraded = self._ask("cad_script", "enclosure_json", user,
                                       schema=enclosure.order_schema(parts), max_tokens=120)
        try:
            if placed is not None:
                raise StopIteration
            if not asked:
                raise LookupError
            order = enclosure.order_from(harness.parse_reply(text), parts)
            placed = enclosure.auto_layout(parts, box, order)
            used_order = order
            notes.append("Order along the box, chosen by the model: "
                         + ", ".join(order) + ".")
        except StopIteration:
            pass
        except LookupError:
            if parts:
                notes.append("The brief has no constraint about where a part goes, so the "
                             "model was not asked for an order: the parts are in Nemo's own, "
                             "largest first.")
        except harness.HarnessError:
            notes.append("No usable order came back, so the parts are in Nemo's own "
                         "order, largest first. That knows nothing of the brief's "
                         "constraints about which part goes near or far from which.")
        except enclosure.EnclosureError as exc:
            notes.append(f"The model's order could not be used ({exc}), so the parts "
                         "are in Nemo's own order, largest first. That knows nothing of "
                         "the brief's constraints about which part goes near or far "
                         "from which.")
        if placed is None:
            placed = fallback
        # One thing about the order is physics, not preference, and is
        # checked: a temperature sensor beside the part that warms the box.
        apart_order = enclosure.thermal_order(parts)
        if apart_order is not None:
            try:
                better = enclosure.auto_layout(parts, box, apart_order)
            except enclosure.EnclosureError:
                better = None
            now = enclosure.nearest_sensor_gap(placed, parts)
            best = enclosure.nearest_sensor_gap(better, parts) if better else None
            if now and best and best[2] > now[2] + 0.5:
                notes.append(
                    f"That order put {now[0]} {now[2]:g} mm from {now[1]}, which draws "
                    f"the most current and will warm it. Nemo's own order keeps them "
                    f"{best[2]:g} mm apart, so that is used instead: "
                    + ", ".join(apart_order) + ".")
                placed, used_order = better, apart_order
        # And one thing is the parts library's: two parts it says must be a
        # given distance apart (D142). The tag player's reader and speaker
        # were 4.4 mm apart under a note that said 25.
        short = enclosure.too_close(placed, parts)
        if short:
            by_ref = {p.ref: p for p in parts}
            said = "; ".join(f"{a} and {b} at least {mm:g} mm (they were {got:g})"
                             for a, b, mm, got in short)
            again, order2, shortfall = enclosure.layout_keeping_apart(
                parts, box, [used_order, apart_order or []])
            if again is not None:
                did = ("kept that order and pushed the end of each row to the far "
                       "wall." if order2 == used_order else
                       "laid the parts out again: " + ", ".join(order2) + ".")
                placed, used_order = again, order2
                notes.append(f"The parts library says to keep {said} apart, so Nemo {did}")
            else:
                why = " ".join(sorted({by_ref[r].notes.strip() for a, b, _, _ in short
                                       for r in (a, b) if by_ref[r].keep_apart}))
                notes.append(f"The parts library says to keep {said} apart ({why}) and no "
                             "layout of these parts in this envelope does it: the best "
                             f"found is {shortfall:g} mm short. Make the envelope larger.")
        chosen = {a.ref: {"x_mm": a.x, "y_mm": a.y,
                          "turned": a.dx != next(p.size_mm[0] for p in parts
                                                 if p.ref == a.ref)}
                  for a in placed}
        apart = enclosure.gaps(placed)
        if apart:
            notes.append("Edge to edge: " + "; ".join(
                f"{a} to {b} {d:g} mm" for a, b, d in apart[:8]) + ".")
        (self.p.housing_script.parent / "layout.json").write_text(
            json.dumps(chosen, indent=2), encoding="utf-8")
        self.p.housing_script.write_text(
            enclosure.cadquery_script(placed, parts, box, corners=style[0],
                                      notch_wall=style[1]), encoding="utf-8")
        # A dimensioned drawing of the same layout and cuts (CADCraft), checked
        # by reading it back; a check of this step (stage_enclosure).
        self._drawing = drawings.enclosure_drawing(
            self.p.housing_script.parent, placed, parts, box, style[0], style[1],
            self.p.root.name)
        if self._drawing is None:
            notes.append(drawings.NOT_INSTALLED)
        notes.append("An open tray with a locating rim for each part. No lid and no "
                     "screw standoffs are drawn: the parts library does not record "
                     "mounting-hole positions." if parts else
                     "No parts: a plain open tray of the brief's inside size, with no "
                     "cable notch. No lid is drawn.")
        return notes, degraded

    @staticmethod
    def _cutouts(script: Path) -> set[str]:
        """Cutouts are named by convention: cutout_<partref> in the script."""
        if not script.exists():
            return set()
        found = set()
        for line in script.read_text(encoding="utf-8", errors="replace").splitlines():
            if "cutout_" in line:
                for token in line.replace("(", " ").replace("=", " ").split():
                    if token.startswith("cutout_"):
                        found.add(token[len("cutout_"):].strip(" ,):"))
        return found

    # ----------------------------------------------------------------
    # 6. firmware
    # ----------------------------------------------------------------

    def stage_firmware(self, max_rounds: int = 3) -> StageResult:
        brief = self.p.load_brief()
        skip = self._not_needed("firmware", brief)
        if skip:
            return skip
        parts = self._parts(brief)
        if self._constrained():
            doc = self._saved_connections(parts)
            if doc is not None:
                written = self._bring_up_firmware(brief, parts, doc)
                if written is not None:
                    return written
            elif self._electrical_failed() and pio_board(brief.mcu).startswith("esp32"):
                # D165: with no connections this fell back to asking the
                # model for the whole file. On the real machine that was 66
                # minutes for three builds that failed, of code that wrote
                # made-up registers to an amplifier that has no bus.
                return StageResult("firmware", False, notes=[
                    "There are no connections to write the firmware from: the "
                    "electrical step did not produce them. The model was not asked "
                    "to write it without them. Run the electrical step first."],
                    go_back_to="electrical")
        pinout = self.p.root / "electrical" / "netlist.net"
        pin_text = (pinout.read_text(encoding="utf-8", errors="replace")[:4000] if pinout.exists()
                    else "netlist not exported; pin assignments unavailable")
        # The wiring harness says which pin of the microcontroller each
        # module's pin is on. The firmware step never saw it: with no
        # netlist, which is the usual case, the model was told the netlist
        # was authoritative and given nothing, and on the real laptop it
        # made the pin numbers up.
        wiring = self._wiring_for_firmware(parts)

        notes, results, degraded = [], [], False
        feedback = ""
        tools_failed = False
        for round_no in range(1, max_rounds + 1):
            text, deg = self._ask(
                "firmware", "firmware",
                f"{brief.function}\n\nMCU: {brief.mcu}\n"
                f"Parts: {[p.ref for p in parts]}\n\n"
                f"Netlist (authoritative for pins):\n{pin_text}\n"
                f"{wiring}"
                f"{constraints_text(brief)}"
                f"{feedback}")
            degraded = degraded or deg
            self._write_pio(self._extract(text, "cpp"), brief)

            result = checks.compile_firmware(self.p.firmware)
            if result.status != FAIL:
                results = [result]
                notes.append(f"built on round {round_no}")
                if result.status == checks.PASS:
                    # A real build is the proof 'nemo offline' asks for.
                    from .offline import record_build
                    record_build(pio_board(brief.mcu), True)
                break
            if result.detail == TOOLS_FAILED:
                # D126: nothing the model can fix. Asking again costs a
                # quarter of an hour a round on this hardware.
                results = [result]
                notes.append(f"round {round_no}: the build tools could not "
                             "run; stopped without asking the model again")
                tools_failed = True
                break
            notes.append(f"round {round_no}: build failed, feeding errors "
                         "back")
            feedback = ("\n\nThe previous attempt failed to compile with "
                        "these errors. Fix them:\n" + "\n".join(result.items)
                        + self._missing_header_advice(result.items))
            results = [result]

        ok = all(r.ok for r in results)
        self.p.commit("firmware", f"{len(notes)} round(s)")
        return StageResult("firmware", ok, results,
                           [self.p.firmware / "src" / "main.cpp"],
                           notes=notes, degraded=degraded,
                           # A tool that will not start is not fixed by
                           # going back to the schematic.
                           go_back_to=("electrical" if not ok and not tools_failed
                                       else None))

    def _bring_up_firmware(self, brief: Brief, parts: list[Part],
                           doc: dict) -> StageResult | None:
        """Write the firmware from the connections instead of asking for it.

        See firmware.py. The model makes one bounded choice, how often the
        project updates; code writes the file. Returns None where no such
        firmware can be written yet (a board that is not an ESP32), so the
        caller falls back to asking the model for the whole file.
        """
        board = pio_board(brief.mcu)
        if not board.startswith("esp32"):
            return None
        notes = ["Bring-up firmware written by Nemo from the connections: pins, "
                 "serial banner, bus set-up (with a scan of the I2C bus where "
                 "there is one) and a non-blocking loop. "
                 "Each part's own logic is NOT generated; its function is empty."]
        degraded = False
        update_ms = firmware.DEFAULT_UPDATE_MS
        stated = firmware.interval_from_text(f"{brief.done_when} {brief.function}")
        if stated is not None:
            # The brief says how often. That is read, not asked for.
            update_ms = stated[0]
            notes.append(f"Updates every {update_ms} ms: the brief says "
                         f"\"{stated[1]}\".")
        else:
            # D172. The model used to be asked. With nothing in the brief to
            # go on its answer was a guess (1000 ms, both real runs), and the
            # asking was three minutes: 188 tokens read for 12 written.
            notes.append(f"Updates every {update_ms} ms, Nemo's own figure: the brief does "
                         "not state an interval. Say how often in the brief (\"every ten "
                         "seconds\") and it is read from there.")
        try:
            source = firmware.scaffold(doc, parts, brief.name, board, update_ms)
        except (firmware.FirmwareError, schematic.SchematicError) as exc:
            return StageResult("firmware", False, notes=[
                f"A firmware could not be written from the connections: {exc}",
                "Fix the connections in the electrical step and run it again."],
                degraded=degraded, go_back_to="electrical")
        self._write_pio(source, brief)
        result = checks.compile_firmware(self.p.firmware)
        if result.status == checks.PASS:
            from .offline import record_build
            record_build(board, True)
        self.p.commit("firmware", "bring-up firmware written")
        return StageResult("firmware", result.ok, [result],
                           [self.p.firmware / "src" / "main.cpp"], notes=notes,
                           degraded=degraded,
                           go_back_to=None if result.ok or result.detail == TOOLS_FAILED
                           else "firmware")

    def _wiring_for_firmware(self, parts: list[Part]) -> str:
        doc = self._load_harness(self.p.harness)
        pairs = self._wire_pairs(doc) if doc else []
        if not pairs:
            return ""
        lines = [f"- {a}.{pa} is wired to {b}.{pb}" for (a, pa), (b, pb) in pairs]
        return ("\nWiring harness (authoritative for pins where the netlist "
                "does not give them). Use exactly these pins:\n"
                + "\n".join(lines[:60]) + "\n")

    @staticmethod
    def _missing_header_advice(errors: list[str]) -> str:
        """What to tell the model when it included a header that is not there.

        On the real laptop it included SSD1306_OLED.h, was told "No such
        file or directory", and included it again, three rounds running.
        The compiler's message does not say what IS there.
        """
        missing = sorted({m.group(1) for e in errors
                          for m in [re.search(r"fatal error: ([\w./-]+\.h(?:pp)?): "
                                              r"No such file or directory", e)] if m})
        if not missing:
            return ""
        return ("\n\n" + ", ".join(missing) + (" is" if len(missing) == 1 else " are")
                + " not installed, and no library will be added for you. Remove "
                "every such #include. The only headers you may use are Arduino.h, "
                "Wire.h and SPI.h. Talk to each part directly over its bus with "
                "Wire or SPI, using the register addresses from its datasheet.")

    def _write_pio(self, source: str, brief: Brief) -> None:
        src = self.p.firmware / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "main.cpp").write_text(source, encoding="utf-8")
        ini = self.p.firmware / "platformio.ini"
        if not ini.exists():
            from .offline import platform_for     # pinned (D196); a pico is not an ESP32
            board = pio_board(brief.mcu)
            ini.write_text(
                f"[env:{board}]\nplatform = {platform_for(board)}\nboard = {board}\n"
                "framework = arduino\nmonitor_speed = 115200\n"
                "build_type = release\n", encoding="utf-8")

    # ----------------------------------------------------------------
    # 7. pack
    # ----------------------------------------------------------------

    def stage_pack(self, prior: list[StageResult]) -> StageResult:
        brief = self.p.load_brief()
        parts = self._parts(brief)
        hw = self.cfg.get("hardware", {})

        unresolved = list(brief.open_questions)
        # Read the persisted findings if this run did not compute them, so
        # packing on its own still lists every safety sign-off. Only the
        # ones the user has not actually given, though: this used to list
        # every signoff-severity finding unconditionally, never once
        # checking signoffs.json -- the file the Sign-off tab writes to --
        # so nothing recorded there could ever remove an item from here.
        given = self.p.given_signoffs()
        from .results import load_safety
        pending = ([(f.rule, f.detail) for f in signoffs(self._safety)]
                   or [(f["rule"], f["detail"]) for f in load_safety(self.p.root)
                       if f.get("severity") == "signoff"])
        for rule, detail in pending:
            # An unreadable record is never signed away: only a new check clears it.
            if f"safety_{rule}" not in given or rule == "record_unreadable":
                unresolved.append(f"[safety] {rule}: {detail}")
        for sr in prior:
            for r in sr.results:
                if r.status == checks.SKIP:
                    unresolved.append(f"[{sr.stage}] unchecked: {r.name} "
                                      f"-- {r.detail}")
                elif r.status == FAIL:
                    unresolved.append(f"[{sr.stage}] FAILED: {r.name} "
                                      f"-- {r.detail}")
            if sr.degraded:
                unresolved.append(f"[{sr.stage}] produced by the local model "
                                  "without review -- check it yourself")

        # What each step said about its own output. On the first run where
        # every step passed, the firmware was a bring-up firmware with each
        # part's logic left empty, and the enclosure layout was Nemo's own
        # after the model's was unsound twice. Both were said on screen and
        # neither reached this guide, which is what the owner builds from.
        from .results import load_results
        saved = load_results(self.p.root)
        this_run = {sr.stage: list(sr.notes) for sr in prior}
        reported = []
        for stage in ("electrical", "wiring", "enclosure", "firmware"):
            notes = this_run.get(stage)
            if notes is None:
                notes = (saved.get(stage) or {}).get("notes") or []
            reported += [f"- [{stage}] {n}" for n in notes]

        lines = [
            f"# {brief.name}", "",
            f"_Generated by Nemo on {self.p.stamp()}. "
            "Nothing here has been built or tested._", "",
            "## What it does", "", brief.function, "",
            "## Bill of materials", "",
            "| ref | part | peak mA |", "|---|---|---|",
        ]
        lines += [f"| {p.ref} | {p.name} | {p.draw_ma:.0f} |" for p in parts]
        lines += [
            "", "## Print settings", "",
            f"- Printer: {hw.get('printer')}",
            f"- Nozzle {hw.get('nozzle_mm')} mm, layer "
            f"{hw.get('layer_mm')} mm",
            f"- Minimum wall {hw.get('min_wall_mm')} mm",
            "- No supports required if the enclosure gate passed",
            "- The case: " + self._concept_line(parts, brief), "",
            "## Wiring order", "",
        ]
        # D154: an adjustable converter comes out of its bag at whatever it
        # was last set to. The first battery designs through the pipeline had
        # one feeding the board's 5 V pin, and this guide never said to set it.
        steps = [f"Before {p.ref} is wired to anything else, power it on its own and set "
                 f"its output to {max(p.output_v):g} V with a meter. It gives whatever it "
                 "was last adjusted to, which may be far more."
                 for p in parts if p.category == "power" and p.output_v]
        steps += ["Check continuity on the harness before powering anything.",
                  "Connect grounds first.",
                  "Bring up the supply with no modules attached and confirm "
                  "each rail with a meter.",
                  "Attach modules one at a time, checking current draw."]
        chain = harness.supply_chain(parts)
        if chain and len(chain) > 1:
            steps.append(f"Connect {chain[0].ref} last of all, and only to {chain[1].ref}: "
                         "its negative lead must not go to the common ground.")
        lines += [f"{n}. {text}" for n, text in enumerate(steps, 1)]
        noted = [p for p in parts if (p.notes or "").strip()]
        if noted:
            lines += ["", "## Notes on the parts", "",
                      "_From the parts library, in its own words._", ""]
            lines += [f"- **{p.ref}**: {' '.join(p.notes.split())}" for p in noted]
        lines += [
            "",
            "## Flashing", "", "```", "cd firmware && pio run -t upload",
            "```", "", "## Test procedure", "", brief.done_when or
            "_Not specified in the brief._", "",
            "## What each step did, and did not do", "",
        ]
        lines += reported or ["- Nothing recorded."]
        # D140: a constraint in the brief is a sentence, and no check reads
        # sentences. The tag player's brief said to keep the speaker magnet
        # 25 mm from the reader; they were placed 4.4 mm apart and this
        # guide said "Open questions: None recorded".
        for c in brief.constraints or []:
            unresolved.append(f"[brief] not checked by Nemo, confirm it yourself: {c}")
        # A levels check can pass with wires it could not rule on (D147),
        # and the pin-current check can only ever ask (D160).
        for asks in ("harness_levels", "pin_current"):
            levels = next((r for sr in prior if sr.stage == "electrical"
                           for r in sr.results if r.name == asks), None)
            if levels is None:
                saved_levels = [r for r in (saved.get("electrical") or {}).get("checks", [])
                                if r.get("name") == asks]
                if saved_levels and saved_levels[0].get("status") == "PASS":
                    unresolved += [f"[electrical] confirm: {i}"
                                   for i in saved_levels[0].get("items", [])]
            elif levels.status == checks.PASS:
                unresolved += [f"[electrical] confirm: {i}" for i in levels.items]
        from . import named
        absent = named.question(named.named_but_absent(brief, parts))    # D162
        if absent:
            unresolved.append(f"[parts] {absent}")
        extras, bad_extras = named.extra_loads(brief)
        unresolved += [f"[parts] {named.extra_question(n, ma)}" for n, ma in extras]
        unresolved += [f"[parts] in the brief's extra_loads, {b}: it is not counted"
                       for b in bad_extras]
        # D159: the switched side of a relay is nobody's unless this says so.
        for p in parts:
            switched = harness.contact_pins(p)
            if switched:
                unresolved.append(
                    f"[electrical] not wired by Nemo: {p.ref} {', '.join(switched)}, its "
                    "switched side. What it switches is not in the parts list, its current "
                    "is not in the power budget, and no check here has looked at it")
        lines += ["", "## Open questions", ""]
        lines += ([f"- {q}" for q in unresolved] if unresolved
                  else ["- None recorded."])
        lines += ["", "---", "",
                  "Review every open question above before printing, "
                  "ordering, or connecting a battery."]

        self.p.build_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # The guide and the drawing as one PDF to print (WordCraft, if installed).
        from . import books
        pdf, said = books.pack_pdf(self.p.root)
        self.p.commit("pack", "build guide written")
        # Finished: onto the Storeroom's Finished shelf (nemo/finished.py).
        from . import finished
        try:
            if finished.send(self.cfg, "workshop", self.p.root) is not None:
                said = (said + " " if said else "") + "Sent to the Storeroom's Finished shelf."
        except OSError:
            pass
        return StageResult("pack", True, artifacts=[self.p.build_md] + ([pdf] if pdf else []),
                           notes=[f"{len(unresolved)} open question(s)"] + ([said] if said else []))
