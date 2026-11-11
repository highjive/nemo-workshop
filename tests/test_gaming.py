"""Gaming (owner, 2026-10-21): the games shelf, and each console's emulator.

No game is downloaded, here or anywhere: where a real emulator is run, it
runs a homemade test cartridge made below (a header, a loop, no picture).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import backup, gaming, staff


def test_cartridge() -> bytes:
    """A homemade NES cartridge: one 16 KB program bank that jumps to itself
    for ever, one empty 8 KB picture bank. Nobody's game."""
    prg = bytearray(16384)
    prg[0:3] = bytes([0x4C, 0x00, 0xC0])                     # JMP $C000
    prg[0x3FFA:0x4000] = bytes([0x00, 0xC0] * 3)             # NMI, RESET, IRQ
    return b"NES\x1a" + bytes([1, 1, 0, 0]) + bytes(8) + bytes(prg) + bytes(8192)


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.home))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        gaming.make_shelves(self.cfg)

    def tearDown(self):
        self._env.stop(); self.t.cleanup()

    def put(self, console: str, name: str, data: bytes = b"x") -> Path:
        p = self.home / "nemo-storeroom" / "games" / console / name
        p.write_bytes(data)
        return p


class TestTheShelf(AHome):
    def test_a_shelf_for_every_console(self):
        for c in gaming.CONSOLES:
            self.assertTrue(gaming.shelf(self.cfg, c).is_dir(), c.key)

    def test_a_game_is_its_shelf_s(self):
        self.put("megadrive", "Racer.bin")
        self.put("atari2600", "Paddles.bin")
        self.put("nes", "Cart.zip")
        self.put("nes", "readme.txt")
        self.put("snes", "Wrong.nes")                 # an NES file on the SNES shelf
        found = {(g.console.key, g.name) for g in gaming.games(self.cfg)}
        self.assertEqual(found, {("megadrive", "Racer"), ("atari2600", "Paddles"),
                                 ("nes", "Cart")})
        self.assertEqual(gaming.find(gaming.games(self.cfg), "racer").console.name, "Mega Drive")


class TestTheEmulators(AHome):
    def test_each_console_is_an_employee(self):
        self.assertEqual({e.key.split(".")[1] for e in staff.team("gaming")} - {"attendant", "writer"},
                         {c.key for c in gaming.CONSOLES})
        for c in gaming.CONSOLES:
            self.assertEqual(staff.STAFF[f"gaming.{c.key}"].title, f"{c.name} Emulator")

    def test_no_retroarch_says_so(self):
        with mock.patch.object(gaming, "retroarch", return_value=None):
            self.assertIn("RetroArch is not installed", gaming.why_not(gaming.BY_KEY["nes"]))
            with self.assertRaises(RuntimeError):
                gaming.argv(gaming.Game("x", Path("x.nes"), gaming.BY_KEY["nes"]))

    def test_on_nemoiso_only_the_atari_has_no_core(self):
        # Mega Drive and Master System gained Debian's non-free Genesis Plus
        # GX on 2026-10-22; Debian packages no Atari 2600 core.
        with mock.patch.object(gaming.sys, "platform", "linux"), \
             mock.patch.object(gaming, "retroarch", return_value=Path("/usr/bin/retroarch")):
            self.assertIn("Debian has no Atari 2600 core",
                          gaming.why_not(gaming.BY_KEY["atari2600"]))
            for key in ("megadrive", "mastersystem", "nes", "ps1"):
                self.assertIn("core is not installed", gaming.why_not(gaming.BY_KEY[key]))

    def test_on_nemoiso_the_playstation_finds_the_core_the_image_built(self):
        # 2026-11-06: the ps1 console had no Linux core, so NemoIso's
        # PlayStation said "Debian has no core" even with one built.
        cores = self.home / "libretro"; cores.mkdir()
        (cores / "pcsx_rearmed_libretro.so").write_bytes(b"\x7fELF")
        with mock.patch.object(gaming.sys, "platform", "linux"),              mock.patch.object(gaming, "LINUX_CORE_DIRS", (str(cores),)),              mock.patch.object(gaming, "retroarch", return_value=Path("/usr/bin/retroarch")):
            self.assertEqual(gaming.core(gaming.BY_KEY["ps1"]), cores / "pcsx_rearmed_libretro.so")
            self.assertEqual(gaming.why_not(gaming.BY_KEY["ps1"]), "")

    def test_the_command_it_runs(self):
        g = gaming.Game("Cart", self.put("nes", "Cart.nes"), gaming.BY_KEY["nes"])
        with mock.patch.object(gaming, "retroarch", return_value=Path("ra.exe")), \
             mock.patch.object(gaming, "core", return_value=Path("nestopia.dll")):
            self.assertEqual(gaming.argv(g), ["ra.exe", "-L", "nestopia.dll", str(g.path),
                                              "--fullscreen"])
            self.assertNotIn("--fullscreen", gaming.argv(g, fullscreen=False))

    def test_backups_leave_games_and_videos_out(self):
        self.put("nes", "Cart.nes")
        (self.home / "nemo-storeroom" / "videos").mkdir(exist_ok=True)
        (self.home / "nemo-storeroom" / "videos" / "Film.mp4").write_bytes(b"v")
        (self.home / "nemo-storeroom" / "pictures").mkdir(exist_ok=True)
        (self.home / "nemo-storeroom" / "pictures" / "Beach.jpg").write_bytes(b"p")
        with mock.patch("nemo.config.CONFIG_HOME", self.home / ".nemo"):
            made = backup.make(self.cfg, self.home / "backups")
        import zipfile
        names = zipfile.ZipFile(made.path).namelist()
        self.assertIn("storeroom/pictures/Beach.jpg", names)
        self.assertFalse([n for n in names if "/games/" in n or "/videos/" in n])


