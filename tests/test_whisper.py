"""Hearing with whisper.cpp on the desktop's GPU (owner, 2026-11-04), Vosk
everywhere else."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import speech, toolkit

ROOT = Path(__file__).resolve().parent.parent


class TestWhichHears(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        (home / "models" / "speech").mkdir(parents=True)
        (home / "models" / "speech" / speech.WHISPER_MODEL).write_bytes(b"x")
        env = mock.patch.dict(os.environ, {"NEMO_HOME": str(home)}); env.start(); self.addCleanup(env.stop)

    def found(self, machine):
        # Both files "there", wherever whisper() looks; only the machine differs.
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": machine}), \
             mock.patch.object(Path, "is_file", autospec=True,
                               side_effect=lambda p: p.name in ("whisper-cli.exe", speech.WHISPER_MODEL)):
            return speech.whisper()

    def test_the_laptop_keeps_vosk(self):
        self.assertIsNone(self.found("laptop"))

    def test_the_desktop_hears_with_whisper(self):
        got = self.found("desktop")
        self.assertIsNotNone(got)
        self.assertEqual(got[0].name, "whisper-cli.exe")
        self.assertEqual(got[1].name, speech.WHISPER_MODEL)


class TestTranscribing(unittest.TestCase):
    def run_with(self, stdout):
        exe, model = Path("whisper-cli.exe"), Path("ggml-small.en.bin")
        with mock.patch.object(speech, "whisper", return_value=(exe, model)), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout=stdout)) as run:
            heard = speech.transcribe(Path("x.wav"))
        return heard, run.call_args[0][0]

    def test_it_asks_for_english_text_with_no_timestamps(self):
        heard, cmd = self.run_with("  How many hours will a 2000 mAh battery last?\n")
        self.assertEqual(heard, "How many hours will a 2000 mAh battery last?")
        for flag in ("-nt", "-np"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("-l") + 1], "en")

    def test_silence_is_nothing_heard(self):
        self.assertEqual(self.run_with(" [BLANK_AUDIO]\n")[0], "")
        self.assertEqual(self.run_with("(wind blowing)")[0], "")

    def test_the_linguist_says_which_it_hears_with(self):
        with mock.patch.object(speech, "available", return_value=(True, "")), \
             mock.patch.object(speech, "whisper", return_value=(Path("a"), Path("b"))):
            self.assertEqual(toolkit._hearing(None), (True, "Whisper (small.en) on the GPU"))


class TestTheInstaller(unittest.TestCase):
    def test_nemodoc_fetches_the_same_files(self):
        for base in (ROOT, ROOT / "install" / "windows"):
            if (base / "NemoDoc.ps1").exists():
                text = (base / "NemoDoc.ps1").read_text(encoding="utf-8")
                break
        else:
            self.skipTest("NemoDoc.ps1 not in this layout")
        block = text[text.index("$WhisperFiles = @("):text.index("$WhisperFiles = @(") + 900]
        pinned = set(re.findall(r'file = "([^"]+)"; sha256 = "([0-9a-f]{64})"; bytes = (\d+)', block))
        self.assertEqual(pinned, {(f, h, str(b)) for f, b, h in speech.WHISPER_SOURCES})


class TestTheFilmStudioStaysOnTheCpu(unittest.TestCase):
    def test_nvenc_was_measured_and_not_taken(self):
        # 2026-11-04, a 20 s scene: libx264 1.93/1.95 s, NVENC 1.84/1.83 s, its
        # file 4.6 times larger. The zoom filter is the work, not the encode.
        from nemo import filmstudio
        self.assertEqual(filmstudio.ENCODE[1], "libx264")


if __name__ == "__main__":
    unittest.main()
