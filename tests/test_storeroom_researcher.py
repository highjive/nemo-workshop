"""The Storeroom's Researcher (owner, 2026-10-22): which library part an
unlinked item may be. It suggests; only the owner links.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import staff, storeroom
from nemo.parts import PartsLibrary

LIB = PartsLibrary.load()


def first(name):
    found = storeroom.suggest(name, LIB)
    return found[0].ref if found else None


class TestSuggestions(unittest.TestCase):
    def test_the_part_number_finds_the_part(self):
        self.assertEqual(first("BME280 sensor board"), "bme280")
        self.assertEqual(first("tower pro SG90"), "sg90_servo")
        self.assertEqual(first("MFRC522 RFID reader"), "rc522")        # RC522 ends MFRC522

    def test_a_letter_on_the_end_is_another_chip(self):
        found = storeroom.suggest("ESP32-C3 super mini", LIB)
        self.assertEqual(found[0].ref, "esp32c3_devkit")
        plain = next(s for s in found if s.ref == "esp32_devkit_v1")
        self.assertNotIn("part number", plain.why)                     # ESP32 is not ESP32-C3's
        self.assertLess(plain.score, found[0].score - 0.4)

    def test_words_when_there_is_no_number(self):
        self.assertEqual(first("5V relay module"), "relay_5v_1ch")
        self.assertEqual(first("Pi Pico"), "rp2040_pico")

    def test_sellers_words_alone_suggest_nothing(self):
        self.assertEqual(storeroom.suggest("module board mini", LIB), [])
        self.assertEqual(storeroom.suggest("blue LED 5 mm", LIB), [])
        self.assertEqual(storeroom.suggest("anything", None), [])

    def test_a_datasheet_that_mentions_it(self):
        sheet = mock.Mock(file="weird.pdf", refs=["bme280"])
        sheets = mock.Mock(search=mock.Mock(return_value=[mock.Mock(file="weird.pdf")]),
                           sheets=mock.Mock(return_value=[sheet]))
        with mock.patch.object(LIB, "__iter__", return_value=iter([])):
            found = storeroom.suggest("XYZ123 thing", LIB, sheets=sheets)
        self.assertEqual([(s.ref, s.why) for s in found],
                         [("bme280", "its datasheet weird.pdf mentions XYZ123")])


class TestLinking(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_suggesting_links_nothing_and_link_keeps_the_count(self):
        storeroom.add(self.root, "tower pro SG90", 4, where="drawer 2", library=LIB)
        self.assertEqual([i.name for i in storeroom.unlinked(self.root)], ["tower pro SG90"])
        storeroom.suggest("tower pro SG90", LIB)
        self.assertEqual(storeroom.load(self.root)[0].part, "")        # only a suggestion
        item = storeroom.link(self.root, "tower pro SG90", "sg90_servo", LIB)
        self.assertEqual((item.part, item.quantity, item.where), ("sg90_servo", 4, "drawer 2"))
        self.assertEqual(storeroom.unlinked(self.root), [])
        self.assertEqual(storeroom.on_hand(self.root), {"sg90_servo": 4})

    def test_what_cannot_be_linked(self):
        storeroom.add(self.root, "thing", 1, library=LIB)
        with self.assertRaises(storeroom.StoreroomError):
            storeroom.link(self.root, "thing", "no_such_part", LIB)
        with self.assertRaises(storeroom.StoreroomError):
            storeroom.link(self.root, "not here", "bme280", LIB)

    def test_the_researcher_works(self):
        self.assertTrue(staff.STAFF["storeroom.researcher"].working)
        self.assertFalse(staff.STAFF["storeroom.writer"].working)       # the owner's choice


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheDialog(unittest.TestCase):
    def test_suggest_then_link(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        root = Path(tempfile.mkdtemp())
        app = A.NemoApp(); app.update()
        try:
            app.cfg.data.setdefault("paths", {})["storeroom"] = str(root)
            d = A.StoreroomDialog(app); app.update()
            d.root_dir = root
            storeroom.add(root, "BME280 sensor board", 2, library=app.library)
            d.refresh()
            d.fields["name"].delete(0, "end"); d.fields["name"].insert(0, "BME280 sensor board")
            d.suggest()
            self.assertEqual(d.fields["part"].get(), "bme280")
            self.assertEqual(storeroom.load(root)[0].part, "")
            d.link()
            self.assertEqual(storeroom.load(root)[0].part, "bme280")
            self.assertIn("now linked to bme280", d.note.cget("text"))
            d.destroy()
        finally:
            app.destroy()
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
