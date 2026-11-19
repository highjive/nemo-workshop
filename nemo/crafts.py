"""Programs Nemo drives but did not write (owner, 2026-11-19: "check out craftanything on
github, check for anime studio on github and music mixing, along with video creation";
"grab and add to nemo"; he chose SoundCraft + Matchering, OpenToonz, FilmCraft on the desktop,
and Craft Anything on the desktop with his own sign-in).

  SoundCraft    (storytold/soundcraft, MIT OR Apache-2.0): the Music Room's Mix Engineer
                lays stems out and bounces the mix headless (nemo/mixing.py).
  FilmCraft     (storytold/filmcraft, MIT OR Apache-2.0): the Film Studio's Finishing
                Editor makes a film's pieces into a FilmCraft project to cut by hand.
  OpenToonz     (opentoonz/opentoonz, BSD-3-Clause; the Toonz line): the Film Studio's
                Animator; tcomposer renders a scene's frames, ffmpeg makes the video.
  Craft Anything (storytold/craft-anything, MIT OR Apache-2.0): the Computer Lab's
                Rebuilder. It builds ONLY through an online coding agent signed in to the
                owner's own account; Nemo never signs in, sets up or runs a rebuild, it
                opens the program and reads its doctor. Clean room is its default.

All four are pinned below by GitHub's own sha256 (also in each release's SHA256SUMS.txt;
OpenToonz's release has no SUMS file, its digest is GitHub's). NemoDoc fetches the Windows
builds. NemoIso (owner, 2026-11-19: "use rea to make them available on the stick") has the
Linux builds of SoundCraft, FilmCraft and Craft Anything (LINUX, below; build-iso.sh puts
each folder in /opt/nemo/<key>), and Matchering. Their programs hold thousands of AVX
instructions (objdump) behind CPUID checks; under QEMU as a Sandy Bridge with AVX, AVX2,
FMA and F16C off, soundcraft-cli mixed and bounced and filmcraft-cli made a project and
exported H.264 (2026-11-19). Their windows are NOT tried on the AH531 (its graphics have no
Vulkan; FilmCraft has a software mode). OpenToonz has no Linux release and no Debian
package: not on NemoIso yet.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TOOLS_DIR = Path(r"C:\Nemo\tools")


@dataclass(frozen=True)
class Program:
    key: str
    label: str
    version: str
    file: str          # the release asset
    bytes: int
    sha256: str
    url: str
    folder: str        # under TOOLS_DIR
    app: str           # the windowed program
    cli: str = ""      # the command-line one, where there is one
    licence: str = ""


def _gh(repo: str, tag: str, file: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{file}"


PROGRAMS: dict[str, Program] = {p.key: p for p in (
    Program("soundcraft", "SoundCraft", "0.20.1", "soundcraft-0.20.1-windows-x64-portable.zip",
            19876437, "9769223e26f727866b249fc5176caa8b3791a98c7d89e901b78f5f48aff03b82",
            _gh("storytold/soundcraft", "v0.20.1", "soundcraft-0.20.1-windows-x64-portable.zip"),
            "soundcraft", "soundcraft.exe", "soundcraft-cli.exe", "MIT OR Apache-2.0"),
    Program("filmcraft", "FilmCraft", "0.20.1", "filmcraft-0.20.1-windows-x64-portable.zip",
            113447048, "bfb00e2089df5f13e6f76aab117a4572a8d005d009c5818989688b140a502710",
            _gh("storytold/filmcraft", "v0.20.1", "filmcraft-0.20.1-windows-x64-portable.zip"),
            "filmcraft", "filmcraft.exe", "filmcraft-cli.exe", "MIT OR Apache-2.0"),
    Program("craft-anything", "Craft Anything", "0.6.1",
            "craft-anything-0.6.1-windows-x64-portable.zip",
            69934191, "bd370fbaa2b44dbc13581db5ffd2bf66924ed40e433c7902212aa17ca781de54",
            _gh("storytold/craft-anything", "v0.6.1",
                "craft-anything-0.6.1-windows-x64-portable.zip"),
            "craft-anything", "craft-anything.exe", "craft-anything-cli.exe",
            "MIT OR Apache-2.0"),
    # An Inno Setup installer: NemoDoc runs it silently into tools\opentoonz. It also makes
    # C:\OpenToonz stuff (OpenToonz's own projects, palettes, settings) and one registry key
    # naming that folder (HKLM\SOFTWARE\OpenToonz); its uninstaller removes both.
    Program("opentoonz", "OpenToonz", "1.8.0", "OpenToonzSetup.exe",
            59788942, "bd678a03d2725522346bf5a055a7bc44ded6537957efb0026bfd875d3ac061d0",
            _gh("opentoonz/opentoonz", "v1.8.0", "OpenToonzSetup.exe"),
            "opentoonz", "OpenToonz.exe", "tcomposer.exe", "BSD-3-Clause"),
)}


# The Linux builds NemoIso carries (build-iso.sh fetches the same files; a test holds the two
# together): (release asset, bytes, GitHub's sha256). Each unpacks to <asset>/bin/<program>.
LINUX_DIR = Path("/opt/nemo")
LINUX: dict[str, tuple[str, int, str]] = {
    "soundcraft": ("soundcraft-0.20.1-linux-x86_64.tar.gz", 21894484,
                   "caefcf85c4f1138717d592d31ce5be07f2fca616ec36d63fac6760cdefbe28a9"),
    "filmcraft": ("filmcraft-0.20.1-linux-x86_64.tar.gz", 112162847,
                  "3e4fea3cb8d473e68f189a0a8792ba46160fab507adab3ab8920073fd41f24fa"),
    "craft-anything": ("craft-anything-0.6.1-linux-x86_64.tar.gz", 70371364,
                       "83ec0730c9117f399122b315c63ed4c3a8d31ac55bddd74cb8b33cd2f76ef704"),
}


class CraftError(RuntimeError):
    pass


def _windows() -> bool:
    return sys.platform.startswith("win")


def folder(key: str, cfg=None) -> Path:
    """Where the program is: config paths.<key> (a folder), else TOOLS_DIR/<folder> on
    Windows and /opt/nemo/<key>/bin elsewhere."""
    given = cfg.get(f"paths.{key}") if cfg is not None else None
    if given:
        return Path(given).expanduser()
    return TOOLS_DIR / PROGRAMS[key].folder if _windows() else LINUX_DIR / key / "bin"


def find(key: str, cfg=None, cli: bool = True) -> Path | None:
    """The program's command-line (cli=True) or windowed executable, or None."""
    p = PROGRAMS[key]
    name = p.cli if cli and p.cli else p.app
    if not _windows():
        name = name.removesuffix(".exe")
    exe = folder(key, cfg) / name
    return exe if exe.is_file() else None


