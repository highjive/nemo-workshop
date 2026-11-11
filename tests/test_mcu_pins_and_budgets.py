"""D135 and D136, from the first Design-mode pipeline run on the AH531
(qwen3-4b, 2026-10-06, 26.5 minutes).

D135: the 4B model wired the ESP32's bus pins as "SCL" and "SDA". The dev
board has no pin list in the library, so any short name was allowed, every
electrical check passed, and the run failed at the firmware step, which
needs a GPIO number, with "fix at stage 'electrical'".

D136: the memory budgets were estimates below what the models were then
measured to hold, and the launcher chose a mode from a third number.
"""
from __future__ import annotations

import copy, re, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

import yaml

from nemo import checks, firmware, harness
from nemo.checks.deterministic import PASS, Result
from nemo.config import DEFAULTS
from test_gates_real import WeatherCase
from test_harness import SchemaRouter, good

ROOT = Path(__file__).resolve().parent.parent


def design_reply() -> dict:
    """What qwen3-4b chose on the laptop: the bus by what it carries."""
    doc = good()
    for cable in doc["cables"]:
        for w in cable["wires"]:
            if w["to_pin"] in ("SCL", "SDA"):
                w["from_pin"] = w["to_pin"]
    return doc


class TestMicrocontrollerPins(WeatherCase):
    """D135, and D144 after it: the DevKit v1 now has a pin list, so it is
    held to that; a board without one (the C3) is held to the pattern."""

    def setUp(self):
        super().setUp()
        self.bare = self.lib.get("waveshare_esp32s3_lcd_128")
        self.bare_parts = [self.bare, self.lib.get("bme280")]

    def bare_reply(self, pin="SCL"):
        return {"cables": [{"from": "waveshare_esp32s3_lcd_128", "to": "bme280", "gauge_awg": 22,
                            "length_mm": 80, "wires": [
                                {"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
                                {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
                                {"from_pin": pin, "to_pin": "SCL", "colour": "yellow"}]}]}

    def test_a_board_with_no_list_is_held_to_power_names_and_gpio_numbers(self):
        self.assertEqual(self.bare.pins, [])
        self.assertEqual(harness._pin_schema(self.bare),
                         {"type": "string", "pattern": harness.MCU_PIN})

    def test_a_board_with_a_list_is_held_to_its_list(self):
        esp = self.lib.get("esp32_devkit_v1")
        self.assertEqual(harness._pin_schema(esp), {"enum": [p.name for p in esp.pins]})
        self.assertNotIn("SCL", [p.name for p in esp.pins])

    def test_what_the_model_wrote_cannot_be_written_under_the_pattern(self):
        ok = re.compile(harness.MCU_PIN)
        for pin in ("SCL", "SDA", "MOSI", "TX", "I2C_SDA", "GPIO", "GPIO213"):
            self.assertIsNone(ok.match(pin), pin)
        for pin in ("3V3", "5V", "VIN", "GND", "GPIO21", "GPIO4"):
            self.assertIsNotNone(ok.match(pin), pin)

    def test_a_gpio_has_one_spelling(self):
        # D144: GPIO0 to one part and D0 to another were the same pin.
        ok = re.compile(harness.MCU_PIN)
        for pin in ("D0", "IO22", "GP15", "D5", "gpio4"):
            self.assertIsNone(ok.match(pin), pin)

    def test_everything_it_allows_the_firmware_step_can_read(self):
        ok = re.compile(harness.MCU_PIN)
        for pin in ("3V3", "5V", "VIN", "VBUS", "GND", "GPIO21", "GPIO4"):
            self.assertIsNotNone(ok.match(pin), pin)
            self.assertTrue(firmware._SUPPLY_PIN.match(pin) or firmware._GPIO.match(pin), pin)

    def test_the_real_reply_is_refused_when_built_naming_the_pin(self):
        with self.assertRaises(harness.HarnessError) as ctx:
            harness.build(design_reply(), self.parts)
        self.assertIn("esp32_devkit_v1 has no pin 'SCL'", str(ctx.exception))

    def test_and_on_a_board_with_no_list_it_is_refused_with_what_to_write(self):
        with self.assertRaises(harness.HarnessError) as ctx:
            harness.build(self.bare_reply("SCL"), self.bare_parts)
        why = str(ctx.exception)
        self.assertIn("'SCL' is not a pin of the microcontroller waveshare_esp32s3_lcd_128", why)
        self.assertIn("GPIO and its number", why)
        harness.build(self.bare_reply("GPIO5"), self.bare_parts)

    def test_and_it_is_exactly_what_the_firmware_step_failed_on(self):
        with self.assertRaises(firmware.FirmwareError) as ctx:
            firmware.plan(design_reply(), self.parts)
        self.assertIn("is not a GPIO number", str(ctx.exception))

    def test_the_good_reply_still_builds(self):
        harness.build(good(), self.parts)
        firmware.plan(good(), self.parts)

    def test_the_model_is_told_and_shown_no_example_to_copy(self):
        line = next(x for x in harness.part_facts(self.bare_parts).splitlines()
                    if x.startswith("- waveshare_esp32s3_lcd_128"))
        self.assertIn("every other pin is written GPIO and its number", line)
        self.assertNotIn("e.g.", line)
        self.assertIsNone(re.search(r"GPIO\d", line))        # pitfall 4b

    def test_a_part_that_is_not_a_microcontroller_keeps_the_looser_rule(self):
        other = copy.copy(self.parts[0])
        other.category, other.pins = "module", []
        self.assertEqual(harness.free_pin(other), harness.FREE_PIN)


class TestSentBackOnce(WeatherCase):
    def run_step(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_the_real_reply_is_sent_back_with_the_reason_and_the_second_is_used(self):
        r = SchemaRouter(design_reply(), good())
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 2)
        self.assertIn("esp32_devkit_v1 has no pin 'SCL'", r.asked[1]["user"])
        saved = yaml.safe_load(self.project.harness.read_text(encoding="utf-8"))
        self.assertIn("GPIO22", str(saved["connections"]))


# Resident memory of llama-server with each mode loaded, on the AH531 under
# Windows 11, with the context sizes the shipped config gives. Measured, MB.
MEASURED = {"design": 3111, "talk": 2070, "build": 2053, "tiny": 885}


class TestBudgetsAreWhatWasMeasured(unittest.TestCase):
    def shipped(self):
        return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["modes_windows"]

    def need(self, spec):
        return spec["ram_mb"] + spec["tools_mb"] + 300          # as modes.start adds up

    def test_no_budget_is_below_what_the_model_holds(self):
        for where, modes in (("config.yaml", self.shipped()),
                             ("DEFAULTS", DEFAULTS["modes_windows"])):
            for name, mb in MEASURED.items():
                self.assertGreaterEqual(modes[name]["ram_mb"], mb, f"{where} {name}")

    def test_the_shipped_file_and_the_built_in_defaults_agree(self):
        for name in MEASURED:
            self.assertEqual(self.shipped()[name], DEFAULTS["modes_windows"][name], name)

    def test_design_loads_in_what_this_machine_has_free(self):
        # At 4200 it was refused with 4116 MB available; forced, the whole
        # pipeline then ran with 891 MB to spare, having used about 3.3 GB.
        need = self.need(self.shipped()["design"])
        self.assertLessEqual(need, 4116)
        self.assertGreaterEqual(need, 4116 - 891 + 300)     # what it used, and a margin

    def test_the_launcher_picks_a_mode_only_when_nemo_will_load_it(self):
        ps = (ROOT / "NemoDoc.ps1")
        if not ps.exists():
            self.skipTest("NemoDoc.ps1 not present in this layout")
        text = ps.read_text(encoding="utf-8")
        for name in ("design", "talk"):
            m = re.search(r"\(\$free -gt (\d+)\) \{ \$Mode = \"%s\" \}" % name, text)
            self.assertIsNotNone(m, name)
            self.assertGreaterEqual(int(m.group(1)), self.need(self.shipped()[name]), name)

    def test_the_refusal_names_what_the_reserve_is_for(self):
        from nemo import modes
        from nemo.config import Config
        cfg = Config(copy.deepcopy(DEFAULTS))
        with mock.patch.object(modes, "mem_available_mb", return_value=1000), \
             mock.patch.object(modes, "mem_total_mb", return_value=8105):
            ok, why = modes.start(cfg, "talk")
        self.assertFalse(ok)
        self.assertIn("2100 for the model", why)
        self.assertIn("reserved for the tools the steps run", why)

    def test_the_window_shows_the_same_figures(self):
        from nemo.gui import controller as C
        for key, _, mb in C.MODES:
            if key in MEASURED:
                self.assertEqual(mb, self.shipped()[key]["ram_mb"], key)


if __name__ == "__main__":
    unittest.main()
