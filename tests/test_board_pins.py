"""D144: the ESP32 DevKit's pins, from Espressif's own table.

The third brief put to the real model (a tilt lamp: ESP32, an MPU-6050, a
WS2812B ring; AH531, qwen3-1.7b, 2026-10-06) passed every step with:

  esp32 -> mpu6050:  VIN-VCC, GND-GND, GPIO25-SDA, GPIO18-SCL, GPIO0-INT
  esp32 -> ring:     5V-5V, GND-GND, D0-DIN, D1-DOUT

GPIO0 and D0 are one pin under two names, so the check for one pin
carrying two signals saw two pins; the firmware gave both the number 0.
GPIO0 is a strapping pin and GPIO1 is the serial port the board is flashed
through. The library had no pins for the board, so nothing could object.

The list here is the one in the library, which cites its source: the GPIO
summary in Espressif's ESP-IDF Programming Guide v6.1.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import harness
from nemo.checks.deterministic import PASS
from nemo.parts import PartsLibrary
from nemo.pipeline import Pipeline
from test_gates_real import WeatherCase
from test_harness import good

# From that table, the pins it gives a caveat for.
STRAPPING = {0, 2, 5, 12, 15}
SERIAL = {1, 3}
FLASH = set(range(6, 12)) | {16, 17}
JTAG = {12, 13, 14, 15}
INPUT_ONLY = set(range(34, 40))
FREE = [4, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33]


def lamp_reply() -> dict:
    def w(a, b):
        return {"from_pin": a, "to_pin": b, "colour": "white"}
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "mpu6050", "gauge_awg": 24, "length_mm": 80,
         "wires": [w("VIN", "VCC"), w("GND", "GND"), w("GPIO25", "SDA"), w("GPIO18", "SCL"),
                   w("GPIO0", "INT")]},
        {"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 26, "length_mm": 80,
         "wires": [w("5V", "5V"), w("GND", "GND"), w("D0", "DIN"), w("D1", "DOUT")]}]}


class TestTheBoardsPins(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()
        self.esp = self.lib.get("esp32_devkit_v1")
        self.gpio = [int(p.name[4:]) for p in self.esp.pins if p.name.startswith("GPIO")]

    def test_they_are_the_eleven_the_table_gives_no_caveat_for(self):
        self.assertEqual(self.gpio, FREE)

    def test_none_is_a_pin_the_table_warns_about(self):
        for group in (STRAPPING, SERIAL, FLASH, JTAG, INPUT_ONLY):
            self.assertEqual(set(self.gpio) & group, set())

    def test_its_supply_pins_say_what_they_give(self):
        self.assertEqual((self.esp.pin("3V3").function, self.esp.pin("3V3").voltage),
                         ("power", 3.3))
        self.assertEqual((self.esp.pin("VIN").function, self.esp.pin("VIN").voltage),
                         ("power", 5.0))
        self.assertEqual(self.esp.pin("GND").function, "gnd")
        self.assertIsNone(self.esp.pin("5V"))               # this board's 5 V pin is VIN

    def test_every_gpio_is_a_3v3_io_pin(self):
        for p in self.esp.pins:
            if p.name.startswith("GPIO"):
                self.assertEqual((p.function, p.voltage), ("io", 3.3), p.name)

    def test_the_board_still_without_a_list_is_not_hidden(self):
        # The C3 and the Pico have had one since D163.
        for ref in ("waveshare_esp32s3_lcd_128",):
            self.assertEqual(self.lib.get(ref).pins, [], ref)


class TestTheLampWiring(unittest.TestCase):
    def setUp(self):
        lib = PartsLibrary.load()
        self.parts = [lib.get(r) for r in ("esp32_devkit_v1", "mpu6050", "ws2812b_ring8")]

    def test_it_is_refused_naming_the_first_pin_the_board_does_not_offer(self):
        with self.assertRaises(harness.HarnessError) as ctx:
            harness.build(lamp_reply(), self.parts)
        self.assertIn("esp32_devkit_v1 has no pin 'GPIO0'", str(ctx.exception))
        self.assertIn("GPIO4, GPIO18", str(ctx.exception))     # and says what it does offer

    def test_none_of_its_four_bad_pins_can_be_written_under_the_schema(self):
        v = next(x for x in harness.harness_schema(self.parts)["properties"]["cables"]["items"]
                 ["anyOf"] if x["properties"]["from"]["const"] == "esp32_devkit_v1")
        allowed = v["properties"]["wires"]["items"]["properties"]["from_pin"]["enum"]
        for pin in ("GPIO0", "D0", "D1", "5V"):
            self.assertNotIn(pin, allowed)
        self.assertIn("GPIO25", allowed)

    def test_wired_to_pins_the_board_has_it_builds(self):
        doc = lamp_reply()
        doc["cables"][0]["wires"][4]["from_pin"] = "GPIO4"
        doc["cables"][1]["wires"] = [dict(w) for w in doc["cables"][1]["wires"][:3]]
        doc["cables"][1]["wires"][0]["from_pin"] = "VIN"
        doc["cables"][1]["wires"][2]["from_pin"] = "GPIO23"
        harness.build(doc, self.parts)


class TestTheBoardIsNowChecked(WeatherCase):
    def test_its_pins_are_verified_and_nothing_is_left_unchecked(self):
        text, _ = harness.build(good(), self.parts)
        r = Pipeline.check_harness_pins(self.harness(text), self.parts)
        self.assertEqual(r.status, PASS, r.render())
        self.assertNotIn("unchecked", r.render())
        self.assertIn("16 pin(s) verified", r.detail)        # 8 on the board's side now too

    def test_the_model_is_given_the_list_and_no_instruction_about_it(self):
        line = harness.part_facts(self.parts).splitlines()[0]
        self.assertTrue(line.endswith("3V3, VIN, GND, GPIO4, GPIO18, GPIO19, GPIO21, GPIO22, "
                                      "GPIO23, GPIO25, GPIO26, GPIO27, GPIO32, GPIO33"))


if __name__ == "__main__":
    unittest.main()
