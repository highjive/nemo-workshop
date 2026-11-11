"""The firmware step writes a bring-up firmware from the connections.

Three times on the real AH531 the 1.7B model was asked for src/main.cpp.
It invented pin numbers, then included headers that do not exist, then
wrote statements outside any function. firmware.py writes instead what
follows entirely from the wiring, and leaves each part's own logic as an
empty, labelled function, because that needs datasheet figures Nemo does
not invent.

The last class compiles the result with real PlatformIO and is skipped
unless the ESP32 platform is already installed. It never downloads one.
"""
from __future__ import annotations

import json, os, re, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, firmware
from nemo.checks.deterministic import FAIL, PASS, Result
from nemo.router import Reply
from test_gates_real import WeatherCase
from test_harness import good
from test_schematic_from_connections import rfid


def swapped() -> dict:
    """What the model really chose on the laptop: SCL on GPIO21, SDA on 22,
    the reverse of the ESP32's defaults."""
    doc = good()
    for cable in doc["cables"]:
        for w in cable["wires"]:
            if w["to_pin"] == "SCL":
                w["from_pin"] = "GPIO21"
            elif w["to_pin"] == "SDA":
                w["from_pin"] = "GPIO22"
    return doc


class TestPlan(WeatherCase):
    def test_the_i2c_pins_are_the_ones_that_were_wired_not_the_defaults(self):
        p = firmware.plan(swapped(), self.parts)
        self.assertEqual(p.i2c, (22, 21))                # (SDA, SCL), as wired
        self.assertEqual(p.i2c_parts, ["bme280", "ssd1306_oled_096"])
        self.assertEqual(firmware.plan(good(), self.parts).i2c, (21, 22))

    def test_every_wire_to_the_microcontroller_is_a_named_constant(self):
        p = firmware.plan(good(), self.parts)
        self.assertEqual([(w.const, w.gpio) for w in p.pins],
                         [("PIN_BME280_SCL", 22), ("PIN_BME280_SDA", 21),
                          ("PIN_SSD1306_OLED_096_SCL", 22), ("PIN_SSD1306_OLED_096_SDA", 21)])
        self.assertNotIn("VCC", " ".join(w.part_pin for w in p.pins))    # supply is not a GPIO

    def test_an_spi_part_gets_the_bus_and_its_own_select(self):
        parts = [self.lib.get("esp32_devkit_v1"), self.lib.get("rc522")]
        p = firmware.plan(rfid(), parts)
        self.assertEqual(p.spi, (18, 19, 23))            # SCK, MISO, MOSI
        self.assertEqual(p.spi_selects, [("rc522", 5)])  # its pin called SDA is the select
        self.assertIsNone(p.i2c)

    def test_two_parts_on_different_i2c_pins_is_refused(self):
        doc = good()
        doc["cables"][1]["wires"][2]["from_pin"] = "GPIO19"
        with self.assertRaises(firmware.FirmwareError) as ctx:
            firmware.plan(doc, self.parts)
        self.assertIn("both must share one pair of pins", str(ctx.exception))

    def test_a_microcontroller_pin_that_is_not_a_gpio_number_is_refused(self):
        doc = good()
        doc["cables"][0]["wires"][2]["from_pin"] = "SCLPIN"
        with self.assertRaises(firmware.FirmwareError) as ctx:
            firmware.plan(doc, self.parts)
        self.assertIn("'SCLPIN' is not a GPIO number", str(ctx.exception))

    def test_a_bus_pin_that_never_reaches_the_microcontroller_is_refused(self):
        doc = good()
        doc["cables"][0]["wires"] = doc["cables"][0]["wires"][:2]       # power only
        with self.assertRaises(firmware.FirmwareError) as ctx:
            firmware.plan(doc, self.parts)
        self.assertIn("bme280.SDA is not wired to esp32_devkit_v1", str(ctx.exception))


