"""The Art Studio's Designer and Editor (owner, 2026-10-21): 3D printable
models from a kit of shapes, built by code, checked for printing.

Real builds run where CadQuery is installed (it is on the AH531: about half
a minute each there).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import modelkit, staff

HAS_CQ = bool(importlib.util.find_spec("cadquery") and importlib.util.find_spec("OCP"))   # D208: cadquery without its kernel
STAND = {"name": "Pen stand", "shapes": [
    {"shape": "rounded_box", "size": [60, 40, 4], "radius": 5, "at": [0, 0, 0]},
    {"shape": "cylinder", "radius": 9, "height": 30, "at": [0, 0, 4]},
    {"shape": "cylinder", "radius": 6, "height": 40, "at": [0, 0, 6], "op": "cut"}]}


class TestTheKit(unittest.TestCase):
    def test_a_sound_list(self):
        spec = modelkit.validate(STAND)
        self.assertEqual([s["shape"] for s in spec.shapes], ["rounded_box", "cylinder", "cylinder"])
        self.assertEqual(spec.shapes[0]["rotate"], [0.0, 0.0, 0.0])

    def test_what_cannot_be_made_says_why(self):
        bad = [
            ({"name": "", "shapes": STAND["shapes"]}, "name"),
            ({"name": "x", "shapes": []}, "at least one shape"),
            ({"name": "x", "shapes": [{"shape": "torus", "radius": 3}]}, "not in the kit"),
            ({"name": "x", "shapes": [{"shape": "box", "size": [10, 10]}]}, "3 numbers"),
            ({"name": "x", "shapes": [{"shape": "box", "size": [10, 10, 0.1]}]}, "between"),
            ({"name": "x", "shapes": [{"shape": "cylinder", "radius": 3}]}, "needs height"),
            ({"name": "x", "shapes": [{"shape": "box", "size": [5, 5, 5], "op": "cut"}]}, "first shape"),
            ({"name": "x", "shapes": [{"shape": "rounded_box", "size": [10, 10, 5], "radius": 5}]},
             "under half"),
            ({"name": "x", "shapes": [{"shape": "box", "size": [5, 5, 5], "op": "glue"}]}, "add or cut"),
        ]
        for doc, words in bad:
            with self.assertRaises(modelkit.ModelError, msg=words) as cm:
                modelkit.validate(doc)
            self.assertIn(words, str(cm.exception))

    def test_code_writes_the_script(self):
        text = modelkit.script(modelkit.validate(STAND))
        self.assertIn("import cadquery as cq", text)
        self.assertIn(".edges('|Z').fillet(5.0)", text)
        self.assertIn("model = model.union(s2)", text)
        self.assertIn("model = model.cut(s3)", text)
        self.assertTrue(text.rstrip().endswith("angularTolerance=0.1)"))
        compile(text, "model.py", "exec")

    def test_the_size_the_shapes_add_up_to(self):
        self.assertEqual(modelkit.expected_size(modelkit.validate(STAND)), [60.0, 40.0, 34.0])
        turned = json.loads(json.dumps(STAND))
        turned["shapes"][1]["rotate"] = [0, 90, 0]
        self.assertIsNone(modelkit.expected_size(modelkit.validate(turned)))

    def test_on_the_roster(self):
        for key in ("art_studio.designer", "art_studio.editor"):
            self.assertTrue(staff.STAFF[key].working, key)


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def tearDown(self):
        self._env.stop(); self.t.cleanup()


@unittest.skipUnless(HAS_CQ, "CadQuery is not installed here")
class TestRealBuilds(AHome):
    def test_a_sphere_is_a_solid(self):
        # D224, 2026-11-05: CadQuery's mesh of a sphere had a hole at each pole
        # (its two pole vertices written as 0.0 and -0.0), and every model with
        # a sphere failed the Editor as "not a valid solid".
        doc = {"name": "Ball on a plate", "shapes": [
            {"shape": "plate", "size": [40, 40], "thickness": 4},
            {"shape": "sphere", "radius": 10, "at": [0, 0, 12]}]}
        out, results = modelkit.build(self.cfg, doc)
        self.assertEqual({r.name: r.status for r in results}["solid"], "PASS",
                         [(r.name, r.detail) for r in results])

    def test_the_stand_is_built_and_passes_the_editor(self):
        out, results = modelkit.build(self.cfg, STAND)
        self.assertEqual({r.name: r.status for r in results},
                         {"model_made": "PASS", "solid": "PASS", "thickness": "PASS",
                          "fits_printer": "PASS", "size_as_asked": "PASS"})
        for f in ("spec.json", "model.py", "model.stl", "checks.json", "model-iso.png"):
            self.assertTrue((out / f).is_file(), f)
        self.assertTrue(modelkit.models(self.cfg)[0]["passed"])

    def test_the_editor_fails_too_thin_and_too_big(self):
        thin = {"name": "Thin", "shapes": [{"shape": "box", "size": [300, 20, 0.6]}]}
        out, results = modelkit.build(self.cfg, thin)
        got = {r.name: r.status for r in results}
        self.assertEqual(got["thickness"], "FAIL")          # 0.6 mm against 1.2 mm
        self.assertEqual(got["fits_printer"], "FAIL")       # 300 mm against 250 mm
        self.assertFalse(modelkit.models(self.cfg)[0]["passed"])


class TestNoCadQuery(AHome):
    def test_it_says_so(self):
        with mock.patch("nemo.checks.runners._run",
                        return_value=(1, "", "ModuleNotFoundError: No module named 'cadquery'")):
            out, results = modelkit.build(self.cfg, STAND)
        self.assertEqual(results[0].status, "FAIL")
        self.assertIn("CadQuery is not installed", results[0].detail)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_shapes_from_the_form(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        app = A.NemoApp(); app.update()
        try:
            w = A.ArtStudio(app); app.update()
            w.name.insert(0, "Stand")
            w.kind.set("plate"); w.fields["dims"].insert(0, "60 40 4"); w.add_shape()
            w.kind.set("cylinder"); w.fields["dims"].delete(0, "end")
            w.fields["dims"].insert(0, "9 30"); w.fields["at"].delete(0, "end")
            w.fields["at"].insert(0, "0 0 4"); w.add_shape()
            w.kind.set("cylinder"); w.fields["dims"].delete(0, "end")
            w.fields["dims"].insert(0, "nine"); w.add_shape()          # not a number
            self.assertEqual([s["shape"] for s in w.shapes], ["plate", "cylinder"])
            self.assertEqual(w.shapes[1]["radius"], 9.0)
            self.assertIn("Not added", w.hint.cget("text"))
            self.assertEqual(len(w.tree.get_children()), 2)
            w.tree.selection_set("1"); w.remove_shape()
            self.assertEqual(len(w.shapes), 1)
            w.destroy()
        finally:
            app.destroy()


class TestALetteredModelsSize(unittest.TestCase):
    """2026-11-08: a key tag's size check was SKIPPED though its size is plain:
    70 x 25 mm, 3 mm thick, 1 mm of raised letters."""

    def test_letters_within_the_base_are_measured(self):
        from nemo import artstudio, modelkit
        doc = artstudio.request("Shed Key Tag", "tag", {"text": "SHED", "width": 70, "height": 25})
        spec = modelkit.validate(doc)
        self.assertIsNone(modelkit.expected_size(spec))
        self.assertEqual(modelkit.lettered_size(spec), [70.0, 25.0, 4.0])
        turned = modelkit.validate({"name": "Turned", "shapes": [
            {"shape": "plate", "size": [40, 20], "thickness": 3},
            {"shape": "text", "text": "AB", "size": 10, "depth": 1, "at": [0, 0, 3],
             "rotate": [0, 0, 90]}]})
        self.assertIsNone(modelkit.lettered_size(turned))           # still not judged


if __name__ == "__main__":
    unittest.main()
