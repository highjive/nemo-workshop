"""The Audio department (owner, 2026-10-21): the Narrator, the Recorder, the
Sound Engineer, the listening shelf and its remembered places.
"""
from __future__ import annotations

import os
import shutil
import struct
import sys
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import audio, backup, staff, videostore, voice


def tone(path: Path, rate: int = 22050, secs: float = 0.2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * secs))
    return path


def mp3(path: Path, header: bytes = b"\xff\xfb\x90\x00") -> Path:
    """A file whose first frame header says MPEG-1 layer III, 44.1 kHz."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x0a" + b"\x00" * 10 + header + b"\x00" * 200)
    return path


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        self.shelf = self.t / "nemo-storeroom" / "audio"

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.t, ignore_errors=True)


class TestTheNarrator(AHome):
    def story(self):
        st = self.t / "nemo-stories" / "the-keeper"
        (st / "chapters").mkdir(parents=True)
        (st / "chapters" / "01-light.md").write_text(
            "## 1. The Light\n\nThe keeper climbed **the** stair.", encoding="utf-8")
        (st / "chapters" / "02-ship.md").write_text("## 2. The Ship\n\nA ship came.", encoding="utf-8")
        return st

    def test_the_words_it_reads(self):
        self.assertEqual(audio._plain("## 3. Rain\n\nIt *rained*."), "Chapter 3. Rain\n\nIt rained.")
        parts = audio._chunks(("word " * 300 + ".\n\n") * 6)
        self.assertTrue(all(len(p) <= audio.CHUNK for p in parts))
        self.assertGreater(len(parts), 1)

    def test_a_chapter_per_file_and_a_titled_playlist(self):
        def fake_speak(text, wav=None, wait=False, whole=False):
            self.assertTrue(whole)
            tone(Path(wav))
            return True, ""
        with mock.patch.object(voice, "speak", side_effect=fake_speak):
            book = audio.narrate(self.cfg, self.story(), say=lambda s: None)
        self.assertEqual(sorted(p.name for p in book.glob("*.wav")),
                         ["01 The Light.wav", "02 The Ship.wav"])
        self.assertIn("#EXTINF:0,1. The Light", (book / "the-keeper.m3u").read_text(encoding="utf-8"))
        self.assertEqual([l.title for l in audio.listening(self.cfg)],
                         ["the-keeper: 01 The Light", "the-keeper: 02 The Ship"])

    def test_no_chapters(self):
        empty = self.t / "nemo-stories" / "none"; empty.mkdir(parents=True)
        with self.assertRaises(ValueError):
            audio.narrate(self.cfg, empty)

    @unittest.skipUnless(voice.engine()[0], "no voice on this machine")
    def test_a_real_voice_reads_it(self):
        book = audio.narrate(self.cfg, self.story(), say=lambda s: None)
        with wave.open(str(next(book.glob("01*.wav")))) as w:
            self.assertGreater(w.getnframes() / w.getframerate(), 1.0)


class TestTheSoundEngineer(AHome):
    def test_rates_from_the_files_own_headers(self):
        self.assertEqual(audio.sample_rate(tone(self.t / "a.wav", 16000)), 16000)
        self.assertEqual(audio.sample_rate(mp3(self.t / "b.mp3")), 44100)
        self.assertEqual(audio.sample_rate(mp3(self.t / "c.mp3", b"\xff\xf3\x84\x00")), 24000)  # MPEG-2
        (self.t / "d.mp3").write_bytes(b"not audio")
        self.assertIsNone(audio.sample_rate(self.t / "d.mp3"))

    def test_numbered_folders_and_an_index(self):
        files = [mp3(self.t / "in" / f"s{i:03d}.mp3") for i in range(257)]
        out, problems = audio.ready_sd_card(self.cfg, "Chest", files)
        self.assertEqual(problems, [])
        self.assertTrue((out / "01" / "001.mp3").is_file())
        self.assertTrue((out / "01" / "255.mp3").is_file())
        self.assertTrue((out / "02" / "002.mp3").is_file())          # the 257th
        index = (out / "index.txt").read_text(encoding="utf-8")
        self.assertIn("02/002.mp3  playFolder(2, 2)  s256.mp3", index)
        self.assertIn("FAT16 or FAT32", index)

    def test_what_the_module_may_not_play_is_said(self):
        files = [tone(self.t / "x.wav", 96000), self.t / "y.ogg"]
        files[1].write_bytes(b"x")
        _, problems = audio.ready_sd_card(self.cfg, "Odd", files)
        self.assertTrue(any("96000 Hz" in p for p in problems))
        self.assertTrue(any("WAV is not on DFRobot" in p for p in problems))
        self.assertTrue(any("not .ogg" in p for p in problems))
        with self.assertRaises(ValueError):
            audio.ready_sd_card(self.cfg, "", files)


class TestTheShelfAndPlaces(AHome):
    def test_places_remembered_and_forgotten(self):
        p = tone(self.shelf / "podcasts" / "Episode 1.wav")
        audio.remember(self.cfg, p, 125.4)
        self.assertEqual(audio.place(self.cfg, p), 125.4)
        audio.remember(self.cfg, p, None)                          # it finished
        self.assertEqual(audio.place(self.cfg, p), 0.0)

    def test_the_recorder_keeps_it_and_says_if_silent(self):
        fake = mock.Mock()
        fake.stop.return_value = tone(self.t / "tmp.wav", secs=1.0)
        with mock.patch("nemo.speech.Recorder", return_value=fake):
            r = audio.Recording(self.cfg); r.start()
            path, said = r.stop("Door creak")
        self.assertEqual(path, self.shelf / "recordings" / "Door creak.wav")
        self.assertIn("silent", said)

    def test_backups_keep_recordings_not_what_nemo_can_remake(self):
        tone(self.shelf / "recordings" / "mine.wav")
        tone(self.shelf / "books" / "story" / "01.wav")
        tone(self.shelf / "sd-cards" / "card" / "01" / "001.wav")
        with mock.patch("nemo.config.CONFIG_HOME", self.t / ".nemo"):
            made = backup.make(self.cfg, self.t / "backups")
        names = zipfile.ZipFile(made.path).namelist()
        self.assertIn("storeroom/audio/recordings/mine.wav", names)
        self.assertFalse([n for n in names if "/books/" in n or "/sd-cards/" in n])

    def test_the_store_s_audio_aisle_and_the_team(self):
        tone(self.shelf / "podcasts" / "Episode 1.wav")
        cases = videostore.shelves(self.cfg)["AUDIO"]
        self.assertEqual([(c.title, c.subtitle) for c in cases], [("Episode 1", "podcast")])
        self.assertEqual([e.title for e in staff.team("audio")],
                         ["Narrator", "Recorder", "Sound Engineer", "Librarian", "Writer"])


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_card_and_shelf(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        tone(self.shelf / "podcasts" / "Episode 1.wav")
        app = A.NemoApp(); app.update()
        try:
            w = A.AudioRoom(app); app.update()
            self.assertEqual(len(w.tree.get_children()), 1)
            w.card.insert(0, "Chest")
            out = w.ready_card([str(mp3(self.t / "in" / "a.mp3"))])
            self.assertTrue((out / "01" / "001.mp3").is_file())
            self.assertIn("1 sound(s) ready", w.note.cget("text"))
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
