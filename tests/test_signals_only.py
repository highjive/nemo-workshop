"""D164, D165: the model is asked for the signal wires and nothing else, and
a step whose connections are missing does not ask in their place.

Real run (AH531, qwen3-4b, Design mode, 2026-10-07): a recorder with a
microphone, an amplifier, a speaker and a distance sensor, five parts.

  electrical   the model had not finished after 1800 s; nothing written
  wiring       asked the same question; 1800 s more, the same end
  firmware     with no connections, asked for the whole file: 66 minutes,
               three builds that failed, I2C registers written to an
               amplifier that has no bus
  in all       163 minutes, and no design

The four-part designs before it had taken 22 to 26 minutes at that step.
Of the eleven wires in the last of them, six were supply and ground wires
that code throws away and wires itself, and every cable carried a gauge, a
length and a colour per wire that code also decides.
"""
from __future__ import annotations

import json, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, harness
from nemo.checks.deterministic import PASS, Result
from nemo.parts import PartsLibrary
from nemo.pipeline import StageResult
from nemo.project import Brief
from nemo.prompts import load_prompt
from nemo.results import save_result
from test_harness import SchemaRouter
from test_pipeline import PipelineCase

LIB = PartsLibrary.load()
BOARD = "esp32_devkit_v1"
LID = (BOARD, "vl53l0x", "sg90_servo", "relay_5v_1ch")
MEMO = (BOARD, "sph0645lm4h", "max98357a", "speaker_8ohm_20mm", "vl53l0x")
BATTERY = (BOARD, "bme280", "lipo_2000", "tp4056_protected", "boost_5v_mt3608")


def P(refs):
    return [LIB.get(r) for r in refs]


def pairs(schema):
    return schema["properties"]["cables"]["items"]["anyOf"]


def short_reply() -> dict:
    """The lid's signal wires, as the model is now asked for them."""
    return {"cables": [
        {"from": BOARD, "to": "sg90_servo", "wires": [{"from_pin": "GPIO4", "to_pin": "PWM"}]},
        {"from": BOARD, "to": "vl53l0x", "wires": [{"from_pin": "GPIO18", "to_pin": "SCL"},
                                                    {"from_pin": "GPIO19", "to_pin": "SDA"},
                                                    {"from_pin": "GPIO21", "to_pin": "XSHUT"}]},
        {"from": BOARD, "to": "relay_5v_1ch", "wires": [{"from_pin": "GPIO25", "to_pin": "IN"}]}]}


def long_reply() -> dict:
    """The same design as it was asked for before, and answered (real run)."""
    def w(a, b, c):
        return {"from_pin": a, "to_pin": b, "colour": c}
    return {"cables": [
        {"from": BOARD, "to": "sg90_servo", "gauge_awg": 22, "length_mm": 100,
         "wires": [w("VIN", "VCC", "red"), w("GND", "GND", "black"), w("GPIO4", "PWM", "yellow")]},
        {"from": BOARD, "to": "vl53l0x", "gauge_awg": 22, "length_mm": 150,
         "wires": [w("VIN", "VIN", "red"), w("GND", "GND", "black"), w("GPIO18", "SCL", "blue"),
                   w("GPIO19", "SDA", "blue"), w("GPIO21", "XSHUT", "blue")]},
        {"from": BOARD, "to": "relay_5v_1ch", "gauge_awg": 22, "length_mm": 100,
         "wires": [w("VIN", "VCC", "red"), w("GND", "GND", "black"), w("GPIO25", "IN", "blue")]}]}


class TestWhenCodeWiresThePower(unittest.TestCase):
    def test_one_board_and_no_battery(self):
        self.assertTrue(harness.power_by_code(P(LID)))
        self.assertTrue(harness.power_by_code(P(MEMO)))

    def test_a_battery_chain_it_understands(self):
        self.assertTrue(harness.power_by_code(P(BATTERY)))

    def test_not_a_supply_it_does_not_understand_nor_two_boards_nor_none(self):
        self.assertFalse(harness.power_by_code(P((BOARD, "bme280", "lipo_2000"))))
        self.assertFalse(harness.power_by_code(P((BOARD, "esp32c3_devkit", "bme280"))))
        self.assertFalse(harness.power_by_code(P(("bme280", "ssd1306_oled_096"))))


