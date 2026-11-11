"""Nemo as his companion: his own tools (journal, check-in, calm) and the
Doctors' memory check (owner's yes, 2026-10-23). All by code; no model.
"""
from __future__ import annotations

import datetime as dt
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import companion as C
from nemo import memorycheck as M


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.root))
        self._env.start()
        self._home = mock.patch("nemo.config.CONFIG_HOME", self.root / ".nemo")
        self._home.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def tearDown(self):
        self._home.stop(); self._env.stop()
        self.t.cleanup()


class TestHisTools(AHome):
    def test_what_code_answers(self):
        self.assertEqual(C.command("journal: today I finished the lamp"),
                         ("journal", "today I finished the lamp"))
        self.assertEqual(C.command("check in"), ("ask-checkin", None))
        self.assertEqual(C.command("mood 3 sleep 4"), ("checkin", (3, 4)))
        self.assertEqual(C.command("breathe"), ("calm", None))
        self.assertIsNone(C.command("print a stand for the lamp"))

    def test_the_journal_keeps_only_what_he_asks(self):
        self.assertIn("Kept", C.keep_journal(self.cfg, "a good day at the bench"))
        text = (C._home(self.cfg) / "journal.md").read_text(encoding="utf-8")
        self.assertIn("a good day at the bench", text)
        self.assertIn("Tell me what to keep", C.keep_journal(self.cfg, ""))

    def test_check_ins_read_plainly(self):
        now = dt.datetime(2026, 10, 23, 9)
        self.assertIn("Too few check-ins", C.check_in(self.cfg, 3, 3, now - dt.timedelta(days=8)))
        said = C.check_in(self.cfg, 2, 3, now)
        self.assertIn("mood lower than the week before (2.0 against 3.0)", said)
        self.assertIn("sleep about the same", said)
        for word in ("great", "worry", "!"):
            self.assertNotIn(word, said)                        # a realist: no cheering, no alarm

    def test_the_breathing_guide(self):
        self.assertEqual(len(C.CALM_STEPS), 12)
        self.assertEqual(C.CALM_STEPS[:3], [("Breathe in", 4), ("Hold", 4), ("Breathe out", 6)])


class TestTheMemoryCheck(AHome):
    def test_five_words_scored_out_of_five(self):
        words = M.start(random.Random(1))
        self.assertEqual(len(set(words)), 5)
        score, missed, trend = M.recall(f"{words[0]}s, {words[1]} and {words[2].upper()} hmm")
        self.assertEqual((score, missed), (3, words[3:]))
        self.assertIn("one day says nothing", trend)
        with self.assertRaises(ValueError):
            M.recall("anything")                                # nothing waiting now

    def test_never_the_same_words_twice_running(self):
        first = M.start(random.Random(2)); M.recall("")
        self.assertTrue(set(first).isdisjoint(M.start(random.Random(2))))

    def test_a_clear_fall_suggests_the_gp_and_no_diagnosis(self):
        for s in (5, 5, 5, 5, 3, 3, 3, 3):
            M._write({"at": "", "words": [], "score": s})
        said = M.trend()
        self.assertIn("clear fall", said)
        self.assertIn("not a diagnosis", said)
        self.assertIn("GP", said)
        for s in (3, 3, 3, 3):
            M._write({"at": "", "words": [], "score": s})
        self.assertIn("no clear change", M.trend())


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_the_tools_in_the_home_scene(self):
        try:
            from nemo.gui import app as A
            from nemo.gui.prompt import PromptWindow
        except ImportError:
            self.skipTest("tkinter not installed")
        app = A.NemoApp(); app.update()
        try:
            app.cfg = self.cfg
            pw = PromptWindow(app); app.update()
            with mock.patch("nemo.companion.reply") as model:
                for text in ("journal: kept here", "memory check"):
                    pw.box.insert("1.0", text); pw.send(); app.update()
                model.assert_not_called()                       # code answered, not the model
            self.assertIn("five words", pw.status.cget("text"))
            pw.calm([("Breathe in", 1)])
            self.assertEqual(pw.glow.voice, 0.1)                # brighter while breathing in
            pw.destroy()                                        # the guide's timer goes with it
        finally:
            app.destroy()


class TestWhatTheModelGotWrong(unittest.TestCase):
    """Nemo first: the companion through qwen3-4b on 2026-11-11. Each line is a
    real exchange it got wrong; code answers these now, never the model."""

    def ask(self, text, history=None, model_says="I hear you."):
        router = mock.Mock()
        router.ask.return_value.text = model_says
        return C.reply(router, text, history), router.ask

    def test_d271_words_that_may_be_a_crisis_get_asked_plainly_with_the_helplines(self):
        for text in ("I feel like there's no point any more.",
                     "I don't want to be here anymore.",
                     "Everyone would be better off without me.",
                     "I can't go on like this."):
            said, model = self.ask(text)
            model.assert_not_called()
            self.assertIn("ending your life", said, text)
            self.assertIn("116 123", said, text)
            self.assertTrue(C.crisis(text), text)          # and no department is offered

    def test_d271_a_yes_or_more_of_the_same_gets_the_helplines_not_the_question_again(self):
        for text in ("yes", "maybe", "I just can't cope"):
            said, model = self.ask(text, [("no point any more", C.ASK)])
            model.assert_not_called()
            self.assertEqual(said, C.HELP, text)
        said, model = self.ask("no, just a long week", [("no point any more", C.ASK)])
        model.assert_called_once()                         # a no goes back to talking

    def test_d271_ordinary_words_are_not_taken_for_one(self):
        for text in ("this lamp is killing me with its bugs", "is there any point in a fuse here",
                     "I want to be there when it prints"):
            self.assertFalse(C.crisis(text), text)

    def test_d272_the_time_is_the_clocks_and_the_weather_is_not_guessed(self):
        # The model said "It's 3:47 PM here", then the same for the weather.
        now = dt.datetime(2026, 11, 11, 16, 5)
        self.assertEqual(C.by_code("What time is it?", now=now),
                         "By this laptop's clock it's 16:05 on Wednesday 11 November 2026.")
        said, model = self.ask("What's the weather like outside today?")
        model.assert_not_called()
        self.assertEqual(said, C.WEATHER)

    def test_d272_it_promises_no_memory_or_reminder_it_cannot_keep(self):
        said, model = self.ask("Remember that my sister's birthday is on the 4th of December.")
        model.assert_not_called()
        self.assertIn("journal", said)
        # What the model wrote: "I'll remind you. When should I remind you?"
        said, _ = self.ask("ok then", model_says="I’ll remind you. When should I remind you?")
        self.assertEqual(said, C.REMEMBER)

    def test_d272_medicines_go_to_a_pharmacist_not_the_model(self):
        # The model named ibuprofen and acetaminophen for a three-day headache.
        said, model = self.ask("I've had a headache for three days, what tablets should I take?")
        model.assert_not_called()
        self.assertIn("pharmacist", said)
        self.assertNotIn("ibuprofen", said.lower())


if __name__ == "__main__":
    unittest.main()
