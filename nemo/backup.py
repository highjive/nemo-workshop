"""A backup of the owner's work, made by hand from the Storeroom (owner,
2026-10-21: "add to storehouse way to manually create a backup of nemo").

One zip file holding what the owner made and chose: the projects, stories,
the Storeroom's catalogue, the parts and datasheets added to the library,
and Nemo's settings. With it, MANIFEST.json: every file's size and sha256,
so verify() can say later whether the zip is whole.

What it leaves out, and why:
  the program, engine and models   reinstalled from the packages, hash-checked;
                                   the models alone are gigabytes
  ~/.nemo/keys                     the Researcher's key: a zip anyone holding it
                                   can read is no place for a key
  ~/.nemo/admin, safety.json       the admin and safety store: a backup put
                                   back would be a way round them (docs/design-rules.md 6)
  logs, slots, mode files          the server's own working files
  the Storeroom's videos and games the Theatre's and Gaming's shelves
                                   (2026-10-21): gigabytes, and the owner
                                   has the originals; pictures stay in
Nothing is deleted or changed by a backup; it only reads.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__

MANIFEST = "MANIFEST.json"
# Folders from config paths, each kept under its key's name in the zip.
FOLDERS = ("projects", "stories", "storeroom", "parts", "datasheets", "models", "studio")
# Files from ~/.nemo (config.CONFIG_HOME) that are the owner's settings.
SETTINGS = ("config.yaml", "gui.json", "offline.json",
            "home.json", "home-permissions.jsonl")   # Home's permissions and their log
# Storeroom shelves left out: large, and copies of what the owner has.
BIG_SHELVES = ("videos", "games", "music",
               "film-studio")     # the Film Studio's working files: made again from the plan
# Audio Nemo made and can make again: audiobooks (from the stories) and the
# copies readied for SD cards. Recordings are the owner's, and stay in.
REMADE = {("audio", "books"), ("audio", "sd-cards")}
# Kept from a big shelf all the same: the Music Room's playlists, small files
# the owner made, beside the music they list (owner, 2026-10-22).
KEPT_FROM_BIG = {("music", ".m3u")}


def _left_out(rel: tuple[str, ...]) -> bool:
    """Whether a file in the Storeroom, at this path inside it, stays out."""
    if not rel:
        return False
    if rel[0] in BIG_SHELVES:
        return not (len(rel) == 2 and (rel[0], Path(rel[1]).suffix.lower()) in KEPT_FROM_BIG)
    return tuple(rel[:2]) in REMADE


class BackupError(RuntimeError):
    """The backup could not be made; the message says why."""


@dataclass
class Made:
    path: Path
    files: int
    bytes: int
    left_out: list[str]          # sources that did not exist, said, not hidden


def default_folder() -> Path:
    return Path("~/nemo-backups").expanduser()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _inside(p: Path, folder: Path) -> bool:
    try:
        p.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def sources(cfg) -> list[tuple[str, Path]]:
    """(name in the zip, where it is) for everything a backup holds."""
    from .config import CONFIG_HOME
    out = [(key, cfg.path(f"paths.{key}")) for key in FOLDERS if cfg.get(f"paths.{key}")]
    out += [(f"settings/{name}", CONFIG_HOME / name) for name in SETTINGS]
    return out


def make(cfg, dest: Path | None = None, now: _dt.datetime | None = None) -> Made:
    """Write nemo-backup-<date>_<time>.zip into `dest` and return what went in."""
    dest = Path(dest or default_folder()).expanduser()
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"cannot make the folder {dest}: {exc}") from None
    stamp = (now or _dt.datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    final = dest / f"nemo-backup-{stamp}.zip"
    part = final.with_suffix(".zip.part")
    entries, total, left_out = [], 0, []
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for name, src in sources(cfg):
                if not src.exists():
                    left_out.append(name)
                    continue
                files = [src] if src.is_file() else sorted(
                    p for p in src.rglob("*") if p.is_file() and not p.is_symlink())
                for f in files:
                    # A backup folder inside a backed-up one would hold
                    # every earlier backup, and this one half written.
                    if _inside(f, dest):
                        continue
                    rel = f.relative_to(src).parts if name == "storeroom" else ()
                    if _left_out(rel):
                        continue
                    arc = name if src.is_file() else f"{name}/{f.relative_to(src).as_posix()}"
                    z.write(f, arc)
                    size = f.stat().st_size
                    entries.append({"path": arc, "bytes": size, "sha256": _sha256(f)})
                    total += size
            z.writestr(MANIFEST, json.dumps({
                "made": stamp, "nemo": __version__, "files": entries,
                "left_out": left_out}, indent=1))
        os.replace(part, final)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise BackupError(f"the backup could not be written to {dest}: {exc}") from None
    return Made(final, len(entries), total, left_out)


def verify(path: Path) -> list[str]:
    """What is wrong with this backup, or [] if every file is as recorded."""
    try:
        with zipfile.ZipFile(path) as z:
            try:
                manifest = json.loads(z.read(MANIFEST).decode("utf-8"))
            except KeyError:
                return [f"{MANIFEST} is missing: not a Nemo backup, or not whole"]
            have = set(z.namelist())
            faults = []
            for e in manifest.get("files", []):
                if e["path"] not in have:
                    faults.append(f"{e['path']} is missing")
                    continue
                if hashlib.sha256(z.read(e["path"])).hexdigest() != e["sha256"]:
                    faults.append(f"{e['path']} has changed")
            return faults
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"it cannot be read as a zip: {exc}"]


def listing(folder: Path | None = None) -> list[Path]:
    """The backups in `folder`, newest first."""
    folder = Path(folder or default_folder()).expanduser()
    return sorted(folder.glob("nemo-backup-*.zip"), reverse=True) if folder.is_dir() else []
