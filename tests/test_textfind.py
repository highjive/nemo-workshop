"""Find and replace like Notepad 11 (owner, 2026-10-28): match case, wrap
around, search up or down, replace, replace all, and Notepad's own message.
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

from nemo import textfind as F

TEXT = "The lamp. the LAMP. A lamp post."


class TestFinding(unittest.TestCase):
    def test_forwards_from_the_cursor_case_or_not(self):
        self.assertEqual(F.find(TEXT, "lamp", 0), (4, 8))
        self.assertEqual(F.find(TEXT, "lamp", 5), (14, 18))          # LAMP: case not matched
        self.assertEqual(F.find(TEXT, "lamp", 5, match_case=True), (22, 26))
        self.assertIsNone(F.find(TEXT, "kettle", 0))
        self.assertIsNone(F.find(TEXT, "", 0))

    def test_wrap_around_or_stop_at_the_end(self):
        self.assertEqual(F.find(TEXT, "the", 20), (0, 3))            # round to the start
        self.assertIsNone(F.find(TEXT, "the", 20, wrap=False))

    def test_search_up(self):
        self.assertEqual(F.find(TEXT, "lamp", 20, reverse=True), (14, 18))
        self.assertEqual(F.find(TEXT, "lamp", 3, reverse=True), (22, 26))   # round to the end
        self.assertIsNone(F.find(TEXT, "lamp", 3, reverse=True, wrap=False))

    def test_offsets_hold_for_letters_that_lower_into_two(self):
        s = "İstanbul lamp"
        self.assertEqual(F.find(s, "LAMP", 0), (9, 13))

    def test_replace_all_and_count(self):
        new, n = F.replace_all(TEXT, "lamp", "torch")
        self.assertEqual((new, n), ("The torch. the torch. A torch post.", 3))
        self.assertEqual(F.replace_all(TEXT, "lamp", "torch", match_case=True)[1], 2)
        self.assertEqual(F.replace_all("aaaa", "aa", "b"), ("bb", 2))   # not overlapping
        self.assertEqual(F.count(TEXT, "LAMP", match_case=True), 1)
        self.assertEqual(F.cannot_find("kettle"), 'Cannot find "kettle"')


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheFindBar(unittest.TestCase):
    def test_find_replace_and_replace_all_in_a_text_box(self):
        try:
            import tkinter as tk
            from nemo.gui import app as A
            from nemo.gui.findbar import FindBar
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                box = tk.Text(app, undo=True); box.pack(); box.insert("1.0", TEXT)
                box.mark_set("insert", "1.0"); box.focus_set(); app.update()
                bar = FindBar.open_for(box); app.update()
                bar.find_var.set("lamp")
                self.assertTrue(bar.find_next())
                self.assertEqual(box.get("sel.first", "sel.last"), "lamp")
                self.assertTrue(bar.find_next())
                self.assertEqual(box.index("sel.first"), "1.14")      # LAMP, case not matched
                bar.case_var.set(True)
                bar.replace_var.set("torch")
                bar.replace()                                         # LAMP is not "lamp": finds on
                self.assertEqual(box.get("sel.first", "sel.last"), "lamp")
                bar.replace()                                         # replaces it, finds the next
                self.assertIn("A torch post", box.get("1.0", "end-1c"))
                bar.case_var.set(False)
                self.assertEqual(bar.replace_all(), 2)
                self.assertEqual(box.get("1.0", "end-1c"), "The torch. the torch. A torch post.")
                box.edit_undo()                                       # one undo takes Replace all back
                self.assertIn("LAMP", box.get("1.0", "end-1c"))
                bar.find_var.set("kettle")
                self.assertFalse(bar.find_next())
                self.assertEqual(bar.status.cget("text"), 'Cannot find "kettle"')
                self.assertIs(FindBar.open_for(box), bar)              # one bar per text box
                bar.destroy()
                box.focus_force(); app.update()
                box.event_generate("<Control-h>"); app.update()       # the keys open it, with Replace
                again = box._findbar
                self.assertTrue(again.replacing)
                again.destroy()
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
