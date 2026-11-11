"""Gaming, second pass (owner, 2026-10-22): game saves kept in the
Storeroom, and the Attendant reading which console a game file is for.
The headers here are built by hand; no game is downloaded or included.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import backup, gaming
from test_gaming import test_cartridge


def at(size: int, *marks: tuple[int, bytes]) -> bytes:
    data = bytearray(size)
    for where, what in marks:
        data[where:where + len(what)] = what
    return bytes(data)


def snes(size=0x80000, at_=0x7FC0, copier=False) -> bytes:
    data = bytearray(size)
    data[at_ + 0x1C:at_ + 0x20] = (0x1234 ^ 0xFFFF).to_bytes(2, "little") + (0x1234).to_bytes(2, "little")
    return (bytes(512) if copier else b"") + bytes(data)


HEADERS = {
    "nes": test_cartridge(),
    "gameboy": at(0x8000, (0x104, bytes.fromhex("CEED6666CC0D000B"))),
    "gba": at(0x1000, (0x04, bytes.fromhex("24FFAE51699AA221")), (0xB2, b"\x96")),
    "megadrive": at(0x2000, (0x100, b"SEGA MEGA DRIVE ")),
    "mastersystem": at(0x8000, (0x7FF0, b"TMR SEGA")),
    "snes": snes(),
}


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.home))
        self._env.start()
        self._cfg_home = mock.patch("nemo.config.CONFIG_HOME", self.home / ".nemo")
        self._cfg_home.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        gaming.make_shelves(self.cfg)

    def tearDown(self):
        self._cfg_home.stop(); self._env.stop()
        self.t.cleanup()

    def put(self, console: str, name: str, data: bytes) -> gaming.Game:
        p = gaming.shelf(self.cfg, gaming.BY_KEY[console]) / name
        p.write_bytes(data)
        return gaming.Game(p.stem, p, gaming.BY_KEY[console])


class TestWhichConsole(AHome):
    def test_each_header_is_read(self):
        for key, data in HEADERS.items():
            g = self.put(key, f"x.{gaming.BY_KEY[key].exts[0][1:]}", data)
            self.assertEqual(gaming.identify(g.path), key, key)
            self.assertEqual(gaming.shelf_check(g), "", key)

    def test_a_snes_file_with_a_copier_header_or_hirom(self):
        self.assertEqual(gaming.identify(self.put("snes", "a.smc", snes(copier=True)).path), "snes")
        self.assertEqual(gaming.identify(self.put("snes", "b.sfc", snes(at_=0xFFC0)).path), "snes")

    def test_a_game_on_the_wrong_shelf_is_said(self):
        g = self.put("nes", "Tetris.nes", HEADERS["gameboy"])
        self.assertIn("looks like a Game Boy game, but it is on the NES shelf", gaming.shelf_check(g))
        self.assertIn("games/gameboy", gaming.shelf_check(g))

    def test_not_a_game(self):
        g = self.put("gba", "notes.gba", b"just some text, not a cartridge" * 20)
        self.assertIn("has no Game Boy Advance header", gaming.shelf_check(g))

    def test_what_is_not_read_is_not_judged(self):
        self.assertEqual(gaming.shelf_check(self.put("atari2600", "Pong.a26", bytes(4096))), "")
        self.assertEqual(gaming.shelf_check(self.put("atari2600", "Pong.bin", bytes(4096))), "")
        self.assertEqual(gaming.shelf_check(self.put("megadrive", "Game.smd", bytes(4096))), "")
        self.assertIsNone(gaming.identify(self.put("nes", "Game.zip", b"PK\x03\x04").path))


class TestTheSaves(AHome):
    def test_retroarch_is_told_to_keep_them_in_the_storeroom(self):
        g = self.put("nes", "Cart.nes", HEADERS["nes"])
        with mock.patch.object(gaming, "retroarch", return_value=Path("ra.exe")), \
             mock.patch.object(gaming, "core", return_value=Path("nestopia.dll")):
            argv = gaming.argv(g, self.cfg)
        extra = Path(argv[argv.index("--appendconfig") + 1])
        text = extra.read_text(encoding="utf-8")
        self.assertIn(f'savefile_directory = "{gaming.saves_home(self.cfg) / "saves"}"', text)
        self.assertIn(f'savestate_directory = "{gaming.saves_home(self.cfg) / "states"}"', text)
        # RetroArch writes appended settings into its own file on exit
        # unless told not to (found on the AH531, 2026-10-22).
        self.assertIn('config_save_on_exit = "false"', text)
        self.assertEqual(gaming.saves_home(self.cfg),
                         self.cfg.path("paths.storeroom") / "game-saves")

    def test_old_saves_are_copied_never_over_new_ones(self):
        old = self.home / "ra" / "saves" / "Nestopia"
        old.mkdir(parents=True)
        (old / "Cart.srm").write_bytes(b"old progress")
        (old / "Other.srm").write_bytes(b"other")
        new = gaming.saves_home(self.cfg) / "saves" / "Nestopia"
        new.mkdir(parents=True)
        (new / "Cart.srm").write_bytes(b"newer progress")
        with mock.patch.object(gaming, "_old_saves", return_value=[self.home / "ra" / "saves"]):
            self.assertEqual(gaming.adopt_old_saves(self.cfg), 1)
        self.assertEqual((new / "Cart.srm").read_bytes(), b"newer progress")
        self.assertEqual((new / "Other.srm").read_bytes(), b"other")
        self.assertTrue((old / "Cart.srm").is_file())                 # copied, not moved

    def test_backups_keep_the_saves_not_the_games(self):
        self.put("nes", "Cart.nes", HEADERS["nes"])
        s = gaming.saves_home(self.cfg) / "saves" / "Nestopia"
        s.mkdir(parents=True)
        (s / "Cart.srm").write_bytes(b"progress")
        made = backup.make(self.cfg, self.home / "backups")
        import zipfile
        names = zipfile.ZipFile(made.path).namelist()
        self.assertTrue(any(n.endswith("game-saves/saves/Nestopia/Cart.srm") for n in names), names)
        self.assertFalse(any(n.endswith("Cart.nes") for n in names))


if __name__ == "__main__":
    unittest.main()
