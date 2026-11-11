"""Nemo's own look throughout (owner, 2026-11-04: "keep the nemo theme
throughout in all menus allow it to be more user friendly")."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.gui import theme as T

GUI = Path(__file__).resolve().parent.parent / "nemo" / "gui"
# The grey-green drafting palette the working windows had before.
OLD = ("#E6E8E3", "#F3F4F0", "#C4CAC2", "#D5DDD6", "#1B2422", "#56625D", "#22302E",
       "#DCE3DD", "#245B70", "#1B4859", "#33443F", "#415550", "#F2F5F1", "#9FB0A8",
       "#FAFBF8", "#3A4B47", "#8FB3A6", "#1B1530", "#FF3DF5", "#36F9F6", "#2A2140", "#0F1A12")


def contrast(a: str, b: str) -> float:
    def lum(h):
        rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestTheTheme(unittest.TestCase):
    def test_text_is_easy_to_read_everywhere_it_is_put(self):
        for ink, ground in ((T.INK, T.PAPER), (T.INK, T.PANEL), (T.INK, T.SELECT),
                            (T.INK2, T.PAPER), (T.INK2, T.PANEL), (T.SHELL_INK, T.SHELL),
                            (T.SHELL_INK, T.SHELL_2), ("#FFFFFF", T.ACTION), (T.INK, T.BRASS)):
            with self.subTest(ink=ink, ground=ground):
                self.assertGreaterEqual(contrast(ink, ground), 4.5)

    def test_it_is_nemos_walnut_and_brass(self):
        self.assertEqual(T.SHELL, "#21170F")          # the rooms' and home window's walnut
        self.assertEqual(T.BRASS, "#C49A52")          # the Home button and the ring edges
        self.assertEqual(T.BLUE, T.ACTION)            # the old name follows the new colour

    def test_no_window_keeps_the_old_grey_green(self):
        found = []
        for f in GUI.glob("*.py"):
            text = f.read_text(encoding="utf-8")
            for colour in OLD:
                if re.search(re.escape(colour), text, re.I) and f.name != "theme.py":
                    found.append(f"{f.name}: {colour}")
        self.assertEqual(found, [])

    def test_results_keep_their_inspection_colours(self):
        self.assertEqual((T.PASS, T.FAIL, T.SKIP), ("#3F6B35", "#9E2F1F", "#94640C"))


class TestTheWindowFitsTheScreen(unittest.TestCase):
    def test_a_saved_size_is_read(self):
        from nemo.gui.app import _saved_height
        self.assertEqual(_saved_height("1366x740+0+0"), 740)
        self.assertEqual(_saved_height(None), 0)
        self.assertEqual(_saved_height("junk"), 0)


if __name__ == "__main__":
    unittest.main()
