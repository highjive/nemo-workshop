"""Accessibility (2026-11-08, the third of the owner's order, after Claude Code
Game Studios' accessibility checklist): text that can be made larger, Enter
presses the focused button, a department's people reachable by keyboard, and
nothing that flashes more than three times a second. Status was already said
in words as well as colour (the step list's stamps)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.gui import theme as T


class TestTheSizes(unittest.TestCase):
    def test_a_size_is_one_of_nemos(self):
        self.assertEqual(T.text_size(125), 125)
        self.assertEqual(T.text_size(140), 150)
        self.assertEqual(T.text_size("big"), 100)
        self.assertEqual(T.text_size(None), 100)
        self.assertEqual(T.text_size(400), 175)
        self.assertEqual(T.scaled(9, 150), 14)

    def test_the_smallest_text_at_the_largest_size_is_readable(self):
        smallest = min(pt for pt, _ in T.SIZES.values())
        self.assertGreaterEqual(T.scaled(smallest, max(T.TEXT_SIZES)), 15)


class TestNothingFlashesFast(unittest.TestCase):
    def test_a_ring_changes_at_most_three_times_a_second(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "gui" / "app.py").read_text(
            encoding="utf-8")
        line = next(l for l in src.splitlines() if "TICK_MS =" in l and "FACE" in l)
        tick = int(line.rsplit("=", 1)[1].split(",")[-1])
        self.assertGreaterEqual(tick, 334)


@unittest.skipUnless(_sandbox.has_display(), "needs a display")
class TestInTheWindow(unittest.TestCase):
    def setUp(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name)); env.start()
        self.addCleanup(env.stop)
        self.app = A.NemoApp(); self.app.update(); self.addCleanup(self.app.destroy)

    def settings(self):
        from nemo.gui import controller as C
        return C.load_settings()

    def test_text_grows_at_once_and_is_remembered(self):
        app = self.app
        body = app.fonts["body"]
        self.assertEqual((body[1], app.text_percent), (10, 100))
        self.assertEqual(app.change_text_size(+1), 125)
        self.assertEqual(body.cget("size"), 12)                  # the same font, changed
        self.assertEqual(self.settings()["text_size"], 125)
        self.assertEqual(app.text_button.cget("text"), "Text 125%")
        for _ in range(5):
            app.change_text_size(+1)
        self.assertEqual(app.text_percent, 175)                  # Ctrl + stops at the largest
        self.assertEqual(app.change_text_size(+1, wrap=True), 100)   # the button goes round
        app.change_text_size(-1)
        self.assertEqual(app.text_percent, 100)
        app.change_text_size(+1); app.change_text_size(0)
        self.assertEqual(app.text_percent, 100)

    def test_every_department_button_shows_at_the_largest_text(self):
        # 2026-11-08: at 150 % Print Shop to Help were pushed out of the window.
        app = self.app
        app.geometry("1366x740+0+0"); app.update()
        while app.text_percent != max(self.A.T.TEXT_SIZES):
            app.change_text_size(+1)
        app.update()
        bottom = app.winfo_rooty() + app.winfo_height()
        for b in app._tool_buttons:
            self.assertTrue(b.winfo_ismapped(), b.cget("text"))
            self.assertLessEqual(b.winfo_rooty() + b.winfo_height(), bottom, b.cget("text"))
            self.assertGreaterEqual(b.winfo_width(),
                                    app.fonts["body"].measure(b.cget("text")), b.cget("text"))
        self.assertGreater(app.proj_list.winfo_height(), 3 * app.fonts["body"].metrics("linespace"))

    def test_enter_presses_the_focused_button_and_only_it(self):
        from tkinter import ttk
        pressed = []
        top = self.A.tk.Toplevel(self.app); self.addCleanup(top.destroy)
        top.bind("<Return>", lambda e: pressed.append("dialog's OK"))
        cancel = ttk.Button(top, text="Cancel", command=lambda: pressed.append("Cancel"))
        cancel.pack(); off = ttk.Button(top, text="Off", state="disabled",
                                        command=lambda: pressed.append("Off"))
        off.pack()
        ev = mock.Mock(widget=cancel)
        self.assertEqual(self.A._press_focused(ev), "break")
        self.assertEqual(self.A._press_focused(mock.Mock(widget=off)), "break")
        self.assertEqual(pressed, ["Cancel"])

    def test_a_departments_people_by_keyboard(self):
        room = self.app.open_department("library"); self.app.update()
        room.end_introductions(); self.app.update()
        first = room.choose_face(+1)
        self.assertTrue(room.canvas.find_withtag("keyfocus"))
        self.assertEqual(room.choose_face(-1), room._roles()[-1])      # round from the first
        room.choose_face(+1)
        self.assertEqual(room.open_chosen_face().title, room._profile.title)
        self.assertEqual(room._profile_role, first)
        room.hide_profile()
        room._draw(room.W, room.H)                                      # kept on a redraw
        self.assertTrue(room.canvas.find_withtag("keyfocus"))


if __name__ == "__main__":
    unittest.main()
