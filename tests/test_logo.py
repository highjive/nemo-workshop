"""Nemo's cog (owner, 2026-10-21): the window icon and the prompt window's
orb, from pictures shipped with the package.
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

from nemo.gui import controller as C

SIZES = (16, 32, 64, 120, 150, 256, 512, 1024)


class TestTheFiles(unittest.TestCase):
    def test_every_size_is_shipped_and_is_a_png(self):
        for n in SIZES:
            p = C.logo(n)
            self.assertTrue(p.is_file(), p)
            self.assertEqual(p.read_bytes()[:4], bytes([0x89]) + b"PNG", p)

    def test_the_package_data_includes_them(self):
        text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"data/logo/*.png"', text)

    def test_the_icons_are_square_and_clear_round_the_cog(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        for n in (16, 32, 64, 120, 150, 256):
            im = Image.open(C.logo(n))
            self.assertEqual(im.size, (n, n))
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.getpixel((0, 0))[3], 0)            # a clear corner


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindows(unittest.TestCase):
    def test_the_icon_and_the_orb(self):
        try:
            from nemo.gui import app as A
            from nemo.gui.prompt import PromptWindow
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                self.assertEqual(len(app._icons), 3)
                pw = PromptWindow(app); app.update()
                self.assertIsNotNone(pw._cog)
                # 2026-10-22: the cog fills the window, glowing, and the
                # prompt sits on it; the rings are gone.
                self.assertEqual(len(pw.glow.frames), pw.glow.LEVELS)
                kinds = {pw.glow.type(i) for i in pw.glow.find_all()}
                self.assertEqual(kinds, {"image", "window"})
                pw.glow.set_voice(1.0)
                self.assertEqual(pw.glow.level(), 1.0)            # brightest while it hears
                pw.glow.set_voice(0.0)
                self.assertLess(pw.glow.level(), 0.61)            # dimmer while it waits
                pw.destroy()
            finally:
                app.destroy()

    def test_the_glow_masks_are_shipped(self):
        for part in ("halo", "logos"):
            p = C.logo_part(part)
            self.assertTrue(p.is_file(), p)
            self.assertEqual(p.read_bytes()[:4], bytes([0x89]) + b"PNG", p)

    def test_no_picture_is_no_failure(self):
        try:
            from nemo.gui import app as A
            from nemo.gui.prompt import PromptWindow
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)), \
             mock.patch.object(C, "logo", return_value=Path(t) / "gone.png"):
            app = A.NemoApp(); app.update()
            try:
                self.assertEqual(app._icons, [])
                pw = PromptWindow(app); app.update()
                self.assertIsNone(pw._cog)
                pw.destroy()
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()


class TestTheWindowsIcon(unittest.TestCase):
    """2026-10-29 ("sort out Nemo icon"): the desktop shortcut showed
    Python's icon and the taskbar grouped Nemo under Python."""

    def test_the_ico_has_every_size_windows_asks_for(self):
        from PIL import Image
        from nemo.gui import controller as C
        with Image.open(C.logo_ico()) as im:
            sizes = set(im.info["sizes"])
        self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes)

    def test_the_installers_shortcut_uses_it_and_opens_home(self):
        app = Path(__file__).resolve().parent.parent
        doc = next((p for p in (app / "NemoDoc.ps1", app / "install" / "windows" / "NemoDoc.ps1")
                    if p.is_file()), None)
        if doc is None:
            self.skipTest("no NemoDoc.ps1 here")
        text = doc.read_text(encoding="utf-8-sig")
        self.assertIn(r'nemo\data\logo\nemo.ico', text)
        self.assertIn('$lnk.IconLocation', text)
        self.assertIn('"-m nemo.gui --prompt"', text)
