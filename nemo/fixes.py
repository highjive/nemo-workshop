"""Power suggestions and fixes for failed checks.

Two rules govern everything in this module.

  Nothing is applied without a person choosing it. Every function here
  returns suggestions; applying one is a separate, explicit call.

  A fix changes the design, never the rules. Suggestions edit the brief --
  a bigger supply, a larger enclosure, a part added, a constraint for the
  model -- and none of them touches the safety floor or policy. Where the
  only way past a check would be to loosen a safety rule, the suggestion is
  an explanation, not a change.

Everything is computed from the parts library and the check results, with
no language model, so the same design always produces the same suggestions.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field

# The margin the parts step requires between peak draw and the supply rating
# (checks.deterministic.current_sum). Suggestions must clear the same bar the
# check applies, or they would suggest supplies that then fail.
HEADROOM = 0.25


# ====================================================================
#  Power
# ====================================================================

@dataclass
class Supply:
    key: str
    label: str
    power: str            # what goes in the brief's "Power source"
    ma: float             # continuous rating
    primary_v: float
    battery: bool = False
    needs_parts: tuple = ()


STANDARD_SUPPLIES = [
    Supply("usb_05", "USB from a computer port", "USB 5 V 0.5 A", 500, 5.0),
    Supply("usb_1", "USB phone charger, 1 A", "USB 5 V 1 A", 1000, 5.0),
    Supply("usb_2", "USB charger, 2 A", "USB 5 V 2 A", 2000, 5.0),
    Supply("usbc_3", "USB-C charger, 3 A", "USB-C 5 V 3 A", 3000, 5.0),
]


@dataclass
class PowerOption:
    supply: Supply
    verdict: str          # recommended | enough | too small | not suitable
    margin: float         # fraction of the rating left at peak
    rails: list[float]
    runtime_h: float | None = None
    why: str = ""
    add_parts: list[str] = field(default_factory=list)


@dataclass
class PowerPlan:
    peak_ma: float
    typical_ma: float
    need_ma: float
    loads: list[tuple[str, float]]
    options: list[PowerOption]


def _loads(parts):
    return [p for p in parts if p and p.category != "power"]


def _rails_for(loads, primary: float, converters=()) -> tuple[list[float], list[str], list[tuple]]:
    """Rails a supply must provide, any loads it cannot feed even with a
    converter, and which loads are fed via a converter rather than
    directly.

    Each load takes the primary voltage if it accepts it, else 3.3 V from
    the microcontroller board's regulator when there is one, else the
    output of a converter in the library whose own output matches a
    voltage the load accepts.
    """
    rails, unfed, converted = {primary}, [], []
    has_regulator = any(p.category == "mcu" for p in loads)
    for p in loads:
        if not p.supply_v:
            continue
        if any(abs(v - primary) < 0.35 for v in p.supply_v):
            continue
        if has_regulator and any(abs(v - 3.3) < 0.2 for v in p.supply_v):
            rails.add(3.3)
            continue
        conv = next((c for c in converters if any(
            abs(ov - sv) < 0.2 for ov in c.output_v for sv in p.supply_v)), None)
        if conv:
            matched = next(ov for ov in conv.output_v
                          if any(abs(ov - sv) < 0.2 for sv in p.supply_v))
            rails.add(matched)
            converted.append((p, conv, matched))
            continue
        unfed.append(p.ref)
    return sorted(rails, reverse=True), unfed, converted


def _is_lipo_cell(p) -> bool:
    return p.category == "power" and "lipo" in (p.ref + p.name).lower()


def _converters(library):
    """Voltage converters in the library: anything in the power category
    with a declared output voltage. A cell has none; a charger has none;
    only something that actually steps a voltage up or down does."""
    return [p for p in library if p.category == "power" and p.output_v]


def _battery_supplies(library) -> list[Supply]:
    """One option per LiPo cell in the library, each paired with a
    protection circuit -- only if the library has one.

    The hard floor requires protection on any LiPo, so no option is built
    at all unless a charger/protection part is present. Matching the
    charger by NAME only, not notes: a cell's own safety note ("needs a
    protection circuit") mentions the word "protect" too, and matching
    notes text picked a second cell as its own charger once there was more
    than one cell in the library.
    """
    charger = next((p for p in library if p.category == "power"
                    and not _is_lipo_cell(p)
                    and re.search(r"protect|dw01|bms", p.name.lower())),
                   None)
    if not charger:
        return []
    out = []
    for cell in library:
        if not _is_lipo_cell(cell):
            continue
        m = re.search(r"(\d+)\s*mAh", cell.name)
        cap = float(m.group(1)) if m else cell.current_ma
        s = Supply(cell.ref, f"Battery: {cell.name}",
                   f"{int(cap)} mAh LiPo, USB charging", cell.current_ma, 3.7,
                   battery=True, needs_parts=(cell.ref, charger.ref))
        s.capacity_mah = cap                                  # type: ignore[attr-defined]
        out.append(s)
    return out


def battery_design(power: str, parts) -> bool:
    return bool(re.search(r"lipo|batter|mah", (power or "").lower())) or any(
        p and _is_lipo_cell(p) for p in parts)


def power_plan(parts, library, current_power: str = "") -> PowerPlan:
    loads = _loads(parts)
    peak = sum(p.draw_ma for p in loads)
    typical = sum(p.current_ma for p in loads)
    need = math.ceil(peak / (1 - HEADROOM)) if peak else 0
    supplies = list(STANDARD_SUPPLIES)
    supplies += _battery_supplies(library)
    converters = _converters(library)

    options = []
    for s in supplies:
        rails, unfed, converted = _rails_for(loads, s.primary_v, converters)

        # A load fed through a converter draws more from the primary
        # supply than its own rating, by the step in voltage and the
        # converter's loss: P in = P out / efficiency, I in = P in / V in.
        # O21: this used to not exist at all -- a design needing 5 V from
        # a cell was reported simply as "not suitable", and a converter
        # added to the parts list by hand was never reflected in the
        # runtime estimate, which silently overstated it.
        s_peak, s_typical = peak, typical
        conv_names = []
        for load, conv, out_v in converted:
            eff = conv.efficiency or 1.0
            extra_peak = load.draw_ma * out_v / (s.primary_v * eff)
            extra_typical = load.current_ma * out_v / (s.primary_v * eff)
            s_peak += extra_peak - load.draw_ma
            s_typical += extra_typical - load.current_ma
            if conv.ref not in conv_names:
                conv_names.append(conv.ref)
        s_need = math.ceil(s_peak / (1 - HEADROOM)) if s_peak else 0

        margin = 1 - s_peak / s.ma if s.ma else 0.0
        runtime = None
        if s.battery and s_typical:
            runtime = round(getattr(s, "capacity_mah", 0) / s_typical, 1)
        add_parts = list(s.needs_parts) + conv_names
        if unfed:
            names = ", ".join(unfed)
            verdict = "not suitable"
            why = (f"{names} cannot run from {s.primary_v:g} V, and there is "
                   "no converter for it in your parts library.")
        elif s.ma < s_need:
            verdict = "too small"
            why = (f"Gives {s.ma:.0f} mA; your parts need {s_need} mA once "
                   f"Nemo's {HEADROOM:.0%} safety margin is added.")
            if conv_names:
                why += (f" ({', '.join(conv_names)} already counted: stepping "
                        "up to feed a 5 V part costs more current than it draws.)")
        else:
            verdict = "enough"
            why = f"Leaves {margin:.0%} spare at peak draw."
            if conv_names:
                why += (f" Includes {', '.join(conv_names)} to feed a part "
                        "that needs a different voltage than the cell gives; "
                        "its conversion loss is in this figure.")
            if s.battery:
                why += (f" About {runtime:g} hours at typical draw. Adds the "
                        "cell and a protected charger to the parts.")
        options.append(PowerOption(s, verdict, margin, rails, runtime, why,
                                   add_parts))

    # Recommend only within the kind of power already chosen. A wearable
    # that runs on a battery is not fixed by a wall charger: if no supply of
    # the same kind is adequate, nothing is recommended and the plan says
    # why, rather than quietly changing what the device is.
    wants_battery = battery_design(current_power, parts)
    pool = [o for o in options if o.verdict == "enough"
            and o.supply.battery == wants_battery]
    if pool:
        best = min(pool, key=lambda o: o.supply.ma)
        best.verdict = "recommended"
    order = {"recommended": 0, "enough": 1, "too small": 2, "not suitable": 3}
    options.sort(key=lambda o: (order[o.verdict], o.supply.ma))
    return PowerPlan(peak, typical, need,
                     [(p.name, p.draw_ma) for p in loads], options)


def apply_power(brief, option: PowerOption):
    b = copy.deepcopy(brief)
    b.power = option.supply.power
    b.supply_ma = option.supply.ma
    b.rails = option.rails
    for ref in option.add_parts:
        if ref not in b.parts:
            b.parts.append(ref)
    return b


# ====================================================================
#  Fixes for failed checks
# ====================================================================

@dataclass
class Fix:
    key: str
    title: str
    why: str
    kind: str                     # change | info
    rerun: str = ""               # step to run after applying
    set_fields: dict = field(default_factory=dict)
    add_parts: list = field(default_factory=list)
    add_constraints: list = field(default_factory=list)
    # For advice whose remedy is a value only the owner can give: the
    # brief's field it goes in. The window then offers to open the brief
    # at that field instead of a greyed-out button.
    brief_field: str = ""
    # For a find the Researcher made online: the page to open.
    url: str = ""

    @property
    def changes(self) -> list[str]:
        """What applying this does to the brief, in the brief's own words."""
        def say(k, v):
            if k == "power":
                return f"power source: {v}"
            if k == "supply_ma":
                return f"supply rating: {v:g} mA"
            if k == "rails":
                return "voltage rails: " + ", ".join(f"{x:g}" for x in v) + " V"
            if k == "envelope_mm":
                return "inside size: " + " x ".join(f"{x:g}" for x in v) + " mm"
            return f"{k.replace('_', ' ')}: {v}"
        out = [say(k, v) for k, v in self.set_fields.items()]
        out += [f"add part {r}" for r in self.add_parts]
        out += [f"add constraint: {c}" for c in self.add_constraints]
        return out


