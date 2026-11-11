"""D149: two signals on one pin of the board are given a pin each by code.

Second real run of the tilt lamp with a level shifter (AH531, qwen3-1.7b,
2026-10-07). The model's signal wires:

  esp32 -> mpu6050: GPIO4-SDA, GPIO18-SCL, GPIO21-INT, GPIO22-AD0
  esp32 -> ring:    GPIO4-DIN, GPIO18-DOUT

GPIO4 for the sensor's data line and for the ring. The check caught it,
the fault was quoted back, and "A second attempt was no better".
"""
from __future__ import annotations

import sys, unittest
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

REFS = ("esp32_devkit_v1", "mpu6050", "ws2812b_ring8", "sn74ahct125")


def w(a, b):
    return {"from_pin": a, "to_pin": b, "colour": "white"}


def real_reply() -> dict:
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 22, "length_mm": 80,
         "wires": [w("3V3", "5V"), w("GND", "GND"), w("GPIO4", "DIN"), w("GPIO18", "DOUT")]},
        {"from": "esp32_devkit_v1", "to": "mpu6050", "gauge_awg": 22, "length_mm": 80,
         "wires": [w("3V3", "VCC"), w("GND", "GND"), w("GPIO4", "SDA"), w("GPIO18", "SCL"),
                   w("GPIO21", "INT"), w("GPIO22", "AD0")]}]}


def board_pins(doc, part):
    return {x["to_pin"]: x["from_pin"] for c in doc["cables"]
            if (c["from"], c["to"]) == ("esp32_devkit_v1", part) for x in c["wires"]}


class LampCase(PipelineCase):
    PARTS = REFS

    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="tilt-lamp", function="A ring of lights that changes colour as it is tilted.",
            power="USB 5 V 2 A", supply_ma=2000, rails=[5.0, 3.3], envelope_mm=[110, 70, 35],
            parts=list(self.PARTS), mcu="esp32", done_when="Tilting it changes the colour."))
        self.parts = [self.lib.get(r) for r in self.PARTS]


class TestEachSignalGetsItsOwnPin(LampCase):
    def setUp(self):
        super().setUp()
        self.fixed, self.notes = harness.spread_shared_pins(real_reply(), self.parts)

    def test_the_first_signal_keeps_the_pin_and_the_others_move_to_free_ones(self):
        ring, imu = board_pins(self.fixed, "ws2812b_ring8"), board_pins(self.fixed, "mpu6050")
        self.assertEqual((ring["DIN"], ring["DOUT"]), ("GPIO4", "GPIO18"))     # met first
        self.assertEqual((imu["INT"], imu["AD0"]), ("GPIO21", "GPIO22"))      # never shared
        self.assertNotIn(imu["SDA"], ("GPIO4", "GPIO18", "GPIO21", "GPIO22"))
        self.assertNotIn(imu["SCL"], ("GPIO4", "GPIO18", "GPIO21", "GPIO22", imu["SDA"]))

    def test_no_pin_of_the_board_then_carries_two_signals(self):
        used = [p for part in ("ws2812b_ring8", "mpu6050")
                for name, p in board_pins(self.fixed, part).items() if p.startswith("GPIO")]
        self.assertEqual(len(used), len(set(used)))

    def test_they_move_only_to_pins_the_board_lists(self):
        listed = {p.name for p in self.parts[0].pins}
        for part in ("ws2812b_ring8", "mpu6050"):
            self.assertLessEqual(set(board_pins(self.fixed, part).values()), listed)

    def test_it_says_which_and_where(self):
        self.assertEqual(len(self.notes), 2)
        self.assertRegex(self.notes[0],
                         r"^esp32_devkit_v1\.GPIO4 was wired to both ws2812b_ring8\.DIN and "
                         r"mpu6050\.SDA\. One pin cannot carry two signals, so Nemo moved "
                         r"mpu6050\.SDA to esp32_devkit_v1\.GPIO\d+\.$")

    def test_power_wires_and_the_answer_it_was_given_are_untouched(self):
        self.assertEqual(board_pins(self.fixed, "mpu6050")["VCC"], "3V3")
        doc = real_reply()
        harness.spread_shared_pins(doc, self.parts)
        self.assertEqual(doc, real_reply())

    def test_done_twice_it_changes_nothing(self):
        self.assertEqual(harness.spread_shared_pins(self.fixed, self.parts), (self.fixed, []))


