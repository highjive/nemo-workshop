"""Newer versions of the departments' own tools (owner, 2026-11-11: "sort with doctor
in nemo so updates to all departments can be done"; he chose a check-up per
department AND a look for newer versions, downloads only on his yes).

LOOKING ONLY. Each tool's version that Nemo pins (what NemoDoc installs and the
code's sha256 pins vouch for) or finds installed is compared with its maker's
latest release. GitHub's API for most, npm's registry for REA. Nothing is
downloaded or installed here: a newer release changes the pins, the hashes and
often how Nemo drives the tool (OrcaSlicer's CLI, D221; Godot's API, O41), so it
is offered, never taken.

A version is called NEWER only where both sides read as numbers by the tool's own
pattern; otherwise both are said and nothing is judged. The last look is kept in
~/.nemo/clinic/updates.json, so the Doctors' ordinary visit reads it without the
network.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__

AGENT = f"Nemo/{__version__} (local workshop assistant; Doctors)"
TIMEOUT = 30
SEMVER = r"(\d+)\.(\d+)(?:\.(\d+))?"


@dataclass(frozen=True)
class Tool:
    key: str
    label: str
    department: str          # staff.DEPARTMENTS key it serves
    feed: str                # "github:<owner>/<repo>" or "npm:<package>"
    pattern: str             # numbers that order its versions, in its tags
    ours: object             # () -> the version Nemo pins or has, or None


def _llama():
    from .machine import CUDA_BUILD
    return CUDA_BUILD


def _sd():
    from .artist import ENGINE_ZIP
    m = re.search(r"/download/([^/]+)/", ENGINE_ZIP[1])
    return m.group(1) if m else None


def _whisper():
    from .speech import WHISPER_TAG
    return WHISPER_TAG


def _harper():
    from .writer import HARPER_TAG
    return HARPER_TAG


def _orca():
    from .printshop import SOURCE
    m = re.search(r"_V(" + SEMVER + r")_", SOURCE[0])
    return m.group(1) if m else None


def _ffmpeg():
    from .filmstudio import SOURCE
    m = re.search(r"ffmpeg-(" + SEMVER + r")-", SOURCE[0])
    return m.group(1) if m else None


def _freerouting():
    from .pcb import FREEROUTING
    m = re.search(r"-(" + SEMVER + r")\.jar", FREEROUTING[0])
    return m.group(1) if m else None


def _retroarch():
    from .gaming import RETROARCH_VERSION
    return RETROARCH_VERSION


def _godot():
    """The Godot found on this machine (its file name carries the version)."""
    from . import gamestudio
    exe = gamestudio.godot()
    m = re.search(r"Godot_v([\d.]+-[a-z]+\d*)", Path(exe).name) if exe else None
    return m.group(1) if m else None


def _rea():
    from . import toolkit
    mjs = toolkit.rea_cli()
    if mjs is None:
        return None
    pkg = Path(mjs).parent.parent / "package.json"
    try:
        return json.loads(pkg.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def _wordcraft():
    from .books import VERSION
    return VERSION


def _cadcraft():
    from .drawings import VERSION
    return VERSION


TOOLS = (
    Tool("llama.cpp", "llama.cpp (the language model engine)", "doctors",
         "github:ggml-org/llama.cpp", r"b(\d+)", _llama),
    Tool("stable-diffusion.cpp", "stable-diffusion.cpp (the Artist's engine)", "library",
         "github:leejet/stable-diffusion.cpp", r"master-(\d+)-", _sd),
    Tool("whisper.cpp", "whisper.cpp (hearing, desktop)", "library",
         "github:ggml-org/whisper.cpp", r"b(\d+)", _whisper),
    Tool("harper", "Harper (the Writer's spelling)", "library",
         "github:Automattic/harper", SEMVER, _harper),
    Tool("orcaslicer", "OrcaSlicer (the Print Shop)", "printshop",
         "github:SoftFever/OrcaSlicer", SEMVER, _orca),
    Tool("ffmpeg", "FFmpeg, Gyan's build (the Film Studio)", "film",
         "github:GyanD/codexffmpeg", SEMVER, _ffmpeg),
    Tool("freerouting", "Freerouting (the PCB Designer)", "workshop",
         "github:freerouting/freerouting", SEMVER, _freerouting),
    Tool("retroarch", "RetroArch (Gaming)", "gaming",
         "github:libretro/RetroArch", SEMVER, _retroarch),
    Tool("godot", "Godot (the Game Studio)", "studio",
         "github:godotengine/godot", SEMVER, _godot),
    Tool("rea", "REA (the Reverse Engineer)", "computer_lab",
         "npm:rea-agents", SEMVER, _rea),
    Tool("cadcraft", "CADCraft (the Workshop's drawings)", "workshop",
         "github:storytold/cadcraft", SEMVER, _cadcraft),
    Tool("wordcraft", "WordCraft (books and the pack PDF)", "library",
         "github:storytold/wordcraft", SEMVER, _wordcraft),
)


@dataclass
class Look:
    key: str
    label: str
    department: str
    ours: str | None
    latest: str | None
    newer: bool | None       # None: not known (not read, or not comparable)
    url: str = ""
    error: str = ""
    also: str = ""           # the maker's "latest", where it is tagged another way

    def line(self) -> str:
        said = self._line()
        return said + (f" (the maker's 'latest' is tagged {self.also})" if self.also else "")

    def _line(self) -> str:
        if self.error:
            return f"{self.label}: could not look ({self.error})"
        if self.ours is None:
            return f"{self.label}: not on this machine; the latest is {self.latest}"
        if self.newer:
            return f"{self.label}: {self.latest} is out; Nemo has {self.ours}"
        if self.newer is False:
            return f"{self.label}: {self.ours} is the latest"
        return f"{self.label}: Nemo has {self.ours}; the latest is {self.latest} (not compared)"


def numbers(pattern: str, version: str | None) -> tuple[int, ...] | None:
    """The numbers that order a version, by the tool's own pattern; None if it does not read."""
    m = re.search(pattern, version or "")
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


