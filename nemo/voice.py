"""The Linguist's voice: Nemo says things aloud (owner, 2026-10-21: "add
linguist to the library dealing with language and audible feedback").

Offline, and no language model: on Windows, the voices Windows already has
(System.Speech, through PowerShell; on the AH531, Microsoft Hazel, en-GB,
and Zira, en-US). Measured there: 0.7 s to make seven seconds of speech. On
Linux, espeak-ng where it is installed (NemoIso's package list has it from
2026-10-21; that image is not built yet). Where neither is there, speak()
says so and nothing else happens: being silent is never a failure.

A British voice is chosen first, as the Writer checks spelling in British
English. The words never go on a command line: they are handed over in an
environment variable (Windows) or on standard input (Linux), so nothing in
them can be run as a command.

Speaking is one at a time: a new sentence stops the one before.
NEMO_VOICE=off (the test sandbox) keeps it silent; writing to a file still works.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

LIMIT = 400                 # characters: past this, reading aloud is no help
_current: subprocess.Popen | None = None

# Speed (owner, 2026-11-11: "Voice still needs more work on timing and
# speed"). Steps from -3 (slower) to +3 (faster), kept in gui.json as
# "voice_rate". Measured on the desktop at Windows' own rate (step 0):
# 97 to 158 words a minute, the short lines with commas slowest; the default
# is now a step faster. Each step is 1 on Windows' -10..10 scale, 20 words a
# minute on espeak-ng (175 at 0) and on the Mac's say.
RATE_STEPS = (-3, -2, -1, 0, 1, 2, 3)
DEFAULT_RATE = 1
_rate = DEFAULT_RATE


def set_rate(step) -> int:
    """Set the speed step (clamped to RATE_STEPS); returns it."""
    global _rate
    try:
        _rate = max(RATE_STEPS[0], min(RATE_STEPS[-1], int(step)))
    except (TypeError, ValueError):
        _rate = DEFAULT_RATE
    return _rate


def rate() -> int:
    return _rate


def words_per_minute(step: int | None = None) -> int:
    """espeak-ng's and the Mac's speed for a step."""
    return 175 + 20 * (_rate if step is None else step)


def speaking() -> bool:
    """Is something being said right now?"""
    return _current is not None and _current.poll() is None

# Picks an enabled en-GB voice, else the default; speaks $env:NEMO_SAY, or
# writes it to $env:NEMO_WAV when that is set (the tests listen that way).
_SAPI = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and "
    "$_.VoiceInfo.Culture.Name -eq 'en-GB' } | Select-Object -First 1; "
    "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
    "if ($env:NEMO_RATE) { $s.Rate = [int]$env:NEMO_RATE }; "
    "if ($env:NEMO_WAV) { $s.SetOutputToWaveFile($env:NEMO_WAV) }; "
    "$s.Speak($env:NEMO_SAY); $s.Dispose()")


def engine() -> tuple[str | None, str]:
    """('sapi'|'say'|'espeak', what it is) or (None, why there is no voice)."""
    if sys.platform.startswith("win"):
        ps = shutil.which("powershell") or shutil.which("powershell.exe")
        return ("sapi", ps) if ps else (None, "PowerShell is not on this computer")
    if sys.platform == "darwin":       # a Mac's own voices (owner, 2026-10-23)
        say = shutil.which("say")
        return ("say", say) if say else (None, "the Mac's say command is missing")
    es = shutil.which("espeak-ng")
    return ("espeak", es) if es else (None, "espeak-ng is not installed")


def plain(text: str, whole: bool = False) -> str:
    """The words worth hearing: no paths or code marks, one line, short
    (unless `whole`: the Audio department's Narrator reads it all)."""
    text = re.sub(r"[A-Za-z]:\\\S+|(?<!\w)/(?:[\w.-]+/)+[\w.-]*", "a file", text)
    text = re.sub(r"[`*_#>|]+", " ", text)
    # A line break is a pause: a line that does not end a sentence is given a
    # full stop, so the lines of a list are not run into one.
    text = re.sub(r"(?<![.!?:;,])[ \t]*\n+\s*", ". ", text.strip())
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > LIMIT and not whole:
        cut = text[:LIMIT]
        text = cut[:cut.rfind(" ")] if " " in cut else cut
        text += ". The rest is on the screen."
    return text


def stop() -> None:
    """Stop whatever is being said."""
    global _current
    if _current is not None and _current.poll() is None:
        _current.terminate()
    _current = None


def speak(text: str, *, wav: Path | None = None, wait: bool = False,
          whole: bool = False) -> tuple[bool, str]:
    """Say `text` aloud (or into `wav`). Returns (started, why not).
    `whole`: all of it, not cut at LIMIT (the Narrator, into a file)."""
    global _current
    words = plain(text, whole)
    if not words:
        return False, "nothing to say"
    if os.environ.get("NEMO_VOICE") == "off" and wav is None:
        return False, "the voice is off here (NEMO_VOICE=off)"   # the test sandbox
    kind, where = engine()
    if kind is None:
        return False, where
    stop()
    try:
        if kind == "sapi":
            env = dict(os.environ, NEMO_SAY=words, NEMO_WAV=str(wav) if wav else "",
                       NEMO_RATE=str(_rate))
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            _current = subprocess.Popen(
                [where, "-NoProfile", "-NonInteractive", "-Command", _SAPI], env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags)
        elif kind == "say":            # no words on the command line: read from stdin
            argv = [where, "-r", str(words_per_minute())] + (["--file-format=WAVE", "--data-format=LEI16@22050",
                               "-o", str(wav)] if wav else [])
            _current = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _current.stdin.write(words.encode("utf-8"))
            _current.stdin.close()
        else:
            argv = [where, "-v", "en-gb", "-s", str(words_per_minute()), "--stdin"] + (
                ["-w", str(wav)] if wav else [])
            _current = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _current.stdin.write(words.encode("utf-8"))
            _current.stdin.close()
    except OSError as exc:
        _current = None
        return False, f"the voice could not start: {exc}"
    if wait:
        try:
            _current.wait(timeout=600 if whole else 60)
        except subprocess.TimeoutExpired:
            stop()
            return False, "the voice took longer than a minute"
    return True, ""
