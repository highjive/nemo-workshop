"""Ask a department (owner, 2026-11-09: "Nemo needs input method in each department
as to what is needed to be done in each department, not being directed back to home
screen"). nemo/asks.py reads the words by code; gui/askbar.py is each department's box."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import asks
from nemo.staff import DEPARTMENTS

P = {"project": "lamp"}


def ask(key, text, ctx=None):
    return asks.answer(key, text, ctx if ctx is not None else {"project": None})


class TestEachDepartmentReadsItsOwnWork(unittest.TestCase):
    def test_every_department_takes_words(self):
        self.assertEqual(set(asks.HANDLERS), set(DEPARTMENTS))
        self.assertEqual(set(asks.CAN_DO), set(DEPARTMENTS))

    def test_the_samples(self):
        cases = [
            ("science", "100 F to C", ["science", "convert", "100 F", "C"]),
            ("science", "what is 3.5 inch in mm?", ["science", "convert", "3.5 inch", "mm"]),
            ("science", "R=? V=5 V I=20 mA", ["science", "formula", "R=?", "V=5 V", "I=20 mA"]),
            ("science", "mean of 3 5 7 9", ["science", "stats", "3", "5", "7", "9"]),
            ("science", "x**2 - 9 = 0", ["science", "solve", "x**2 - 9 = 0"]),
            ("comms", "letter to Ann Smith: thank you for the parts.",
             ["comms", "letter", "Ann Smith", "--body", "thank you for the parts."]),
            ("art_studio", "make a tag saying SHED", ["model", "make", "tag", "Shed Tag", "text=SHED"]),
            ("art_studio", "a box 80 mm wide", ["model", "make", "box", "My Box", "width=80"]),
            ("printshop", "slice the shed key tag", ["print", "slice", "shed key tag"]),
            ("film", "make a film of the canal story", ["film", "make", "canal story"]),
            ("audio", "narrate the fox story", ["audio", "narrate", "fox story"]),
            ("theatre", "play Sailing Away", ["theatre", "play", "Sailing Away"]),
            ("gaming", "play 2048", ["games", "play", "2048"]),
            ("home", "look around", ["home", "survey"]),
            ("storeroom", "add 10 resistors in drawer 2",
             ["store", "add", "resistors", "--qty", "10", "--where", "drawer 2"]),
            ("storeroom", "take 2 resistors", ["store", "take", "resistors", "--qty", "2"]),
            ("doctors", "why is it slow", ["clinic"]),
            ("workshop", "laminate floor 4.2 x 3.6 m", ["wood", "laminate floor 4.2 x 3.6 m"]),
            ("library", "look up canal locks", ["lookup", "canal locks"]),
        ]
        for key, text, argv in cases:
            r = ask(key, text)
            self.assertEqual((r.kind, r.argv), (asks.RUN, argv), (key, text))

    def test_the_open_project_is_worked_on(self):
        self.assertEqual(ask("bench", "flash it", P).argv, ["--project", "lamp", "bench", "flash"])
        self.assertEqual(ask("computer_lab", "build the firmware", P).argv,
                         ["--project", "lamp", "test"])
        self.assertEqual(ask("bench", "flash it").kind, asks.SAY)            # none open: said
        self.assertIn("Open a project first", ask("computer_lab", "test it").say)

    def test_designs_and_stories_start_from_the_words(self):
        r = ask("workshop", "a desk lamp that dims")
        self.assertEqual((r.kind, r.text), (asks.DESIGN, "a desk lamp that dims"))
        r = ask("library", "a story about a fox")
        self.assertEqual((r.kind, r.text), (asks.STORY, "a story about a fox"))

    def test_casting_is_never_done_from_words(self):
        # docs/design-rules.md: never cast to the owner's Chromecast unasked. The control is lit.
        for key in ("theatre", "music"):
            r = ask(key, "cast it to the TV")
            self.assertEqual((r.kind, r.button, r.argv), (asks.WINDOW, "Cast", []))

    def test_what_it_cannot_do_is_said_here(self):
        r = ask("gaming", "make me a cup of tea")
        self.assertEqual(r.kind, asks.SAY)
        self.assertIn("Gaming did not understand that", r.say)
        self.assertIn("'play <game>'", r.say)
        self.assertNotIn("Workshop", r.say)        # no words matched: no false hint
        r = ask("music", "slice the tag for the printer")
        self.assertIn("The Music Room did not understand", r.say)
        self.assertIn("work for the Print Shop", r.say)
        self.assertIn("Type what you would like", ask("science", "  ").say)


@unittest.skipUnless(_sandbox.has_display(), "needs a display")
class TestTheBoxInADepartment(unittest.TestCase):
    def setUp(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name)); env.start()
        self.addCleanup(env.stop)
        self.app = A.NemoApp(); self.app.update(); self.addCleanup(self.app.destroy)

    def wait(self):
        bar, t0 = self.app.ask_bar, time.time()
        while bar.job is not None and time.time() - t0 < 120:
            self.app.update(); time.sleep(0.05)

    def test_each_department_has_its_box_and_answers_there(self):
        from nemo.gui.prompt import PromptWindow
        room = self.app.open_department("science"); self.app.update()
        room.end_introductions(); self.app.update()
        bar = self.app.ask_bar
        self.assertTrue(bar.winfo_ismapped())
        self.assertEqual(bar.label.cget("text"), "Ask Science:")
        bar.send("100 F to C"); self.wait()
        self.assertIn("37.7778", bar.reply.get("1.0", "end"))
        self.assertTrue(room.winfo_exists())                     # still in the department
        self.assertFalse(any(isinstance(w, PromptWindow) for w in self.app.winfo_children()))
        self.app.back_to_workshop(); self.app.update()
        self.assertFalse(bar.winfo_ismapped())                   # gone with the department

    def test_a_departments_own_window_has_it_too(self):
        for key, name in self.A.WINDOW_OF.items():
            self.assertTrue(hasattr(self.A, name), name)                    # a real window
            self.assertEqual(self.A.department_of(type(name, (), {})()), key)
        self.assertIsNone(self.A.department_of(type("NewPartDialog", (), {})()))
        win = self.app.real_window("science"); self.app.update()
        self.assertEqual(self.A.department_of(win), "science")
        self.assertTrue(self.app.ask_bar.winfo_ismapped())

    def test_an_employees_ask_offer_is_the_box_not_home(self):
        from nemo import skills
        from nemo.gui.prompt import PromptWindow
        room = self.app.open_department("library"); self.app.update()
        room.end_introductions(); self.app.update()
        room.show_profile("writer"); self.app.update()
        room.use_skill(skills.Skill("Write me a story", skills.ASK)); self.app.update()
        self.assertFalse(any(isinstance(w, PromptWindow) for w in self.app.winfo_children()))
        self.assertIn("Write me a story: type it here", self.app.ask_bar.reply.get("1.0", "end"))

    def test_casting_lights_the_button_and_presses_nothing(self):
        room = self.app.open_department("theatre"); self.app.update()
        room.end_introductions(); self.app.update()
        with mock.patch("nemo.cast.Session") as session:
            self.app.ask_bar.send("cast the film to the TV")
            for _ in range(10):
                self.app.update(); time.sleep(0.05)
        session.assert_not_called()
        self.assertEqual(self.A.department_of(self.app._embedded), "theatre")


if __name__ == "__main__":
    unittest.main()
