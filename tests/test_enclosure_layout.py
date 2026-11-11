"""The enclosure is written by code from a layout the model chooses.

Three real runs on the AH531 asked the 1.7B model for a CadQuery script:
it ran out of time, was never executed (D131), and then called a method
CadQuery does not have. enclosure.py asks the model only where each part
sits, checks that, lays the parts out itself if the model cannot, and
writes every line of CadQuery.

The last class runs real CadQuery and is skipped without it.
"""
from __future__ import annotations

import dataclasses, importlib.util, json, re, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, enclosure
from nemo.checks.deterministic import FAIL, PASS, Result
from nemo.router import Reply
from test_gates_real import WeatherCase
from test_pipeline import StubRouter

HW = {"min_wall_mm": 1.2, "nozzle_mm": 0.4, "build_volume_mm": [250, 250, 260]}


def sound() -> dict:
    """A layout that fits the weather project's 90 x 60 mm box."""
    return {"esp32_devkit_v1": {"x_mm": 3, "y_mm": 3, "turned": True},
            "ssd1306_oled_096": {"x_mm": 36, "y_mm": 3, "turned": False},
            "bme280": {"x_mm": 70, "y_mm": 40, "turned": False}}


def overlapping() -> dict:
    return {"esp32_devkit_v1": {"x_mm": 3, "y_mm": 3, "turned": False},
            "ssd1306_oled_096": {"x_mm": 20, "y_mm": 10, "turned": False},
            "bme280": {"x_mm": 70, "y_mm": 40, "turned": False}}


class LayoutCase(WeatherCase):
    def setUp(self):
        super().setUp()
        self.box = enclosure.box_for([90, 60, 35], HW)


class TestBox(unittest.TestCase):
    def test_the_wall_is_a_whole_number_of_nozzle_widths_and_never_under_the_minimum(self):
        self.assertEqual(enclosure.wall_thickness(1.2, 0.4), 1.2)
        self.assertEqual(enclosure.wall_thickness(1.5, 0.4), 1.6)
        self.assertEqual(enclosure.wall_thickness(0.3, 0.4), 0.8)   # two perimeters at least
        self.assertEqual(enclosure.wall_thickness(1.2, 0.6), 1.2)

    def test_the_inside_is_the_envelope_less_the_walls_and_floor(self):
        box = enclosure.box_for([90, 60, 35], HW)
        self.assertEqual([round(v, 3) for v in box.inner], [87.6, 57.6, 33.8])

    def test_an_envelope_the_printer_cannot_print_is_refused(self):
        with self.assertRaises(enclosure.EnclosureError) as ctx:
            enclosure.box_for([300, 60, 35], HW)
        self.assertIn("build volume", str(ctx.exception))
        with self.assertRaises(enclosure.EnclosureError):
            enclosure.box_for([], HW)
        with self.assertRaises(enclosure.EnclosureError):
            enclosure.box_for([2, 2, 1], HW)


class TestSchemaAndFacts(LayoutCase):
    def test_one_required_entry_per_part_bounded_by_the_floor(self):
        s = enclosure.layout_schema(self.parts, self.box)
        self.assertEqual(sorted(s["required"]), ["bme280", "esp32_devkit_v1", "ssd1306_oled_096"])
        self.assertIs(s["additionalProperties"], False)
        x = s["properties"]["bme280"]["properties"]["x_mm"]
        self.assertEqual((x["minimum"], x["maximum"]), (0, 87))

    def test_the_model_is_told_the_floor_and_each_parts_size(self):
        facts = enclosure.part_facts(self.parts, self.box)
        self.assertIn("88 mm along x and 58 mm along y", facts)
        self.assertIn("- esp32_devkit_v1 (", facts)
        self.assertIn("51.5 x 28.5 x 13", facts)