def not_installed(key: str) -> str:
    p = PROGRAMS[key]
    if not _windows():
        return (f"{p.label} is not installed (looked in {folder(key)})"
                + ("; build-iso.sh puts it in the image" if key in LINUX else
                   "; it has no Linux build Nemo carries yet"))
    return (f"{p.label} {p.version} is not installed (looked in {TOOLS_DIR / p.folder}); "
            "NemoDoc fetches it on Windows")


def version(key: str, cfg=None) -> str | None:
    """The version the installed program says, or None."""
    exe = find(key, cfg)
    if exe is None:
        return None
    args = [str(exe), "-version"] if key == "opentoonz" else [str(exe), "--version"]
    try:
        out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", out.stdout + out.stderr)
    return m.group(1) if m else None


def open_app(key: str, *args: str, cfg=None) -> Path:
    """Open the windowed program (detached: Nemo does not wait for it)."""
    exe = find(key, cfg, cli=False)
    if exe is None:
        raise CraftError(not_installed(key))
    flags = 0x00000008 if sys.platform == "win32" else 0      # DETACHED_PROCESS
    subprocess.Popen([str(exe), *args], cwd=str(exe.parent), creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    return exe


def run_cli(key: str, args: list[str], cfg=None, timeout: int = 1800) -> str:
    """Run the program's command line; its output, or CraftError with its own words."""
    exe = find(key, cfg)
    if exe is None:
        raise CraftError(not_installed(key))
    try:
        p = subprocess.run([str(exe), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           cwd=str(exe.parent))
    except subprocess.TimeoutExpired as exc:
        raise CraftError(f"{PROGRAMS[key].label} did not finish in {timeout} s") from exc
    except OSError as exc:
        raise CraftError(f"{PROGRAMS[key].label} could not be started: {exc}") from exc
    if p.returncode != 0:
        said = (p.stderr or p.stdout).strip()
        raise CraftError(f"{PROGRAMS[key].label} stopped (exit {p.returncode}): "
                         + (said[-500:] or "it said nothing"))
    return p.stdout


# ------------------------------------------------------------------ FilmCraft
FILM_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm")


def film_pieces(cfg, title: str) -> tuple[list[Path], Path | None]:
    """A Film Studio film's pieces in order (title, scenes, credits: the work folder's
    NN-*.mp4), else the finished film alone; and its subtitles, if any."""
    from . import filmstudio as F
    slug = F._slug(title)
    work = F.studio(cfg, title)
    pieces = sorted(p for p in work.glob("[0-9][0-9]-*.mp4")) if work.is_dir() else []
    shelf = F.videos_shelf(cfg)
    film = next((shelf / f"{slug}{s}" for s in FILM_SUFFIXES if (shelf / f"{slug}{s}").is_file()),
                None)
    if not pieces and film is None:
        given = Path(title).expanduser()
        if given.is_file() and given.suffix.lower() in FILM_SUFFIXES:
            film, slug = given, F._slug(given.stem)
    if not pieces and film is None:
        raise CraftError(f"no film called {title!r} on the videos shelf or in the Film Studio")
    srt = (film.with_suffix(".srt") if film else shelf / f"{slug}.srt")
    return (pieces or [film]), (srt if srt.is_file() else None)


def filmcraft_script(pieces: list[Path], name: str, project: Path, srt: Path | None,
                     width: int = 1280, height: int = 720, fps: float = 30) -> list[dict]:
    """FilmCraft engine commands: a project, the pieces imported and laid on one sequence
    in order with no transitions, saved; then the subtitles as a caption track, saved again. The Film
    Studio's ENCODE is 1280x720 at 30 fps, so the sequence is too."""
    def p(x: Path) -> str:
        return str(x).replace("\\", "/")
    cmds = [
        {"id": "file.newProject", "params": {"name": name}},
        {"id": "file.import", "params": {"paths": [p(x) for x in pieces]}},
        {"id": "file.newSequence", "params": {"name": name, "width": width,
                                               "height": height, "fps": fps}},
        {"id": "clip.automateToSequence",
         "params": {"items": list(range(1, len(pieces) + 1)), "ordering": "selection",
                    "placement": "sequentially", "method": "insert", "overlapFrames": 0,
                    "videoTransition": False, "audioTransition": False}},
    ]
    cmds.append({"id": "file.saveAs", "params": {"path": p(project)}})
    if srt is not None:     # after the first save: subtitles it cannot read lose only themselves
        cmds.append({"id": "captions.import", "params": {"path": p(srt), "language": "en"}})
        cmds.append({"id": "file.save", "params": {}})
    return cmds


def results(out: str) -> list[dict]:
    """filmcraft-cli run prints one JSON object a line; what does not parse is left out."""
    got = []
    for line in out.splitlines():
        try:
            got.append(json.loads(line))
        except ValueError:
            continue
    return got


def hand_edit(cfg, title: str, open_it: bool = True, say=print) -> Path:
    """The Finishing Editor: the film as a FilmCraft project beside its pieces, opened to cut
    by hand. Nothing of the film is changed."""
    from . import filmstudio as F
    pieces, srt = film_pieces(cfg, title)
    work = F.studio(cfg, title)
    work.mkdir(parents=True, exist_ok=True)
    project = work / f"{F._slug(title)}.fcproj"
    script = work / "filmcraft-commands.jsonl"
    cmds = filmcraft_script(pieces, title, project, srt)
    script.write_text("\n".join(json.dumps(c) for c in cmds) + "\n", encoding="utf-8")
    try:
        out = run_cli("filmcraft", ["run", str(script)], cfg)
    except CraftError as exc:
        out = str(exc)                     # exit 1 still printed what each line did
    got = results(out[out.find("{"):] if "{" in out else out)
    saved = next((i for i, g in enumerate(got) if g.get("id") == "file.saveAs"), None)
    if saved is None or not got[saved].get("ok") or not project.is_file():
        failed = next((g for g in got if not g.get("ok")), None)
        raise CraftError("FilmCraft could not make the project: "
                         + (failed.get("error", "") if failed else out.strip()[-300:]))
    subtitled = srt is not None and len(got) == len(cmds) and all(g.get("ok") for g in got)
    say(f"Finishing Editor: {len(pieces)} piece(s)"
        + (" and the subtitles" if subtitled else "") + f" in {project}")
    if srt is not None and not subtitled:
        failed = next((g for g in got[saved + 1:] if not g.get("ok")), {})
        say(f"Finishing Editor: the subtitles were not added ({failed.get('error', 'no answer')}); "
            "the film is in the project without them")
    if open_it:
        open_app("filmcraft", str(project), cfg=cfg)
        say("FilmCraft is opening it: cut by hand there, and export from its File menu.")
    return project


# ------------------------------------------------------------------ OpenToonz
def opentoonz_scenes() -> list[Path]:
    """OpenToonz's own scenes (.tnz) under its projects folder."""
    root = Path(r"C:\OpenToonz stuff\projects")
    return sorted(root.rglob("*.tnz")) if root.is_dir() else []


def render_scene(cfg, scene: Path, name: str = "", first: int | None = None,
                 last: int | None = None, fps: int = 24, say=print) -> Path:
    """The Animator: an OpenToonz scene rendered frame by frame with its own renderer
    (tcomposer), then made a video with the Film Studio's ffmpeg, onto the videos shelf.
    NOT YET TRIED on a real scene (none here on 2026-11-19)."""
    from . import filmstudio as F
    scene = Path(scene).expanduser()
    if not scene.is_file() or scene.suffix.lower() != ".tnz":
        raise CraftError(f"{scene} is not an OpenToonz scene (.tnz)")
    ff = F.ffmpeg(cfg)
    if ff is None:
        raise CraftError("ffmpeg is not installed (NemoDoc fetches it)")
    name = name or scene.stem
    work = F.studio(cfg, name) / "frames"
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("frame*.png"):
        old.unlink()
    args = [str(scene), "-o", str(work / "frame.png")]
    if first is not None and last is not None:
        args += ["-range", str(first), str(last)]
    say(f"Animator: OpenToonz renders {scene.name}")
    run_cli("opentoonz", args, cfg, timeout=7200)
    frames = sorted(work.glob("frame*.png"))
    if not frames:
        raise CraftError("OpenToonz rendered no frames (tcomposer wrote nothing)")
    m = re.match(r"frame\.(\d+)\.png$", frames[0].name)
    pattern = f"frame.%0{len(m.group(1))}d.png" if m else None
    if pattern is None:
        raise CraftError(f"OpenToonz named its frames {frames[0].name}: not a numbered sequence")
    shelf = F.videos_shelf(cfg)
    shelf.mkdir(parents=True, exist_ok=True)
    out = shelf / f"{F._slug(name)}.mp4"
    p = subprocess.run([str(ff), "-y", "-loglevel", "error", "-framerate", str(fps),
                        "-start_number", m.group(1), "-i", str(work / pattern),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0 or not out.is_file():
        raise CraftError("ffmpeg could not make the video: " + p.stderr.strip()[-300:])
    say(f"Animator: {len(frames)} frame(s) at {fps} fps -> {out}")
    return out


# ------------------------------------------------------------------ Craft Anything
def craft_anything_doctor(cfg=None) -> str:
    """Craft Anything's own check of its install, agents and engines, as it says it. Reads
    only; it signs nothing in and registers nothing."""
    return run_cli("craft-anything", ["--format", "text", "doctor"], cfg, timeout=120)


REBUILD_RULES = (
    "Craft Anything builds through a coding agent signed in to YOUR account (Claude Code "
    "first); Nemo never signs in for you or sets it up. Keep it in clean room (its default): "
    "only what a visitor sees. Rebuild only what you own or may examine, and never copy "
    "another maker's logos, pictures or text.")


def open_craft_anything(cfg=None) -> Path:
    return open_app("craft-anything", cfg=cfg)


def environment_note() -> str:
    """What the four need that Nemo cannot see from here."""
    return ("FilmCraft and SoundCraft draw with DirectX 12 or Vulkan; OpenToonz with OpenGL. "
            + ("" if os.name == "nt" else "On Linux none of them is installed by Nemo yet."))
