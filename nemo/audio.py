"""The Audio department: making and keeping sound (owner, 2026-10-21), beside
the Music Room, which plays music.

  Narrator        reads a Library story aloud into an audiobook: one WAV per
                  chapter, in the Linguist's British voice, offline
  Recorder        records from the laptop's microphone (speech.Recorder)
  Sound Engineer  readies sound files for a DFPlayer Mini's SD card
  Audio Librarian keeps the listening shelf (audiobooks, podcasts,
                  recordings) and the place reached in each
  Writer          titles each audiobook's chapters in its playlist

All on the Storeroom's audio shelf: audio/books/<book>/, audio/podcasts/,
audio/recordings/, audio/sd-cards/<name>/. Nothing here asks the model.

The DFPlayer Mini's rules, as far as a source gives them: up to 100 folders
of up to 255 songs each, a FAT16 or FAT32 card of up to 32 GB, sample rates
8 to 48 kHz (DFRobot's wiki, SKU DFR0299); the Arduino library plays a file
by folder and file number (playFolder). The names used, folders 01, 02...
holding 001.mp3, 002.mp3..., are the module's usual numbering; NOT TRIED on
a real module here.
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from . import storeroom

LISTEN = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav", ".wma"}
DFPLAYER_RATES = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}
DFPLAYER_FOLDERS, DFPLAYER_PER_FOLDER = 99, 255
CHUNK = 4000            # characters read at a time: well under Windows' 32,767 for one setting


def shelf(cfg, part: str = "") -> Path:
    root = storeroom.shelf(cfg.path("paths.storeroom"), "audio")
    return root / part if part else root


# ------------------------------------------------------------ the shelf
@dataclass
class Listen:
    title: str
    kind: str          # "book", "podcast" or "recording"
    path: Path


def listening(cfg) -> list[Listen]:
    """The Audio Librarian's shelf: audiobooks (each chapter), podcasts, recordings."""
    out = []
    for kind, folder in (("book", "books"), ("podcast", "podcasts"), ("recording", "recordings")):
        root = shelf(cfg, folder)
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix.lower() in LISTEN:
                    title = (f"{p.parent.name}: {p.stem}" if kind == "book" and p.parent != root
                             else p.stem)
                    out.append(Listen(title, kind, p))
    return out


def _places_path(cfg) -> Path:
    return shelf(cfg) / "places.json"


def place(cfg, path: Path) -> float:
    """Seconds reached in this file when it was last stopped, or 0."""
    try:
        return float(json.loads(_places_path(cfg).read_text(encoding="utf-8"))
                     .get(Path(path).relative_to(shelf(cfg)).as_posix(), 0))
    except (OSError, ValueError, KeyError):
        return 0.0


def remember(cfg, path: Path, seconds: float | None) -> None:
    p = _places_path(cfg)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    key = Path(path).relative_to(shelf(cfg)).as_posix()
    if seconds and seconds > 5:
        data[key] = round(float(seconds), 1)
    else:
        data.pop(key, None)                 # finished, or hardly begun
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