class TestScaffold(WeatherCase):
    def source(self, doc=None, **kw):
        return firmware.scaffold(doc or swapped(), self.parts, "desk-weather", "esp32dev", **kw)

    def test_what_the_firmware_prompt_always_asked_for_is_there(self):
        text = self.source(update_ms=10000)
        self.assertIn("#include <Arduino.h>", text)
        self.assertIn("Serial.begin(115200);", text)
        self.assertIn("__DATE__", text)                  # the build date in the banner
        self.assertIn("if (!Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL))", text)   # begin() is checked
        self.assertIn("const unsigned long UPDATE_EVERY_MS = 10000UL;", text)
        self.assertNotIn("delay(", text)                 # loop never blocks
        self.assertIn("now - lastUpdate >= UPDATE_EVERY_MS", text)

    def test_it_uses_only_headers_that_exist(self):
        headers = set(re.findall(r"#include <([^>]+)>", self.source()))
        self.assertEqual(headers, {"Arduino.h", "Wire.h"})
        parts = [self.lib.get("esp32_devkit_v1"), self.lib.get("rc522")]
        spi = firmware.scaffold(rfid(), parts, "rfid", "esp32dev")
        self.assertEqual(set(re.findall(r"#include <([^>]+)>", spi)), {"Arduino.h", "SPI.h"})
        self.assertIn("SPI.begin(PIN_SPI_SCK, PIN_SPI_MISO, PIN_SPI_MOSI);", spi)
        self.assertIn("digitalWrite(PIN_SPI_SELECT_RC522, HIGH);", spi)

    def test_the_bus_is_started_on_the_pins_as_wired(self):
        text = self.source()
        self.assertIn("const int PIN_I2C_SDA = 22;", text)
        self.assertIn("const int PIN_I2C_SCL = 21;", text)

    def test_it_scans_the_bus_and_says_how_many_parts_to_expect(self):
        text = self.source()
        self.assertIn("int scanI2C()", text)
        self.assertIn("2 expected (bme280, ssd1306_oled_096)", text)

    def test_it_says_plainly_what_it_did_not_write(self):
        text = self.source()
        self.assertIn("It is NOT the finished application", text)
        self.assertIn("// NOT GENERATED. What bme280 does each update goes here.", text)
        self.assertIn("void update_bme280() {\n}", text)
        self.assertIn('Serial.println("bme280: its own logic is not generated yet");', text)

    def test_no_register_address_or_other_datasheet_figure_is_invented(self):
        # The scan loop's 0x%02X format is the only hex in the file.
        self.assertEqual(re.findall(r"0x[0-9A-Fa-f]{2}\b", self.source()), [])

    def test_braces_balance_and_every_statement_is_inside_a_function(self):
        text = self.source()
        self.assertEqual(text.count("{"), text.count("}"))
        depth = 0
        for line in text.splitlines():
            code = line.split("//")[0].strip()
            if depth == 0 and code and not code.startswith("#"):
                self.assertRegex(code, r"^(const |unsigned long |int |void |})", line)
            depth += code.count("{") - code.count("}")

    def test_only_esp32_boards_for_now(self):
        with self.assertRaises(firmware.FirmwareError) as ctx:
            firmware.scaffold(good(), self.parts, "x", "pico")
        self.assertIn("only written for ESP32", str(ctx.exception))


