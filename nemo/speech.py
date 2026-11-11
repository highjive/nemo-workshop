"""Speaking to Nemo instead of typing (owner's redesign, 2026-10-17).

Offline: Vosk and its small English model (vosk-model-small-en-us-0.15,
about 68 MB unpacked). Measured on the AH531, no AVX, under Windows with a
synthetic voice: model loaded in 1 s, 4.7 s of speech recognised in 2.4 s,
every word right. A real voice through the laptop's own microphone has not
been measured, and will do worse.

Nothing is sent anywhere, and nothing is acted on: the words go into the
prompt box for the owner to read and Send.

Recording: `arecord` (alsa-utils) on Linux; on Windows the MCI wave device
through winmm, which needs no extra package.
"""
from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

MODEL_NAME = "vosk-model-small-en-us-0.15"
RATE = 16000


def model_dirs() -> list[Path]:
    """Where the speech model may be, in order."""
    home = Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo"))
    out = [home / "models" / "speech" / MODEL_NAME,
           Path("/opt/nemo/speech") / MODEL_NAME,
           Path(r"C:\Nemo\models\speech") / MODEL_NAME]
    # The Windows disk NemoIso reads models from (nemodoc, read-only).
    out += sorted(Path("/mnt/nemo-windows").glob(f"*/Nemo/models/speech/{MODEL_NAME}"))
    return out


def find_model() -> Path | None:
    for d in model_dirs():
        if (d / "am").is_dir() or (d / "conf").is_dir():
            return d
    return None


# The desktop hears with whisper.cpp on its GPU (owner, 2026-11-04). Measured
# there on six spoken requests in Nemo's own voice: Vosk heard "e s p thirty
# two", "right me a story" and "two thousand million power battery"; Whisper
# heard "ESP32", "Write me a story" and "2000 mAh battery"; both missed
# "Kobra". 0.9 s a request each. The laptop keeps Vosk: no GPU, and Whisper's
# small model would cost it far more than Vosk's.
# whisper.cpp b5454 (cuda-12.4.0 x64) and ggml-small.en.bin: sha256 in
# WHISPER_SOURCES; NemoDoc fetches them on an NVIDIA machine.
WHISPER_MODEL = "ggml-small.en.bin"
WHISPER_TAG = "b5454"          # the release WHISPER_SOURCES come from (NemoDoc's url)
WHISPER_SOURCES = (
    ("whisper-bin-win-cuda-12.4.0-x64.zip", 684913404,
     "afef0b881c500958921c3f5523b50e59ee2ec9b6f5cbd25b324c51ed308a957a"),
    ("ggml-small.en.bin", 487614201,
     "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"),
)


def whisper() -> tuple[Path, Path] | None:
    """(whisper-cli, its model) where both are here AND this is the desktop
    (nemo/machine.py); None otherwise, and Vosk hears."""
    from .machine import is_desktop
    if not is_desktop():
        return None
    home = Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo"))
    exes = [Path(r"C:\Nemo\tools\whisper\Release\whisper-cli.exe"),
            Path(r"C:\Nemo\tools\whisper\whisper-cli.exe")]
    models = [home / "models" / "speech" / WHISPER_MODEL, Path(r"C:\Nemo\models\speech") / WHISPER_MODEL]
    exe = next((p for p in exes if p.is_file()), None)
    model = next((p for p in models if p.is_file()), None)
    return (exe, model) if exe and model else None


def available() -> tuple[bool, str]:
    """(True, '') when the Speak button can work, else why not."""
    if whisper() is not None:
        return True, ""
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False, "the speech recogniser (vosk) is not installed"
    if find_model() is None:
        return False, f"the speech model ({MODEL_NAME}) is not on this machine"
    if sys.platform != "win32" and not shutil.which("arecord"):
        return False, "there is no recorder (arecord, from alsa-utils)"
    return True, ""


