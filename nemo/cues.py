"""Audio cues (owner, 2026-10-23: "add audio cues where possible"): short
tones that say what happened without looking: a job done, a failure,
something wanting attention, a department opening, a drive plugged in, a
job starting.

The tones are made by code (sine notes with a soft start and end, 16-bit
mono WAV, kept in ~/.nemo/cues), nothing downloaded. Played without waiting:
on Windows by winsound, on a Mac by afplay, on Linux by paplay or aplay.
Where none is there a cue is simply not heard: silence is never a failure.
The Sounds switch (gui.json "sounds") turns them off; NEMO_CUES=off is the
test sandbox's.
"""
from __future__ import annotations

import io
import math
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

RATE = 22050
# name -> notes (hertz, milliseconds); 0 Hz is a rest.
CUES = {
    "done": [(523, 90), (659, 90), (784, 160)],          # C E G, rising: finished well
    "fail": [(392, 160), (0, 40), (262, 260)],            # G down to C: something failed
    "attention": [(659, 120), (0, 60), (659, 120)],      # two the same: look at me
    "open": [(587, 110), (880, 150)],                     # a department opens
    "drive": [(784, 70), (988, 70), (1175, 110)],         # quick rise: a drive plugged in
    "start": [(440, 120)],                                 # one soft note: work begun
}
VOLUME = 0.25


def wav_bytes(name: str) -> bytes:
    """The cue as a WAV file in memory."""
    frames = bytearray()
    for hz, ms in CUES[name]:
        n = int(RATE * ms / 1000)
        fade = min(n // 4, int(RATE * 0.012))
        for i in range(n):
            amp = 0.0 if hz == 0 else math.sin(2 * math.pi * hz * i / RATE)
            edge = min(1.0, i / fade, (n - 1 - i) / fade) if fade else 1.0
            frames += struct.pack("<h", int(32767 * VOLUME * amp * edge))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return out.getvalue()


def path(name: str) -> Path:
    """The cue's WAV file, made the first time it is wanted."""
    from .config import CONFIG_HOME
    p = Path(CONFIG_HOME) / "cues" / f"{name}.wav"
    data = wav_bytes(name)
    if not p.is_file() or p.read_bytes() != data:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return p


def player() -> list[str] | None:
    """The command that plays a WAV here, or None (Windows uses winsound)."""
    if sys.platform == "darwin":
        return ["afplay"] if shutil.which("afplay") else None
    for cmd in (["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def play(name: str) -> bool:
    """Play a cue without waiting; False when it was not played."""
    if os.environ.get("NEMO_CUES") == "off" or name not in CUES:
        return False
    try:
        wav = path(name)
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        cmd = player()
        if cmd is None:
            return False
        subprocess.Popen(cmd + [str(wav)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, RuntimeError):
        return False


def for_colour(colour, theme) -> str:
    """The cue for a status colour: a failure, a pass, or anything else."""
    if colour == theme.FAIL:
        return "fail"
    if colour == theme.PASS:
        return "done"
    return "attention"
