"""The Projectionist's codec check (owner, 2026-10-22): what is inside a
video, and whether a Chromecast plays it, by Google's list.

tests/data/vlc-h264-640x480.mp4 is a real file: VLC 3.0.24 made it on the
AH531 from Nemo's cog picture (2 s, H.264 High, no sound).
"""
from __future__ import annotations

import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import mediainfo, theatre

REAL = Path(__file__).resolve().parent / "data" / "vlc-h264-640x480.mp4"


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def video_entry(fourcc: bytes, w: int, h: int, codec_box: bytes) -> bytes:
    # 78 bytes after the box header before the codec's own box (ISO 14496-12)
    fixed = (b"\0" * 6 + b"\0\x01" + b"\0" * 16 + struct.pack(">HH", w, h)
             + b"\0" * (78 - 28))
    return box(fourcc, fixed + codec_box)


def trak(handler: bytes, entry: bytes) -> bytes:
    stsd = box(b"stsd", b"\0\0\0\0" + struct.pack(">I", 1) + entry)
    hdlr = box(b"hdlr", b"\0" * 8 + handler + b"\0" * 12)
    return box(b"trak", box(b"mdia", hdlr + box(b"minf", box(b"stbl", stsd))))


def avc(profile: int, level: int) -> bytes:
    return box(b"avcC", bytes([1, profile, 0, level]) + b"\xff\xe1")


def hvc(level: float) -> bytes:
    return box(b"hvcC", bytes([1, 1]) + b"\0" * 10 + bytes([round(level * 30)]) + b"\0" * 10)


def sound(fourcc: bytes) -> bytes:
    return trak(b"soun", box(fourcc, b"\0" * 28))


def mp4(path: Path, *traks: bytes, big_first: bool = False) -> Path:
    moov = box(b"moov", b"".join(traks))
    ftyp = box(b"ftyp", b"isom\0\0\0\0isom")
    # A 64-bit sized mdat first, as a long film written moov-last has.
    mdat = struct.pack(">I", 1) + b"mdat" + struct.pack(">Q", 16 + 100) + b"\0" * 100
    path.write_bytes(ftyp + (mdat + moov if big_first else moov + mdat))
    return path


class AFolder(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)


class TestReadingFiles(AFolder):
    def test_a_real_file_made_by_vlc(self):
        m = mediainfo.probe(REAL)
        self.assertEqual((m.container, m.video, m.profile, m.level, m.size, m.sound),
                         ("MP4", "h264", "High", 22, (640, 480), []))

    def test_h264_with_its_sound_and_the_moov_last(self):
        p = mp4(self.t / "a.mp4", trak(b"vide", video_entry(b"avc1", 1920, 1080, avc(100, 42))),
                sound(b"mp4a"), big_first=True)
        m = mediainfo.probe(p)
        self.assertEqual((m.video, m.profile, m.level, m.size, m.sound),
                         ("h264", "High", 42, (1920, 1080), ["aac"]))

    def test_h265_and_dolby_sound(self):
        p = mp4(self.t / "b.mp4", trak(b"vide", video_entry(b"hvc1", 3840, 2160, hvc(5.1))),
                sound(b"ac-3"))
        m = mediainfo.probe(p)
        self.assertEqual((m.video, m.profile, m.level, m.sound), ("hevc", "Main", 51, ["ac3"]))

    def test_matroska_codec_names(self):
        head = (b"\x1a\x45\xdf\xa3" + b"\x42\x82\x84webm" + b"\x00" * 20
                + b"\x86\x85V_VP9" + b"\x00" * 9 + b"\x86\x86A_OPUS" + b"\x00" * 9)
        (self.t / "c.webm").write_bytes(head)
        m = mediainfo.probe(self.t / "c.webm")
        self.assertEqual((m.container, m.video, m.sound), ("WebM", "vp9", ["opus"]))

    def test_what_is_not_a_video(self):
        (self.t / "x.mp4").write_bytes(b"not a film at all")
        with self.assertRaises(mediainfo.MediaError):
            mediainfo.probe(self.t / "x.mp4")
        with self.assertRaises(mediainfo.MediaError):
            mediainfo.probe(self.t / "x.avi")


