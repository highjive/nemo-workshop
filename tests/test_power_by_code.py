"""D145: power and ground are wired by code, not by the model.

Second real run of the tilt-lamp brief (AH531, qwen3-1.7b, 2026-10-06),
the first with the board's pins listed for the model to choose from:

  esp32 -> ring:    3V3-5V, GND-GND, VIN-GND, GPIO22-DIN, GPIO23-DOUT,
                    GPIO25-GND, GPIO26-GND, GPIO27-GND
  esp32 -> mpu6050: 3V3-VCC, GND-GND, GPIO18-SCL, GPIO19-SDA, GPIO21-INT, GPIO22-AD0

A 5 V ring on the 3.3 V pin; VIN wired to a ground pin; three GPIOs run to
ground; GPIO22 doing two jobs. The step failed, on the first and the last
of those. The short was not named by anything.
"""
from __future__ import annotations

import copy, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, harness
from nemo.checks.deterministic import PASS, Result
from nemo.pipeline import Pipeline
from nemo.project import Brief
from test_gates_real import WeatherCase
from test_harness import SchemaRouter, good
from test_pipeline import PipelineCase

REFS = ("esp32_devkit_v1", "mpu6050", "ws2812b_ring8")


def w(a, b):
    return {"from_pin": a, "to_pin": b, "colour": "white"}


def real_reply() -> dict:
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 26, "length_mm": 80,
         "wires": [w("3V3", "5V"), w("GND", "GND"), w("VIN", "GND"), w("GPIO22", "DIN"),
                   w("GPIO23", "DOUT"), w("GPIO25", "GND"), w("GPIO26", "GND"),
                   w("GPIO27", "GND")]},
        {"from": "esp32_devkit_v1", "to": "mpu6050", "gauge_awg": 24, "length_mm": 80,
         "wires": [w("3V3", "VCC"), w("GND", "GND"), w("GPIO18", "SCL"), w("GPIO19", "SDA"),
                   w("GPIO21", "INT"), w("GPIO22", "AD0")]}]}


def pairs(doc, a, b):
    out = []
    for c in doc["cables"]:
        if {c["from"], c["to"]} == {a, b}:
            flip = c["from"] != a
            out += [(x["to_pin"], x["from_pin"]) if flip else (x["from_pin"], x["to_pin"])
                    for x in c["wires"]]
    return out


