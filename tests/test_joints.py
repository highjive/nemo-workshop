"""Joints, made by the Art Studio's Designer (owner, 2026-11-04: "objects for 3D printing including any
joints needed"; O38): a model too big for the printer, split into pieces
that fit and pinned back together. Planned on the mesh by code, cut by
CadQuery where it is installed.
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

from nemo import joints, modelkit

HAS_MESH = bool(importlib.util.find_spec("trimesh") and importlib.util.find_spec("numpy"))
HAS_CQ = bool(importlib.util.find_spec("cadquery") and importlib.util.find_spec("OCP"))
VOLUME = [250, 250, 260]


def box(x, y, z, at=(0, 0, 0)):
    import trimesh
    m = trimesh.creation.box([x, y, z])
    m.apply_translation([at[0], at[1], at[2] + z / 2])
    return m


@unittest.skipUnless(HAS_MESH, "needs trimesh and numpy")
class TestTheFace(unittest.TestCase):
    def test_inside_and_distance_on_a_square(self):
        segs = joints.section(box(40, 20, 10), 0, 0.0)            # 20 x 10 in y, z
        got = joints.inside([(0, 5), (9, 5), (11, 5), (0, -1)], segs)
        self.assertEqual(list(got), [True, True, False, False])
        d = joints.edge_distance([(0, 5), (9, 5)], segs)
        self.assertAlmostEqual(float(d[0]), 5.0, places=3)
        self.assertAlmostEqual(float(d[1]), 1.0, places=3)

    def test_the_face_area(self):
        self.assertAlmostEqual(joints.area(box(40, 20, 10), 0, 0.0), 200, delta=4)
        self.assertEqual(joints.area(box(40, 20, 10), 0, 100.0), 0.0)


@unittest.skipUnless(HAS_MESH, "needs trimesh and numpy")
class TestThePlan(unittest.TestCase):
    def test_a_long_board_two_pieces_two_pins_in_the_middle_of_its_thickness(self):
        p = joints.plan(box(400, 80, 8), VOLUME, 1.2)
        self.assertEqual((p.axes, p.pieces), ([0], 2))
        self.assertEqual(len(p.cuts[0].pins), 2)
        for pin in p.cuts[0].pins:
            self.assertAlmostEqual(pin.v, 4.0, places=6)            # centred: 8 mm board
            need = pin.diameter / 2 + p.clearance + 1.2
            self.assertLessEqual(abs(pin.u) + need, 40 + 1e-6)     # solid round it
        a, b = p.cuts[0].pins
        self.assertGreater(abs(a.u - b.u), 20)                      # far apart: no turning

    def test_every_piece_fits(self):
        p = joints.plan(box(700, 60, 20), VOLUME, 1.2)
        self.assertEqual(p.pieces, 3)
        self.assertTrue(all(b - a <= 250 - 2 * joints.EDGE_MM for a, b in p.ranges(0)))

    def test_too_big_two_ways_is_a_grid_with_pins_in_every_joint(self):
        # Owner, 2026-11-04: "if parts are too large for printer have them
        # separated". A 400 x 300 slab: 2 x 2 pieces, four joints, each pinned,
        # and no pin within reach of the other cut.
        p = joints.plan(box(400, 300, 12), VOLUME, 1.2)
        self.assertEqual((p.axes, p.pieces), ([0, 1], 4))
        j = joints.joint_pins(p)
        self.assertEqual(sorted(j), [(1, 2), (1, 3), (2, 4), (3, 4)])
        self.assertTrue(all(len(pins) == 2 for pins in j.values()), j)
        for c in p.cuts:
            other = [o.at for o in p.cuts if o.axis != c.axis][0]
            for q in c.pins:
                # On an x cut, u is y; on a y cut, u is x: across the other cut.
                self.assertGreater(abs(q.u - other), q.diameter / 2 + p.clearance + 1.2 - 1e-6)
        for n, spans in p.cells():
            self.assertTrue(all(b - a <= 250 for a, b in spans))

    def test_pieces_that_meet_on_nothing_are_not_a_joint(self):
        # An L cut in four: the cell beside both arms holds none of it. It is
        # no piece, and nothing is said about joining it.
        import trimesh
        m = trimesh.util.concatenate([box(400, 60, 10, at=(0, -120, 0)),
                                      box(60, 300, 10, at=(-170, 0, 0))])
        p = joints.plan(m, VOLUME, 1.2)
        self.assertEqual(p.empty, [[1, 1, 0]])                      # the corner: no piece
        self.assertEqual(p.pieces, 3)
        self.assertEqual(sorted(joints.joint_pins(p)), [(1, 2), (1, 3)])
        self.assertFalse([n for n in p.notes if "glue" in n], p.notes)

    def test_too_thin_for_a_pin_is_glued_and_said(self):
        p = joints.plan(box(400, 80, 3), VOLUME, 1.2)
        self.assertEqual(p.cuts[0].pins, [])
        self.assertIn("glue", " ".join(p.notes))

    def test_what_it_will_not_split(self):
        with self.assertRaisesRegex(joints.SplitError, "fits the printer whole"):
            joints.plan(box(100, 80, 8), VOLUME, 1.2)

    def test_the_cut_misses_a_rib_in_its_way(self):
        # A rib across the board where it would be cut evenly: the cut moves
        # off it, as a sign's cut moved off a letter (2026-11-04).
        import trimesh
        m = trimesh.util.concatenate([box(400, 80, 8), box(6, 80, 20, at=(0, 0, 0))])
        p = joints.plan(m, VOLUME, 1.2)
        self.assertGreaterEqual(abs(p.cuts[0].at), 3.0)            # at or past the rib's face


class TestTheScript(unittest.TestCase):
    def plan(self):
        return joints.Plan([-200, -40, 0], [200, 40, 8],
                           [joints.Cut(0, 0.0, [joints.Pin(-30, 4, 5.0), joints.Pin(30, 4, 5.0)])],
                           0.15, 8.0)

    def test_code_writes_holes_pieces_and_pins(self):
        spec = modelkit.validate({"name": "Board", "shapes": [{"shape": "box", "size": [400, 80, 8]}]})
        text = joints.script(modelkit.script(spec), self.plan())
        self.assertNotIn("'model.stl'", text)                       # the whole model is not rewritten
        self.assertEqual(text.count("model = model.cut(along(0, 2.65, 17.0, [0.0, -30.0, 4.0]))")
                         + text.count("model = model.cut(along(0, 2.65, 17.0, [0.0, 30.0, 4.0]))"), 2)
        self.assertIn("'pieces/piece-1.stl'", text)
        self.assertIn("'pieces/piece-2.stl'", text)
        self.assertIn("'pieces/pins.stl'", text)
        self.assertIn("extrude(15.4)", text)                        # 0.3 mm short each end

    def test_the_assembly_note_says_the_fit_is_a_rule_of_thumb(self):
        text = joints.assembly("Board", self.plan())
        self.assertIn("rule of thumb", text)
        self.assertIn("lying on their flat side", text)
        self.assertIn("piece-1 to piece-2: 2 pin(s), 5 mm", text)


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def tearDown(self):
        self._env.stop(); self.t.cleanup()


class TestWhereItIsOffered(AHome):
    def test_the_editor_points_to_the_joiner(self):
        from nemo.checks import FAIL
        spec = modelkit.validate({"name": "Long", "shapes": [{"shape": "box", "size": [400, 20, 8]}]})
        out = Path(self.t.name) / "m"; out.mkdir()
        with mock.patch("nemo.checks.runners.solid") as s, mock.patch("nemo.checks.runners.thickness") as t, \
             mock.patch("nemo.render.read_stl") as r:
            import numpy as np
            s.return_value = t.return_value = modelkit_result()
            r.return_value = np.array([[-200, -10, 0], [200, 10, 8]], dtype=float)
            results = modelkit.editor_checks(self.cfg, out, spec)
        fits = next(x for x in results if x.name == "fits_printer")
        self.assertEqual(fits.status, FAIL)
        self.assertIn("nemo model split Long", " ".join(fits.items))

    def test_the_print_shop_lists_the_pieces(self):
        from nemo import printshop
        d = self.cfg.path("paths.models") / "long" / "pieces"; d.mkdir(parents=True)
        for f in ("piece-1.stl", "piece-2.stl", "pins.stl"):
            (d / f).write_bytes(b"solid x\nendsolid x\n")
        names = {m.name for m in printshop.models(self.cfg)}
        self.assertEqual(names, {"long-piece-1", "long-piece-2", "long-pins"})

    def test_split_says_when_nothing_is_built(self):
        with self.assertRaisesRegex(joints.SplitError, "has been built"):
            joints.split(self.cfg, "Nothing here")


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindowsButton(AHome):
    def test_split_to_fit_comes_on_only_when_it_is_too_long(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        from nemo.checks import FAIL, PASS, Result
        app = A.NemoApp(); app.update()
        try:
            w = A.ArtStudio(app); app.update()
            w.name.insert(0, "Long")
            self.assertEqual(str(w.btn_split.cget("state")), "disabled")
            fine = [Result("fits_printer", PASS, "fits")]
            w.built({"out": (Path(self.t.name), fine)})
            self.assertEqual(str(w.btn_split.cget("state")), "disabled")
            long = [Result("fits_printer", FAIL, "too big for the printer: x 400 > 250 mm",
                           ["The Designer can split it into pieces that fit, pinned together: "
                            "nemo model split Long"])]
            w.built({"out": (Path(self.t.name), long)})
            self.assertEqual(str(w.btn_split.cget("state")), "normal")
            done = (Path(self.t.name), [Result("pieces_made", PASS, "2 pieces along x")], None)
            with mock.patch("nemo.joints.split", return_value=done) as split:
                w.split()
                for _ in range(40):
                    app.update()
                    if w._job is None:
                        break
                    import time; time.sleep(0.05)
            split.assert_called_once_with(app.cfg, "Long")
            self.assertIn("ASSEMBLY.txt", w.result.get("1.0", "end"))
            w.destroy()
        finally:
            app.destroy()


def modelkit_result():
    from nemo.checks import PASS, Result
    return Result("x", PASS, "fine")


@unittest.skipUnless(HAS_CQ and HAS_MESH, "CadQuery is not installed here")
class TestARealSplit(AHome):
    def test_a_long_board_is_cut_pinned_and_checked(self):
        doc = {"name": "Long board", "shapes": [{"shape": "box", "size": [400, 60, 10]}]}
        out, results = modelkit.build(self.cfg, doc)
        self.assertEqual({r.name: r.status for r in results}["fits_printer"], "FAIL")
        out, results, p = joints.split(self.cfg, "Long board")
        got = {r.name: r.status for r in results}
        self.assertEqual(got, {"pieces_made": "PASS", "piece-1": "PASS", "piece-2": "PASS",
                               "pins": "PASS"}, [(r.name, r.detail) for r in results])
        self.assertEqual(len(p.cuts[0].pins), 2)
        self.assertTrue((out / "pieces" / "ASSEMBLY.txt").is_file())
        plan = json.loads((out / "joints.json").read_text(encoding="utf-8"))
        self.assertEqual([c["axis"] for c in plan["cuts"]], [0])
        # The two pieces together are the board, less the holes.
        import trimesh
        a, b = (trimesh.load_mesh(str(out / "pieces" / f"piece-{k}.stl")) for k in (1, 2))
        holes = sum(3.14159 * (q.diameter / 2 + p.clearance) ** 2 * (2 * p.depth + 1)
                    for q in p.cuts[0].pins)
        self.assertAlmostEqual(a.volume + b.volume, 400 * 60 * 10 - holes, delta=60)


# --------------------------------------------- full size, shown on the concept
# Owner, 2026-11-04: "split the blunderbuss at full size instead of shrinking";
# "if parts are too large for printer have them separated so can be printed in
# parts and have concept show this with joints parts".

def concept_doc(length=823.0):
    """An invented long object as a concept's shapes: a stock and a barrel."""
    from nemo import blockout
    doc = {"name": "Long thing", "shapes": [
        {"shape": "box", "op": "add", "size": [100, 30, 20], "at": [-40, 0, 0], "label": "Stock"},
        {"shape": "cylinder", "op": "add", "radius": 6, "height": 70, "rotate": [0, 90, 0],
         "at": [10, 0, 10], "label": "Barrel"}]}
    blockout.fit(doc, [length, 0, 0])
    return doc


