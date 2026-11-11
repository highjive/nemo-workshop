"""The department view (owner's preferred, 2026-10-23): a busy worker's ring
glows while its real job runs (nemo/busy.py, what is left of the pixel rooms).
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

from nemo import busy as P
from nemo.staff import team


class TestTheSignals(unittest.TestCase):
    def test_busy_follows_the_real_job(self):
        app = mock.Mock(job=mock.Mock(running=True, kind="story"))
        with mock.patch("nemo.foreman.load", return_value=[]):
            busy = P.signals(app)
        self.assertTrue(busy["writer"] and busy["editor"] and busy["timekeeper"])
        self.assertFalse(busy["artist"] or busy["foreman"])
        idle = P.signals(mock.Mock(job=None))
        self.assertFalse(any(idle.values()))
        self.assertTrue(set(P.NO_SIGNAL).isdisjoint(busy))         # said, not pretended


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(unittest.TestCase):
    def test_it_animates_and_its_timer_dies_with_it(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                lib = app.open_department("library"); app.update()
                self.assertIsInstance(lib, A.IllustratedRoom)     # his preferred view (2026-10-23)
                self.assertFalse(lib.painted)                     # no painting yet: the card stands in
                with mock.patch.object(P, "signals", return_value={"writer": True}):
                    lib.phase = 0; lib.tick()
                    self.assertEqual(lib.canvas.itemcget(lib.rings["writer"], "width"), "7.0")
                    self.assertEqual(lib.canvas.itemcget(lib.rings["artist"], "width"), "4.0")
                # Its tick, the introductions and (full screen, 2026-11-04) a
                # redraw at the new size: every one still pending is cancelled.
                pending = {j for j in (lib._job, lib._intro_job, lib._resize_job) if j}
                self.assertIn(lib._job, pending)
                with mock.patch.object(lib, "after_cancel", wraps=lib.after_cancel) as cancel:
                    lib.destroy()
                self.assertEqual({c.args[0] for c in cancel.call_args_list}, pending)
            finally:
                app.destroy()


    def test_it_fills_the_window_it_is_given(self):
        # Owner, 2026-11-04: full screen. It was 960 wide whatever the window.
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.geometry("1366x740+0+0"); app.update()
            try:
                lib = app.open_department("library")
                for _ in range(10):
                    app.update(); lib.after(30); app.update_idletasks()
                    if lib._resize_job is None and lib.W != 960:
                        break
                    app.after(150); app.update()
                app.update()
                self.assertGreater(lib.W, 960)
                self.assertEqual(lib.W, int(lib.canvas.cget("width")))
                self.assertIn("writer", lib.rings)                 # the team is drawn again
                lib.destroy()
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()


class TestEveryDepartment(unittest.TestCase):
    def test_no_signal_is_said_for_every_worker_but_the_timekeeper(self):
        from nemo.staff import DEPARTMENTS
        for key in DEPARTMENTS:
            roles = {e.key.split(".", 1)[1] for e in team(key)}
            self.assertNotIn("timekeeper", P.no_signal(key))
            self.assertTrue(set(P.no_signal(key)) <= roles, key)
