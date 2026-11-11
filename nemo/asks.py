"""Ask a department (owner, 2026-11-09: "Nemo needs input method in each department
as to what is needed to be done in each department, not being directed back to home
screen").

Every department has its own box. What is typed there is read HERE, by code (no
model: docs/design-rules.md 4d), and becomes ONE of:

  run       a `nemo` command the department already has (its own, tested), run in
            the department's bar with its words shown there
  design    a new Workshop project from the words, its brief drafted (the model)
  story     a story filed from the words and written (the model)
  window    the department's own window, with one of its controls lit (never
            pressed: casting to a television never happens unasked)
  say       an answer in words: what it did not understand, and what it can do

Nothing here sends the owner back to the home screen. A request a department
cannot take is answered there, with what it can do and, if another department
does that, which one; going there is the owner's choice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Reply:
    kind: str                       # run, design, story, window, say
    say: str = ""                   # what the department says first
    argv: list[str] = field(default_factory=list)   # run: nemo's arguments
    button: str = ""                # window: the control to light ("" = just open it)
    text: str = ""                  # design, story: the owner's words


RUN, DESIGN, STORY, WINDOW, SAY = "run", "design", "story", "window", "say"


def _words(text: str) -> str:
    return " ".join(text.strip().split())


def _after(text: str, *verbs: str) -> str:
    """What follows the first of `verbs` (a word or phrase) in `text`, without
    a leading "the", "a", "my", or "called"; "" if none of them is there."""
    for v in verbs:
        m = re.search(rf"\b{v}\b\s*(.*)$", text, re.I)
        if m:
            rest = re.sub(r"^(?:(?:the|a|an|my|called|named|of|for|to)\s+)+", "", m.group(1).strip(),
                          flags=re.I)
            return rest.strip(" .?!\"'“”")
    return ""


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}\b", text, re.I) for w in words)


def _project(ctx) -> list[str]:
    p = (ctx or {}).get("project")
    return ["--project", p] if p else []


# --------------------------------------------------------------- departments
def _workshop(t, ctx):
    if _has(t, "floor", "flooring", "laminate", "plank", "planks", "skirting", "scotia"):
        return Reply(RUN, "The Woodworker plans it.", ["wood", t])
    if _has(t, "run", "carry on", "continue", "next step", "build it") and (ctx or {}).get("project"):
        return Reply(RUN, "Running the open project's steps.", [*_project(ctx), "run"])
    if _has(t, "status", "where is it", "how far"):
        return Reply(RUN, "", [*_project(ctx), "status"])
    if _has(t, "second opinion", "look again"):
        return Reply(RUN, "The Second Opinion looks at the wiring.", [*_project(ctx), "second"])
    if _has(t, "circuit board", "pcb"):
        return Reply(RUN, "The PCB Designer makes the board.", [*_project(ctx), "pcb"])
    return Reply(DESIGN, "A new project from your words; the Writer drafts its brief.", text=t)


def _computer_lab(t, ctx):
    if not (ctx or {}).get("project"):
        return Reply(SAY, "Open a project first: the Computer Lab works on the open project's "
                          "firmware.")
    if _has(t, "guide", "explain", "pins"):
        return Reply(RUN, "The Writer writes the firmware guide.", [*_project(ctx), "guide"])
    if _has(t, "next model", "ahead", "load"):
        return Reply(RUN, "", [*_project(ctx), "ahead"])
    return Reply(RUN, "The Tester builds the firmware.", [*_project(ctx), "test"])


def _library(t, ctx):
    if _has(t, "look up", "lookup", "what is", "who was", "who is", "wikipedia"):
        what = _after(t, "look up", "lookup", "what is", "who was", "who is", "wikipedia")
        return Reply(RUN, "The Researcher looks it up.", ["lookup", what or t])
    if _has(t, "list", "my stories", "which stories"):
        return Reply(RUN, "", ["story", "list"])
    return Reply(STORY, "Filed as a story; the Writer plans and writes it.", text=t)


_SCIENCE_ACTIONS = ("convert", "solve", "simplify", "factor", "expand", "differentiate",
                    "integrate", "evaluate", "formula", "formulas", "stats")


def _science(t, ctx):
    low = t.lower()
    first = low.split()[0] if low.split() else ""
    if first in _SCIENCE_ACTIONS:
        rest = t.split(None, 1)[1] if len(t.split()) > 1 else ""
        if first == "convert":
            m = re.match(r"(.+?)\s+(?:to|in|into)\s+(.+)$", rest, re.I)
            return Reply(RUN, "", ["science", "convert", *(m.groups() if m else [rest])])
        if first == "formula":
            return Reply(RUN, "", ["science", "formula", *_formula_items(rest)])
        if first == "stats":
            return Reply(RUN, "", ["science", "stats", *re.findall(r"-?\d+(?:\.\d+)?", rest)])
        return Reply(RUN, "", ["science", first, rest] if rest else ["science", first])
    m = re.match(r"\s*(?:what is|how many|convert)?\s*(-?\d[\d.,]*\s*[^\d\s]+(?:/[^\s]+)?)\s+"
                 r"(?:to|in|into)\s+([^\s?]+)\s*\??$", t, re.I)
    if m:
        return Reply(RUN, "", ["science", "convert", m.group(1).replace(",", ""), m.group(2)])
    if "?" in t and "=" in t:
        return Reply(RUN, "", ["science", "formula", *_formula_items(t)])
    nums = re.findall(r"-?\d+(?:\.\d+)?", t)
    if _has(t, "mean", "average", "spread", "statistics", "stats") and len(nums) >= 2:
        return Reply(RUN, "", ["science", "stats", *nums])
    if "=" in t and re.search(r"[a-z]", t, re.I):
        return Reply(RUN, "", ["science", "solve", t])
    if re.fullmatch(r"[\d\s+\-*/^().,a-z]+", t, re.I) and re.search(r"\d", t):
        return Reply(RUN, "", ["science", "evaluate", t])
    return None


def _formula_items(text: str) -> list[str]:
    """'R=? V=5 V I=20 mA' -> ['R=?', 'V=5 V', 'I=20 mA'] (a value runs to the next name=)."""
    parts = re.split(r"\s+(?=[A-Za-z_]\w*\s*=)", text.strip())
    out = []
    for p in parts:
        p = re.sub(r"\s*=\s*", "=", p.strip(), count=1)
        if p.split("=", 1)[0] and not p.startswith("="):
            out.append(p)
    return out


def _comms(t, ctx):
    m = re.match(r"\s*(?:write\s+)?(?:a\s+)?(letter|email|e-mail|post)\s+(?:to\s+)?([^:]+?)\s*:\s*(.+)$",
                 t, re.I | re.S)
    if m:
        kind = "email" if m.group(1).lower().startswith("e") else m.group(1).lower()
        return Reply(RUN, "The Writer drafts it; nothing is sent.",
                     ["comms", kind, m.group(2).strip(), "--body", m.group(3).strip()])
    if _has(t, "letter", "email", "e-mail"):
        return Reply(SAY, "Say who it is to and what it says, after a colon: letter to Ann "
                          "Smith: thank you for the parts.")
    if _has(t, "open") and _after(t, "open"):
        return Reply(RUN, "", ["comms", "open", _after(t, "open")])
    if _has(t, "contacts", "address book"):
        return Reply(RUN, "", ["comms", "contacts"])
    if _has(t, "bookmarks", "sites"):
        return Reply(RUN, "", ["comms", "bookmarks"])
    if _has(t, "drafts"):
        return Reply(RUN, "", ["comms", "drafts"])
    return None


_KINDS = ("plaque", "box", "pot", "tag", "stand")


def _art_studio(t, ctx):
    kind = next((k for k in _KINDS if _has(t, k, k + "s")), "")
    if _has(t, "kinds", "what can you make"):
        return Reply(RUN, "", ["model", "kinds"])
    if _has(t, "list", "my models"):
        return Reply(RUN, "", ["model", "list"])
    if kind:
        said = re.search(r"(?:saying|reading|with the words?|that says)\s+[\"'“]?([^\"'”]+)",
                         t, re.I) or re.search(r"[\"“]([^\"”]+)[\"”]", t)
        letters = said.group(1).strip().upper() if said else ""
        name = f"{letters.title()} {kind.title()}" if letters else f"My {kind.title()}"
        args = ["model", "make", kind, name] + ([f"text={letters}"] if letters and kind in (
            "plaque", "tag") else [])
        for key, way in (("width", "wide|width"), ("height", "high|tall|height"),
                         ("depth", "deep|depth"), ("diameter", "across|diameter"),
                         ("thickness", "thick|thickness")):
            m = re.search(rf"(\d+(?:\.\d+)?)\s*mm\s+(?:{way})\b|\b(?:{way})\s*(?:of\s*)?"
                          rf"(\d+(?:\.\d+)?)", t, re.I)
            if m:
                args.append(f"{key}={m.group(1) or m.group(2)}")
        return Reply(RUN, "The Clerk sets it up; the Designer builds it; the Editor checks it.", args)
    return None


def _printshop(t, ctx):
    if _has(t, "slice", "print"):
        name = _after(t, "slice", "print")
        if name:
            return Reply(RUN, "The Slicer slices it; Nemo never sends a print.", ["print", "slice", name])
    if _has(t, "list", "models", "what can"):
        return Reply(RUN, "", ["print", "list"])
    return None


def _film(t, ctx):
    if _has(t, "list", "films"):
        return Reply(RUN, "", ["film", "list"])
    if _has(t, "plan"):
        return Reply(RUN, "The Director plans it.", ["film", "plan", _after(t, "plan", "film of")])
    name = _after(t, "film of", "film from", "make", "film")
    if name:
        return Reply(RUN, "The Director, Artist and Editor make it.", ["film", "make", name])
    return None


def _audio(t, ctx):
    if _has(t, "list", "listening shelf"):
        return Reply(RUN, "", ["audio", "list"])
    name = _after(t, "narrate", "read aloud", "audiobook of", "audiobook")
    if name:
        return Reply(RUN, "The Narrator reads it.", ["audio", "narrate", name])
    if _has(t, "record"):
        return Reply(WINDOW, "The Recorder is ready: press Record.", button="Record")
    return None


def _cast(t):
    return _has(t, "cast", "chromecast", "tv", "television")


def _theatre(t, ctx):
    if _cast(t):
        return Reply(WINDOW, "Choose what to cast and to which device, then press Cast: Nemo "
                             "never casts unasked.", button="Cast")
    if _has(t, "check"):
        return Reply(RUN, "", ["theatre", "check", _after(t, "check")])
    if _has(t, "play", "show", "watch"):
        return Reply(RUN, "The Projectionist plays it here.", ["theatre", "play",
                                                              _after(t, "play", "show", "watch")])
    if _has(t, "list", "videos", "pictures", "photos"):
        return Reply(RUN, "", ["theatre", "list"])
    return None


def _music(t, ctx):
    if _cast(t):
        return Reply(WINDOW, "Choose the tracks and a device, then press Cast: Nemo never "
                             "casts unasked.", button="Cast")
    if _has(t, "play"):
        return Reply(RUN, "The Player plays it.", ["music", "play", _after(t, "play")])
    if _has(t, "list", "tracks", "albums", "what music"):
        return Reply(RUN, "", ["music", "list"])
    return None


def _gaming(t, ctx):
    if _has(t, "play"):
        return Reply(RUN, "The Attendant starts it.", ["games", "play", _after(t, "play")])
    if _has(t, "emulators", "consoles"):
        return Reply(RUN, "", ["games", "emulators"])
    if _has(t, "list", "games", "what games"):
        return Reply(RUN, "", ["games", "list"])
    return None


def _home(t, ctx):
    if _has(t, "look around", "survey", "scan", "find devices", "what is on"):
        return Reply(RUN, "The Surveyor listens to the network; it contacts nothing.",
                     ["home", "survey"])
    if _has(t, "list", "devices"):
        return Reply(RUN, "", ["home", "list"])
    return None


def _bench(t, ctx):
    if _has(t, "ports", "plugged", "boards"):
        return Reply(RUN, "", ["bench", "ports"])
    if not (ctx or {}).get("project"):
        return Reply(SAY, "Open a project first: the Test Bench flashes and listens to the open "
                          "project's board.")
    if _has(t, "flash", "upload", "program it"):
        return Reply(RUN, "The Flasher puts the firmware on the board.",
                     [*_project(ctx), "bench", "flash"])
    if _has(t, "listen", "monitor", "serial"):
        return Reply(RUN, "The Serial Monitor listens for 10 s.", [*_project(ctx), "bench", "listen"])
    return None


def _storeroom(t, ctx):
    m = re.match(r"\s*(add|take|remove|use|used)\s+(?:(\d+)\s+)?(.+?)(?:\s+(?:in|on|from|at)\s+(.+))?$",
                 t, re.I)
    if m:
        verb = {"use": "take", "used": "take"}.get(m.group(1).lower(), m.group(1).lower())
        args = ["store", verb, m.group(3).strip()]
        if m.group(2) and verb != "remove":
            args += ["--qty", m.group(2)]
        if m.group(4) and verb == "add":
            args += ["--where", m.group(4).strip()]
        return Reply(RUN, "", args)
    if _has(t, "space", "room left", "how full"):
        return Reply(RUN, "", ["store", "space"])
    if _has(t, "drives", "usb"):
        return Reply(RUN, "", ["store", "drives"])
    if _has(t, "list", "what do i have", "stock", "parts"):
        return Reply(RUN, "", ["store", "list"])
    return None


def _doctors(t, ctx):
    if _has(t, "notes", "case notes"):
        return Reply(RUN, "", ["clinic", "notes"])
    if _has(t, "report"):
        return Reply(RUN, "", ["clinic", "report"])
    return Reply(RUN, "The Doctors look; nothing is changed.", ["clinic"])


def _studio(t, ctx):
    if _has(t, "kinds", "what kinds", "what can you make"):
        return Reply(RUN, "", ["studio", "kinds"])
    if re.match(r"\s*(?:list|my games|which games|what games)\b", t, re.I):
        return Reply(RUN, "", ["studio", "list"])
    if re.match(r"\s*(?:play|open)\s+\S", t, re.I):
        return Reply(RUN, "The game opens in its own window.", ["studio", "play", _after(t, "play", "open")])
    if re.match(r"\s*(?:check|test)\s+\S", t, re.I):
        return Reply(RUN, "The Tester runs it with no window.", ["studio", "check", _after(t, "check", "test")])
    return Reply(RUN, "Your idea: the Designer reads it, the Level Designer and Programmer build "
                      "it, the Tester runs it.", ["studio", "new", t])


HANDLERS = {"workshop": _workshop, "computer_lab": _computer_lab, "library": _library,
            "science": _science, "comms": _comms, "art_studio": _art_studio,
            "printshop": _printshop, "film": _film, "audio": _audio, "theatre": _theatre,
            "music": _music, "gaming": _gaming, "home": _home, "bench": _bench,
            "storeroom": _storeroom, "doctors": _doctors, "studio": _studio}

# What each department says it can do, when it does not understand (examples are
# the shape of a request, not answers: docs/design-rules.md 4b does not apply, no model reads them).
CAN_DO = {
    "workshop": "describe a thing to build; 'flooring 4.2 x 3.6 m'; 'run'; 'second opinion'",
    "computer_lab": "'build the firmware'; 'write the guide'",
    "library": "describe a story; 'look up <words>'; 'list'",
    "science": "'100 F to C'; 'solve x**2 = 9'; 'R=? V=5 V I=20 mA'; 'mean of 3 5 7'",
    "comms": "'letter to <name>: <words>'; 'email <name>: <words>'; 'open <site>'; 'contacts'",
    "art_studio": "'a tag saying SHED'; 'a box 80 mm wide'; 'kinds'; 'list'",
    "printshop": "'slice <model>'; 'list'",
    "film": "'make a film of <story>'; 'plan <story>'; 'list'",
    "audio": "'narrate <story>'; 'record'; 'list'",
    "theatre": "'play <video>'; 'check <video>'; 'cast'; 'list'",
    "music": "'play <track>'; 'cast'; 'list'",
    "gaming": "'play <game>'; 'list'; 'emulators'",
    "home": "'look around'; 'list'",
    "bench": "'flash it'; 'listen'; 'ports'",
    "storeroom": "'add 10 resistors in drawer 2'; 'take 2 resistors'; 'list'; 'space'",
    "doctors": "'see me'; 'notes'; 'report'",
    "studio": "your game idea ('a platformer where you play a fox who collects berries'); "
              "'play <game>'; 'check <game>'; 'list'",
}


def answer(key: str, text: str, ctx: dict | None = None) -> Reply:
    """What the department `key` does with the owner's `text`."""
    t = _words(text)
    if not t:
        return Reply(SAY, "Type what you would like done here: " + CAN_DO.get(key, "") + ".")
    handler = HANDLERS.get(key)
    got = handler(t, ctx) if handler else None
    if got is not None:
        return got
    from .gui import prompt_logic as L
    elsewhere, matched = L.department_for(t)
    hint = ""
    # Only when words matched: with none, department_for falls back to the Workshop.
    if matched and elsewhere != key:
        hint = f" That sounds like work for {called(elsewhere)}."
    here = called(key)
    return Reply(SAY, f"{here[0].upper() + here[1:]} did not understand that.{hint} Here you "
                      f"can say: {CAN_DO.get(key, 'what you would like')}.")


PLACES = ("library", "art_studio", "workshop", "computer_lab", "storeroom", "theatre", "music",
          "bench", "printshop", "film", "studio")


def called(key: str) -> str:
    """A department as a sentence names it: 'the Print Shop', 'Science'."""
    from .staff import DEPARTMENTS
    name = DEPARTMENTS[key].name if key in DEPARTMENTS else key
    return f"the {name}" if key in PLACES else name
