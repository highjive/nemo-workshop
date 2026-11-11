"""Audio cues (owner, 2026-10-23): tones made by code, played without
waiting, a Sounds switch; a talk reply has the voice, not a chime.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import cues


class TestTheTones(unittest.TestCase):
    def test_each_cue_is_a_short_clean_wav(self):
        for name, notes in cues.CUES.items():
            with wave.open(io.BytesIO(cues.wav_bytes(name))) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()),
                                 (1, 2, cues.RATE), name)
                secs = w.getnframes() / cues.RATE
            self.assertAlmostEqual(secs, sum(ms for _, ms in notes) / 1000, delta=0.01)
            self.assertLess(secs, 0.6, name)                     # a cue, not a tune

    def test_written_once_and_played_by_the_platform(self):
        with tempfile.TemporaryDirectory() as t, mock.patch("nemo.config.CONFIG_HOME", Path(t)):
            p = cues.path("done")
            self.assertEqual(p.read_bytes(), cues.wav_bytes("done"))
            with mock.patch.dict(os.environ, {"NEMO_CUES": ""}):
                if sys.platform.startswith("win"):
                    with mock.patch("winsound.PlaySound") as ps:
                        self.assertTrue(cues.play("done"))
                    ps.assert_called_once()
                with mock.patch.object(cues.sys, "platform", "darwin"), \
                        mock.patch.object(cues.shutil, "which", return_value="/usr/bin/afplay"), \
                        mock.patch.object(cues.subprocess, "Popen") as run:
                    self.assertTrue(cues.play("fail"))
                self.assertEqual(run.call_args[0][0][0], "afplay")
                with mock.patch.object(cues.sys, "platform", "linux"), \
                        mock.patch.object(cues.shutil, "which", return_value=None):
                    self.assertFalse(cues.play("fail"))            # no player: silent, not an error
        self.assertFalse(cues.play("done"))                        # the sandbox keeps it quiet
        self.assertFalse(cues.play("no such cue"))


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheSwitch(unittest.TestCase):
    def test_announce_cues_by_colour_and_talk_does_not(self):
        try:
            from nemo.gui import app as A
            from nemo.gui import theme as T
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                with mock.patch.object(cues, "play", return_value=True) as play:
                    app.announce("A check failed.", T.FAIL)
                    app.announce("Film Studio: ready.")
                    app.announce("Hello.", cue="")
                    app.sounds_on.set(False)
                    app.announce("Quiet now.", T.FAIL)
                self.assertEqual([c.args[0] for c in play.call_args_list], ["fail", "done"])
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()


class TestTheMacVoice(unittest.TestCase):
    def test_say_reads_the_words_from_stdin(self):
        from nemo import voice
        with mock.patch.object(voice.sys, "platform", "darwin"), \
                mock.patch.object(voice.shutil, "which", return_value="/usr/bin/say"), \
                mock.patch.object(voice.subprocess, "Popen") as run, \
                mock.patch.dict(os.environ, {"NEMO_VOICE": ""}):
            ok, _ = voice.speak("Hello; rm -rf")
        self.assertTrue(ok)
        argv = run.call_args[0][0]
        self.assertEqual(argv, ["/usr/bin/say", "-r", str(voice.words_per_minute())])  # the speed; nothing said on the command line
        run.return_value.stdin.write.assert_called_once_with(b"Hello; rm -rf")
