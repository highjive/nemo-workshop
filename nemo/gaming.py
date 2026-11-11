"""Gaming: retro games from the Storeroom (owner, 2026-10-21).

The owner's words: "retro emulator that can read game data in the
storehouse, each console emulator available to run on this added as a
different employee". RetroArch runs them, with one core per console (the
owner's choice); each console is an employee (nemo/staff.py, gaming.*).

Game files are the owner's own, on the Storeroom's shelf games/<console>/.
Nemo never downloads a game or a BIOS.

Where the cores come from:
  Windows  RetroArch 1.22.2 from libretro's buildbot, in C:\\Nemo\\games
           (NemoDoc.ps1 fetches it; SOURCES pins the two downloads). The
           NES core ran a homemade test cartridge on the AH531 (2026-10-21).
  NemoIso  Debian 13's retroarch and its packaged cores, from main: NES,
           SNES, Game Boy, Game Boy Advance. Mega Drive and Master System
           (Genesis Plus GX) are only in Debian's non-free section, and
           Debian packages no Atari 2600 core, so those three emulators do
           not work there yet. Debian packages no PlayStation core: the
           image builds PCSX ReARMed from a pinned tag (build-pcsx.sh) into
           the same folder. Debian's core folder: read from the 83fc78f image's
           file list (2026-11-05), /usr/lib/x86_64-linux-gnu/libretro holds
           nestopia, bsnes_mercury_performance, genesis_plus_gx, gambatte and
           mgba, as LINUX_CORE_DIRS and the core names expect; not yet run on a
           booted stick.
An emulator whose core is missing says so; it never runs another's.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import storeroom


@dataclass(frozen=True)
class Console:
    key: str                 # the staff role, gaming.<key>, and its shelf games/<key>
    name: str
    exts: tuple[str, ...]
    windows_core: str        # in RetroArch-Win64/cores/<core>_libretro.dll
    linux_core: str = ""     # Debian's <core>_libretro.so; "" where Debian has none
    linux_package: str = ""  # Debian's package for it, where its name is not
                             # libretro-<core> with hyphens (build-iso.sh installs it)
    linux_built: str = ""    # the script that builds it into the image, where
                             # Debian packages none (install/linux/<script>)

    @property
    def debian_package(self) -> str:
        """Debian's package for the core, or "" where the image builds it."""
        if self.linux_built:
            return ""
        return self.linux_package or "libretro-" + self.linux_core.replace("_", "-")


CONSOLES: tuple[Console, ...] = (
    Console("nes", "NES", (".nes",), "nestopia", "nestopia"),
    Console("snes", "SNES", (".sfc", ".smc"), "snes9x", "bsnes_mercury_performance"),
    # Genesis Plus GX is in Debian's non-free section (trixie 1.7.4+git20221128-2,
    # packages.debian.org, read 2026-10-22); the image enables non-free for it.
    Console("megadrive", "Mega Drive", (".md", ".gen", ".smd", ".bin"), "genesis_plus_gx",
            "genesis_plus_gx", "libretro-genesisplusgx"),
    Console("mastersystem", "Master System", (".sms",), "genesis_plus_gx",
            "genesis_plus_gx", "libretro-genesisplusgx"),
    Console("gameboy", "Game Boy", (".gb", ".gbc"), "gambatte", "gambatte"),
    Console("gba", "Game Boy Advance", (".gba",), "mgba", "mgba"),
    Console("atari2600", "Atari 2600", (".a26", ".bin"), "stella2014"),
    # PlayStation (owner, 2026-10-23): PCSX ReARMed, RetroPie's PS1 core. A
    # disc is a .cue (beside its .bin), .chd, .pbp or an .m3u of discs. It
    # runs without a BIOS for many games; the owner's own BIOS goes in
    # RetroArch's system folder. Debian packages no PS1 core, so NemoIso
    # builds it (build-pcsx.sh, pinned to PS1_LINUX; owner, 2026-11-06).
    Console("ps1", "PlayStation", (".cue", ".chd", ".pbp", ".m3u"), "pcsx_rearmed",
            "pcsx_rearmed", linux_built="build-pcsx.sh"),
)
BY_KEY = {c.key: c for c in CONSOLES}
ZIPPED = ".zip"              # RetroArch opens a zipped game for these cores

