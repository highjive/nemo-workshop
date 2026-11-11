"""What the owner's request asked for, decided by code after the model drafts
a brief (owner, 2026-11-05: "run test of blunderbuss through nemo llm then
fix"; tests now go through Nemo's own model first, then Nemo is fixed).

Run for real with qwen3-8b on "A replica blunderbuss gun with a mechanical
trigger and cocking mechanism that simulates the firing action, full size
like a real one, to 3D print." The model's brief:

  - added "sound effects and visual cues", and made the test of done
    depend on them: nothing in the request asked for either;
  - left No power and No parts unticked, so the brief asked for a power
    supply, parts and an enclosure's inside size a printed prop has none of;
  - left the real size empty (rightly: it must not guess one) but asked no
    one for it, so the Concept step would only fail later.

Each is something code can see in the request's own words (docs/design-rules.md 4d: the
model is not asked twice for what code can decide):

  invented()   features the brief names that the request never did, from
               the Inspector's own word lists; strip_invented() takes the
               sentences (or ", and" clauses) naming them out, and says so.
  mechanical() a shaped object whose request names nothing electrical: no
               power and no parts, said, for the owner to untick.
  size_from()  a size written in the request ("80 cm long") into the real
               size; else, for an object Nemo's code can build, a question.

Nothing here invents a figure: a size is taken only from the request's own
words, with its unit, and converted (1 in = 25.4 mm), never estimated.
"""
from __future__ import annotations

import re

from .named import _said

# Things an object can do that need electricity, as a brief names them. The
# Inspector's DEVICES lists (review.py) and lights, which it has no list for.
LIGHTS = ("light", "lights", "led", "leds", "glow", "glows", "lit", "illuminated",
          "visual cue", "visual cues", "visual effect", "visual effects", "flash",
          "flashes", "flashing", "lamp")
ELECTRIC = ("battery", "batteries", "usb", "power supply", "powered", "electric",
            "electrical", "electronic", "electronics", "motor", "motors", "servo",
            "sensor", "sensors", "display", "screen", "wifi", "wi-fi", "bluetooth",
            "app", "microcontroller", "arduino", "esp32", "raspberry pi", "circuit",
            "wired", "wiring", "charge", "charging", "vibrate", "vibrates", "vibration",
            # A noise it makes (a prop's "bang") needs a speaker, unless the request
            # says otherwise.
            "bang", "bangs", "noise", "noises", "sound effect", "sound effects")


def features() -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    """(what it is, the words that name it, the parts that do it) for every
    feature that needs a part."""
    from .review import DEVICES
    out = [(thing, words, refs) for thing, words, refs in DEVICES.values()]
    out.append(("lights", LIGHTS, ("ws2812b_ring8",)))
    return out


def invented(request: str, brief) -> list[tuple[str, tuple[str, ...]]]:
    """Features the drafted brief names that the request did not."""
    asked = (request or "").lower()
    drafted = " ".join([brief.function or "", brief.done_when or ""]).lower()
    return [(thing, words) for thing, words, _ in features()
            if _said(words, drafted) and not _said(words, asked)]


def _without(text: str, words: tuple[str, ...]) -> str:
    """The text with each sentence, then each ", and" or ";" clause, that
    names one of the words taken out."""
    keep = []
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        if not sentence:
            continue
        if not _said(words, sentence.lower()):
            keep.append(sentence)
            continue
        parts = [p for p in re.split(r",\s+and\s+|;\s*", sentence.rstrip(".!? "))
                 if p and not _said(words, p.lower())]
        if parts:
            kept = ", and ".join(parts).strip()
            keep.append(kept[0].upper() + kept[1:] + ".")
    return " ".join(keep)


def strip_invented(request: str, brief) -> list[str]:
    """Take the invented features out of the brief (in place); what was done."""
    found = invented(request, brief)
    if not found:
        return []
    words = tuple(w for _, ws in found for w in ws)
    fn = _without(brief.function, words)
    brief.function = fn or (request or "").strip()
    brief.done_when = _without(brief.done_when, words)
    names = [t for t, _ in found]
    things = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    it = "it" if len(found) == 1 else "them"
    # The parts that do only what was taken out go too: left in, the Inspector
    # stopped on them as parts the brief gives no reason for.
    refs = {r for t, _, rs in features() if t in names for r in rs}
    dropped = [r for r in (brief.parts or []) if r in refs and r != brief.mcu]
    brief.parts = [r for r in (brief.parts or []) if r not in dropped]
    note = (f"Writer: your request did not ask for {things}; the model added {it}, and Nemo "
            f"took {it} out of what it does and the test of done"
            + (f", and the parts for {it} ({', '.join(dropped)})" if dropped else "")
            + f". Put {it} back on the Brief tab if you want {it}.")
    if not brief.done_when:
        brief.open_questions = list(brief.open_questions or []) + [
            "How will you know it works? (The test of done named only what was taken out.)"]
    return [note]


