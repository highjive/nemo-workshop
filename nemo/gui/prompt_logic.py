"""The prompt window's decisions, with no window: what a request is, what
to call it, and where a story is kept.

The prompt window is where Nemo opens at boot (owner's redesign,
2026-10-17): a pulsing orb, a box to type in, later a microphone. A request
is either something to design and build, which becomes a project and goes
through the seven steps, or a story. Which one is decided here, by words,
not by the model: it is asked nothing until it has a job to do (4f).
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

# Words that make a request a story rather than a thing to build. Whole
# words only: "storyboard a lamp housing" is not a story.
_STORY = re.compile(r"\b(story|stories|tale|novel|novella|chapter|chapters|"
                    r"episode|episodes|screenplay|script for|fiction|fable|"
                    r"short story|bedtime story|plot|character arc)\b", re.I)
# ...unless it is plainly hardware: "a story box that plays a tale when a
# tag is placed" is a device.
_HARDWARE = re.compile(r"\b(circuit|esp32|pico|arduino|sensor|led|leds|"
                       r"speaker|battery|enclosure|housing|pcb|wire|wiring|"
                       r"firmware|servo|motor|relay|rfid|button|plays? (?:a |the )?"
                       r"(?:sound|track|audio))\b", re.I)


def kind_of(request: str) -> str:
    """'story' or 'design'. A request naming hardware is a design even if
    it mentions a story; with neither, it is a design, the workshop's job."""
    if _HARDWARE.search(request):
        return "design"
    return "story" if _STORY.search(request) else "design"


_FILLER = {"a", "an", "the", "i", "me", "my", "want", "would", "like", "to",
           "make", "build", "design", "create", "write", "please", "can",
           "you", "could", "for", "of", "that", "which", "with", "and",
           "about", "need", "some", "new", "nemo", "help", "story", "short",
           "tale", "novel", "who", "is", "it"}


def name_for(request: str, taken: set[str] | None = None) -> str:
    """A short name from the request's own words, unique among `taken`
    (compared as slugs). Fits the project-name rule: letters, numbers,
    spaces, hyphens, up to 48 characters."""
    # An apostrophe joins its word (2026-11-06: "a lighthouse keeper's cat"
    # was named "children-lighthouse-keeper-s").
    words = [w for w in re.findall(r"[A-Za-z0-9]+", re.sub(r"['’]", "", request))
             if w.lower() not in _FILLER]
    base = " ".join(words[:4])[:40].strip() or "untitled"
    taken = {t.lower() for t in (taken or set())}
    name, n = base, 2
    while _slug(name) in taken:
        name = f"{base} {n}"; n += 1
    return name


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-")


# ----------------------------------------------------------------- stories
# A story is a folder under paths.stories (the stick's NemoData keeps it).
# Until the employees can write one, the folder holds the request, so it is
# in the Story list and nothing asked for is lost.

REQUEST = "request.md"


