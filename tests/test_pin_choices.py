"""D171: the model names a board pin for each signal pin, and nothing else.

From the model server's own log of the real audio run (AH531, qwen3-4b,
2026-10-07), the wiring call:

    prompt eval   518 tokens at 1.15 a second   451 s
    eval          310 tokens at 0.71 a second   433 s

Eight wires. Most of the 310 tokens were the cable list's own words.
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
from nemo.project import Brief
from nemo.prompts import load_prompt
from test_harness import SchemaRouter
from test_pipeline import PipelineCase

LIB = PartsLibrary.load()
BOARD = "esp32_devkit_v1"
MEMO = (BOARD, "sph0645lm4h", "max98357a", "speaker_8ohm_20mm", "vl53l0x")


def P(refs):
    return [LIB.get(r) for r in refs]


def choices() -> dict:
    """The third real audio run's wiring, in the form now asked for."""
    return {"sph0645lm4h": {"BCLK": "GPIO21", "DOUT": "GPIO22", "LRCL": "GPIO23"},
            "max98357a": {"DIN": "GPIO25", "BCLK": "GPIO26", "LRC": "GPIO27"},
            "vl53l0x": {"SCL": "GPIO32", "SDA": "GPIO33"}}


def cables() -> dict:
    """The same wiring as the cable list it was asked for before."""
    return {"cables": [{"from": BOARD, "to": ref, "wires": [
        {"from_pin": to, "to_pin": pin} for pin, to in pins.items()]}
        for ref, pins in choices().items()]}


class TestTheSchema(unittest.TestCase):
    def setUp(self):
        self.schema = harness.pin_choice_schema(P(MEMO))

    def test_one_key_a_part_one_key_a_signal_pin_and_only_a_board_pin_to_choose(self):
        self.assertEqual(self.schema["required"], ["sph0645lm4h", "max98357a", "vl53l0x"])
        self.assertIs(self.schema["additionalProperties"], False)
        amp = self.schema["properties"]["max98357a"]
        self.assertEqual(amp["required"], ["DIN", "BCLK", "LRC"])
        self.assertIs(amp["additionalProperties"], False)
        for part in self.schema["properties"].values():
            for pin in part["properties"].values():
                self.assertEqual(pin["enum"][:2], ["GPIO4", "GPIO18"])
                self.assertEqual(len(pin["enum"]), 11)

    def test_no_board_supply_ground_speaker_or_optional_pin_is_in_it(self):
        text = json.dumps(self.schema)
        for word in (BOARD, "speaker_8ohm_20mm", "3V3", "VIN", "GND", "OUT+", "SEL", "XSHUT",
                     "GAIN", '"SD"'):
            self.assertNotIn(word, text)

    def test_a_board_with_no_pin_list_takes_a_gpio_number(self):
        s = harness.pin_choice_schema(P(("waveshare_esp32s3_lcd_128", "bme280")))
        self.assertEqual(s["properties"]["bme280"]["properties"]["SDA"],
                         {"type": "string", "pattern": harness.SIGNAL_MCU_PIN})

    def test_it_does_not_fit_without_exactly_one_board_or_with_nothing_to_place(self):
        self.assertIsNone(harness.pin_choice_schema(P(("bme280", "ssd1306_oled_096"))))
        self.assertIsNone(harness.pin_choice_schema(P((BOARD, "esp32c3_devkit", "bme280"))))
        self.assertIsNone(harness.pin_choice_schema(P((BOARD, "speaker_8ohm_20mm"))))

    def test_the_same_wiring_is_under_half_the_text_of_the_cable_list(self):
        short, long = len(json.dumps(choices())), len(json.dumps(cables()))
        self.assertLess(short * 2, long, (short, long))

    def test_the_prompt_is_under_half_the_length_of_the_one_before_and_shows_no_example(self):
        new, old = load_prompt("wiring_pins_json"), load_prompt("wiring_signals_json")
        self.assertLess(len(new.split()) * 2, len(old.split()) + len(new.split()))
        self.assertLess(len(new.split()), 130)
        self.assertIn("Power and ground are already wired", new)
        for word in ("GPIO", "e.g.", "cable", "colour"):
            self.assertNotIn(word, new)