class TestFaults(LayoutCase):
    def faults(self, doc):
        return enclosure.faults(enclosure.placed_from(doc, self.parts), self.box)

    def test_a_sound_layout_has_none(self):
        self.assertEqual(self.faults(sound()), [])

    def test_two_parts_on_the_same_patch_of_floor(self):
        found = self.faults(overlapping())
        self.assertEqual(len(found), 1)
        self.assertIn("esp32_devkit_v1 and ssd1306_oled_096 overlap", found[0])

    def test_a_part_through_the_wall_says_how_big_the_floor_is(self):
        doc = sound(); doc["bme280"]["x_mm"] = 80
        found = self.faults(doc)
        self.assertIn("bme280 at (80, 40)", found[0])
        self.assertIn("87.6 x 57.6", found[0])

    def test_turning_a_part_swaps_its_footprint(self):
        doc = sound(); doc["esp32_devkit_v1"]["turned"] = False      # 51.5 along x now
        self.assertTrue(any("overlap" in f for f in self.faults(doc)))

    def test_a_part_too_tall_for_the_box(self):
        low = enclosure.box_for([90, 60, 12], HW)
        found = enclosure.faults(enclosure.placed_from(sound(), self.parts), low)
        self.assertTrue(any("esp32_devkit_v1 is 13 mm tall" in f for f in found))

    def test_two_parts_exactly_the_required_distance_apart_are_not_too_close(self):
        # Floating point once said they were.
        m = enclosure.margin()
        a = enclosure.Placed("a", m, m, 60.0, 39.0, 5.0)
        b = enclosure.Placed("b", m + 60.0 + 2 * m, m, 20.0, 20.0, 5.0)
        c = enclosure.Placed("c", m, m + 39.0 + 2 * m, 20.0, 17.0, 5.0)
        self.assertEqual(enclosure.faults([a, b, c], enclosure.box_for([140, 100, 40], HW)), [])

    def test_a_layout_that_leaves_a_part_out_is_refused(self):
        doc = sound(); del doc["bme280"]
        with self.assertRaises(enclosure.EnclosureError) as ctx:
            enclosure.placed_from(doc, self.parts)
        self.assertIn("does not place bme280", str(ctx.exception))


class TestAutoLayout(LayoutCase):
    def test_it_finds_a_sound_layout_by_turning_a_board_that_will_not_go_lengthways(self):
        placed = enclosure.auto_layout(self.parts, self.box)
        self.assertEqual(enclosure.faults(placed, self.box), [])
        esp = next(a for a in placed if a.ref == "esp32_devkit_v1")
        self.assertEqual((esp.dx, esp.dy), (28.5, 51.5))             # turned

    def test_parts_that_cannot_fit_say_so(self):
        with self.assertRaises(enclosure.EnclosureError) as ctx:
            enclosure.auto_layout(self.parts, enclosure.box_for([60, 40, 35], HW))
        self.assertIn("Make the envelope larger", str(ctx.exception))

    def test_a_box_too_shallow_names_the_part(self):
        with self.assertRaises(enclosure.EnclosureError) as ctx:
            enclosure.auto_layout(self.parts, enclosure.box_for([90, 60, 12], HW))
        self.assertIn("esp32_devkit_v1 is too tall", str(ctx.exception))


class TestScript(LayoutCase):
    def script(self, doc=None, parts=None):
        parts = parts or self.parts
        return enclosure.cadquery_script(enclosure.placed_from(doc or sound(), parts), parts,
                                         self.box)

    def test_it_is_python_and_uses_only_the_cadquery_that_was_proved(self):
        text = self.script()
        compile(text, "housing.py", "exec")
        methods = set(re.findall(r"\.([a-z_]+)\(", text))
        self.assertLessEqual(methods, {"Workplane", "box", "cut", "workplane", "translate",
                                       "center", "rect", "extrude", "union", "export"})
        self.assertTrue(text.rstrip().endswith('exporters.export(housing, "housing.stl")'))

    def test_every_dimension_is_a_named_variable_from_the_brief_or_the_library(self):
        text = self.script()
        self.assertIn("length, width, height = 90, 60, 35", text)
        self.assertIn("wall = 1.2", text)
        self.assertIn("p_bme280 = (70, 40, 15, 13)", text)           # the library's size

    def test_a_rim_for_each_part_and_a_cable_notch(self):
        text = self.script()
        for ref in ("esp32_devkit_v1", "bme280", "ssd1306_oled_096"):
            self.assertIn(f"housing = housing.union(rim_{ref})", text)
        self.assertIn("cutout_cable", text)

    def test_vents_only_when_something_draws_enough(self):
        self.assertIn("vent_width", self.script())                   # the ESP32 draws 260 mA
        cool = [p for p in self.parts if p.ref != "esp32_devkit_v1"]
        doc = {k: v for k, v in sound().items() if k != "esp32_devkit_v1"}
        self.assertNotIn("vent_width", self.script(doc, cool))

    def test_a_panel_mounted_part_gets_a_cutout_named_for_the_cross_check(self):
        panel = [dataclasses.replace(p, mount="panel") if p.ref == "bme280" else p
                 for p in self.parts]
        text = self.script(parts=panel)
        self.assertIn("cutout_bme280 = ", text)
        from nemo.pipeline import Pipeline
        path = self.tmp / "housing.py"
        path.write_text(text, encoding="utf-8")
        self.assertIn("bme280", Pipeline._cutouts(path))

    def test_an_unsound_layout_is_never_drawn(self):
        with self.assertRaises(enclosure.EnclosureError):
            self.script(overlapping())

    def test_no_standoff_or_screw_hole_is_invented(self):
        text = self.script().lower()
        for word in ("standoff", "hole(", "cbore", "screw", "m3", "m2"):
            self.assertNotIn(word, text)