class LampCase(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="tilt-lamp", function="A ring of lights that changes colour as it is tilted.",
            power="USB 5 V 2 A", supply_ma=2000, rails=[5.0, 3.3], envelope_mm=[110, 70, 35],
            parts=list(REFS), mcu="esp32", done_when="Tilting it changes the colour."))
        self.parts = [self.lib.get(r) for r in REFS]

    def path(self, doc):
        text, _ = harness.build(doc, self.parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        return self.project.harness


class TestWhatTheChecksSaidOfTheRealWiring(LampCase):
    def test_the_short_is_now_named(self):
        r = Pipeline.check_harness_supply(self.path(real_reply()), self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("esp32_devkit_v1.VIN (5 V) is wired to", r.render())
        self.assertIn("a supply joined to ground is a short circuit", r.render())

    def test_and_so_is_the_ring_on_the_wrong_pin(self):
        r = Pipeline.check_harness_supply(self.path(real_reply()), self.parts)
        self.assertIn("ws2812b_ring8.5V is fed from esp32_devkit_v1.3V3, which is 3.3 V. "
                      "The part runs from 5 V", r.render())

    def test_a_gpio_run_to_a_ground_pin_is_named(self):
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 22,
                           "length_mm": 80, "wires": [w("VIN", "5V"), w("GPIO25", "GND")]}]}
        r = Pipeline.check_harness_signals(self.path(doc), self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("esp32_devkit_v1.GPIO25 is wired to ws2812b_ring8.GND, which is a "
                      "supply or ground pin, not a signal", r.render())

    def test_one_gpio_for_two_signals_was_already_caught(self):
        r = Pipeline.check_harness_signals(self.path(real_reply()), self.parts)
        self.assertIn("esp32_devkit_v1.GPIO22 is wired to mpu6050.AD0 and ws2812b_ring8.DIN",
                      r.render())


class TestPowerIsWiredByCode(LampCase):
    def setUp(self):
        super().setUp()
        self.fixed, self.notes = harness.wire_power(real_reply(), self.parts)

    def test_each_part_is_on_the_supply_it_can_take_and_on_ground(self):
        ring = pairs(self.fixed, "esp32_devkit_v1", "ws2812b_ring8")
        imu = pairs(self.fixed, "esp32_devkit_v1", "mpu6050")
        self.assertEqual(ring[:2], [("VIN", "5V"), ("GND", "GND")])
        self.assertEqual(imu[:2], [("3V3", "VCC"), ("GND", "GND")])    # the model's, kept

    def test_the_models_signal_wires_are_untouched(self):
        ring = pairs(self.fixed, "esp32_devkit_v1", "ws2812b_ring8")
        imu = pairs(self.fixed, "esp32_devkit_v1", "mpu6050")
        self.assertEqual(ring[2:], [("GPIO22", "DIN"), ("GPIO23", "DOUT")])
        self.assertEqual(imu[2:], [("GPIO18", "SCL"), ("GPIO19", "SDA"), ("GPIO21", "INT"),
                                   ("GPIO22", "AD0")])

    def test_nothing_else_reaches_a_supply_or_ground_pin(self):
        for c in self.fixed["cables"]:
            for x in c["wires"][2:]:
                self.assertNotIn(x["to_pin"], ("GND", "5V", "VCC"))
                self.assertNotIn(x["from_pin"], ("GND", "VIN", "3V3"))

    def test_it_says_what_it_moved_and_what_it_set_aside(self):
        text = "\n".join(self.notes)
        self.assertIn("ws2812b_ring8.5V was wired to esp32_devkit_v1.3V3 (3.3 V). The part runs "
                      "from 5 V, so Nemo moved that wire to esp32_devkit_v1.VIN.", text)
        self.assertIn("Set aside 4 wire(s) the model ran to supply or ground pins where none "
                      "belongs: esp32_devkit_v1.VIN to ws2812b_ring8.GND", text)
        self.assertIn("esp32_devkit_v1.GPIO27 to ws2812b_ring8.GND", text)
        self.assertNotIn("mpu6050.VCC", text)                # that one was right

    def test_the_supply_check_then_passes_and_the_signal_fault_remains(self):
        p = self.path(self.fixed)
        self.assertEqual(Pipeline.check_harness_supply(p, self.parts).status, PASS)
        self.assertEqual(Pipeline.check_harness_electrical(p, self.parts).status, PASS)
        r = Pipeline.check_harness_signals(p, self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertEqual(len(r.items), 1)                    # GPIO22, twice: the model's to fix

    def test_done_twice_it_changes_nothing_and_says_nothing(self):
        again, notes = harness.wire_power(self.fixed, self.parts)
        self.assertEqual(again, self.fixed)
        self.assertEqual(notes, [])

    def test_the_answer_it_was_given_is_not_altered(self):
        doc = real_reply()
        harness.wire_power(doc, self.parts)
        self.assertEqual(doc, real_reply())


class TestOtherShapes(LampCase):
    def test_a_part_the_model_gave_no_power_gets_it_and_a_cable_if_it_had_none(self):
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "mpu6050", "gauge_awg": 24,
                           "length_mm": 80, "wires": [w("GPIO18", "SCL"), w("GPIO19", "SDA")]}]}
        fixed, notes = harness.wire_power(doc, self.parts)
        self.assertEqual(pairs(fixed, "esp32_devkit_v1", "mpu6050")[:2],
                         [("3V3", "VCC"), ("GND", "GND")])
        self.assertEqual(pairs(fixed, "esp32_devkit_v1", "ws2812b_ring8"),
                         [("VIN", "5V"), ("GND", "GND")])
        text = "\n".join(notes)
        self.assertIn("mpu6050.VCC had no supply wire from the board, so Nemo wired it to "
                      "esp32_devkit_v1.3V3.", text)
        self.assertIn("ws2812b_ring8.GND had no ground wire from the board, so Nemo added one.",
                      text)

    def test_a_cable_written_from_the_part_to_the_board_is_wired_the_right_way_round(self):
        doc = {"cables": [{"from": "mpu6050", "to": "esp32_devkit_v1", "gauge_awg": 24,
                           "length_mm": 80, "wires": [w("SCL", "GPIO18"), w("SDA", "GPIO19")]}]}
        fixed, _ = harness.wire_power(doc, self.parts)
        cable = next(c for c in fixed["cables"] if c["from"] == "mpu6050")
        self.assertEqual((cable["wires"][0]["from_pin"], cable["wires"][0]["to_pin"]),
                         ("VCC", "3V3"))
        harness.build(fixed, self.parts)

    def test_power_passed_from_one_module_to_the_next_becomes_a_wire_each(self):
        doc = real_reply()
        doc["cables"].append({"from": "mpu6050", "to": "ws2812b_ring8", "gauge_awg": 22,
                              "length_mm": 50, "wires": [w("VCC", "5V"), w("GND", "GND")]})
        fixed, notes = harness.wire_power(doc, self.parts)
        self.assertEqual(len(fixed["cables"]), 2)             # the emptied cable is gone
        self.assertNotIn("mpu6050.VCC to ws2812b_ring8.5V", "\n".join(notes))

    def test_a_part_no_board_pin_suits_is_left_for_the_check_to_fail(self):
        odd = copy.copy(self.lib.get("mpu6050"))
        odd.supply_v = [12.0]
        parts = [self.parts[0], odd]
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "mpu6050", "gauge_awg": 24,
                           "length_mm": 80, "wires": [w("VIN", "VCC"), w("GPIO18", "SCL")]}]}
        fixed, notes = harness.wire_power(doc, parts)
        self.assertEqual(pairs(fixed, "esp32_devkit_v1", "mpu6050")[0], ("VIN", "VCC"))

    def test_with_a_battery_in_the_project_only_the_narrower_fix_is_made(self):
        parts = self.parts + [self.lib.get("lipo_1000")]
        fixed, notes = harness.wire_power(real_reply(), parts)
        self.assertIn(("VIN", "GND"), pairs(fixed, "esp32_devkit_v1", "ws2812b_ring8"))

    def test_a_board_with_no_pin_list_offers_3v3_and_vin(self):
        self.assertEqual(harness.board_supplies(self.lib.get("esp32c3_devkit"))[0], ("3V3", 3.3))
        self.assertEqual(harness.board_supplies(self.lib.get("esp32_devkit_v1")),
                         [("3V3", 3.3), ("VIN", 5.0)])


