"""Departments open inside Nemo's window, not as windows of their own
(owner, 2026-10-25); Home and Workshop on the bar bring those back.
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


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestDialogsAboveADepartment(unittest.TestCase):
    """D205 (booted stick, 2026-10-31): the Nurse's question opened under the
    overrideredirect department, holding the grab: Nemo froze. No window
    manager stacks here, so these test the standing aside, not the stacking."""

    def setUp(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name))
        self.env.start()
        self.app = A.NemoApp(); self.app.update()
        self.room = A.Clinic(self.app); self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.env.stop()
        self.tmp.cleanup()

    def system(self, name):
        real = self.app.tk.call
        return mock.patch.object(self.app, "tk", mock.Mock(call=lambda *a: (
            name if a == ("tk", "windowingsystem") else real(*a))))

    def test_on_linux_the_department_steps_aside_and_comes_back(self):
        with self.system("x11"):
            self.assertTrue(self.app.stand_aside())
        self.assertEqual(self.room.state(), "withdrawn")
        self.app._place_embedded()                               # a <Configure> meanwhile
        self.assertEqual(self.room.state(), "withdrawn")
        self.app.come_back(); self.app.update()
        self.assertEqual(self.room.state(), "normal")

    def test_on_windows_nothing_moves(self):
        with self.system("win32"):
            self.assertFalse(self.app.stand_aside())
        self.assertEqual(self.room.state(), "normal")

    def test_every_message_box_and_file_dialog_passes_through_it(self):
        from tkinter import commondialog
        self.assertEqual(commondialog.Dialog.show.__name__, "above")

    def test_the_nurse_works_without_holding_the_window_still(self):
        import time
        from nemo import clinic
        finding = clinic.Finding("doctors.gp", clinic.LOOK, "x", "y", "z", remedy="backup")

        def slow(*a):
            time.sleep(0.3)
            return {"title": "Make a backup"}
        self.room.ask = lambda *a, **k: True
        self.room.run = lambda: None
        self.room.N = mock.Mock(NurseError=RuntimeError)
        self.room.N.plan.return_value = mock.Mock(token="t", stamp="s")
        self.room.N.describe.return_value = "the plan"
        self.room.N.treat.side_effect = slow
        ticks, real = [], self.app.update
        with mock.patch.object(self.app, "update", lambda: (ticks.append(1), real())):
            rec = self.room.treat(finding)
        self.assertEqual(rec["title"], "Make a backup")
        self.assertGreater(len(ticks), 1)                        # the window went on running


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestOneWindow(unittest.TestCase):
    def test_a_department_takes_the_workshops_place_and_gives_it_back(self):
        try:
            from nemo.gui import app as A
            from nemo.gui.prompt import PromptWindow
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                sci = A.ScienceRoom(app); app.update()
                self.assertIs(app._embedded, sci)
                self.assertTrue(sci.wm_overrideredirect())               # no frame of its own
                slot = app._slot
                self.assertEqual((sci.winfo_rootx(), sci.winfo_width()),
                                 (slot.winfo_rootx(), slot.winfo_width()))  # laid over the space
                self.assertFalse(app.body.winfo_ismapped())
                self.assertEqual(app._stage_label.cget("text"), "Science")
                sci.title("Science: sums")                               # a later wm call is harmless
                self.assertEqual(app._stage_label.cget("text"), "Science: sums")
                room = app.open_department("music"); app.update()        # one at a time
                self.assertFalse(sci.winfo_exists())
                self.assertIs(app._embedded, room)
                app.back_to_workshop(); app.update()
                self.assertIsNone(app._embedded)
                self.assertTrue(app.body.winfo_ismapped())
                A.Gaming(app); app.update()
                # Home is Nemo Mode now (owner, 2026-11-04); "home": "prompt"
                # in gui.json keeps the prompt window.
                from nemo.gui.nemomode import NemoMode
                home = app.go_home(); app.update()
                self.assertIsInstance(home, NemoMode)
                self.assertIsNone(app._embedded)
                home.destroy()
                from nemo.gui import controller as C
                C.save_settings({**C.load_settings(), "home": "prompt"})
                home = app.go_home(); app.update()
                self.assertIsInstance(home, PromptWindow)
                home.destroy()
                with mock.patch.dict(os.environ, {"NEMO_ONE_WINDOW": "off"}):
                    own = A.ScienceRoom(app); app.update()
                self.assertFalse(own.wm_overrideredirect())              # the old way, on request
                own.destroy()
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestHome(unittest.TestCase):
    def test_home_has_no_workshop_button_and_closing_it_closes_nemo(self):
        try:
            from nemo.gui import app as A
            from nemo.gui.prompt import PromptWindow
        except ImportError:
            self.skipTest("tkinter not installed")
        import tkinter as tk
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                home = PromptWindow(app); app.update()
                texts = []
                todo = [home]
                while todo:
                    w = todo.pop()
                    todo += w.winfo_children()
                    if isinstance(w, tk.Button):
                        texts.append(w.cget("text"))
                self.assertNotIn("Workshop", texts)              # he says what he wants instead
                self.assertIn("Send", texts)
                with mock.patch.object(app, "_close") as close:
                    home.protocol("WM_DELETE_WINDOW")            # the handler is set
                    home.quit_nemo()
                close.assert_called_once()
                home.destroy()
            finally:
                app.destroy()


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestBack(unittest.TestCase):
    """Owner, 2026-11-11: "in each department method back to previous menus".
    Back on the bar returns to the screen before: a department's room from its
    window, and Home when there is nothing before."""

    def setUp(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name))
        self.env.start()
        self.app = A.NemoApp(); self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.env.stop()
        self.tmp.cleanup()

    def shown(self):
        self.app.update(); self.app.update()
        return self.app._embedded

    def test_window_to_room_to_home(self):
        A = self.A
        A.IllustratedRoom(self.app, "science")
        self.assertIsInstance(self.shown(), A.IllustratedRoom)
        self.app.real_window("science")
        self.assertIsInstance(self.shown(), A.ScienceRoom)
        self.assertEqual(self.app._back_button.cget("text"), "← Back")
        self.app.go_back()
        room = self.shown()
        self.assertIsInstance(room, A.IllustratedRoom)
        self.assertEqual(room.key, "science")
        self.assertEqual(self.app._back, [])               # going back is not a new step
        with mock.patch.object(self.app, "go_home") as home:
            self.app.go_back()
        home.assert_called_once()

    def test_home_forgets_the_way_back(self):
        A = self.A
        A.IllustratedRoom(self.app, "science"); self.shown()
        self.app.real_window("science"); self.shown()
        self.assertEqual(len(self.app._back), 1)
        self.app.back_to_workshop()
        self.assertEqual(self.app._back, [])
