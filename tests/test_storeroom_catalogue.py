"""The Storeroom's catalogue redone (owner, 2026-10-29): search as you type,
sort by any column, group by where things are kept or by kind of part.
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

from nemo import storeroom as S
from nemo.parts import PartsLibrary

ITEMS = [S.Item("a", "ESP32 DevKit", 3, "esp32_devkit_v1", "drawer 1", "spare"),
         S.Item("b", "Jumper wires", 40, "", "blue box", ""),
         S.Item("c", "SG90 servo", 2, "sg90_servo", "drawer 1", "one with a bent arm"),
         S.Item("d", "Solder", 1, "", "", "lead free")]


class TestTheView(unittest.TestCase):
    def test_search_every_word_any_field_any_case(self):
        names = lambda q: [i.name for _, items in S.view(ITEMS, q) for i in items]
        self.assertEqual(names("DRAWER"), ["ESP32 DevKit", "SG90 servo"])
        self.assertEqual(names("drawer bent"), ["SG90 servo"])
        self.assertEqual(names("lead free"), ["Solder"])
        self.assertEqual(names("nothing like it"), [])
        self.assertEqual(len(names("")), 4)

    def test_sort_by_a_column_and_back(self):
        by = lambda col, desc=False: [i.name for i in S.view(ITEMS, sort=col, descending=desc)[0][1]]
        self.assertEqual(by("qty"), ["Solder", "SG90 servo", "ESP32 DevKit", "Jumper wires"])
        self.assertEqual(by("qty", True)[0], "Jumper wires")
        self.assertEqual(by("where")[-1], "Solder")                 # nowhere said goes last

    def test_group_by_where_and_by_kind(self):
        groups = dict(S.view(ITEMS, group="where"))
        self.assertEqual(list(groups), ["blue box", "drawer 1", S.NOWHERE])
        self.assertEqual([i.name for i in groups["drawer 1"]], ["ESP32 DevKit", "SG90 servo"])
        lib = PartsLibrary.load()
        kinds = dict(S.view(ITEMS, group="kind", library=lib))
        self.assertEqual(list(kinds)[-1], S.UNSORTED)
        self.assertEqual(len(kinds[S.UNSORTED]), 2)                # wires and solder: not linked
        self.assertEqual(sum(len(v) for v in kinds.values()), 4)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(unittest.TestCase):
    def test_typing_filters_headings_sort_and_groups_show(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                store = Path(t) / "store"
                with mock.patch.object(S, "load", return_value=list(ITEMS)):
                    w = A.StoreroomDialog(app); app.update()
                self.assertEqual(w.count.cget("text"), "4 item(s)")
                w.query.set("drawer"); app.update()
                self.assertEqual(len(w.tree.get_children()), 2)
                self.assertEqual(w.count.cget("text"), "2 of 4 item(s)")
                w.query.set("")
                w.sort_by("qty"); w.sort_by("qty")                  # twice: the other way
                self.assertEqual(w.tree.get_children()[0], "b")     # the most first
                self.assertIn("▼", w.tree.heading("qty", "text"))
                w.group.set("Where it is kept"); w.show()
                self.assertEqual(w.tree.get_children()[0], "group:blue box")
                self.assertEqual(w.tree.get_children("group:drawer 1"), ("a", "c"))
                w.destroy()
                del store
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
