"""Employee profiles (owner, 2026-11-04: "improve employees profiles"): a
card of what Nemo knows about each employee, opened from its portrait."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import profiles, toolkit
from nemo.config import Config
from nemo.staff import STAFF
from nemo.steps import STEPS


class TestTheFacts(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load(Path("/nonexistent"))

    def test_every_employee_has_one(self):
        for key in STAFF:
            p = profiles.profile(key, self.cfg)
            self.assertEqual((p.title, p.job), (STAFF[key].title, STAFF[key].job))
            self.assertTrue(p.introduction.startswith("This is the"))

    def test_its_steps_are_the_tables_with_this_machines_model(self):
        p = profiles.profile("workshop.designer", self.cfg)
        owned = [s for s in STEPS if s.owner == "workshop.designer"]
        self.assertEqual([s.name for s in p.steps], [s.name for s in owned])
        for line, step in zip(p.steps, owned):
            self.assertEqual(line.uses_model, step.uses_model)
            if step.uses_model:
                self.assertEqual(line.model, self.cfg.mode(step.mode)["model"])
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": "desktop"}):
            desk = profiles.profile("workshop.designer", self.cfg)
        self.assertIn("qwen3-8b", [s.model for s in desk.steps])          # the desktop's design model

    def test_the_tools_are_the_tools_checks_and_only_when_asked(self):
        self.assertIsNone(profiles.profile("library.writer", self.cfg).tools)
        need = toolkit.Need("a thing", lambda cfg: (False, "not here"))
        with mock.patch.dict(toolkit.NEEDS, {"library.writer": (need,)}):
            p = profiles.profile("library.writer", self.cfg, tools=True)
        self.assertEqual([(t.need, t.ok, t.detail) for t in p.tools], [("a thing", False, "not here")])
        self.assertEqual(p.status, profiles.NEEDS)

    def test_a_look_that_fails_is_said_not_raised(self):
        def broken(cfg):
            raise OSError("no network")
        with mock.patch.dict(toolkit.NEEDS, {"library.writer": (toolkit.Need("a site", broken),)}):
            p = profiles.profile("library.writer", self.cfg, tools=True)
        self.assertFalse(p.tools[0].ok)
        self.assertIn("could not be checked", p.tools[0].detail)

    def test_status(self):
        unbuilt = next(k for k, e in STAFF.items() if not e.working)
        self.assertEqual(profiles.profile(unbuilt, self.cfg).status, profiles.NOT_BUILT)
        with mock.patch.dict(toolkit.NEEDS, {"library.writer": (toolkit.Need("x", lambda c: (True, "ok")),)}):
            self.assertEqual(profiles.profile("library.writer", self.cfg, tools=True).status, profiles.READY)


@unittest.skipUnless(_sandbox.has_display(), "needs a display")
class TestTheCard(unittest.TestCase):
    def setUp(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name)); env.start()
        self.addCleanup(env.stop)
        self.app = A.NemoApp(); self.app.update(); self.addCleanup(self.app.destroy)
        self.room = self.app.open_department("library"); self.app.update()
        self.room.end_introductions(); self.app.update()

    def test_a_portrait_click_opens_its_card_and_escape_closes_it(self):
        r = self.room
        face = r.canvas.find_withtag("face:writer")
        self.assertTrue(face)                                       # ring, face, name, plate
        p = r.show_profile("writer"); self.app.update()
        self.assertEqual(p.title, "Writer")
        self.assertTrue(r.canvas.find_withtag("profile"))
        self.assertIs(r.focus_get(), r.canvas)                     # so Esc reaches it
        r.canvas.event_generate("<Escape>"); self.app.update()
        self.assertFalse(r.canvas.find_withtag("profile"))

    def test_during_an_introduction_a_click_is_the_next_line_not_a_card(self):
        r = self.room
        r.introduce(); self.app.update()
        self.assertIsNone(r.show_profile("writer"))
        self.assertFalse(r.canvas.find_withtag("profile"))
        r.end_introductions()

    def test_the_tools_look_is_a_timer_that_dies_with_the_room(self):
        r = self.room
        r.show_profile("editor"); self.app.update_idletasks()
        job = r._profile_job
        self.assertTrue(job)
        with mock.patch.object(r, "after_cancel", wraps=r.after_cancel) as cancel:
            r.destroy()
        self.assertIn(job, {c.args[0] for c in cancel.call_args_list})

    def test_the_card_survives_a_redraw(self):
        r = self.room
        r.show_profile("writer"); self.app.update()
        r._draw(r.W + 100, r.H); self.app.update()
        self.assertTrue(r.canvas.find_withtag("profile"))


if __name__ == "__main__":
    unittest.main()
