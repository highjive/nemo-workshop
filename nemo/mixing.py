"""The Music Room's Mix Engineer and Mastering Engineer (owner, 2026-11-19; nemo/crafts.py).

Mix Engineer: your stems (one file per instrument or voice) into one mix. CODE decides the
starting balance and SoundCraft does the mixing: each stem is measured (RMS of its
loudest part), brought to the same level (LEVEL_DB) and moved by any change you ask
("vocals=+3"), then SoundCraft lays them on tracks, sets each track's volume and pan, and
bounces the mix. If the bounce peaks above PEAK_DB, every track comes down by the same
amount and it is bounced again, once. The SoundCraft session is kept beside the mix so
you can open it and carry on by hand. Nothing is guessed about the music: equal levels
are a starting point, said as one.

Mastering Engineer: Matchering 2.0.6 (GPL-3.0, sergree/matchering) makes your track
sound like a reference track you choose (its loudness, tone and width). You give the
reference: Nemo never fetches one.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

LEVEL_DB = -20.0           # each stem's loud-part RMS, dBFS, before your changes (a choice)
PEAK_DB = -1.0             # the bounce must peak below this (dBFS)
MAX_GAIN_DB = 12.0         # SoundCraft's track volume runs -144..+12 dB
MIN_GAIN_DB = -40.0
AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".ogg")


class MixError(RuntimeError):
    pass


@dataclass
class Stem:
    path: Path
    name: str
    rms_db: float
    change_db: float = 0.0     # the owner's
    pan: float = 0.0           # -1 left .. 1 right; the owner's

    @property
    def gain_db(self) -> float:
        g = LEVEL_DB - self.rms_db + self.change_db
        return round(max(MIN_GAIN_DB, min(MAX_GAIN_DB, g)), 2)


@dataclass
class Mix:
    out: Path
    session: Path
    stems: list[Stem]
    lufs: float | None
    peak_db: float | None
    trimmed_db: float = 0.0
    notes: list[str] = field(default_factory=list)


def loud_rms_db(path: Path, block_s: float = 0.4) -> float:
    """The RMS of the loudest tenth of the file's 0.4 s blocks, in dBFS: a stem with long
    silences is judged by where it plays. -inf for silence."""
    import numpy as np
    import soundfile as sf
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    n = max(1, int(rate * block_s))
    blocks = [mono[i:i + n] for i in range(0, len(mono), n)]
    rms = sorted((float(np.sqrt(np.mean(b * b))) for b in blocks if len(b)), reverse=True)
    top = rms[:max(1, len(rms) // 10)]
    level = sum(top) / len(top) if top else 0.0
    return 20 * math.log10(level) if level > 0 else float("-inf")


_CHANGE = re.compile(r"^(?P<name>[^=]+)=(?P<db>[+-]?\d+(?:\.\d+)?)(?:db)?"
                     r"(?:,(?P<pan>left|right|centre|center|[+-]?\d*\.?\d+))?$", re.I)


def changes(words: list[str]) -> tuple[list[str], dict[str, tuple[float, float | None]]]:
    """Split 'vocals=+3' / 'bass=-2,left' / 'gtr=0,-0.5' from the stems: (stems, {name:
    (dB, pan)}). A pan word: left -0.6, right 0.6, centre 0."""
    stems, said = [], {}
    for w in words:
        m = _CHANGE.match(w.strip())
        if not m:
            stems.append(w)
            continue
        pan = m.group("pan")
        p = None
        if pan:
            p = {"left": -0.6, "right": 0.6, "centre": 0.0, "center": 0.0}.get(pan.lower())
            p = float(pan) if p is None else p
            if not -1 <= p <= 1:
                raise MixError(f"pan {pan} is outside -1 (left) to 1 (right)")
        said[m.group("name").strip().lower()] = (float(m.group("db")), p)
    return stems, said


def plan(paths: list[Path], said: dict[str, tuple[float, float | None]]) -> list[Stem]:
    """Each stem measured, with the owner's changes; a change naming no stem is refused."""
    if not paths:
        raise MixError("no stems given")
    stems = []
    for p in paths:
        if not p.is_file():
            raise MixError(f"{p} is not there")
        if p.suffix.lower() not in AUDIO:
            raise MixError(f"{p.name} is not a sound file Nemo mixes ({', '.join(AUDIO)})")
        rms = loud_rms_db(p)
        if rms == float("-inf"):
            raise MixError(f"{p.name} is silent")
        stems.append(Stem(p, p.stem, rms))
    for key, (db, pan) in said.items():
        hit = [s for s in stems if s.name.lower() == key or s.name.lower().startswith(key)]
        if len(hit) != 1:
            raise MixError(f"'{key}' names {'no' if not hit else len(hit)} stem(s): "
                           + ", ".join(s.name for s in stems))
        hit[0].change_db = db
        if pan is not None:
            hit[0].pan = pan
    return stems


def soundcraft_commands(stems: list[Stem]) -> list[tuple[str, dict]]:
    """Engine commands: import every stem on its own track (tracks are numbered as SoundCraft
    numbers them: read back from the import's own answer, see mix()), then volume and pan."""
    return [("file.import_audio", {"paths": [str(s.path) for s in stems]})]