class TestWillItPlay(unittest.TestCase):
    def M(self, video, level=None, sound=("aac",), container="MP4"):
        return mediainfo.Media(container, video, "High", level, (1920, 1080), list(sound))

    def test_every_chromecast(self):
        ok, lines = mediainfo.verdict(self.M("h264", 41))
        self.assertTrue(ok)
        self.assertIn("Plays on every Chromecast.", lines)
        self.assertTrue(mediainfo.verdict(self.M("vp8"))[0])

    def test_newer_ones_only(self):
        ok, lines = mediainfo.verdict(self.M("hevc", 51))
        self.assertIsNone(ok)
        self.assertIn("Plays only on: Chromecast Ultra, Chromecast with Google TV, "
                      "Google TV Streamer.", lines)
        self.assertEqual(mediainfo.verdict(self.M("av1"))[1][-1], "Plays only on: Google TV Streamer.")

    def test_for_the_model_in_hand(self):
        ok, lines = mediainfo.verdict(self.M("hevc", 51), "Chromecast")
        self.assertFalse(ok)
        self.assertIn("Will not play on a Chromecast.", lines)
        self.assertTrue(mediainfo.verdict(self.M("hevc", 51), "Chromecast Ultra")[0])
        self.assertTrue(mediainfo.verdict(self.M("h264", 52), "Google TV Streamer")[0])
        self.assertFalse(mediainfo.verdict(self.M("h264", 52), "Chromecast with Google TV")[0])

    def test_a_plain_chromecast_may_be_the_third_generation(self):
        # Level 4.2 plays on a 3rd gen, not a 1st; the name does not say which.
        self.assertIsNone(mediainfo.verdict(self.M("h264", 42), "Chromecast")[0])

    def test_a_level_not_read_is_not_promised(self):
        ok, lines = mediainfo.verdict(self.M("h264", None, container="WebM"))
        self.assertIsNone(ok)
        self.assertIn("level is not read", " ".join(lines))

    def test_dolby_sound_may_be_silent(self):
        ok, lines = mediainfo.verdict(self.M("h264", 40, sound=("ac3",)))
        self.assertIsNone(ok)
        self.assertIn("may be silent", lines[-1])

    def test_nemo_does_not_cast_matroska(self):
        ok, lines = mediainfo.verdict(self.M("h264", 40, container="Matroska"))
        self.assertFalse(ok)
        self.assertIn("converts nothing", lines[-1])


class TestTheProjectionist(AFolder):
    def test_a_video_is_looked_inside_a_picture_is_not(self):
        v = theatre.Item("film.mp4", mp4(self.t / "film.mp4", trak(
            b"vide", video_entry(b"hvc1", 3840, 2160, hvc(5.1)))), "video", "Storeroom")
        ok, lines = theatre.check(v, "Chromecast")
        self.assertFalse(ok)
        self.assertIn("H.265 (HEVC) Main, level 5.1", lines[0])
        self.assertEqual(theatre.check(theatre.Item("a.png", self.t / "a.png", "photo", "x")),
                         (True, []))
        broken = theatre.Item("b.mp4", self.t / "nothing.mp4", "video", "Storeroom")
        self.assertIsNone(theatre.check(broken)[0])

    def test_the_window_warns_and_still_casts(self):
        if not _sandbox.has_display():
            self.skipTest("no display")
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        film = mp4(self.t / "film.mp4", trak(b"vide", video_entry(b"hvc1", 3840, 2160, hvc(5.1))))
        app = A.NemoApp(); app.update()
        try:
            w = A.Theatre(app); app.update()
            item = theatre.Item("film.mp4", film, "video", "Storeroom")
            device = mock.Mock()
            device.cast_info.friendly_name, device.cast_info.model_name = "Family Room TV", "Chromecast"
            w.devices = [device]
            w.device_box.config(values=["Family Room TV"]); w.device_box.set("Family Room TV")
            with mock.patch.object(w, "chosen", return_value=item), \
                 mock.patch.object(w.cast, "Session") as session, \
                 mock.patch.object(w, "_watch_cast"):
                w.cast_it()
            session.assert_called_once()
            self.assertIn("Will not play on a Chromecast", w.note.cget("text"))
            w.session = None
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
