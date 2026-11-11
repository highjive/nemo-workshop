"""The Second Opinion (owner, 2026-11-04): the other model looks again at the
design's pin choices and says where it thinks one is wrong.

  ask     one connection at a time, with only the facts that decide it (the
          two pins' jobs and voltages from the parts library, and what else
          shares the board pin), and three answers: fine, wrong, not sure.
          docs/design-rules.md 4g: two answers force a guess; the third is the way out.
          The model is the one the design was NOT made with (design runs the
          8B on the desktop, so the 4B of talk mode is asked).
  says    a "wrong" is a doubt for the owner to look at, raised on the Second
          Opinion's card like any problem (nemo/issues.py). It changes
          nothing, and Nemo's own checks still decide what passes: a model's
          judgement is a signal, not a verdict.
  keeps   <project>/.nemo/second-opinion.json.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

VERDICTS = ("fine", "wrong", "not sure")
SCHEMA = {"type": "object",
          "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)},
                         "reason": {"type": "string", "maxLength": 200}},
          "required": ["verdict", "reason"]}


@dataclass
class Opinion:
    part: str
    part_pin: str
    mcu_pin: str
    verdict: str
    reason: str


def _pin(part, name):
    return next((q for q in part.pins if q.name == name), None)


def facts(w, mcu, part, sharing: list[str]) -> str:
    """Only what decides this one connection."""
    pp, mp = _pin(part, w.part_pin), _pin(mcu, w.mcu_pin)
    def say(q, whose):
        if q is None:
            return f"{whose} pin: not in the parts library."
        bits = [q.function]
        if getattr(q, "direction", None):
            bits.append(q.direction)
        if getattr(q, "voltage", None):
            bits.append(f"{q.voltage:g} V")
        return f"{whose} pin {q.name}: {', '.join(bits)}."
    lines = [f"Part: {part.name}" + (f", logic {part.logic_v:g} V" if part.logic_v else "") + ".",
             say(pp, "Its"),
             f"Board: {mcu.name}" + (f", logic {mcu.logic_v:g} V" if mcu.logic_v else "") + ".",
             say(mp, "Board"),
             f"Wired: {part.name} {w.part_pin} to board {w.mcu_pin}."]
    if sharing:
        lines.append("Also on that board pin: " + "; ".join(sharing) + ".")
        # Code knows this (docs/design-rules.md 4d): a bus line of the same name on more
        # than one part is how a bus is wired. Untold, the 4B called a correct
        # shared I2C bus "wrong" twice out of four (2026-11-04).
        if pp is not None and pp.function == "bus" and all(s.endswith(f" {w.part_pin}") for s in sharing):
            lines.append(f"{w.part_pin} is a bus line: parts on one bus share it by design.")
    return "\n".join(lines)


QUESTION = ("Is this one connection sound? Answer fine if it will work, wrong if it will not, or "
            "not sure if the facts given do not settle it. Give one short reason.")


def ask(base: str, text: str, post=None) -> dict:
    payload = {"model": "local", "temperature": 0, "max_tokens": 120,
               "messages": [{"role": "user", "content": f"{text}\n\n{QUESTION}"}],
               "chat_template_kwargs": {"enable_thinking": False},
               "response_format": {"type": "json_schema",
                                   "json_schema": {"name": "opinion", "schema": SCHEMA}}}
    if post is not None:
        return post(payload)
    req = urllib.request.Request(f"{base}/chat/completions", json.dumps(payload).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        reply = json.loads(r.read().decode("utf-8"))
    return json.loads(reply["choices"][0]["message"]["content"])


def review(doc: dict, parts: list, base: str, post=None) -> list[Opinion]:
    from . import firmware
    plan = firmware.plan(doc, parts)
    by_ref = {p.ref: p for p in parts}
    mcu = by_ref[plan.mcu]
    out = []
    for w in plan.pins:
        part = by_ref.get(w.part)
        if part is None:
            continue
        sharing = [f"{o.part} {o.part_pin}" for o in plan.pins
                   if o.mcu_pin == w.mcu_pin and (o.part, o.part_pin) != (w.part, w.part_pin)]
        got = ask(base, facts(w, mcu, part, sharing), post)
        verdict = got.get("verdict") if got.get("verdict") in VERDICTS else "not sure"
        out.append(Opinion(part.name, w.part_pin, w.mcu_pin, verdict, str(got.get("reason", ""))[:200]))
    return out


def path(project_root: Path) -> Path:
    return Path(project_root) / ".nemo" / "second-opinion.json"


def save(project_root: Path, opinions: list[Opinion], model: str) -> Path:
    p = path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"model": model, "opinions": [asdict(o) for o in opinions]}, indent=1),
                 encoding="utf-8")
    return p


def doubts(project_root: Path) -> list[Opinion]:
    """The connections the last second opinion called wrong."""
    try:
        d = json.loads(path(project_root).read_text(encoding="utf-8"))
        return [Opinion(**o) for o in d.get("opinions", []) if o.get("verdict") == "wrong"]
    except (OSError, ValueError, TypeError):
        return []
