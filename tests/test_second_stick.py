"""Read from the owner's stick after a real run of the cc83c2b image on the
AH531 (2026-10-19). Speech heard "build me a smartphone device" (D186
confirmed), and three things were wrong. Invented content in their shapes."""
from __future__ import annotations

import os, struct, sys, tempfile, unittest, wave
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import research, review, speech
from nemo.fixes import apply_fix
from nemo.parts import PartsLibrary
from nemo.project import Brief, Project

LIB = PartsLibrary.load()


class TestD187TheRecordingsLength(unittest.TestCase):
    """arecord stopped with SIGTERM left its placeholder length in the
    header: 1073741824 frames, 18 hours for 9 seconds."""

    def test_measured_from_the_sound_not_the_header(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b"\x10\x00" * 16000 * 2)          # 2 s of sound
            data = bytearray(p.read_bytes())
            data[40:44] = struct.pack("<I", 0x7FFFFFFF)            # the placeholder
            p.write_bytes(bytes(data))
            secs, peak, rms = speech.measure(p)
        self.assertAlmostEqual(secs, 2.0, places=2)

    def test_arecord_is_interrupted_so_it_finishes_the_file(self):
        import signal
        rec = speech.Recorder()
        rec.proc = mock.Mock()
        with mock.patch.object(speech.sys, "platform", "linux"):
            rec.stop()
        rec.proc.send_signal.assert_called_once_with(signal.SIGINT)
        rec.proc.terminate.assert_not_called()


class TestTheMouserKey(unittest.TestCase):
    """The key entered was 35 characters; Mouser's are 36 (8-4-4-4-12) and
    it answered 'Invalid unique identifier'."""

    def test_its_shape_is_checked(self):
        self.assertTrue(research.key_looks_right("0" * 8 + "-" + "a" * 4 + "-" + "1" * 4 + "-"
                                                 + "b" * 4 + "-" + "2" * 12))
        self.assertFalse(research.key_looks_right("0" * 8 + "-" + "a" * 4 + "-" + "1" * 4 + "-"
                                                  + "b" * 4 + "-" + "2" * 11))

    def test_mousers_refusal_says_to_enter_it_again(self):
        finds, why = research.parse({"Errors": [{"Message": "Invalid unique identifier."}]})
        self.assertIn("enter it again", why)


class TestD188AShapeNemoCannotMake(unittest.TestCase):
    """'Holds a phone on a table in the shape of a hand' was made as an open
    box and every check passed."""

    HOLDER = Brief(name="holder", function="A stand that holds a phone.",
                   envelope_mm=[60, 40, 90], done_when="It holds a phone in the shape of a paw.",
                   no_power=True, no_parts=True)

    def project(self, b):
        return Project(Path(tempfile.mkdtemp()) / "p").create(b)

    def test_noted_early_and_stopped_at_the_enclosure(self):
        p = self.project(self.HOLDER)
        stops, notes = review.before("parts", p, LIB)
        self.assertEqual(stops, [])
        self.assertTrue(any("rectangular trays" in n for n in notes))
        names = [r.name for r in review.before("enclosure", p, LIB)[0]]
        self.assertIn("review_shape_unsupported", names)

    def test_a_tray_can_be_accepted(self):
        fix = next(f for f in review.fixes("shape_unsupported", self.HOLDER, LIB)
                   if f.key == "review_accept_shape")
        p = self.project(apply_fix(self.HOLDER, fix))
        names = [r.name for r in review.before("enclosure", p, LIB)[0]]
        self.assertNotIn("review_shape_unsupported", names)

    def test_ordinary_words_are_not_a_shape(self):
        for text in ("A lid that a servo opens when a hand comes near.",
                     "A round speaker grille.", "A handheld torch."):
            self.assertIsNone(review.SHAPED.search(text), text)
        for text in ("in the shape of a hand", "shaped like a fox", "a star-shaped lamp",
                     "a small statue"):
            self.assertIsNotNone(review.SHAPED.search(text), text)