class TestTheShortQuestion(unittest.TestCase):
    def setUp(self):
        self.schema = harness.harness_schema(P(LID), True)

    def test_a_cable_is_its_two_parts_and_its_wires_and_a_wire_its_two_pins(self):
        for pair in pairs(self.schema):
            self.assertEqual(pair["required"], ["from", "to", "wires"])
            self.assertEqual(sorted(pair["properties"]), ["from", "to", "wires"])
            wire = pair["properties"]["wires"]["items"]
            self.assertEqual(wire["required"], ["from_pin", "to_pin"])
            self.assertEqual(sorted(wire["properties"]), ["from_pin", "to_pin"])
            self.assertIs(pair["additionalProperties"], False)
            self.assertIs(wire["additionalProperties"], False)

    def test_no_supply_or_ground_pin_can_be_named_on_any_part(self):
        offered = {}
        for pair in pairs(self.schema):
            offered[pair["properties"]["from"]["const"]] = \
                pair["properties"]["wires"]["items"]["properties"]["from_pin"]["enum"]
        self.assertEqual(offered["sg90_servo"], ["PWM"])
        self.assertEqual(offered["vl53l0x"], ["SCL", "SDA"])        # less the two it works without
        self.assertEqual(offered["relay_5v_1ch"], ["IN"])
        self.assertEqual(offered[BOARD], ["GPIO4", "GPIO18", "GPIO19", "GPIO21", "GPIO22",
                                          "GPIO23", "GPIO25", "GPIO26", "GPIO27", "GPIO32",
                                          "GPIO33"])

    def test_a_board_with_no_pin_list_takes_a_gpio_number_and_no_power_name(self):
        import re
        board = LIB.get("waveshare_esp32s3_lcd_128")
        self.assertEqual(harness._pin_schema(board, True),
                         {"type": "string", "pattern": harness.SIGNAL_MCU_PIN})
        self.assertTrue(re.match(harness.SIGNAL_MCU_PIN, "GPIO21"))
        for name in ("3V3", "VIN", "GND", "5V"):
            self.assertFalse(re.match(harness.SIGNAL_MCU_PIN, name), name)

    def test_the_parts_are_listed_with_their_signal_pins_only(self):
        facts = harness.part_facts(P(LID), True)
        self.assertIn("- sg90_servo (SG90 9 g micro servo): PWM", facts)
        self.assertIn("- relay_5v_1ch (5 V single-channel relay module): IN", facts)
        for word in ("VCC", "VIN", "GND", "3V3", "COM"):
            self.assertNotIn(word, facts)

    def test_the_long_question_is_as_it_was_for_a_supply_code_does_not_wire(self):
        schema = harness.harness_schema(P(LID))
        self.assertEqual(pairs(schema)[0]["required"],
                         ["from", "to", "gauge_awg", "length_mm", "wires"])
        self.assertIn("VCC", harness.part_facts(P(LID)))

    def test_its_prompt_asks_for_no_power_colour_gauge_or_length_and_shows_no_example(self):
        text = load_prompt("wiring_signals_json")
        self.assertIn("Power and ground are already wired", text)
        for word in ("colour", "gauge", "length", " red ", "black", "GPIO", "e.g."):
            self.assertNotIn(word, text)

    def test_the_answer_it_asks_for_is_under_half_the_length(self):
        short = len(json.dumps(short_reply()))
        long = len(json.dumps(long_reply()))
        self.assertLess(short * 2, long, (short, long))
        self.assertEqual((sum(len(c["wires"]) for c in short_reply()["cables"]),
                          sum(len(c["wires"]) for c in long_reply()["cables"])), (5, 11))


class TestWhatCodeMakesOfAShortAnswer(unittest.TestCase):
    def decided(self):
        doc, notes = harness.wire_power(short_reply(), P(LID), asked=False)
        doc, hues = harness.recolour_signals(doc, P(LID))
        return doc, notes + hues

    def wires(self, doc):
        return {(c["to"], w["to_pin"]): (w["from_pin"], w.get("colour"))
                for c in doc["cables"] for w in c["wires"]}

    def test_every_part_is_fed_from_a_pin_that_suits_it(self):
        got = self.wires(self.decided()[0])
        self.assertEqual(got[("sg90_servo", "VCC")], ("VIN", "red"))
        self.assertEqual(got[("relay_5v_1ch", "VCC")], ("VIN", "red"))
        self.assertEqual(got[("vl53l0x", "VIN")], ("3V3", "red"))     # the lowest that suits
        for part in ("sg90_servo", "relay_5v_1ch", "vl53l0x"):
            self.assertEqual(got[(part, "GND")], ("GND", "black"))

    def test_the_signal_wires_are_the_models_and_each_has_a_colour_that_is_not_a_supplys(self):
        got = self.wires(self.decided()[0])
        self.assertEqual(got[("sg90_servo", "PWM")][0], "GPIO4")
        self.assertEqual(got[("vl53l0x", "XSHUT")][0], "GPIO21")
        for (part, pin), (_, colour) in got.items():
            if pin not in ("VCC", "VIN", "GND"):
                self.assertIn(colour, set(harness.COLOURS) - {"red", "black"}, (part, pin))
        in_one = [got[("vl53l0x", p)][1] for p in ("SCL", "SDA", "XSHUT")]
        self.assertEqual(len(set(in_one)), 3)

    def test_it_is_said_once_not_once_a_pin_and_nothing_is_called_missing(self):
        notes = self.decided()[1]
        self.assertEqual(notes, [
            "Power and ground wired by Nemo from the parts library, each part to "
            "esp32_devkit_v1: vl53l0x.VIN from 3V3; sg90_servo.VCC from VIN; "
            "relay_5v_1ch.VCC from VIN; every ground to GND."])

    def test_it_builds_with_no_remark_about_gauge_or_length(self):
        text, notes = harness.build(self.decided()[0], P(LID))
        self.assertEqual(notes, [])
        self.assertIn("22 AWG", text)

    def test_an_answer_the_long_way_is_still_understood(self):
        doc, notes = harness.wire_power(long_reply(), P(LID), asked=False)
        got = self.wires(doc)
        self.assertEqual(got[("vl53l0x", "VIN")][0], "VIN")      # its own choice, and it suits
        self.assertEqual(notes, [])


