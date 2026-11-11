"""Updates once NemoIso has booted (owner, 2026-10-23): a newer NemoWin.zip
on the Windows disk is offered, unpacked, checked and chosen; nemodoc starts it.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import update as U

APP = Path(__file__).resolve().parent.parent
COMMIT = "a" * 40


def ut(t: int) -> bytes:
    return struct.pack("<HHBI", 0x5455, 5, 1, t)


def make_zip(path: Path, when: int, commit: str = COMMIT, files: dict | None = None,
             real: bool = False):
    """A zip shaped like `git archive --prefix=NemoWin/`; real=True carries this tree's nemo."""
    with zipfile.ZipFile(path, "w") as z:
        z.comment = commit.encode()
        items = dict(files or {"nemo/__init__.py": "__version__ = 'x'\n"})
        if real:
            for f in (APP / "nemo").rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts:
                    items["nemo/" + f.relative_to(APP / "nemo").as_posix()] = f.read_bytes()
        for name, data in items.items():
            info = zipfile.ZipInfo("NemoWin/" + name)
            info.extra = ut(when)
            z.writestr(info, data)


class AnImage(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        (self.root / "opt").mkdir()
        (self.root / "opt" / "COMMIT").write_text("b" * 40, encoding="utf-8")
        (self.root / "opt" / "COMMIT_TIME").write_text("1000", encoding="utf-8")
        self._p = mock.patch.object(U, "PREFIX", self.root / "opt"); self._p.start()
        self._e = mock.patch.dict(os.environ, {"NEMO_UPDATES": str(self.root / "updates")})
        self._e.start()

    def tearDown(self):
        self._e.stop(); self._p.stop(); self.t.cleanup()


class TestWhatIsOffered(AnImage):
    def test_a_newer_zip_is_offered_an_older_or_same_one_not(self):
        z = self.root / "NemoWin.zip"
        make_zip(z, 2000)
        found = U.available(str(z))
        self.assertEqual((found.commit, found.time), (COMMIT, 2000))
        self.assertIn("commit aaaaaaa", U.describe(found))
        make_zip(z, 900)
        self.assertIsNone(U.available(str(z)))                   # older than the image
        make_zip(z, 2000, commit="b" * 40)
        self.assertIsNone(U.available(str(z)))                   # the image's own commit

    def test_not_a_nemowin_zip(self):
        z = self.root / "other.zip"
        make_zip(z, 2000, commit="hello")
        self.assertIsNone(U.available(str(z)))
        make_zip(z, 2000, files={"README": "x"})
        self.assertIsNone(U.available(str(z)))
        z.write_bytes(b"not a zip")
        self.assertIsNone(U.available(str(z)))
        self.assertIsNone(U.available(str(self.root / "missing.zip")))

    def test_the_real_nemowin_zip_reads(self):
        z = Path("C:/Nemo/dist/NemoWin.zip")
        if not z.is_file():
            self.skipTest("no NemoWin.zip here")
        found = U.read_zip(z)
        git = subprocess.run(["git", "-C", str(APP), "log", "-1", "--format=%ct", found.commit],
                             capture_output=True, text=True)
        if git.returncode != 0:
            self.skipTest("its commit is not in this repository")
        self.assertEqual(found.time, int(git.stdout))            # the commit's own time


class TestApplying(AnImage):
    def test_unpacked_checked_and_chosen_then_stopped(self):
        z = self.root / "NemoWin.zip"
        make_zip(z, 2000, real=True)
        dest = U.apply(U.available(str(z)))
        self.assertTrue((dest / "nemo" / "update.py").is_file())
        self.assertEqual(U.in_use(), dest)
        self.assertFalse(any(p.name.endswith(".part") for p in dest.parent.iterdir()))
        U.stop_using()
        self.assertIsNone(U.in_use())

    def test_the_update_in_use_is_not_offered_again(self):
        """D204 (booted stick, 2026-10-31): after "update" restarted Nemo, it
        said a newer version was available: it asked only about the image."""
        z = self.root / "NemoWin.zip"
        make_zip(z, 2000, real=True)
        dest = U.apply(U.available(str(z)))
        self.assertIsNone(U.available(str(z)))
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(dest)}):
            self.assertEqual(U.running(), dest)
        with mock.patch.dict(os.environ, {"PYTHONPATH": ""}):
            self.assertIsNone(U.running())
        U.stop_using()
        self.assertIsNotNone(U.available(str(z)))                 # gone back: offered again

    def test_one_that_does_not_import_is_refused_and_nothing_chosen(self):
        z = self.root / "NemoWin.zip"
        make_zip(z, 2000, files={"nemo/__init__.py": "import a_library_the_image_lacks\n"})
        with self.assertRaises(RuntimeError) as err:
            U.apply(U.available(str(z)))
        self.assertIn("a_library_the_image_lacks", str(err.exception))
        self.assertIsNone(U.in_use())
        self.assertEqual(list((self.root / "updates").iterdir()), [])

    def test_paths_outside_the_folder_are_left_out(self):
        z = self.root / "NemoWin.zip"
        make_zip(z, 2000, real=True)
        with zipfile.ZipFile(z, "a") as zz:
            zz.writestr("NemoWin/../escape.txt", "x")
            zz.writestr("elsewhere.txt", "x")
        dest = U.apply(U.read_zip(z))
        self.assertFalse((self.root / "updates" / "escape.txt").exists())
        self.assertFalse((dest / "elsewhere.txt").exists())


class TestTheImageSide(unittest.TestCase):
    def test_nemodoc_and_the_build_carry_it(self):
        doc = (APP / "install" / "linux" / "nemodoc").read_text(encoding="utf-8")
        self.assertIn("windows_folder Nemo/dist 'NemoWin.zip'", doc)
        self.assertIn("NEMO_UPDATE_ZIP", doc)
        self.assertLess(doc.index("PYTHONPATH"), doc.index('exec "$VENV/bin/nemo" gui --prompt'))
        build = (APP / "install" / "live-build" / "build-iso.sh").read_text(encoding="utf-8")
        self.assertIn('/opt/nemo/COMMIT_TIME"', build)


if __name__ == "__main__":
    unittest.main()
