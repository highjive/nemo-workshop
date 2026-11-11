"""Things a brief names that no part in its list is.

D162. The fourth real design was for a lid with "a relay that switches a
5 V fan". The parts were a board, a sensor, a servo and a relay. Every
step passed, the power budget added up four parts, and nowhere did Nemo
say that the fan was in the sentence and not in the design: its current
was in no sum and its wires on no cable.

This is a list of words, not understanding. It looks only for things
that draw current of their own, because that is what silently falls out
of the power budget, and it asks; it never fails a step. It knows a few
names for each thing and the plain ways of saying one is not wanted
("no fan", "without a fan", "a fan is not needed"). A name it does not
know gets no question, and a refusal put another way gets one it did
not need.

The answer to the question is the brief's `extra_loads`: a name and a
peak current in mA, the owner's own figure, for a thing the library has
no part for. It goes into the power budget and nowhere else.
"""
from __future__ import annotations

import re

from .parts import Part

# thing -> (the words a brief uses for it, what in a part's reference or
# name shows that the part is one). Whole words, any case.
LOADS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "a fan": (("fan", "fans", "blower", "blowers", "ventilator", "ventilators"),
              ("fan", "blower")),
    "a motor": (("motor", "motors", "gearmotor", "gearmotors"), ("motor",)),
    "a pump": (("pump", "pumps"), ("pump",)),
    "a heater": (("heater", "heaters", "heating element", "heating pad", "hotplate"),
                 ("heater", "heating")),
    "a solenoid": (("solenoid", "solenoids", "electromagnet", "electromagnets"),
                   ("solenoid", "electromagnet")),
    "a valve": (("valve", "valves"), ("valve",)),
    "a buzzer": (("buzzer", "buzzers", "beeper", "beepers", "siren", "sirens"),
                 ("buzzer", "siren")),
    "a speaker": (("speaker", "speakers", "loudspeaker", "loudspeakers"), ("speaker",)),
    "lights": (("led", "leds", "lights", "led strip", "light strip", "lamp", "lamps", "bulb",
                "bulbs"), ("led", "ws2812", "pixel", "lamp")),
    "a display": (("display", "displays", "screen", "screens"),
                  ("display", "oled", "lcd", "screen")),
    "a camera": (("camera", "cameras"), ("camera",)),
}
# A part that drives a thing is not the thing: a motor driver has "motor"
# in its name and no motor on it.
NOT_THE_THING = ("driver",)

_BEFORE = re.compile(r"(?:\b(?:no|without|not\s+need(?:ing)?|(?:does\s+not|doesn't|do\s+not|don't)"
                     r"\s+(?:need|use|have)|needs\s+no|has\s+no|not\s+(?:a|an|any))\s+"
                     r"(?:(?:a|an|any|the)\s+)?(?:[a-z0-9-]+\s+){0,2})$")
_AFTER = re.compile(r"^(?:\s+(?:is|are)\s+(?:not|never)|\s+(?:isn't|aren't))\s+"
                    r"(?:needed|required|wanted|used|fitted|included)")


def _mentions(words: tuple[str, ...], text: str) -> list[bool]:
    """One entry per place a word is used: True where it is wanted, False
    where the sentence says it is not."""
    found = []
    for w in words:
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text):
            clause = re.split(r"[.;:!?]|,| but | and ", text[:m.start()])[-1]
            found.append(not (_BEFORE.search(clause) or _AFTER.match(text[m.end():])))
    return found


def _said(words: tuple[str, ...], text: str) -> bool:
    return any(_mentions(words, text))


def extra_loads(brief) -> tuple[list[tuple[str, float]], list[str]]:
    """((name, peak mA) for each usable entry of the brief's extra_loads,
    what is wrong with the rest)."""
    good, bad = [], []
    for n, item in enumerate(getattr(brief, "extra_loads", None) or [], 1):
        name = item.get("name") if isinstance(item, dict) else None
        ma = item.get("ma") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            bad.append(f"extra load {n} has no name")
        elif isinstance(ma, bool) or not isinstance(ma, (int, float)) or ma <= 0:
            bad.append(f"extra load '{name.strip()}' has no current in mA above zero")
        else:
            good.append((name.strip(), float(ma)))
    return good, bad


def named_but_absent(brief, parts: list[Part]) -> list[str]:
    """The things from LOADS that the brief's function, done-when or
    constraints name, and that neither a part nor an extra load is, in
    LOADS's order."""
    text = " ".join([brief.function or "", brief.done_when or "",
                     *[str(c) for c in (brief.constraints or [])]]).lower()
    have = [f"{p.ref} {p.name}".lower() for p in parts if p.category not in NOT_THE_THING]
    kinds = {p.category for p in parts}
    given = " ; ".join(name.lower() for name, _ in extra_loads(brief)[0])
    out = []
    for thing, (words, shown_by) in LOADS.items():
        if not _said(words, text):
            continue
        if thing == "a display" and "display" in kinds:
            continue
        if any(s in h for s in shown_by for h in have):
            continue
        if any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", given)
               for w in words):
            continue
        out.append(thing)
    return out


def question(things: list[str]) -> str:
    """One open question for the guide, or '' if there is nothing to ask."""
    if not things:
        return ""
    listed = things[0] if len(things) == 1 else ", ".join(things[:-1]) + " and " + things[-1]
    one = len(things) == 1
    return (f"the brief names {listed} and no part in the list is {'one' if one else 'any of them'}. "
            f"{'Its' if one else 'Their'} current is not in the power budget and "
            f"{'it is' if one else 'they are'} on no cable. Add {'it' if one else 'them'} to the "
            f"parts, or give {'its' if one else 'their'} peak current under extra_loads in "
            "brief.yaml, or confirm the brief means something else")


def extra_question(name: str, ma: float) -> str:
    """What stays open about a load the brief gave a figure for."""
    return (f"{name} ({ma:g} mA, the brief's own figure) is counted in the power budget and "
            "nowhere else: it is on no cable and in no enclosure, and where it takes its "
            "current from is not checked")
