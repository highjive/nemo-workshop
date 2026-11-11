"""The Storeroom as a 90s video store (owner, 2026-10-21): every kind of
file Nemo keeps, shelved by aisle, for the window (gui VideoStore).

  BOOKS     the Library's stories (story.md, and a cover if painted)
  GAMES     games on the games shelf, by console (nemo/gaming.py)
  VIDEOS    the videos shelf (nemo/theatre.py)
  MUSIC     the music shelf (nemo/music.py)
  AUDIO     audiobooks, podcasts and recordings (nemo/audio.py)
  PICTURES  the pictures shelf, story covers, concept drawings
  PARTS     the catalogue of parts on hand (nemo/storeroom.py)

Each case says what can be done with it; the departments do it. Nothing
here asks the model, and looking changes nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

AISLES = ("BOOKS", "AUDIO", "GAMES", "VIDEOS", "MUSIC", "PICTURES", "PARTS")


@dataclass
class Case:
    aisle: str
    title: str
    subtitle: str
    actions: tuple[str, ...]
    thing: object = field(default=None, repr=False)    # what the action is done to


def _books(cfg) -> list[Case]:
    from .gui import prompt_logic
    out = []
    for st in prompt_logic.list_stories(cfg.path("paths.stories")):
        folder = Path(st["path"])
        written = (folder / "story.md").is_file()
        acts = (("Read",) if written else ()) + (("Show cover",) if (folder / "cover.png").is_file() else ())
        title = st["name"].replace("-", " ").strip().capitalize()
        out.append(Case("BOOKS", title, "written" if written else "not written yet",
                        acts or ("Open the folder",), folder))
    return out


def _games(cfg) -> list[Case]:
    from . import gaming
    return [Case("GAMES", g.name, g.console.name, ("Play",), g) for g in gaming.games(cfg)]


def _videos(cfg) -> list[Case]:
    from . import theatre
    return [Case("VIDEOS", theatre.caption(cfg, i)[0], "castable" if i.castable else "plays here only",
                 ("Play here", "Cast...") if i.castable else ("Play here",), i)
            for i in theatre.videos(cfg)]


def _audio(cfg) -> list[Case]:
    from . import audio
    return [Case("AUDIO", l.title, l.kind, ("Play here", "Cast...") if _castable(l.path)
                 else ("Play here",), l) for l in audio.listening(cfg)]


def _castable(path) -> bool:
    from .cast import castable
    return castable(path) is not None


def _music(cfg) -> list[Case]:
    from . import music
    return [Case("MUSIC", t.title, t.artist or t.album or "music",
                 ("Play here", "Cast...") if t.castable else ("Play here",), t)
            for t in music.tracks(cfg)]


def _pictures(cfg) -> list[Case]:
    from . import theatre
    return [Case("PICTURES", theatre.caption(cfg, i)[0].replace(" (cover)", ""),
                 i.source, ("Show", "Cast..."), i)
            for i in theatre.photos(cfg)]


def _parts(cfg) -> list[Case]:
    from . import storeroom
    out = []
    for i in storeroom.load(cfg.path("paths.storeroom")):
        sub = f"x{i.quantity}" + (f", {i.where}" if i.where else "")
        out.append(Case("PARTS", i.name, sub, ("Details",), i))
    return out


def shelves(cfg) -> dict[str, list[Case]]:
    """Every aisle and its cases. An aisle that cannot be read is empty, and
    says why in its one case."""
    makers = {"BOOKS": _books, "AUDIO": _audio, "GAMES": _games, "VIDEOS": _videos,
              "MUSIC": _music,
              "PICTURES": _pictures, "PARTS": _parts}
    out = {}
    for aisle in AISLES:
        try:
            out[aisle] = makers[aisle](cfg)
        except Exception as exc:                                # noqa: BLE001
            out[aisle] = [Case(aisle, "Cannot be read", str(exc)[:60], ())]
    return out


EMPTY = {
    "BOOKS": "No stories yet: ask for one in the prompt window.",
    "GAMES": "No games yet: put your own game files in the games shelf.",
    "VIDEOS": "No videos yet: put them in the videos shelf.",
    "MUSIC": "No music yet: put it in the music shelf.",
    "AUDIO": "No audiobooks or recordings yet: the Audio department makes them.",
    "PICTURES": "No pictures yet: put them in the pictures shelf.",
    "PARTS": "No parts yet: add them in the parts catalogue.",
}