def is_newer(pattern: str, ours: str | None, latest: str | None) -> bool | None:
    a, b = numbers(pattern, ours), numbers(pattern, latest)
    if a is None or b is None:
        return None
    return b > a


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def latest(feed: str, pattern: str = SEMVER, get=_get) -> tuple[str, str, str]:
    """(version, its page, the maker's own "latest" tag where that reads otherwise)
    for a feed.

    On GitHub, the newest recent release that reads by the tool's own pattern.
    Build-numbered tools (b12282, master-1088-...) mark their builds pre-releases
    (2026-11-11: llama.cpp's "latest" was v0.9.0, its newest build b12282; whisper's
    b5454 is the pre-release twin of v1.9.5), so for them pre-releases count; for a
    numbered version (4.7.2) they do not: a 4.8 beta is not an update. If none
    reads, the maker's "latest", said but not compared."""
    kind, _, name = feed.partition(":")
    if kind == "github":
        builds = pattern != SEMVER
        rels = [r for r in get(f"https://api.github.com/repos/{name}/releases?per_page=40")
                if isinstance(r, dict) and not r.get("draft")
                and (builds or not r.get("prerelease"))]
        read = [(numbers(pattern, str(r.get("tag_name") or "")), r) for r in rels]
        read = [(n, r) for n, r in read if n is not None]
        if read:
            r = max(read, key=lambda x: x[0])[1]
            other = ""
            if builds:
                stable = get(f"https://api.github.com/repos/{name}/releases/latest")
                tag = str(stable.get("tag_name") or "")
                other = tag if tag and numbers(pattern, tag) is None else ""
            return str(r.get("tag_name") or ""), str(r.get("html_url") or ""), other
        r = get(f"https://api.github.com/repos/{name}/releases/latest")
        return str(r.get("tag_name") or ""), str(r.get("html_url") or ""), ""
    if kind == "npm":
        d = get(f"https://registry.npmjs.org/{name}/latest")
        return str(d.get("version") or ""), f"https://www.npmjs.com/package/{name}", ""
    raise ValueError(f"not a feed Nemo reads: {feed}")


def look(tools=TOOLS, get=_get) -> list[Look]:
    """Every tool's version against its maker's latest. One that cannot be read is
    said, and the rest still look."""
    out = []
    for t in tools:
        try:
            ours = t.ours()
        except Exception:                                       # noqa: BLE001
            ours = None
        try:
            new, url, other = latest(t.feed, t.pattern, get)
        except Exception as exc:                                # noqa: BLE001
            out.append(Look(t.key, t.label, t.department, ours, None, None,
                            error=f"{type(exc).__name__}: {exc}"))
            continue
        out.append(Look(t.key, t.label, t.department, ours, new or None,
                        is_newer(t.pattern, ours, new) if ours else None, url,
                        also=other))
    return out


def path() -> Path:
    from .clinic import notes_path
    return notes_path().parent / "updates.json"


def save(looks: list[Look], now: float | None = None) -> Path:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": now or time.time(), "tools": [asdict(x) for x in looks]},
                              indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def last() -> tuple[float, list[Look]] | None:
    """The last look kept, or None (never looked, or the file cannot be read)."""
    try:
        d = json.loads(path().read_text(encoding="utf-8"))
        return float(d["at"]), [Look(**x) for x in d["tools"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None