# A battery and what charges or boosts it, by the words a request needs to say
# for one (2026-11-06: "Runs from a USB phone charger" was drafted with a
# TP4056 LiPo charger and no battery). "charger" alone is not one of them.
BATTERY = ("battery", "batteries", "rechargeable", "lipo", "li-po", "li-ion", "lithium",
           "cordless", "portable", "charge", "charges", "charging", "cell", "cells",
           "18650")
BATTERY_PARTS = ("tp4056_protected", "lipo_1000", "lipo_2000", "eemb_lipo_500",
                 "boost_5v_mt3608")


# Words that give a part its purpose here, beyond the Inspector's lists: a part
# taken out wrongly is worse than one the Inspector asks about ("a tag player").
MORE_WORDS = {"rc522": ("tag", "tags", "card", "cards", "fob", "fobs")}


def unasked_parts(request: str, brief, chosen=()) -> list[str]:
    """Take out (in place) the parts the model added for a purpose the request
    never names; what was done. Only parts with known purposes are judged; the
    board and the owner's own choices (chosen) are never taken out.

    2026-11-06, a soil moisture alarm through qwen3-8b: the draft added a
    DS18B20 thermometer, a relay and a LiPo charger, none asked for; the
    Inspector then stopped the parts step on them."""
    from .review import PURPOSE, _text
    # The request, and the brief's own words once invented features are out
    # of them (strip_invented runs first): a part either explains is kept.
    asked = (request or "").lower() + " " + _text(brief)
    dropped = []
    for ref in list(brief.parts or []):
        if ref == brief.mcu or ref in chosen:
            continue
        words = BATTERY if ref in BATTERY_PARTS else PURPOSE.get(ref)
        if words and ref in MORE_WORDS:
            words = tuple(words) + MORE_WORDS[ref]
        if words and not _said(words, asked):
            dropped.append(ref)
    if not dropped:
        return []
    brief.parts = [r for r in brief.parts if r not in dropped]
    one = len(dropped) == 1
    it, they = ("it", "it is") if one else ("them", "they are")
    return [f"Writer: your request gives no reason for {', '.join(dropped)}; the model added "
            f"{it}, and Nemo took {it} out. Add {it} back on the Brief tab if {they} needed."]


def purposes_from_request(request: str, brief) -> list[str]:
    """Where the request says what a kept part is for and the brief does not,
    add the request's own words for it to the brief's constraints (in place);
    what was done.

    D270. Gemma 4 E4B (trial, 2026-11-11), asked for "two small DC motors driven
    by a DRV8833", drafted a brief that never said "motor"; the Inspector reads
    the brief and stopped the parts step: "the brief never says what these are
    for: drv8833". The owner's words are quoted, never reworded."""
    from .review import PURPOSE, _text
    text = _text(brief)
    clauses = [c.strip() for c in re.split(r"[.;:,!?\n]+", request or "") if c.strip()]
    added = []
    for ref in brief.parts or []:
        words = BATTERY if ref in BATTERY_PARTS else PURPOSE.get(ref)
        if not words or _said(words, text):
            continue
        said = sorted((c for c in clauses if _said(words, c.lower())), key=len)
        if not said:
            continue
        line = f"Your request: {said[0]}"
        if line not in (brief.constraints or []):
            brief.constraints = list(brief.constraints or []) + [line]
            text = _text(brief)
            added.append((ref, said[0]))
    if not added:
        return []
    return ["Writer: the draft did not say what " + ", ".join(r for r, _ in added)
            + " " + ("is" if len(added) == 1 else "are") + " for, and your request did, so Nemo "
            "added your own words to the constraints: "
            + "; ".join(f'"{c}"' for _, c in added) + "."]


def library_refs(brief, known, request: str = "") -> list[str]:
    """A part reference the model wrote that is not the library's, put right
    (in place) where exactly one library part is that close: the model
    nearly copies the reference (2026-11-08, a robot car through qwen3-8b:
    "esp32c3_devkitc_1" for the library's esp32c3_devkit, and the Inspector
    stopped with no board). A reference with no one close match is left for
    the Inspector to ask about. Where two are close (esp32c3_devkit and
    esp32s3_devkitc_1), the one whose name's first word the request says
    ("ESP32-C3") is the one."""
    import difflib
    known = dict(known)
    said = []

    def fix(ref):
        if not ref or ref in known:
            return ref
        close = difflib.get_close_matches(ref, list(known), n=3, cutoff=0.8)
        if len(close) > 1:
            close = [c for c in close if _named(getattr(known[c], "name", ""), request)]
            # "ESP32-C3" says ESP32 too: the longest model named is the one meant.
            size = {c: len(_model(getattr(known[c], "name", ""))) for c in close}
            close = [c for c in close if size[c] == max(size.values(), default=0)]
        if len(close) != 1:
            return ref
        said.append(f"Writer: the model wrote {ref}; the library's part is {close[0]} "
                    f"({getattr(known[close[0]], 'name', close[0])}), used instead.")
        return close[0]
    brief.mcu = fix(brief.mcu)
    brief.parts = [fix(r) for r in brief.parts or []]
    return list(dict.fromkeys(said))


