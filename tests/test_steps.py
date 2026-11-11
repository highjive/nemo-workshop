"""nemo/steps.py: the one table of a design's steps (2026-10-20).

Before it, the order, owners, model use, modes, prerequisites, done-files
and window names of the steps were each written out in their own module,
and adding the Concept step meant finding every copy. These tests hold
every former copy to the table, and pin the table to what those copies
said, so the change moved the facts without changing one.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import modes, project, results, review, staff, steps
from nemo.gui import controller


class TestTheTableIsWhatTheCopiesSaid(unittest.TestCase):
    """The values as they were written out before the table (commit c593f0a)."""

    def test_order(self):
        self.assertEqual(steps.ORDER, ["brief", "parts", "electrical", "wiring",
                                       "concept", "enclosure", "firmware", "pack"])

    def test_owners(self):
        self.assertEqual({s.key: s.owner for s in steps.STEPS}, {
            "brief": "workshop.writer", "parts": "workshop.designer",
            "electrical": "workshop.designer", "wiring": "workshop.designer",
            "concept": "art_studio.artist", "enclosure": "workshop.designer",
            "firmware": "computer_lab.coder", "pack": "workshop.writer"})

    def test_which_ask_the_model(self):
        self.assertEqual(steps.MODEL_STEPS,
                         {"brief", "electrical", "wiring", "enclosure", "firmware"})

    def test_modes(self):
        self.assertEqual({s.key: s.mode for s in steps.STEPS}, {
            "brief": "talk", "parts": "talk", "electrical": "design", "wiring": "design",
            "concept": "talk", "enclosure": "design", "firmware": "build", "pack": "talk"})

    def test_what_each_builds_on(self):
        self.assertEqual({s.key: s.builds_on for s in steps.STEPS if s.builds_on}, {
            "electrical": ("parts",), "wiring": ("electrical",), "concept": ("parts",),
            "enclosure": ("parts",), "firmware": ("electrical",)})


class TestEveryCopyReadsTheTable(unittest.TestCase):
    def test_the_lists(self):
        self.assertIs(project.STAGES, steps.ORDER)
        self.assertIs(review.ORDER, steps.ORDER)
        self.assertEqual(results.MODEL_STAGES, steps.MODEL_STEPS)

    def test_every_step_has_one_owner_on_the_staff(self):
        for s in steps.STEPS:
            self.assertIn(s.owner, staff.STAFF, s.key)
            self.assertEqual(staff.owner(s.key).key, s.owner)
            self.assertEqual(sum(s.key in e.steps for e in staff.STAFF.values()), 1, s.key)

    def test_the_window_names_every_step(self):
        self.assertEqual(list(controller.STEP_NAMES), steps.ORDER)
        self.assertEqual(list(controller.STEP_HELP), steps.ORDER)
        self.assertEqual(controller.STEP_NAMES["pack"], "Build guide")

    def test_the_mode_each_step_suits(self):
        with mock.patch.object(modes, "mem_total_mb", return_value=8000), \
                mock.patch.object(modes, "cpu_flags", return_value={"avx"}):
            for s in steps.STEPS:
                self.assertEqual(modes.suggest(s.key), s.mode, s.key)
            self.assertEqual(modes.suggest("story"), "talk")

    def test_done_is_read_from_each_steps_file(self):
        t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t, True)
        p = project.Project(t / "lamp")
        self.assertEqual(list(p._outputs()), steps.ORDER)
        for s in steps.STEPS:
            self.assertTrue(str(s.output(p)).startswith(str(p.root)), s.key)


class TestWhenAStepHasNothingToDo(unittest.TestCase):
    def brief(self, **kw):
        return mock.Mock(**{"no_parts": False, "parts": ["esp32_devkit_v1"], **kw})

    def test_no_parts(self):
        b = self.brief(no_parts=True, parts=[])
        for key, verb in (("electrical", "draw"), ("wiring", "wire"), ("firmware", "program")):
            self.assertIn(verb, steps.not_needed(key, b))
            self.assertFalse(steps.asks_model(key, b))
        self.assertIsNone(steps.not_needed("enclosure", b))
        self.assertFalse(steps.asks_model("enclosure", b))   # nothing to place (D172)
        self.assertTrue(steps.asks_model("brief", b))

    def test_with_parts_every_model_step_asks(self):
        b = self.brief()
        for key in steps.ORDER:
            self.assertEqual(steps.asks_model(key, b), key in steps.MODEL_STEPS, key)
            self.assertIsNone(steps.not_needed(key, b), key)

    def test_an_unknown_step_says_which_there_are(self):
        with self.assertRaisesRegex(KeyError, "brief, parts"):
            steps.get("painting")


if __name__ == "__main__":
    unittest.main()
