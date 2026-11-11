"""Working offline: what is ready, and getting the rest ready in one go.

Most of Nemo already runs without a connection. The exceptions are all
things that are downloaded on first use, and each one fails at the worst
moment -- in the field, with no network:

  * Models. Each mode needs its GGUF file on disk.
  * The firmware toolchain. PlatformIO downloads the compiler and framework
    for a board the first time it builds for it -- several hundred
    megabytes. Until one build has succeeded online, the firmware step
    cannot work offline at all.
  * Second opinions from the online reviewer. These are queued, not lost
    (nemo.reviews).

'Prepare' fetches the models and does one real build per board, so that
readiness is proved rather than assumed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# The reference list. NemoDoc.ps1, nemodoc and fetch-models.sh carry copies
# for their own shells; a test checks every copy agrees with this one, and
# that every model any mode uses has a source here.
MODEL_SOURCES = {
    "gemma3-1b": ("unsloth/gemma-3-1b-it-GGUF", "gemma-3-1b-it-Q4_K_M.gguf"),
    "qwen3-1.7b": ("unsloth/Qwen3-1.7B-GGUF", "Qwen3-1.7B-Q4_K_M.gguf"),
    "qwen2.5-coder-3b": ("Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
                         "qwen2.5-coder-3b-instruct-q4_k_m.gguf"),
    "qwen3-4b": ("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf"),
    # Deep mode, NemoIso only. No installer fetched it before this list
    # existed, so choosing Deep failed with "no GGUF".
    "qwen3-8b": ("Qwen/Qwen3-8B-GGUF", "Qwen3-8B-Q4_K_M.gguf"),
    # The desktop's Game mode (2026-11-11 trial, docs/model-candidates.md).
    "gemma4-e4b": ("unsloth/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-Q4_K_M.gguf"),
}


HF_BASE = "https://huggingface.co"


def home() -> Path:
    return Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo"))


def models_dir() -> Path:
    return home() / "models"


def state_path() -> Path:
    return home() / "offline.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(data: dict) -> None:
    state_path().parent.mkdir(parents=True, exist_ok=True)
    state_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


@dataclass
class Item:
    name: str
    status: str          # ready | missing | partial
    detail: str
    area: str            # models | engine | tools | firmware | data


# ====================================================================
#  Models
# ====================================================================

def model_file(name: str) -> Path | None:
    d = models_dir()
    for pat in (f"{name}.gguf", f"{name}*.gguf"):
        found = sorted(d.glob(pat)) if d.exists() else []
        if found:
            return found[0]
    return None


def is_gguf(path: Path) -> bool:
    """A real model file starts with the magic bytes GGUF. A failed download
    saved as an HTML error page does not."""
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"GGUF"
    except OSError:
        return False


def modes_models(cfg) -> dict[str, str]:
    """Mode name -> model name, for the modes this install actually uses."""
    import sys
    key = "modes_windows" if sys.platform.startswith("win") else "modes"
    modes = cfg.get(key) or cfg.get("modes") or {}
    return {m: spec["model"] for m, spec in modes.items() if "model" in spec}


def download_model(name: str, progress=print) -> tuple[bool, str]:
    if name not in MODEL_SOURCES:
        return False, f"no download source for {name}"
    repo, file = MODEL_SOURCES[name]
    url = f"{HF_BASE}/{repo}/resolve/main/{file}"
    dest = models_dir() / f"{name}.gguf"
    part = dest.with_suffix(".gguf.part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "Nemo"})
    if have:
        # Resume: a multi-gigabyte download on 2011 Wi-Fi will be interrupted.
        req.add_header("Range", f"bytes={have}-")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            mode = "ab" if (have and r.status == 206) else "wb"
            total = int(r.headers.get("Content-Length") or 0) + (have if mode == "ab" else 0)
            done, last = (have if mode == "ab" else 0), 0.0
            with part.open(mode) as fh:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 5:
                        last = time.time()
                        pct = f"{100 * done / total:.0f}%" if total else ""
                        progress(f"  {name}: {done / 2**20:.0f} MB {pct}")
    except OSError as exc:
        return False, f"download interrupted ({exc}); run Prepare again to resume"
    # D211: a stream can end early without an error. A short file still
    # starts with GGUF, so the magic check alone took 78% of qwen3-8b for the
    # model. Kept as .part, so the next Prepare resumes from where it stopped.
    if total and done < total:
        return False, (f"download stopped at {done / 2**20:.0f} of {total / 2**20:.0f} MB; "
                       "run Prepare again to resume")
    if not is_gguf(part):
        part.unlink(missing_ok=True)
        return False, "downloaded file is not a model (the server sent something else)"
    part.replace(dest)
    return True, f"{dest.name}, {dest.stat().st_size / 2**30:.1f} GB"


# ====================================================================
#  Firmware toolchains
# ====================================================================

def boards(library) -> list[str]:
    from .pipeline import pio_board
    return sorted({pio_board(p.ref) for p in library if p.category == "mcu"})


# D196: pinned. Unpinned, the image carried whatever was newest on the day
# it was built: 7.1.3 (Arduino-ESP32 2.0.17) on 2026-10-19, 8.0.0 (3.3) a day
# later, whose compilers took the image from 1.9 to over 2.9 GB. 7.1.3 is
# the one the 2026-10-19 image compiled with. build-iso.sh warms up this
# same version; tests/test_platform_pin.py holds the two together.
ESP32_PLATFORM = "espressif32@7.1.3"


def platform_for(board: str) -> str:
    return "raspberrypi" if board == "pico" else ESP32_PLATFORM


def pio_home() -> Path:
    return Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio"))


def board_ready(board: str) -> tuple[bool, str]:
    """Proved by a successful build, and the platform still installed."""
    st = load_state().get("boards", {}).get(board)
    # The folder is the platform's name, without the pinned version (D196).
    platform_dir = pio_home() / "platforms" / platform_for(board).split("@")[0]
    if not st or not st.get("ok"):
        return False, "never built here; the toolchain downloads on first build"
    if not platform_dir.exists():
        return False, "built once, but the platform has since been removed"
    return True, f"built {time.strftime('%d %b %Y', time.localtime(st['when']))}"


def record_build(board: str, ok: bool) -> None:
    """Note that firmware for `board` was (or was not) built on this machine.

    Only the warm-up build used to record this, so a board whose toolchain
    had arrived through an ordinary firmware step, and which had since
    built successfully, was still listed as "never built here; the
    toolchain downloads on first build".
    """
    try:
        state = load_state()
        state.setdefault("boards", {})[board] = {"ok": bool(ok), "when": int(time.time())}
        save_state(state)
    except OSError:
        pass          # a readiness note must never fail a firmware step


WARMUP_SKETCH = """#include <Arduino.h>
// Built once by 'nemo offline prepare', so PlatformIO downloads this board's
// compiler and framework while a connection is available.
void setup() { Serial.begin(115200); }
void loop() { delay(1000); }
"""


def prepare_board(board: str, progress=print, timeout: int = 3600) -> tuple[bool, str]:
    from .platform_probe import find_tool
    pio = find_tool("pio")
    if not pio:
        return False, "PlatformIO is not installed"
    work = home() / "offline-warmup" / board
    (work / "src").mkdir(parents=True, exist_ok=True)
    (work / "platformio.ini").write_text(
        f"[env:{board}]\nplatform = {platform_for(board)}\nboard = {board}\n"
        "framework = arduino\n", encoding="utf-8")
    (work / "src" / "main.cpp").write_text(WARMUP_SKETCH, encoding="utf-8")
    progress(f"  {board}: building once to fetch its toolchain "
             "(several minutes on this laptop)")
    try:
        p = subprocess.run([pio, "run", "-d", str(work)], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except OSError as exc:
        return False, str(exc)
    state = load_state()
    ok = p.returncode == 0
    state.setdefault("boards", {})[board] = {"ok": ok, "when": int(time.time())}
    save_state(state)
    if ok:
        shutil.rmtree(work / ".pio" / "build", ignore_errors=True)   # keep the toolchain, not the objects
        return True, "toolchain ready"
    tail = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()][-2:]
    return False, "build failed: " + " | ".join(tail)


# ====================================================================
#  Readiness
# ====================================================================

def readiness(cfg, library) -> list[Item]:
    from .platform_probe import find_tool
    items: list[Item] = []

    for mode, model in sorted(modes_models(cfg).items()):
        f = model_file(model)
        if f and is_gguf(f):
            items.append(Item(f"{mode.capitalize()} mode model", "ready",
                              f"{model}, {f.stat().st_size / 2**30:.1f} GB", "models"))
        elif f:
            items.append(Item(f"{mode.capitalize()} mode model", "missing",
                              f"{f.name} is not a valid model file", "models"))
        else:
            items.append(Item(f"{mode.capitalize()} mode model", "missing",
                              f"{model} not downloaded", "models"))

    engine = cfg.get("paths.llama_server", "llama-server")
    engine = engine if Path(str(engine)).is_file() else find_tool("llama-server")
    items.append(Item("Language model engine", "ready" if engine else "missing",
                      str(engine) if engine else "not installed; run NemoDoc or "
                      "nemodoc while online", "engine"))

    for tool, label in (("kicad-cli", "KiCad"), ("dot", "Graphviz"),
                        ("wireviz", "WireViz"), ("pio", "PlatformIO")):
        hit = find_tool(tool)
        status, detail = ("ready", "installed") if hit else ("missing", "not installed")
        if hit and tool == "kicad-cli":
            from .checks.runners import KICAD_MIN_FOR_RULES, kicad_version
            ver = kicad_version(hit)
            if ver and ver < KICAD_MIN_FOR_RULES:
                status = "partial"
                detail = (f"{'.'.join(map(str, ver))} works for drawing, but its "
                          "rule checks need KiCad 8 or later")
        items.append(Item(label, status, detail, "tools"))

    for b in boards(library):
        ok, why = board_ready(b)
        items.append(Item(f"Firmware for {b}", "ready" if ok else "missing", why,
                          "firmware"))

    try:
        from .datasheets import Library
        with Library() as lib:
            sheets = lib.sheets()
        good = sum(1 for s in sheets if s.status == "ok")
        linked = sum(1 for s in sheets if s.parts)
        items.append(Item("Datasheets", "ready" if good else "partial",
                          f"{good} searchable, {linked} linked to parts"
                          if sheets else "none added yet", "data"))
    except Exception:                                   # noqa: BLE001
        items.append(Item("Datasheets", "partial", "library unavailable", "data"))

    from .reviews import pending
    n = len(pending())
    items.append(Item("Second opinions", "ready" if not n else "partial",
                      f"{n} waiting to be sent when online" if n else "none waiting",
                      "data"))
    return items


def summary(items: list[Item]) -> str:
    missing = [i for i in items if i.status == "missing"]
    if not missing:
        return "Ready to work offline."
    return (f"{len(missing)} thing{'s' if len(missing) > 1 else ''} still need "
            "a connection once: " + ", ".join(i.name for i in missing) + ".")


def prepare(cfg, library, progress=print, include_optional=False) -> list[tuple[str, bool, str]]:
    """Fetch what is missing. Returns (what, ok, detail) for each attempt."""
    results = []
    for mode, model in sorted(modes_models(cfg).items()):
        f = model_file(model)
        if f and is_gguf(f):
            continue
        if mode == "deep" and not include_optional:
            results.append((f"{model} (Deep mode)", True,
                            "skipped: 5 GB, fetch with --all if you want it"))
            continue
        progress(f"Downloading {model} for {mode} mode")
        ok, why = download_model(model, progress)
        results.append((model, ok, why))
    for b in boards(library):
        if board_ready(b)[0]:
            continue
        ok, why = prepare_board(b, progress)
        results.append((f"firmware for {b}", ok, why))
    return results