def _named(name: str, request: str) -> bool:
    """The request says this part's model: the first word of its name
    ("ESP32-C3" of "ESP32-C3 DevKit (RISC-V, WiFi + BLE)"), hyphens aside."""
    first = _model(name)
    return len(first) >= 4 and first in _flat(request)


def _flat(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _model(name: str) -> str:
    """The first word of a part's name, flattened: "esp32c3" of "ESP32-C3 DevKit"."""
    return _flat((name.split() or [""])[0])


# A charger the request asks for by name ("powered by a LiPo with a charger"):
# the draft left it out and asked "What type of charger is required?",
# though the library has one (2026-11-08).
CHARGE = ("charger", "charging", "rechargeable", "recharge", "recharged")
CELLS = ("lipo_1000", "lipo_2000", "eemb_lipo_500")
CHARGERS = ("tp4056_protected",)


def asked_cell(request: str, brief, known) -> list[str]:
    """The cell the request names by its capacity ("a 1000 mAh LiPo cell")
    put among the parts (in place) when no cell is (2026-11-08: the second
    draft of the same request left it out)."""
    parts = list(brief.parts or [])
    m = re.search(r"(\d[\d,]*)\s*mah\b", (request or "").lower())
    if brief.no_parts or not m or any(c in parts for c in CELLS):
        return []
    mah = m.group(1).replace(",", "")
    match = [c for c in CELLS if c in known
             and re.search(rf"\b{mah}\s*mAh\b", getattr(known[c], "name", ""))]
    if len(match) != 1:
        return []
    brief.parts = parts + match
    return [f"Writer: your request names a {mah} mAh cell; the library's is {match[0]}, added."]


def asked_charger(request: str, brief, known) -> list[str]:
    """The library's charger put among the parts (in place) when the request
    asks for charging, a cell is among them and no charger is; an open
    question asking which charger is then answered and taken off."""
    parts = list(brief.parts or [])
    have = [c for c in CHARGERS if c in known]
    if (brief.no_parts or len(have) != 1 or any(c in parts for c in CHARGERS)
            or not any(c in parts for c in CELLS) or not _said(CHARGE, (request or "").lower())):
        return []
    brief.parts = parts + [have[0]]
    asked = [q for q in brief.open_questions or [] if "charg" in q.lower()]
    brief.open_questions = [q for q in brief.open_questions or [] if q not in asked]
    return [f"Writer: your request asks for a charger; the library's is {have[0]}, added."
            + (" That answers: " + " ".join(asked) if asked else "")]


def envelope_fits(request: str, brief, known) -> list[str]:
    """A box the request never sized, made to hold its parts (in place)
    when the model's guess cannot (2026-11-08, a desk weather display: "60 x
    40 mm" for parts needing 2532 mm2 of floor, and the size check failed a
    size nobody asked for). Only where the request gives no size; the
    height is raised to the tallest part with room; the floor keeps the
    model's proportions."""
    from .enclosure import fitting_size, layout_fault
    env = list(brief.envelope_mm or [])
    # size_from needs a unit AND a way ("80 cm long"): a "0.96 inch screen" is no box size.
    if brief.no_parts or size_from(request):
        return []
    parts = [known[r] for r in brief.parts or [] if r in known]
    if len(env) != 3 and parts:
        # No size at all from the model (2026-11-11, Gemma 4 E4B, both briefs): the brief
        # stopped as incomplete, though the box can be sized from its parts as above.
        new = fitting_size(parts, None)
        if not new:
            return []
        brief.envelope_mm = new
        return [f"Writer: your request gives no size and the model gave none, so Nemo sized "
                f"the box to hold the parts: {' x '.join(f'{v:g}' for v in new)} mm. Change it "
                "on the Brief tab."]
    if len(env) != 3:
        return []
    if not parts or layout_fault(parts, env) is None:
        return []
    new = fitting_size(parts, env)
    if not new:
        return []
    old = " x ".join(f"{v:g}" for v in env)
    brief.envelope_mm = new
    return [f"Writer: your request gives no size; the model's {old} mm could not hold the "
            f"parts, so Nemo grew it until its enclosure packing places them: "
            f"{' x '.join(f'{v:g}' for v in new)} mm. Change it on the Brief tab."]


_CURRENT = re.compile(r"\s*[,(]?\s*\b\d+(?:\.\d+)?\s*(?:m?a|amps?|milliamps?)\b\)?", re.I)


def power_figures(request: str, brief) -> list[str]:
    """A current in the power line that the request never gave and that
    the brief's own supply current contradicts, taken out (in place):
    "USB 5 V 1 A" with supply_ma 500, from a request that said only
    "powered from USB" (2026-11-08)."""
    power = brief.power or ""
    m = _CURRENT.search(power)
    if not m or _CURRENT.search(request or ""):
        return []
    said = re.search(r"(\d+(?:\.\d+)?)\s*(m?a|amps?|milliamps?)", m.group(0), re.I)
    ma = float(said.group(1)) * (1 if said.group(2).lower().startswith("m") else 1000)
    if not brief.supply_ma or abs(ma - brief.supply_ma) < 1:
        return []
    brief.power = (power[:m.start()] + power[m.end():]).strip()
    return [f"Writer: the model wrote the supply as '{power}' with {brief.supply_ma:g} mA as its "
            f"current; your request gives no current, so '{m.group(0).strip()}' is taken out."]


def board_in_parts(brief, known) -> list[str]:
    """The board the brief chose, put among its parts (in place) when the
    library has it and the draft left it out (2026-11-06: mcu esp32_devkit_v1
    with no board among the parts, and the Inspector stopped)."""
    if brief.no_parts or not brief.mcu or brief.mcu in (brief.parts or []):
        return []
    if brief.mcu not in known:
        return []
    brief.parts = [brief.mcu] + list(brief.parts or [])
    return []


def mechanical(request: str, brief) -> bool:
    """A shaped object (review.shape_asked) whose request names nothing that
    needs electricity, and whose brief names none either once invented
    features are out."""
    from .review import shape_asked
    if not shape_asked(brief):
        return False
    words = ELECTRIC + tuple(w for _, ws, _r in features() for w in ws)
    text = " ".join([request or "", brief.function or "", brief.done_when or ""]).lower()
    return not _said(words, text)


UNITS = {"mm": 1.0, "millimetre": 1.0, "millimetres": 1.0, "millimeter": 1.0,
         "millimeters": 1.0, "cm": 10.0, "centimetre": 10.0, "centimetres": 10.0,
         "centimeter": 10.0, "centimeters": 10.0, "m": 1000.0, "metre": 1000.0,
         "metres": 1000.0, "meter": 1000.0, "meters": 1000.0, "in": 25.4, "inch": 25.4,
         "inches": 25.4, '"': 25.4, "ft": 304.8, "foot": 304.8, "feet": 304.8}
AXES = {"long": 0, "length": 0, "in length": 0, "wide": 1, "width": 1, "in width": 1,
        "across": 1, "tall": 2, "high": 2, "height": 2, "in height": 2, "deep": 1}
_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|millimet(?:re|er)s?|cm|centimet(?:re|er)s?|"
                   r"metres?|meters?|m|inch(?:es)?|in|ft|foot|feet|\")\s*"
                   r"(in length|in width|in height|long|length|wide|width|across|"
                   r"tall|high|height|deep)\b", re.I)


