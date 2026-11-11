"""The Music Room (owner, 2026-10-21): the shelf, playlists, playing here,
and the DJ's cast queue (with a stand-in Chromecast; the web server that
lends each track is real).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import cast, music, staff, videostore


class AShelf(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        self.shelf = self.t / "nemo-storeroom" / "music"
        for rel in ("Band/First album/01 Opening.mp3", "Band/First album/02 Second.flac",
                    "Solo/Loose track.wav", "Odd.wma", "notes.txt"):
            p = self.shelf / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * 64)

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.t, ignore_errors=True)


class TestTheShelf(AShelf):
    def test_tracks_by_artist_and_album(self):
        got = [(t.artist, t.album, t.title) for t in music.tracks(self.cfg)]
        # A file name's track number is not its title (2026-11-06).
        self.assertEqual(got, [("", "", "Odd"), ("Band", "First album", "Opening"),
                               ("Band", "First album", "Second"), ("Solo", "", "Loose track")])
        self.assertFalse(music.tracks(self.cfg)[0].castable)          # .wma
        self.assertEqual(len(music.find(music.tracks(self.cfg), "band")), 2)

    def test_a_track_is_found_by_its_name_without_its_number(self):
        # 2026-11-06: `music save "Test List" "Low Tone"` found no "01 Low Tone".
        self.assertEqual(music.numbered("01 Low Tone"), (1, "Low Tone"))
        self.assertEqual(music.numbered("2. High Tone"), (2, "High Tone"))
        self.assertEqual(music.numbered("03 - Third"), (3, "Third"))
        self.assertEqual(music.numbered("1984"), (0, "1984"))
        ts = music.tracks(self.cfg)
        self.assertEqual([t.path.name for t in music.find(ts, "Opening")], ["01 Opening.mp3"])
        self.assertEqual([t.number for t in ts if t.artist == "Band"], [1, 2])

    def test_playlists_round_trip_and_skip_what_is_gone(self):
        ts = music.tracks(self.cfg)
        p = music.save_playlist(self.cfg, "Evening", [ts[2], ts[1]])
        self.assertEqual(p.read_text(encoding="utf-8").splitlines(),
                         ["#EXTM3U", "Band/First album/02 Second.flac",
                          "Band/First album/01 Opening.mp3"])
        (self.shelf / "Band/First album/01 Opening.mp3").unlink()
        self.assertEqual([t.title for t in music.load_playlist(self.cfg, p)], ["Second"])
        with self.assertRaises(ValueError):
            music.save_playlist(self.cfg, "  ", ts)

    def test_played_here_in_order(self):
        ts = music.tracks(self.cfg)[1:3]
        with mock.patch("nemo.theatre.player", return_value="vlc"), \
             mock.patch.object(music.subprocess, "Popen") as popen:
            self.assertEqual(music.play_here(ts), "VLC")
        self.assertEqual(popen.call_args[0][0], ["vlc", str(ts[0].path), str(ts[1].path)])

    def test_the_store_s_music_aisle(self):
        cases = videostore.shelves(self.cfg)["MUSIC"]
        self.assertEqual([c.title for c in cases][:2], ["Odd", "Opening"])
        self.assertEqual(cases[0].actions, ("Play here",))
        self.assertEqual(cases[1].actions, ("Play here", "Cast..."))

    def test_the_team(self):
        self.assertEqual([e.title for e in staff.team("music")], ["Player", "DJ", "Writer"])


class TestTheDJ(AShelf):
    def device(self):
        d = mock.Mock()
        d.cast_info.host = "127.0.0.1"
        d.status.app_id = cast.DEFAULT_RECEIVER
        return d

    def wait_for(self, cond, secs=5):
        import time
        end = time.time() + secs
        while time.time() < end and not cond():
            time.sleep(0.02)
        return cond()

    def test_one_after_another_then_let_go(self):
        ts = [t.path for t in music.tracks(self.cfg)]         # the .wma is left out
        d = self.device()
        q = cast.Queue(d, ts)
        self.assertEqual(len(q.paths), 3)
        first_url = d.media_controller.play_media.call_args[0][0]
        self.assertEqual(d.media_controller.play_media.call_args[0][1], "audio/mpeg")
        q.new_media_status(mock.Mock(player_state="IDLE", idle_reason="FINISHED"))
        self.assertTrue(self.wait_for(lambda: q.index == 1))
        with self.assertRaises(OSError):                      # the first is no longer lent
            urllib.request.urlopen(first_url, timeout=3)
        q.new_media_status(mock.Mock(player_state="IDLE", idle_reason="FINISHED"))
        self.assertTrue(self.wait_for(lambda: q.index == 2))
        q.new_media_status(mock.Mock(player_state="IDLE", idle_reason="FINISHED"))
        self.assertTrue(self.wait_for(lambda: q.released))
        self.assertEqual(q.ended, "FINISHED")
        d.quit_app.assert_called_once()
        d.disconnect.assert_called_once()

    def test_the_next_is_said_only_once_the_last_is_let_go(self):
        # D200: the index moved first, so a check of the old address
        # could still reach it. Seen once in a full suite.
        ts = [t.path for t in music.tracks(self.cfg)]
        q = cast.Queue(self.device(), ts)
        seen = []
        real_stop = cast.Lender.stop
        with mock.patch.object(cast.Lender, "stop", autospec=True,
                               side_effect=lambda lender: (seen.append(q.index), real_stop(lender))):
            q.next()
        self.assertEqual(seen[0], 0)
        self.assertEqual(q.index, 1)
        q.release()

    def test_stop_and_someone_else(self):
        ts = [t.path for t in music.tracks(self.cfg)]
        d = self.device()
        q = cast.Queue(d, ts)
        q.stop()
        d.quit_app.assert_called_once()
        d2 = self.device()
        q2 = cast.Queue(d2, ts)
        q2.new_media_status(mock.Mock(player_state="IDLE", idle_reason="INTERRUPTED"))
        self.assertTrue(self.wait_for(lambda: q2.released))
        d2.quit_app.assert_not_called()

    def test_nothing_castable(self):
        with self.assertRaises(cast.CastError):
            cast.Queue(self.device(), [self.shelf / "Odd.wma"])


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AShelf):
    def test_list_choose_and_save(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        app = A.NemoApp(); app.update()
        try:
            w = A.MusicRoom(app); app.update()
            self.assertEqual(len(w.tree.get_children()), 4)
            w.tree.selection_set(("1", "2")); w.pl_name.set("Mine"); w.save_playlist()
            self.assertIn("saved Mine.m3u with 2 track(s)", w.note.cget("text"))
            w.tree.selection_set(()); w.load_playlist()
            self.assertEqual(set(w.tree.selection()), {"1", "2"})
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