class TestTheInstallersAgree(unittest.TestCase):
    """NemoDoc.ps1 fetches what gaming.py pins, and keeps the cores it uses;
    the image's script installs Debian's cores gaming.py looks for."""

    def test_nemodoc(self):
        text = (Path(__file__).resolve().parent.parent / "NemoDoc.ps1").read_text(encoding="utf-8")
        for name, (size, sha) in gaming.SOURCES.items():
            self.assertIn(f'file = "{name}"; sha256 = "{sha}"; bytes = {size}', text)
        for core in {c.windows_core for c in gaming.CONSOLES}:
            self.assertIn(f'"{core}"', text)
        name, size, sha = gaming.PS1_CORE
        self.assertIn(f'file = "{name}"; sha256 = "{sha}"; bytes = {size}', text)

    def test_the_image(self):
        text = (Path(__file__).resolve().parent.parent / "install" / "live-build"
                / "build-iso.sh").read_text(encoding="utf-8")
        for pkg in {c.debian_package for c in gaming.CONSOLES if c.linux_core} - {""}:
            self.assertIn(pkg, text)
        self.assertIn("libretro-genesisplusgx", text)       # Mega Drive, Master System
        self.assertIn("trixie main contrib non-free non-free-firmware", text)


@unittest.skipUnless(sys.platform.startswith("win") and gaming.retroarch(),
                     "RetroArch is not installed here")
class TestThePlayStationIsBuilt(unittest.TestCase):
    """Debian packages no PS1 core: the image builds PCSX ReARMed from the
    tag and commit gaming.PS1_LINUX pins (owner, 2026-11-06)."""

    def setUp(self):
        root = Path(__file__).resolve().parent.parent / "install"
        self.script = (root / "linux" / "build-pcsx.sh").read_text(encoding="utf-8")
        self.iso = (root / "live-build" / "build-iso.sh").read_text(encoding="utf-8")

    def test_the_script_builds_the_pinned_commit(self):
        tag, commit = gaming.PS1_LINUX
        self.assertIn(f'TAG="{tag}"', self.script)
        self.assertIn(f'COMMIT="{commit}"', self.script)
        self.assertIn('if [ "$got" != "$COMMIT" ]', self.script)   # a moved tag stops it
        make = [l for l in self.script.splitlines() if l.startswith("make ")]
        self.assertEqual(len(make), 1)
        self.assertNotIn("-march", make[0])                        # nothing newer than SSE4.2
        self.assertNotIn("CFLAGS", make[0])
        self.assertIn(f'CORE_DIR="{gaming.LINUX_CORE_DIRS[0]}"', self.script)
        self.assertNotIn("\r", self.script)

    def test_the_image_runs_it_where_gaming_looks(self):
        ps1 = gaming.BY_KEY["ps1"]
        self.assertEqual(ps1.linux_built, "build-pcsx.sh")
        self.assertEqual(ps1.debian_package, "")
        copied = self.iso[self.iso.index("for f in nemodoc"):].splitlines()[0]
        self.assertIn("build-pcsx.sh", copied)
        self.assertIn("/opt/nemo/app/build-pcsx.sh", self.iso)
        self.assertIn(f"{gaming.LINUX_CORE_DIRS[0]}/{ps1.linux_core}_libretro.so", self.iso)
        # After the desktop's compilers, before the manifest of Nemo's files.
        self.assertLess(self.iso.index("build-essential cmake"), self.iso.index("app/build-pcsx.sh"))
        self.assertLess(self.iso.index("app/build-pcsx.sh"), self.iso.index("manifest.sha256"))
        self.assertNotIn("libretro-pcsx", self.iso)


class TestARealEmulator(AHome):
    def test_the_nes_emulator_runs_the_test_cartridge(self):
        g = gaming.Game("test", self.put("nes", "test.nes", test_cartridge()),
                        gaming.BY_KEY["nes"])
        log = self.home / "ra.log"
        own = gaming.retroarch().parent / "retroarch.cfg"
        before = own.read_bytes() if own.is_file() else None
        argv = gaming.argv(g, self.cfg, fullscreen=False) + ["--max-frames=60", "--verbose",
                                                             "--log-file", str(log)]
        p = subprocess.run(argv, timeout=120)
        text = log.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(p.returncode, 0, text[-800:])
        self.assertIn("Geometry: 256x224", text)          # the core ran the cartridge
        # Its saves go to the Storeroom, and RetroArch's own settings file is
        # left as it was: without config_save_on_exit off, one run wrote
        # Nemo's save folders into it (2026-10-22).
        self.assertIn(str(gaming.saves_home(self.cfg) / "saves"), text)
        if before is not None:
            self.assertEqual(own.read_bytes(), before)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_it_lists_and_plays(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.put("gba", "Puzzle.gba")
        app = A.NemoApp(); app.update()
        try:
            w = A.Gaming(app); app.update()
            self.assertEqual(w.tree.item("0", "values"), ("Game Boy Advance", "Puzzle"))
            self.assertIsNone(w.play())                       # nothing chosen
            w.tree.selection_set("0")
            with mock.patch.object(gaming, "play") as play:
                w.play()
            self.assertEqual(play.call_args[0][0].name, "Puzzle")
            self.assertIn("is playing Puzzle", w.note.cget("text"))
            with mock.patch.object(gaming, "play", side_effect=RuntimeError("the core is gone")):
                w.play()
            self.assertIn("the core is gone", w.note.cget("text"))
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
