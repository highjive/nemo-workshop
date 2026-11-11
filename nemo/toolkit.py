"""What each employee needs to do its job, and whether this machine has it
(owner, 2026-10-21: "go from department to department and make sure each
employee has the required tools to do its jobs").

Each need is a check that looks, and never installs: the installers
(NemoDoc.ps1, build-iso.sh) and the owner do that. An employee whose job is
not built yet says so, rather than reading as ready. `nemo staff` shows it.

Departments are added here one at a time, as each is gone through.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

Check = Callable[[object], tuple[bool, str]]


@dataclass(frozen=True)
class Need:
    name: str
    check: Check


@dataclass
class Row:
    employee: str            # a staff.STAFF key
    need: str
    ok: bool
    detail: str


# ------------------------------------------------------------ the checks
def model(mode: str) -> Need:
    """A mode's model on disk, and the engine that runs it."""
    def check(cfg):
        from . import modes
        if modes.engine_path(cfg) is None:
            return False, "llama-server is not installed"
        try:
            spec = cfg.mode(mode)
            return True, modes.model_path(cfg, spec["model"]).name
        except (KeyError, FileNotFoundError) as exc:
            return False, str(exc)
    return Need(f"the {mode} model", check)


def _harper(cfg):
    from . import writer
    exe = writer.harper(cfg)
    return (True, exe) if exe else (False, "Harper is not installed (NemoDoc installs it)")


def _image_engine(cfg):
    from . import artist
    try:
        t = artist.tools(cfg)
    except artist.ArtistError as exc:
        return False, str(exc)
    return True, f"{t.engine.name}, {t.model.name}" + (", TAESD" if t.taesd else "")


def _hearing(cfg):
    from . import speech
    ok, why = speech.available()
    if ok and speech.whisper() is not None:
        return True, "Whisper (small.en) on the GPU"
    return ok, "Vosk and its English model" if ok else why


def _voice(cfg):
    from . import voice
    kind, where = voice.engine()
    return (True, {"sapi": "Windows voices", "espeak": "espeak-ng"}[kind]) if kind else (False, where)


def _wikipedia(cfg):
    import socket
    try:
        socket.create_connection(("en.wikipedia.org", 443), timeout=5).close()
        return True, "Wikipedia can be reached"
    except OSError as exc:
        return False, f"Wikipedia cannot be reached now ({exc}); it needs a connection"


def _model_logs(cfg):
    from . import timekeeper
    found = timekeeper.times()
    return True, (f"timings for {', '.join(t.mode for t in found)}" if found
                  else "no timings yet: a mode must be loaded and asked")


def _place(what: str, path_of):
    """Somewhere it may write: the folder, or the nearest folder above it
    that exists, writable. Nothing is made."""
    import os
    def check(cfg):
        p = Path(path_of())
        here = next((q for q in (p, *p.parents) if q.exists()), None)
        if here is not None and os.access(here, os.W_OK):
            return True, str(p)
        return False, f"cannot write {what} in {p}"
    return Need(f"a place for {what}", check)


def _archive_home():
    from . import archivist
    return archivist._home()


def _queue_home():
    from . import foreman
    return foreman.queue_path().parent


REA_HOME = Path(r"C:\Nemo\tools\rea")         # Nemo's own copy (npm install, 2026-10-22)
REA_HOME_ISO = Path("/opt/nemo/tools/rea")    # NemoIso's (build-iso.sh, 2026-11-03)


