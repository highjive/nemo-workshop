"""Speaking to Nemo (redesign, 2026-10-17): offline recognition, and the
words going into the prompt box to be checked, never sent on their own.

data/speech-lamp.wav is Windows' own speech synthesiser saying an invented
request, 16 kHz mono: "Build me a lamp that turns on when someone walks
past the door."
"""
from __future__ import annotations

import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import speech

SAMPLE = Path(__file__).resolve().parent / "data" / "speech-lamp.wav"


def can_hear() -> bool:
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False
    return speech.find_model() is not None


class TestWhetherItCanWork(unittest.TestCase):
    def test_says_why_not(self):
        with mock.patch.dict(sys.modules, {"vosk": None}):
            ok, why = speech.available()
        self.assertFalse(ok); self.assertIn("vosk", why)
        with mock.patch.object(speech, "find_model", return_value=None), \
             mock.patch.dict(sys.modules, {"vosk": mock.Mock()}):
            ok, why = speech.available()
        self.assertFalse(ok); self.assertIn(speech.MODEL_NAME, why)

    def test_looks_on_the_windows_disk_nemoiso_reads(self):
        self.assertTrue(any("nemo" in str(d).lower() for d in speech.model_dirs()))

    def running(self):
        import subprocess
        proc = mock.Mock()
        proc.wait.side_effect = subprocess.TimeoutExpired("arecord", 0.4)
        return proc

    def test_records_16k_mono_on_linux(self):
        with mock.patch.object(speech.sys, "platform", "linux"), \
             mock.patch.object(speech, "capture_on", return_value=[]), \
             mock.patch("subprocess.Popen", return_value=self.running()) as popen:
            speech.Recorder().start()
        argv = popen.call_args[0][0]
        self.assertEqual(argv[0], "arecord")
        self.assertIn("16000", argv); self.assertIn("S16_LE", argv)

    def test_a_recorder_that_stops_at_once_says_why(self):
        dead = mock.Mock()
        dead.wait.return_value = 1
        dead.stderr.read.return_value = b"arecord: main:850: audio open error: No such device"
        with mock.patch.object(speech.sys, "platform", "linux"), \
             mock.patch.object(speech, "capture_on", return_value=[]), \
             mock.patch("subprocess.Popen", return_value=dead):
            with self.assertRaises(OSError) as e:
                speech.Recorder().start()
        self.assertIn("No such device", str(e.exception))

    def test_d274_a_recording_leaves_no_file_behind(self):
        # 2026-11-11: 178 empty nemo-speech-*.wav in Temp; the handle was never
        # closed and a failed start or a discarded recording was never deleted.
        rec = speech.Recorder()
        self.assertTrue(rec.path.exists())
        rec.path.unlink()                                   # possible: no handle held open
        rec = speech.Recorder()
        rec.discard()
        self.assertFalse(rec.path.exists())
        dead = mock.Mock()
        dead.wait.return_value = 1
        dead.stderr.read.return_value = b"audio open error"
        rec = speech.Recorder()
        with mock.patch.object(speech.sys, "platform", "linux"), \
             mock.patch.object(speech, "capture_on", return_value=[]), \
             mock.patch("subprocess.Popen", return_value=dead):
            with self.assertRaises(OSError):
                rec.start()
        self.assertFalse(rec.path.exists())                 # a failed start cleans up

    def test_the_microphone_is_switched_on_first(self):
        ok = mock.Mock(returncode=0)
        with mock.patch.object(speech.shutil, "which", return_value="/usr/bin/amixer"), \
             mock.patch("subprocess.run", return_value=ok) as run:
            done = speech.capture_on()
        self.assertEqual(done, list(speech.CAPTURE_CONTROLS))
        first = run.call_args_list[0][0][0]
        self.assertEqual(first[:4], ["amixer", "-q", "sset", "Capture"])
        self.assertIn("cap", first)

    def test_how_loud(self):
        secs, peak, rms = speech.measure(SAMPLE)
        self.assertAlmostEqual(secs, 4.7, delta=0.1)
        self.assertGreater(peak, speech.SILENT)
        self.assertEqual(speech.loudness(b"\x00\x00" * 100), (0.0, 0.0))


