"""The Workshop, gone through (owner, 2026-10-21): the Clerk keeps what the
owner chose from the Brief tab's lists, and the Foreman and Timekeeper are
the Library's, shown for the Workshop alone.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

import unittest

from nemo import clerk, foreman, staff, timekeeper, toolkit
from nemo.project import Brief
from test_pipeline import GOOD_BRIEF, PipelineCase, StubRouter


class Recording(StubRouter):
    """Also keeps the user's message it was sent."""

    def ask(self, task, system, user, **kw):
        self.user = user
        return super().ask(task, system, user, **kw)


class TestTheClerk(PipelineCase):
    def chosen_brief(self, **kw):
        b = Brief(name="chest", mcu="rp2040_pico", parts=["rp2040_pico", "rc522"],
                  power="USB 5 V 2 A", supply_ma=2000, envelope_mm=[120, 80, 60], **kw)
        self.project.create(b)
        return b

    def test_what_was_chosen_is_kept_whatever_the_model_writes(self):
        self.chosen_brief()
        r = self.pipe(Recording(GOOD_BRIEF)).stage_brief("an rfid player")
        b = self.project.load_brief()
        # The model wrote esp32 and four parts at USB 1 A; the owner had chosen.
        self.assertEqual((b.mcu, b.parts, b.power, b.supply_ma, b.envelope_mm),
                         ("rp2040_pico", ["rp2040_pico", "rc522"], "USB 5 V 2 A", 2000,
                          [120.0, 80.0, 60.0]))
        # What the owner did not choose is the model's.
        self.assertIn("RFID card player", b.function)
        text = r.render()
        self.assertIn("Clerk: kept as you chose", text)
        self.assertIn("the model had changed mcu, parts, power, supply_ma, envelope_mm", text)

    def test_the_model_is_told_to_leave_them_out(self):
        self.chosen_brief()
        router = Recording(GOOD_BRIEF)
        self.pipe(router).stage_brief("an rfid player")
        self.assertTrue(router.user.startswith("an rfid player"))
        self.assertIn("leave these fields out", router.user)
        self.assertIn("mcu: rp2040_pico", router.user)
        self.assertIn("parts: rp2040_pico, rc522", router.user)

    def test_nothing_chosen_changes_nothing(self):
        self.project.create(Brief(name="x"))
        router = Recording(GOOD_BRIEF)
        r = self.pipe(router).stage_brief("an rfid player")
        self.assertEqual(router.user, "an rfid player")
        self.assertEqual(self.project.load_brief().mcu, "esp32")
        self.assertNotIn("Clerk", r.render())

    def test_no_parts_and_no_power_are_not_choices_to_keep(self):
        b = Brief(name="x", mcu="rp2040_pico", parts=["rp2040_pico"], power="USB",
                  supply_ma=500, no_parts=True, no_power=True)
        self.assertEqual(clerk.decided(b), {})

    def test_on_the_roster_and_checked(self):
        self.assertTrue(staff.STAFF["workshop.clerk"].working)
        self.assertEqual(toolkit.NEEDS["workshop.clerk"], ())


class TestSharedWithTheLibrary(unittest.TestCase):
    def test_the_workshop_s_foreman_and_timekeeper_work(self):
        for key in ("workshop.foreman", "workshop.timekeeper"):
            self.assertTrue(staff.STAFF[key].working, key)
            self.assertIn("Shares the Library's", staff.STAFF[key].job)

    def test_jobs_and_modes_by_department(self):
        step = foreman.step_job("lamp", "wiring")
        story = foreman.Job("story", "fox", "write", "talk", [])
        fw = foreman.step_job("lamp", "firmware")
        self.assertEqual([foreman.department(j) for j in (step, story, fw)],
                         ["workshop", "library", "computer_lab"])
        self.assertEqual(timekeeper.modes_of("workshop"), {"design", "talk"})
        self.assertEqual(timekeeper.modes_of("computer_lab"), {"build"})

    def test_the_queue_for_one_department(self):
        import os, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as t, \
             mock.patch.dict(os.environ, _sandbox.home_env(t)), \
             mock.patch("nemo.config.CONFIG_HOME", Path(t) / ".nemo"):
            from nemo import cli
            with redirect_stdout(io.StringIO()):
                cli.main(["queue", "add", "lamp", "wiring", "firmware"])
                cli.main(["queue", "story", "fox"])
            out = io.StringIO()
            with redirect_stdout(out):
                cli.main(["queue", "--department", "workshop"])
        self.assertIn("lamp: wiring", out.getvalue())
        self.assertNotIn("fox", out.getvalue())
        self.assertNotIn("firmware", out.getvalue())


if __name__ == "__main__":
    unittest.main()
