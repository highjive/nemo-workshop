"""The Workshop's Inspector (the Reviewer until 2026-10-21): checks every
handoff before a step starts.

Owner's redesign, 2026-10-17: "allow for more errors to be caught before
failures". Each check here is one that a step would otherwise discover by
failing, or, worse, would not discover at all: an RFID player whose parts
have no RFID reader passes every gate and builds the wrong thing. All of
it is code; the model is asked nothing (docs/design-rules.md 4f: every token costs
minutes here).

A finding that would make the step fail or build the wrong thing STOPS it:
it comes back as a failed check named review_<key>, so the window shows it
with its fixes (nemo/fixes.py asks fixes() below). A finding that is only
worth a look is a NOTE and the step goes ahead. The owner can accept a
stop he knows is fine (Brief.accepted); it is then a note.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .checks import FAIL, Result
from .checks.deterministic import current_sum, fits_envelope, supply_rails
from .named import _said, extra_loads
from . import steps
from .staff import DEPARTMENTS, STAFF, owner

ORDER = steps.ORDER                    # the one list: nemo/steps.py

# Things a brief can ask for that only a part can do: what the brief says,
# and the library parts that do it. Whole words, negation respected.
DEVICES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "rfid": ("an RFID reader",
             ("rfid", "nfc", "rfid tag", "rfid tags", "rfid card", "rfid cards",
              "tag reader", "card reader"), ("rc522",)),
    "microphone": ("a microphone", ("microphone", "microphones", "mic"), ("sph0645lm4h",)),
    "distance": ("a distance sensor",
                 ("distance", "proximity", "comes near", "come near", "rangefinder",
                  "range finder"), ("vl53l0x",)),
    "climate": ("a temperature sensor",
                ("temperature", "thermometer", "humidity", "air pressure", "weather"),
                ("bme280", "ds18b20")),
    "motion": ("a motion sensor",
               ("tilt", "tilted", "shake", "shaken", "accelerometer", "gyro", "gyroscope",
                "orientation"), ("mpu6050",)),
    # D184: a replica with "sound effects" was drafted with no speaker.
    "sound": ("a speaker",
              ("sound", "sounds", "sound effect", "sound effects", "audio", "music",
               "speaker", "speakers", "beep", "beeps", "tone", "tones", "voice"),
              ("speaker_8ohm_20mm",)),
    "sound_files": ("something to play sound files",
                    ("mp3", "mp3s", "audio file", "audio files", "sound file", "sound files",
                     "audio player", "plays audio", "play audio", "plays music",
                     "play music", "pre-recorded"), ("dfplayer_mini",)),
}

# A brief that describes a sculpted form. Phrases, not single words: "a
# hand comes near" is not a shape, "in the shape of a hand" is.
# A replica, a prop or a scale model is a shaped object too (the AH531,
# 2026-10-21: "a replica Blunderbust gun" passed unremarked, and the Artist
# drew two empty trays for it).
SHAPED = re.compile(r"\b(in the shape of [a-z ]{1,30}|shaped (?:like|as) [a-z ]{1,30}|"
                    r"[a-z]+-shaped|the shape of [a-z ]{1,30}|statue|figurine|sculpture|"
                    r"bust of [a-z ]{1,30}|replicas? (?:of )?"
                    # Not a linking word straight after it: "a 3D-printed replica that
                    # simulates the firing" was quoted as the shape (2026-11-05).
                    r"(?!(?:with|that|and|which|for|to|in|on|is|was|of)\b)[a-z]+"
                    r"(?: (?!(?:with|that|and|which|for|to|in|on)\b)[a-z]+){0,2}|"
                    r"scale model of [a-z ]{1,30}|(?:a|an|the) prop [a-z]+|cosplay [a-z]+)",
                    re.I)


def shape_asked(brief) -> str | None:
    """The words by which the brief asks for a shaped object, unless the
    owner has said a rectangular tray will do. None otherwise."""
    if "shape_unsupported" in set(getattr(brief, "accepted", None) or []):
        return None
    text = _text(brief)
    m = SHAPED.search(text)
    if m:
        return m.group(0)
    # A replica, prop or full-size model of a kind of object Nemo's code can
    # build (nemo/anatomy.py): shaped, named by that kind ("blunderbuss").
    if PROPLIKE.search(text):
        from .anatomy import FAMILIES
        import re as _re
        for fam in FAMILIES.values():
            for w in fam.words:
                if _re.search(rf"\b{_re.escape(w)}", text):
                    return w
    return None


def built_by_code(brief) -> bool:
    """A shaped object with no parts whose kind Nemo's code can build
    (nemo/anatomy.py): the Concept step makes it, there is no case, and the
    enclosure step has nothing to do (D227). A shape Nemo cannot build (a phone
    stand like a paw, D188) still stops at the enclosure, where a tray can be
    said to do."""
    try:
        if not getattr(brief, "no_parts", False) or brief.parts:
            return False
        if not shape_asked(brief):
            return False
        from .anatomy import family_of
        return family_of(" ".join([brief.name or "", _text(brief)])) is not None
    except (TypeError, AttributeError):
        return False                  # not a brief (a stand-in): nothing to decide


PROPLIKE = re.compile(r"\b(replicas?|props?|scale model|model of|cosplay|full[- ]sized?|"
                      r"life[- ]sized?)\b", re.I)

# What a part is for, in a brief's words. A part none of whose words the
# brief uses may be a guess (the model put a servo in an audio player on
# the AH531, 2026-10-17). Only a note: the brief may say it another way.
PURPOSE: dict[str, tuple[str, ...]] = {
    "sg90_servo": ("servo", "lid", "arm", "turn", "turns", "rotate", "rotates", "open",
                   "opens", "close", "closes", "point", "pointer", "flag", "move", "moves"),
    "relay_5v_1ch": ("relay", "switch", "switches", "mains", "fan", "pump", "heater",
                     "lamp", "valve", "solenoid"),
    "speaker_8ohm_20mm": ("speaker", "sound", "sounds", "audio", "play", "plays", "music",
                          "voice", "tone", "beep"),
    "ws2812b_ring8": ("led", "leds", "light", "lights", "glow", "glows", "colour", "color",
                      "colours", "colors", "pixel", "pixels", "ring", "lamp"),
    "ssd1306_oled_096": ("display", "screen", "show", "shows", "text", "oled"),
    "drv8833": ("motor", "motors", "wheel", "wheels", "drive", "drives", "spin", "spins"),
    "max98357a": ("speaker", "sound", "audio", "play", "plays", "music", "voice"),
    "dfplayer_mini": ("mp3", "sound", "audio", "play", "plays", "music", "track", "tracks"),
    **{ref: words for _, (_, words, refs) in DEVICES.items() for ref in refs
       if ref not in ("dfplayer_mini",)},
}


def _text(brief) -> str:
    return " ".join([brief.function or "", brief.done_when or "",
                     *[str(c) for c in (brief.constraints or [])]]).lower()


def _stop(key: str, who: str, detail: str, items=()) -> tuple[Result, str]:
    return Result(f"review_{key}", FAIL, detail, list(items)), who


def before(step: str, project, library) -> tuple[list[Result], list[str]]:
    """(stops, notes) for starting `step`. Stops are failed checks named
    review_<key>; notes are sentences. Empty stops: the step may start."""
    stops: list[tuple[Result, str]] = []
    notes: list[str] = []
    if step not in ORDER or step == "brief":
        return [], []
    i = ORDER.index(step)
    try:
        brief = project.load_brief()
    except Exception as exc:                                    # noqa: BLE001
        return [Result("review_brief", FAIL, f"the brief cannot be read ({exc})")], []
    accepted = set(getattr(brief, "accepted", None) or [])
    if step == "parts" and brief.parts and not getattr(brief, "no_parts", False):
        notes.append(_stock_note(brief.parts))
    complete, missing = brief.complete
    if not complete:
        stops.append(_stop("brief_incomplete", "workshop.designer",
                           "the brief is missing " + ", ".join(missing),
                           ["Fill these in on the Brief tab and save it."]))
    # The Writer reads the brief before anyone works from it (owner,
    # 2026-10-21): a misspelt word went on to the image model as it was.
    # Offered, never changed; a word the owner says is meant is let be.
    from .writer import brief_spelling
    spelt = [s for s in (brief_spelling(brief, library) or [])
             if f"spelling:{s.old.lower()}" not in accepted]
    if spelt:
        stops.append(_stop("brief_spelling", "workshop.writer",
                           "the brief may be misspelt: " + "; ".join(
                               f"'{s.old}' (did you mean '{s.new}'?)" for s in spelt),
                           ["Apply the spellings you want, or say the words are meant."]))
    known = [library.get(r) for r in brief.parts]
    unknown = [r for r, p in zip(brief.parts, known) if p is None]
    parts = [p for p in known if p]
    if unknown:
        stops.append(_stop("unknown_parts", "workshop.researcher",
                           "the library has no part called " + ", ".join(unknown),
                           ["Choose parts from the library on the Brief tab."]))
    no_power = bool(getattr(brief, "no_power", False))
    no_parts = bool(getattr(brief, "no_parts", False))
    if no_parts and brief.parts:
        stops.append(_stop("parts_but_none", "workshop.designer",
                           "the brief says no parts are needed, and lists "
                           + ", ".join(brief.parts),
                           ["Clear the parts, or untick No parts needed."]))
    if no_power:
        drawing = [p.ref for p in parts if p.category != "power" and p.draw_ma > 0]
        if drawing:
            stops.append(_stop("parts_need_power", "workshop.designer",
                               "the brief says no power is needed, and these parts need it: "
                               + ", ".join(drawing),
                               ["Untick No power needed, or remove them."]))
    boards = [p for p in parts if p.category == "mcu"]
    if parts and not boards:
        stops.append(_stop("no_board", "workshop.designer", "no microcontroller board among the parts",
                           ["Every design here is built round one board."]))
    elif len(boards) > 1:
        # D184: a note until the AH531 (2026-10-18), where a brief with two
        # boards went on to fail. Every design here is wired round one.
        stops.append(_stop("boards_many", "workshop.designer",
                           "more than one board: " + ", ".join(p.ref for p in boards),
                           ["Every design here is built round one board. Keep one."]))

    # What the brief asks for that no part does.
    text = _text(brief)
    have = {p.ref for p in parts}
    for key, (thing, words, refs) in DEVICES.items():
        if no_parts:
            break                    # the owner said none: nothing is missing
        if _said(words, text) and not have & set(refs):
            k = f"missing_{key}"
            msg = f"the brief asks for {thing}, and no part is one"
            if k in accepted:
                notes.append(f"Inspector: {msg}; you said it is not needed.")
            else:
                stops.append(_stop(k, "workshop.designer", msg,
                                   ["Add " + " or ".join(refs) + ", or say it is not needed."]))
    # Parts the brief never gives a reason for. D184: notes until the
    # AH531 (2026-10-18), where the model drafted a replica with a
    # thermometer, a weather sensor, a microphone, a display and a servo,
    # none of them asked for; the notes were read past and the step failed.
    loose = [p for p in parts if PURPOSE.get(p.ref) and not _said(PURPOSE[p.ref], text)]
    if loose:
        names = ", ".join(f"{p.ref} ({p.name})" for p in loose)
        if "unexplained_parts" in accepted:
            notes.append(f"Inspector: the brief never says what these are for: {names}; "
                         "you said they are needed.")
        else:
            stops.append(_stop("unexplained_parts", "workshop.designer",
                               "the brief never says what these are for: " + names,
                               ["Remove them, or say they are needed."]))

    if i >= ORDER.index("electrical") and parts and not no_power:
        extra = extra_loads(brief)[0]
        cs = current_sum(parts, brief.supply_ma, extra=extra)
        if not brief.supply_ma:
            stops.append(_stop("no_supply", "workshop.designer", "the brief gives no supply rating",
                               ["Give 'Supply rating' on the Brief tab, or use Suggest power."]))
        elif not cs.ok:
            stops.append(_stop("over_budget", "workshop.designer", cs.detail, cs.items))
        sr = supply_rails(parts, brief.rails)
        if not sr.ok:
            stops.append(_stop("rails", "workshop.designer", sr.detail, sr.items))
        bare = [p.ref for p in parts if p.category not in ("power",) and not p.pins]
        if bare:
            stops.append(_stop("no_pins", "workshop.researcher",
                               "the library gives no pins for " + ", ".join(bare),
                               ["Without its pins a part cannot be wired."]))
    # D188, the AH531 on 2026-10-19: "holds a phone on a table in the shape
    # of a hand" was made as a 12 x 30 x 50 mm open box, and every check
    # passed. Nemo's enclosure is a rectangular tray round the parts; a
    # shaped object is not something it can model, and that is said.
    shaped = shape_asked(brief)
    if shaped and built_by_code(brief):
        # A printed object with nothing in it: no case, so nothing to stop; the
        # Art Studio's Designer builds it (steps.not_needed says so at its step).
        if step == "concept":
            notes.append(f"Inspector: a shaped object (“{shaped}”) with no parts: "
                         "Nemo builds two concepts of it to choose from, and the Art Studio's "
                         "Designer builds the one chosen.")
    elif shaped:
        msg = (f"the brief asks for a shape (\u201c{shaped}\u201d), and Nemo makes only "
               "rectangular trays round the parts")
        if step == "enclosure":
            stops.append(_stop("shape_unsupported", "workshop.designer", msg,
                               ["Model the shape in a CAD program, or say a tray is fine."]))
        elif step == "concept":
            # Two concepts built by code from the object's anatomy (owner,
            # 2026-11-04: "remove blockout"; nemo/anatomy.py), to choose from; the
            # Art Studio's Designer builds the one chosen.
            notes.append(f"Inspector: {msg}; Nemo builds two concepts of it from its parts "
                         "to choose from, the Art Studio's Designer builds the one chosen, and "
                         "the enclosure step will stop on the shape.")
        else:
            notes.append(f"Inspector: {msg}; the enclosure step will stop on it.")
    if step in ("concept", "enclosure") and parts:
        if len(brief.envelope_mm or []) < 3:
            stops.append(_stop("no_envelope", "workshop.designer", "the brief gives no inside size",
                               ["Give 'Inside size' on the Brief tab."]))
        else:
            fe = fits_envelope(parts, brief.envelope_mm)
            if not fe.ok:
                stops.append(_stop("too_small", "workshop.designer", fe.detail, fe.items))
        unsized = [p.ref for p in parts if len(p.size_mm) < 3]
        if unsized:
            stops.append(_stop("no_size", "workshop.researcher",
                               "the library gives no size for " + ", ".join(unsized)))
    # The owner picks the Artist's concept before the Designer models it
    # (owner's request, 2026-10-20). A pick made for other parts or another
    # envelope does not count.
    if step == "enclosure" and "no_concept" not in accepted and not shaped:
        from .concept import chosen, current_signature
        if chosen(project.root, current_signature(brief, parts)) is None:
            stops.append(_stop("no_concept", "art_studio.artist",
                               "no concept of the enclosure has been chosen for these "
                               "parts and this size",
                               ["Run the concept step and choose A or B, with any changes."]))

    # What this step builds on must have passed.
    needs = steps.get(step).builds_on
    done = _results(project)
    for prior in needs:
        rec = done.get(prior)
        if not rec or not rec.get("ok"):
            stops.append(_stop(f"needs_{prior}", owner(prior).key,
                               f"step '{prior}' has not passed, and this one builds on it",
                               [f"Run '{prior}' first."]))
    if step == "pack":
        failed = [s for s in ORDER[1:-1] if not (done.get(s) or {}).get("ok")]
        if failed:
            notes.append("Inspector: the build guide will say these steps have not passed: "
                         + ", ".join(failed) + ".")

    results = []
    for r, who in stops:
        r.items = list(r.items) + [f"For the {STAFF[who].label}."]
        results.append(r)
    return results, notes


def _stock_note(refs: list[str]) -> str:
    """What of the brief's parts the Storeroom has (storeroom.check_parts):
    checked before any part is asked for. A note, never a stop."""
    try:
        from . import storeroom
        from .config import Config
        have, need = storeroom.check_parts(Config.load().path("paths.storeroom"), refs)
        return storeroom.describe_stock(have, need)
    except Exception as exc:                                    # noqa: BLE001
        return f"Storeroom: could not be checked ({exc})."


def _results(project) -> dict:
    try:
        from .results import load_results
        return load_results(project.root)
    except Exception:                                           # noqa: BLE001
        return {}


# -------------------------------------------------------------- the log
def record(project_root: Path, step: str, event: str, **detail) -> None:
    """One line of the work log: who had the job, what happened."""
    try:
        e = owner(step)
        who, dept = e.title, DEPARTMENTS[e.department].name
    except KeyError:
        who, dept = "Inspector", DEPARTMENTS["workshop"].name
    line = {"at": int(time.time()), "step": step, "who": who, "department": dept,
            "event": event, **detail}
    path = Path(project_root) / ".nemo" / "work.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def work_log(project_root: Path) -> list[dict]:
    path = Path(project_root) / ".nemo" / "work.jsonl"
    if not path.is_file():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


# ------------------------------------------------------------- fixes
def researchable(stops) -> list[tuple[str, str]]:
    """(key, thing) for each stop the Researcher can look up online: a
    thing no part is, and a part name the library does not know."""
    out = []
    for r in stops:
        key = r.name[len("review_"):]
        if key.startswith("missing_") and key[8:] in DEVICES:
            out.append((key, DEVICES[key[8:]][0]))
        elif key == "unknown_parts":
            names = r.detail.split("called ", 1)[-1]
            out += [(key, n.strip()) for n in names.split(",") if n.strip()]
    return out


def found_online(key: str, project_root) -> list:
    """The Researcher's finds for one stop, as fixes that open a page."""
    from .fixes import Fix
    from . import research
    out = []
    if project_root is None:
        return out
    for thing, rec in research.finds_for(project_root, key):
        if not rec.get("finds"):
            out.append(Fix(f"research_none_{key}_{thing}", f"Researcher: nothing found for {thing}",
                           rec.get("why") or "No part came back.", "info"))
            continue
        for i, f in enumerate(rec["finds"]):
            out.append(Fix(f"research_{key}_{thing}_{i}", f"Found online: {f['title']}",
                           (f.get("snippet") or "") + " Read its datasheet, then add it with "
                           "Add a part: the Researcher puts no figure in the library itself.",
                           "info", url=f.get("datasheet") or f["url"]))
    return out