@unittest.skipUnless(can_hear(), "needs vosk and its model")
class TestRecognition(unittest.TestCase):
    def test_the_sample_is_heard(self):
        text = speech.transcribe(SAMPLE)
        for w in ("lamp", "turns on", "walks past", "door"):
            self.assertIn(w, text)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheSpeakButton(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        from nemo.gui.prompt import PromptWindow
        self.app = A.NemoApp(); self.app.withdraw(); self.app.update()
        self.pw = PromptWindow(self.app); self.app.update()

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def wait(self):
        for _ in range(100):
            self.app.update(); self.app.after(50)
            if str(self.pw.mic.cget("state")) == "normal" and self.pw._speech_timer is None:
                return

    def recorder(self):
        rec = mock.Mock()
        rec.start.return_value = ["Capture"]
        rec.level.return_value = 0.4
        rec.stop.return_value = Path(self.t.name) / "x.wav"
        return rec

    def test_silence_is_said_and_not_sent_to_the_recogniser(self):
        rec = self.recorder()
        with mock.patch.object(speech, "available", return_value=(True, "")), \
             mock.patch.object(speech, "Recorder", return_value=rec), \
             mock.patch.object(speech, "measure", return_value=(3.0, 0.001, 0.0002)), \
             mock.patch.object(speech, "keep_last"), \
             mock.patch.object(speech, "transcribe") as hear:
            self.pw.toggle_speech()
            self.pw.toggle_speech()
            self.wait()
        hear.assert_not_called()
        self.assertIn("heard silence", self.pw.status.cget("text"))
        self.assertIn("alsamixer", self.pw.status.cget("text"))

    def test_what_is_heard_goes_into_the_box_and_is_not_sent(self):
        rec = self.recorder()
        with mock.patch.object(speech, "available", return_value=(True, "")), \
             mock.patch.object(speech, "Recorder", return_value=rec), \
             mock.patch.object(speech, "measure", return_value=(2.0, 0.5, 0.1)), \
             mock.patch.object(speech, "keep_last") as kept, \
             mock.patch.object(speech, "transcribe", return_value="a lamp for the hall"), \
             mock.patch.object(self.pw, "send") as send:
            self.pw.toggle_speech()
            self.assertEqual(self.pw.mic.cget("text"), "Stop listening")
            self.assertIn("switched on: Capture", self.pw.status.cget("text"))
            self.app.after(450); self.app.update()
            self.assertGreater(self.pw.glow.voice, 0)          # the glow follows the voice
            self.pw.toggle_speech()
            self.wait()
        kept.assert_called_once()                             # the recording is kept
        self.assertEqual(self.pw.glow.voice, 0.0)
        self.assertEqual(self.pw.box.get("1.0", "end").strip(), "a lamp for the hall")
        send.assert_not_called()
        self.assertIn("then Send", self.pw.status.cget("text"))

    def test_not_set_up_says_so(self):
        with mock.patch.object(speech, "available", return_value=(False, "no model")):
            self.pw.toggle_speech()
        self.assertIn("not set up", self.pw.status.cget("text"))
        self.assertEqual(self.pw.mic.cget("text"), "Speak")

    def test_closing_while_listening_stops_the_recorder(self):
        rec = self.recorder()
        with mock.patch.object(speech, "available", return_value=(True, "")), \
             mock.patch.object(speech, "Recorder", return_value=rec):
            self.pw.toggle_speech()
        self.pw.destroy()
        rec.stop.assert_called_once()


class TestTheImageCanHear(unittest.TestCase):
    def test_the_build_installs_speech_and_pins_the_model(self):
        b = Path(__file__).resolve().parent.parent / "install" / "live-build" / "build-iso.sh"
        if not b.exists():
            self.skipTest("build-iso.sh is not in this layout")
        t = b.read_text(encoding="utf-8")
        self.assertRegex(t, r"apt-get install[^\n]*\balsa-utils\b")
        self.assertIn("/opt/nemo/venv/bin/pip install --quiet vosk", t)
        self.assertIn("30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498", t)
        self.assertIn("sha256sum -c -", t)
        self.assertIn("speech-lamp.wav", t)          # the image proves it can hear
