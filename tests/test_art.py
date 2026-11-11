"""Nemo's own paintings (owner, 2026-10-29): the department scenes and the
portraits live in ~/.nemo/art, not on the Storeroom's pictures shelf, so the
Theatre, the Storeroom's aisles and the drives' sorting never list them.
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

from nemo import art


class TestNemosOwnPictures(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        self._home = mock.patch("nemo.config.CONFIG_HOME", self.root / ".nemo"); self._home.start()
        self.store = self.root / "nemo-storeroom"
        pics = self.store / "pictures"
        for rel in ("departments/library.png", "employees/library/writer.png",
                    "employees-first/library/writer.png", "holiday/beach.jpg"):
            (pics / rel).parent.mkdir(parents=True, exist_ok=True)
            (pics / rel).write_bytes(b"\x89PNG" + rel.encode())

    def tearDown(self):
        self._home.stop(); self.t.cleanup()

    def test_moved_once_never_overwriting_his_own_pictures_stay(self):
        (art.home() / "departments").mkdir(parents=True)
        art.scene("library").write_bytes(b"newer")
        self.assertEqual(art.migrate(self.store), 2)               # the scene already there stays
        self.assertEqual(art.scene("library").read_bytes(), b"newer")
        self.assertTrue(art.portrait("library", "writer").is_file())
        self.assertTrue((art.home() / "employees-first/library/writer.png").is_file())
        pics = self.store / "pictures"
        self.assertTrue((pics / "holiday/beach.jpg").is_file())    # his pictures are his
        self.assertFalse((pics / "employees").exists())
        self.assertTrue((pics / "departments/library.png").is_file())   # kept, not overwritten
        self.assertEqual(art.migrate(self.store), 0)

    def test_no_menu_lists_them(self):
        art.migrate(self.store)
        from nemo import theatre
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))
        with mock.patch.object(cfg, "path", side_effect=lambda k: {
                "paths.storeroom": self.store}.get(k, self.root / "none")):
            names = [i.name for i in theatre.photos(cfg)]
        self.assertEqual(names, ["beach.jpg"])                      # his own, and none of Nemo's
        self.assertNotIn("writer.png", names)

    def test_an_older_stick_image_gets_copies_not_moves(self):
        with mock.patch.object(art, "kept_on_stick", return_value=False):
            self.assertEqual(art.migrate(self.store), 3)
        self.assertTrue(art.portrait("library", "writer").is_file())
        self.assertTrue((self.store / "pictures/employees/library/writer.png").is_file())

    def test_the_stick_keeps_them(self):
        sync = (Path(__file__).resolve().parent.parent / "install" / "linux" / "nemo-sync")
        self.assertIn(".nemo/art", sync.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
