"""The Storeroom: the parts the owner has to hand (owner, 2026-10-21).

What, how many and where, kept in stock.yaml apart from the parts library,
which says what a part IS. These tests hold the counts, the linking to the
library (exact names only, never a guess), the command and the window.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import cli, storeroom
from nemo.parts import PartsLibrary

LIB = PartsLibrary.load()


class Shelves(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name) / "nemo-storeroom"

    def tearDown(self):
        self.t.cleanup()


class TestTheCounts(Shelves):
    def test_an_empty_storeroom_is_empty(self):
        self.assertEqual(storeroom.load(self.root), [])

    def test_adding_again_adds_to_the_count(self):
        storeroom.add(self.root, "Red LED 5 mm", 10, where="drawer 3")
        i = storeroom.add(self.root, "red led 5 MM", 5)
        self.assertEqual((i.quantity, i.where), (15, "drawer 3"))
        self.assertEqual(len(storeroom.load(self.root)), 1)

    def test_taking_never_goes_below_none(self):
        storeroom.add(self.root, "Red LED 5 mm", 3)
        self.assertEqual(storeroom.take(self.root, "Red LED 5 mm", 3).quantity, 0)
        with self.assertRaises(storeroom.StoreroomError) as cm:
            storeroom.take(self.root, "Red LED 5 mm")
        self.assertIn("only 0", str(cm.exception))
        # At none it is kept, with its place, until removed.
        self.assertEqual(storeroom.load(self.root)[0].quantity, 0)
        self.assertTrue(storeroom.remove(self.root, "Red LED 5 mm"))
        self.assertFalse(storeroom.remove(self.root, "Red LED 5 mm"))

    def test_what_cannot_be_added(self):
        for name, qty in (("", 1), ("  ", 1), ("LED", 0), ("LED", -2)):
            with self.assertRaises(storeroom.StoreroomError, msg=(name, qty)):
                storeroom.add(self.root, name, qty)
        with self.assertRaises(storeroom.StoreroomError):
            storeroom.take(self.root, "nothing here")

    def test_the_file_is_utf8_and_survives_a_name_with_symbols(self):
        storeroom.add(self.root, "10 kΩ resistor", 20, notes="½ W")
        text = storeroom.stock_path(self.root).read_text(encoding="utf-8")
        self.assertIn("Ω", text)
        self.assertEqual(storeroom.load(self.root)[0].notes, "½ W")

    def test_a_broken_file_is_said_not_read_as_empty(self):
        # Read as empty, the next add would overwrite the owner's own edits.
        storeroom.stock_path(self.root).parent.mkdir(parents=True)
        storeroom.stock_path(self.root).write_text("a: [unclosed", encoding="utf-8")
        with self.assertRaises(storeroom.StoreroomError):
            storeroom.add(self.root, "LED", 1)
        self.assertEqual(storeroom.stock_path(self.root).read_text(encoding="utf-8"),
                         "a: [unclosed")


class TestTheLibraryLink(Shelves):
    def test_an_exact_ref_or_name_is_linked(self):
        p = next(iter(LIB))
        self.assertEqual(storeroom.add(self.root, p.ref, 1, library=LIB).part, p.ref)
        self.assertEqual(storeroom.add(self.root, p.name.upper(), 1, library=LIB).part, p.ref)

    def test_a_near_name_is_not_guessed(self):
        p = next(iter(LIB))
        i = storeroom.add(self.root, p.name + " spare", 1, library=LIB)
        self.assertEqual(i.part, "")

    def test_a_named_part_must_be_in_the_library(self):
        with self.assertRaises(storeroom.StoreroomError) as cm:
            storeroom.add(self.root, "Mystery board", 1, part="no_such_part", library=LIB)
        self.assertIn("nemo part add", str(cm.exception))
        p = next(iter(LIB))
        i = storeroom.add(self.root, "Mystery board", 2, part=p.ref, library=LIB)
        self.assertEqual(i.part, p.ref)
        self.assertEqual(storeroom.on_hand(self.root), {p.ref: 2})


class TestTheCommand(unittest.TestCase):
    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["store", *argv])
        return rc, out.getvalue()

    def test_add_take_list_remove(self):
        with tempfile.TemporaryDirectory() as t, \
             mock.patch.dict(os.environ, _sandbox.home_env(t)):
            rc, out = self.run_cli("add", "Red LED 5 mm", "--qty", "4", "--where", "drawer 3")
            self.assertEqual(rc, 0, out)
            self.assertIn("4 on hand, in drawer 3", out)
            rc, out = self.run_cli("take", "Red LED 5 mm", "--qty", "9")
            self.assertEqual(rc, 1)
            self.assertIn("only 4", out)
            rc, out = self.run_cli()
            self.assertIn("Red LED 5 mm", out)
            self.assertIn("1 item(s)", out)
            self.assertTrue((Path(t) / "nemo-storeroom" / "stock.yaml").is_file())
            self.assertEqual(self.run_cli("remove", "Red LED 5 mm")[0], 0)
            self.assertEqual(self.run_cli("remove", "Red LED 5 mm")[0], 1)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.app = A.NemoApp(); self.app.update()

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def test_add_and_take_from_the_window(self):
        w = self.A.StoreroomDialog(self.app); self.app.update()
        w.fields["name"].insert(0, "Red LED 5 mm")
        w.fields["qty"].delete(0, "end"); w.fields["qty"].insert(0, "6")
        w.fields["where"].insert(0, "drawer 3")
        w.add()
        # Tk gives back every value as text.
        self.assertEqual(w.tree.item("red-led-5-mm", "values")[:2], ("6", "Red LED 5 mm"))
        w.fields["qty"].delete(0, "end"); w.fields["qty"].insert(0, "2")
        w.take()
        self.assertEqual(w.tree.item("red-led-5-mm", "values")[0], "4")
        self.assertIn("4 left", w.note.cget("text"))
        w.fields["qty"].delete(0, "end"); w.fields["qty"].insert(0, "two")
        w.add()
        self.assertIn("whole number", w.note.cget("text"))
        w.destroy()

    def test_the_side_panel_has_the_button(self):
        texts = []
        def walk(widget):
            for c in widget.winfo_children():
                try:
                    texts.append(c.cget("text"))
                except Exception:                                # noqa: BLE001
                    pass
                walk(c)
        walk(self.app)
        self.assertIn("Storeroom", texts)


if __name__ == "__main__":
    unittest.main()
