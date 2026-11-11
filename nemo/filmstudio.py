"""The Film Studio: films from stories, your own clips joined, and slideshows
(owner, 2026-10-22: "films from stories, edit your own videos, slideshows
from pictures").

  Director          splits a story into scenes, a few paragraphs each, and
                    gives each a picture prompt from its own words; the
                    plan (film.json) can be changed before anything is made
  Storyboard Artist one picture per scene with the Library's image engine
                    (artist.paint: about 11 minutes a picture on the AH531),
                    or the pictures given (the story's cover, your own)
  Narrator          each scene read aloud with Nemo's voice (voice.speak)
  Editor            ffmpeg puts it together: each picture with a slow zoom
                    for as long as its narration, a title card, credits;
                    H.264 High level 4.0 and AAC at 1280 x 720, which every
                    Chromecast plays (mediainfo checks it). It also joins
                    your own clips, trimmed, and makes slideshows of
                    pictures over Music Room tracks
  Writer            the title and credits cards, and subtitles (.srt)
                    beside the film

The finished film goes on the Storeroom's videos shelf, where the Theatre
finds it. The working files are kept in <storeroom>/film-studio/<film> and
left out of backups (they can be made again). Nothing asks the model.

ffmpeg 9.0.2 (GyanD's essentials build, C:/Nemo/tools) ran on the AH531 with
no AVX: a 4.7 s scene with zoom and narration took 6.9 s (2026-10-22).
"""
from __future__ import annotations

import json
import re
import shutil
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

# What NemoDoc.ps1 fetches into <prefix>\tools (a test ties them): GyanD's
# release, with its own sha256 on GitHub, checked 2026-10-22.
SOURCE = ("ffmpeg-9.0.2-essentials_build.7z", 35430500,
          "4705843ccaaf54257c16ad90f3e952ece33c17df964ecf7bfdbb0f49c7171077")
FOLDER = "ffmpeg-9.0.2-essentials_build"

WIDTH, HEIGHT, FPS = 1280, 720, 30
SCENE_CHARS = 700            # a scene is a few paragraphs, about a minute read aloud
MAX_SCENES = 12
TITLE_SECONDS, CREDITS_SECONDS = 4, 5
# The same for every piece, so the pieces join without being made again.
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-level", "4.0",
          "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
          "-ac", "2"]


class FilmError(RuntimeError):
    pass


@dataclass
class Scene:
    text: str                       # what the Narrator reads
    prompt: str = ""                # what the Storyboard Artist paints
    picture: str = ""               # a picture to use, or "" to paint one


@dataclass
class Plan:
    title: str
    story: str = ""
    scenes: list[Scene] = field(default_factory=list)


@dataclass
class Made:
    film: Path
    seconds: float
    subtitles: Path | None = None
    notes: list[str] = field(default_factory=list)


def ffmpeg(cfg=None) -> Path | None:
    """ffmpeg: the configured file, Nemo's own copy, or the system's."""
    found = []
    if cfg is not None and cfg.get("paths.ffmpeg"):
        found.append(Path(str(cfg.get("paths.ffmpeg"))).expanduser())
    if cfg is not None and cfg.get("paths.llama_server"):
        engine = Path(str(cfg.get("paths.llama_server"))).expanduser()
        found.append(engine.parent.parent / "tools" / FOLDER / "bin" / "ffmpeg.exe")
    found.append(Path(r"C:\Nemo\tools") / FOLDER / "bin" / "ffmpeg.exe")
    which = shutil.which("ffmpeg")
    if which:
        found.append(Path(which))
    return next((p for p in found if p.is_file()), None)


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _-]+", "", s).strip()[:60] or "film"


def studio(cfg, name: str) -> Path:
    return cfg.path("paths.storeroom") / "film-studio" / _slug(name)


def videos_shelf(cfg) -> Path:
    from . import storeroom
    return storeroom.shelf(cfg.path("paths.storeroom"), "videos")


# ---------------------------------------------------------------- the Director
def _story_text(folder: Path) -> str:
    chapters = sorted((folder / "chapters").glob("*.md"))
    files = chapters or ([folder / "story.md"] if (folder / "story.md").is_file() else [])
    if not files:
        raise FilmError("the story has no chapters written yet")
    return "\n\n".join(f.read_text(encoding="utf-8-sig", errors="replace") for f in files)


def _prompt(text: str, title: str = "", known: set[str] = frozenset()) -> str:
    """What the Artist paints for a scene: the story's title, so it knows
    what the story is about, and the first of the scene's first three
    sentences that names someone the story names, else its first sentence
    (2026-11-06: scenes were painted from "He climbed the spiral staircase"
    and "a pair of bright eyes blinked open", with no cat and no lighthouse)."""
    from .artist import STYLE
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    named = [x for x in sentences[:3] if any(n.split()[-1] in x for n in known)]
    pick = (named or sentences)[0]
    about = f", from the story \"{title}\"" if title else ""
    return f"{STYLE}{about}: " + " ".join(pick.split()[:40])


