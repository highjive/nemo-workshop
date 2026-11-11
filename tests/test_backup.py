"""The backup made by hand from the Storeroom (owner, 2026-10-21).

What goes in (the owner's work and settings), what never does (the key,
the admin and safety store, the models), that a backup can be checked, and
that a damaged one is caught.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import backup, cli


class AHome(unittest.TestCase):
    """A home with work in it, and the things that must stay out."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.home))
        self._env.start()
        # config.CONFIG_HOME is fixed at import; point it at this home.
        self._ch = mock.patch("nemo.config.CONFIG_HOME", self.home / ".nemo")
        self._ch.start()
        self.write("nemo-projects/lamp/brief.yaml", "name: lamp\n")
        self.write("nemo-projects/lamp/.nemo/work.jsonl", "{}\n")
        self.write("nemo-stories/fox/story.md", "# The fox — a tale\n")
        self.write("nemo-storeroom/stock.yaml", "red-led:\n  name: Red LED\n  quantity: 3\n")
        self.write(".nemo/config.yaml", "engine: {}\n")
        self.write(".nemo/keys/mouser.key", "SECRET-KEY")
        self.write(".nemo/admin/state.json", "{}")
        self.write(".nemo/safety.json", "{}")
        self.write(".nemo/models/m.gguf", "weights")
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def tearDown(self):
        self._ch.stop(); self._env.stop(); self.t.cleanup()

    def write(self, rel: str, text: str):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def names(self, made) -> set[str]:
        with zipfile.ZipFile(made.path) as z:
            return set(z.namelist())


class TestWhatGoesIn(AHome):
    def test_the_work_and_settings_go_in(self):
        made = backup.make(self.cfg, self.home / "backups")
        names = self.names(made)
        for n in ("projects/lamp/brief.yaml", "projects/lamp/.nemo/work.jsonl",
                  "stories/fox/story.md", "storeroom/stock.yaml",
                  "settings/config.yaml", backup.MANIFEST):
            self.assertIn(n, names)
        self.assertEqual(made.files, len(names) - 1)
        self.assertIn("parts", made.left_out)

    def test_the_key_the_safety_store_and_the_models_never_do(self):
        made = backup.make(self.cfg, self.home / "backups")
        with zipfile.ZipFile(made.path) as z:
            everything = b"".join(z.read(n) for n in z.namelist())
        self.assertNotIn(b"SECRET-KEY", everything)
        self.assertNotIn(b"weights", everything)
        self.assertFalse([n for n in self.names(made)
                          if "admin" in n or "safety" in n or "keys" in n])

    def test_a_backup_folder_inside_the_work_is_not_backed_up_into_itself(self):
        inside = self.home / "nemo-projects" / "backups"
        first = backup.make(self.cfg, inside, now=backup._dt.datetime(2026, 1, 1))
        second = backup.make(self.cfg, inside, now=backup._dt.datetime(2026, 1, 2))
        self.assertFalse([n for n in self.names(second) if n.endswith(".zip")])
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(backup.listing(inside), [second.path, first.path])

    def test_no_half_file_is_left_when_it_fails(self):
        with mock.patch("nemo.backup.zipfile.ZipFile.write", side_effect=OSError("disk full")):
            with self.assertRaises(backup.BackupError) as cm:
                backup.make(self.cfg, self.home / "backups")
        self.assertIn("disk full", str(cm.exception))
        self.assertEqual(list((self.home / "backups").iterdir()), [])


class TestChecking(AHome):
    def test_a_whole_backup_checks(self):
        made = backup.make(self.cfg, self.home / "backups")
        self.assertEqual(backup.verify(made.path), [])
        m = json.loads(zipfile.ZipFile(made.path).read(backup.MANIFEST))
        self.assertEqual(len(m["files"]), made.files)

    def test_a_changed_file_is_caught(self):
        made = backup.make(self.cfg, self.home / "backups")
        bad = self.home / "bad.zip"
        with zipfile.ZipFile(made.path) as src, zipfile.ZipFile(bad, "w") as dst:
            for n in src.namelist():
                data = src.read(n)
                dst.writestr(n, b"changed" if n == "storeroom/stock.yaml" else data)
        self.assertEqual(backup.verify(bad), ["storeroom/stock.yaml has changed"])

    def test_not_a_backup_says_so(self):
        junk = self.home / "junk.zip"
        junk.write_bytes(b"not a zip")
        self.assertIn("cannot be read", backup.verify(junk)[0])
        with zipfile.ZipFile(self.home / "plain.zip", "w") as z:
            z.writestr("a.txt", "a")
        self.assertIn("MANIFEST.json is missing", backup.verify(self.home / "plain.zip")[0])


class TestTheCommand(AHome):
    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["backup", *argv])
        return rc, out.getvalue()

    def test_make_list_check(self):
        to = str(self.home / "backups")
        rc, out = self.run_cli("--to", to)
        self.assertEqual(rc, 0, out)
        self.assertIn("Researcher's key", out)
        zipped = backup.listing(Path(to))[0]
        self.assertIn(zipped.name, self.run_cli("list", "--to", to)[1])
        rc, out = self.run_cli("check", str(zipped))
        self.assertEqual(rc, 0)
        self.assertIn("is whole", out)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheStoreroomButton(AHome):
    def test_the_window_makes_a_backup(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        app = A.NemoApp(); app.update()
        try:
            w = A.StoreroomDialog(app); app.update()
            made = w.backup(self.home / "backups")
            self.assertEqual(backup.verify(made.path), [])
            self.assertIn(made.path.name, w.note.cget("text"))
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
