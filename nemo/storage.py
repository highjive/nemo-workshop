"""Where created work is kept, and saving it to the USB stick.

On NemoIso the home folder is in memory, and `nemo-sync` (a root-only
script the image installs, run every two minutes and at shutdown) copies
the projects and stories to NemoData on the boot stick. This asks it for
its status and to save now. Anywhere else there is no stick: the work is
already on a disk, and these say so and do nothing.
"""
from __future__ import annotations

import getpass
import subprocess
from pathlib import Path

SYNC = Path("/usr/local/sbin/nemo-sync")


def has_stick() -> bool:
    return SYNC.is_file()


def _run(action: str, as_root: bool) -> tuple[bool, str]:
    argv = [str(SYNC), action, getpass.getuser()]
    if as_root:
        argv = ["sudo", "-n"] + argv
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    text = (p.stdout or p.stderr or "").strip().splitlines()
    msg = text[-1] if text else f"exited {p.returncode}"
    return p.returncode == 0, msg.removeprefix("nemo-sync: ")


def status() -> str | None:
    """A sentence on where the work is kept, or None off a stick."""
    if not has_stick():
        return None
    return _run("status", as_root=False)[1]


def save_now() -> tuple[bool, str]:
    if not has_stick():
        return True, "work is kept on this computer's disk"
    return _run("save", as_root=True)