# The two Windows downloads, as fetched on 2026-10-21 from
RETROARCH_VERSION = "1.22.2"     # the stable folder SOURCES come from
# https://buildbot.libretro.com/stable/1.22.2/windows/x86_64/. libretro
# publishes no hashes: these pin that download rather than vouch for it.
SOURCES = {
    "RetroArch.7z": (202509078,
                     "b2139b1d0f9d4526dc6b5ce23cbb3efdc766096fa6f2c3df016818b486ac6372"),
    "RetroArch_cores.7z": (229761684,
                           "86b871e11b9b4772ac644b40a38f2c8e9449da1f355eae7da08aa061148547b0"),
}
# The PS1 core on its own, from libretro's nightly folder (re-fetched 2026-11-06;
# pinned as fetched: a newer nightly will not match, and NemoDoc says so).
PS1_CORE = ("pcsx_rearmed_libretro.dll.zip", 847073,
            "b759a011dc8f2b3190225c5accd8b34b2f9d8e0bd82f4365d29a6c783a3cc21c")
# NemoIso's PS1 core, built from source in the image (install/linux/build-pcsx.sh
# holds the same two; a test keeps them together): libretro/pcsx_rearmed, GPL-2.0,
# tag r26l of 2026-03-29. Built and run on Debian 13 in WSL, 2026-11-06.
PS1_LINUX = ("r26l", "9f8b6f248e073f03c530efda7c4cc60a7e2ecafc")
LINUX_CORE_DIRS = ("/usr/lib/x86_64-linux-gnu/libretro", "/usr/lib/libretro")


@dataclass
class Game:
    name: str
    path: Path
    console: Console


def retroarch(cfg=None) -> Path | None:
    """RetroArch: the configured file, Nemo's own copy, or the system's."""
    found = []
    if cfg is not None and cfg.get("paths.retroarch"):
        found.append(Path(str(cfg.get("paths.retroarch"))).expanduser())
    if cfg is not None and cfg.get("paths.llama_server"):
        engine = Path(str(cfg.get("paths.llama_server"))).expanduser()
        found.append(engine.parent.parent / "games" / "RetroArch-Win64" / "retroarch.exe")
    found.append(Path(r"C:\Nemo\games\RetroArch-Win64\retroarch.exe"))
    which = shutil.which("retroarch")
    if which:
        found.append(Path(which))
    return next((p for p in found if p.is_file()), None)


def core(console: Console, cfg=None) -> Path | None:
    """This console's core on this machine, or None."""
    if sys.platform.startswith("win"):
        ra = retroarch(cfg)
        p = ra.parent / "cores" / f"{console.windows_core}_libretro.dll" if ra else None
        return p if p and p.is_file() else None
    if not console.linux_core:
        return None
    for d in LINUX_CORE_DIRS + (str(Path("~/.config/retroarch/cores").expanduser()),):
        p = Path(d) / f"{console.linux_core}_libretro.so"
        if p.is_file():
            return p
    return None


def why_not(console: Console, cfg=None) -> str:
    """Why this emulator cannot play here, or "" if it can."""
    if retroarch(cfg) is None:
        return ("RetroArch is not installed (NemoDoc installs it on Windows; NemoIso's "
                "next image has it)")
    if core(console, cfg) is None:
        if not sys.platform.startswith("win") and not console.linux_core:
            return f"Debian has no {console.name} core, so it does not play here yet"
        return f"the {console.name} core is not installed"
    return ""


def shelf(cfg, console: Console) -> Path:
    return storeroom.shelf(cfg.path("paths.storeroom"), f"games/{console.key}")


def make_shelves(cfg) -> list[Path]:
    return storeroom.make_shelves(cfg.path("paths.storeroom"),
                                  tuple(f"games/{c.key}" for c in CONSOLES))


def games(cfg) -> list[Game]:
    """Every game on the shelves. A file is on its console's shelf, so a
    .bin on the Mega Drive shelf is a Mega Drive game, not an Atari one."""
    out = []
    for c in CONSOLES:
        folder = shelf(cfg, c)
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if p.is_file() and p.suffix.lower() in c.exts + (ZIPPED,):
                out.append(Game(p.stem, p, c))
    return out


# --------------------------------------------------------------------
#  Which console a game file is for, from its own header (the Attendant,
#  owner 2026-10-22). Each console's files carry a mark of their own; the
#  Atari 2600's carry none, and a zipped game is not opened, so neither is
#  checked. A file on the wrong shelf is said, not moved or refused.
# --------------------------------------------------------------------
_GB_LOGO = bytes.fromhex("CEED6666CC0D000B")         # Nintendo's logo, at 0x104
_GBA_LOGO = bytes.fromhex("24FFAE51699AA221")        # at 0x04; 0x96 at 0xB2


def _snes(data: bytes, size: int) -> bool:
    """An internal header whose checksum and its complement make FFFF, at
    0x7FC0 (LoROM) or 0xFFC0 (HiROM), after a copier's 512 bytes if any.
    Whether there is one is told by the FILE's size, not what was read."""
    skip = 512 if size % 1024 == 512 else 0
    for at in (0x7FC0, 0xFFC0):
        h = skip + at
        if len(data) >= h + 0x20:
            comp = int.from_bytes(data[h + 0x1C:h + 0x1E], "little")
            check = int.from_bytes(data[h + 0x1E:h + 0x20], "little")
            if comp ^ check == 0xFFFF and check not in (0, 0xFFFF):
                return True
    return False


