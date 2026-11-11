"""Which kind of machine Nemo is on: the laptop it was written for, or a
desktop with a GPU that can hold the model (owner, 2026-11-04).

  laptop   the AH531 and anything like it: the CPU engine and the measured
           mode figures in config.modes / modes_windows. Unchanged.
  desktop  an NVIDIA GPU with room for the design model, and the CUDA build
           of the same llama.cpp release beside the CPU one. The modes in
           config.modes_desktop run every layer on the GPU.

Chosen from the hardware ("auto"), or forced by `machine: laptop|desktop`
in config.yaml, or by NEMO_MACHINE (the test sandbox sets it to laptop, so
no test picks up whatever card the machine running it has).

Looking never changes anything: nvidia-smi is asked, nothing is started.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

LAPTOP, DESKTOP = "laptop", "desktop"
CHOICES = ("auto", LAPTOP, DESKTOP)

# The design mode's measured need on an RTX 3050 8 GB (qwen3-8b, ctx 16384,
# every layer offloaded: 6958 MiB, 2026-11-04). A card with less total
# memory than this cannot hold it, so it is not a desktop.
DESKTOP_MIN_VRAM_MIB = 7000

# llama.cpp's CUDA build of the release NemoDoc pins for the CPU (b11175),
# and the CUDA runtime it needs. Hashes are GitHub's own for each asset
# (fetched 2026-11-04); NemoDoc.ps1 carries the same list and a test holds
# the two together.
CUDA_BUILD = "b11175"
CUDA_ENGINE = (
    ("llama-b11175-bin-win-cuda-13.4-x64.zip", 150242012,
     "d4eb4db7bd9227f5b9be1e6abd9fb0416b0e87280a14c7fbea352779ac585684"),
    ("cudart-llama-bin-win-cuda-13.4-x64.zip", 423535356,
     "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668"),
)
CUDA_HOME_WIN = r"C:\Nemo\engine-cuda"


@dataclass(frozen=True)
class Gpu:
    name: str
    total_mib: int


def _smi() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    win = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    return win if os.path.isfile(win) else None


def _query(field: str) -> list[str]:
    smi = _smi()
    if not smi:
        return []
    try:
        p = subprocess.run([smi, f"--query-gpu={field}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]


@lru_cache(maxsize=1)
def gpus() -> tuple[Gpu, ...]:
    """NVIDIA cards nvidia-smi reports. () where there is no NVIDIA driver."""
    out = []
    for line in _query("name,memory.total"):
        name, _, total = line.rpartition(",")
        try:
            out.append(Gpu(name.strip(), int(float(total))))
        except ValueError:
            continue
    return tuple(out)


def gpu_free_mib() -> int | None:
    """Free memory on the first card right now; None if it cannot be read."""
    lines = _query("memory.free")
    try:
        return int(float(lines[0])) if lines else None
    except ValueError:
        return None


GPU_FIELDS = ("name", "temperature.gpu", "utilization.gpu", "power.draw", "memory.total",
              "memory.used", "memory.free", "driver_version", "fan.speed")


def gpu_status() -> dict | None:
    """The first card's readings now, from nvidia-smi: name, temperature (C),
    utilization (%), power (W), memory total/used/free (MiB), driver, fan
    (%). None without an NVIDIA driver. A reading the card does not give
    ("[N/A]") is None, never a guess."""
    lines = _query(",".join(GPU_FIELDS))
    if not lines:
        return None
    values = [v.strip() for v in lines[0].split(",")]
    if len(values) != len(GPU_FIELDS):
        return None
    out: dict = {}
    for k, v in zip(GPU_FIELDS, values):
        if k in ("name", "driver_version"):
            out[k] = v
            continue
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = None
    return out


def cuda_engine() -> str | None:
    """The CUDA llama-server, if installed (C:\\Nemo\\engine-cuda, or paths.llama_server_gpu)."""
    from .platform_probe import find_tool
    return find_tool("llama-server-cuda")


def setting(cfg=None) -> str:
    """auto, laptop or desktop: NEMO_MACHINE, else config `machine`, else auto."""
    raw = os.environ.get("NEMO_MACHINE") or (cfg.get("machine", "auto") if cfg is not None else "auto")
    raw = str(raw or "auto").strip().lower()
    return raw if raw in CHOICES else "auto"


def detect() -> tuple[str, str]:
    """(profile, why) from the hardware alone."""
    cards = gpus()
    if not cards:
        return LAPTOP, "no NVIDIA GPU found"
    big = max(cards, key=lambda g: g.total_mib)
    if big.total_mib < DESKTOP_MIN_VRAM_MIB:
        return LAPTOP, (f"{big.name} has {big.total_mib} MiB; the design model needs "
                        f"{DESKTOP_MIN_VRAM_MIB}")
    if not cuda_engine():
        return LAPTOP, (f"{big.name} ({big.total_mib} MiB) could hold the model, but the CUDA "
                        "engine is not installed: run NemoDoc while online")
    return DESKTOP, f"{big.name} with {big.total_mib} MiB and the CUDA engine"


def profile(cfg=None) -> tuple[str, str]:
    """(profile, why): what Nemo runs as here."""
    chosen = setting(cfg)
    if chosen != "auto":
        src = "NEMO_MACHINE" if os.environ.get("NEMO_MACHINE") else "config.yaml"
        return chosen, f"set to {chosen} in {src}"
    return detect()


def is_desktop(cfg=None) -> bool:
    return profile(cfg)[0] == DESKTOP
