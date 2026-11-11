"""The Storeroom's drives, space and vault (owner, 2026-10-23): a drive's
files sorted by extension and moved only when asked, checked by hash; the
vault sealed with his passphrase, the companion in only if he allows it.
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

from nemo import drives as D
from nemo import vault as V


class ATemp(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)

    def tearDown(self):
        self.t.cleanup()


class TestSorting(ATemp):
    def test_each_extension_to_its_shelf(self):
        self.assertEqual(D.shelf_for(".MP4"), "videos")
        self.assertEqual(D.shelf_for(".heic"), "pictures")
        self.assertEqual(D.shelf_for(".flac"), "music")
        self.assertEqual(D.shelf_for(".nes"), "games/nes")
        self.assertEqual(D.shelf_for(".bin"), "")                # too many things to guess
        self.assertEqual(D.shelf_for(".docx"), "")

    def test_survey_groups_and_skips_system_folders(self):
        drive = self.root / "drive"
        (drive / "holiday").mkdir(parents=True)
        (drive / "System Volume Information").mkdir()
        (drive / "holiday" / "a.jpg").write_bytes(b"x" * 10)
        (drive / "holiday" / "b.JPG").write_bytes(b"y" * 5)
        (drive / "film.mkv").write_bytes(b"z")
        (drive / "notes.docx").write_bytes(b"d")
        (drive / "System Volume Information" / "x.jpg").write_bytes(b"s")
        groups, cut = D.survey(drive)
        by = {g.ext: g for g in groups}
        self.assertFalse(cut)
        self.assertEqual((len(by[".jpg"].files), by[".jpg"].bytes, by[".jpg"].shelf), (2, 15, "pictures"))
        self.assertEqual(groups[-1].ext, ".docx")                # what has no shelf comes last
        _, cut = D.survey(drive, limit=2)
        self.assertTrue(cut)


class TestMoving(ATemp):
    def test_moved_checked_original_removed_name_kept_apart(self):
        drive, store = self.root / "drive", self.root / "store"
        drive.mkdir()
        (store / "pictures").mkdir(parents=True)
        (store / "pictures" / "a.jpg").write_bytes(b"old")
        (drive / "a.jpg").write_bytes(b"new")
        (drive / "keep.docx").write_bytes(b"d")
        groups, _ = D.survey(drive)
        done = D.move(groups, store)
        self.assertEqual([p.name for p in done.moved], ["a (2).jpg"])
        self.assertEqual((store / "pictures" / "a.jpg").read_bytes(), b"old")   # never overwritten
        self.assertFalse((drive / "a.jpg").exists())
        self.assertTrue((drive / "keep.docx").exists())          # no shelf: stays

    def test_a_bad_copy_keeps_the_original(self):
        drive, store = self.root / "drive", self.root / "store"
        drive.mkdir()
        (drive / "a.mp4").write_bytes(b"film")
        groups, _ = D.survey(drive)
        with mock.patch.object(D, "_sha", side_effect=["one", "two"]):
            done = D.move(groups, store)
        self.assertTrue((drive / "a.mp4").exists())
        self.assertEqual(done.moved, [])
        self.assertFalse((store / "videos" / "a.mp4").exists())

    def test_no_room_moves_nothing(self):
        drive, store = self.root / "drive", self.root / "store"
        drive.mkdir()
        (drive / "a.mp4").write_bytes(b"film")
        groups, _ = D.survey(drive)
        with mock.patch.object(D.shutil, "disk_usage", return_value=mock.Mock(free=1)):
            with self.assertRaises(OSError):
                D.move(groups, store)
        self.assertTrue((drive / "a.mp4").exists())

    def test_space_per_shelf(self):
        (self.root / "videos").mkdir()
        (self.root / "videos" / "a.mp4").write_bytes(b"x" * 100)
        (self.root / "stock.yaml").write_text("x", encoding="utf-8")
        use, free, total = D.space(self.root)
        self.assertEqual((use["videos"], use["other"]), (100, 1))
        self.assertGreater(total, free)

    def test_the_boot_stick_is_never_a_drive(self):
        with mock.patch.object(D, "_windows_drives", return_value=[Path("E:/")]), \
                mock.patch.object(D, "_linux_drives", return_value=[Path("/media/n/E")]), \
                mock.patch.object(D, "_label", return_value="NEMOISO"):
            self.assertEqual(D.drives(), [])


class TestTheVault(ATemp):
    def test_sealed_unreadable_without_the_passphrase(self):
        v = V.create(self.root, "a long passphrase")
        item = v.add_bytes("to my brother.txt", b"Dear brother, private words")
        blob = (V.folder(self.root) / f"{item.id}.nv").read_bytes()
        self.assertNotIn(b"private", blob)
        self.assertNotIn(b"brother", blob)                       # not even the name
        with self.assertRaises(V.VaultError):
            V.unlock(self.root, "wrong passphrase")
        again = V.unlock(self.root, "a long passphrase")
        self.assertEqual(again.read(item.id), b"Dear brother, private words")
        self.assertEqual([i.kind for i in again.items()], ["letter"])

    def test_rules(self):
        with self.assertRaises(V.VaultError):
            V.create(self.root, "short")
        V.create(self.root, "a long passphrase")
        with self.assertRaises(V.VaultError):
            V.create(self.root, "another passphrase")            # never over an existing vault

    def test_adding_a_file_removes_the_original_only_when_asked(self):
        v = V.create(self.root, "a long passphrase")
        f = self.root / "voice.wav"
        f.write_bytes(b"RIFF....")
        v.add_file(f)
        self.assertTrue(f.exists())
        item = v.add_file(f, remove_original=True)
        self.assertFalse(f.exists())
        self.assertEqual(item.kind, "recording")

    def test_plain_copies_go_with_the_lock(self):
        v = V.create(self.root, "a long passphrase")
        item = v.add_bytes("a.txt", b"words")
        copy = v.open_copy(item.id)
        self.assertEqual(copy.read_bytes(), b"words")
        v.lock()
        self.assertFalse(copy.exists())
        with self.assertRaises(V.VaultError):
            v.read(item.id)                                      # the key went with it

    def test_the_companion_only_when_allowed(self):
        v = V.create(self.root, "a long passphrase")
        v.add_bytes("a.txt", b"words")
        v.add_bytes("b.wav", b"sound")
        self.assertEqual(v.letters_for_companion(), [])
        v.allow_companion(True)
        self.assertEqual(v.letters_for_companion(), [("a.txt", "words")])
        v.lock()
        with self.assertRaises(V.VaultError):
            v.allow_companion(False)                             # only with the vault open

    def test_a_damaged_file_is_said(self):
        v = V.create(self.root, "a long passphrase")
        item = v.add_bytes("a.txt", b"words")
        p = V.folder(self.root) / f"{item.id}.nv"
        p.write_bytes(p.read_bytes()[:-1] + b"\0")
        self.assertEqual([i.kind for i in v.items()], ["damaged"])

    def test_the_backup_carries_it_sealed(self):
        from nemo import backup
        v = V.create(self.root, "a long passphrase")
        v.add_bytes("a.txt", b"private words")
        self.assertFalse(backup._left_out(("vault", "x.nv")))


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindows(ATemp):
    def test_storeroom_watcher_and_windows_open_and_close(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with mock.patch.dict(os.environ, _sandbox.home_env(self.t.name)):
            app = A.NemoApp(); app.update()
            try:
                app.cfg.data.setdefault("paths", {})["storeroom"] = str(self.root / "store")
                with mock.patch.object(D, "drives", return_value=[]):
                    store = A.VideoStore(app); app.update()
                    self.assertIsNotNone(store._drive_job)
                    with mock.patch.object(store, "after_cancel", wraps=store.after_cancel) as cancel:
                        store.destroy()
                    cancel.assert_called_once()
                    room = A.DrivesRoom(app); app.update()
                    self.assertIn("No external drive", room.note.cget("text"))
                    room.destroy()
                vr = A.VaultRoom(app); app.update()
                vr.pw.insert(0, "a long passphrase"); vr.open_it(True)
                self.assertIs(app.vault, vr.vault)
                vr.destroy()
                self.assertIsNone(app.vault)                     # locked on close
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()


class TestTheCommands(ATemp):
    def run_cli(self, *argv):
        import io
        from contextlib import redirect_stdout
        from nemo import cli
        out = io.StringIO()
        with mock.patch.dict(os.environ, _sandbox.home_env(self.t.name)), redirect_stdout(out):
            with mock.patch("nemo.config.Config.path", return_value=self.root / "store"):
                code = cli.main(list(argv))
        return code, out.getvalue()

    def test_move_asks_first_then_moves(self):
        drive = self.root / "drive"; drive.mkdir()
        (drive / "a.jpg").write_bytes(b"x")
        code, said = self.run_cli("store", "move", str(drive), "--ext", ".JPG")
        self.assertIn("1 file(s)", said)
        self.assertTrue((drive / "a.jpg").exists())
        code, said = self.run_cli("store", "move", str(drive), "--ext", ".jpg", "--yes")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "store" / "pictures" / "a.jpg").exists())
        self.assertFalse((drive / "a.jpg").exists())

    def test_vault_lists_with_the_passphrase(self):
        V.create(self.root / "store", "a long passphrase").add_bytes("a.txt", b"w")
        with mock.patch("getpass.getpass", return_value="a long passphrase"):
            code, said = self.run_cli("store", "vault")
        self.assertIn("a.txt", said)
        with mock.patch("getpass.getpass", return_value="wrong one"):
            code, said = self.run_cli("store", "vault")
        self.assertEqual(code, 1)
