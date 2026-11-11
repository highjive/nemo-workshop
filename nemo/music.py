"""The Music Room: your music, played here or cast (owner, 2026-10-21).

  Player   plays tracks here (VLC, which takes a whole list in order)
  DJ       casts a list to the Chromecast, one track after another over one
           connection, and lets the Chromecast go at the end (cast.Queue)
  Writer   keeps playlists: plain .m3u files beside the music, which other
           players read too

The music is the owner's own, on the Storeroom's music shelf, arranged as he
likes. Each file's own tags give its title, artist, album and track number
(nemo/tags.py, Nemo's own reader, 2026-10-22); where a file has none,
Artist/Album/track folders show as artist and album, as before. What was
read is kept in ~/.nemo/music-tags.json by each file's size and date, so a
big shelf is not read again each time. Nemo downloads nothing, and nothing
here asks the model.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import storeroom

AUDIO = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav", ".wma"}


@dataclass
class Track:
    title: str
    artist: str
    album: str
    path: Path
    number: int = 0          # its track number, from its tags; 0 when not known

    @property
    def castable(self) -> bool:
        from .cast import castable
        return castable(self.path) is not None


def shelf(cfg) -> Path:
    return storeroom.shelf(cfg.path("paths.storeroom"), "music")


def _tag_cache() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "music-tags.json"


def numbered(stem: str) -> tuple[int, str]:
    """A file name's track number and title: "01 Low Tone", "1. Low Tone" and
    "01 - Low Tone" are track 1, "Low Tone" (2026-11-06: an untagged file's
    title kept its number, and a playlist could not find it by its name).
    A name that is all number ("1984") keeps it."""
    import re
    m = re.match(r"^(\d{1,3})(?:\s*[-.)_]\s*|\s+)(\S.*)$", stem)
    return (int(m[1]), m[2].strip()) if m else (0, stem)


def tracks(cfg) -> list[Track]:
    """Every track on the music shelf, by artist, album, track number and
    name. Tags first; the folders where a file has none."""
    import json
    from . import tags
    root = shelf(cfg)
    if not root.is_dir():
        return []
    try:
        cache = json.loads(_tag_cache().read_text(encoding="utf-8"))
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    fresh, out = {}, []
    for p in root.rglob("*"):
        if not (p.is_file() and p.suffix.lower() in AUDIO):
            continue
        st = p.stat()
        stamp = f"{st.st_size}:{int(st.st_mtime)}"
        rel = p.relative_to(root).as_posix()
        kept = cache.get(rel)
        found = kept["tags"] if isinstance(kept, dict) and kept.get("stamp") == stamp             else tags.read(p)
        fresh[rel] = {"stamp": stamp, "tags": found}
        parts = p.relative_to(root).parts[:-1]
        number, title = numbered(p.stem)
        out.append(Track(found.get("title") or title,
                         found.get("artist") or (parts[0] if parts else ""),
                         found.get("album") or (parts[1] if len(parts) > 1 else ""),
                         p, int(found.get("number") or number)))
    if fresh != cache:
        try:
            _tag_cache().parent.mkdir(parents=True, exist_ok=True)
            _tag_cache().write_text(json.dumps(fresh, indent=0), encoding="utf-8")
        except OSError:
            pass                       # only a cache: the tags are read again next time
    return sorted(out, key=lambda t: (t.artist.lower(), t.album.lower(), t.number,
                                      t.path.name.lower()))


def find(found: list[Track], name: str) -> list[Track]:
    """A track by its name, or every track of an artist or album so named."""
    n = name.strip().lower()
    exact = [t for t in found if n in (t.title.lower(), t.path.name.lower(), t.path.stem.lower())]
    return exact or [t for t in found if n in (t.artist.lower(), t.album.lower())]


# ------------------------------------------------------------ playlists
def playlists(cfg) -> list[Path]:
    root = shelf(cfg)
    return sorted(root.glob("*.m3u")) if root.is_dir() else []


def save_playlist(cfg, name: str, chosen: list[Track]) -> Path:
    """The Writer: an .m3u of these tracks, paths relative to the shelf."""
    import re
    slug = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip()
    if not slug or not chosen:
        raise ValueError("a playlist needs a name and at least one track")
    root = shelf(cfg)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{slug}.m3u"
    lines = ["#EXTM3U"] + [t.path.relative_to(root).as_posix() for t in chosen]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_playlist(cfg, path: Path) -> list[Track]:
    """The tracks a playlist names that are still on the shelf, in order."""
    root = shelf(cfg)
    by_path = {t.path.resolve(): t for t in tracks(cfg)}
    out = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            t = by_path.get((root / line).resolve())
            if t:
                out.append(t)
    return out


# ------------------------------------------------------------ playing
def play_here(chosen: list[Track]) -> str:
    """The Player: the tracks in order, in VLC (or the system's player, which
    takes only the first)."""
    from . import theatre
    if not chosen:
        raise ValueError("choose a track first")
    vlc = theatre.player()
    if vlc:
        subprocess.Popen([vlc, *[str(t.path) for t in chosen]])
        return "VLC"
    item = theatre.Item(chosen[0].title, chosen[0].path, "video", "music")
    return theatre.play_here(item)
