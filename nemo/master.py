"""Master-authority operations: applying a signed floor, and cloning.

Physical presence is required to apply a floor document, because the
requirement was explicit and because it is the one restriction here that
genuinely narrows the attack surface: it removes remote application
entirely. It does not constrain the person holding the laptop, and nothing
can.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .signing import FloorDocument, SigningError, verify_floor

# Written at build time by tools/embed-key.py. A public key is not a secret,
# so shipping it in every clone is safe -- that is the whole reason this is
# asymmetric rather than a password.
MASTER_PUBLIC_KEY = ""


def _on_local_console() -> tuple[bool, str]:
    """Is this a physical console session rather than a remote one?"""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False, "this is an SSH session"
    if not sys.stdin.isatty():
        return False, "no interactive terminal (piped or scripted)"
    if sys.platform.startswith("win"):
        return True, "local console"
    tty = os.ttyname(sys.stdin.fileno()) if hasattr(os, "ttyname") else ""
    # A desktop terminal emulator is a pty; a true console is ttyN. Accept
    # both, since requiring a bare VT would be unusable in practice, but
    # report which was seen so the operator can judge.
    return True, f"local terminal ({tty or 'unknown'})"


def _is_removable(path: Path) -> tuple[bool, str]:
    """Does this path live on removable media?"""
    path = Path(path).resolve()
    if sys.platform.startswith("win"):
        try:
            import ctypes
            drive = str(path.drive) + "\\"
            # DRIVE_REMOVABLE = 2
            kind = ctypes.windll.kernel32.GetDriveTypeW(drive)
            return kind == 2, f"drive type {kind}"
        except (AttributeError, OSError) as exc:
            return False, str(exc)
    # Ask lsblk about the device itself rather than deriving a /sys path
    # from its name. Stripping trailing digits works for sdb1 but turns
    # mmcblk0p1 into "mmcblk0p" and nvme0n1p2 into "nvme0n1p", so an SD card
    # in the laptop's own slot was rejected as not removable.
    try:
        src = subprocess.run(["findmnt", "-no", "SOURCE", "--target",
                              str(path)], capture_output=True, text=True,
                             timeout=5).stdout.strip()
        if not src:
            return False, "could not determine the device"
        # -P emits KEY="value" pairs, which survive empty fields. lsblk
        # leaves TRAN blank on partitions, and an earlier revision split the
        # plain output on whitespace -- so a blank collapsed away and every
        # column after it shifted by one. -s walks to the parent disk, where
        # RM and TRAN are actually populated.
        raw = subprocess.run(["lsblk", "-sPno", "RM,TRAN,NAME", src],
                             capture_output=True, text=True,
                             timeout=5).stdout
        rows = [dict(re.findall(r'(\w+)="([^"]*)"', line))
                for line in raw.splitlines() if line.strip()]
        removable = any(r.get("RM") == "1" for r in rows)
        # Many modern USB sticks report RM=0. The transport is the better
        # signal for those; mmc covers the built-in card reader.
        via_usb = any(r.get("TRAN") in ("usb", "mmc") for r in rows)
        name = rows[-1].get("NAME", src) if rows else src
        return (removable or via_usb), f"{src} ({name})"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def apply_floor(doc_path: Path, store_dir: Path, minimum_serial: int = 0,
                require_physical: bool = True) -> tuple[dict, list[str]]:
    """Verify and install a signed floor document.

    Returns (values, warnings). Raises SigningError on any failure.
    """
    if not MASTER_PUBLIC_KEY:
        raise SigningError(
            "this build has no master public key embedded, so no signed "
            "floor can be verified. It was built without tools/embed-key.py.")

    warnings: list[str] = []

    if require_physical:
        on_console, how = _on_local_console()
        if not on_console:
            raise SigningError(
                f"physical presence required: {how}. A floor reset must be "
                "performed at the machine, not remotely.")
        removable, where = _is_removable(doc_path)
        if not removable:
            raise SigningError(
                f"the document must be presented on removable media "
                f"({where}). Copy it to a USB stick and run this again from "
                "that path.")
        warnings.append(f"applied from {where} at {how}")

    doc = FloorDocument.from_json(Path(doc_path).read_text(encoding="utf-8"))
    values = verify_floor(doc, MASTER_PUBLIC_KEY, minimum_serial)

    dest = Path(store_dir) / "floor.signed.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(Path(doc_path).read_text(encoding="utf-8"), encoding="utf-8")
    return values, warnings


def load_installed_floor(store_dir: Path) -> tuple[dict | None, int]:
    """The signed floor currently in force, if any, and its serial."""
    path = Path(store_dir) / "floor.signed.json"
    if not path.exists() or not MASTER_PUBLIC_KEY:
        return None, 0
    try:
        doc = FloorDocument.from_json(path.read_text(encoding="utf-8"))
        values = verify_floor(doc, MASTER_PUBLIC_KEY)
        return values, doc.serial
    except SigningError:
        # A stored floor that no longer verifies is not trusted. Falling
        # back to the compiled default is the safe direction: the default
        # is at least as restrictive as anything a signed document would
        # have relaxed.
        return None, 0


# ====================================================================
#  Clone hygiene
# ====================================================================

# Removed from every clone. A clone that carries the source machine's
# credential gives every recipient the same admin password, and a clone
# that carries its boot baseline locks on first boot because the hardware
# differs.
CLONE_EXCLUDE = [
    "admin/admin.cred",       # local admin credential
    "admin/admin.state",      # failure counters
    "admin/admin.session",    # live session token
    "admin/audit.log",        # the source machine's history
    "admin/boot.baseline",    # hardware-specific
    "admin/lock.state",
    # Maintenance identity and state. clone.id above all: if a clone
    # inherited its source's ID, a halt document issued for one machine
    # would halt every machine cloned from it, and target binding -- the
    # property that stops a single document being a universal kill switch --
    # would quietly stop working.
    "admin/clone.id",
    "admin/maint.state",      # a halted source must not produce halted clones
    "admin/maint.used",       # nonces are per-clone
    "mode.pid",
]

# Deliberately kept: the signed floor, the parts library, the prompts, and
# the embedded public key. None of these is a secret.
CLONE_KEEP = [
    "admin/floor.signed.json",
    "admin/policy.yaml",
]


def clone_manifest(home: Path) -> tuple[list[Path], list[Path]]:
    """What a clone drops and what it carries."""
    home = Path(home)
    drop = [home / rel for rel in CLONE_EXCLUDE if (home / rel).exists()]
    keep = [home / rel for rel in CLONE_KEEP if (home / rel).exists()]
    return drop, keep


def stage_clone(home: Path, source_tree: Path, dest: Path) -> dict:
    """Stage a clean copy of this install, ready to build a clone image.

    Copies the Nemo source tree and the portable parts of the state
    directory, applying CLONE_EXCLUDE. Does not build the ISO itself:
    that takes live-build, root, and far more time and disk than the
    AH531 has to spare, so it belongs on a faster machine.
    """
    home, source_tree, dest = Path(home), Path(source_tree), Path(dest)
    # A clone is built from a distribution folder. From a pip install the
    # "source tree" is site-packages, which has none of the installers,
    # services or docs, and would stage an unbootable fragment.
    markers = ("nemodoc", "NemoDoc.ps1", "pyproject.toml")
    if not any((source_tree / mk).exists() for mk in markers):
        raise FileNotFoundError(
            f"{source_tree} is not a Nemo distribution folder. Run 'nemo "
            "clone' from an install made with nemodoc or NemoDoc, not from "
            "a pip-installed package.")
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty")
    dest.mkdir(parents=True, exist_ok=True)

    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".git",
                                    "*.part", "models")
    for sub in ("nemo", "tests", "docs", "tools", "system",
                "packaging", "manual"):
        s = source_tree / sub
        if s.is_dir():
            shutil.copytree(s, dest / sub, ignore=ignore)
    for f in ("nemodoc", "pyproject.toml", "config.yaml", "README.md"):
        if (source_tree / f).is_file():
            shutil.copy2(source_tree / f, dest / f)

    carried, dropped = [], []
    state_out = dest / "seed-state"
    for rel in CLONE_KEEP:
        src = home / rel
        if src.exists():
            (state_out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, state_out / rel)
            carried.append(rel)
    for rel in CLONE_EXCLUDE:
        if (home / rel).exists():
            dropped.append(rel)

    return {"dest": str(dest), "carried": carried, "dropped": dropped}
