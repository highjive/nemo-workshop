"""The Theatre: video, streaming and photos (owner, 2026-10-21).

The owner's words: "Theatre allows video playback and casting to chromecast
from files stored in storehouse, or saved pictures also allows browser
access to stream again to chromecast", and "each employee handles different
video, streaming, photo":

  Projectionist   videos from the Storeroom's videos shelf: here, or cast
  Photo Curator   pictures from its pictures shelf, story covers and concept
                  drawings: here, or cast
  Streamer        opens Chrome for websites, to cast with Chrome's own button

Playing here hands the file to the computer's own player (VLC where it is
installed, else whatever the system opens it with). Casting is nemo/cast.py.
Nothing here asks the model.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import storeroom

VIDEO = {".mp4", ".m4v", ".webm", ".mkv", ".avi", ".mov", ".mpg", ".mpeg", ".wmv"}
PHOTO = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@dataclass
class Item:
    name: str
    path: Path
    kind: str           # "video" or "photo"
    source: str         # "Storeroom", "story cover", "concept"

    @property
    def castable(self) -> bool:
        from .cast import castable
        return castable(self.path) is not None


def _files(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in exts),
                  key=lambda p: p.name.lower())


def videos(cfg) -> list[Item]:
    """The Projectionist's: everything on the videos shelf."""
    shelf = storeroom.shelf(cfg.path("paths.storeroom"), "videos")
    return [Item(p.name, p, "video", "Storeroom") for p in _files(shelf, VIDEO)]


def photos(cfg) -> list[Item]:
    """The Photo Curator's: the pictures shelf, story covers, concept drawings."""
    shelf = storeroom.shelf(cfg.path("paths.storeroom"), "pictures")
    out = [Item(p.name, p, "photo", "Storeroom") for p in _files(shelf, PHOTO)]
    stories = cfg.path("paths.stories")
    if stories.is_dir():
        out += [Item(f"{p.parent.name} (cover)", p, "photo", "story cover")
                for p in sorted(stories.glob("*/cover.png"))]
    projects = cfg.path("paths.projects")
    if projects.is_dir():
        out += [Item(f"{p.parts[-3]}: {p.stem}", p, "photo", "concept")
                for p in sorted(projects.glob("*/concept/*.png"))]
    return out


def check(item: Item, model: str | None = None) -> tuple[bool | None, list[str]]:
    """The Projectionist's look inside a video before it is cast (owner,
    2026-10-22): its codecs, and whether this Chromecast model plays them
    (nemo/mediainfo.py). Pictures and sound are not looked at."""
    from . import mediainfo
    if item.kind != "video":
        return True, []
    try:
        return mediainfo.verdict(mediainfo.probe(item.path), model)
    except (OSError, mediainfo.MediaError) as exc:
        return None, [f"Could not look inside it: {exc}."]


def find(items: list[Item], name: str) -> Item | None:
    n = name.strip().lower()
    return (next((i for i in items if i.name.lower() == n), None)
            or next((i for i in items if i.path.stem.lower() == n), None))


# ------------------------------------------------------------ here
def player() -> str | None:
    """VLC, where it is installed."""
    for p in (shutil.which("vlc"), r"C:\Program Files\VideoLAN\VLC\vlc.exe",
              r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"):
        if p and Path(p).is_file():
            return p
    return None


def play_here(item: Item) -> str:
    """Open it on this computer; says with what."""
    if item.kind == "video" and player():
        subprocess.Popen([player(), str(item.path)])
        return "VLC"
    if sys.platform.startswith("win"):
        os.startfile(str(item.path))                # noqa: S606: the owner's own file
        return "the program Windows opens it with"
    opener = shutil.which("xdg-open")
    if not opener:
        raise RuntimeError("there is nothing here to open it with")
    subprocess.Popen([opener, str(item.path)])
    return "the program this desktop opens it with"


# ------------------------------------------------------------ streaming
def browser() -> str | None:
    """Chrome (or Chromium, or Edge, which casts too)."""
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              shutil.which("chromium"), shutil.which("chromium-browser"),
              shutil.which("google-chrome"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if p and Path(p).is_file():
            return p
    return None


def stream(url: str = "") -> str:
    """The Streamer: open Chrome (at `url`, if given). Casting is then
    Chrome's own: its menu, Cast. Returns which browser was opened."""
    b = browser()
    if b is None:
        raise RuntimeError("Chrome is not installed (on NemoIso, Chromium is in the "
                           "package list of the next image)")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    subprocess.Popen([b] + ([url] if url else []))
    return Path(b).stem


# ------------------------------------------------------------ the Writer
# A title and a line for each video and picture (owner's choice, 2026-10-21),
# the owner's to write, kept in the Storeroom's captions.json; until written,
# the title is the file's name made readable.
def _captions_path(cfg) -> Path:
    return cfg.path("paths.storeroom") / "captions.json"


def _caption_key(cfg, item: Item) -> str:
    try:
        return item.path.relative_to(cfg.path("paths.storeroom")).as_posix()
    except ValueError:
        return str(item.path)


def captions(cfg) -> dict:
    import json
    try:
        return json.loads(_captions_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def caption(cfg, item: Item) -> tuple[str, str]:
    """(title, line): the owner's, or a title made from the file's name."""
    rec = captions(cfg).get(_caption_key(cfg, item), {})
    plain = item.path.stem.replace("_", " ").replace("-", " ").strip()
    return rec.get("title") or plain, rec.get("line", "")


def write_caption(cfg, item: Item, title: str, line: str = "") -> None:
    import json
    data = captions(cfg)
    if title.strip() or line.strip():
        data[_caption_key(cfg, item)] = {"title": title.strip(), "line": line.strip()}
    else:
        data.pop(_caption_key(cfg, item), None)
    p = _captions_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")