# ------------------------------------------------------------ the Narrator
def _plain(md: str) -> str:
    text = re.sub(r"^#+\s*(\d+)\.\s*", r"Chapter \1. ", md, flags=re.M)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = re.sub(r"[*_`>|]+", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _chunks(text: str) -> list[str]:
    out, cur = [], ""
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        while len(para) > CHUNK:                      # one huge paragraph: at a sentence
            cut = para.rfind(". ", 0, CHUNK) + 1 or CHUNK
            out.append(para[:cut]); para = para[cut:].strip()
        if cur and len(cur) + len(para) + 2 > CHUNK:
            out.append(cur); cur = para
        else:
            cur = (cur + "\n\n" + para) if cur else para
    return out + ([cur] if cur else [])


def _join_wavs(parts: list[Path], out: Path) -> float:
    """One WAV from several of the same format; returns its seconds."""
    with wave.open(str(parts[0])) as first:
        params = first.getparams()
    frames = 0
    with wave.open(str(out), "wb") as w:
        w.setparams(params)
        for p in parts:
            with wave.open(str(p)) as r:
                data = r.readframes(r.getnframes())
                frames += r.getnframes()
                w.writeframes(data)
    return frames / params.framerate


def narrate(cfg, story: Path, say=print) -> Path:
    """Read each chapter of `story` (a Library story folder) into a WAV;
    returns the audiobook's folder, with a playlist the Writer titled."""
    from . import voice
    chapters = sorted((Path(story) / "chapters").glob("*.md"))
    if not chapters and (Path(story) / "story.md").is_file():
        chapters = [Path(story) / "story.md"]
    if not chapters:
        raise ValueError("the story has no chapters written yet")
    book = shelf(cfg, "books") / Path(story).name
    book.mkdir(parents=True, exist_ok=True)
    titles = []
    for n, ch in enumerate(chapters, 1):
        md = ch.read_text(encoding="utf-8", errors="replace")
        first = next((l for l in md.splitlines() if l.strip()), ch.stem)
        title = re.sub(r"^#+\s*", "", first).strip() or ch.stem
        bare = re.sub(r"^\d+\.\s*", "", title)             # "1. The Light" -> "The Light"
        out = book / f"{n:02d} {re.sub(r'[^A-Za-z0-9 ._-]+', '', bare)[:60].strip() or 'chapter'}.wav"
        t = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            parts = []
            for i, piece in enumerate(_chunks(_plain(md))):
                part = Path(tmp) / f"{i:03d}.wav"
                ok, why = voice.speak(piece, wav=part, wait=True, whole=True)
                if not ok or not part.is_file():
                    raise RuntimeError(f"the voice could not read chapter {n}: {why}")
                parts.append(part)
            secs = _join_wavs(parts, out)
        say(f"Narrator: chapter {n} of {len(chapters)}, {secs:.0f} s of reading, "
            f"made in {time.time() - t:.0f} s")
        titles.append((secs, title, out.name))
    lines = ["#EXTM3U"] + [x for s, t, f in titles for x in (f"#EXTINF:{int(s)},{t}", f)]
    (book / f"{Path(story).name}.m3u").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return book


# ------------------------------------------------------------ the Recorder
class Recording:
    """The microphone into the recordings shelf: start(), then stop()."""

    def __init__(self, cfg):
        from . import speech
        self.cfg, self.rec = cfg, speech.Recorder()

    def start(self) -> list[str]:
        return self.rec.start()

    def stop(self, name: str = "") -> tuple[Path, str]:
        from . import speech
        tmp = self.rec.stop()
        stats = speech.measure(tmp)
        folder = shelf(self.cfg, "recordings")
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip() or time.strftime("recording %Y-%m-%d %H%M%S")
        dest = folder / f"{stem}.wav"
        shutil.move(str(tmp), dest)
        secs, loudest = stats[0], stats[1]
        note = (f"{secs:.0f} s recorded" + (", but it was silent: is the microphone on?"
                                             if loudest < 0.01 else ""))
        return dest, note


# ------------------------------------------------------------ the Sound Engineer
def sample_rate(path: Path) -> int | None:
    """A WAV's or an MP3's sample rate, from its own header; None if unknown."""
    path = Path(path)
    try:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path)) as w:
                return w.getframerate()
        data = path.read_bytes()[:65536]
        i = 0
        if data[:3] == b"ID3" and len(data) > 10:          # skip an ID3v2 tag
            size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
            i = 10 + size
            data = path.read_bytes()[i:i + 65536]
            i = 0
        while i < len(data) - 4:
            if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                version = (data[i + 1] >> 3) & 3            # 3: MPEG-1, 2: MPEG-2, 0: 2.5
                idx = (data[i + 2] >> 2) & 3
                base = (44100, 48000, 32000, None)[idx]
                if base and version != 1:
                    return {3: base, 2: base // 2, 0: base // 4}[version]
            i += 1
    except (OSError, wave.Error, EOFError, struct.error):
        return None
    return None


def ready_sd_card(cfg, name: str, files: list[Path]) -> tuple[Path, list[str]]:
    """Copy `files`, in order, into audio/sd-cards/<name>/ as 01/001.mp3,
    01/002.mp3..., the DFPlayer's numbered folders; write index.txt (which
    number is which sound). Returns (folder, problems): a file the module
    may not play is still copied, and said."""
    files = [Path(f) for f in files]
    if not files:
        raise ValueError("choose the sounds first")
    if len(files) > DFPLAYER_FOLDERS * DFPLAYER_PER_FOLDER:
        raise ValueError(f"a DFPlayer holds at most {DFPLAYER_FOLDERS * DFPLAYER_PER_FOLDER} sounds")
    slug = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip()
    if not slug:
        raise ValueError("give the card a name")
    out = shelf(cfg, "sd-cards") / slug
    if out.exists():
        shutil.rmtree(out)
    problems, index = [], []
    for n, f in enumerate(files):
        folder, number = n // DFPLAYER_PER_FOLDER + 1, n % DFPLAYER_PER_FOLDER + 1
        ext = f.suffix.lower()
        if ext not in (".mp3", ".wav"):
            problems.append(f"{f.name}: a DFPlayer plays MP3 (and, by common use, WAV), not {ext}")
        elif ext == ".wav":
            problems.append(f"{f.name}: WAV is not on DFRobot's page; MP3 is the sure choice")
        rate = sample_rate(f)
        if rate and rate not in DFPLAYER_RATES:
            problems.append(f"{f.name}: {rate} Hz is not a rate the module lists")
        dest = out / f"{folder:02d}" / f"{number:03d}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        index.append(f"{folder:02d}/{number:03d}{ext}  playFolder({folder}, {number})  {f.name}")
    (out / "index.txt").write_text(
        "Copy the numbered folders to the root of a FAT16 or FAT32 card of up to 32 GB.\n"
        "Folder, file, the Arduino call that plays it, and the sound it was:\n\n"
        + "\n".join(index) + "\n", encoding="utf-8")
    return out, problems
