"""The Theatre (owner, 2026-10-21): video, streaming and photos, here or on
a Chromecast. The web server that lends a file is tested for real, on this
computer; the Chromecast is a stand-in (no real one is cast to here).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import cast, staff, storeroom, theatre

BODY = bytes(range(256)) * 40          # 10240 bytes


def fetch(url: str, rng: str = "") -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers={"Range": rng} if rng else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        e.close()
        return e.code, b"", dict(e.headers)


class AFile(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.file = Path(self.t.name) / "holiday film.mp4"
        self.file.write_bytes(BODY)
        self.secret = Path(self.t.name) / "secret.txt"
        self.secret.write_text("not to be lent", encoding="utf-8")

    def tearDown(self):
        self.t.cleanup()


class TestTheLender(AFile):
    def setUp(self):
        super().setUp()
        self.lender = cast.Lender(self.file)
        self.addCleanup(self.lender.stop)
        self.url = self.lender.url("127.0.0.1")

    def test_the_whole_file(self):
        code, body, head = fetch(self.url)
        self.assertEqual((code, body), (200, BODY))
        self.assertEqual(head["Content-Type"], "video/mp4")
        self.assertEqual(head["Accept-Ranges"], "bytes")

    def test_a_range_as_a_chromecast_seeks(self):
        code, body, head = fetch(self.url, "bytes=100-199")
        self.assertEqual((code, body), (206, BODY[100:200]))
        self.assertEqual(head["Content-Range"], f"bytes 100-199/{len(BODY)}")
        self.assertEqual(fetch(self.url, "bytes=10000-")[1], BODY[10000:])
        self.assertEqual(fetch(self.url, "bytes=-40")[1], BODY[-40:])
        self.assertEqual(fetch(self.url, f"bytes={len(BODY)}-")[0], 416)

    def test_it_lends_that_file_and_nothing_else(self):
        base = f"http://127.0.0.1:{self.lender.port}"
        for path in ("/", f"/{self.lender.token}/", f"/{self.lender.token}/secret.txt",
                     "/holiday%20film.mp4", f"/{self.lender.token}/../secret.txt",
                     f"/wrong/{urllib.parse.quote(self.file.name)}"):
            self.assertEqual(fetch(base + path)[0], 404, path)
        self.assertGreaterEqual(len(self.lender.token), 16)
        self.assertNotEqual(self.lender.token, cast.Lender(self.file).token)

    def test_it_stops(self):
        self.lender.stop()
        with self.assertRaises(OSError):
            urllib.request.urlopen(self.url, timeout=3)
        self.lender.stop()                        # again: harmless (and the cleanup's third)


class TestCasting(AFile):
    def device(self):
        d = mock.Mock()
        d.cast_info.host = "127.0.0.1"
        d.cast_info.friendly_name = "Front room"
        return d

    def test_what_a_chromecast_plays(self):
        for name, ok in (("a.mp4", True), ("a.WEBM", True), ("a.jpg", True), ("a.png", True),
                         ("a.mkv", False), ("a.avi", False), ("a.txt", False)):
            self.assertEqual(cast.castable(Path(name)) is not None, ok, name)

    def test_a_session_lends_the_file_and_tells_the_chromecast(self):
        d = self.device()
        s = cast.Session(d, self.file)
        url, mime = d.media_controller.play_media.call_args[0]
        self.assertEqual(mime, "video/mp4")
        self.assertEqual(d.media_controller.play_media.call_args[1]["stream_type"], "BUFFERED")
        self.assertEqual(fetch(url)[1], BODY)            # what the Chromecast would fetch
        s.pause(); s.resume(); s.stop()
        d.media_controller.pause.assert_called_once()
        d.media_controller.stop.assert_called_once()
        with self.assertRaises(OSError):
            urllib.request.urlopen(url, timeout=3)

    def test_a_file_it_cannot_play_is_refused_before_anything_starts(self):
        mkv = self.file.with_suffix(".mkv"); mkv.write_bytes(BODY)
        with mock.patch.object(cast, "Lender") as lender:
            with self.assertRaises(cast.CastError) as cm:
                cast.Session(self.device(), mkv)
        lender.assert_not_called()
        self.assertIn(".mkv", str(cm.exception))

    def test_a_chromecast_that_will_not_take_it_leaves_no_server(self):
        d = self.device()
        d.media_controller.block_until_active.side_effect = TimeoutError("no answer")
        with mock.patch.object(cast.Lender, "stop", autospec=True) as stop:
            with self.assertRaises(cast.CastError):
                cast.Session(d, self.file)
        stop.assert_called_once()

    def test_stop_lets_the_chromecast_go(self):
        # D199: after Stop the Chromecast still ran the cast app and Nemo
        # stayed connected (Family Room TV, 2026-10-21).
        d = self.device()
        d.status.app_id = cast.DEFAULT_RECEIVER
        s = cast.Session(d, self.file)
        s.stop()
        d.quit_app.assert_called_once()
        d.disconnect.assert_called_once()
        self.assertTrue(s.released)
        s.stop()                                   # again: nothing more is sent
        d.quit_app.assert_called_once()

    def test_another_s_app_is_never_closed(self):
        d = self.device()
        d.status.app_id = "SOMEONE-ELSE"
        cast.Session(d, self.file).stop()
        d.quit_app.assert_not_called()
        d.disconnect.assert_called_once()

    def test_a_video_that_ends_lets_it_go_by_itself(self):
        import threading
        d = self.device()
        d.status.app_id = cast.DEFAULT_RECEIVER
        ended = threading.Event()
        s = cast.Session(d, self.file, on_end=lambda s: ended.set())
        s.new_media_status(mock.Mock(player_state="PLAYING", idle_reason=None))
        self.assertFalse(s.released)
        s.new_media_status(mock.Mock(player_state="IDLE", idle_reason="FINISHED"))
        self.assertTrue(ended.wait(5))
        self.assertEqual(s.ended, "FINISHED")
        d.quit_app.assert_called_once()
        with self.assertRaises(OSError):            # the file is no longer lent
            urllib.request.urlopen(s.lender.url("127.0.0.1"), timeout=3)

    def test_someone_else_taking_over_is_left_alone(self):
        import threading
        d = self.device()
        d.status.app_id = cast.DEFAULT_RECEIVER
        ended = threading.Event()
        s = cast.Session(d, self.file, on_end=lambda s: ended.set())
        s.new_media_status(mock.Mock(player_state="IDLE", idle_reason="INTERRUPTED"))
        self.assertTrue(ended.wait(5))
        d.quit_app.assert_not_called()             # their cast keeps playing
        d.disconnect.assert_called_once()

    def test_finding_them_binds_each_to_its_address(self):
        # The first real cast (Family Room TV, 2026-10-21) never connected: a found
        # Chromecast connects through discovery, which find() then stops.
        a, b = self.device(), self.device()
        a.cast_info.friendly_name, b.cast_info.friendly_name = "Kitchen", "Family Room TV"
        a.cast_info.host, b.cast_info.host = "192.168.50.5", "192.168.50.6"
        a.cast_info.port = b.cast_info.port = 8009
        calls = []
        fake = mock.Mock()
        fake.get_chromecasts.return_value = ([a, b], "browser")
        fake.models.HostServiceInfo = lambda host, port: ("host", host, port)
        fake.models.CastInfo = lambda services, uuid, model, name, host, port, kind, maker: \
            mock.Mock(services=services, friendly_name=name, host=host)

        def bound(info, zconf):
            calls.append(("bound", info.friendly_name, zconf))
            return mock.Mock(cast_info=info)
        fake.get_chromecast_from_cast_info.side_effect = bound
        fake.discovery.stop_discovery.side_effect = lambda br: calls.append(("stopped", br))
        with mock.patch.dict(sys.modules, {"pychromecast": fake,
                                           "pychromecast.models": fake.models}):
            found = cast.find(timeout=1)
        self.assertEqual([d.cast_info.friendly_name for d in found], ["Family Room TV", "Kitchen"])
        self.assertEqual(found[0].cast_info.services, {("host", "192.168.50.6", 8009)})
        self.assertEqual(calls, [("bound", "Kitchen", None), ("bound", "Family Room TV", None),
                                 ("stopped", "browser")])

    def test_the_address_on_the_way_to_it(self):
        self.assertEqual(cast.address_towards("127.0.0.1"), "127.0.0.1")


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.home))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        storeroom.make_shelves(self.cfg.path("paths.storeroom"))
        self.shelf = self.cfg.path("paths.storeroom")

    def tearDown(self):
        self._env.stop(); self.t.cleanup()

    def put(self, rel: str) -> Path:
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p


class TestWhatIsShowing(AHome):
    def test_each_employee_has_its_own(self):
        self.put("nemo-storeroom/videos/Film.mp4")
        self.put("nemo-storeroom/videos/old/Tape.avi")
        self.put("nemo-storeroom/videos/notes.txt")
        self.put("nemo-storeroom/pictures/Beach.jpg")
        self.put("nemo-stories/fox/cover.png")
        self.put("nemo-projects/lamp/concept/a.png")
        self.assertEqual([i.name for i in theatre.videos(self.cfg)], ["Film.mp4", "Tape.avi"])
        photos = theatre.photos(self.cfg)
        self.assertEqual([(i.name, i.source) for i in photos],
                         [("Beach.jpg", "Storeroom"), ("fox (cover)", "story cover"),
                          ("lamp: a", "concept")])
        self.assertEqual(theatre.find(photos, "beach").name, "Beach.jpg")
        self.assertFalse(theatre.videos(self.cfg)[1].castable)

    def test_playing_here(self):
        item = theatre.Item("Film.mp4", self.put("nemo-storeroom/videos/Film.mp4"), "video",
                            "Storeroom")
        with mock.patch.object(theatre, "player", return_value="vlc"), \
             mock.patch.object(theatre.subprocess, "Popen") as popen:
            self.assertEqual(theatre.play_here(item), "VLC")
        self.assertEqual(popen.call_args[0][0], ["vlc", str(item.path)])

    def test_the_streamer_opens_chrome(self):
        with mock.patch.object(theatre, "browser", return_value="C:/x/chrome.exe"), \
             mock.patch.object(theatre.subprocess, "Popen") as popen:
            self.assertEqual(theatre.stream("www.bbc.co.uk/iplayer"), "chrome")
            theatre.stream()
        self.assertEqual(popen.call_args_list[0][0][0],
                         ["C:/x/chrome.exe", "https://www.bbc.co.uk/iplayer"])
        self.assertEqual(popen.call_args_list[1][0][0], ["C:/x/chrome.exe"])
        with mock.patch.object(theatre, "browser", return_value=None):
            with self.assertRaises(RuntimeError):
                theatre.stream()


class TestTheTeam(unittest.TestCase):
    def test_video_streaming_photo(self):
        self.assertEqual([e.title for e in staff.team("theatre")],
                         ["Projectionist", "Streamer", "Photo Curator", "Writer"])
        self.assertIn("Video", staff.STAFF["theatre.projectionist"].job)
        self.assertIn("Streaming", staff.STAFF["theatre.streamer"].job)
        self.assertIn("Photos", staff.STAFF["theatre.curator"].job)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_find_cast_and_close(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.put("nemo-storeroom/pictures/Beach.jpg")
        app = A.NemoApp(); app.update()
        try:
            w = A.Theatre(app); app.update()
            self.assertEqual(w.tree.item("0", "values")[1], "Beach.jpg")
            d = mock.Mock(); d.cast_info.friendly_name = "Family Room TV"
            w.found({"found": [d]})
            self.assertEqual(str(w.btn_cast.cget("state")), "normal")
            w.tree.selection_set("0")
            with mock.patch.object(A, "Theatre", A.Theatre), \
                 mock.patch("nemo.cast.Session") as session:
                session.return_value.released = False
                w.cast_it()
            session.assert_called_once_with(d, self.shelf / "pictures" / "Beach.jpg")
            self.assertIn("Casting Beach.jpg to Family Room TV", w.note.cget("text"))
            w.destroy(); app.update()
            session.return_value.stop.assert_called_once()     # closing stops the cast
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