def apply_fix(brief, fix: Fix):
    """A new brief with the fix applied. The original is not modified."""
    if fix.kind != "change":
        raise ValueError("this suggestion is advice, not a change")
    b = copy.deepcopy(brief)
    for k, v in fix.set_fields.items():
        setattr(b, k, v)
    for r in fix.add_parts:
        if r not in b.parts:
            b.parts.append(r)
    for c in fix.add_constraints:
        if c not in b.constraints:
            b.constraints.append(c)
    return b


def _round_up(x: float, step: float = 5.0) -> float:
    return float(math.ceil(x / step) * step)


def _power_fixes(brief, parts, library, rerun) -> list[Fix]:
    plan = power_plan(parts, library, brief.power)
    fixes = []
    for o in plan.options:
        if o.verdict != "recommended":
            continue
        fixes.append(Fix(
            f"power_{o.supply.key}", f"Power it from: {o.supply.label}",
            f"Your parts draw {plan.peak_ma:.0f} mA at peak; with the "
            f"{HEADROOM:.0%} margin that needs {plan.need_ma} mA. {o.why}",
            "change", rerun,
            set_fields={"power": o.supply.power, "supply_ma": o.supply.ma,
                        "rails": o.rails},
            add_parts=list(o.add_parts)))
    if not fixes and plan.loads:
        big = max(plan.loads, key=lambda t: t[1])
        if battery_design(brief.power, parts):
            # The most favourable case: even the largest cell in the
            # library falls short, so report that one, not just the first.
            battery_opts = [o for o in plan.options if o.supply.battery]
            bat = max(battery_opts, key=lambda o: o.supply.ma, default=None)
            have = f"{bat.supply.ma:.0f} mA" if bat else "the cell's rating"
            fixes.append(Fix(
                "power_battery", "The battery cannot supply the peak draw",
                f"Your parts need {plan.need_ma} mA with the safety margin; the "
                f"cell gives {have} continuously. The largest draw is {big[0]} "
                f"at {big[1]:.0f} mA at full output -- a larger cell (add one "
                "to the parts library first), or a design that limits that "
                "peak, would fix it. Nemo will not switch a battery device to "
                "mains power for you.", "info"))
        else:
            fixes.append(Fix(
                "power_none", "No standard supply is big enough",
                f"Your parts need {plan.need_ma} mA. The largest draw is "
                f"{big[0]} at {big[1]:.0f} mA; replacing or removing it is "
                "the place to start.", "info"))
    return fixes


