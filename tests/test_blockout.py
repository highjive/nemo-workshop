"""A shaped object's concept as shapes (nemo/blockout.py): the geometry,
checks and drawings. Since 2026-11-04 the shapes are built by code
(nemo/anatomy.py, tests/test_anatomy.py); the model no longer places them.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import blockout as B
from nemo.modelkit import ModelError

HAS_NUMPY = bool(importlib.util.find_spec("numpy"))
HAS_CQ = bool(importlib.util.find_spec("cadquery") and importlib.util.find_spec("OCP"))


def gun():
    """An invented two-part object: a stock, and a barrel lying along x."""
    return {"name": "gun", "shapes": [
        {"shape": "box", "op": "add", "size": [80, 20, 30], "at": [-60, 0, 0],
         "rotate": [0, 0, 0], "label": "stock"},
        {"shape": "cylinder", "op": "add", "radius": 8, "height": 120, "at": [-20, 0, 15],
         "rotate": [0, 90, 0], "label": "barrel"}]}


def wedge():
    return {"shape": "prism", "op": "add", "points": [[0, 0], [100, 30], [100, 60], [0, 40]],
            "width": 20, "at": [0, 0, 0], "rotate": [0, 0, 0], "label": "wedge"}


class TestTheShapes(unittest.TestCase):
    def test_a_lying_cylinder_runs_along_x_from_its_at(self):
        lo, hi = B.extent(gun()["shapes"][1])
        self.assertEqual((lo[0], hi[0]), (-20.0, 100.0))
        self.assertEqual((lo[2], hi[2]), (7.0, 23.0))                # z is its axis

    def test_fitted_to_a_size_on_the_floor_and_centred(self):
        doc = gun()
        B.fit(doc, [400, 0, 0])
        lo, hi = B.bounds(doc)
        self.assertAlmostEqual(hi[0] - lo[0], 400, delta=0.1)
        self.assertAlmostEqual(lo[2], 0, delta=0.01)
        self.assertAlmostEqual(lo[0] + hi[0], 0, delta=0.1)
        self.assertEqual(B.fit(gun(), [1000, 1000, 1000], shrink_only=True), 1.0)

    def test_a_floating_piece_is_refused(self):
        doc = gun()
        doc["shapes"].append({"shape": "box", "op": "add", "size": [50, 3, 3], "at": [0, 80, 0],
                              "rotate": [0, 0, 0], "label": "ramrod"})
        self.assertEqual(B.floating(doc), ["ramrod"])
        with self.assertRaisesRegex(ModelError, "ramrod"):
            B.check(doc)

    def test_the_views_are_drawn(self):
        doc = B.check(gun())
        with tempfile.TemporaryDirectory() as t:
            p = B.views_png(doc, Path(t) / "v.png", "A")
            from PIL import Image
            with Image.open(p) as im:
                self.assertEqual(im.size, (3 * 210 + 40, 210 + 90))
        self.assertEqual([B._seen_as(s, "Side") for s in doc["shapes"]], ["rectangle", "circle"])


@unittest.skipUnless(HAS_NUMPY, "numpy is not installed")
class TestTurnedShapesAndPrisms(unittest.TestCase):
    def test_a_prisms_extent_and_mesh(self):
        lo, hi = B.extent(wedge())
        self.assertEqual((lo, hi), ([0.0, -10.0, 0.0], [100.0, 10.0, 60.0]))
        import trimesh
        m = trimesh.Trimesh(**trimesh.triangles.to_kwargs(B._placed_tris(wedge())))
        m.merge_vertices()
        self.assertTrue(m.is_watertight)
        self.assertAlmostEqual(m.volume, 3500 * 20, delta=0.5)       # its outline's area x width

    def test_a_shape_turned_across_has_its_true_box(self):
        # A trigger guard across the gun (rotate [90, 0, 0]): its box from its
        # triangles. Before 2026-11-04 extent() gave it the box of an upright one.
        ring = {"shape": "cylinder", "op": "add", "radius": 14, "height": 6, "at": [0, 3, 50],
                "rotate": [90, 0, 0]}
        lo, hi = B.extent(ring)
        self.assertAlmostEqual(hi[1] - lo[1], 6, delta=0.01)
        self.assertAlmostEqual(hi[2] - lo[2], 28, delta=0.05)

    def test_a_turned_box_is_no_container(self):
        doc = {"name": "x", "shapes": [
            {"shape": "box", "op": "add", "size": [100, 40, 40], "at": [0, 0, 0], "rotate": [0, 30, 0]},
            {"shape": "box", "op": "add", "size": [10, 10, 10], "at": [0, 0, 60], "rotate": [0, 0, 0]}]}
        self.assertEqual(B.hidden(doc), [])                          # in its outline box, not in it

    def test_the_sketch_is_drawn_from_the_same_numbers(self):
        doc = B.check(gun())
        tris = B.triangles(doc).reshape(-1, 3)
        lo, hi = B.bounds(doc)
        for i in range(3):
            self.assertAlmostEqual(float(tris[:, i].min()), lo[i], delta=0.05)
            self.assertAlmostEqual(float(tris[:, i].max()), hi[i], delta=0.05)
        with tempfile.TemporaryDirectory() as t:
            p = B.sketch_png(doc, Path(t) / "s.png", "A", size=200)
            from PIL import Image
            with Image.open(p) as im:
                self.assertLess(min(im.convert("L").getdata()), 60)


@unittest.skipUnless(HAS_CQ, "CadQuery is not installed")
class TestBuiltForReal(unittest.TestCase):
    def built(self, doc):
        from unittest import mock
        from nemo import modelkit
        from nemo.config import Config
        from nemo.render import read_stl
        with tempfile.TemporaryDirectory() as t:
            cfg = Config.load(Path("/nonexistent"))
            with mock.patch.object(cfg, "path", return_value=Path(t)):
                out, results = modelkit.build(cfg, {"name": doc["name"],
                                                    "shapes": B.buildable(doc)["shapes"]})
            self.assertNotIn("FAIL", [r.status for r in results if r.name in ("model_made", "solid")],
                             [(r.name, r.detail) for r in results])
            tris = read_stl(out / "model.stl").reshape(-1, 3)
            return tris.min(0).tolist(), tris.max(0).tolist()

    def test_what_is_drawn_is_what_cadquery_builds(self):
        doc = B.check(gun())
        lo, hi = B.bounds(doc)
        mlo, mhi = self.built(doc)
        for a, b in zip(mlo + mhi, lo + hi):
            self.assertAlmostEqual(a, b, delta=0.5)

    def test_the_code_built_blunderbuss_too(self):
        # Prism, turned guard, lying cone: CadQuery agrees with the drawing's numbers.
        from nemo import anatomy
        from nemo.project import Brief
        b = Brief(name="Long gun", function="A replica flintlock blunderbuss",
                  shape_size_mm=[500, 50, 120], shape_facts={"barrel_mm": 260})
        doc, _ = anatomy.build(b, b.shape_size_mm, detail=True)
        lo, hi = B.bounds(doc)
        mlo, mhi = self.built(doc)
        for a, b2 in zip(mlo + mhi, lo + hi):
            self.assertAlmostEqual(a, b2, delta=0.6)


if __name__ == "__main__":
    unittest.main()
