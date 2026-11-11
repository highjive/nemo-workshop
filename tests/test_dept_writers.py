"""The Writers of Gaming and the Theatre (owner, 2026-10-21): note cards for
games, titles and lines for videos and pictures.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import gaming, staff, theatre, videostore

CFG = """input_player1_a = "x"
input_player1_b = "z"
input_player1_start = "enter"
input_player1_select = "rshift"
input_player1_up = "up"
input_player1_l = "q"
input_menu_toggle = "f1"
input_exit_emulator = "escape"
input_save_state = "nul"
quit_press_twice = "true"
"""


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        ra = self.t / "RetroArch-Win64" / "retroarch.exe"
        ra.parent.mkdir(parents=True); ra.write_bytes(b"x")
        (ra.parent / "retroarch.cfg").write_text(CFG, encoding="utf-8")
        self._ra = mock.patch.object(gaming, "retroarch", return_value=ra)
        self._ra.start()

    def tearDown(self):
        self._ra.stop(); self._env.stop()
        shutil.rmtree(self.t, ignore_errors=True)


class TestGamingWriter(AHome):
    def game(self, console="nes"):
        p = self.t / "nemo-storeroom" / "games" / console / "Cart.nes"
        p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
        return gaming.Game("Cart", p, gaming.BY_KEY[console])

    def test_the_card_shows_retroarch_s_own_keys(self):
        text = gaming.card(self.cfg, self.game())
        self.assertIn("A       x", text)
        self.assertIn("Select  rshift", text)
        self.assertNotIn("L       q", text)                    # an NES has no L
        self.assertIn("f1      RetroArch's menu", text)
        self.assertNotIn("save your place", text)              # "nul": no key
        self.assertIn("(quit: press it twice)", text)
        self.assertIn("Not played from Nemo yet.", text)
        self.assertIn("not checked", gaming.card(self.cfg, self.game("megadrive")))

    def test_played_and_notes_are_kept(self):
        g = self.game()
        with mock.patch.object(gaming.subprocess, "Popen"), \
             mock.patch.object(gaming, "core", return_value=Path("core.dll")):
            gaming.play(g, self.cfg); gaming.play(g, self.cfg)
        gaming.write_note(self.cfg, g, "  World 1-2, the pipe on the left  ")
        text = gaming.card(self.cfg, g)
        self.assertIn("2 time(s)", text)
        self.assertIn("World 1-2, the pipe on the left", text)
        self.assertTrue((self.t / "nemo-storeroom" / "game-notes.json").is_file())

    def test_no_settings_file_says_so(self):
        (self.t / "RetroArch-Win64" / "retroarch.cfg").unlink()
        with mock.patch("pathlib.Path.expanduser", return_value=self.t / "none.cfg"):
            self.assertIn("not found", gaming.card(self.cfg, self.game()))


class TestTheatreWriter(AHome):
    def item(self, rel="videos/holiday_film-2024.mp4"):
        p = self.t / "nemo-storeroom" / rel
        p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
        return theatre.Item(p.name, p, "video", "Storeroom")

    def test_a_title_from_the_name_until_one_is_written(self):
        it = self.item()
        self.assertEqual(theatre.caption(self.cfg, it), ("holiday film 2024", ""))
        theatre.write_caption(self.cfg, it, "Cornwall, 2024", "The week it rained.")
        self.assertEqual(theatre.caption(self.cfg, it), ("Cornwall, 2024", "The week it rained."))
        self.assertEqual(videostore.shelves(self.cfg)["VIDEOS"][0].title, "Cornwall, 2024")
        theatre.write_caption(self.cfg, it, "", "")
        self.assertEqual(theatre.caption(self.cfg, it)[0], "holiday film 2024")

    def test_both_writers_work(self):
        for key in ("gaming.writer", "theatre.writer", "doctors.writer"):
            self.assertTrue(staff.STAFF[key].working, key)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindows(AHome):
    def test_note_card_and_caption(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        TestGamingWriter.game(self)
        TestTheatreWriter.item(self)
        app = A.NemoApp(); app.update()
        try:
            g = A.Gaming(app); app.update()
            g.tree.selection_set("0")
            card = g.note_card(); app.update()
            card.mine.insert("1.0", "boss at the end")
            card.save()
            self.assertIn("boss at the end", gaming.card(self.cfg, g.games[0]))
            g.destroy()
            t = A.Theatre(app); app.update()
            t.tree.selection_set("0")
            answers = iter(["Cornwall", "Rain all week"])
            self.assertEqual(t.write_caption(ask=lambda *a: next(answers)), "Cornwall")
            self.assertIn("Cornwall: Rain all week", t.note.cget("text"))
            t.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
