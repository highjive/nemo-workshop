"""D163: two more boards have a pin list, and one is left without on purpose.

Only the ESP32 DevKit had one (D144). On the Pico and the ESP32-C3 the
model could write any GPIO number at all, the pins-exist check had nothing
to check against, and a strapping, flash or USB pin passed like any other.

Sources, read 2026-10-07: Espressif's GPIO summary for the ESP32-C3
(ESP-IDF Programming Guide v6.1); Raspberry Pi's Pico-series documentation
and a third party's drawing of the Pico's header. The entries in the
library say what each gave and what was not verified.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import harness
from nemo.parts import PartsLibrary

LIB = PartsLibrary.load()


def gpios(ref):
    return [int(p.name[4:]) for p in LIB.get(ref).pins if p.name.startswith("GPIO")]


def cable(board, part, *wires):
    return {"cables": [{"from": board, "to": part, "gauge_awg": 22, "length_mm": 80,
                        "wires": [{"from_pin": a, "to_pin": b, "colour": "white"}
                                  for a, b in wires]}]}


class TestTheC3(unittest.TestCase):
    def test_its_pins_are_the_eight_left_after_every_caveat(self):
        self.assertEqual(gpios("esp32c3_devkit"), [0, 1, 3, 4, 5, 6, 7, 10])

    def test_none_is_a_pin_the_table_warns_about_or_one_held_back(self):
        strapping, flash, usb, held_back = {2, 8, 9}, set(range(12, 18)), {18, 19}, {20, 21}
        self.assertFalse(set(gpios("esp32c3_devkit")) & (strapping | flash | usb | held_back))

    def test_between_them_they_account_for_every_pin_of_the_chip(self):
        self.assertEqual(sorted(set(gpios("esp32c3_devkit")) | {2, 8, 9} | set(range(12, 18))
                                | {18, 19, 20, 21} | {11}), list(range(22)))
        # GPIO11 has no caveat in the table and is held back like 20 and 21:
        # a caution of this library's, which no source read for it states.

    def test_its_supply_pins(self):
        self.assertEqual(harness.board_supplies(LIB.get("esp32c3_devkit")),
                         [("3V3", 3.3), ("5V", 5.0)])


class TestThePico(unittest.TestCase):
    def test_its_pins_are_the_headers_less_two(self):
        self.assertEqual(gpios("rp2040_pico"), list(range(2, 23)) + [26, 27, 28])

    def test_the_four_the_board_uses_itself_are_not_offered(self):
        self.assertFalse(set(gpios("rp2040_pico")) & {23, 24, 25, 29})

    def test_its_supply_pins_and_no_vsys(self):
        self.assertEqual(harness.board_supplies(LIB.get("rp2040_pico")),
                         [("3V3", 3.3), ("VBUS", 5.0)])
        self.assertIsNone(LIB.get("rp2040_pico").pin("VSYS"))

    def test_they_are_spelt_the_way_the_firmware_step_reads(self):
        import re
        for ref in ("rp2040_pico", "esp32c3_devkit"):
            for p in LIB.get(ref).pins:
                self.assertRegex(p.name, harness.MCU_PIN, (ref, p.name))
                if p.name.startswith("GPIO"):
                    self.assertEqual((p.function, p.voltage), ("io", 3.3), (ref, p.name))
        self.assertTrue(re.match(harness.MCU_PIN, "VBUS"))


class TestWhatTheListsNowStop(unittest.TestCase):
    def test_a_pin_the_board_does_not_offer_is_refused_by_name(self):
        for board, pin in (("esp32c3_devkit", "GPIO9"), ("esp32c3_devkit", "GPIO18"),
                           ("rp2040_pico", "GPIO25"), ("rp2040_pico", "GPIO0")):
            parts = [LIB.get(board), LIB.get("ds18b20")]
            with self.assertRaises(harness.HarnessError) as cm:
                harness.build(cable(board, "ds18b20", (pin, "DQ")), parts)
            self.assertIn(f"{board} has no pin '{pin}'", str(cm.exception))

    def test_and_cannot_be_written_under_the_schema(self):
        for board, bad in (("esp32c3_devkit", "GPIO9"), ("rp2040_pico", "GPIO25")):
            schema = harness.harness_schema([LIB.get(board), LIB.get("ds18b20")])
            pair = next(p for p in schema["properties"]["cables"]["items"]["anyOf"]
                        if p["properties"]["from"]["const"] == board)
            names = pair["properties"]["wires"]["items"]["properties"]["from_pin"]["enum"]
            self.assertNotIn(bad, names)
            self.assertIn("GPIO4", names)

    def test_power_is_wired_to_the_pins_each_board_has(self):
        for board, five in (("esp32c3_devkit", "5V"), ("rp2040_pico", "VBUS")):
            parts = [LIB.get(board), LIB.get("bme280"), LIB.get("sg90_servo")]
            doc = {"cables": [
                {"from": board, "to": "bme280", "gauge_awg": 22, "length_mm": 80,
                 "wires": [{"from_pin": "GPIO4", "to_pin": "SDA", "colour": "white"},
                           {"from_pin": "GPIO5", "to_pin": "SCL", "colour": "white"}]},
                {"from": board, "to": "sg90_servo", "gauge_awg": 22, "length_mm": 80,
                 "wires": [{"from_pin": "GPIO6", "to_pin": "PWM", "colour": "white"}]}]}
            out, _ = harness.wire_power(doc, parts)
            got = {(c["to"], w["to_pin"]): w["from_pin"] for c in out["cables"]
                   for w in c["wires"]}
            self.assertEqual(got[("bme280", "VCC")], "3V3", board)
            self.assertEqual(got[("sg90_servo", "VCC")], five, board)
            self.assertEqual(got[("sg90_servo", "GND")], "GND", board)


class TestABatteryIsNotWiredToAUsbPin(unittest.TestCase):
    CHAIN = ("lipo_2000", "tp4056_protected", "boost_5v_mt3608")

    def test_on_the_pico_the_chain_is_left_unwired(self):
        parts = [LIB.get(r) for r in ("rp2040_pico", "bme280") + self.CHAIN]
        self.assertIsNone(harness.supply_chain(parts))
        out, _ = harness.wire_power(cable("rp2040_pico", "bme280", ("GPIO4", "SDA")), parts)
        ends = {(c["from"], w["from_pin"], c["to"], w["to_pin"]) for c in out["cables"]
                for w in c["wires"]}
        self.assertFalse([e for e in ends if "VBUS" in e and "boost_5v_mt3608" in e])

    def test_on_a_board_with_a_supply_input_it_is_wired_as_before(self):
        for board in ("esp32_devkit_v1", "esp32c3_devkit"):
            parts = [LIB.get(r) for r in (board, "bme280") + self.CHAIN]
            self.assertEqual([p.ref for p in harness.supply_chain(parts)], list(self.CHAIN))


class TestTheBoardLeftWithoutOne(unittest.TestCase):
    def test_it_has_none_and_the_file_says_why(self):
        self.assertEqual(LIB.get("waveshare_esp32s3_lcd_128").pins, [])
        text = (Path(harness.__file__).parent / "data" / "parts" / "pendant.yaml").read_text(
            encoding="utf-8")
        self.assertIn("No pin list, on purpose", text)
        self.assertIn("only in a picture", text)

    def test_four_of_the_five_boards_now_have_one(self):
        self.assertEqual(sorted(p.ref for p in LIB.parts.values()
                                if p.category == "mcu" and p.pins),
                         ["esp32_devkit_v1", "esp32c3_devkit", "esp32s3_devkitc_1", "rp2040_pico"])


if __name__ == "__main__":
    unittest.main()