def identify(path: Path) -> str | None:
    """The console key a game file's header says, "" when it says none,
    or None when it is not looked at (a zip; an Atari-only extension)."""
    path = Path(path)
    if path.suffix.lower() in (ZIPPED, ".a26"):
        return None
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            data = f.read(0x10200)
    except OSError:
        return None
    if data[:4] == b"NES\x1a":
        return "nes"
    if data[0x104:0x10C] == _GB_LOGO:
        return "gameboy"
    if data[0x04:0x0C] == _GBA_LOGO and len(data) > 0xB2 and data[0xB2] == 0x96:
        return "gba"
    if b"SEGA" in data[0x100:0x110]:
        return "megadrive"
    if any(data[at:at + 8] == b"TMR SEGA" for at in (0x7FF0, 0x3FF0, 0x1FF0)):
        return "mastersystem"
    if _snes(data, size):
        return "snes"
    return ""


def shelf_check(game: Game) -> str:
    """The Attendant's word on a game on its shelf: "" when all is well."""
    found = identify(game.path)
    if found is None or found == game.console.key:
        return ""
    if found:
        return (f"{game.path.name} looks like a {BY_KEY[found].name} game, but it is on the "
                f"{game.console.name} shelf: move it to games/{found} to play it")
    if game.console.key in ("atari2600", "ps1"):
        return ""                                    # no mark read: a 2600 has none, a disc is not read
    if game.console.key == "megadrive" and game.path.suffix.lower() == ".smd":
        return ""                                    # an .smd file is interleaved: not read
    return (f"{game.path.name} has no {game.console.name} header: it may not be a "
            f"{game.console.name} game, or not a game at all")


def find(found: list[Game], name: str) -> Game | None:
    n = name.strip().lower()
    return (next((g for g in found if g.name.lower() == n), None)
            or next((g for g in found if g.path.name.lower() == n), None))


# --------------------------------------------------------------------
#  Game saves in the Storeroom (owner, 2026-10-22). RetroArch kept them in
#  its own folder (RetroArch-Win64/saves and states), so no backup and no
#  stick held them, and a reinstall of RetroArch lost them. Nemo now starts
#  RetroArch with one more settings file of its own (--appendconfig), which
#  puts them in <storeroom>/game-saves: small files, kept by backups (only
#  the games themselves are left out) and by nemo-sync. RetroArch's own
#  settings file is never changed.
# --------------------------------------------------------------------

def saves_home(cfg) -> Path:
    return cfg.path("paths.storeroom") / "game-saves"


def _old_saves(cfg) -> list[Path]:
    """Where RetroArch kept saves before: beside it on Windows, its own
    folder on Linux."""
    ra = retroarch(cfg)
    homes = [ra.parent] if ra is not None and sys.platform.startswith("win") else []
    homes.append(Path("~/.config/retroarch").expanduser())
    return [h / d for h in homes for d in ("saves", "states")]


def adopt_old_saves(cfg) -> int:
    """Copy saves made before into the Storeroom, never over one already
    there. The originals stay where they are. Returns how many were copied."""
    n = 0
    for old in _old_saves(cfg):
        if not old.is_dir():
            continue
        new = saves_home(cfg) / old.name
        for f in old.rglob("*"):
            target = new / f.relative_to(old)
            if f.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                n += 1
    return n


def nemo_settings(cfg) -> Path:
    """Nemo's own few RetroArch settings, written each time a game starts."""
    from .config import CONFIG_HOME
    home = saves_home(cfg)
    for d in ("saves", "states"):
        (home / d).mkdir(parents=True, exist_ok=True)
    p = CONFIG_HOME / "retroarch-nemo.cfg"
    p.parent.mkdir(parents=True, exist_ok=True)
    # config_save_on_exit off: RetroArch otherwise writes these settings into
    # its own retroarch.cfg when it closes. Found on the AH531 (2026-10-22):
    # one test run changed the owner's two save lines; they were put back.
    p.write_text("# Written by Nemo (nemo/gaming.py) each time a game starts.\n"
                 f'savefile_directory = "{home / "saves"}"\n'
                 f'savestate_directory = "{home / "states"}"\n'
                 'config_save_on_exit = "false"\n', encoding="utf-8")
    return p


