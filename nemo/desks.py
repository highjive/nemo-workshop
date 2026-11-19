"""Each department laid out like the Workshop (owner, 2026-11-18: "fix so each
department has menu layout like workshop for their department"; he chose its own
list + tabs).

The Workshop shows, on the left, its list (Projects) and a "New project" button;
on the right, tabs for the chosen one's work. Every department now does the same
with its OWN things: the Library its stories, the Art Studio its models, the Music
Room its tracks... This module says, for each department, what that list is, what
is shown about the chosen entry, and what can be done with it. It reads; it never
changes a file. What an action does is a `nemo` command the department already has
(run in the department's box, gui/askbar.py) or a control in its own window, lit,
never pressed (casting: never unasked).

No model is asked here (docs/design-rules.md 4d): the lists are read from the
department's own folders and files.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Action:
    label: str
    argv: list = field(default_factory=list)     # nemo's arguments, run in the box
    button: str = ""                             # or: light this button in its window
    project: str = ""                            # or: open this project in the Workshop


@dataclass
class Entry:
    id: str
    label: str
    about: str = ""
    actions: list = field(default_factory=list)
    picture: Path | None = None                  # shown beside what is said, if it is there


@dataclass
class Desk:
    title: str                  # the list's heading, as the Workshop's "Projects"
    tab: str                    # the chosen one's tab, as the Workshop's "Brief"
    new: str                    # the button under it, as "New project"
    hint: str                   # what "New" says in the department's box
    entries: object = None      # cfg -> list[Entry]
    empty: str = "Nothing here yet."


def _size(p: Path) -> str:
    try:
        n = p.stat().st_size
    except OSError:
        return "size not known"
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _when(p: Path) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
    except OSError:
        return "not known"


# ------------------------------------------------------------------ the lists
def _projects(cfg):
    root = cfg.path("paths.projects")
    names = sorted(p.parent.name for p in root.glob("*/brief.yaml")) if root.exists() else []
    out = []
    for n in names:
        folder = root / n
        done = sorted(p.stem for p in (folder / ".nemo").glob("*.done")) if (folder / ".nemo").is_dir() else []
        out.append(Entry(n, n, f"Project folder: {folder}\nLast changed: {_when(folder / 'brief.yaml')}"
                         + (f"\nSteps done: {', '.join(done)}" if done else ""),
                         [Action("Open it in the Workshop", project=n),
                          Action("Where is it up to?", ["--project", n, "status"])]))
    return out


def _lab(cfg):
    out = []
    for e in _projects(cfg):
        fw = cfg.path("paths.projects") / e.id / "firmware"
        if not fw.is_dir():
            continue
        out.append(Entry(e.id, e.id, f"Firmware folder: {fw}",
                         [Action("Build the firmware", ["--project", e.id, "test"]),
                          Action("Write the guide", ["--project", e.id, "guide"]),
                          Action("Open it in the Workshop", project=e.id)]))
    return out


def _stories(cfg):
    from .gui import prompt_logic as L
    out = []
    for st in L.list_stories(cfg.path("paths.stories")):
        written = "story.md" in st["files"]
        folder = cfg.path("paths.stories") / st["name"]
        acts = [Action("Write it" if not written else "Write it again", ["story", "write", st["name"]])]
        if written:
            acts += [Action("Paint its cover", ["story", "cover", st["name"]]),
                     Action("Bind it as a book", ["story", "book", st["name"]]),
                     Action("Narrate it", ["audio", "narrate", st["name"]]),
                     Action("Make a film of it", ["film", "make", st["name"]])]
        out.append(Entry(st["name"], st["name"],
                         f"{'Written' if written else 'Asked for, not written yet'}.\n"
                         f"Asked: {st['asked']}\nFolder: {folder}", acts,
                         folder / "cover.png"))
    return out


def _models(cfg):
    from . import modelkit
    out = []
    for m in modelkit.models(cfg):
        out.append(Entry(m["name"], m["name"],
                         f"{'Passed the Editor' if m['passed'] else 'FAILED the Editor'}.\n"
                         f"Folder: {m['folder']}",
                         [Action("Its card", ["model", "card", m["name"]]),
                          # the Print Shop knows a model by its folder's name (printshop.models)
                          Action("Slice it for the printer", ["print", "slice", Path(m["folder"]).name])],
                         next((Path(m["folder"]) / f for f in ("model-top.png", "model-iso.png")
                               if m.get("kind") == "relief" or f == "model-iso.png"), None)))
    return out


def _stock(cfg):
    from . import storeroom
    out = []
    for i in storeroom.load(cfg.path("paths.storeroom")):
        out.append(Entry(i.key, f"{i.name} ({i.quantity})",
                         f"{i.name}: {i.quantity} in stock" + (f", in {i.where}" if i.where else "")
                         + (f"\nLibrary part: {i.part}" if i.part else "")
                         + (f"\nNotes: {i.notes}" if i.notes else ""),
                         [Action("Take one", ["store", "take", i.name]),
                          Action("Suggest a library part", ["store", "suggest", i.name])]))
    return out


def _shows(cfg):
    from . import theatre
    out = []
    for it in theatre.videos(cfg) + theatre.photos(cfg):
        pic = it.path if it.kind == "photo" else None
        acts = [Action("Play it here", ["theatre", "play", it.name])]
        if it.kind == "video":
            acts.append(Action("Will it cast?", ["theatre", "check", it.name]))
        acts.append(Action("Cast it...", button="Cast"))
        out.append(Entry(str(it.path), it.name, f"A {it.kind}, from the {it.source}.\n"
                         f"{_size(it.path)}, {_when(it.path)}\n{it.path}", acts, pic))
    return out


def _games(cfg):
    from . import gaming
    return [Entry(str(g.path), f"{g.name} ({g.console.name})",
                  f"{g.console.name} game.\n{_size(g.path)}\n{g.path}",
                  [Action("Play it", ["games", "play", g.name])])
            for g in gaming.games(cfg)]


def _tracks(cfg):
    from . import music
    out = [Entry(str(p), f"Playlist: {p.stem}", f"A playlist.\n{p}",
                 [Action("Play it", ["music", "play", p.stem])]) for p in music.playlists(cfg)]
    stems = music.shelf(cfg) / music.STEMS
    for d in sorted(p for p in stems.iterdir() if p.is_dir()) if stems.is_dir() else []:
        out.append(Entry(str(d), f"Stems: {d.name}", "Stems to mix (one file per instrument "
                         f"or voice), in the shelf's stems folder.\n{d}",
                         [Action("Mix them", ["music", "mix", d.name, d.name])]))
    for t in music.tracks(cfg):
        out.append(Entry(str(t.path), t.title, f"{t.title}\nArtist: {t.artist or 'not known'}\n"
                         f"Album: {t.album or 'not known'}\n{t.path}",
                         [Action("Play it", ["music", "play", t.title]),
                          Action("Cast it...", button="Cast")]))
    return out


def _listening(cfg):
    from . import audio
    return [Entry(str(it.path), it.title, f"A {it.kind}.\n{_size(it.path)}, {_when(it.path)}\n{it.path}",
                  [Action("Play it", ["music", "play", it.title])])
            for it in audio.listening(cfg)]


def _bench(cfg):
    out = []
    for e in _projects(cfg):
        if not (cfg.path("paths.projects") / e.id / "firmware").is_dir():
            continue
        out.append(Entry(e.id, e.id, "A project with firmware to put on its board.",
                         [Action("Flash it", ["--project", e.id, "bench", "flash"]),
                          Action("Listen to it", ["--project", e.id, "bench", "listen"]),
                          Action("Which ports?", ["bench", "ports"])]))
    return out


def _prints(cfg):
    from . import printshop
    return [Entry(str(m.stl), f"{m.name} ({m.where})", f"From the {m.where}.\n{m.stl}",
                  [Action("Slice it", ["print", "slice", m.name])])
            for m in printshop.models(cfg)]


def _films(cfg):
    from . import filmstudio as F, theatre
    out = [Entry(str(v.path), v.name, f"A finished film.\n{_size(v.path)}\n{v.path}",
                 [Action("Play it", ["theatre", "play", v.name]),
                  Action("Edit by hand (FilmCraft)", ["film", "edit", v.path.stem])])
           for v in theatre.videos(cfg)]
    out += [Entry(str(d), f"Story: {d.name}", "A story the Film Studio can make a film of.",
                  [Action("Plan the film", ["film", "plan", d.name]),
                   Action("Make the film", ["film", "make", d.name])]) for d in F.stories(cfg)]
    return out


def _devices(cfg):
    from . import home
    return [Entry(d.key, d.label, f"Address: {d.ip or 'not known'}\nAllowed: {d.permission}\n"
                  f"Last seen: {d.seen or 'not known'}",
                  [Action("Look around again", ["home", "survey"])])
            for d in home.known() if d.permission != "hidden"]


def _post(cfg):
    from . import comms
    out = [Entry(str(p), f"Draft: {p.stem}", f"{_when(p)}\n{p}", []) for p in comms.drafts(cfg)]
    out += [Entry("contact:" + c.name, f"Contact: {c.name}", f"{c.name}\n{c.email or 'no email'}"
                  + (f"\n{c.address}" if c.address else ""), []) for c in comms.contacts(cfg)]
    out += [Entry("site:" + b.url, f"Site: {b.name}", f"{b.name}\n{b.url}",
                  [Action("Open it", ["comms", "open", b.name])]) for b in comms.bookmarks(cfg)]
    return out


def _sheets(cfg):
    folder = cfg.path("paths.storeroom") / "science"
    files = sorted(folder.glob("*.md"), reverse=True) if folder.is_dir() else []
    out = []
    for p in files:
        try:
            first = p.read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
        except (OSError, IndexError):
            first = p.stem
        out.append(Entry(str(p), first, f"Worked {_when(p)}\n{p}", []))
    return out


def _cases(cfg):
    import json
    from . import clinic
    path = clinic.notes_path()
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for n, line in enumerate(reversed(lines[-50:])):
        try:
            c = json.loads(line)
        except ValueError:
            continue
        at = time.strftime("%Y-%m-%d %H:%M", time.localtime(c.get("at", 0)))
        finds = c.get("findings", [])
        out.append(Entry(f"case{n}", f"{at}: {len(finds)} finding(s)",
                         "\n".join(f"- {f.get('what') or f}" if isinstance(f, dict) else f"- {f}"
                                   for f in finds)
                         or "Nothing found.", []))
    return out


def _studio_games(cfg):
    from . import gamestudio as G
    return [Entry(str(g["folder"]), g["title"], f"A {g['kind']}.\n{g['folder']}",
                  [Action("Play it", ["studio", "play", g["title"]]),
                   Action("Test it", ["studio", "check", g["title"]])]) for g in G.games(cfg)]


DESKS = {
    "workshop": Desk("Projects", "Project", "New project", "Describe a thing to build, then press Ask.",
                     _projects, "No projects yet."),
    "computer_lab": Desk("Firmware", "Firmware", "New project", "Describe a thing to build in the Workshop; "
                         "its firmware comes here.", _lab, "No project has firmware yet."),
    "library": Desk("Stories", "Story", "New story", "Describe the story you would like, then press Ask.",
                    _stories, "No stories yet."),
    "art_studio": Desk("Models", "Model", "New model", "Say what to make: 'a tag saying SHED', "
                       "'a box 80 mm wide', or 'a relief of <picture>'.", _models, "No models yet."),
    "storeroom": Desk("Stock", "Item", "Add to stock", "Say 'add 10 resistors in drawer 2'.", _stock,
                      "Nothing in stock yet."),
    "theatre": Desk("Videos and pictures", "Show", "Add a video", "Put videos on the Storeroom's videos "
                    "shelf; they are listed here.", _shows, "No videos or pictures yet."),
    "gaming": Desk("Games", "Game", "Add a game", "Put your own game files on the games shelf "
                   "(one folder per console); they are listed here.", _games, "No games yet."),
    "music": Desk("Music", "Track", "Add music", "Put music on the Storeroom's music shelf, and "
                  "stems to mix in its stems folder (one folder a song); say 'mix <folder>' or "
                  "'master <track> like <reference>'.", _tracks, "No music yet."),
    "audio": Desk("Listening", "Listen", "Narrate a story", "Say 'narrate <story>'.", _listening,
                  "Nothing to listen to yet."),
    "bench": Desk("Boards", "Board", "Which ports?", "Say 'ports' to see what is plugged in.", _bench,
                  "No project has firmware to flash yet."),
    "printshop": Desk("Models to print", "Print", "Slice a model", "Say 'slice <model>'.", _prints,
                      "No models to print yet."),
    "film": Desk("Films", "Film", "Make a film", "Say 'make a film of <story>', 'edit <film> by "
                 "hand' or 'animate'.", _films, "No films yet."),
    "home": Desk("Devices", "Device", "Look around", "Say 'look around': the Surveyor listens to the "
                 "network and contacts nothing.", _devices, "No devices found yet."),
    "comms": Desk("Letters and contacts", "Post", "Write a letter", "Say 'letter to <name>: <words>'.",
                  _post, "No drafts, contacts or sites yet."),
    "science": Desk("Worked sheets", "Sheet", "Ask a question", "Say '100 F to C', 'solve x**2 = 9' or "
                    "'R=? V=5 V I=20 mA'.", _sheets, "No worked sheets yet."),
    "doctors": Desk("Case notes", "Case", "See the Doctors", "Say 'see me': the Doctors look; nothing "
                    "is changed.", _cases, "No case notes yet."),
    "studio": Desk("Games made here", "Game", "New game", "Describe your game idea, then press Ask.",
                   _studio_games, "No games made yet."),
}


def entries(key: str, cfg) -> tuple[list[Entry], str]:
    """(the department's entries, a problem reading them or '')."""
    desk = DESKS.get(key)
    if desk is None:
        return [], ""
    try:
        return desk.entries(cfg), ""
    except Exception as exc:            # one bad file must not close the department
        return [], f"Could not read the list: {exc}"