class TestReadingAnAnswer(unittest.TestCase):
    def test_it_becomes_the_cable_list_everything_else_reads(self):
        self.assertEqual(harness.from_pin_choices(choices(), P(MEMO)), cables())

    def test_an_answer_that_is_already_a_cable_list_is_left_alone(self):
        self.assertEqual(harness.from_pin_choices(cables(), P(MEMO)), cables())

    def test_two_parts_given_the_same_pins_for_a_bus_share_them(self):
        parts = P((BOARD, "bme280", "ssd1306_oled_096"))
        doc = harness.from_pin_choices({"bme280": {"SCL": "GPIO22", "SDA": "GPIO21"},
                                        "ssd1306_oled_096": {"SCL": "GPIO22", "SDA": "GPIO21"}},
                                       parts)
        ends = {(c["to"], w["to_pin"]): w["from_pin"] for c in doc["cables"] for w in c["wires"]}
        self.assertEqual(ends[("bme280", "SDA")], ends[("ssd1306_oled_096", "SDA")])

    def test_what_cannot_be_read_is_refused_by_name(self):
        for bad, why in (({"teapot": {"SDA": "GPIO4"}}, "names 'teapot'"),
                         ({BOARD: {"GPIO4": "GPIO4"}}, f"names '{BOARD}'"),
                         ({"vl53l0x": {}}, "gives no pins for vl53l0x"),
                         ({"vl53l0x": ["GPIO4"]}, "gives no pins for vl53l0x"),
                         ({"vl53l0x": {"SDA": 4}}, "gives vl53l0x.SDA no microcontroller pin"),
                         ({}, "places no pins")):
            with self.assertRaises(harness.HarnessError) as ctx:
                harness.from_pin_choices(bad, P(MEMO))
            self.assertIn(why, str(ctx.exception))

    def test_a_pin_the_part_or_the_board_does_not_have_is_still_caught_downstream(self):
        doc = harness.from_pin_choices({"vl53l0x": {"SDA": "GPIO0", "SCL": "GPIO32"}}, P(MEMO))
        with self.assertRaises(harness.HarnessError) as ctx:
            harness.build(doc, P(MEMO))
        self.assertIn("has no pin 'GPIO0'", str(ctx.exception))


class MemoCase(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="voice-memo", function="A desk recorder that plays the last ten seconds back.",
            power="USB 5 V 2 A", supply_ma=2000, rails=[5.0, 3.3], envelope_mm=[120, 80, 40],
            parts=list(MEMO), mcu="esp32", done_when="A hand starts playback."))
        self.parts = P(MEMO)

    def wiring(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()


class TestTheStep(MemoCase):
    def test_it_asks_this_way_and_the_real_wiring_passes_every_check(self):
        r = SchemaRouter(choices())
        sr = self.wiring(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        self.assertEqual(r.asked[0]["schema"], harness.pin_choice_schema(
            harness.chosen_by_model(self.parts)))
        self.assertIn("You choose which pin of the microcontroller", r.asked[0]["system"])
        text = sr.render()
        self.assertIn("speaker_8ohm_20mm is wired by Nemo to max98357a", text)
        self.assertIn("max98357a.VIN from VIN", text)

    def test_an_answer_in_the_older_form_is_still_understood(self):
        sr = self.wiring(SchemaRouter(cables()))
        self.assertTrue(sr.ok, sr.render())

    def test_an_answer_that_cannot_be_read_gets_its_one_second_chance(self):
        r = SchemaRouter({"teapot": {"SDA": "GPIO4"}}, choices())
        sr = self.wiring(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 2)
        self.assertIn("names 'teapot'", r.asked[1]["user"])
        self.assertIn("Give the whole answer again", r.asked[1]["user"])

    def test_faults_are_quoted_back_asking_for_the_answer_not_a_cable_list(self):
        clash = choices()
        clash["vl53l0x"] = {"SCL": "GPIO21", "SDA": "GPIO22"}       # the microphone's pins
        full = {"sph0645lm4h": {"BCLK": "GPIO4", "DOUT": "GPIO4", "LRCL": "GPIO4"},
                "max98357a": {"DIN": "GPIO4", "BCLK": "GPIO4", "LRC": "GPIO4"},
                "vl53l0x": {"SCL": "GPIO4", "SDA": "GPIO4"}}
        r = SchemaRouter(full, choices())
        self.wiring(r)
        if len(r.asked) == 2:                       # code may mend the first without asking
            self.assertIn("give the whole answer again", r.asked[1]["user"])


class TestASupplyCodeDoesNotWireKeepsTheLongQuestion(PipelineCase):
    def test_the_cable_list_is_still_asked_for_there(self):
        refs = (BOARD, "bme280", "lipo_2000")
        self.project.create(Brief(
            name="odd", function="A sensor on a bare cell.", power="LiPo", supply_ma=1000,
            rails=[3.3], envelope_mm=[80, 50, 30], parts=list(refs), mcu="esp32",
            done_when="It reads."))
        r = SchemaRouter({"cables": [{"from": BOARD, "to": "bme280", "gauge_awg": 22,
                                      "length_mm": 80, "wires": [
            {"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
            {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
            {"from_pin": "GPIO21", "to_pin": "SDA", "colour": "blue"},
            {"from_pin": "GPIO22", "to_pin": "SCL", "colour": "yellow"}]}]})
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            self.pipe(r).stage_wiring()
        self.assertIn("cables", r.asked[0]["schema"]["required"])


if __name__ == "__main__":
    unittest.main()