class TestABusStaysTogether(WeatherCase):
    def test_two_parts_on_one_i2c_bus_keep_their_shared_pins(self):
        self.assertEqual(harness.spread_shared_pins(good(), self.parts), (good(), []))


class TestWhereItCannot(LampCase):
    def test_a_board_with_no_pin_list_is_left_alone(self):
        parts = [self.lib.get("waveshare_esp32s3_lcd_128"), self.lib.get("mpu6050"),
                 self.lib.get("ws2812b_ring8")]
        doc = real_reply()
        for c in doc["cables"]:
            c["from"] = "waveshare_esp32s3_lcd_128"
        self.assertEqual(harness.spread_shared_pins(doc, parts), (doc, []))

    def test_with_no_pin_free_nothing_moves_and_the_check_still_fails(self):
        board = self.parts[0]
        few = type(board)(**{**board.__dict__,
                             "pins": [p for p in board.pins
                                      if p.name in ("3V3", "VIN", "GND", "GPIO4")]})
        parts = [few, self.parts[1], self.parts[2]]
        doc = {"cables": [
            {"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 22, "length_mm": 80,
             "wires": [w("GPIO4", "DIN")]},
            {"from": "esp32_devkit_v1", "to": "mpu6050", "gauge_awg": 22, "length_mm": 80,
             "wires": [w("GPIO4", "INT")]}]}
        fixed, notes = harness.spread_shared_pins(doc, parts)
        self.assertEqual((fixed, notes), (doc, []))
        text, _ = harness.build(fixed, parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        self.assertEqual(Pipeline.check_harness_signals(self.project.harness, parts).status,
                         "FAIL")


class TestTheStep(LampCase):
    def test_the_real_answer_passes_at_the_first_asking(self):
        r = SchemaRouter(real_reply())
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            sr = self.pipe(r).stage_wiring()
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        text = sr.render()
        self.assertIn("One pin cannot carry two signals, so Nemo moved", text)
        self.assertIn("so Nemo routed it through sn74ahct125", text)
        self.assertIn("Set aside the wire from ws2812b_ring8.DOUT", text)
        for name in ("harness_signals", "harness_supply", "harness_levels",
                     "harness_electrical"):
            self.assertEqual(next(x for x in sr.results if x.name == name).status, PASS, name)


class TestOneI2CBus(unittest.TestCase):
    """D269: Gemma 4 E4B's real reply (2026-11-11) put the screen on GPIO4/3 and
    the BME280 on GPIO6/7; electrical passed it, firmware refused it."""

    def setUp(self):
        from nemo import firmware
        from nemo.parts import PartsLibrary
        lib = PartsLibrary.load()
        self.firmware = firmware
        self.parts = [lib.get(r) for r in ("esp32c3_devkit", "bme280", "ssd1306_oled_096")]
        self.reply = {"cables": [
            {"from": "esp32c3_devkit", "to": "bme280",
             "wires": [w("3V3", "VCC"), w("GND", "GND"), w("GPIO7", "SCL"), w("GPIO6", "SDA")]},
            {"from": "esp32c3_devkit", "to": "ssd1306_oled_096",
             "wires": [w("3V3", "VCC"), w("GND", "GND"), w("GPIO3", "SCL"), w("GPIO4", "SDA")]}]}

    def test_the_second_part_joins_the_first_parts_pair(self):
        with self.assertRaises(self.firmware.FirmwareError):   # what stopped the trial
            self.firmware.plan(self.reply, self.parts)
        fixed, notes = harness.join_i2c_bus(self.reply, self.parts)
        oled = {x["to_pin"]: x["from_pin"] for x in fixed["cables"][1]["wires"]}
        self.assertEqual((oled["SDA"], oled["SCL"]), ("GPIO6", "GPIO7"))
        self.assertIn("one bus", notes[0])
        self.assertEqual(self.firmware.plan(fixed, self.parts).i2c, (6, 7))
        self.assertEqual(harness.join_i2c_bus(fixed, self.parts), (fixed, []))
        self.assertEqual(self.reply["cables"][1]["wires"][2]["from_pin"], "GPIO3")  # not changed in place


if __name__ == "__main__":
    unittest.main()
