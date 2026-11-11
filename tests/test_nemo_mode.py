"""Nemo Mode (owner, 2026-11-04: "use bazzite as reference for nemo
departments interface"): the departments as a full-screen shelf, worked
from the keyboard, the desktop one key away."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import


@unittest.skipUnless(_sandbox.has_display(), "needs a display")
class TestNemoMode(unittest.TestCase):
    def setUp(self):
        try:
            from nemo.gui import app as A
            from nemo.gui import nemomode as M
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A, self.M = A, M
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name))
        env.start(); self.addCleanup(env.stop)
        self.app = A.NemoApp(); self.app.update()
        self.addCleanup(self.app.destroy)
        self.mode = M.NemoMode(self.app, fullscreen=False); self.app.update()

    def test_every_department_is_on_the_shelf_in_roster_order(self):
        from nemo.staff import DEPARTMENTS
        self.assertEqual(self.mode.keys, list(DEPARTMENTS))

    def test_the_keys_move_along_the_shelf_and_stop_at_its_ends(self):
        m = self.mode
        m.event_generate("<Right>"); m.event_generate("<Right>"); self.app.update()
        self.assertEqual(m.at, 2)
        m.choose(-5); self.assertEqual(m.at, 0)
        m.choose(99); self.assertEqual(m.at, len(m.keys) - 1)

    def test_it_remembers_where_it_was(self):
        self.mode.choose(5)
        again = self.M.NemoMode(self.app, fullscreen=False); self.app.update()
        self.assertEqual(again.keys[again.at], self.mode.keys[5])
        again.destroy()

    def test_enter_goes_into_the_room_and_home_comes_back_to_the_same_shelf(self):
        m = self.mode
        m.choose(m.keys.index("science"))
        room = m.go_in(); self.app.update()
        self.assertIsInstance(room, self.A.IllustratedRoom)
        self.assertEqual(m.state(), "withdrawn")
        back = self.app.go_home(); self.app.update()
        self.assertIs(back, m)
        self.assertEqual(m.keys[m.at], "science")

    def test_escape_is_the_desktop(self):
        self.mode.desktop(); self.app.update()
        self.assertEqual(self.mode.state(), "withdrawn")
        self.assertTrue(self.app.body.winfo_ismapped())

    def test_ask_nemo_is_the_prompt_window(self):
        from nemo.gui.prompt import PromptWindow
        pw = self.mode.ask(); self.app.update()
        self.assertIsInstance(pw, PromptWindow)
        pw.destroy()

    def test_its_clock_dies_with_it(self):
        m = self.mode
        job = m._clock_job
        self.assertTrue(job)
        with mock.patch.object(m, "after_cancel", wraps=m.after_cancel) as cancel:
            m.destroy()
        cancel.assert_called_once_with(job)


if __name__ == "__main__":
    unittest.main()
