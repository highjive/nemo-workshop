"""Concepts built by code from an object's anatomy (owner, 2026-11-04: "concept
drawings dont look like what its supposed to"; "remove blockout"; he chose
code-built shapes). nemo/anatomy.py. Figures here are invented for the test.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import anatomy, blockout
from nemo.project import Brief

HAS_NUMPY = bool(importlib.util.find_spec("numpy"))


def brief(**kw):
    b = dict(name="Prop", function="A replica flintlock blunderbuss for a stage play",
             shape_size_mm=[700.0, 60.0, 160.0], shape_facts={"barrel_mm": 360.0, "muzzle_bore_mm": 30.0})
    b.update(kw)
    return Brief(**b)


def by_label(doc):
    return {s["label"]: s for s in doc["shapes"]}


class TestWhichObject(unittest.TestCase):
    def test_long_guns_are_known_by_their_words(self):
        for words in ("a blunderbuss", "replica Blunderbust gun", "a flintlock musket",
                      "an old rifle", "a musketoon prop"):
            self.assertEqual(anatomy.family_of(words).key, "long_gun", words)
        for words, key in (("a flintlock pistol", "pistol"), ("a prop sword", "sword"),
                           ("a cutlass for a pirate costume", "sword"),
                           ("a scale model of a lighthouse", "lighthouse"),
                           ("a model space rocket", "rocket"), ("a doll's house", "house"),
                           ("a little cottage", "house")):
            self.assertEqual(anatomy.family_of(words).key, key, words)
        for words in ("a trumpet", "a garden gnome", "a statue of a horse"):
            self.assertIsNone(anatomy.family_of(words), words)

    def test_an_unknown_object_or_no_size_is_said_not_guessed(self):
        with self.assertRaisesRegex(anatomy.UnknownObject, "only these kinds of object yet: pistol"):
            anatomy.build(brief(name="Gnome", function="a replica of a garden gnome"), [500, 100, 100], False)
        with self.assertRaisesRegex(anatomy.UnknownObject, "real size"):
            anatomy.build(brief(), [], False)


class TestTheLongGun(unittest.TestCase):
    def test_its_overall_size_is_the_briefs(self):
        for detail in (False, True):
            doc, _ = anatomy.build(brief(), [700, 60, 160], detail)
            lo, hi = blockout.bounds(doc)
            self.assertAlmostEqual(hi[0] - lo[0], 700, delta=0.6)
            self.assertAlmostEqual(lo[2], 0, delta=0.01)                 # the butt on the ground
            self.assertAlmostEqual(hi[1] - lo[1], 60, delta=2.1)         # the butt plate is 1 proud
            self.assertAlmostEqual(hi[2] - lo[2], 160, delta=1.1)
            self.assertAlmostEqual(hi[0], 350, delta=0.6)                # the muzzle at +x

    def test_the_parts_where_a_gun_has_them(self):
        doc, _ = anatomy.build(brief(), [700, 60, 160], False)
        p = by_label(doc)
        lo_b, hi_b = blockout.extent(p["Barrel"])
        lo_m, hi_m = blockout.extent(p["Bell mouth"])
        self.assertAlmostEqual(hi_m[0] - lo_b[0], 360, delta=0.5)        # the barrel's given length
        self.assertAlmostEqual(p["Bell mouth"]["top_radius"], 30 / 2 + anatomy.LONG_GUN_ESTIMATES["muzzle_wall"])
        butt = blockout.extent(p["Butt"])
        lock = blockout.extent(p["Lock"])
        self.assertLess(butt[1][0], lock[0][0] + 1)                      # the butt behind the lock
        self.assertLess(lock[1][0], hi_m[0])                             # the lock behind the muzzle
        self.assertGreater(lo_b[2], butt[0][2])                          # the barrel above the butt's toe
        pts = p["Butt"]["points"]
        self.assertGreater(pts[3][1], pts[0][1])                         # tall at the heel, toe on the ground

    def test_more_detail_adds_parts_and_nothing_floats_or_hides(self):
        a, _ = anatomy.build(brief(), [700, 60, 160], False)
        b, _ = anatomy.build(brief(), [700, 60, 160], True)
        self.assertLess(len(a["shapes"]), len(b["shapes"]))
        for part in ("Trigger", "Lock plate", "Hammer", "Pan", "Ramrod", "Butt plate"):
            self.assertIn(part, by_label(b))
        for doc in (a, b):
            self.assertEqual(blockout.floating(doc), [])
            self.assertEqual(blockout.hidden(doc), [])
            blockout.check(doc)                                          # modelkit takes it

    def test_a_prop_the_barrel_is_solid(self):
        # nemo/safety.py lets a declared prop through: nothing here makes a bore.
        doc, _ = anatomy.build(brief(), [700, 60, 160], True)
        cuts = [s for s in doc["shapes"] if s["op"] == "cut"]
        bore = [s for s in cuts if s["label"] == "Muzzle opening"][0]
        self.assertLessEqual(bore["height"], 26)                         # a shallow recess only
        self.assertLess(bore["height"], 0.1 * 360)
        self.assertEqual({s["label"] for s in cuts}, {"Muzzle opening", "Guard opening"})

    def test_measured_and_estimated_are_said(self):
        _, said = anatomy.build(brief(), [700, 60, 160], False)
        self.assertIn("Measured, from the brief: length, width, height, barrel, muzzle bore", said[0])
        self.assertIn("Estimated (rules of thumb, not measured)", said[0])
        _, said = anatomy.build(brief(shape_facts={}), [700, 0, 0], False)
        for w in ("width", "height", "barrel length", "bore"):
            self.assertIn(w, said[0].split("Estimated")[1], w)

    def test_a_musket_has_no_bell_mouth(self):
        doc, _ = anatomy.build(brief(function="a replica flintlock musket"), [900, 60, 160], False)
        self.assertNotIn("Bell mouth", by_label(doc))


FAMILIES = [("pistol", "A replica flintlock pistol prop", [400, 0, 0]),
            ("sword", "A prop sword for a play", [900, 0, 0]),
            ("lighthouse", "A scale model of a lighthouse", [0, 0, 300]),
            ("rocket", "A scale model of a space rocket", [0, 0, 400]),
            ("house", "A scale model of a cottage", [200, 0, 0]),
            ("long gun", "A replica blunderbuss", [857, 74, 188])]


class TestEveryFamily(unittest.TestCase):
    """Owner, 2026-11-05: "add more families". Each from one size alone (the
    others from its proportions, said as estimates)."""

    def test_its_size_and_nothing_floats_or_hides(self):
        for name, words, size in FAMILIES:
            for detail in (False, True):
                doc, said = anatomy.build(Brief(name=name, function=words, shape_size_mm=size),
                                          size, detail)
                lo, hi = blockout.bounds(doc)
                given = [i for i in range(3) if size[i] > 0][0]
                self.assertAlmostEqual(hi[given] - lo[given], size[given], delta=0.02 * size[given],
                                       msg=(name, detail))
                self.assertAlmostEqual(lo[2], 0, delta=0.01, msg=name)
                self.assertEqual(blockout.floating(doc), [], (name, detail))
                self.assertEqual(blockout.hidden(doc), [], (name, detail))
                blockout.check(doc)
                if sum(1 for v in size if v > 0) == 1:
                    self.assertIn("Estimated", said[0])

    def test_a_prop_sword_is_blunt(self):
        doc, _ = anatomy.build(Brief(name="s", function="a prop sword", shape_size_mm=[900, 0, 0]),
                               [900, 0, 0], True)
        blade = by_label(doc)["Blade"]
        self.assertGreaterEqual(blade["width"], anatomy.EDGE_MM)              # its thickness
        tip = [p for p in blade["points"] if p[0] == max(q[0] for q in blade["points"])]
        self.assertGreaterEqual(abs(tip[0][1] - tip[1][1]), 2 * anatomy.EDGE_MM)   # a flat, no point

    def test_a_prop_pistol_is_solid_too(self):
        doc, _ = anatomy.build(Brief(name="p", function="a flintlock pistol prop",
                                     shape_size_mm=[400, 0, 0]), [400, 0, 0], True)
        bore = by_label(doc)["Muzzle opening"]
        self.assertEqual(bore["op"], "cut")
        self.assertLessEqual(bore["height"], 16)


@unittest.skipUnless(importlib.util.find_spec("cadquery") and importlib.util.find_spec("OCP")
                     and HAS_NUMPY and importlib.util.find_spec("trimesh"), "CadQuery is not installed")
class TestEveryFamilyPrints(unittest.TestCase):
    """Built for real, every face measured (the Editor samples 2000, O39): the
    new families had a sphere's open poles (D224), a pistol grip's corner of
    0.33 mm, a sword ridge of 1.0, a roof rim of 1.08 and a butt join of 0.45
    and then 0.02 mm, all found this way and fixed (2026-11-05)."""

    def test_solid_and_no_wall_under_the_minimum(self):
        import tempfile
        import numpy as np
        import trimesh
        from unittest import mock
        from nemo import modelkit
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))
        with tempfile.TemporaryDirectory() as t, mock.patch.object(cfg, "path", return_value=Path(t)):
            for name, words, size in FAMILIES:
                for detail in (False, True):
                    doc, _ = anatomy.build(Brief(name=name, function=words, shape_size_mm=size),
                                           size, detail)
                    out, res = modelkit.build(cfg, {"name": f"{name} {detail}",
                                                    "shapes": blockout.buildable(doc)["shapes"]})
                    st = {r.name: r.status for r in res}
                    self.assertEqual(st["solid"], "PASS", (name, detail))
                    m = trimesh.load_mesh(str(out / "model.stl"))
                    o, n = m.triangles_center, -m.face_normals
                    hits, idx, _ = m.ray.intersects_location(o + n * 1e-4, n, multiple_hits=False)
                    thin = float((np.linalg.norm(hits - (o + n * 1e-4)[idx], axis=1) + 1e-4).min())
                    self.assertGreaterEqual(thin, 1.2, (name, detail))


@unittest.skipUnless(HAS_NUMPY, "numpy is not installed")
class TestItsDrawing(unittest.TestCase):
    def test_turned_and_prism_parts_draw_true_outlines(self):
        import tempfile
        from PIL import Image
        doc, _ = anatomy.build(brief(), [700, 60, 160], True)
        with tempfile.TemporaryDirectory() as t:
            p = blockout.blueprint_png(doc, Path(t) / "b.png", "test")
            with Image.open(p) as im:
                self.assertEqual(im.size, (960, 640))


if __name__ == "__main__":
    unittest.main()
