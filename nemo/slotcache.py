"""The model's reading of a system prompt, kept on disk between runs.

Reading is as slow as writing on the AH531: qwen3-1.7b reads 2.6 to 3
tokens a second and qwen3-4b 1.16 (~/.nemo/talk.log, design.log), so a
step's fixed instructions cost one to five minutes before the model writes
a word. llama-server keeps what it has read in memory and reuses the shared
beginning of the next prompt, but loses it whenever the server stops: every
mode change, every boot.

llama-server (b11175) can write a slot's cache to a file and read it back
(--slot-save-path, POST /slots/0?action=save|restore). Measured on the
AH531, qwen3-1.7b, a 227-token prompt after a restart: 78.3 s read cold,
9.5 s with its cache restored first (the restore took 0.14 s, from a 26 MB
file).

So, before a local model call: if this server has just read this same
system prompt, nothing is done; if a file for it exists, it is restored;
if not, the system prompt alone is read once (one token written) and saved,
and the real request then reuses it. The file holds only the system prompt,
which is the part that does not vary (mistake 4c: what never changes goes
first).

The files belong to one model file and one context size: they are kept in
a folder named for the GGUF (name and size) and the context. modes.start
names that folder to the server and records it in slots.json beside
mode.pid, with the server's pid.

Every failure here is quiet: a cache that cannot be used costs the time it
always cost, never a step. Where its folder is in RAM (a live system
started without a persistence partition) each file would take its size out
of the 8 GB the model needs: on a live stick the files are kept on the
stick instead (STICK_SLOTS, below), and anywhere else in RAM it is off.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

# Kept per folder, newest first; older files go. A system prompt of 300
# tokens is about 35 MB for qwen3-1.7b (measured 26 MB for 229 tokens).
MAX_MB = 512
SLOT = 0                 # modes.start runs one slot (-np 1)
STATE_NAME = "slots.json"

# A live NemoIso stick (owner's go-ahead, 2026-10-20). The home folder is in
# RAM there, so the server's folder is only a staging place: nemo-sync moves
# each saved file to NemoData on the stick and never copies one back at
# login, and before a restore the one file wanted is copied from the stick
# into the folder and deleted from it again straight after. At most
# STAGING_MB waits in RAM for nemo-sync; past that nothing more is saved.
STICK_SLOTS = Path(os.environ.get("NEMO_STICK_SLOTS",
                                  "/run/live/medium/NemoData/.nemo/slots"))
STAGING_MB = 128


def staged_mb(folder: Path) -> float:
    try:
        return sum(f.stat().st_size for f in folder.glob("*.bin")) / 2**20
    except OSError:
        return 0.0

# What this process last left in the slot, per server pid. Another process
# using the same server makes this stale; the worst that does is one
# restore that was not needed, or one prompt read in full as before.
_warm: dict[int, str] = {}


def folder_for(home: Path, gguf: Path, ctx: int) -> Path:
    try:
        size = gguf.stat().st_size
    except OSError:
        size = 0
    return home / "slots" / f"{gguf.stem}-{size}-c{int(ctx)}"


def key(system: str) -> str:
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:24]


def in_ram(path: Path, mounts: str | None = None) -> bool:
    """True if `path` is on a RAM-backed filesystem (Linux only): tmpfs,
    or an overlay whose writable layer is tmpfs, as live-boot's root is
    when no persistence partition was found."""
    if mounts is None:
        if not sys.platform.startswith("linux"):
            return False
        try:
            mounts = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
    table = []
    for line in mounts.splitlines():
        f = line.split()
        if len(f) >= 4:
            table.append((f[1].replace("\\040", " "), f[2], f[3]))

    def mount_of(p: str):
        best = None
        for point, fstype, opts in table:
            if p == point or p.startswith(point.rstrip("/") + "/") or point == "/":
                if best is None or len(point) > len(best[0]):
                    best = (point, fstype, opts)
        return best

    m = mount_of(path.as_posix())
    for _ in range(4):                       # overlay on overlay, at most
        if m is None:
            return False
        point, fstype, opts = m
        if fstype in ("tmpfs", "ramfs"):
            return True
        if fstype != "overlay":
            return False
        upper = next((o.split("=", 1)[1] for o in opts.split(",")
                      if o.startswith("upperdir=")), None)
        if not upper:
            return False
        m = mount_of(upper)
    return False


def write_state(state_dir: Path, pid: int, folder: Path,
                stick: Path | None = None) -> None:
    (state_dir / STATE_NAME).write_text(
        json.dumps({"pid": pid, "folder": str(folder),
                    "stick": str(stick) if stick else None}), encoding="utf-8")


def clear_state(state_dir: Path) -> None:
    (state_dir / STATE_NAME).unlink(missing_ok=True)


def read_state(state_dir: Path) -> tuple[int, Path, Path | None] | None:
    """(server pid, its folder, the stick folder or None)."""
    try:
        d = json.loads((state_dir / STATE_NAME).read_text(encoding="utf-8"))
        stick = d.get("stick")
        return int(d["pid"]), Path(d["folder"]), Path(stick) if stick else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _root(base: str) -> str:
    """http://host:port from the OpenAI-style base ending in /v1."""
    base = base.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def prune(folder: Path, max_mb: int = MAX_MB) -> None:
    files = sorted(folder.glob("*.bin"), key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for f in files:
        total += f.stat().st_size
        if total > max_mb * 2**20:
            f.unlink(missing_ok=True)


def prepare(base: str, pid: int, folder: Path, system: str, payload: dict,
            timeout: float, stick: Path | None = None) -> str:
    """Make the server's slot start with `system` already read, if it can
    be done. `payload` is the chat request about to be sent; its model and
    template options are reused for the priming request. `stick` is where
    a live stick keeps the files (then `folder` is only staging). Returns
    what was done: "warm", "restored", "saved", "read" (not saved), or
    "off: <why>"."""
    k = key(system)
    if _warm.get(pid) == k:
        return "warm"
    root = _root(base)
    name = f"{k}.bin"
    path = folder / name
    try:
        if stick is None and in_ram(folder):
            return "off: the cache folder is in RAM"
        borrowed = False
        if stick is not None and not path.is_file() and (stick / name).is_file():
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stick / name, path)
            borrowed = True
        if path.is_file():
            try:
                _post(f"{root}/slots/{SLOT}?action=restore", {"filename": name}, 120)
                if not borrowed:
                    os.utime(path)
                _warm[pid] = k
                return "restored"
            except Exception:                              # noqa: BLE001
                # Written by another engine build, or cut short: read the
                # prompt afresh below and write a new one.
                path.unlink(missing_ok=True)
            finally:
                if borrowed:
                    path.unlink(missing_ok=True)     # its home is the stick
        folder.mkdir(parents=True, exist_ok=True)
        prime = {key_: v for key_, v in payload.items()
                 if key_ in ("model", "chat_template_kwargs")}
        prime.update({"messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": ""}],
                      "max_tokens": 1, "temperature": 0})
        _post(f"{base.rstrip('/')}/chat/completions", prime, timeout)
        if stick is not None and staged_mb(folder) >= STAGING_MB:
            _warm[pid] = k
            return "read (not saved: earlier files are still waiting for the stick)"
        _post(f"{root}/slots/{SLOT}?action=save", {"filename": name}, 120)
        _warm[pid] = k
        if stick is None:
            prune(folder)
        return "saved"
    except Exception as exc:                               # noqa: BLE001
        _warm.pop(pid, None)
        return f"off: {exc}"
