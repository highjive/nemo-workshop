"""Speed between builds (2026-11-08, after Claude Code Game Studios'
performance-analyst): each timing says which Nemo ran it and on which
machine, a build is compared only with the build before it on the same
machine, and the Doctors say when a job has got slower."""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from test_library_jobs import AHome
from nemo import cli, clinic, stories, timekeeper


def runs(build, seconds, what="slice", machine="desk (win32)", ok=True):
    return [json.dumps({"department": "printshop", "what": what, "seconds": s, "ok": ok,
                        "build": build, "machine": machine}) for s in seconds]


class TestBetweenBuilds(unittest.TestCase):
    def test_a_slower_build_is_said_with_its_figures(self):
        lines = runs("aaa", [10, 11, 10]) + runs("bbb", [15, 16, 15])
        found = timekeeper.changes(lines)
        self.assertEqual(len(found), 1)
        c = found[0]
        self.assertEqual((c.before, c.after, c.before_s, c.after_s), ("aaa", "bbb", 10, 15))
        self.assertIn("1.50x, slower", c.line())

    def test_only_the_same_machine_is_compared(self):
        # The desktop slices in a second what the AH531 takes a minute over.
        lines = runs("aaa", [1, 1, 1], machine="desk (win32)") + runs("bbb", [60, 61, 60],
                                                                     machine="ah531 (linux)")
        self.assertEqual(timekeeper.changes(lines, everything=True), [])

    def test_too_few_runs_failed_runs_and_old_records_are_not_compared(self):
        old = [json.dumps({"department": "printshop", "what": "slice", "seconds": 1, "ok": True})] * 5
        lines = old + runs("aaa", [10, 10, 10]) + runs("bbb", [30, 30])
        self.assertEqual(timekeeper.changes(lines, everything=True), [])
        lines += runs("bbb", [30, 30, 30], ok=False)
        self.assertEqual(timekeeper.changes(lines, everything=True), [])

    def test_a_small_change_is_not_said_unless_asked(self):
        lines = runs("aaa", [10, 10, 10]) + runs("bbb", [11, 11, 11])
        self.assertEqual(timekeeper.changes(lines), [])
        self.assertEqual(len(timekeeper.changes(lines, everything=True)), 1)

    def test_the_latest_build_is_the_one_last_seen(self):
        lines = runs("aaa", [10, 10, 10]) + runs("bbb", [10, 10, 10]) + runs("aaa", [20, 20, 20])
        c = timekeeper.changes(lines)[0]
        # A build run again keeps all its runs: the median of 10,10,10,20,20,20.
        self.assertEqual((c.before, c.after, c.after_s), ("bbb", "aaa", 15))


class TestTimingsSayWhereAndWhich(AHome):
    def setUp(self):
        super().setUp()
        self.b = mock.patch.object(timekeeper, "build", return_value="cafe12345678")
        self.b.start()

    def tearDown(self):
        self.b.stop()
        super().tearDown()

    def recorded(self):
        return [json.loads(x) for x in
                (self.home / ".nemo" / "job-times.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_every_record_names_the_build_and_machine(self):
        timekeeper.record("film", "film", 3.2, True)
        got = self.recorded()[0]
        self.assertEqual(got["build"], "cafe12345678")
        self.assertEqual(got["machine"], timekeeper.machine())

    def test_a_timer_records_failure_and_an_exception(self):
        with timekeeper.Timer("workshop", "step parts") as t:
            t.ok = False
        with self.assertRaises(ValueError):
            with timekeeper.Timer("workshop", "step parts"):
                raise ValueError("x")
        self.assertEqual([r["ok"] for r in self.recorded()], [False, False])

    def test_story_chapters_are_timed(self):
        from test_stories import Model, outline, prose, story
        f = story("A short story about a fox")
        stories.write_story(f, Model([outline(3)], [prose("a"), prose("b"), prose("c")]),
                            say=lambda s: None)
        self.assertEqual([r["what"] for r in self.recorded()], ["story chapter"] * 3)

    def test_the_doctors_say_a_slower_job(self):
        me = timekeeper.machine()
        (self.home / ".nemo" / "job-times.jsonl").write_text(
            "\n".join(runs("aaa", [10, 10, 10], machine=me) + runs("bbb", [20, 20, 20], machine=me))
            + "\n", encoding="utf-8")
        found = [f for f in clinic.records(self.cfg) if "slower" in f.what]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, clinic.LOOK)
        self.assertIn("2.00x", found[0].evidence)

    def test_the_command_says_between_builds(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["times", "--builds"]), 0)
        self.assertIn("Between builds", out.getvalue())


if __name__ == "__main__":
    unittest.main()
