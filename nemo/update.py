"""Updates once NemoIso has booted (owner, 2026-10-23: "look at getting
updates once boots into nemo").

The newer Nemo is the NemoWin.zip on the Windows disk (C:\\Nemo\\dist), which
nemodoc finds READ-ONLY, as it finds the models, and names in NEMO_UPDATE_ZIP.
`git archive` writes the commit into the zip's comment and the commit's time
into every entry (the "UT" extra field, UTC), so newer is judged by the
commit's time against the image's (/opt/nemo/COMMIT and COMMIT_TIME, or the
time of the image's own files, which tar kept from the same archive).

On his yes it is unpacked into ~/.nemo/updates/<commit>, checked (every entry
read back by its CRC; Nemo imports from it in a fresh Python), and
~/.nemo/updates/use names it; nemodoc then starts Nemo with PYTHONPATH on it.
On a live boot the home is in RAM, so after a restart it is offered again:
the zip stays on the Windows disk and the image is never changed.

LIMITS, said plainly: the zip is not signed (the image's own hash list is
not either), so it is trusted as the owner's own file on his own disk; an
update that needs a library the image lacks fails the import check and is
refused; the image's programs (llama-server, sd-cli, RetroArch) do not change.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

PREFIX = Path(os.environ.get("NEMO_PREFIX", "/opt/nemo"))
ROOT = "NemoWin/"


@dataclass
class Found:
    zip: Path
    commit: str
    time: int          # commit time, seconds since 1970 (UTC)


def _home() -> Path:
    return Path(os.environ.get("NEMO_UPDATES", Path.home() / ".nemo" / "updates"))


def _ut_time(info: zipfile.ZipInfo) -> int | None:
    """The modification time from an entry's "UT" extra field (UTC), if any."""
    extra, i = info.extra, 0
    while i + 4 <= len(extra):
        tag, size = struct.unpack("<HH", extra[i:i + 4])
        if tag == 0x5455 and size >= 5 and extra[i + 4] & 1:
            return struct.unpack("<I", extra[i + 5:i + 9])[0]
        i += 4 + size
    return None


def read_zip(path: Path) -> Found:
    """The commit and its time; ValueError if this is not a NemoWin zip."""
    with zipfile.ZipFile(path) as z:
        commit = z.comment.decode("ascii", "replace").strip()
        if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            raise ValueError("it carries no commit (not made by git archive)")
        names = z.namelist()
        if ROOT + "nemo/__init__.py" not in names:
            raise ValueError("it has no nemo package")
        times = [t for t in (_ut_time(i) for i in z.infolist()) if t]
        if not times:
            raise ValueError("its entries carry no time")
        return Found(path, commit, max(times))


def image() -> tuple[str, int]:
    """The running image's commit and commit time ("", 0 when not known)."""
    commit = ""
    try:
        commit = (PREFIX / "COMMIT").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        when = int((PREFIX / "COMMIT_TIME").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        try:            # images before COMMIT_TIME: tar kept the commit's time
            when = int((PREFIX / "app" / "nemo" / "__init__.py").stat().st_mtime)
        except OSError:
            when = 0
    return commit, when


def available(zip_path: str | None = None) -> Found | None:
    """The newer Nemo on the Windows disk, or None (none, unreadable, or not newer)."""
    zip_path = zip_path or os.environ.get("NEMO_UPDATE_ZIP", "")
    if not zip_path or not Path(zip_path).is_file():
        return None
    try:
        found = read_zip(Path(zip_path))
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    commit, when = image()
    if found.commit == commit or found.time <= when:
        return None
    # D204: the update already chosen is not a newer Nemo. Compared with the
    # image alone, it was offered again after it had been applied.
    used = in_use()
    if used is not None and used.name == found.commit[:12]:
        return None
    return found


def in_use() -> Path | None:
    """The unpacked update nemodoc should start, if one was chosen and is whole."""
    try:
        dest = Path((_home() / "use").read_text(encoding="utf-8").strip())
    except OSError:
        return None
    return dest if (dest / "nemo" / "__init__.py").is_file() else None


def running() -> Path | None:
    """The update this very process was started from, if it was."""
    used = in_use()
    path = os.environ.get("PYTHONPATH", "")
    return used if used is not None and str(used) in path.split(os.pathsep) else None


def apply(found: Found) -> Path:
    """Unpack, check, and choose it. Raises RuntimeError with the reason; on
    any failure nothing is chosen and the half-made folder is removed."""
    home = _home()
    dest = home / found.commit[:12]
    tmp = home / (found.commit[:12] + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        with zipfile.ZipFile(found.zip) as z:
            bad = z.testzip()
            if bad:
                raise RuntimeError(f"{bad} is damaged in the zip")
            for info in z.infolist():
                name = info.filename
                if not name.startswith(ROOT) or ".." in Path(name).parts or info.is_dir():
                    continue
                out = tmp / name[len(ROOT):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(info))
        env = dict(os.environ, PYTHONPATH=str(tmp))
        run = subprocess.run([sys.executable, "-c", "import nemo.cli, nemo.gui.app"],
                             env=env, cwd=str(tmp), capture_output=True, text=True, timeout=120)
        if run.returncode != 0:
            last = (run.stderr.strip().splitlines() or ["no reason given"])[-1]
            raise RuntimeError("the new Nemo does not start with this image's libraries: " + last)
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    (home / "use").write_text(str(dest), encoding="utf-8")
    return dest


def stop_using():
    """Back to the image's own Nemo at the next start."""
    try:
        (_home() / "use").unlink()
    except FileNotFoundError:
        pass


def describe(found: Found) -> str:
    import datetime as dt
    when = dt.datetime.fromtimestamp(found.time, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit, _ = image()
    return (f"A newer Nemo is on the Windows disk: commit {found.commit[:7]}, made {when}"
            + (f" (this image is {commit[:7]})" if commit else "") + ".")


def relaunch(dest: Path):
    """Start the chosen Nemo in place of this one (Linux)."""
    env = dict(os.environ, PYTHONPATH=str(dest))
    os.execve(sys.executable, [sys.executable, "-m", "nemo.cli", "gui", "--prompt"], env)