class TestOrder(LayoutCase):
    """What the real model returned when asked for positions, on the AH531:
    all three parts on top of one another, twice, in five and a half
    minutes. Geometry is code's. The model is asked for the order."""

    REAL_POSITIONS = {"esp32_devkit_v1": {"x_mm": 30, "y_mm": 10, "turned": False},
                      "bme280": {"x_mm": 40, "y_mm": 20, "turned": True},
                      "ssd1306_oled_096": {"x_mm": 50, "y_mm": 30, "turned": False}}

    def test_the_positions_the_model_really_gave_were_four_faults(self):
        found = enclosure.faults(enclosure.placed_from(self.REAL_POSITIONS, self.parts), self.box)
        self.assertEqual(len(found), 4)
        self.assertEqual(sum("overlap" in f for f in found), 3)

    def test_the_schema_is_each_part_and_nothing_else(self):
        s = enclosure.order_schema(self.parts)["properties"]["order"]
        self.assertEqual((s["minItems"], s["maxItems"]), (3, 3))
        self.assertEqual(sorted(s["items"]["enum"]),
                         ["bme280", "esp32_devkit_v1", "ssd1306_oled_096"])

    def test_an_order_must_name_each_part_exactly_once(self):
        good = ["bme280", "ssd1306_oled_096", "esp32_devkit_v1"]
        self.assertEqual(enclosure.order_from({"order": good}, self.parts), good)
        for bad in (["bme280", "bme280", "esp32_devkit_v1"], ["bme280"], "bme280", None,
                    good + ["rc522"]):
            with self.assertRaises(enclosure.EnclosureError):
                enclosure.order_from({"order": bad}, self.parts)

    def test_code_packs_soundly_in_whatever_order_it_is_given(self):
        import itertools
        refs = ["bme280", "esp32_devkit_v1", "ssd1306_oled_096"]
        for order in itertools.permutations(refs):
            placed = enclosure.auto_layout(self.parts, self.box, list(order))
            self.assertEqual(enclosure.faults(placed, self.box), [], order)
            self.assertEqual([a.ref for a in sorted(placed, key=lambda a: (a.y, a.x))][0],
                             order[0])

    def test_the_order_is_what_keeps_two_parts_apart(self):
        def gap(order):
            placed = enclosure.auto_layout(self.parts, self.box, order)
            return {frozenset((a, b)): d for a, b, d in enclosure.gaps(placed)}[
                frozenset(("bme280", "esp32_devkit_v1"))]
        ends = gap(["bme280", "ssd1306_oled_096", "esp32_devkit_v1"])
        beside = gap(["bme280", "esp32_devkit_v1", "ssd1306_oled_096"])
        self.assertGreater(ends, 30)
        self.assertLess(beside, 5)


