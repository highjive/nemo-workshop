"""The Art Studio's Clerk, Writer, Foreman and Timekeeper (owner,
2026-10-22). Builds use a stand-in CadQuery run, except where noted.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import artstudio, foreman, modelkit, staff, timekeeper
from nemo.modelkit import ModelError

CUBE = ("solid c\n" + "".join(
    "facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {x} {y} {z}\n" for x, y, z in t)
    + "endloop\nendfacet\n" for t in (((0, 0, 0), (10, 0, 0), (0, 10, 0)),
                                      ((0, 0, 5), (10, 0, 5), (0, 10, 5)))) + "endsolid c\n")


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        # the timekeeper and clerk keep their files beside the queue
        self._home = mock.patch("nemo.config.CONFIG_HOME", self.t / ".nemo")
        self._home.start()

    def tearDown(self):
        self._home.stop(); self._env.stop()
        shutil.rmtree(self.t, ignore_errors=True)

    def fake_build(self, rc=0):
        def run(cmd, cwd=None, timeout=0):
            if rc == 0:
                (Path(cwd) / "model.stl").write_text(CUBE, encoding="utf-8")
            return rc, "", "boom" if rc else ""
        return run


class TestTheClerk(AHome):
    def test_each_kind_makes_shapes_the_designer_takes(self):
        for kind in artstudio.KINDS:
            v = artstudio.last(kind)
            doc = artstudio.request(f"a {kind}", kind, v)
            self.assertEqual(modelkit.validate(doc).name, f"a {kind}")
            self.assertEqual(doc["from"]["kind"], kind)

    def test_the_box_is_hollow_with_a_floor(self):
        s = artstudio.shapes("box", {"width": 80, "depth": 60, "height": 40, "wall": 2, "floor": 3})
        self.assertEqual(s[1]["op"], "cut")
        self.assertEqual(s[1]["size"], [76, 56, 38])
        self.assertEqual(s[1]["at"], [0, 0, 3])

    def test_choices_are_kept_for_next_time(self):
        v = dict(artstudio.last("pot"), diameter="72")
        artstudio.request("pot", "pot", v)
        self.assertEqual(artstudio.last("pot")["diameter"], 72.0)
        self.assertEqual(artstudio.last("box")["width"], 80)        # untouched: the default

    def test_what_cannot_be_made_is_said(self):
        with self.assertRaises(ModelError) as e:
            artstudio.shapes("box", {"width": 10, "depth": 10, "height": 10, "wall": 5, "floor": 1})
        self.assertIn("no room inside", str(e.exception))
        with self.assertRaises(ModelError):
            artstudio.shapes("plaque", dict(artstudio.last("plaque"), text="A LONG LONG NAME"))
        with self.assertRaises(ModelError):
            artstudio.shapes("vase", {})
        with self.assertRaises(ModelError):
            artstudio.shapes("pot", dict(artstudio.last("pot"), height="tall"))

    def test_letters_too_small_to_print_are_refused(self):
        # 7 % strokes, measured: 14 mm letters had 0.98 mm strokes, under 1.2.
        with self.assertRaises(ModelError) as e:
            artstudio.shapes("plaque", dict(artstudio.last("plaque"), text="HI", letters=14))
        self.assertIn("at least 17 mm", str(e.exception))
        ok = artstudio.shapes("plaque", dict(artstudio.last("plaque"), text="HI", letters=18))
        self.assertEqual(ok[1]["shape"], "text")
        self.assertNotEqual(ok[1].get("op"), "cut")                 # raised, never cut in


class TestTheWriter(AHome):
    def test_the_card(self):
        doc = artstudio.request("Desk tidy", "pot", artstudio.last("pot"))
        with mock.patch("nemo.checks.runners._run", side_effect=self.fake_build()), \
             mock.patch.object(modelkit, "editor_checks", return_value=[]):
            out, _ = modelkit.build(self.cfg, doc)
        (out / "checks.json").write_text(json.dumps(
            [{"name": "solid", "status": "PASS", "detail": "", "items": []}]), encoding="utf-8")
        (out / "print").mkdir()
        (out / "print" / "desk-tidy-0.20mm-PLA-card.txt").write_text(
            "x\nTime      1h 2m\n", encoding="utf-8")
        artstudio.write_about(out, "Pen pot", "For the workbench.")
        text = artstudio.card(out)
        for words in ("Pen pot", "For the workbench.", "Made from   Round pot (diameter 60",
                      "cylinder, cylinder cut", "10.0 x 10.0 x 5.0 mm (measured from the mesh)",
                      "Editor      passed it", "desk-tidy-0.20mm-PLA: 1h 2m"):
            self.assertIn(words, text)
        self.assertEqual((out / "card.txt").read_text(encoding="utf-8"), text)
        artstudio.write_about(out, "", None)                       # empty clears the title
        self.assertTrue(artstudio.card(out).startswith("Desk tidy"))

    def test_never_built(self):
        with self.assertRaises(ModelError):
            artstudio.card(self.t / "nothing")


class TestTheForemanAndTimekeeper(AHome):
    def test_a_model_and_its_slice_are_queued_in_order(self):
        doc = artstudio.request("Desk tidy", "pot", artstudio.last("pot"))
        with mock.patch.object(foreman, "queue_path", return_value=self.t / ".nemo" / "queue.json"):
            foreman.add([foreman.slice_job("desk-tidy")])            # queued first, on purpose
            foreman.add([foreman.model_job(doc)])
            jobs = foreman.order(foreman.load())
            spec = Path(foreman.load()[1].argv[2])
        self.assertEqual([foreman.department(j) for j in foreman.load()], ["printshop", "art_studio"])
        self.assertEqual([j.kind for j in jobs], ["slice", "model"])    # same owner: queued order
        self.assertEqual(json.loads(spec.read_text(encoding="utf-8"))["from"]["kind"], "pot")
        self.assertEqual(jobs[1].argv[:2], ["model", "build"])

    def test_builds_and_slices_are_timed(self):
        doc = {"name": "cube", "shapes": [{"shape": "box", "size": [10, 10, 5]}]}
        with mock.patch.object(modelkit, "editor_checks", return_value=[]):
            with mock.patch("nemo.checks.runners._run", side_effect=self.fake_build()):
                modelkit.build(self.cfg, doc)
            with mock.patch("nemo.checks.runners._run", side_effect=self.fake_build(1)):
                modelkit.build(self.cfg, doc)
        found = timekeeper.job_times("art_studio")
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].what, len(found[0].seconds), found[0].failed), ("model build", 1, 1))
        self.assertIn("1 run(s)", timekeeper.describe_jobs(found))
        self.assertEqual(timekeeper.job_times("printshop"), [])

    def test_the_team_is_all_working(self):
        self.assertEqual([e.title for e in staff.team("art_studio") if not e.working], [])
        from nemo import toolkit
        for key in ("art_studio.writer", "art_studio.foreman", "art_studio.timekeeper"):
            self.assertTrue(all(n.check(self.cfg)[0] for n in toolkit.NEEDS[key]), key)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_from_a_list_queue_and_card(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        app = A.NemoApp(); app.update()
        try:
            app.cfg = self.cfg
            w = A.ArtStudio(app); app.update()
            self.assertTrue(w.from_list("box", artstudio.last("box")))
            self.assertEqual(len(w.tree.get_children()), 2)
            self.assertEqual(w.name.get(), "Open box")
            self.assertFalse(w.from_list("box", dict(artstudio.last("box"), wall=50)))
            self.assertIn("no room inside", w.result.get("1.0", "end"))
            with mock.patch.object(foreman, "queue_path", return_value=self.t / ".nemo" / "q.json"):
                w.queue_it()
                self.assertEqual(foreman.load()[0].owner, "open-box")
            self.assertIsNone(w.write_card(ask=lambda *a: "x"))       # not built yet
            with mock.patch("nemo.checks.runners._run", side_effect=self.fake_build()), \
                 mock.patch.object(modelkit, "editor_checks", return_value=[]):
                modelkit.build(self.cfg, w._doc())
            answers = iter(["Parts tray", "Screws, sorted."])
            text = w.write_card(ask=lambda *a: next(answers))
            self.assertIn("Parts tray", text)
            self.assertIn("Made from   Open box", text)
            w.destroy()
        finally:
            app.destroy()


class TestTheStandSitsFlat(unittest.TestCase):
    """2026-11-04: the leaning back, tipped about the middle of its foot, put
    one edge 0.52 mm under the base (4 mm, 15 degrees); the stand rested on
    that edge with its base off the bed, and OrcaSlicer would not slice it."""

    def lowest(self, values):
        import math
        back = artstudio.shapes("stand", values)[1]
        x, y, z = back["at"]
        lean = math.radians(back["rotate"][0])
        t = back["size"][1]
        # the back's two bottom edges, tipped about the middle of its foot
        return min(z + s * (t / 2) * math.sin(lean) for s in (-1, 1))

    def test_the_back_does_not_go_under_the_base(self):
        for lean in (0, 15, 40):
            for thick in (3, 4, 8):
                self.assertGreaterEqual(self.lowest({"lean": lean, "thickness": thick}), -1e-6,
                                        (lean, thick))

    def test_it_still_sinks_into_the_base(self):
        back = artstudio.shapes("stand", {"lean": 15, "thickness": 4})[1]
        self.assertLess(back["at"][2], 4)


if __name__ == "__main__":
    unittest.main()