def pan_commands(track: int, channels: int, pan: float) -> list[tuple[str, dict]]:
    """A mono track is panned; a stereo one is BALANCED: toward the right, its left channel
    moves in to the middle and beyond (at 0.5 the left sits in the centre), its right stays
    hard right; and the other way round. Panning both channels of a stereo track to one
    place (SoundCraft's own pan with no index) lost one side of it (2026-11-19)."""
    if not pan:
        return []
    if channels < 2:
        return [("mix.pan", {"tracks": [track], "pan": pan})]
    left, right = (-1 + 2 * pan, 1.0) if pan > 0 else (-1.0, 1 + 2 * pan)
    return [("mix.pan", {"tracks": [track], "pan": round(max(-1, min(1, left)), 3), "index": 0}),
            ("mix.pan", {"tracks": [track], "pan": round(max(-1, min(1, right)), 3), "index": 1})]


def _run(cmds: list[tuple[str, dict]], cfg, bounce: Path | None = None,
         session_in: Path | None = None, save: Path | None = None) -> list[dict]:
    from . import crafts
    argv = ["run"]
    if session_in is not None:
        argv += ["--in", str(session_in)]
    for cid, params in cmds:
        argv += ["--cmd", f"{cid}={json.dumps(params)}"]
    if bounce is not None:
        argv += ["--bounce", str(bounce)]
    if save is not None and save == session_in:
        argv += ["--in-place"]                 # SoundCraft refuses --save onto its --in
    elif save is not None:
        argv += ["--save", str(save)]
    out = crafts.run_cli("soundcraft", argv, cfg, timeout=1800)
    got = []
    for line in out.splitlines():
        head, _, rest = line.partition(": ")
        try:
            got.append({"id": head, "result": json.loads(rest)} if rest else json.loads(line))
        except ValueError:
            try:
                got.append(json.loads(line))
            except ValueError:
                continue
    return got


def mix(cfg, name: str, paths: list[Path], said: dict | None = None, say=print) -> Mix:
    """The Mix Engineer's mix: <music shelf>/mixes/<name>/<name>.wav, .scraft and .json."""
    from . import filmstudio, music
    stems = plan(paths, said or {})
    slug = filmstudio._slug(name or "mix")
    work = music.shelf(cfg) / "mixes" / slug
    work.mkdir(parents=True, exist_ok=True)
    session = work / f"{slug}.scraft"
    out = work / f"{slug}.wav"
    say(f"Mix Engineer: {len(stems)} stem(s), each brought to {LEVEL_DB:g} dBFS"
        + (" with your changes" if said else ""))
    got = _run(soundcraft_commands(stems), cfg, save=session)
    imported = next((g["result"].get("imported") for g in got
                     if g.get("id") == "file.import_audio" and isinstance(g.get("result"), dict)),
                    None)
    if not imported or len(imported) != len(stems):
        raise MixError("SoundCraft did not say which track each stem went on")
    tracks = [i["track"] for i in imported]
    channels = [i.get("channels", 1) for i in imported]
    trim, bounce, notes = 0.0, None, []
    for attempt in (1, 2):
        cmds = []
        for s, t, ch in zip(stems, tracks, channels):
            cmds.append(("mix.volume", {"tracks": [t], "db": max(MIN_GAIN_DB, s.gain_db - trim)}))
            cmds += pan_commands(t, ch, s.pan)
        got = _run(cmds, cfg, session_in=session, bounce=out, save=session)
        bounce = next((g for g in got if isinstance(g, dict) and "peak_db" in g), None)
        if bounce is None:
            raise MixError("SoundCraft bounced nothing it reported")
        peak = bounce.get("true_peak_db", bounce.get("peak_db"))
        if peak is None or peak <= PEAK_DB or attempt == 2:
            break
        trim = round(peak - PEAK_DB + 0.5, 2)
        notes.append(f"the first bounce peaked at {peak:.1f} dBFS: every track down {trim:g} dB")
    peak = bounce.get("true_peak_db", bounce.get("peak_db"))
    if peak is not None and peak > PEAK_DB:
        notes.append(f"it still peaks at {peak:.1f} dBFS: lower a loud stem or master it")
    notes.append("equal levels are a starting point, not a judgement of the music: change a "
                 "stem with name=+dB, or open the .scraft session in SoundCraft")
    m = Mix(out, session, stems, bounce.get("lufs"), peak, trim, notes)
    (work / f"{slug}.json").write_text(json.dumps({
        "stems": [{"file": str(s.path), "measured_db": round(s.rms_db, 2),
                   "your_change_db": s.change_db, "pan": s.pan,
                   "volume_db": round(s.gain_db - trim, 2)} for s in stems],
        "lufs": m.lufs, "peak_db": peak, "trimmed_db": trim, "notes": notes},
        indent=2), encoding="utf-8")
    return m


def master(cfg, track: Path, reference: Path, say=print) -> Path:
    """The Mastering Engineer: <track>-mastered.wav (24-bit) beside the mix, made like the
    reference by Matchering."""
    try:
        import matchering as mg
    except ImportError as exc:
        raise MixError("Matchering is not installed (NemoDoc installs it)") from exc
    for p, what in ((track, "track"), (reference, "reference")):
        if not Path(p).is_file():
            raise MixError(f"the {what} {p} is not there")
    out = Path(track).with_name(Path(track).stem + "-mastered.wav")
    say(f"Mastering Engineer: {Path(track).name} made like {Path(reference).name}")
    try:
        mg.log(info_handler=lambda m: None, warning_handler=lambda m: say(f"Matchering: {m}"))
        mg.process(target=str(track), reference=str(reference),
                   results=[mg.pcm24(str(out))])
    except Exception as exc:          # Matchering raises its own ModuleError kinds
        raise MixError(f"Matchering stopped: {exc}") from exc
    if not out.is_file():
        raise MixError("Matchering wrote nothing")
    return out
