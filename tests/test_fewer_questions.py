"""D172: two questions the model is no longer asked.

From the model server's own log of a real run (AH531, qwen3-4b,
2026-10-08), after the wiring question had been shortened:

    enclosure   485 tokens read, 52 written   494 s
    firmware    188 tokens read, 12 written   175 s

The enclosure question asks for the order of the parts along the box. With
no constraint in the brief there is nothing for the model to weigh: what
warms what, and what the library says to keep apart, are decided by code
either way. The firmware question asks how often to update when the brief
does not say; the answer was 1000 ms on both real runs.
"""
from __future__ import annotations

import json, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, enclosure
from nemo.checks.deterministic import PASS, Result
from nemo.project import Brief
from test_gates_real import WeatherCase
from test_harness import SchemaRouter

ORDER = {"order": ["ssd1306_oled_096", "esp32_devkit_v1", "bme280"]}


class EnclosureCase(WeatherCase):
    def run_step(self, router):
        gen = Result("enclosure_script", PASS, "generated housing.stl")
        with mock.patch.object(checks, "generate_enclosure", return_value=gen), \
             mock.patch.object(checks, "solid", return_value=Result("solid", PASS, "ok")), \
             mock.patch.object(checks, "thickness", return_value=Result("thickness", PASS, "ok")):
            return self.pipe(router).stage_enclosure()

    def constrain(self, *lines):
        self.project.save_brief(Brief(**{**self.project.load_brief().__dict__,
                                         "constraints": list(lines)}))


class TestTheOrderOfTheParts(EnclosureCase):
    def test_with_no_constraint_the_model_is_not_asked_and_the_step_says_so(self):
        r = SchemaRouter(ORDER)
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(r.asked, [])
        self.assertIn("The brief has no constraint about where a part goes, so the model was "
                      "not asked for an order: the parts are in Nemo's own, largest first.",
                      sr.render())
        self.assertFalse(sr.degraded)

    def test_blank_constraints_count_as_none(self):
        self.constrain("", "   ")
        r = SchemaRouter(ORDER)
        self.run_step(r)
        self.assertEqual(r.asked, [])

    def test_with_a_constraint_it_is_asked_as_before(self):
        self.constrain("The display must be at one end.")
        r = SchemaRouter(ORDER)
        sr = self.run_step(r)
        self.assertEqual(len(r.asked), 1)
        self.assertIn("The display must be at one end.", r.asked[0]["user"])
        self.assertIn("Order along the box, chosen by the model", sr.render())

    def test_unasked_the_sensor_is_still_kept_from_the_warm_part_by_code(self):
        sr = self.run_step(SchemaRouter(ORDER))
        parts = self.parts
        placed = enclosure.auto_layout(parts, enclosure.box_for(
            self.project.load_brief().envelope_mm, self.cfg.get("hardware", {})),
            enclosure.thermal_order(parts))
        best = enclosure.nearest_sensor_gap(placed, parts)
        self.assertIsNotNone(best)
        self.assertIn(f"{best[2]:g} mm", sr.render())       # the distance code's order gives

    def test_a_box_is_drawn_either_way(self):
        self.run_step(SchemaRouter(ORDER))
        script = self.project.housing_script.read_text(encoding="utf-8")
        for ref in ("esp32_devkit_v1", "bme280", "ssd1306_oled_096"):
            self.assertIn(f"p_{ref} = (", script)


if __name__ == "__main__":
    unittest.main()