def fixes(key: str, brief, library, project_root=None) -> list:
    """The Inspector's own fixes for its findings, as nemo.fixes.Fix, and
    what the Researcher found online for them."""
    from .fixes import Fix
    out = found_online(key, project_root)
    if key == "brief_spelling":
        from .writer import brief_spelling, corrected
        accepted = set(getattr(brief, "accepted", []) or [])
        spelt = [s for s in (brief_spelling(brief, library) or [])
                 if f"spelling:{s.old.lower()}" not in accepted]
        for n, s in enumerate(spelt):
            out.append(Fix(f"writer_spell_{n}_{s.old.lower()}", f"Spell '{s.old}' as '{s.new}'",
                           f"In the {s.field.replace('_', ' ')}. {s.message}", "change",
                           "parts", set_fields={s.field: corrected(brief, s)}))
        if spelt:
            out.append(Fix("writer_spelling_meant", "These words are spelt as meant",
                           "Tells the Writer to let them be: " + ", ".join(s.old for s in spelt)
                           + ".", "change", "parts",
                           set_fields={"accepted": sorted(accepted | {
                               f"spelling:{s.old.lower()}" for s in spelt})}))
        return out
    if key.startswith("missing_") and key[8:] in DEVICES:
        thing, _, refs = DEVICES[key[8:]]
        for ref in refs:
            p = library.get(ref)
            if p:
                out.append(Fix(f"review_add_{ref}", f"Add {ref} ({p.name})",
                               f"The brief asks for {thing}.", "change", "parts",
                               add_parts=[ref]))
        out.append(Fix(f"review_accept_{key}", f"{thing[0].upper() + thing[1:]} is not needed",
                       "Tells the Inspector this is right: it will note it and go on.",
                       "change", "parts",
                       set_fields={"accepted": sorted(set(getattr(brief, "accepted", []) or [])
                                                      | {key})}))
    elif key == "boards_many":
        boards = [r for r in brief.parts if (library.get(r) and library.get(r).category == "mcu")]
        for b in boards:
            keep = [r for r in brief.parts if r == b or r not in boards]
            out.append(Fix(f"review_keep_{b}", f"Keep only {b}",
                           "Every design here is built round one board.", "change", "parts",
                           set_fields={"parts": keep, "mcu": b}))
    elif key == "unexplained_parts":
        text = _text(brief)
        loose = [r for r in brief.parts if PURPOSE.get(r) and not _said(PURPOSE[r], text)]
        out.append(Fix("review_drop_unexplained", "Remove " + ", ".join(loose),
                       "The brief gives no reason for them.", "change", "parts",
                       set_fields={"parts": [r for r in brief.parts if r not in loose]}))
        out.append(Fix("review_accept_unexplained_parts", "They are needed",
                       "Tells the Inspector this is right: it will note them and go on.",
                       "change", "parts",
                       set_fields={"accepted": sorted(set(getattr(brief, "accepted", []) or [])
                                                      | {"unexplained_parts"})}))
    elif key == "unknown_parts":
        keep = [r for r in brief.parts if library.get(r)]
        out.append(Fix("review_drop_unknown", "Remove the parts the library does not have",
                       "Only parts in the library can be wired and checked.", "change",
                       "parts", set_fields={"parts": keep}))
    elif key == "no_board":
        for p in sorted((p for p in library.parts.values() if p.category == "mcu"),
                        key=lambda p: p.ref):
            out.append(Fix(f"review_board_{p.ref}", f"Use {p.ref} ({p.name})",
                           "Every design here is built round one board.", "change",
                           "parts", add_parts=[p.ref], set_fields={"mcu": p.ref}))
    elif key == "shape_unsupported":
        out.append(Fix("review_accept_shape", "A rectangular tray is fine",
                       "Tells the Inspector the box Nemo can make will do.", "change",
                       "enclosure",
                       set_fields={"accepted": sorted(set(getattr(brief, "accepted", []) or [])
                                                      | {"shape_unsupported"})}))
    elif key == "parts_but_none":
        out.append(Fix("review_clear_parts", "Clear the parts list",
                       "The brief says none are needed.", "change", "parts",
                       set_fields={"parts": [], "mcu": ""}))
        out.append(Fix("review_untick_no_parts", "Parts are needed after all",
                       "Unticks No parts needed.", "change", "parts",
                       set_fields={"no_parts": False}))
    elif key == "parts_need_power":
        # D189: the only fix was to untick No power needed, the owner's own
        # answer; applying it on the AH531 undid it. Removing the parts that
        # need power comes first.
        drawing = [r for r in brief.parts
                   if library.get(r) and library.get(r).category != "power"
                   and library.get(r).draw_ma > 0]
        keep = [r for r in brief.parts if r not in drawing]
        out.append(Fix("review_drop_powered", "Remove " + ", ".join(drawing),
                       "They need power, and the brief says none is needed.", "change",
                       "parts", set_fields={"parts": keep,
                                            "mcu": brief.mcu if brief.mcu in keep else ""}))
        out.append(Fix("review_untick_no_power", "Power is needed after all",
                       "Unticks No power needed; give the supply on the Brief tab.",
                       "change", "parts", set_fields={"no_power": False}))
    elif key in ("no_supply", "brief_incomplete", "no_envelope"):
        field = {"no_supply": "supply_ma", "no_envelope": "envelope_mm"}.get(key, "function")
        out.append(Fix(f"review_{key}", "Open the brief", "Only you can give this.",
                       "info", brief_field=field))
    return out