def plan_story(folder: Path) -> Plan:
    """The Director: scenes of a few paragraphs each, at most MAX_SCENES
    (later paragraphs join the last scenes rather than being dropped)."""
    from .artist import title_and_request
    from .audio import _plain
    folder = Path(folder)
    title = title_and_request(folder)[0] or folder.name
    paras = [p.strip() for p in _plain(_story_text(folder)).split("\n\n") if p.strip()]
    # The title and short "Chapter 2. The Light" headings are not scenes.
    heading = re.compile(r"Chapter \d+\.?.{0,60}")
    paras = [p for p in paras if p != title and not (len(p) <= 80 and heading.fullmatch(p))]
    if not paras:
        raise FilmError("the story has no paragraphs to film")
    total = sum(len(p) for p in paras)
    size = max(SCENE_CHARS, total // MAX_SCENES + 1)
    scenes, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > size:
            scenes.append(cur); cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    scenes.append(cur)
    # Paragraphs never fill a scene exactly, so the packing above can run
    # over (15 for a long story in a test): join the shortest neighbours.
    while len(scenes) > MAX_SCENES:
        i = min(range(len(scenes) - 1), key=lambda k: len(scenes[k]) + len(scenes[k + 1]))
        scenes[i:i + 2] = [scenes[i] + "\n\n" + scenes[i + 1]]
    from .stories import names
    known = names(_story_text(folder))
    return Plan(title, str(folder), [Scene(t, _prompt(t, title, known)) for t in scenes])


def save_plan(cfg, plan: Plan) -> Path:
    work = studio(cfg, plan.title)
    work.mkdir(parents=True, exist_ok=True)
    p = work / "film.json"
    p.write_text(json.dumps(asdict(plan), indent=1), encoding="utf-8")
    return p


def load_plan(path: Path) -> Plan:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return Plan(d["title"], d.get("story", ""), [Scene(**s) for s in d.get("scenes", [])])


def stories(cfg) -> list[Path]:
    """The Library's stories that have something written to film."""
    root = cfg.path("paths.stories")
    return sorted((d for d in root.iterdir() if d.is_dir() and (
        (d / "story.md").is_file() or any((d / "chapters").glob("*.md")))),
        key=lambda d: d.name.lower()) if root.is_dir() else []


def plan_for(cfg, story: Path) -> Plan:
    """The plan kept for this story, changed by hand or not, else a new one."""
    from .artist import title_and_request
    title = title_and_request(Path(story))[0] or Path(story).name
    kept = studio(cfg, title) / "film.json"
    return load_plan(kept) if kept.is_file() else plan_story(story)


def clip_spec(text: str) -> tuple[str, float | None, float | None]:
    """'holiday.mp4@5-20' -> ('holiday.mp4', 5.0, 20.0); a clip whole without @."""
    name, _, cut = text.partition("@")
    if not cut:
        return name, None, None
    a, _, b = cut.partition("-")
    try:
        return name, (float(a) if a else None), (float(b) if b else None)
    except ValueError:
        raise FilmError(f"{text!r}: a cut is @start-end in seconds, such as @5-20") from None


# ---------------------------------------------------------------- running ffmpeg
def _run(cfg, args: list[str], timeout: int = 3600) -> None:
    from .checks.runners import _run as run
    exe = ffmpeg(cfg)
    if exe is None:
        raise FilmError("ffmpeg is not installed (NemoDoc fetches it; C:\\Nemo\\tools)")
    rc, so, se = run([str(exe), "-hide_banner", "-loglevel", "error", "-y", *args],
                     timeout=timeout)
    if rc != 0:
        tail = [l for l in (se or so or "").splitlines() if l.strip()][-3:]
        raise FilmError(f"ffmpeg stopped (code {rc})" + (": " + " ".join(tail) if tail else ""))


def _zoom(seconds: float) -> str:
    """A slow zoom towards the middle over the whole scene, as a filter."""
    frames = max(1, int(seconds * FPS))
    step = 0.15 / frames
    return (f"scale={WIDTH * 2}:-2,zoompan=z='min(zoom+{step:.6f},1.15)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={WIDTH}x{HEIGHT}:fps={FPS},"
            f"format=yuv420p")


def _still(cfg, picture: Path, seconds: float, out: Path, audio: Path | None = None) -> None:
    """One piece: a picture zooming for `seconds`, over `audio` or silence."""
    sound = ["-i", str(audio)] if audio else ["-f", "lavfi", "-t", f"{seconds:.3f}",
                                             "-i", "anullsrc=r=44100:cl=stereo"]
    # -framerate: a looped picture comes in at 25 a second unless told, and
    # zoompan makes one frame per frame in: the first real film had 26 frames
    # a second and ended 0.9 s before its sound (2026-10-22).
    _run(cfg, ["-framerate", str(FPS), "-loop", "1", "-t", f"{seconds:.3f}", "-i", str(picture), *sound,
               "-filter_complex", f"[0:v]{_zoom(seconds)}[v]", "-map", "[v]", "-map", "1:a",
               *ENCODE, "-t", f"{seconds:.3f}", str(out)])


def _join(cfg, pieces: list[Path], out: Path) -> None:
    """Pieces made with the same settings, one after another, not made again."""
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces), encoding="utf-8")
    _run(cfg, ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
               "-movflags", "+faststart", str(out)])
    listing.unlink(missing_ok=True)