def _envelope_fix(brief, parts) -> Fix | None:
    env = list(brief.envelope_mm or [])
    sized = [p for p in parts if p and len(p.size_mm) >= 3]
    if len(env) < 3 or not sized:
        return None
    clearance = 3.0                   # as checks.deterministic.fits_envelope
    L, W, H = env[:3]
    tallest = max(p.size_mm[2] for p in sized) + clearance
    area = sum((p.size_mm[0] + clearance) * (p.size_mm[1] + clearance)
               for p in sized)
    newL, newW, newH = L, W, H
    if tallest > H:
        newH = _round_up(tallest + 2)
    if area > L * W:
        scale = math.sqrt(area * 1.15 / (L * W))
        newL, newW = _round_up(L * scale), _round_up(W * scale)
    # Grown on until the enclosure's own packing places them (mistake 3).
    from .enclosure import fitting_size
    packed = fitting_size(sized, [newL, newW, newH])
    if packed:
        newL, newW, newH = packed
    if (newL, newW, newH) == (L, W, H):
        return None
    return Fix("envelope", f"Enlarge the enclosure to {newL:g} x {newW:g} x {newH:g} mm",
               f"The parts need about {area:.0f} mm\u00b2 of floor and "
               f"{tallest:.0f} mm of height, with 3 mm clearance around each.",
               "change", "parts", set_fields={"envelope_mm": [newL, newW, newH]})