class TestSensorAwayFromTheWarmPart(LayoutCase):
    """The order the real model chose on the AH531, for a brief that said
    the sensor must sit away from the warm ESP32: sensor in the middle,
    4.4 mm from it."""

    REAL_ORDER = ["ssd1306_oled_096", "bme280", "esp32_devkit_v1"]

    def test_the_library_says_which_part_is_warm_and_which_is_a_sensor(self):
        self.assertEqual(enclosure.warm_part(self.parts).ref, "esp32_devkit_v1")
        self.assertEqual(enclosure.thermal_order(self.parts),
                         ["bme280", "ssd1306_oled_096", "esp32_devkit_v1"])

    def test_the_real_order_left_them_side_by_side(self):
        placed = enclosure.auto_layout(self.parts, self.box, self.REAL_ORDER)
        self.assertEqual(enclosure.nearest_sensor_gap(placed, self.parts),
                         ("bme280", "esp32_devkit_v1", 4.4))

    def test_codes_order_keeps_them_at_opposite_ends(self):
        placed = enclosure.auto_layout(self.parts, self.box, enclosure.thermal_order(self.parts))
        sensor, hot, mm = enclosure.nearest_sensor_gap(placed, self.parts)
        self.assertGreater(mm, 30)

    def test_no_warm_part_or_no_sensor_means_nothing_to_enforce(self):
        cool = [p for p in self.parts if p.ref != "esp32_devkit_v1"]
        self.assertIsNone(enclosure.thermal_order(cool))
        no_sensor = [p for p in self.parts if p.ref != "bme280"]
        self.assertIsNone(enclosure.thermal_order(no_sensor))
        self.assertIsNone(enclosure.nearest_sensor_gap(
            enclosure.auto_layout(no_sensor, self.box), no_sensor))


class LayoutRouter:
    supports_schema = True
    timeout = 1800

    def __init__(self, reply):
        self.reply = reply if isinstance(reply, str) else json.dumps(reply)
        self.asked = []

    def ask(self, task, system, user, **kw):
        self.asked.append({"task": task, "system": system, "user": user, **kw})
        return Reply(self.reply, "local", "stub")

    def local_up(self):
        return True


APART = {"order": ["bme280", "ssd1306_oled_096", "esp32_devkit_v1"]}