# ---------------------------------------------------------------- the Writer
def _font(size: int):
    from PIL import ImageFont
    for name in ("arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def card(lines: list[tuple[str, int]], out: Path) -> Path:
    """A plain card: lines of (text, size) in the middle, light on dark."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (WIDTH, HEIGHT), (16, 20, 26))
    d = ImageDraw.Draw(img)
    fonts = [(t, _font(s)) for t, s in lines]
    heights = [d.textbbox((0, 0), t or " ", font=f)[3] + 18 for t, f in fonts]
    y = (HEIGHT - sum(heights)) // 2
    for (t, f), h in zip(fonts, heights):
        w = d.textbbox((0, 0), t, font=f)[2]
        d.text(((WIDTH - w) // 2, y), t, font=f, fill=(232, 222, 196))
        y += h
    img.save(out)
    return out


def _stamp(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def subtitles(scenes: list[tuple[str, float, float]], out: Path) -> Path:
    """An .srt: each scene's words in pieces of a sentence or so, timed by
    their share of the scene's characters (the voice reads evenly enough)."""
    n, lines = 0, []
    for text, start, length in scenes:
        bits = [b.strip() for b in re.split(r"(?<=[.!?;:])\s+", re.sub(r"\s+", " ", text)) if b.strip()]
        chars = sum(len(b) for b in bits) or 1
        t = start
        for b in bits:
            dur = length * len(b) / chars
            n += 1
            lines += [str(n), f"{_stamp(t)} --> {_stamp(t + dur)}", b, ""]
            t += dur
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# ---------------------------------------------------------------- films from stories
def make_film(cfg, plan: Plan, paint: bool = True, say=print) -> Made:
    """The whole film: pictures, narration, title, credits, joined. A scene
    with a picture given keeps it; with none, it is painted (paint=True) or
    has the story's cover or a card with its first words."""
    from . import audio, timekeeper, voice
    began = time.time()
    work = studio(cfg, plan.title)
    work.mkdir(parents=True, exist_ok=True)
    save_plan(cfg, plan)
    cover = Path(plan.story) / "cover.png" if plan.story else None
    pieces, timed, notes, t = [], [], [], float(TITLE_SECONDS)
    title_png = card([(plan.title, 64)], work / "title.png")
    pieces.append(work / "00-title.mp4")
    _still(cfg, title_png, TITLE_SECONDS, pieces[-1])
    painted = 0
    for n, s in enumerate(plan.scenes, 1):
        say(f"Film Studio: scene {n} of {len(plan.scenes)}")
        pic = Path(s.picture) if s.picture else work / f"scene{n:02d}.png"
        if not pic.is_file():
            if paint:
                from . import artist
                artist.paint(pic, s.prompt, cfg, say=say)
                painted += 1
            elif cover is not None and cover.is_file():
                pic = cover
            else:
                pic = card([(" ".join(s.text.split()[:8]) + "...", 40)], pic)
        wav = work / f"scene{n:02d}.wav"
        parts = []
        for i, piece in enumerate(audio._chunks(s.text)):
            part = work / f"scene{n:02d}-{i:02d}.wav"
            ok, why = voice.speak(piece, wav=part, wait=True, whole=True)
            if not ok or not part.is_file():
                raise FilmError(f"the Narrator could not read scene {n}: {why}")
            parts.append(part)
        secs = audio._join_wavs(parts, wav)
        for p in parts:
            p.unlink(missing_ok=True)
        pieces.append(work / f"{n:02d}-scene.mp4")
        _still(cfg, pic, secs + 0.6, pieces[-1], wav)
        timed.append((s.text, t, secs))
        t += secs + 0.6
    credits = card([(plan.title, 44), ("", 20), ("Written in Nemo's Library", 30),
                    (("Pictures by Nemo's Artist" if painted else "Pictures from the Storeroom"), 30),
                    ("Read by Nemo's voice", 30), ("Put together in the Film Studio", 30)],
                   work / "credits.png")
    pieces.append(work / "99-credits.mp4")
    _still(cfg, credits, CREDITS_SECONDS, pieces[-1])
    shelf = videos_shelf(cfg)
    shelf.mkdir(parents=True, exist_ok=True)
    film = shelf / f"{_slug(plan.title)}.mp4"
    _join(cfg, pieces, film)
    srt = subtitles(timed, film.with_suffix(".srt"))
    took = time.time() - began
    timekeeper.record("film", "film", took, True)
    total = t + CREDITS_SECONDS
    notes.append(f"{len(plan.scenes)} scene(s), {total:.0f} s long, made in {took:.0f} s"
                 + (f"; {painted} picture(s) painted" if painted else ""))
    return Made(film, total, srt, notes)


# ---------------------------------------------------------------- your own clips
def has_sound(cfg, clip: Path) -> bool:
    """Whether a clip has a sound track, by ffprobe beside ffmpeg."""
    from .checks.runners import _run as run
    exe = ffmpeg(cfg)
    probe = exe.with_name("ffprobe" + exe.suffix) if exe else None
    if probe is None or not probe.is_file():
        found = shutil.which("ffprobe")
        probe = Path(found) if found else None
    if probe is None:
        raise FilmError("ffprobe is not installed beside ffmpeg")
    rc, so, _ = run([str(probe), "-v", "error", "-select_streams", "a", "-show_entries",
                     "stream=index", "-of", "csv=p=0", str(clip)], timeout=60)
    return rc == 0 and bool(so.strip())


def _fit(cfg, clip: Path, out: Path, start: float | None, end: float | None) -> None:
    """A clip made like every other piece: 1280 x 720 (bars where its shape
    differs), 30 frames a second, stereo; silence where it has no sound."""
    cut = (["-ss", f"{start:.3f}"] if start else []) + (["-to", f"{end:.3f}"] if end else [])
    vf = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
          f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p")
    sound = ["-map", "0:a:0"] if has_sound(cfg, clip) else ["-map", "1:a", "-shortest"]
    _run(cfg, [*cut, "-i", str(clip), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
               "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", *sound, *ENCODE, str(out)])


def join_clips(cfg, name: str, clips: list[tuple[Path, float | None, float | None]]) -> Made:
    """Your clips, each trimmed to (start, end) seconds if given, one after
    another, as one film on the videos shelf."""
    if not clips:
        raise FilmError("choose at least one clip")
    work = studio(cfg, name)
    work.mkdir(parents=True, exist_ok=True)
    pieces = []
    for n, (clip, start, end) in enumerate(clips, 1):
        if not Path(clip).is_file():
            raise FilmError(f"{Path(clip).name} is not there")
        pieces.append(work / f"clip{n:02d}.mp4")
        _fit(cfg, Path(clip), pieces[-1], start, end)
    film = videos_shelf(cfg) / f"{_slug(name)}.mp4"
    film.parent.mkdir(parents=True, exist_ok=True)
    _join(cfg, pieces, film)
    return Made(film, 0.0, None, [f"{len(clips)} clip(s) joined"])


# ---------------------------------------------------------------- slideshows
def slideshow(cfg, name: str, pictures: list[Path], music: list[Path] | None = None,
              seconds: float = 5.0) -> Made:
    """Pictures, each zooming slowly for `seconds`, over the music given
    (cut at the end of the pictures, silence after it if it is shorter)."""
    if not pictures:
        raise FilmError("choose at least one picture")
    work = studio(cfg, name)
    work.mkdir(parents=True, exist_ok=True)
    pieces = []
    for n, pic in enumerate(pictures, 1):
        pieces.append(work / f"slide{n:02d}.mp4")
        _still(cfg, Path(pic), seconds, pieces[-1])
    silent = work / "slides.mp4"
    _join(cfg, pieces, silent)
    film = videos_shelf(cfg) / f"{_slug(name)}.mp4"
    film.parent.mkdir(parents=True, exist_ok=True)
    total = seconds * len(pictures)
    if music:
        ins = [x for m in music for x in ("-i", str(m))]
        mix = "".join(f"[{i + 1}:a]" for i in range(len(music)))
        _run(cfg, ["-i", str(silent), *ins, "-filter_complex",
                   f"{mix}concat=n={len(music)}:v=0:a=1,apad[a]", "-map", "0:v", "-map", "[a]",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                   "-t", f"{total:.3f}", "-movflags", "+faststart", str(film)])
    else:
        shutil.copy2(silent, film)
    return Made(film, total, None, [f"{len(pictures)} picture(s)"
                                    + (f" over {len(music)} track(s)" if music else "")])