def size_from(request: str) -> list[float] | None:
    """[long, wide, high] in mm from sizes the request writes with a unit and
    which way they run ("80 cm long", "30 cm tall"); 0 where it says none.
    None if it gives none so written: a bare number is not taken."""
    size = [0.0, 0.0, 0.0]
    found = False
    for num, unit, axis in _SIZE.findall(request or ""):
        u = UNITS.get(unit.lower())
        a = AXES.get(axis.lower())
        if u is None or a is None:
            continue
        size[a] = round(float(num) * u, 1)
        found = True
    return size if found else None


def shape_notes(request: str, brief) -> list[str]:
    """For a shaped object: its real size from the request, or a question for
    it where Nemo's code can build the object (nemo/anatomy.py)."""
    from .anatomy import FAMILIES, family_of
    from .review import shape_asked
    if not shape_asked(brief):
        return []
    if any(v > 0 for v in (getattr(brief, "shape_size_mm", None) or [])):
        return []
    size = size_from(request)
    if size:
        brief.shape_size_mm = size
        return ["Writer: its real size, from your request: " + " x ".join(
            f"{v:g}" if v else "?" for v in size) + " mm (long x wide x high)."]
    fam = family_of(" ".join([brief.name or "", brief.function or "", request or ""]))
    if fam is None:
        return []
    facts = "".join(f", and its {f.replace('_mm', '').replace('_', ' ')} if you have it"
                    for f in FAMILIES[fam.key].facts)
    q = (f"What is its real size? Give long x wide x high in mm (one of them will do) "
         f"from a measured example{facts}. Nemo does not guess it.")
    if q not in (brief.open_questions or []):
        brief.open_questions = list(brief.open_questions or []) + [q]
    return []