def _starting_envelope(parts) -> Fix | None:
    """An inside size that fits the parts, for a brief that gives none:
    their floor area with the same 3 mm clearance the check uses and
    room to spare, laid out about half again as long as wide, and the
    tallest part's height with clearance. A start, said as one."""
    sized = [p for p in parts if p and len(p.size_mm) >= 3]
    if not sized:
        return None
    clearance = 3.0                   # as checks.deterministic.fits_envelope
    area = sum((p.size_mm[0] + clearance) * (p.size_mm[1] + clearance) for p in sized)
    floor = area * 1.5                # room for wires and for the layout to move parts
    W = _round_up(math.sqrt(floor / 1.5))
    L = _round_up(max(floor / W, max(p.size_mm[0] + clearance for p in sized)))
    W = max(W, _round_up(max(p.size_mm[1] + clearance for p in sized)))
    H = _round_up(max(p.size_mm[2] for p in sized) + clearance + 2)
    from .enclosure import fitting_size
    packed = fitting_size(sized, [L, W, H])
    if packed:
        L, W, H = packed
    return Fix("envelope_start", f"Use a starting enclosure of {L:g} x {W:g} x {H:g} mm",
               f"Worked out from the parts: about {area:.0f} mm² of floor with 3 mm "
               "clearance around each, half as much again for wiring, and the tallest "
               "part's height. It is a starting size; change it on the Brief tab if "
               "the box must be smaller or a particular shape.",
               "change", "parts", set_fields={"envelope_mm": [L, W, H]})