class TestIntervalFromText(unittest.TestCase):
    def test_periods_written_out(self):
        for text, ms in (("updates every ten seconds", 10000), ("every 250 ms", 250),
                         ("blinks twice a second", 500), ("logs once a minute", 60000),
                         ("checks each second", 1000), ("every half a second", 500),
                         ("runs every 5 minutes", 300000), ("Every Hour", 3600000),
                         ("polls 4 times a second", 250)):
            got = firmware.interval_from_text(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(got[0], ms, text)

    def test_the_words_it_read_are_returned_for_the_owner(self):
        self.assertEqual(firmware.interval_from_text("It updates every ten seconds, quietly.")[1],
                         "every ten seconds")

    def test_anything_it_is_not_sure_of_is_left_alone(self):
        for text in ("It beeps when a card is read.", "every single time", "every 3 fortnights",
                     "every 0.001 ms", "every several seconds", "", None):
            self.assertIsNone(firmware.interval_from_text(text), text)


class ChoiceRouter:
    supports_schema = True
    timeout = 1800

    def __init__(self, reply='{"update_every_ms": 10000}'):
        self.reply, self.asked = reply, []

    def ask(self, task, system, user, **kw):
        self.asked.append({"task": task, "system": system, "user": user, **kw})
        return Reply(self.reply, "local", "stub")

    def local_up(self):
        return True


class TestFirmwareStep(WeatherCase):
    def setUp(self):
        super().setUp()
        self.project.connections.parent.mkdir(parents=True, exist_ok=True)
        self.project.connections.write_text(json.dumps(swapped()), encoding="utf-8")

    def run_step(self, router, result=None):
        built = result or Result("compile", PASS, "builds clean")
        with mock.patch.object(checks, "compile_firmware", return_value=built):
            return self.pipe(router).stage_firmware()

    def source(self):
        return (self.project.firmware / "src" / "main.cpp").read_text(encoding="utf-8")

    def test_an_interval_the_brief_states_is_read_and_the_model_is_not_asked(self):
        # This brief says "updates every ten seconds". On the real laptop
        # the model, asked for the interval, answered 1000.
        r = ChoiceRouter('{"update_every_ms": 1000}')
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(r.asked, [])            # it was up to three calls, each for a whole file
        self.assertEqual(self.source(),
                         firmware.scaffold(swapped(), self.parts, "desk-weather", "esp32dev", 10000))
        self.assertIn('Updates every 10000 ms: the brief says "every ten seconds"', sr.render())

    def unstated(self):
        return mock.patch.object(firmware, "interval_from_text", return_value=None)

    def test_where_the_brief_is_silent_nemo_uses_its_own_figure_and_asks_nobody(self):
        # D172. The model used to be asked: three minutes on the real machine
        # for a guess, which was 1000 ms both times.
        r = ChoiceRouter('{"update_every_ms": 2500}')
        with self.unstated():
            sr = self.run_step(r)
        self.assertEqual(r.asked, [])
        self.assertIn("UPDATE_EVERY_MS = 1000UL", self.source())
        self.assertIn("Updates every 1000 ms, Nemo's own figure: the brief does not state an "
                      "interval. Say how often in the brief", sr.render())
        self.assertNotIn("chosen by the model", sr.render())

    def test_the_owner_is_told_it_is_a_bring_up_firmware(self):
        text = self.run_step(ChoiceRouter()).render()
        self.assertIn("Each part's own logic is NOT generated", text)

    def test_whatever_a_model_would_say_the_step_passes_on_the_default(self):
        for reply in ("I am not sure.", '{"update_every_ms": "often"}', '{"update_every_ms": 5}'):
            with self.unstated():
                sr = self.run_step(ChoiceRouter(reply))
            self.assertTrue(sr.ok, reply)
            self.assertIn("UPDATE_EVERY_MS = 1000UL", self.source())

    def test_connections_no_firmware_can_be_written_from_fail_with_the_reason(self):
        doc = swapped()
        doc["cables"][1]["wires"][2]["from_pin"] = "GPIO19"
        self.project.connections.write_text(json.dumps(doc), encoding="utf-8")
        sr = self.run_step(ChoiceRouter())
        self.assertFalse(sr.ok)
        self.assertIn("both must share one pair of pins", sr.render())
        self.assertEqual(sr.go_back_to, "electrical")

    def test_a_build_that_fails_is_this_steps_own(self):
        bad = Result("compile", FAIL, "build failed (rc=1)", ["src/main.cpp:1:1: error: x"])
        sr = self.run_step(ChoiceRouter(), bad)
        self.assertFalse(sr.ok)
        self.assertEqual(sr.go_back_to, "firmware")
        self.assertEqual(len(sr.results), 1)

    def test_without_saved_connections_the_old_request_is_made(self):
        self.project.connections.unlink()
        r = ChoiceRouter("```cpp\nvoid setup(){}\nvoid loop(){}\n```")
        self.run_step(r)
        self.assertNotIn("schema", r.asked[0])
        self.assertIn("Arduino-framework C++", r.asked[0]["system"])


REAL_PIO_HOME = _sandbox.REAL_HOME / ".platformio"
HAVE_PLATFORM = (REAL_PIO_HOME / "platforms" / "espressif32").is_dir()


@unittest.skipUnless(HAVE_PLATFORM, "the ESP32 platform is not installed; "
                                    "this test never downloads it")
class TestItCompilesWithRealPlatformIO(WeatherCase):
    """Slow: about 90 s a build on the AH531."""

    def build(self, doc, parts, name):
        fw = self.tmp / "fw"
        (fw / "src").mkdir(parents=True)
        (fw / "platformio.ini").write_text(
            "[env:esp32dev]\nplatform = espressif32\nboard = esp32dev\nframework = arduino\n",
            encoding="utf-8")
        (fw / "src" / "main.cpp").write_text(
            firmware.scaffold(doc, parts, name, "esp32dev", 10000), encoding="utf-8")
        # The installed toolchain, not a fresh download into the test sandbox.
        with mock.patch.dict(os.environ, {"PLATFORMIO_CORE_DIR": str(REAL_PIO_HOME)}):
            return checks.compile_firmware(fw)

    def test_the_i2c_bring_up_firmware_builds_clean(self):
        r = self.build(swapped(), self.parts, "desk-weather")
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn("Flash:", r.render())

    def test_the_spi_bring_up_firmware_builds_clean(self):
        parts = [self.lib.get("esp32_devkit_v1"), self.lib.get("rc522")]
        r = self.build(rfid(), parts, "rfid-reader")
        self.assertEqual(r.status, PASS, r.render())


if __name__ == "__main__":
    unittest.main(verbosity=2)
