"""No power needed, No parts needed (owner's request, 2026-10-18), and
D185: saving the brief from the window dropped the Reviewer findings the
owner had accepted."""
from __future__ import annotations

import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import review
from nemo.parts import PartsLibrary
from nemo.project import Brief, Project
from test_pipeline import PipelineCase, StubRouter

LIB = PartsLibrary.load()
HOLDER = Brief(name="pen holder", function="A desk holder for six pens.",
               envelope_mm=[90, 60, 80], done_when="Six pens stand in it.",
               no_power=True, no_parts=True)


def project(b):
    return Project(Path(tempfile.mkdtemp()) / "p").create(b)


class TestTheBrief(unittest.TestCase):
    def test_complete_without_power_or_parts(self):
        self.assertEqual(HOLDER.complete, (True, []))
        self.assertFalse(Brief(name="x", function="f", envelope_mm=[1, 1, 1],
                               done_when="d").complete[0])

    def test_the_window_does_not_ask_for_a_supply(self):
        from nemo.gui import controller as C
        self.assertEqual(C.brief_problems(HOLDER), [])


class TestTheReviewer(unittest.TestCase):
    def test_nothing_to_stop(self):
        for step in ("parts", "electrical", "concept", "enclosure"):
            p = project(HOLDER)
            from nemo.pipeline import StageResult
            from nemo.results import save_result
            save_result(p.root, StageResult("parts", True))
            if step == "enclosure":
                # A holder still has a case to choose (the Artist's concept,
                # 2026-10-20); with no parts the concepts differ in style only.
                from nemo import concept, enclosure
                box = enclosure.box_for(HOLDER.envelope_mm, {"min_wall_mm": 1.2, "nozzle_mm": 0.4})
                sig = concept.signature([], HOLDER.envelope_mm)
                concept.save(p.root, concept.make([], box), sig, box, [])
                concept.choose(p.root, "B", sig)
            self.assertEqual(review.before(step, p, LIB)[0], [], step)

    def test_no_parts_with_parts_listed(self):
        b = Brief(**{**HOLDER.__dict__, "parts": ["ws2812b_ring8"]})
        names = [r.name for r in review.before("parts", project(b), LIB)[0]]
        self.assertIn("review_parts_but_none", names)

    def test_no_power_with_parts_that_need_it(self):
        b = Brief(**{**HOLDER.__dict__, "no_parts": False,
                     "parts": ["esp32_devkit_v1", "ws2812b_ring8"], "mcu": "esp32_devkit_v1",
                     "function": "A lamp whose LEDs glow."})
        stops = {r.name: r for r in review.before("parts", project(b), LIB)[0]}
        self.assertIn("review_parts_need_power", stops)
        self.assertIn("ws2812b_ring8", stops["review_parts_need_power"].detail)
        fixes = review.fixes("parts_need_power", b, LIB)
        # D189: removing them comes first; unticking the owner's answer second.
        self.assertEqual(fixes[0].key, "review_drop_powered")
        self.assertEqual(fixes[1].set_fields, {"no_power": False})


class TestTheSteps(PipelineCase):
    def test_nothing_to_draw_wire_or_program_and_the_supply_checks_pass(self):
        self.project.create(HOLDER)
        pipe = self.pipe(StubRouter())
        parts = pipe.stage_parts()
        self.assertTrue(parts.ok, parts.render())
        self.assertIn("no power needed", parts.render())
        for step in ("electrical", "wiring", "firmware"):
            r = getattr(pipe, f"stage_{step}")()
            self.assertTrue(r.ok, step)
            self.assertIn("No parts are needed", r.render())

    def test_no_model_is_needed_for_them(self):
        from nemo.cli import needs_model
        self.project.create(HOLDER)
        for step in ("electrical", "wiring", "firmware", "enclosure"):
            self.assertFalse(needs_model(step, self.project), step)
        self.project.save_brief(Brief(**{**HOLDER.__dict__, "no_parts": False,
                                         "parts": ["esp32_devkit_v1"]}))
        self.assertTrue(needs_model("electrical", self.project))

    def test_an_empty_tray_is_a_valid_cadquery_script(self):
        from nemo import enclosure
        box = enclosure.Box(90, 60, 80, 1.2)
        script = enclosure.cadquery_script([], [], box)
        compile(script, "housing.py", "exec")
        self.assertIn('exporters.export(housing, "housing.stl")', script)
        self.assertNotIn("notch", script)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        from nemo.config import Config
        root = Config.load().path("paths.projects") / "holder"
        Project(root).create(Brief(**{**HOLDER.__dict__, "accepted": ["unexplained_parts"]}))
        self.app = A.NemoApp(); self.app.update()
        self.app.refresh_projects(select="holder"); self.app.update()

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def test_the_ticks_are_shown_and_saved(self):
        self.assertTrue(self.app.no_power.get()); self.assertTrue(self.app.no_parts.get())
        self.app.no_power.set(False)
        b = self.app._form_brief()
        self.assertFalse(b.no_power); self.assertTrue(b.no_parts)

    def test_d185_what_the_owner_accepted_survives_a_save(self):
        self.assertEqual(self.app._form_brief().accepted, ["unexplained_parts"])
        self.assertFalse(self.app.brief_changed())          # nothing typed, nothing changed
