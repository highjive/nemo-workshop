"""The Library's Linguist: language and audible feedback (owner, 2026-10-21).

Held here: what is read aloud is the plain words; the words never reach a
command line; no voice is no failure; one sentence at a time; silence under
the test sandbox; and, where this machine has a voice, real speech made into
a file.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import staff, voice

TRICK = 'Done"; Remove-Item C:\\x; echo "$(rm -rf ~)'


class TestTheWords(unittest.TestCase):
    def test_paths_and_marks_are_not_read_out(self):
        said = voice.plain("Saved to C:\\Users\\a\\bom.csv and /home/nemo/p/x.md: **done** `ok`")
        self.assertEqual(said, "Saved to a file and a file: done ok")

    def test_a_long_text_is_cut_at_a_word(self):
        said = voice.plain("word " * 200)
        self.assertLessEqual(len(said), voice.LIMIT + 40)
        self.assertTrue(said.endswith("word. The rest is on the screen."))

    def test_nothing_to_say(self):
        self.assertEqual(voice.speak("  ** ")[0], False)


class Popens(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"NEMO_VOICE": ""})
        self._env.start()
        self.popen = mock.patch("nemo.voice.subprocess.Popen").start()
        self.popen.return_value.poll.return_value = None

    def tearDown(self):
        mock.patch.stopall(); self._env.stop()
        voice._current = None


class TestTheWordsNeverReachACommandLine(Popens):
    def test_windows(self):
        with mock.patch.object(voice, "engine", return_value=("sapi", "powershell")):
            self.assertEqual(voice.speak(TRICK), (True, ""))
        argv = self.popen.call_args[0][0]
        self.assertNotIn("Remove-Item", " ".join(argv))
        self.assertEqual(self.popen.call_args[1]["env"]["NEMO_SAY"], voice.plain(TRICK))
        self.assertIn("en-GB", argv[-1])                  # a British voice first

    def test_linux(self):
        with mock.patch.object(voice, "engine", return_value=("espeak", "espeak-ng")):
            voice.speak(TRICK)
        argv = self.popen.call_args[0][0]
        self.assertEqual(argv, ["espeak-ng", "-v", "en-gb", "-s", str(voice.words_per_minute()), "--stdin"])
        self.popen.return_value.stdin.write.assert_called_once_with(
            voice.plain(TRICK).encode("utf-8"))


class TestQuietWays(Popens):
    def test_no_voice_is_no_failure(self):
        with mock.patch.object(voice, "engine", return_value=(None, "espeak-ng is not installed")):
            self.assertEqual(voice.speak("Hello"), (False, "espeak-ng is not installed"))
        self.popen.assert_not_called()

    def test_the_sandbox_keeps_it_silent(self):
        with mock.patch.dict(os.environ, {"NEMO_VOICE": "off"}):
            ok, why = voice.speak("Hello")
        self.assertFalse(ok)
        self.assertIn("NEMO_VOICE", why)
        self.popen.assert_not_called()

    def test_one_sentence_at_a_time(self):
        with mock.patch.object(voice, "engine", return_value=("sapi", "powershell")):
            voice.speak("First.")
            first = voice._current
            voice.speak("Second.")
        first.terminate.assert_called_once()
        voice.stop()
        self.assertIsNone(voice._current)


@unittest.skipUnless(voice.engine()[0], "no voice on this machine")
class TestARealVoice(unittest.TestCase):
    def test_it_speaks_into_a_file(self):
        with tempfile.TemporaryDirectory() as t:
            wav = Path(t) / "said.wav"
            ok, why = voice.speak("Step three, wiring, passed.", wav=wav, wait=True)
            self.assertTrue(ok, why)
            with wave.open(str(wav)) as w:
                seconds = w.getnframes() / w.getframerate()
        self.assertGreater(seconds, 0.8)


class TestTheLinguist(unittest.TestCase):
    def test_in_the_library_and_working(self):
        e = staff.STAFF["library.linguist"]
        self.assertTrue(e.working)
        self.assertIn("aloud", e.job)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindows(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.app = A.NemoApp(); self.app.withdraw(); self.app.update()

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def test_a_finished_job_is_said_aloud_while_voice_is_on(self):
        with mock.patch("nemo.voice.speak", return_value=(True, "")) as speak:
            self.app.announce("Finished.")
            self.assertEqual(speak.call_args[0][0], "Finished.")
            self.app.voice_on.set(False); self.app._voice_switched()
            self.app.announce("A check failed.")
        self.assertEqual(speak.call_count, 1)
        self.assertEqual(self.app.status.cget("text"), "A check failed.")
        from nemo.gui import controller as C
        self.assertIs(C.load_settings()["voice"], False)

    def test_read_aloud_in_the_prompt_window(self):
        from nemo.gui.prompt import PromptWindow
        pw = PromptWindow(self.app); self.app.update()
        pw.tell("Kept as the story 'fox'.")
        with mock.patch("nemo.voice.speak", return_value=(True, "")) as speak:
            pw.read_aloud()
        self.assertEqual(speak.call_args[0][0], "Kept as the story 'fox'.")
        pw.read_aloud()              # the sandbox's NEMO_VOICE=off: says why, no sound
        self.assertIn("Not read aloud", pw.status.cget("text"))
        pw.destroy()


if __name__ == "__main__":
    unittest.main()


class TestTimingAndSpeed(Popens):
    """Owner, 2026-11-11: "Voice still needs more work on timing and speed"."""

    def tearDown(self):
        voice.set_rate(voice.DEFAULT_RATE)
        super().tearDown()

    def test_a_step_faster_by_default_and_each_step_reaches_every_voice(self):
        self.assertEqual(voice.DEFAULT_RATE, 1)
        self.assertEqual(voice.set_rate(9), 3)                      # clamped
        self.assertEqual(voice.set_rate("x"), voice.DEFAULT_RATE)
        voice.set_rate(-2)
        with mock.patch.object(voice, "engine", return_value=("sapi", "powershell")):
            voice.speak("hello there")
        self.assertEqual(self.popen.call_args[1]["env"]["NEMO_RATE"], "-2")
        self.assertIn("$s.Rate = [int]$env:NEMO_RATE", self.popen.call_args[0][0][-1])
        with mock.patch.object(voice, "engine", return_value=("espeak", "espeak-ng")):
            voice.speak("hello there")
        self.assertIn("135", self.popen.call_args[0][0])            # 175 - 2 x 20 words a minute
        with mock.patch.object(voice, "engine", return_value=("say", "say")):
            voice.speak("hello there")
        self.assertEqual(self.popen.call_args[0][0][1:3], ["-r", "135"])

    def test_a_line_break_is_a_pause(self):
        self.assertEqual(voice.plain("Parts:\nbme280\nesp32c3 devkit\nAll done."),
                         "Parts: bme280. esp32c3 devkit. All done.")
        self.assertEqual(voice.plain("One.\nTwo"), "One. Two")

    def test_it_says_whether_it_is_still_speaking(self):
        with mock.patch.object(voice, "engine", return_value=("espeak", "espeak-ng")):
            voice.speak("hello there")
        self.popen.return_value.poll.return_value = None
        self.assertTrue(voice.speaking())
        self.popen.return_value.poll.return_value = 0
        self.assertFalse(voice.speaking())
