"""nemo/workflow.py: the step loop, run without the command line.

`nemo run` and the window (through `nemo run --json`) both go through
run_steps; tests/test_review.py, test_model_failure.py and test_research.py
drive it through the command line. These call it directly, with a stand-in
for the pipeline, so what the loop decides is tested on its own.
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

from nemo import review, workflow
from nemo.checks import FAIL, Result
from nemo.parts import PartsLibrary
from nemo.pipeline import StageResult
from nemo.project import Brief, Project
from nemo.results import load_results

LIB = PartsLibrary.load()
BRIEF = Brief(name="weather box", function="Shows the temperature.", power="USB 5 V 1 A",
              supply_ma=1000, rails=[3.3, 5.0], envelope_mm=[120, 80, 40],
              parts=["esp32_devkit_v1", "bme280"], mcu="esp32_devkit_v1",
              done_when="It shows the temperature.")


class FakePipe:
    """Each stage_<step> passes, unless named in `fail`; calls are kept."""

    def __init__(self, fail=()):
        self.lib, self.fail, self.calls = LIB, set(fail), []

    def __getattr__(self, name):
        if not name.startswith("stage_"):
            raise AttributeError(name)
        step = name[len("stage_"):]

        def run(*args):
            self.calls.append(step)
            return StageResult(step, step not in self.fail, notes=[f"{step} ran"])
        return run


class Case(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        self.project = Project(Path(self.t.name) / "weather-box").create(BRIEF)
        self.said, self.events = [], []
        # The Reviewer lets everything through unless a test says otherwise;
        # no llama-server is asked what is loaded.
        self._patches = [mock.patch.object(review, "before", return_value=([], [])),
                         mock.patch.object(workflow.modes, "current",
                                           return_value=mock.Mock(running=False))]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._env.stop(); self.t.cleanup()

    def run_steps(self, order, pipe=None, model=True, **kw):
        pipe = pipe or FakePipe()
        router = mock.Mock(local_up=mock.Mock(return_value=model))
        rc = workflow.run_steps(self.project, pipe, router, order, say=self.said.append,
                                event=lambda **e: self.events.append(e), **kw)
        return rc, pipe


class TestPlan(Case):
    def test_from_a_step_to_the_end(self):
        self.assertEqual(workflow.plan(self.project, "concept"),
                         ["concept", "enclosure", "firmware", "pack"])

    def test_only_one(self):
        self.assertEqual(workflow.plan(self.project, only="wiring"), ["wiring"])

    def test_by_default_from_the_first_not_done(self):
        self.assertEqual(workflow.plan(self.project)[0], self.project.next_stage())

    def test_an_unknown_step_names_the_real_ones(self):
        with self.assertRaisesRegex(ValueError, "unknown step 'paint'.*brief, parts"):
            workflow.plan(self.project, "paint")


class TestRunSteps(Case):
    def test_every_step_runs_in_order_and_is_saved(self):
        rc, pipe = self.run_steps(workflow.plan(self.project, "parts"))
        self.assertEqual(rc, workflow.OK)
        self.assertEqual(pipe.calls, ["parts", "electrical", "wiring", "concept",
                                      "enclosure", "firmware", "pack"])
        self.assertEqual(set(load_results(self.project.root)), set(pipe.calls))
        states = [(e["stage"], e["state"]) for e in self.events]
        self.assertEqual(states[:2], [("parts", "running"), ("parts", "done")])

    def test_the_brief_is_not_run_here(self):
        rc, pipe = self.run_steps(["brief", "parts"])
        self.assertEqual(pipe.calls, ["parts"])

    def test_a_failed_step_stops_the_run(self):
        rc, pipe = self.run_steps(["parts", "electrical", "wiring"], FakePipe(fail={"electrical"}))
        self.assertEqual(rc, workflow.FAILED)
        self.assertEqual(pipe.calls, ["parts", "electrical"])

    def test_keep_going(self):
        rc, pipe = self.run_steps(["parts", "electrical", "wiring"],
                                  FakePipe(fail={"electrical"}), keep_going=True)
        self.assertEqual(pipe.calls, ["parts", "electrical", "wiring"])

    def test_no_model_stops_at_the_first_step_that_asks_one(self):
        rc, pipe = self.run_steps(["parts", "electrical", "wiring"], model=False)
        self.assertEqual(rc, workflow.NEEDS_MODEL)
        self.assertEqual(pipe.calls, ["parts"])          # parts asks no model
        self.assertEqual(self.events[-1], {"stage": "electrical", "state": "needs_model",
                                           "mode": workflow.modes.suggest("electrical")})

    def test_a_reviewer_stop_means_the_step_never_runs(self):
        stop = Result("review_no_board", FAIL, "no microcontroller board among the parts")
        with mock.patch.object(review, "before", return_value=([stop], [])):
            rc, pipe = self.run_steps(["parts"])
        self.assertEqual(rc, workflow.FAILED)
        self.assertEqual(pipe.calls, [])
        rec = load_results(self.project.root)["parts"]
        self.assertFalse(rec["ok"])
        self.assertEqual(rec["go_back_to"], "brief")
        self.assertIn("Inspector stopped this step before the Workshop Designer began",
                      " ".join(rec["notes"]))

    def test_the_handoffs_are_in_the_work_log(self):
        self.run_steps(["parts"])
        events = [e["event"] for e in review.work_log(self.project.root)]
        # The Writer hands over the assignment before parts (2026-10-21).
        self.assertEqual(events, ["reviewed", "assignment", "started", "passed"])


class TestTheHarnessChecksHaveTheirOwnModule(unittest.TestCase):
    """2026-10-20: the harness checks moved from pipeline.py (where they were
    800 lines of Pipeline static methods) to nemo/checks/harness.py."""

    def test_the_old_names_are_the_moved_functions(self):
        from nemo.checks import harness as hc
        from nemo.pipeline import Pipeline
        names = [n for n in vars(hc) if n.startswith(("check_harness_", "check_pin_"))]
        self.assertGreaterEqual(len(names), 8)
        for n in names:
            self.assertIs(getattr(Pipeline, n), getattr(hc, n), n)

    def test_pipeline_no_longer_writes_them_out(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "pipeline.py").read_text(
            encoding="utf-8")
        self.assertNotIn("def check_harness_", src)
        self.assertNotIn("def _load_harness", src)


if __name__ == "__main__":
    unittest.main()