@unittest.skipUnless(HAS_MESH, "needs trimesh and numpy")
class TestFullSize(unittest.TestCase):
    def test_a_length_alone_sets_the_scale(self):
        from nemo import blockout
        before = concept_doc(170)                       # the shapes' own size: 170 long
        b0, b1 = blockout.bounds(before)
        doc = concept_doc(823)
        lo, hi = blockout.bounds(doc)
        self.assertAlmostEqual(hi[0] - lo[0], 823, delta=0.5)
        self.assertAlmostEqual((hi[1] - lo[1]) / (hi[0] - lo[0]),
                               (b1[1] - b0[1]) / (b1[0] - b0[0]), delta=0.002)   # proportions kept

    def test_no_size_is_not_shrunk_to_the_printer(self):
        from nemo import blockout
        doc = {"name": "x", "shapes": [{"shape": "box", "op": "add", "size": [600, 40, 20],
                                        "at": [0, 0, 0]}]}
        self.assertEqual(blockout.fit(doc, None), 1.0)
        lo, hi = blockout.bounds(doc)
        self.assertAlmostEqual(hi[0] - lo[0], 600, delta=0.01)

    def test_the_brief_says_the_size(self):
        from nemo import concept
        from nemo.project import Brief
        b = Brief(name="t", envelope_mm=[150, 80, 30], shape_size_mm=[823, 0, 0])
        self.assertEqual(concept.size_for(b), [823.0, 0.0, 0.0])        # the real size first
        self.assertEqual(concept.size_for(Brief(name="t", envelope_mm=[150, 80, 30])),
                         [150.0, 80.0, 30.0])
        self.assertIsNone(concept.size_for(Brief(name="t")))

    def test_a_concept_too_big_is_planned_in_pieces_and_its_holes_never_meet(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            from nemo.config import Config
            p = joints.plan_concept(Config.load(Path("/nonexistent")), concept_doc(823))
        self.assertIsNotNone(p)
        self.assertIn(0, p.axes)
        self.assertTrue(all(len(v) >= 1 for v in joints.joint_pins(p).values()))
        # The blunderbuss, 2026-11-04: where two cuts crossed, an x pin's hole and a
        # y pin's ran into each other (0.09 mm apart). Every pair of holes keeps a wall.
        holes = [(c, q) for c in p.cuts for q in c.pins]
        for i, (c1, q1) in enumerate(holes):
            for c2, q2 in holes[i + 1:]:
                if c1 is c2:
                    continue
                kept = joints._clear_of_holes(__import__("numpy").array([[q1.u, q1.v]]),
                                              joints.Plan(p.lo, p.hi, [c2], p.clearance, p.depth),
                                              c1, q1.diameter, 1.2, p.depth)
                self.assertEqual(len(kept), 1)

    def test_no_cut_on_a_face(self):
        # The blunderbuss's cuts fell on its barrel's end and its stock's end and
        # left slivers 0.00 and 0.10 mm thick.
        p = joints.plan(joints.Body(*__import__("nemo.blockout", fromlist=["x"])
                                    .shape_meshes(concept_doc(823))), VOLUME, 1.2)
        faces = joints._square_faces(joints.Body(*__import__("nemo.blockout", fromlist=["x"])
                                                 .shape_meshes(concept_doc(823))), 0)
        for c in p.cuts:
            if c.axis == 0:
                self.assertTrue(all(abs(c.at - f) >= 2.4 - 1e-6 for f in faces), (c.at, faces))

    def test_the_views_use_the_room(self):
        # The scale took mm from px: an 823 mm concept was drawn at the 0.2 floor.
        from nemo import blockout
        self.assertGreater(blockout.view_scale([823, 370, 144]), 0.35)
        self.assertAlmostEqual(blockout.view_scale([150, 60, 22]), 2.30, delta=0.3)

    def test_the_blueprint_shows_the_pieces_in_amber(self):
        from PIL import Image
        from nemo import blockout
        doc = concept_doc(823)
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            from nemo.config import Config
            p = joints.plan_concept(Config.load(Path("/nonexistent")), doc)
            whole = blockout.blueprint_png(doc, Path(t) / "w.png", "x")
            split = blockout.blueprint_png(doc, Path(t) / "s.png", "x", plan=p)
            amber = lambda f: sum(n for n, c in Image.open(f).convert("RGB").getcolors(1 << 20)
                                  if c == blockout.BP_JOINT)
            self.assertEqual(amber(whole), 0)
            self.assertGreater(amber(split), 500)


class TestOnlyAgainstARealSize(unittest.TestCase):
    def test_an_inside_size_is_a_box_not_proportions(self):
        from nemo import concept
        from nemo.project import Brief
        self.assertIsNone(concept.real_size(Brief(name="t", envelope_mm=[150, 80, 30])))
        self.assertEqual(concept.real_size(Brief(name="t", shape_size_mm=[857, 74, 188])),
                         [857.0, 74.0, 188.0])


class TestRedraw(AHome):
    def test_the_old_concepts_are_moved_aside_not_deleted(self):
        from nemo import concept
        root = Path(self.t.name) / "p"
        d = concept.folder(root); d.mkdir(parents=True)
        for f in ("A.json", "B.json", "choice.json", "A-blueprint.png"):
            (d / f).write_text("x", encoding="utf-8")
        where = concept.set_aside(root)
        self.assertEqual(sorted(p.name for p in where.iterdir()),
                         ["A-blueprint.png", "A.json", "B.json", "choice.json"])
        self.assertEqual([p.name for p in d.iterdir() if p.is_file()], [])
        self.assertEqual(concept.load(root), [])
        self.assertIsNone(concept.set_aside(root))                 # nothing left to move


@unittest.skipUnless(HAS_MESH, "needs trimesh and numpy")
class TestTheConceptCarriesItsJoints(AHome):
    def concept(self, length):
        from nemo import concept
        return concept.Concept(key="A", title="Long", corners="", notch_wall="", order=[],
                               placed=[], kind="blockout", spec=concept_doc(length))

    def test_too_big_is_planned_said_and_kept_for_the_build(self):
        from nemo import concept
        root = Path(self.t.name) / "p"
        c = self.concept(823)
        concept.save_painted(root, [c], "sig")
        d = concept.folder(root)
        self.assertTrue((d / "A-joints.json").is_file())
        self.assertTrue((d / "A-blueprint.png").is_file())
        said = json.loads((d / "A.json").read_text(encoding="utf-8"))["said"]
        self.assertTrue(any(s.startswith("Printed in ") and "pins" in s for s in said), said)
        plan = concept.joints_plan(root, "A")
        self.assertEqual(plan.pieces, joints.plan_concept(self.cfg, c.spec).pieces)

    def test_one_that_fits_has_no_joints(self):
        from nemo import concept
        root = Path(self.t.name) / "p"
        concept.save_painted(root, [self.concept(200)], "sig")
        self.assertFalse((concept.folder(root) / "A-joints.json").exists())
        self.assertIsNone(concept.joints_plan(root, "A"))

    def test_the_build_is_split_with_the_concepts_own_plan(self):
        from nemo import concept
        from nemo.checks import FAIL, PASS, Result
        from nemo.pipeline import Pipeline
        root = Path(self.t.name) / "p"
        c = self.concept(823)
        concept.save_painted(root, [c], "sig")
        plan = concept.joints_plan(root, "A")
        too_big = [Result("fits_printer", FAIL, "too big for the printer: x 823 > 250 mm", [])]
        out = Path(self.t.name) / "model"; out.mkdir()
        done = (out, [Result("pieces_made", PASS, "pieces")], plan)
        pipe = Pipeline.__new__(Pipeline); pipe.cfg = self.cfg
        with mock.patch("nemo.joints.split", return_value=done) as split:
            got = pipe._split_if_too_long("Long", out, too_big, plan)
        split.assert_called_once_with(self.cfg, "Long", given=plan)
        self.assertEqual(got[0].name, "pieces_made")
        self.assertEqual(too_big[0].status, PASS)                           # built in pieces
        self.assertIn("built in pieces", too_big[0].detail)


if __name__ == "__main__":
    unittest.main()
