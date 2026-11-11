"""A throwaway home directory for the whole test process.

D112: the suite isolated itself by patching HOME. On Linux that redirects
`~`; on Windows it does nothing, because Path.home() and expanduser() read
USERPROFILE there. The first run on the real AH531 therefore created
projects and stories in the owner's own folders, wrote sign-off entries to
his real audit log and overwrote the running mode's log file.

Every test module calls activate() before it imports nemo, so that module
level paths (config.CONFIG_HOME, modes.STATE) are computed inside the
sandbox too, and a test that forgets to patch anything still cannot reach
the real home. Per-test patches use home_env() so they redirect `~` on
both platforms.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Recorded before anything is redirected, so tests can assert against it.
REAL_HOME = Path(os.path.expanduser("~")).resolve()

_home: Path | None = None


def home_env(home, nemo_home=None) -> dict:
    """The environment that points `~` and NEMO_HOME at `home`."""
    home = str(home)
    return {"HOME": home, "USERPROFILE": home,
            "NEMO_HOME": str(nemo_home) if nemo_home else home + "/.nemo"}


def git_on():
    """A patch that lets project git run, for the tests of history."""
    from unittest import mock
    return mock.patch.dict(os.environ, {"NEMO_PROJECT_GIT": "on"})


def has_display() -> bool:
    """Whether a test may open a window.

    D117: every window test was guarded by os.environ.get("DISPLAY"). That
    is an X11 variable. Windows never sets it, so on the target's own
    operating system all 61 of them skipped and the desktop interface had
    never been exercised there.
    """
    if sys.platform.startswith("win"):
        try:
            import tkinter                                   # noqa: F401
        except ImportError:
            return False
        return os.environ.get("NEMO_TEST_NO_DISPLAY") != "1"
    return bool(os.environ.get("DISPLAY"))


def activate() -> Path:
    """Redirect this process's home to a temporary folder. Idempotent."""
    global _home
    if _home is None:
        _home = Path(tempfile.mkdtemp(prefix="nemo-test-home-")).resolve()
        atexit.register(shutil.rmtree, str(_home), ignore_errors=True)
        os.environ.update(home_env(_home))
        # Projects made by tests are not git repositories: git's start-up
        # was most of the suite's time on the AH531 (project._no_git). The
        # tests of history turn it back on with git_on().
        os.environ["NEMO_PROJECT_GIT"] = "off"
        # Nor do tests run the Writer's spelling checker (nemo/writer.py) unless
        # they ask: where Harper is installed every Reviewer check would call it.
        os.environ["NEMO_WRITER_CHECK"] = "off"
        # Nor does the Linguist speak aloud while windows are tested
        # (nemo/voice.py); a test that listens writes to a file instead.
        os.environ["NEMO_VOICE"] = "off"
        # Nor are audio cues played (nemo/cues.py).
        os.environ["NEMO_CUES"] = "off"
        # Nor does the enclosure step draw with whatever CADCraft this
        # machine has (nemo/drawings.py); its own tests turn it on.
        os.environ["NEMO_CADCRAFT"] = "off"
        # Nor bind stories as books with this machine's WordCraft (nemo/books.py).
        os.environ["NEMO_WORDCRAFT"] = "off"
        # Nor does the Archivist reuse one test's answers in another
        # (nemo/archivist.py); its own tests turn it on.
        os.environ["NEMO_ARCHIVE"] = "off"
        # Nor does Home's Gatekeeper stop the casting tests' stand-in
        # Chromecasts (nemo/home.py); its own tests turn it on.
        os.environ["NEMO_HOME_GATE"] = "off"
        # Every test runs as the laptop (nemo/machine.py), whatever GPU the
        # machine running it has; the desktop's own tests set it.
        os.environ["NEMO_MACHINE"] = "laptop"
        # Measured on the AH531 (KiCad 10.0.6): with USERPROFILE redirected,
        # every kicad-cli call creates "KiCad/10.0" in the current folder.
        # KICAD_CONFIG_HOME, KICAD_DOCUMENTS_HOME and a Documents folder in
        # the sandbox were each tried and did not stop it; the cause inside
        # KiCad is not known. So remove it afterwards, unless it was there
        # before we started and is therefore not ours.
        litter = Path.cwd() / "KiCad"
        if not litter.exists():
            atexit.register(shutil.rmtree, str(litter), ignore_errors=True)
    return _home
