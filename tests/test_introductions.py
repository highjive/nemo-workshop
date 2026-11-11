"""The team introduced the first time a department opens (owner,
2026-10-23: "companion first, employees introduced before going to the
different departments"): the roster's own words, one employee at a time.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import introductions as I
from nemo.staff import DEPARTMENTS, STAFF, team


class TestTheWords(unittest.TestCase):
    def test_every_employee_has_a_line_from_the_roster(self):
        for key in DEPARTMENTS:
            said = I.lines(key)
            self.assertEqual([r for r, _ in said], [e.key.split(".", 1)[1] for e in team(key)])
            for role, text in said:
                self.assertTrue(text.startswith("This is the "), text)
                self.assertNotIn("nemo/", text)                  # no code references
                self.assertNotIn(".py", text)
                self.assertNotIn("(owner", text)
                self.assertNotRegex(text, r"\bIt [a-z]+:")        # no "It photos:"

    def test_wording(self):
        self.assertEqual(I.line(STAFF["library.timekeeper"]),
                         "This is the Timekeeper. It times every job from the model server's own "
                         "figures, so what is slow is measured, not guessed.")
        self.assertTrue(I.line(STAFF["computer_lab.rea"]).startswith("This is the Reverse Engineer: REA:"))
        self.assertTrue(I.line(STAFF["computer_lab.designer"]).endswith("Its job is not built yet."))
        self.assertEqual(I.welcome("workshop"), "Here is the Workshop team: 11 of them.")

    def test_remembered_once_introduced(self):
        s = {}
        self.assertFalse(I.seen(s, "library"))
        s = I.mark(I.mark(s, "library"), "library")
        self.assertEqual(s["introduced"], ["library"])
        self.assertTrue(I.seen(s, "library"))


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestInTheRoom(unittest.TestCase):
    def test_first_visit_introduces_then_not_again(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                room = app.open_department("music"); app.update()
                self.assertIn("Music Room team", room.canvas.itemcget(room._cap, "text"))
                room.next_introduction()
                self.assertEqual(room.speaking, "player")
                room.tick()
                self.assertEqual(room.canvas.itemcget(room.rings["player"], "outline"), "#FFF6E0")
                room.end_introductions()
                self.assertEqual(room.canvas.itemcget(room._cap, "state"), "hidden")
                room.destroy()
                again = app.open_department("music"); app.update()
                self.assertIsNone(again._intro)                  # once is enough
                again.introduce()                                # Meet the team: on request
                self.assertIsNotNone(again._intro)
                again.destroy()                                  # its timers go with it
            finally:
                app.destroy()


class TestTheVoiceIsNotCutOff(unittest.TestCase):
    """D275 (2026-11-11, measuring the voice): the next introduction came on a
    reading-time timer (1.5 s + 0.38 s a word) and stopped the voice in the
    middle: "Hello, I'm the Writer." style lines ran at 97 words a minute,
    longer than the timer gave. Now it waits until the voice has finished."""

    def test_the_next_waits_for_the_voice(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        from nemo import voice
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                app.voice_on.set(True)
                room = app.open_department("music"); app.update()
                calls = []
                with mock.patch.object(voice, "speak", return_value=(True, "")),                      mock.patch.object(voice, "speaking", return_value=True),                      mock.patch.object(room, "after", side_effect=lambda ms, fn: calls.append((ms, fn)) or "j"):
                    room.next_introduction()
                    self.assertEqual(calls[-1], (A.INTRO_POLL_MS, room._intro_when_quiet))
                    room._intro_when_quiet()                     # still speaking: look again
                    self.assertEqual(calls[-1], (A.INTRO_POLL_MS, room._intro_when_quiet))
                with mock.patch.object(voice, "speaking", return_value=False),                      mock.patch.object(room, "after", side_effect=lambda ms, fn: calls.append((ms, fn)) or "j"):
                    room._intro_when_quiet()                     # finished: a breath, then the next
                    self.assertEqual(calls[-1], (A.INTRO_BREATH_MS, room.next_introduction))
                room._intro_job = None
                room.end_introductions()
                room.destroy()
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