def argv(game: Game, cfg=None, fullscreen: bool = True) -> list[str]:
    """The command that plays it; raises RuntimeError saying why it cannot.
    With cfg, the saves go to the Storeroom (nemo_settings)."""
    why = why_not(game.console, cfg)
    if why:
        raise RuntimeError(why)
    return ([str(retroarch(cfg)), "-L", str(core(game.console, cfg)), str(game.path)]
            + (["--appendconfig", str(nemo_settings(cfg))] if cfg is not None else [])
            + (["--fullscreen"] if fullscreen else []))


def play(game: Game, cfg=None, fullscreen: bool = True) -> subprocess.Popen:
    """Hand the game to its console's emulator. Esc quits RetroArch. The
    Writer notes when (gaming.played)."""
    if cfg is not None:
        try:
            adopt_old_saves(cfg)
        except OSError:
            pass                     # an old save that cannot be copied stays where it is
    proc = subprocess.Popen(argv(game, cfg, fullscreen))
    if cfg is not None:
        try:
            played(cfg, game)
        except OSError:
            pass                     # a note must never stop a game
    return proc


# ------------------------------------------------------------ the Writer
# Note cards (owner's choice, 2026-10-21): each game's controls, when it was
# last played, and the owner's own notes, in the Storeroom's game-notes.json
# (the games shelf is left out of backups; this file is not).
PAD = ("up", "down", "left", "right", "a", "b", "x", "y", "l", "r", "start", "select")
HOTKEYS = (("menu_toggle", "RetroArch's menu"), ("save_state", "save your place"),
           ("load_state", "go back to it"), ("hold_fast_forward", "fast forward, held"),
           ("toggle_fullscreen", "full screen on or off"), ("exit_emulator", "quit"))
# Which of RetroArch's pad buttons each console has. NES, SNES, Game Boy and
# GBA are the pad's own names; for the Sega and Atari consoles the core maps
# its buttons onto the pad in a way not checked here.
BUTTONS = {"nes": ("a", "b", "start", "select"),
           "snes": ("a", "b", "x", "y", "l", "r", "start", "select"),
           "gameboy": ("a", "b", "start", "select"),
           "gba": ("a", "b", "l", "r", "start", "select")}


def _notes_path(cfg) -> Path:
    return cfg.path("paths.storeroom") / "game-notes.json"


def _key(game: Game) -> str:
    return f"{game.console.key}/{game.path.name}"


def notes(cfg) -> dict:
    import json
    try:
        return json.loads(_notes_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_notes(cfg, data: dict) -> None:
    import json
    p = _notes_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def played(cfg, game: Game) -> None:
    import time
    data = notes(cfg)
    rec = data.setdefault(_key(game), {})
    rec["played"] = int(time.time())
    rec["plays"] = rec.get("plays", 0) + 1
    _save_notes(cfg, data)


def write_note(cfg, game: Game, text: str) -> None:
    data = notes(cfg)
    data.setdefault(_key(game), {})["notes"] = text.strip()
    _save_notes(cfg, data)


def keys(cfg=None) -> dict[str, str]:
    """RetroArch's keys, from its own settings file where there is one; its
    names (x, z, rshift...) as written there."""
    ra = retroarch(cfg)
    out = {}
    for f in ([ra.parent / "retroarch.cfg"] if ra else []) + [
            Path("~/.config/retroarch/retroarch.cfg").expanduser()]:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if "=" in line:
                k, v = (x.strip() for x in line.split("=", 1))
                out[k] = v.strip('"')
        break
    return out


def card(cfg, game: Game) -> str:
    """The note card, in words."""
    import datetime as dt
    k = keys(cfg)
    rec = notes(cfg).get(_key(game), {})
    lines = [f"{game.name} ({game.console.name})", ""]
    if rec.get("played"):
        lines.append(f"Last played {dt.datetime.fromtimestamp(rec['played']):%d %b %Y %H:%M}, "
                     f"{rec.get('plays', 1)} time(s).")
    else:
        lines.append("Not played from Nemo yet.")
    lines += ["", "Controls (RetroArch's own settings on this computer):"]
    if not k:
        lines.append("  RetroArch's settings file was not found, so its keys are not known here.")
    else:
        wanted = BUTTONS.get(game.console.key)
        pad = [b for b in PAD if b in ("up", "down", "left", "right") or not wanted or b in wanted]
        for b in pad:
            v = k.get(f"input_player1_{b}")
            if v:
                lines.append(f"  {b.capitalize():<7} {v}")
        if not wanted:
            lines.append("  (how this console's buttons sit on the pad is the core's, not checked)")
        for h, what in HOTKEYS:
            v = k.get(f"input_{h}")
            if v and v != "nul":
                lines.append(f"  {v:<7} {what}")
        if k.get("quit_press_twice") == "true":
            lines.append("  (quit: press it twice)")
    lines += ["", "Notes:", rec.get("notes") or "  none yet"]
    return "\n".join(lines)