def rea_cli() -> Path | None:
    """REA's command-line script: installed for npm, or in npx's cache. Run
    with node directly: through npx it re-checks the registry first, 79 s
    on the hotspot (2026-10-21) against 4.6 s started directly."""
    import glob
    import os
    import shutil
    # Nemo's own copy first (C:\Nemo\tools\rea, owner 2026-10-22): npx's
    # cache can be emptied at any time, which would leave REA unstartable.
    found = [home / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
             for home in (REA_HOME, REA_HOME_ISO)]
    if shutil.which("rea"):
        found.append(Path(shutil.which("rea")))
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        found.append(Path(appdata) / "npm" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs")
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        found += sorted(Path(p) for p in glob.glob(os.path.join(
            local, "npm-cache", "_npx", "*", "node_modules", "rea-agents", "scripts", "rea.mjs")))
    return next((p for p in found if p.is_file()), None)


def _tool_dir(env: str, *patterns: str) -> Path | None:
    import glob
    import os
    if os.environ.get(env) and Path(os.environ[env]).is_dir():
        return Path(os.environ[env])
    for pattern in patterns:
        hits = sorted(glob.glob(pattern))
        if hits:
            return Path(hits[-1])
    return None


def _node(cfg):
    import shutil
    node = shutil.which("node")
    return (True, node) if node else (False, "Node.js is not installed")


def _kicad_pcbnew(cfg):
    from . import pcb
    try:
        t = pcb.tools()
    except pcb.PcbError as exc:
        return False, str(exc)
    return (True, str(t.python)) if t.python.is_file() else (False, "KiCad's own Python is not there")


def _freerouting(cfg):
    from . import pcb
    try:
        t = pcb.tools()
    except pcb.PcbError as exc:
        return False, str(exc)
    if t.freerouting is None or t.java is None:
        return False, "not installed (NemoDoc fetches them into C:\\Nemo\\tools)"
    return True, f"{t.freerouting.name}, {t.java.parent.parent.name}"


def _nvidia_smi(cfg):
    from . import machine
    smi = machine._smi()
    return (True, smi) if smi else (False, "no NVIDIA driver (nvidia-smi): nothing to look at "
                                           "on a machine without an NVIDIA card")


def _godot(cfg):
    from . import gamestudio
    ok, why = gamestudio.available(cfg)
    return (True, str(gamestudio.godot(cfg))) if ok else (False, why)


def _studio_home():
    from .config import Config
    return Config.load().path("paths.studio")


def _task_file(cfg):
    p = Path(__file__).parent / "data" / "evals" / "nemo-tasks.jsonl"
    return (True, str(p)) if p.is_file() else (False, f"no task file at {p}")


def _rea(cfg):
    p = rea_cli()
    return (True, str(p)) if p else (False, "REA (rea-agents) is not installed or cached")


def _ghidra(cfg):
    d = _tool_dir("GHIDRA_INSTALL_DIR", r"C:\Nemo\tools\ghidra_*", "/opt/nemo/tools/ghidra_*")
    if d and any((d / "support" / name).is_file() for name in ("analyzeHeadless.bat", "analyzeHeadless")):
        return True, str(d)
    return False, "Ghidra is not installed (C:\\Nemo\\tools, or GHIDRA_INSTALL_DIR)"


JAVA_MAJOR = 21          # Ghidra 12's floor


def _java_version(d: Path) -> str | None:
    """JAVA_VERSION from the JDK's own `release` file; None if it has none.
    Read, not run: looking never starts a program."""
    try:
        for line in (d / "release").read_text(encoding="utf-8").splitlines():
            if line.startswith("JAVA_VERSION="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


def _java_major(version: str) -> int:
    import re
    parts = re.findall(r"\d+", version)
    if not parts:
        return 0
    return int(parts[1]) if parts[0] == "1" and len(parts) > 1 else int(parts[0])   # "1.8.0" is 8


def _java(cfg):
    # D209: any JAVA_HOME with a java binary used to pass, so a JRE 8 was
    # shown as "Java 21 ready", and it hid a JDK 21 in C:\Nemo\tools.
    # Every place is tried, and only a known version of 21 or later passes.
    import glob
    import os
    places = [Path(os.environ["JAVA_HOME"])] if os.environ.get("JAVA_HOME") else []
    for pattern in (r"C:\Nemo\tools\jdk-*", "/usr/lib/jvm/java-21-*"):
        places += [Path(p) for p in sorted(glob.glob(pattern), reverse=True)]
    seen = []
    for d in places:
        if not any((d / "bin" / name).is_file() for name in ("java.exe", "java")):
            continue
        version = _java_version(d)
        if version and _java_major(version) >= JAVA_MAJOR:
            return True, str(d)
        seen.append(f"{d} is Java {version}" if version else f"{d}: version not known")
    found = f"; found {', '.join(seen)}" if seen else ""
    return False, f"a Java {JAVA_MAJOR} JDK is not installed (C:\\Nemo\\tools, or JAVA_HOME){found}"


def _module(name: str, why: str) -> Need:
    def check(cfg):
        import importlib.util
        return ((True, f"{name} is installed") if importlib.util.find_spec(name)
                else (False, f"{name} is not installed ({why})"))
    return Need(name, check)


def _models_home():
    from .config import Config
    return Config.load().path("paths.models")


def _program(name: str, why: str) -> Need:
    def check(cfg):
        from .platform_probe import find_tool
        where = find_tool(name)
        return (True, where) if where else (False, f"{name} is not installed ({why})")
    return Need(name, check)


def _mouser_key(cfg):
    from . import research
    return ((True, "a key is set") if research.key()
            else (False, "no Mouser key: get a free one at mouser.com (My Mouser, APIs) and "
                         "enter it with the Researcher key button"))


def _mouser_reachable(cfg):
    import socket
    try:
        socket.create_connection(("api.mouser.com", 443), timeout=5).close()
        return True, "Mouser can be reached"
    except OSError as exc:
        return False, f"Mouser cannot be reached now ({exc}); it needs a connection"


def _boards(cfg):
    """A toolchain for every board in the parts library: PlatformIO fetches
    each the first time it builds for that board (nemo/offline.py)."""
    from . import offline
    from .parts import PartsLibrary
    extra = cfg.get("paths.parts")
    lib = PartsLibrary.load(*([Path(extra).expanduser()] if extra else []))
    missing = [b for b in offline.boards(lib) if not offline.board_ready(b)[0]]
    if missing:
        return False, ("no toolchain yet for " + ", ".join(missing)
                       + ": fetched once, online, by `nemo offline prepare` or a first build")
    return True, "every board in the library has built here"


def _storeroom_home():
    from .config import Config
    return Config.load().path("paths.storeroom")


def _backups_home():
    from . import backup
    return backup.default_folder()


def _catalogue(cfg):
    from . import storeroom
    try:
        items = storeroom.load(cfg.path("paths.storeroom"))
    except storeroom.StoreroomError as exc:
        return False, str(exc)
    linked = sum(1 for i in items if i.part)
    return True, f"{len(items)} item(s), {linked} linked to a library part"


def _vlc(cfg):
    from . import theatre
    p = theatre.player()
    return (True, p) if p else (False, "VLC is not installed; videos open in the system's own player")


def _chrome(cfg):
    from . import theatre
    p = theatre.browser()
    return (True, p) if p else (False, "no Chrome, Chromium or Edge to cast websites from")


def _caster(cfg):
    from . import cast
    ok, why = cast.available()
    return (True, "pychromecast is installed") if ok else (False, why)


def _picture_opener(cfg):
    import shutil
    if sys.platform.startswith("win"):
        return True, "Windows opens pictures itself"
    return ((True, shutil.which("xdg-open")) if shutil.which("xdg-open")
            else (False, "xdg-open is not installed"))


def _retroarch(cfg):
    from . import gaming
    p = gaming.retroarch(cfg)
    return (True, str(p)) if p else (False, "RetroArch is not installed (NemoDoc installs it)")


def _core(key: str) -> Need:
    def check(cfg):
        from . import gaming
        why = gaming.why_not(gaming.BY_KEY[key], cfg)
        return (False, why) if why else (True, str(gaming.core(gaming.BY_KEY[key], cfg)))
    return Need("its core", check)


def _retroarch_cfg(cfg):
    from . import gaming
    k = gaming.keys(cfg)
    return ((True, f"{len(k)} settings read, keys among them") if k
            else (False, "RetroArch's settings file was not found (it writes one on first run)"))


def _games_shelf():
    from .config import Config
    return Config.load().path("paths.storeroom") / "games"


def _engine(cfg):
    from . import modes
    p = modes.engine_path(cfg)
    return (True, p) if p else (False, "llama-server is not installed")


def _stick(cfg):
    from . import storage
    if not storage.has_stick():
        return True, "not a live stick here: work is on this computer's disk"
    said = storage.status() or ""
    return ("nothing is kept" not in said), "nemo-sync: " + said


def _clinic_home():
    from . import clinic
    return clinic.notes_path().parent


def _music_shelf():
    from .config import Config
    return Config.load().path("paths.storeroom") / "music"


def _audio_shelf():
    from .config import Config
    return Config.load().path("paths.storeroom") / "audio"


def _microphone(cfg):
    import shutil
    if sys.platform.startswith("win"):
        return True, "Windows' own recorder (MCI)"
    return ((True, shutil.which("arecord")) if shutil.which("arecord")
            else (False, "arecord is not installed (alsa-utils)"))


def _orca(cfg):
    from . import printshop
    p = printshop.orca(cfg)
    return (True, str(p)) if p else (False, "OrcaSlicer is not installed (C:\\Nemo\\tools\\OrcaSlicer)")


def _kobra3(cfg):
    from . import printshop
    p = printshop.orca(cfg)
    if not p:
        return False, "no OrcaSlicer, so no profiles"
    c = printshop.choices(p)
    return ((True, f"{len(c['process'])} qualities, {len(c['filament'])} filaments")
            if printshop.QUALITY in c["process"] and printshop.FILAMENT in c["filament"]
            else (False, "OrcaSlicer has no Kobra 3 0.4 mm profiles"))


def _ffmpeg(cfg):
    from . import filmstudio
    p = filmstudio.ffmpeg(cfg)
    return (True, str(p)) if p else (False, "ffmpeg is not installed (NemoDoc fetches it)")


def _videos_shelf():
    from .config import Config
    return Config.load().path("paths.storeroom") / "videos"


def not_built(what: str) -> Need:
    return Need("its job", lambda cfg: (False, f"not built yet: {what}"))


NEEDS: dict[str, tuple[Need, ...]] = {
    # The Library (gone through 2026-10-21)
    "library.researcher": (Need("Wikipedia", _wikipedia),),
    "library.writer": (Need("Harper (spelling)", _harper), model("talk")),
    "library.artist": (Need("the image engine", _image_engine),),
    "library.linguist": (Need("hearing", _hearing), Need("a voice", _voice)),
    "library.editor": (),                    # code only
    "library.archivist": (_place("kept answers", _archive_home),),
    "library.foreman": (_place("the queue", _queue_home),
                        model("design"), model("talk"), model("build")),
    "library.timekeeper": (Need("the model logs", _model_logs),),
    # The Art Studio (gone through 2026-10-21)
    "art_studio.writer": (_place("the models' cards", _models_home),),
    "art_studio.artist": (_module("cadquery", "concepts are drawn from its models"),
                          _module("numpy", "it renders the pictures"),
                          Need("the image engine", _image_engine)),
    "art_studio.designer": (_module("cadquery", "it builds the models"),
                            _place("models", _models_home)),
    "art_studio.editor": (_module("trimesh", "it checks the mesh"),
                          _module("rtree", "it measures the walls")),
    "art_studio.clerk": (),                   # code only: the kinds and their choices
    "art_studio.foreman": (_place("the queue", _queue_home),),
    "art_studio.timekeeper": (_place("the job times", _queue_home),),
    # The Workshop (gone through 2026-10-21)
    "workshop.reader": (_module("pypdf", "it reads the datasheets' text"), model("design")),
    "workshop.second": (model("talk"),),
    "workshop.pcb": (Need("KiCad and its pcbnew", _kicad_pcbnew), Need("Freerouting and Java 25", _freerouting)),
    "workshop.researcher": (Need("a Mouser key", _mouser_key),
                            Need("Mouser", _mouser_reachable)),
    "workshop.writer": (Need("Harper (spelling)", _harper), model("talk")),
    "workshop.designer": (model("design"), model("talk"),
                          _program("kicad-cli", "the schematic and its checks"),
                          _module("skidl", "it draws the schematic"),
                          _program("wireviz", "it draws the harness"),
                          _program("dot", "Graphviz, which WireViz draws with"),
                          _module("cadquery", "it models the case"),
                          _module("trimesh", "it checks the case"),
                          _module("rtree", "it measures the case's walls")),
    "workshop.inspector": (Need("Harper (spelling)", _harper),),
    "workshop.clerk": (),                     # code only: the Brief tab's lists
    "workshop.woodworker": (),                # code only: plans by arithmetic
    "workshop.foreman": (_place("the queue", _queue_home),
                         model("design"), model("talk")),
    "workshop.timekeeper": (Need("the model logs", _model_logs),),
    # The Computer Lab (REA added 2026-10-21; the rest when it is gone through)
    "computer_lab.writer": (),                # code only: GUIDE.md beside the firmware
    "computer_lab.designer": (not_built("printed parts: cases, brackets, mounts"),),
    "computer_lab.coder": (model("build"),
                           _program("pio", "PlatformIO, which builds the firmware"),
                           Need("board toolchains", _boards)),
    "computer_lab.tester": (_program("pio", "PlatformIO, which compiles the firmware"),
                            Need("board toolchains", _boards)),
    "computer_lab.technician": (model("design"), model("talk"), model("build")),
    "computer_lab.foreman": (not_built("the Computer Lab's own queue"),),
    "computer_lab.timekeeper": (not_built("the Computer Lab's own timings"),),
    # The Theatre (gone through 2026-10-21)
    "theatre.projectionist": (Need("VLC", _vlc), Need("casting", _caster)),
    "theatre.streamer": (Need("Chrome", _chrome),),
    "theatre.curator": (Need("a picture viewer", _picture_opener), Need("casting", _caster),
                        _module("PIL", "it shrinks pictures for the store's shelves")),
    "theatre.writer": (_place("captions", _storeroom_home),),
    # Gaming (gone through 2026-10-21)
    "gaming.attendant": (Need("RetroArch", _retroarch), _place("the games shelf", _games_shelf)),
    "gaming.nes": (_core("nes"),),
    "gaming.snes": (_core("snes"),),
    "gaming.megadrive": (_core("megadrive"),),
    "gaming.mastersystem": (_core("mastersystem"),),
    "gaming.gameboy": (_core("gameboy"),),
    "gaming.gba": (_core("gba"),),
    "gaming.atari2600": (_core("atari2600"),),
    "gaming.ps1": (_core("ps1"),),
    "gaming.writer": (Need("RetroArch's settings", _retroarch_cfg),
                      _place("note cards", _storeroom_home)),
    # The Music Room (built 2026-10-21)
    "music.player": (Need("VLC", _vlc),),
    "music.dj": (Need("casting", _caster),),
    "music.writer": (_place("playlists", _music_shelf),),
    # Audio (built 2026-10-21)
    "audio.narrator": (Need("a voice", _voice), _place("audiobooks", _audio_shelf)),
    "audio.recorder": (Need("a recorder", _microphone), _place("recordings", _audio_shelf)),
    "audio.engineer": (_place("SD-card copies", _audio_shelf),),
    "audio.librarian": (Need("VLC", _vlc), Need("casting", _caster)),
    "audio.writer": (),                       # code only: the playlists
    # The Test Bench (built 2026-10-21)
    "bench.flasher": (_program("pio", "PlatformIO, which uploads the firmware"),
                      Need("board toolchains", _boards)),
    "bench.monitor": (_module("serial", "pyserial, which PlatformIO brings"),),
    "bench.writer": (),                       # code only: logs beside the project
    # The Print Shop (built 2026-10-22)
    "printshop.slicer": (Need("OrcaSlicer", _orca), Need("the Kobra 3 profiles", _kobra3)),
    "printshop.writer": (),                   # code only: a card beside the G-code
    # The Film Studio (built 2026-10-22)
    "film.director": (),                      # code only: the plan
    "film.artist": (Need("the image engine", _image_engine),),
    "film.narrator": (Need("a voice", _voice),),
    "film.editor": (Need("ffmpeg", _ffmpeg), _place("the videos shelf", _videos_shelf)),
    "film.writer": (_module("PIL", "it draws the title and credits cards"),),
    # Home (built 2026-10-22)
    "home.surveyor": (_module("zeroconf", "it hears what devices announce; pychromecast brings it"),),
    "home.gatekeeper": (_place("the permissions", _queue_home),),
    "home.keeper": (),                         # code only: the work logs and the survey
    "home.writer": (_place("the device list", _storeroom_home),),
    # Communications (built 2026-10-22)
    "comms.browser": (Need("Chrome", _chrome),),
    "comms.postman": (_place("the address book", _storeroom_home),),
    "comms.social": (Need("Chrome", _chrome),),
    "comms.writer": (Need("Harper (spelling)", _harper),),
    # Science (built 2026-10-22)
    "science.calculator": (_module("pint", "it converts units"),),
    "science.mathematician": (_module("sympy", "it does the algebra"),),
    "science.physicist": (_module("sympy", "it solves the formula"), _module("pint", "it carries the units")),
    "science.statistician": (_module("numpy", "it counts"), _module("scipy", "it finds the trend")),
    "science.bookkeeper": (_module("openpyxl", "it reads and writes .xlsx"),),
    "science.writer": (_place("the worked sheets", _storeroom_home),),
    # The Doctors (gone through 2026-10-21)
    "doctors.gp": (),                         # code only: asks the specialists
    "doctors.machine": (),                    # code only: the machine check
    "doctors.gpu": (Need("nvidia-smi", _nvidia_smi),),
    "doctors.model": (Need("the engine", _engine),),
    "doctors.design": (),                     # code only: the projects' results
    "doctors.stick": (Need("the stick", _stick),),
    "doctors.clerk": (_place("case notes", _clinic_home),),
    "doctors.nurse": (_place("treatment copies", _clinic_home),),
    "doctors.memory": (),                     # code only: ~/.nemo/memory-check.jsonl
    "doctors.writer": (_place("reports", _clinic_home),),
    # The Game Studio (2026-11-09; the desktop's only)
    "studio.designer": (),                    # code only: reads the idea
    "studio.level": (),                       # code only: every jump checked
    "studio.programmer": (Need("Godot", _godot), _place("the games", _studio_home),
                           model("game")),
    "studio.tester": (Need("Godot", _godot),),
    "studio.writer": (_place("the games", _studio_home),),
    # The Storeroom (gone through 2026-10-21)
    "storeroom.storekeeper": (Need("the catalogue", _catalogue),
                              _place("the shelves", _storeroom_home),
                              _place("backups", _backups_home)),
    "storeroom.writer": (not_built("a label for each item"),),
    "storeroom.researcher": (Need("the catalogue", _catalogue),),   # and the parts library
    "computer_lab.quality": (Need("the task file", _task_file), Need("the engine", _engine)),
    "computer_lab.rea": (Need("Node.js", _node), Need("REA", _rea),
                         Need("Ghidra", _ghidra), Need("Java 21", _java)),
}


def check(cfg, department: str | None = None) -> list[Row]:
    """A row per need of every employee on the list (of one department)."""
    from .staff import STAFF
    rows = []
    for key, needs in NEEDS.items():
        if department and STAFF[key].department != department:
            continue
        if not needs:
            rows.append(Row(key, "nothing outside Nemo", True, "code only"))
        for n in needs:
            try:
                ok, detail = n.check(cfg)
            except Exception as exc:                            # noqa: BLE001
                ok, detail = False, f"the check failed: {exc}"
            rows.append(Row(key, n.name, ok, detail))
    return rows
