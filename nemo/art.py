"""Nemo's own pictures (owner, 2026-10-29: "images for portraits only
accessible by Nemo, and don't show up in other menus"): the Artist's
department scenes and employee portraits.

They live in ~/.nemo/art, apart from the Storeroom's pictures shelf, which
the Theatre's Photo Curator, the Storeroom's PICTURES aisle and the drives'
sorting all read. Only the department views (gui IllustratedRoom) and the
cards drawn on the scenes use them.

  ~/.nemo/art/departments/<key>.png
  ~/.nemo/art/employees/<department>/<role>.png
  ~/.nemo/art/employees-first/...      the first set, kept

migrate() moves the ones painted before into the Storeroom's pictures shelf
here, once; a file already here is never overwritten. nemo-sync keeps the
folder on the stick (.nemo/art), so a booted Nemo has them too.
"""
from __future__ import annotations

import shutil
from pathlib import Path

KINDS = ("departments", "employees", "employees-first")


def home() -> Path:
    from .config import CONFIG_HOME
    return Path(CONFIG_HOME) / "art"


def scene(key: str) -> Path:
    return home() / "departments" / f"{key}.png"


def portrait(department: str, role: str) -> Path:
    return home() / "employees" / department / f"{role}.png"


def kept_on_stick() -> bool:
    """Whether this system keeps ~/.nemo/art: anywhere but a live NemoIso
    whose nemo-sync predates it (the image of 2026-10-26 does), where the
    home is in RAM and a moved painting would be gone after a restart."""
    sync = Path("/usr/local/sbin/nemo-sync")
    try:
        return not sync.is_file() or ".nemo/art" in sync.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def migrate(storeroom_root: Path) -> int:
    """Move the paintings from the Storeroom's pictures shelf into Nemo's
    own folder; returns how many files moved. Never overwrites; an old
    folder emptied by the move is removed. On an older stick image that
    would not keep the new folder they are copied instead, and stay on
    the shelf until the image is rebuilt."""
    move = kept_on_stick()
    old_root = Path(storeroom_root).expanduser() / "pictures"
    moved = 0
    for kind in KINDS:
        old = old_root / kind
        if not old.is_dir():
            continue
        for f in sorted(p for p in old.rglob("*") if p.is_file()):
            dest = home() / kind / f.relative_to(old)
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            (shutil.move if move else shutil.copy2)(str(f), str(dest))
            moved += 1
        if not move:
            continue
        for d in sorted((p for p in old.rglob("*") if p.is_dir()), reverse=True) + [old]:
            try:
                d.rmdir()                       # only when empty
            except OSError:
                pass
    return moved