def file_story(root: Path, request: str, now: _dt.datetime | None = None) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    taken = {p.name for p in root.iterdir() if p.is_dir()}
    folder = root / _slug(name_for(request, taken))
    folder.mkdir()
    stamp = (now or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    (folder / REQUEST).write_text(f"# Asked for on {stamp}\n\n{request.strip()}\n",
                                  encoding="utf-8")
    return folder


def list_stories(root: Path) -> list[dict]:
    """Every story folder, newest first: its name, when it was last
    changed, the first line of what was asked for, and its files."""
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        files = sorted(p for p in d.rglob("*") if p.is_file())
        changed = max([p.stat().st_mtime for p in files] or [d.stat().st_mtime])
        asked = ""
        req = d / REQUEST
        if req.is_file():
            lines = [l for l in req.read_text(encoding="utf-8", errors="replace").splitlines()
                     if l.strip() and not l.startswith("#")]
            asked = lines[0] if lines else ""
        out.append({"name": d.name, "path": d, "changed": changed,
                    "asked": asked, "files": [str(p.relative_to(d)) for p in files]})
    return sorted(out, key=lambda s: s["changed"], reverse=True)


# ---------------------------------------------------------------- which department
# The home scene (owner, 2026-10-22): Nemo asks what you want and answers
# with the department that does it, its card and its scene. Chosen by words,
# not by the model, as kind_of() is. Each department's words, in roster
# order; the most matches wins, and a tie goes to the earlier department.
DEPARTMENT_WORDS = {
    "library": r"stor(?:y|ies)|tale|novel|chapters?|poem|look (?:it )?up|wikipedia|research|"
               r"book about|write (?:me )?a",
    "art_studio": r"draw|paint(?:ing)?|picture of|illustrat\w*|concept|3d model|model of|"
                  r"plaque|sculpt\w*|replica|tag with",
    "workshop": r"circuit|esp32|pico|arduino|sensor|leds?|enclosure|housing|pcb|wiring|"
                r"servo|motor|relay|rfid|device|gadget|build (?:a|an|me)|"
                r"floor(?:ing)?|laminate|skirting|woodwork",
    "computer_lab": r"firmware|code|program(?:me)?|compile|reverse engineer|ghidra",
    "storeroom": r"parts? I have|in stock|stock|inventory|catalogue|back ?up|shelf|shelves",
    "theatre": r"watch|videos?|photos?|cast|chromecast|youtube|tv",
    "gaming": r"games?|play (?:a |the )?(?:nes|snes|game boy|mega drive)|playstation|ps1|retro|emulat\w*|console",
    "music": r"music|songs?|playlists?|albums?|tracks?|dj",
    "audio": r"audiobook|podcast|record(?:ing)?|narrat\w*|sound ?board|sd card|dfplayer",
    "bench": r"flash|upload|serial|monitor|test the board|on the board",
    "printshop": r"3d print|print (?:it|this|a|the)|slice|g-?code|kobra|filament",
    "film": r"make a (?:film|movie)|film of|movie|slideshow|trailer|join (?:the )?clips|edit (?:my )?video",
    "home": r"network|wi-?fi devices|smart home|router|devices at home|what is on my",
    "comms": r"write (?:a |an )?(?:letter|email)|e-?mail|letter to|send (?:a )?message|"
             r"browse|website|web page|social media|facebook|instagram|twitter|post on",
    "science": r"convert|units?|equation|solve|maths?|calculat\w*|integrat\w*|differentiat\w*|"
               r"physics|formula|statistics|average|spreadsheet|excel|xlsx|how many \w+ in",
    "doctors": r"wrong|broken|error|crash\w*|not working|diagnos\w*|slow|fix it",
    "studio": r"platformer|game idea|godot|game studio|(?:make|design|build|create|invent) "
              r"(?:me |us )?(?:a|an|my|our) (?:\w+ )?(?:video )?game|game where|game in which",
}
_DEPT_RES = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in DEPARTMENT_WORDS.items()}


def department_for(request: str) -> tuple[str, list[str]]:
    """The department for a request, and the words that chose it. A request
    with none of them goes as kind_of() says: a story to the Library, the
    rest to the Workshop."""
    # More matches win; between equal counts the longer words, which say
    # more ("make a film" over "story" in "make a film of my story").
    best, words, score = "", [], (0, 0)
    for key, rx in _DEPT_RES.items():
        found = [m.group(0) for m in rx.finditer(request)]
        here = (len(found), sum(len(w) for w in found))
        if found and here > score:
            best, words, score = key, found, here
    if not best:
        return ("library" if kind_of(request) == "story" else "workshop"), []
    if best == "library" and _HARDWARE.search(request):    # a story box is a device
        return "workshop", [m.group(0) for m in _HARDWARE.finditer(request)]
    return best, words


def named_department(request: str) -> str | None:
    """The department he NAMES ("go to the Print Shop", "open Science", or
    just "Print Shop"), or None. Nemo changes department only when told
    (owner, 2026-10-23); department_for() only suggests."""
    from ..staff import DEPARTMENTS
    text = request.strip().lower().rstrip(".!?")
    text = re.sub(r"^(?:please\s+)?(?:go to|open|take me to|switch to|show me|change to)\s+(?:the\s+)?",
                  "", text)
    for key, d in DEPARTMENTS.items():
        if text in (d.name.lower(), key.replace("_", " ")):
            return key
    return None