class TestASoundWiringIsLeftAlone(WeatherCase):
    def test_nothing_is_changed_or_said(self):
        fixed, notes = harness.wire_power(good(), self.parts)
        self.assertEqual(notes, [])
        self.assertEqual({(c["from"], c["to"]): [(x["from_pin"], x["to_pin"]) for x in c["wires"]]
                          for c in fixed["cables"]},
                         {(c["from"], c["to"]): [(x["from_pin"], x["to_pin"]) for x in c["wires"]]
                          for c in good()["cables"]})


class TestTheStep(LampCase):
    def run_step(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_nothing_is_sent_back_to_the_model_at_all(self):
        # Was "only the signal fault is sent back": GPIO22 on two signals was
        # the model's to fix. Since D149 code gives each its own pin, and since
        # D147 the ring's 5 V output is set aside, so the first answer passes.
        r = SchemaRouter(real_reply())
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        text = sr.render()
        self.assertIn("so Nemo moved that wire to esp32_devkit_v1.VIN", text)
        self.assertIn("Set aside 4 wire(s)", text)
        self.assertIn("esp32_devkit_v1.GPIO22 was wired to both ws2812b_ring8.DIN and "
                      "mpu6050.AD0. One pin cannot carry two signals, so Nemo moved "
                      "mpu6050.AD0 to", text)


if __name__ == "__main__":
    unittest.main()