class LidCase(PipelineCase):
    REFS, NAME = LID, "hand-lid"

    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name=self.NAME, function="A lid that a servo opens when a hand comes near.",
            power="USB 5 V 2 A", supply_ma=2000, rails=[5.0, 3.3], envelope_mm=[150, 100, 50],
            parts=list(self.REFS), mcu="esp32", done_when="The lid opens."))
        self.parts = P(self.REFS)

    def wiring(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()


class TestTheStepAsksTheShortWay(LidCase):
    def test_and_the_short_answer_passes_every_check(self):
        r = SchemaRouter(short_reply())
        sr = self.wiring(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        asked = r.asked[0]
        self.assertEqual(asked["schema"], harness.pin_choice_schema(self.parts))   # D171
        self.assertIn("Power and ground are already wired", asked["system"])
        self.assertNotIn("VCC", asked["user"])
        self.assertIn("Power and ground wired by Nemo from the parts library", sr.render())


class TestABatteryItDoesNotUnderstandIsAskedTheLongWay(LidCase):
    REFS, NAME = (BOARD, "bme280", "lipo_2000"), "odd-supply"

    def test_the_model_is_still_asked_for_power_there(self):
        r = SchemaRouter({"cables": [{"from": BOARD, "to": "bme280", "gauge_awg": 22,
                                      "length_mm": 80, "wires": [
            {"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
            {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
            {"from_pin": "GPIO21", "to_pin": "SDA", "colour": "blue"},
            {"from_pin": "GPIO22", "to_pin": "SCL", "colour": "yellow"}]}]})
        self.wiring(r)
        self.assertIn("gets a wire to a supply pin", r.asked[0]["system"])
        self.assertIn("VCC", r.asked[0]["user"])


# ----------------------------------------------------------------- D165
class TestAfterTheElectricalStepFailed(LidCase):
    def setUp(self):
        super().setUp()
        save_result(self.project.root, StageResult("electrical", False, notes=[
            "The model had not finished after 1800 s, which is the limit."]))

    def test_the_wiring_step_does_not_ask_the_same_question_again(self):
        r = SchemaRouter(short_reply())
        sr = self.wiring(r)
        self.assertFalse(sr.ok)
        self.assertEqual(r.asked, [])
        self.assertEqual(sr.go_back_to, "electrical")
        self.assertIn("The model was not asked again", sr.render())

    def test_the_firmware_step_does_not_ask_for_the_whole_file_instead(self):
        r = SchemaRouter("```cpp\nvoid setup(){}\nvoid loop(){}\n```")
        sr = self.pipe(r).stage_firmware()
        self.assertFalse(sr.ok)
        self.assertEqual(r.asked, [])
        self.assertEqual(sr.go_back_to, "electrical")
        self.assertIn("The model was not asked to write it without them", sr.render())
        self.assertFalse((self.project.firmware / "src" / "main.cpp").exists())


class TestWhereTheElectricalStepHasNotRun(LidCase):
    def test_the_wiring_step_still_decides_for_itself(self):
        r = SchemaRouter(short_reply())
        self.assertTrue(self.wiring(r).ok)
        self.assertEqual(len(r.asked), 1)


class TestWhereItPassed(LidCase):
    def test_its_connections_are_used_and_nothing_is_asked(self):
        doc, _ = harness.wire_power(short_reply(), self.parts, asked=False)
        self.project.connections.parent.mkdir(parents=True, exist_ok=True)
        self.project.connections.write_text(json.dumps(doc), encoding="utf-8")
        save_result(self.project.root, StageResult("electrical", True))
        r = SchemaRouter(short_reply())
        self.assertTrue(self.wiring(r).ok)
        self.assertEqual(r.asked, [])


if __name__ == "__main__":
    unittest.main()