def suggest_fixes(brief, library, stage: str, record: dict,
                  safety: list[dict] | None = None,
                  min_wall_mm: float = 1.2, project_root=None) -> list[Fix]:
    """Suggestions for the failed or unchecked results of one step."""
    if not record:
        return []
    parts = [library.get(r) for r in brief.parts]
    parts = [p for p in parts if p]
    fixes: list[Fix] = []
    seen: set[str] = set()

    def add(f: Fix | None):
        if f and f.key not in seen:
            seen.add(f.key); fixes.append(f)

    for c in record.get("checks", []):
        name, status, items = c["name"], c["status"], c.get("items", [])
        if status == "PASS":
            # D148: the one passing check that can leave something to do.
            shifter = next((p for p in library.parts.values() if p.gates), None)
            if name == "harness_levels" and shifter is not None \
                    and shifter.ref not in brief.parts \
                    and any("drives" in it and "input" in it for it in items):
                add(Fix("level_shifter", f"Add a level shifter ({shifter.ref})",
                        "The board drives an input that works at a higher voltage "
                        "than the board's pins give. With the shifter in the parts "
                        "list Nemo routes that signal through it.",
                        "change", "parts", add_parts=[shifter.ref]))
            continue

        if name.startswith("review_") and status == "FAIL":
            # The Reviewer stopped the step before it began; it knows its
            # own remedies (nemo/review.py).
            from .review import fixes as review_fixes
            for f in review_fixes(name[len("review_"):], brief, library, project_root):
                add(f)
            continue
        if status == "SKIP":
            # D175. A check skipped because the BRIEF lacks a value is not a
            # missing tool, and was offered only as "'current_sum' could not
            # run (advice)" with both buttons greyed out. Seen on the first
            # NemoIso run on the AH531 (2026-10-15): a brief with no supply
            # rating and no enclosure size, step 2 "Unchecked", and nothing
            # on the screen saying where either value goes. Where Nemo can
            # work a value out it now offers it; and it always says where
            # the owner can type it.
            if name == "current_sum" and not brief.supply_ma:
                for f in _power_fixes(brief, parts, library, "parts"):
                    add(f)
                add(Fix("brief_supply", "Give the supply rating",
                        "The brief does not say how much current the supply gives, so "
                        "the parts' draw cannot be checked against it. Type it in "
                        "'Supply rating' (mA) on the Brief tab, or apply a supply "
                        "above if one is offered.", "info", brief_field="supply_ma"))
                continue
            if name == "fits_envelope" and len(brief.envelope_mm or []) < 3:
                add(_starting_envelope(parts))
                add(Fix("brief_envelope", "Give the enclosure size",
                        "The brief does not say how big the inside of the box is, so "
                        "Nemo cannot check the parts fit. Type it in 'Inside size' "
                        "(mm, length x width x height) on the Brief tab, or apply "
                        "the starting size above if one is offered.", "info",
                        brief_field="envelope_mm"))
                continue
            hint = items[-1] if items else ""
            add(Fix(f"tool_{name}", f"'{name}' could not run",
                    (c.get("detail", "") + (f". {hint}" if hint else "")).strip(),
                    "info"))
            continue

        if name == "current_sum":
            for f in _power_fixes(brief, parts, library, "parts"):
                add(f)
        elif name == "supply_rails":
            wanted = set()
            for it in items:
                m = re.search(r"wants \[([^\]]+)\] V", it)
                if m:
                    wanted.add(float(m.group(1).split(",")[0]))
            if wanted:
                rails = sorted(set(brief.rails) | wanted, reverse=True)
                add(Fix("rails", f"Add a {', '.join(f'{v:g} V' for v in sorted(wanted))} rail",
                        "A part needs a voltage the design does not provide yet.",
                        "change", "parts", set_fields={"rails": rails}))
        elif name == "fits_envelope":
            add(_envelope_fix(brief, parts))
        elif name == "safety":
            for f in (safety or []):
                if f.get("severity") != "block":
                    continue
                rule = f.get("rule", "")
                if rule == "lipo_requires_protection_circuit":
                    ch = next((p for p in library if p.category == "power"
                               and not _is_lipo_cell(p)
                               and re.search(r"protect|dw01|bms",
                                             p.name.lower())), None)
                    if ch:
                        add(Fix("add_protection", f"Add {ch.name}",
                                "Every lithium cell needs a protection circuit. "
                                "This is a safety rule, so the fix is to add one.",
                                "change", "parts", add_parts=[ch.ref]))
                elif rule == "supply_headroom_fraction":
                    for fx in _power_fixes(brief, parts, library, "parts"):
                        add(fx)
                else:
                    # Voltage ceiling, current ceiling, forbidden domains:
                    # the rule stays, so the suggestion is advice.
                    add(Fix(f"rule_{rule}", "A safety rule blocks this design",
                            f"{f.get('detail', '')} Safety rules cannot be "
                            "loosened from here; the design has to change.",
                            "info"))
        elif name == "voltage_compat":
            lines = []
            for it in items:
                m = re.match(r"(\S+) \(([\d.]+) V\) -> (\S+) \(([\d.]+) V\)", it)
                if m:
                    lines.append(f"Level-shift {m.group(1)} ({m.group(2)} V) "
                                 f"to {m.group(3)} ({m.group(4)} V)")
            if lines:
                add(Fix("level_shift", "Ask for level shifting in the schematic",
                        "Parts on the same bus run at different logic voltages.",
                        "change", stage, add_constraints=lines))
        elif name == "wire_gauge":
            lines = []
            for it in items:
                m = re.match(r"(\w+): .*needs (\d+) AWG", it)
                if m:
                    lines.append(f"Use {m.group(2)} AWG or thicker for {m.group(1)}")
            if lines:
                add(Fix("gauge", "Ask for thicker wire", "Some cables are too "
                        "thin for the current they carry.", "change", stage,
                        add_constraints=lines))
        elif name == "harness_pins":
            lines = []
            if any("read as" in it and "YAML" in it for it in items):
                lines.append('Quote pin names YAML reads as true/false '
                             '(NO, ON, OFF, YES, Y, N), e.g. "NO"')
            for it in items:
                m = re.match(r"\S+: (\w+) has no pin '[^']*' \(has ([^)]*)\)", it)
                if m:
                    lines.append(f"{m.group(1)} pins are exactly: {m.group(2)}")
            if lines:
                add(Fix("pins", "Tell the model the real pin names",
                        "Some wires were drawn to pins that do not exist.",
                        "change", stage, add_constraints=sorted(set(lines))))
        elif name == "xref_cutouts":
            refs = [it.split(":")[0].strip() for it in items if ":" in it]
            if refs:
                add(Fix("cutouts", "Ask for the missing openings",
                        "Panel-mounted parts have no opening in the case.",
                        "change", stage,
                        add_constraints=[f"Add an opening named cutout_{r}" for r in refs]))
        elif name == "thickness":
            add(Fix("walls", f"Ask for walls of at least {min_wall_mm:g} mm",
                    "Part of the enclosure is too thin to print reliably.",
                    "change", stage,
                    add_constraints=[f"Every wall at least {min_wall_mm:g} mm thick"]))
        elif name == "solid":
            add(Fix("solid", "Ask for one closed solid",
                    "The enclosure is not watertight, so a slicer cannot print it.",
                    "change", stage,
                    add_constraints=["The enclosure must be a single closed, watertight solid"]))
        elif name in ("erc", "wireviz", "compile"):
            detail = "; ".join(i.strip() for i in items[:3] if i.strip())
            label = {"erc": "electrical-rule errors", "wireviz": "harness errors",
                     "compile": "compile errors"}[name]
            if detail:
                add(Fix(f"errors_{name}", f"Ask the model to fix the {label}",
                        f"The step reported: {detail}", "change", stage,
                        add_constraints=[f"Fix these {label}: {detail}"[:300]]))
            add(Fix(f"retry_{name}", "Run the step again",
                    "Model output varies between runs; a second attempt "
                    "sometimes passes without any change.", "change", stage))

    if record.get("go_back_to") and not fixes:
        add(Fix("go_back", "Fix an earlier step first",
                f"This failure starts at the '{record['go_back_to']}' step.",
                "info"))
    return fixes
