"""The Music Room, second pass (owner, 2026-10-22): tags read from the
music files, and playlists kept in backups.

The tagged files are built here, byte by byte, to each format's layout. VLC
on the AH531 wrote no tags into what it made (MP3, Ogg, Opus, FLAC, M4A),
though Ogg and Opus carried an empty comment block that the reader read.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import backup, music, tags

MPEG = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(400)        # a frame's start, then silence


def syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def id3v23(**frames) -> bytes:
    body = b"".join(fid.encode() + struct.pack(">I", 1 + len(v.encode("utf-16"))) + b"\0\0"
                    + b"\x01" + v.encode("utf-16") for fid, v in frames.items())
    return b"ID3\x03\x00\x00" + syncsafe(len(body)) + body


def id3v24(**frames) -> bytes:
    body = b"".join(fid.encode() + syncsafe(1 + len(v.encode())) + b"\0\0" + b"\x03" + v.encode()
                    for fid, v in frames.items())
    return b"ID3\x04\x00\x00" + syncsafe(len(body)) + body


def id3v1(title, artist, album, track) -> bytes:
    f = lambda s: s.encode("latin-1").ljust(30, b"\0")   # noqa: E731
    return b"TAG" + f(title) + f(artist) + f(album) + b"2026" + bytes(28) + b"\0" + bytes([track]) + b"\xff"


def vorbis(**c) -> bytes:
    vendor = b"Nemo test"
    entries = [f"{k}={v}".encode() for k, v in c.items()]
    return (struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(entries))
            + b"".join(struct.pack("<I", len(e)) + e for e in entries))


def flac(**c) -> bytes:
    streaminfo = b"\x00" + (34).to_bytes(3, "big") + bytes(34)
    block = vorbis(**c)
    return b"fLaC" + streaminfo + bytes([0x84]) + len(block).to_bytes(3, "big") + block


def ogg_pages(packet: bytes, page_max: int = 255 * 3) -> bytes:
    """An Ogg stream carrying `packet` over as many pages as it takes."""
    out, seq = b"", 0
    for start in range(0, len(packet), page_max):
        chunk = packet[start:start + page_max]
        lacing = [255] * (len(chunk) // 255) + [len(chunk) % 255]
        out += (b"OggS\0" + (b"\x01" if start else b"\0") + bytes(8) + b"\1\0\0\0"
                + struct.pack("<I", seq) + bytes(4) + bytes([len(lacing)]) + bytes(lacing) + chunk)
        seq += 1
    return out


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def m4a() -> bytes:
    """An M4A whose moov/udta/meta/ilst holds a title, artist, album and
    track 2 of 9, as iTunes-style taggers write them."""
    def item(kind: bytes, value: bytes) -> bytes:
        return box(kind, box(b"data", b"\0\0\0\x01" + b"\0\0\0\0" + value))
    ilst = (item(b"\xa9nam", b"Rain") + item(b"\xa9ART", b"Cloud") + item(b"\xa9alb", b"Weather")
            + item(b"trkn", b"\0\0\0\x02\0\x09\0\0"))
    meta = box(b"meta", b"\0\0\0\0" + box(b"hdlr", bytes(25)) + box(b"ilst", ilst))
    return box(b"ftyp", b"M4A \0\0\0\0") + box(b"moov", box(b"udta", meta)) + box(b"mdat", bytes(64))


class AFolder(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)

    def tearDown(self):
        self.t.cleanup()

    def write(self, name: str, data: bytes) -> Path:
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p


class TestReadingTags(AFolder):
    def test_mp3_id3v2_3_in_utf16(self):
        p = self.write("a.mp3", id3v23(TIT2="Sunrise", TPE1="Ana Lí", TALB="Dawn", TRCK="3/12") + MPEG)
        self.assertEqual(tags.read(p), {"title": "Sunrise", "artist": "Ana Lí", "album": "Dawn",
                                        "number": 3})

    def test_mp3_id3v2_4_in_utf8(self):
        p = self.write("b.mp3", id3v24(TIT2="Ünder", TPE1="Band") + MPEG)
        self.assertEqual(tags.read(p), {"title": "Ünder", "artist": "Band"})

    def test_mp3_id3v1_at_the_end_fills_what_v2_lacks(self):
        p = self.write("c.mp3", id3v24(TIT2="From v2") + MPEG + id3v1("v1 title", "Old Artist", "Old Album", 7))
        self.assertEqual(tags.read(p), {"title": "From v2", "artist": "Old Artist",
                                        "album": "Old Album", "number": 7})

    def test_flac(self):
        p = self.write("d.flac", flac(TITLE="Low Tide", ARTIST="Sea", album="Shore", TRACKNUMBER="05"))
        self.assertEqual(tags.read(p), {"title": "Low Tide", "artist": "Sea", "album": "Shore",
                                        "number": 5})

    def test_ogg_vorbis_and_opus_over_several_pages(self):
        long_ = "x" * 900                                       # forces the packet over pages
        p = self.write("e.ogg", ogg_pages(b"\x03vorbis" + vorbis(COMMENT=long_, TITLE="Pages",
                                                                  ARTIST="Ogg")))
        self.assertEqual(tags.read(p), {"title": "Pages", "artist": "Ogg"})
        p = self.write("f.opus", ogg_pages(b"OpusTags" + vorbis(TITLE="Op", ALBUM="Us")))
        self.assertEqual(tags.read(p), {"title": "Op", "album": "Us"})

    def test_m4a(self):
        p = self.write("g.m4a", m4a())
        self.assertEqual(tags.read(p), {"title": "Rain", "artist": "Cloud", "album": "Weather",
                                        "number": 2})

    def test_no_tags_and_broken_files_give_nothing(self):
        self.assertEqual(tags.read(self.write("h.mp3", MPEG)), {})
        self.assertEqual(tags.read(self.write("i.flac", b"fLaC" + b"\x80\x00\x00\x22" + bytes(34))), {})
        self.assertEqual(tags.read(self.write("j.mp3", b"ID3\x03\x00\x00\x7f\x7f\x7f\x7f" + bytes(20))), {})
        self.assertEqual(tags.read(self.write("k.ogg", b"OggS" + bytes(10))), {})
        self.assertEqual(tags.read(self.write("l.wma", b"anything")), {})
        self.assertEqual(tags.read(self.root / "missing.mp3"), {})


class TestTheMusicRoom(AFolder):
    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.root))
        self._env.start()
        self._cfg_home = mock.patch("nemo.config.CONFIG_HOME", self.root / ".nemo")
        self._cfg_home.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def tearDown(self):
        self._cfg_home.stop(); self._env.stop()
        super().tearDown()

    def shelf(self, rel: str, data: bytes) -> Path:
        return self.write(str(Path("nemo-storeroom") / "music" / rel), data)

    def test_tags_first_folders_where_there_are_none(self):
        self.shelf("loose/02 b.mp3", id3v24(TIT2="Second", TPE1="Band", TALB="Album", TRCK="2") + MPEG)
        self.shelf("loose/01 a.mp3", id3v24(TIT2="First", TPE1="Band", TALB="Album", TRCK="10") + MPEG)
        self.shelf("Folder Artist/Folder Album/untagged.mp3", MPEG)
        found = music.tracks(self.cfg)
        self.assertEqual([(t.artist, t.album, t.title, t.number) for t in found],
                         [("Band", "Album", "Second", 2), ("Band", "Album", "First", 10),
                          ("Folder Artist", "Folder Album", "untagged", 0)])
        self.assertEqual([t.title for t in music.find(found, "02 b")], ["Second"])

    def test_the_cache_is_used_until_the_file_changes(self):
        p = self.shelf("x.mp3", id3v24(TIT2="Before") + MPEG)
        self.assertEqual(music.tracks(self.cfg)[0].title, "Before")
        with mock.patch("nemo.tags.read", side_effect=AssertionError("read again")):
            self.assertEqual(music.tracks(self.cfg)[0].title, "Before")
        p.write_bytes(id3v24(TIT2="After, longer") + MPEG)              # a new size
        self.assertEqual(music.tracks(self.cfg)[0].title, "After, longer")

    def test_backups_keep_playlists_not_music(self):
        t = self.shelf("Band/Album/song.mp3", MPEG)
        music.save_playlist(self.cfg, "Evening", [music.Track("song", "Band", "Album", t)])
        made = backup.make(self.cfg, self.root / "backups")
        names = zipfile.ZipFile(made.path).namelist()
        self.assertIn("storeroom/music/Evening.m3u", names)
        self.assertFalse([n for n in names if n.endswith(".mp3")], names)


class TestTheRule(unittest.TestCase):
    def test_only_a_playlist_at_the_top_of_the_music_shelf(self):
        L = backup._left_out
        self.assertFalse(L(("music", "Evening.m3u")))
        self.assertTrue(L(("music", "Band", "list.m3u")))       # inside the music: stays out
        self.assertTrue(L(("music", "song.mp3")))
        self.assertTrue(L(("videos", "a.m3u")))
        self.assertTrue(L(("audio", "books", "x.wav")))
        self.assertFalse(L(("audio", "recordings", "x.wav")))
        self.assertFalse(L(("stock.yaml",)))


if __name__ == "__main__":
    unittest.main()
