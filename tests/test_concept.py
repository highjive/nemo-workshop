"""The Artist's enclosure concepts (owner's request, 2026-10-20): two ways the
case could be, drawn from geometry the enclosure step can build; the owner
picks one and may change it before the Designer models it."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, concept, enclosure, review, staff
from nemo.checks import runners
from nemo.config import Config
from nemo.parts import PartsLibrary
from nemo.project import STAGES, Brief, Project

HW = {"min_wall_mm": 1.2, "nozzle_mm": 0.4}
ENV = [110, 70, 35]


def lib():
    return PartsLibrary.load()


def weather_parts():
    lb = lib()
    return [lb.get(r) for r in ("esp32_devkit_v1", "bme280", "ssd1306_oled_096")]


class TestTheConcepts(unittest.TestCase):
    def setUp(self):
        self.parts = weather_parts()
        self.box = enclosure.box_for(ENV, HW)
        self.a, self.b = concept.make(self.parts, self.box)

    def test_a_is_what_nemo_builds_unasked(self):
        placed, order, _ = concept.nemos_layout(self.parts, self.box)
        self.assertEqual(self.a.layout(), placed)
        self.assertEqual((self.a.corners, self.a.notch_wall), ("square", "left"))

    def test_b_is_another_sound_layout_no_warmer(self):
        self.assertNotEqual([(p.x, p.y) for p in self.a.layout()],
                            [(p.x, p.y) for p in self.b.layout()])
        self.assertEqual(enclosure.faults(self.b.layout(), self.box), [])
        self.assertEqual(enclosure.too_close(self.b.layout(), self.parts), [])
        ga = enclosure.nearest_sensor_gap(self.a.layout(), self.parts)
        gb = enclosure.nearest_sensor_gap(self.b.layout(), self.parts)
        self.assertGreaterEqual(gb[2] + 0.5, ga[2])
        self.assertEqual((self.b.corners, self.b.notch_wall), ("rounded", "front"))

    def test_with_nothing_else_that_fits_b_differs_in_style_only_and_says_so(self):
        one = [lib().get("rp2040_pico")]
        box = enclosure.box_for([60, 30, 20], HW)
        a, b = concept.make(one, box)
        self.assertEqual(a.layout(), b.layout())
        self.assertIn("style only", " ".join(b.said))

    def test_a_box_too_small_for_any_layout_raises(self):
        with self.assertRaises(enclosure.EnclosureError):
            concept.make(self.parts, enclosure.box_for([40, 30, 35], HW))

    def test_the_plan_names_the_parts_and_shows_the_opening(self):
        svg = concept.plan_svg(self.b, self.box, self.parts)
        self.assertIn("BME280", svg)
        self.assertIn("#E07A1F", svg)                       # the cable opening
        self.assertIn(f'rx="{enclosure.corner_radius(self.box) * 3.0:.1f}"', svg)
        self.assertIn('rx="0.0"', concept.plan_svg(self.a, self.box, self.parts))


class TestTheChoice(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.parts = weather_parts()
        self.box = enclosure.box_for(ENV, HW)
        self.sig = concept.signature(self.parts, ENV)
        concept.save(self.root, concept.make(self.parts, self.box), self.sig, self.box, self.parts)

    def test_choose_and_read_back_with_changes(self):
        concept.choose(self.root, "B", self.sig, "square", "left", " keep the display at the front ")
        ch = concept.chosen(self.root, self.sig)
        self.assertEqual((ch.concept, ch.corners, ch.notch_wall, ch.notes),
                         ("B", "square", "left", "keep the display at the front"))
        self.assertIn("Changes: keep the display", concept.describe(ch))

    def test_no_changes_keeps_the_concepts_own_style(self):
        ch = concept.choose(self.root, "B", self.sig)
        self.assertEqual((ch.corners, ch.notch_wall), ("rounded", "front"))

    def test_a_choice_for_other_parts_or_size_is_stale(self):
        concept.choose(self.root, "A", self.sig)
        self.assertIsNone(concept.chosen(self.root, concept.signature(self.parts, [120, 70, 35])))
        self.assertIsNone(concept.chosen(self.root, concept.signature(self.parts[:2], ENV)))
        self.assertEqual(concept.load(self.root, concept.signature(self.parts[:2], ENV)), [])

    def test_what_cannot_be_built_is_refused(self):
        with self.assertRaises(ValueError):
            concept.choose(self.root, "C", self.sig)
        with self.assertRaises(ValueError):
            concept.choose(self.root, "A", self.sig, corners="chamfered")
        with self.assertRaises(ValueError):
            concept.choose(self.root, "A", self.sig, notch_wall="lid")


class TestTheStyleInCadQuery(unittest.TestCase):
    def setUp(self):
        self.parts = weather_parts()
        self.box = enclosure.box_for(ENV, HW)
        self.placed = enclosure.auto_layout(self.parts, self.box)

    def test_the_default_is_the_tray_nemo_always_drew(self):
        s = enclosure.cadquery_script(self.placed, self.parts, self.box)
        self.assertNotIn("fillet", s)
        self.assertIn("notch_y = wall", s)

    def test_rounded_rounds_the_inside_too_so_the_corner_is_not_thin(self):
        s = enclosure.cadquery_script(self.placed, self.parts, self.box, corners="rounded")
        self.assertEqual(s.count('.edges("|Z").fillet('), 2)
        self.assertIn("fillet(corner_radius - wall)", s)

    def test_front_puts_the_notch_in_the_wall_at_y_0(self):
        s = enclosure.cadquery_script(self.placed, self.parts, self.box, notch_wall="front")
        self.assertIn("notch_x = wall", s)
        self.assertIn("(notch_x, wall / 2, height - notch_depth)", s)

    def test_unknown_styles_raise(self):
        with self.assertRaises(enclosure.EnclosureError):
            enclosure.cadquery_script(self.placed, self.parts, self.box, corners="oval")

    def test_the_radius_always_leaves_a_rounded_inside(self):
        thick = enclosure.Box(100, 60, 30, 5.0)
        self.assertGreater(enclosure.corner_radius(thick), thick.wall)


@unittest.skipUnless(importlib.util.find_spec("cadquery") and importlib.util.find_spec("OCP") and importlib.util.find_spec("numpy"),
                     "needs CadQuery and numpy")
class TestRoundedWithRealCadQuery(unittest.TestCase):
    """Run on the AH531 (CadQuery 2.8.0): rounded only outside, the corner wall
    was 0.6 mm and the thickness check failed; rounded inside too, it passes."""

    def test_a_rounded_tray_passes_the_wall_check(self):
        d = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d, True)
        parts = weather_parts()
        box = enclosure.box_for(ENV, HW)
        script = d / "housing.py"
        script.write_text(enclosure.cadquery_script(enclosure.auto_layout(parts, box), parts,
                                                    box, "rounded", "front"), encoding="utf-8")
        made = runners.generate_enclosure(script, d / "housing.stl", timeout=900)
        self.assertEqual(made.status, checks.PASS, made.items)
        r = checks.thickness(d / "housing.stl", HW["min_wall_mm"])
        self.assertNotEqual(r.status, checks.FAIL, (r.detail, r.items))


class TestTheStep(unittest.TestCase):
    """The Concept step, between wiring and enclosure, belongs to the Artist,
    passes only once a concept is chosen, and the enclosure is built as chosen."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.proj = Project(self.home / "p")
        self.proj.create(Brief(name="w", function="A weather station that shows the "
                               "temperature on a display", parts=[
                                   "esp32_devkit_v1", "bme280", "ssd1306_oled_096"],
                               envelope_mm=ENV, power="usb", supply_ma=1000,
                               mcu="esp32_devkit_v1"))
        from nemo.pipeline import Pipeline
        self.router = mock.Mock()
        cfg = Config.load(Path("/nonexistent"))
        cfg.data["hardware"].update(HW)
        self.pipe = Pipeline(self.proj, cfg, self.router, lib())
        self.sig = concept.signature(weather_parts(), ENV)

    def run_concept(self):
        made = checks.Result("enclosure_script", checks.SKIP, "CadQuery is not installed")
        with mock.patch.object(checks, "generate_enclosure", return_value=made):
            return self.pipe.stage_concept()

    def test_the_step_order_and_its_owner(self):
        self.assertEqual(STAGES[STAGES.index("concept") + 1], "enclosure")
        self.assertEqual(STAGES[STAGES.index("concept") - 1], "wiring")
        self.assertEqual(review.ORDER, STAGES)
        self.assertEqual(staff.owner("concept").title, "Artist")
        self.assertEqual(staff.owner("enclosure").title, "Designer")

    def test_drawn_then_waits_for_the_owner(self):
        r = self.run_concept()
        self.assertFalse(r.ok)
        names = {c.name: c.status for c in r.results}
        self.assertEqual(names["concepts"], "PASS")
        self.assertEqual(names["concept_pictures"], "SKIP")   # no CadQuery: said, plans still drawn
        self.assertEqual(names["concept_choice"], "FAIL")
        self.assertTrue((concept.folder(self.proj.root) / "A-plan.svg").exists())
        concept.choose(self.proj.root, "B", self.sig)
        r = self.run_concept()
        self.assertTrue(r.ok)
        names = {c.name: c.status for c in r.results}
        self.assertEqual(names["concept_choice"], "PASS")
        # Pictures that could not be made are tried again; the plans stand.
        self.assertEqual(names.get("concept_pictures"), "SKIP")

    def test_choosing_by_command_runs_the_step_again_as_the_window_does(self):
        # 2026-11-08: `nemo concept choose A` said "Next: nemo run --only
        # concept"; not run, the step's saved "waiting for your choice" stayed
        # after the enclosure and firmware were built, and the Doctors said so.
        import argparse
        from nemo import cli
        self.run_concept()
        args = argparse.Namespace(action="choose", key="a", corners=None, notch=None,
                                  changes=None, project="p", config=None)
        with mock.patch.object(cli, "_project", return_value=self.proj), \
             mock.patch.object(cli, "_library", return_value=lib()), \
             mock.patch.object(cli, "main", return_value=0) as again:
            self.assertEqual(cli.cmd_concept(args, Config.load(Path("/nonexistent"))), 0)
        again.assert_called_once_with(["--project", "p", "run", "--only", "concept"])

    def test_the_reviewer_stops_the_enclosure_until_a_choice(self):
        lb = lib()
        stops = [s.name for s in review.before("enclosure", self.proj, lb)[0]]
        self.assertIn("review_no_concept", stops)
        self.run_concept()
        concept.choose(self.proj.root, "A", self.sig)
        stops = [s.name for s in review.before("enclosure", self.proj, lb)[0]]
        self.assertNotIn("review_no_concept", stops)
        b = self.proj.load_brief(); b.envelope_mm = [120, 70, 35]; self.proj.save_brief(b)
        stops = [s.name for s in review.before("enclosure", self.proj, lb)[0]]
        self.assertIn("review_no_concept", stops)              # stale after a change

    def test_the_enclosure_is_built_as_chosen_and_the_model_not_asked(self):
        self.run_concept()
        concept.choose(self.proj.root, "B", self.sig, corners="rounded", notch_wall="left")
        b = {c.key: c for c in concept.load(self.proj.root, self.sig)}["B"]
        with mock.patch.object(checks, "generate_enclosure",
                               return_value=checks.Result("enclosure_script", checks.SKIP, "x")):
            r = self.pipe.stage_enclosure()
        self.router.ask.assert_not_called()
        s = self.proj.housing_script.read_text(encoding="utf-8")
        self.assertIn("fillet(corner_radius)", s)
        self.assertIn("notch_y = wall", s)
        lay = json.loads((self.proj.housing_script.parent / "layout.json").read_text())
        for p in b.placed:
            self.assertEqual((lay[p["ref"]]["x_mm"], lay[p["ref"]]["y_mm"]), (p["x"], p["y"]))
        self.assertTrue(any("Built as chosen" in n for n in r.notes))

    def test_changes_about_where_parts_go_reach_the_model(self):
        self.run_concept()
        concept.choose(self.proj.root, "A", self.sig, notes="the display nearest the cable")
        from nemo.router import Reply
        self.router.ask.return_value = Reply(json.dumps(
            {"order": ["ssd1306_oled_096", "bme280", "esp32_devkit_v1"]}), "local", "m")
        with mock.patch.object(checks, "generate_enclosure",
                               return_value=checks.Result("enclosure_script", checks.SKIP, "x")):
            self.pipe.stage_enclosure()
        self.router.ask.assert_called_once()
        self.assertIn("the display nearest the cable", self.router.ask.call_args[0][2])


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict("os.environ", _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.app = A.NemoApp(); self.app.withdraw(); self.app.update()
        self.proj = Project(Path(self.t.name) / "p")
        self.proj.create(Brief(name="w", function="f", parts=[
            "esp32_devkit_v1", "bme280", "ssd1306_oled_096"], envelope_mm=ENV))
        self.app.project = self.proj
        parts = weather_parts()
        box = enclosure.box_for(ENV, Config.load().get("hardware", {}))
        self.sig = concept.signature(parts, ENV)
        concept.save(self.proj.root, concept.make(parts, box), self.sig, box, parts)

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def test_it_fits_the_laptops_screen(self):
        # The AH531 is 1366 x 768, less the task bar and the title bar.
        for k in ("A", "B"):                       # with the rendered pictures too
            (concept.folder(self.proj.root) / f"{k}-iso.png").write_bytes(self._png(420))
        d = self.A.ConceptDialog(self.app); self.app.update()
        self.assertLessEqual(d.winfo_reqheight(), 700)
        self.assertLessEqual(d.winfo_reqwidth(), 1300)
        d.destroy()

    @staticmethod
    def _png(side):
        import struct, zlib
        raw = b"".join(b"\x00" + b"\x80\x90\xa0" * side for _ in range(side))

        def chunk(tag, body):
            return (struct.pack(">I", len(body)) + tag + body
                    + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def test_choose_b_with_changes(self):
        d = self.A.ConceptDialog(self.app); self.app.update()
        d.key.set("B"); d._picked(); self.app.update()
        self.assertEqual(d.corners.get(), "Rounded")
        d.notch.set("Left wall")
        d.notes.insert("1.0", "sensor by the vents")
        with mock.patch.object(self.app, "run_stage") as run:
            d.use()
        ch = concept.chosen(self.proj.root, self.sig)
        self.assertEqual((ch.concept, ch.corners, ch.notch_wall, ch.notes),
                         ("B", "rounded", "left", "sensor by the vents"))
        run.assert_called_once_with("concept")


if __name__ == "__main__":
    unittest.main()


BLUNDERBUSS = dict(
    name="blunderbust-gun",
    function=("A replica Blunderbust gun with a mechanical trigger mechanism that simulates "
              "the firing action, including a mechanical cocking system and a simulated firing "
              "mechanism."),
    envelope_mm=[150.0, 80.0, 30.0], done_when="test_firing_simulation",
    constraints=["requires mechanical components, must be durable, must be safe"],
    no_power=True, no_parts=True, accepted=["missing_sound", "unexplained_parts"],
    # Invented figures for the test: a long gun 600 mm long.
    shape_size_mm=[600.0, 50.0, 140.0], shape_facts={"barrel_mm": 300.0})


def model_asked(*a, **k):
    raise AssertionError("the model was asked for a shaped object's concepts")


class TestAShapedObjectIsBuiltByCode(unittest.TestCase):
    """The AH531, 2026-10-21: for "a replica Blunderbust gun" the Concept step
    drew two empty trays; then two paintings, which the Designer could not
    build from; then (2026-10-28) shapes the model placed, which did not look
    like the object. Since 2026-11-04 (owner: "remove blockout"): two concepts
    built by code from the object's anatomy (nemo/anatomy.py); the model is
    never asked. The Art Studio's Designer builds the one chosen."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.proj = Project(self.home / "p")
        self.proj.create(Brief(**BLUNDERBUSS))
        from nemo.pipeline import Pipeline
        cfg = Config.load(Path("/nonexistent"))
        self.pipe = Pipeline(self.proj, cfg, mock.Mock(), lib())

    def run_concept(self):
        from nemo import modelkit
        made = (self.home / "m", [checks.Result("model_made", checks.PASS, "built")])
        with mock.patch.object(self.pipe, "_ask", side_effect=model_asked), \
                mock.patch.object(modelkit, "build", return_value=made) as build:
            r = self.pipe.stage_concept()
        self.built = build
        return r

    def test_replicas_props_and_scale_models_are_shapes(self):
        for words in ("A replica Blunderbust gun", "replicas of old coins",
                      "a scale model of a lighthouse", "a prop sword for a play",
                      "cosplay armour for a convention"):
            self.assertIsNotNone(review.shape_asked(Brief(name="x", function=words)), words)
        self.assertEqual(review.shape_asked(Brief(**BLUNDERBUSS)), "replica blunderbust gun")
        for words in ("replicate the readings to a display", "a weather station",
                      "a box that props up a phone"):
            self.assertIsNone(review.shape_asked(Brief(name="x", function=words)), words)

    def test_concept_goes_on_and_the_enclosure_has_nothing_to_do(self):
        # D227 (2026-11-05): a printed prop of a kind Nemo builds has no case; the
        # enclosure step stood aside instead of stopping it on every run.
        from nemo import steps
        stops, notes = review.before("concept", self.proj, lib())
        self.assertNotIn("review_shape_unsupported", [s.name for s in stops])
        self.assertTrue(any("two concepts" in n for n in notes))
        stops = [s.name for s in review.before("enclosure", self.proj, lib())[0]]
        self.assertNotIn("review_shape_unsupported", stops)
        self.assertIn("no case to make", steps.not_needed("enclosure", self.proj.load_brief()))

    def test_with_parts_the_enclosure_still_stops_on_the_shape(self):
        b = self.proj.load_brief(); b.no_parts = False; b.parts = ["sg90_servo"]
        self.proj.save_brief(b)
        stops = [s.name for s in review.before("enclosure", self.proj, lib())[0]]
        self.assertIn("review_shape_unsupported", stops)
        self.assertNotIn("review_no_concept", stops)       # one reason, not two

    def test_two_concepts_built_by_code_then_wait_for_a_choice(self):
        r = self.run_concept()                                  # model_asked would raise
        self.assertFalse(r.ok)
        names = {c.name: c.status for c in r.results}
        self.assertEqual((names["concepts"], names["concept_choice"]), ("PASS", "FAIL"))
        d = concept.folder(self.proj.root)
        specs = {}
        for k in ("A", "B"):
            self.assertTrue((d / f"{k}-blueprint.png").is_file())
            specs[k] = json.loads((d / f"{k}-spec.json").read_text(encoding="utf-8"))
        for part in ("Barrel", "Bell mouth", "Fore-end", "Lock", "Wrist", "Butt", "Trigger guard"):
            self.assertIn(part, specs["A"]["parts"])
        self.assertGreater(len(specs["B"]["shapes"]), len(specs["A"]["shapes"]))
        self.assertIn("Hammer", specs["B"]["parts"])
        said = " ".join(r.results[0].items)
        self.assertIn("Measured, from the brief: length, width, height, barrel", said)
        self.assertIn("Estimated", said)
        self.assertFalse((d / "A-plan.svg").exists())                       # no tray
        self.built.assert_not_called()                                      # not before a choice

    def test_chosen_then_the_designer_builds_it(self):
        self.run_concept()
        sig = concept.current_signature(self.proj.load_brief(), [])
        ch = concept.choose(self.proj.root, "B", sig, notes="a longer flared muzzle")
        self.assertEqual(ch.kind, "blockout")
        self.assertIn("Designer builds it", concept.describe(ch))
        r = self.run_concept()
        self.assertTrue(r.ok)
        doc = self.built.call_args[0][1]
        spec = json.loads((concept.folder(self.proj.root) / "B-spec.json").read_text(encoding="utf-8"))
        self.assertEqual(len(doc["shapes"]), len(spec["shapes"]))
        note = next(c for c in r.results if c.name == "designer_model")
        self.assertIn("a longer flared muzzle", " ".join(note.items))

    def test_an_object_nemo_does_not_know_is_said(self):
        b = self.proj.load_brief()
        b.name = "gnome"                                   # the name is read too
        b.function = "A replica of a garden gnome with a lamp in its hand"
        self.proj.save_brief(b)
        r = self.run_concept()
        self.assertFalse(r.ok)
        self.assertIn("knows how to build only these kinds of object yet: pistol, long gun",
                      " ".join(r.results[0].items))

    def test_no_size_is_said(self):
        b = self.proj.load_brief()
        b.shape_size_mm = []
        b.envelope_mm = []
        self.proj.save_brief(b)
        r = self.run_concept()
        self.assertFalse(r.ok)
        self.assertIn("give the object's real size", " ".join(r.results[0].items))

    def test_a_new_size_draws_them_again_by_code(self):
        from nemo import blockout
        self.run_concept()
        b = self.proj.load_brief()
        b.shape_size_mm = [900.0, 60.0, 180.0]
        self.proj.save_brief(b)
        self.run_concept()
        spec = json.loads((concept.folder(self.proj.root) / "A-spec.json").read_text(encoding="utf-8"))
        lo, hi = blockout.bounds(spec)
        self.assertAlmostEqual(hi[0] - lo[0], 900, delta=1)

    def test_trays_drawn_before_are_cleared(self):
        d = concept.folder(self.proj.root)
        d.mkdir(parents=True)
        for f in ("A-iso.png", "A-plan.svg", "B-render.txt", "A-painted.png"):
            (d / f).write_text("old")
        self.run_concept()
        self.assertEqual(sorted(p.name for p in d.glob("*.png")), ["A-blueprint.png", "B-blueprint.png"])
        self.assertEqual(list(d.glob("*.svg")), [])

    def test_saying_a_tray_is_fine_goes_back_to_trays(self):
        b = self.proj.load_brief()
        b.accepted = list(b.accepted) + ["shape_unsupported"]
        self.proj.save_brief(b)
        made = checks.Result("enclosure_script", checks.SKIP, "CadQuery is not installed")
        with mock.patch.object(checks, "generate_enclosure", return_value=made):
            self.run_concept()
        self.assertTrue((concept.folder(self.proj.root) / "A-plan.svg").exists())


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheConceptWindow(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict("os.environ", _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.app = A.NemoApp(); self.app.withdraw(); self.app.update()
        self.proj = Project(Path(self.t.name) / "p")
        self.proj.create(Brief(**BLUNDERBUSS))
        self.app.project = self.proj
        self.sig = concept.painted_signature(self.proj.load_brief())
        concept.save_painted(self.proj.root, concept.make_built(self.proj.load_brief()), self.sig)

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def test_built_concepts_have_no_tray_choices_and_record_the_changes(self):
        d = self.A.ConceptDialog(self.app); self.app.update()
        self.assertTrue(d.blockout and d.painted)
        self.assertFalse(d.corners.winfo_ismapped())
        self.assertEqual(len(d.images), 2)                                  # both views shown
        d.key.set("A"); d.notes.insert("1.0", "brass fittings")
        with mock.patch.object(self.app, "run_stage"):
            d.use()
        ch = concept.chosen(self.proj.root, self.sig)
        self.assertEqual((ch.concept, ch.kind, ch.notes), ("A", "blockout", "brass fittings"))