# ------------------------------------------------------------- recording
class Recorder:
    """Start, then stop: a 16 kHz mono WAV of what was said."""

    def __init__(self):
        # D274: the handle mkstemp opens was never closed, and nothing deleted a
        # recording that failed to start or was cut off by closing the window:
        # 178 empty nemo-speech-*.wav in this desktop's Temp (2026-11-11).
        fd, name = tempfile.mkstemp(prefix="nemo-speech-", suffix=".wav")
        os.close(fd)
        self.path = Path(name)
        self.proc = None

    def discard(self) -> None:
        """Delete the recording's file (one not kept or moved elsewhere)."""
        try:
            self.path.unlink()
        except OSError:
            pass

    def start(self) -> list[str]:
        """Start recording. Returns the mixer controls switched on first
        (Linux), so the window can say so. One that cannot start deletes its file."""
        try:
            return self._start()
        except BaseException:
            self.discard()
            raise

    def _start(self) -> list[str]:
        if sys.platform == "win32":
            _mci("open new type waveaudio alias nemo_rec")
            _mci(f"set nemo_rec bitspersample 16 samplespersec {RATE} channels 1")
            _mci("record nemo_rec")
            return []
        switched = capture_on()
        self.proc = subprocess.Popen(
            ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "wav",
             str(self.path)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        # A recorder that cannot open the microphone stops at once, and its
        # reason was thrown away: say it.
        try:
            self.proc.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            return switched
        err = (self.proc.stderr.read() or b"").decode("utf-8", "replace").strip()
        raise OSError("the microphone could not be used: " + (err or "the recorder stopped"))

    def level(self) -> float | None:
        """How loud the last fifth of a second was, 0 to 1, while
        recording; None where it cannot be read (Windows records to memory)."""
        if sys.platform == "win32":
            return None
        try:
            size = self.path.stat().st_size
            if size <= 44:
                return 0.0
            with self.path.open("rb") as f:
                f.seek(max(44, size - 6400))
                return loudness(f.read())[1]
        except OSError:
            return None

    def stop(self) -> Path:
        if sys.platform == "win32":
            _mci("stop nemo_rec")
            _mci(f'save nemo_rec "{self.path}"')
            _mci("close nemo_rec")
        elif self.proc:
            # D187: SIGINT, not SIGTERM. On the AH531 a recording stopped
            # with SIGTERM kept the placeholder length arecord writes first
            # (1073741824 frames, 18 hours for 9 seconds); arecord writes the
            # real length when interrupted.
            import signal
            try:
                self.proc.send_signal(signal.SIGINT)
            except (OSError, ValueError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return self.path


# Mixer controls that hold a microphone's capture, on the HD audio chips of
# laptops of the AH531's age. Speech on the AH531 (2026-10-18) recorded but
# heard nothing: a fresh Linux often starts with capture muted or at zero,
# and the image has no sound server to turn it on. Absent controls are
# skipped.
CAPTURE_CONTROLS = ("Capture", "Mic", "Internal Mic", "Mic Boost", "Internal Mic Boost")


def capture_on() -> list[str]:
    """Switch the microphone's capture on and up. Returns what it changed."""
    if not shutil.which("amixer"):
        return []
    done = []
    for ctl in CAPTURE_CONTROLS:
        level = "33%" if "Boost" in ctl else "80%"
        try:
            r = subprocess.run(["amixer", "-q", "sset", ctl, level, "cap"],
                               capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            done.append(ctl)
    return done


def loudness(frames: bytes) -> tuple[float, float]:
    """(peak, rms) of 16-bit little-endian samples, each 0 to 1."""
    import array
    a = array.array("h")
    a.frombytes(frames[: len(frames) // 2 * 2])
    if sys.byteorder != "little":
        a.byteswap()
    if not a:
        return 0.0, 0.0
    peak = max(abs(x) for x in a) / 32768
    rms = (sum(x * x for x in a) / len(a)) ** 0.5 / 32768
    return peak, rms


def measure(wav_path: Path) -> tuple[float, float, float]:
    """(seconds, peak, rms) of a recording."""
    with wave.open(str(wav_path), "rb") as w:
        frames = w.readframes(w.getnframes())
        rate = float(w.getframerate() or RATE)
    # From the sound itself, not the header's count, which a recorder that
    # was stopped hard leaves at its placeholder (D187).
    secs = len(frames) / 2 / rate
    peak, rms = loudness(frames)
    return secs, peak, rms


SILENT = 0.01        # a peak under 1 % of full scale: the microphone heard nothing


def keep_last(wav_path: Path, heard: str, stats: tuple[float, float, float]) -> Path | None:
    """The last recording and what was made of it, in the projects folder,
    which goes to the stick (NemoData): so what the microphone really heard
    can be listened to afterwards. Only the latest is kept."""
    try:
        from .config import Config
        d = Config.load().path("paths.projects") / ".speech"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wav_path, d / "last.wav")
        secs, peak, rms = stats
        (d / "last.txt").write_text(
            f"seconds {secs:.1f}, peak {peak:.1%}, rms {rms:.2%}\nheard: {heard!r}\n",
            encoding="utf-8")
        return d / "last.wav"
    except OSError:
        return None


def _mci(command: str) -> None:
    import ctypes
    err = ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
    if err:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.winmm.mciGetErrorStringW(err, buf, 256)
        raise OSError(f"the microphone could not be used: {buf.value}")


# ------------------------------------------------------------ recognising
_MODEL = None


def transcribe(wav_path: Path) -> str:
    """The words in a 16 kHz mono WAV, or '' if none were heard: Whisper on
    the desktop where it is installed, else Vosk."""
    global _MODEL
    w = whisper()
    if w is not None:
        exe, model = w
        p = subprocess.run([str(exe), "-m", str(model), "-f", str(wav_path), "-nt", "-np", "-l", "en"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120)
        heard = " ".join((p.stdout or "").split())
        # Whisper writes "[BLANK_AUDIO]" (or similar) for silence: that is nothing heard.
        return "" if re.fullmatch(r"\[[A-Z_ ]+\]|\([^)]*\)", heard) else heard
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    if _MODEL is None:
        where = find_model()
        if where is None:
            raise FileNotFoundError(f"no speech model ({MODEL_NAME})")
        _MODEL = Model(str(where))
    with wave.open(str(wav_path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("the recording is not 16-bit mono")
        rec = KaldiRecognizer(_MODEL, w.getframerate())
        while True:
            data = w.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
    return json.loads(rec.FinalResult()).get("text", "").strip()
