"""Finished work, on the Storeroom's Finished shelf (owner, 2026-11-11:
"Finished projects from which ever department gets sent to storehouse with
way to view all parts of project from that department").

Each department keeps its work where it always has (nemo-projects,
nemo-stories, the Storeroom's own shelves...), all of it saved to the stick
by nemo-sync; nothing is copied twice. What is FINISHED is decided by code,
department by department, from the files the department itself writes last
(a project's build guide, a story's story.md, a game's spec...). send()
records one on the shelf when a department finishes it; gather() looks for
every finished piece, older ones too, and keeps the list in
<storeroom>/finished/shelf.json. parts() lists everything a piece is made
of, folder by folder, so each part can be opened.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SHELF = "finished"
INDEX = "shelf.json"
SKIP_DIRS = {".git", ".speech", "__pycache__", ".godot", ".import"}


@dataclass
class Piece:
    department: str          # its key in staff.DEPARTMENTS
    title: str
    folder: str
    finished: str            # the newest of its files, YYYY-MM-DD HH:MM
    parts: int = 0           # how many files it is made of
    sent: str = ""           # when the department sent it here ("" = found by gather)

    @property
    def path(self) -> Path:
        return Path(self.folder)


@dataclass
class Source:
    department: str
    root: str                # a cfg path key, or "storeroom:<shelf>"
    done: tuple[str, ...]    # a piece is finished when ANY of these files is in its folder
    depth: int = 1           # how far below root its folders are
    title_from: str = ""     # a JSON file in the folder with a "title"
    note: str = field(default="")


# What "finished" means in each department: the file it writes last.
SOURCES = (
    Source("workshop", "paths.projects", ("BUILD.md",), note="a project with its build guide"),
    Source("workshop", "paths.projects:woodworker", ("floor.pdf",), note="a floor drawn to scale"),
    Source("library", "paths.stories", ("story.md",), note="a story written"),
    Source("art_studio", "paths.models", ("model.stl",), title_from="spec.json", note="a 3D model"),
    Source("studio", "paths.studio", ("project.godot",), title_from="spec.json", note="a game"),
    Source("film", "storeroom:film-studio", ("film.json",), note="a film"),
    Source("audio", "storeroom:audio/books", (".m3u",), note="an audio book"),
    Source("music", "storeroom:music", (".mid", ".wav", ".mp3", ".ogg"), note="a piece of music"),
)


def _root(cfg, spec: str) -> Path:
    if spec.startswith("storeroom:"):
        return cfg.path("paths.storeroom") / spec.split(":", 1)[1]
    key, _, sub = spec.partition(":")
    return cfg.path(key) / sub if sub else cfg.path(key)


def _is_done(folder: Path, done: tuple[str, ...]) -> bool:
    for d in done:
        if d.startswith("."):
            if any(f.suffix.lower() == d for f in folder.iterdir() if f.is_file()):
                return True
        elif (folder / d).is_file():
            return True
    return False


def _files(folder: Path) -> list[Path]:
    out = []
    for f in folder.rglob("*"):
        rel = f.relative_to(folder).parts
        if f.is_file() and not any(p in SKIP_DIRS or p.startswith(".") for p in rel):
            out.append(f)
    # A folder's own files first, then each folder inside it, in name order.
    return sorted(out, key=lambda f: (f.relative_to(folder).parts[:-1], f.name.lower()))


def _title(folder: Path, title_from: str) -> str:
    if title_from:
        try:
            t = json.loads((folder / title_from).read_text(encoding="utf-8")).get("title")
            if t:
                return str(t)
        except (OSError, ValueError, AttributeError):
            pass
    if (folder / "story.md").is_file():
        first = (folder / "story.md").read_text(encoding="utf-8", errors="replace").lstrip()
        if first.startswith("# "):
            return first[2:].splitlines()[0].strip()
    return folder.name


def piece(department: str, folder: Path, title_from: str = "", sent: str = "") -> Piece:
    files = _files(folder)
    newest = max((f.stat().st_mtime for f in files), default=folder.stat().st_mtime)
    when = _dt.datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M")
    return Piece(department, _title(folder, title_from), str(folder), when, len(files), sent)


def _index(cfg) -> Path:
    return cfg.path("paths.storeroom") / SHELF / INDEX


def _load(cfg) -> list[Piece]:
    try:
        rows = json.loads(_index(cfg).read_text(encoding="utf-8"))
        return [Piece(**r) for r in rows]
    except (OSError, ValueError, TypeError):
        return []


def _save(cfg, pieces: list[Piece]) -> None:
    p = _index(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(x) for x in pieces], indent=1), encoding="utf-8")
    tmp.replace(p)


def gather(cfg) -> list[Piece]:
    """Every finished piece in every department, newest first; the shelf
    list is kept up to date. When each was sent is kept from before."""
    sent = {(x.department, x.folder): x.sent for x in _load(cfg)}
    out: list[Piece] = []
    for src in SOURCES:
        root = _root(cfg, src.root)
        if not root.is_dir():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            try:
                if _is_done(folder, src.done):
                    out.append(piece(src.department, folder, src.title_from,
                                     sent.get((src.department, str(folder)), "")))
            except OSError:
                continue
    out.sort(key=lambda x: x.finished, reverse=True)
    try:
        _save(cfg, out)
    except OSError:
        pass
    return out


def send(cfg, department: str, folder: Path) -> Piece | None:
    """A department sends a piece it has just finished to the shelf."""
    folder = Path(folder)
    src = next((s for s in SOURCES if s.department == department
                and folder.is_dir() and _is_done(folder, s.done)), None)
    if src is None:
        return None
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    p = piece(department, folder, src.title_from, now)
    others = [x for x in _load(cfg) if (x.department, x.folder) != (department, str(folder))]
    try:
        _save(cfg, [p] + others)
    except OSError:
        pass
    return p


def by_department(pieces: list[Piece]) -> dict[str, list[Piece]]:
    out: dict[str, list[Piece]] = {}
    for p in pieces:
        out.setdefault(p.department, []).append(p)
    return out


def parts(p: Piece) -> list[tuple[str, Path]]:
    """(the folder within the piece it is in, "" for the top, the file), in order."""
    out = []
    for f in _files(p.path):
        rel = f.relative_to(p.path)
        out.append(("/".join(rel.parts[:-1]), f))
    return out


def department_name(key: str) -> str:
    from .staff import DEPARTMENTS
    d = DEPARTMENTS.get(key)
    return d.name if d else key
