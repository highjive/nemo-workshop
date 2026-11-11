"""The Computer Lab's Writer (owner, 2026-10-22): a firmware guide written
from what code decided, never from the model.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import firmware, labwriter, review, staff
from test_firmware_scaffold import swapped
from test_gates_real import WeatherCase


class TestTheGuide(WeatherCase):
    def wire(self, main: str | None = None):
        self.project.connections.parent.mkdir(parents=True, exist_ok=True)
        self.project.connections.write_text(json.dumps(swapped()), encoding="utf-8")
        src = self.project.firmware / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "main.cpp").write_text(main if main is not None else
                                      firmware.scaffold(swapped(), self.parts, "desk-weather",
                                                        "esp32dev", 10000), encoding="utf-8")
        (self.project.firmware / "platformio.ini").write_text(
            "[env:esp32dev]\nboard = esp32dev\nmonitor_speed = 115200\n", encoding="utf-8")

    def test_the_pins_are_the_ones_the_firmware_uses(self):
        self.wire()
        text = labwriter.guide(self.project, self.lib)
        # SCL on GPIO21 and SDA on 22, as the model chose on the laptop:
        # the guide must say what was wired, not the ESP32's defaults.
        self.assertIn("| bme280 | SCL | GPIO21 | 21 |", text)
        self.assertIn("| bme280 | SDA | GPIO22 | 22 |", text)
        self.assertIn("I2C: SDA on GPIO 22, SCL on GPIO 21; on it: bme280, ssd1306_oled_096.", text)
        self.assertIn("built for PlatformIO's `esp32dev`", text)
        self.assertEqual((self.project.firmware / "GUIDE.md").read_text(encoding="utf-8"), text)

    def test_what_nemo_s_own_firmware_does(self):
        self.wire()
        text = labwriter.guide(self.project, self.lib)
        self.assertIn("Nemo's bring-up firmware, written by code", text)
        self.assertIn("prints which addresses answer", text)
        self.assertIn("it updates every 10000 ms", text)
        self.assertIn("empty function, to be written from its datasheet: bme280", text)
        self.assertIn("at 115200 baud", text)
        self.assertIn("Not tried on a board yet.", text)

    def test_a_file_nemo_did_not_write_is_listed_not_explained(self):
        self.wire('#include <Arduino.h>\n#include "dht.h"\nvoid setup() {}\nvoid loop() {}\n'
                  'float readTemp() { return 0; }\n')
        text = labwriter.guide(self.project, self.lib)
        self.assertIn("not written by Nemo's code", text)
        self.assertIn("Includes: Arduino.h, dht.h", text)
        self.assertIn("Functions: loop, readTemp, setup", text)
        self.assertNotIn("bring-up firmware, written by code", text)

    def test_what_is_not_known_says_so(self):
        text = labwriter.guide(self.project, self.lib)
        self.assertIn("Not known: there are no connections yet", text)
        self.assertIn("There is no src/main.cpp yet", text)
        self.assertIn("there is no platformio.ini yet, so 115200 is assumed", text)

    def test_the_bench_runs_are_listed(self):
        self.wire()
        review.record(self.project.root, "firmware", "flashed", by="Flasher", ok=True)
        review.record(self.project.root, "firmware", "listened", by="Serial Monitor", ok=False)
        text = labwriter.guide(self.project, self.lib)
        self.assertIn(": flashed, passed", text)
        self.assertIn(": listened, did not pass", text)

    def test_the_writer_works(self):
        self.assertTrue(staff.STAFF["computer_lab.writer"].working)


if __name__ == "__main__":
    unittest.main()