class TestEnclosureStep(WeatherCase):
    def setUp(self):
        super().setUp()
        # With no constraint the model is not asked for an order (D172), and
        # these are about what is done with the order it gives.
        from nemo.project import Brief
        self.project.save_brief(Brief(**{
            **self.project.load_brief().__dict__,
            "constraints": ["The display must be at one end."]}))

    def run_step(self, router, generated=None):
        gen = generated or Result("enclosure_script", PASS, "generated housing.stl")
        with mock.patch.object(checks, "generate_enclosure", return_value=gen), \
             mock.patch.object(checks, "solid", return_value=Result("solid", PASS, "ok")), \
             mock.patch.object(checks, "thickness", return_value=Result("thickness", PASS, "ok")):
            return self.pipe(router).stage_enclosure()

    def script(self):
        return self.project.housing_script.read_text(encoding="utf-8")

    def test_the_model_is_asked_for_an_order_once_and_never_for_cadquery_or_positions(self):
        r = LayoutRouter(APART)
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        self.assertEqual(r.asked[0]["schema"],
                         enclosure.order_schema([self.lib.get(x) for x in
                                                 ("esp32_devkit_v1", "bme280", "ssd1306_oled_096")]))
        self.assertLessEqual(r.asked[0]["max_tokens"], 120)
        self.assertNotIn("CadQuery", r.asked[0]["system"])
        self.assertIn("only the order", r.asked[0]["system"])
        self.assertIn("- bme280 (", r.asked[0]["user"])

    def test_code_places_the_parts_in_that_order_and_says_how_far_apart(self):
        sr = self.run_step(LayoutRouter(APART))
        self.assertIn("p_bme280 = (2.2, 2.2, 15, 13)", self.script())      # first: at the origin end
        text = sr.render()
        self.assertIn("Order along the box, chosen by the model: bme280, "
                      "ssd1306_oled_096, esp32_devkit_v1.", text)
        self.assertIn("bme280 to esp32_devkit_v1 38.8 mm", text)

    def test_an_order_that_puts_the_sensor_by_the_warm_part_is_overruled_and_why(self):
        real = {"order": ["ssd1306_oled_096", "bme280", "esp32_devkit_v1"]}
        sr = self.run_step(LayoutRouter(real))
        self.assertTrue(sr.ok, sr.render())
        text = sr.render()
        self.assertIn("put bme280 4.4 mm from esp32_devkit_v1", text)
        self.assertIn("Nemo's own order keeps them 38.8 mm apart", text)
        self.assertIn("p_bme280 = (2.2, 2.2, 15, 13)", self.script())
        self.assertIn("bme280 to esp32_devkit_v1 38.8 mm", text)        # what was built

    def test_an_order_that_already_keeps_them_apart_is_left_alone(self):
        sr = self.run_step(LayoutRouter(APART))
        self.assertNotIn("used instead", sr.render())

    def test_the_briefs_constraints_reach_the_model(self):
        from nemo.project import Brief
        self.project.save_brief(Brief(**{
            **self.project.load_brief().__dict__,
            "constraints": ["The sensor must sit away from the warm ESP32 module."]}))
        r = LayoutRouter(APART)
        self.run_step(r)
        self.assertIn("The sensor must sit away from the warm ESP32", r.asked[0]["user"])

    def test_an_order_that_is_not_one_falls_back_to_codes_and_says_so(self):
        for reply in ({"order": ["bme280", "bme280", "esp32_devkit_v1"]},
                      "I would put the sensor near the top."):
            sr = self.run_step(LayoutRouter(reply))
            self.assertTrue(sr.ok, sr.render())
            self.assertIn("Nemo's own order, largest first", sr.render())
            self.assertIn("knows nothing of the brief's constraints", sr.render())
            self.assertIn("p_esp32_devkit_v1 = (2.2, 2.2, 28.5, 51.5)", self.script())

    def test_parts_that_cannot_fit_fail_before_the_model_is_asked(self):
        from nemo.project import Brief
        self.project.save_brief(Brief(**{**self.project.load_brief().__dict__,
                                         "envelope_mm": [60, 40, 35]}))
        r = LayoutRouter(APART)
        sr = self.run_step(r)
        self.assertFalse(sr.ok)
        self.assertEqual(r.asked, [])                   # no minutes spent on a box that cannot work
        self.assertIn("Make the envelope larger", sr.render())
        self.assertEqual(sr.go_back_to, "brief")

    def test_the_layout_is_saved_for_the_owner_to_see(self):
        self.run_step(LayoutRouter(APART))
        saved = json.loads((self.project.housing_script.parent / "layout.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(saved["bme280"], {"x_mm": 2.2, "y_mm": 2.2, "turned": False})
        self.assertIs(saved["esp32_devkit_v1"]["turned"], True)

    def test_the_owner_is_told_what_is_not_drawn(self):
        self.assertIn("No lid and no screw standoffs", self.run_step(LayoutRouter(APART)).render())

    def test_a_router_that_cannot_constrain_still_gets_the_old_request(self):
        r = StubRouter('```python\nopen("housing.stl", "w").write("solid x\\nendsolid x\\n")\n```')
        self.run_step(r)
        self.assertEqual(r.calls, ["cad_script"])


@unittest.skipUnless(importlib.util.find_spec("cadquery") and importlib.util.find_spec("OCP"), "needs CadQuery")
class TestAgainstRealCadQuery(LayoutCase):
    """About 10 s a box on the AH531."""

    def build(self, placed, parts, box):
        work = self.tmp / "enclosure"
        work.mkdir(parents=True, exist_ok=True)
        (work / "housing.py").write_text(enclosure.cadquery_script(placed, parts, box),
                                         encoding="utf-8")
        g = checks.generate_enclosure(work / "housing.py", work / "housing.stl")
        self.assertEqual(g.status, PASS, g.render())
        return work / "housing.stl"

    def test_the_weather_box_is_a_printable_solid_with_walls_at_the_minimum(self):
        stl = self.build(enclosure.placed_from(sound(), self.parts), self.parts, self.box)
        solid = checks.solid(stl)
        self.assertEqual(solid.status, PASS, solid.render())
        wall = checks.thickness(stl, 1.2)
        self.assertEqual(wall.status, PASS, wall.render())
        self.assertIn("1.20 mm", wall.render())
        self.assertTrue(stl.with_suffix(".step").exists())

    def test_codes_own_layout_and_a_panel_cutout_build_too(self):
        parts = [self.lib.get("esp32_devkit_v1"), self.lib.get("rc522"),
                 dataclasses.replace(self.lib.get("relay_5v_1ch"), mount="panel")]
        box = enclosure.box_for([140, 100, 40], HW)
        stl = self.build(enclosure.auto_layout(parts, box), parts, box)
        self.assertEqual(checks.solid(stl).status, PASS)
        self.assertEqual(checks.thickness(stl, 1.2).status, PASS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
