"""D147: which way a pin drives, and signal voltages checked on the wires.

Third real run of the tilt-lamp brief (AH531, qwen3-1.7b, 2026-10-06), the
first design of it to pass every check:

  esp32 -> ring:    VIN-5V, GND-GND, GPIO4-DIN, GPIO18-DOUT
  mpu6050 -> esp32: VCC-3V3, GND-GND, SCL-GPIO27, SDA-GPIO32, INT-GPIO26, AD0-GPIO25

The ring runs at 5 V. Its DOUT is a 5 V output and GPIO18 is a 3.3 V pin.
Nothing compared them: the only voltage check looked at same-named bus
pins of parts sharing an interface, not at the wires.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, harness
from nemo.checks.deterministic import PASS, Result
from nemo.parts import PartsLibrary, _build_part
from nemo.pipeline import Pipeline, StageResult
from nemo.project import Brief
from test_gates_real import WeatherCase
from test_harness import SchemaRouter, good
from test_pipeline import PipelineCase, StubRouter

REFS = ("esp32_devkit_v1", "mpu6050", "ws2812b_ring8")


def w(a, b):
    return {"from_pin": a, "to_pin": b, "colour": "white"}


def real_reply() -> dict:
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 22, "length_mm": 80,
         "wires": [w("VIN", "5V"), w("GND", "GND"), w("GPIO4", "DIN"), w("GPIO18", "DOUT")]},
        {"from": "mpu6050", "to": "esp32_devkit_v1", "gauge_awg": 22, "length_mm": 80,
         "wires": [w("VCC", "3V3"), w("GND", "GND"), w("SCL", "GPIO27"), w("SDA", "GPIO32"),
                   w("INT", "GPIO26"), w("AD0", "GPIO25")]}]}


class TestTheLibrarySaysWhichWay(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()

    def test_only_where_the_pins_name_says_so(self):
        # Signal pins only: a supply pin's direction (D150) is which side of a
        # power part it is on, and comes from the part's own source.
        marked = {(p.ref, x.name): x.direction for p in self.lib.parts.values()
                  for x in p.pins if x.direction and x.function in ("io", "bus")}
        for (ref, name), way in marked.items():
            if ref == "sn74ahct125":
                continue        # its directions are the I/O column of its datasheet (D148)
            stem = name.upper()
            self.assertTrue(
                (way == "in" and (stem in ("DIN", "RX", "IN", "MOSI") or stem.endswith(("IN1", "IN2"))))
                or (way == "out" and stem in ("DOUT", "TX", "MISO")), (ref, name, way))
        self.assertEqual(marked[("ws2812b_ring8", "DIN")], "in")
        self.assertEqual(marked[("ws2812b_ring8", "DOUT")], "out")
        self.assertEqual(marked[("dfplayer_mini", "TX")], "out")
        self.assertEqual(marked[("rc522", "MISO")], "out")

    def test_pins_whose_names_do_not_say_are_left_unmarked(self):
        for ref, name in (("mpu6050", "INT"), ("mpu6050", "AD0"), ("bme280", "SDA"),
                          ("dfplayer_mini", "BUSY"), ("rc522", "SCK")):
            self.assertEqual(self.lib.get(ref).pin(name).direction, "", (ref, name))

    def test_a_mistyped_direction_is_refused_when_the_library_loads(self):
        with self.assertRaises(ValueError) as ctx:
            _build_part("x", {"name": "X", "category": "sensor",
                              "pins": [{"name": "Q", "function": "io", "direction": "both"}]})
        self.assertIn("direction must be in or out", str(ctx.exception))

    def test_what_a_signal_pin_works_at(self):
        ring, esp = self.lib.get("ws2812b_ring8"), self.lib.get("esp32_devkit_v1")
        self.assertEqual(harness.signal_level(ring, "DOUT"), (5.0, "out"))
        self.assertEqual(harness.signal_level(ring, "DIN"), (5.0, "in"))
        self.assertEqual(harness.signal_level(esp, "GPIO18"), (3.3, ""))
        self.assertEqual(harness.signal_level(self.lib.get("relay_5v_1ch"), "IN"), (3.3, "in"))
        self.assertIsNone(harness.signal_level(ring, "5V"))            # a supply pin
        self.assertIsNone(harness.signal_level(esp, "GND"))
        self.assertEqual(harness.signal_level(self.lib.get("esp32c3_devkit"), "GPIO5"),
                         (3.3, ""))                                    # a board with no list
        self.assertIsNone(harness.signal_level(self.lib.get("esp32c3_devkit"), "3V3"))


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


class TestTheCheck(LampCase):
    def test_the_design_that_passed_everything_fails_on_the_output_wire(self):
        r = Pipeline.check_harness_levels(self.path(real_reply()), self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("ws2812b_ring8.DOUT is a 5 V output wired to esp32_devkit_v1.GPIO18, "
                      "a 3.3 V pin: more than that pin is made for", r.render())
        self.assertEqual(r.detail, "1 output(s) wired to a pin of lower voltage")

    def test_and_passed_every_other_check_there_was(self):
        p = self.path(real_reply())
        for check in (Pipeline.check_harness_pins, Pipeline.check_harness_covers,
                      Pipeline.check_harness_electrical, Pipeline.check_harness_signals,
                      Pipeline.check_harness_supply):
            self.assertEqual(check(p, self.parts).status, PASS, check.__name__)

    def test_without_that_wire_it_passes_and_lists_the_input_for_a_person(self):
        doc = real_reply()
        doc["cables"][0]["wires"].pop()
        r = Pipeline.check_harness_levels(self.path(doc), self.parts)
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn("1 to confirm", r.detail)
        self.assertIn("esp32_devkit_v1.GPIO4 (3.3 V) drives ws2812b_ring8.DIN, a 5 V input: "
                      "it may not reach the level that input needs", r.render())

    def test_parts_at_one_voltage_pass_with_nothing_to_confirm(self):
        doc = {"cables": [real_reply()["cables"][1]]}
        r = Pipeline.check_harness_levels(self.path(doc), self.parts)
        self.assertEqual(r.status, PASS)
        self.assertEqual(r.detail, "4 signal wire(s) compared, voltages match")
        self.assertEqual(r.items, [])

    def test_a_pin_the_library_gives_a_voltage_of_its_own_is_judged_by_that(self):
        relay = self.lib.get("relay_5v_1ch")            # a 5 V part whose IN takes 3.3 V
        parts = [self.parts[0], relay]
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "relay_5v_1ch", "gauge_awg": 22,
                           "length_mm": 80, "wires": [w("VIN", "VCC"), w("GND", "GND"),
                                                      w("GPIO4", "IN")]}]}
        text, _ = harness.build(doc, parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        r = Pipeline.check_harness_levels(self.project.harness, parts)
        self.assertEqual((r.status, r.items), (PASS, []))

    def test_two_voltages_and_no_known_direction_is_listed_not_failed(self):
        servo = self.lib.get("sg90_servo")              # 5 V logic, PWM pin unmarked
        parts = [self.parts[0], servo]
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "sg90_servo", "gauge_awg": 22,
                           "length_mm": 80, "wires": [w("VIN", "VCC"), w("GND", "GND"),
                                                      w("GPIO4", "PWM")]}]}
        text, _ = harness.build(doc, parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        r = Pipeline.check_harness_levels(self.project.harness, parts)
        self.assertEqual(r.status, PASS)
        self.assertIn("the library does not say which drives", r.render())

    def test_nothing_to_read_or_nothing_comparable_is_a_skip(self):
        self.assertEqual(Pipeline.check_harness_levels(self.project.harness, self.parts).status,
                         checks.SKIP)
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 22,
                           "length_mm": 80, "wires": [w("VIN", "5V"), w("GND", "GND")]}]}
        r = Pipeline.check_harness_levels(self.path(doc), self.parts)
        self.assertEqual(r.status, checks.SKIP)
        self.assertIn("no two signal pins of known voltage share a wire", r.detail)


class TestTheWireIsSetAside(LampCase):
    def test_the_output_wire_goes_and_the_step_says_why(self):
        fixed, notes = harness.drop_overvoltage(real_reply(), self.parts)
        ring = [(x["from_pin"], x["to_pin"]) for x in fixed["cables"][0]["wires"]]
        self.assertEqual(ring, [("VIN", "5V"), ("GND", "GND"), ("GPIO4", "DIN")])
        self.assertEqual(notes, [
            "Set aside the wire from ws2812b_ring8.DOUT to esp32_devkit_v1.GPIO18: it is a "
            "5 V output and that pin is made for 3.3 V. If the signal is needed it must go "
            "through a level shifter."])

    def test_the_input_wire_and_everything_else_stay(self):
        fixed, _ = harness.drop_overvoltage(real_reply(), self.parts)
        self.assertEqual(fixed["cables"][1], real_reply()["cables"][1])
        self.assertIn(w("GPIO4", "DIN"), fixed["cables"][0]["wires"])

    def test_the_answer_it_was_given_is_not_altered_and_twice_changes_nothing(self):
        doc = real_reply()
        fixed, _ = harness.drop_overvoltage(doc, self.parts)
        self.assertEqual(doc, real_reply())
        self.assertEqual(harness.drop_overvoltage(fixed, self.parts), (fixed, []))

    def test_a_sound_wiring_is_untouched(self):
        lib = PartsLibrary.load()
        parts = [lib.get(r) for r in ("esp32_devkit_v1", "bme280", "ssd1306_oled_096")]
        self.assertEqual(harness.drop_overvoltage(good(), parts), (good(), []))


class TestTheStepAndTheGuide(LampCase):
    def run_step(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_the_real_answer_now_passes_at_the_first_asking_without_that_wire(self):
        r = SchemaRouter(real_reply())
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        self.assertIn("Set aside the wire from ws2812b_ring8.DOUT", sr.render())
        levels = next(x for x in sr.results if x.name == "harness_levels")
        self.assertEqual(levels.status, PASS)
        self.assertIn("1 to confirm", levels.detail)

    def test_the_wire_it_could_not_rule_on_is_an_open_question_in_the_guide(self):
        levels = Result("harness_levels", PASS, "5 signal wire(s) compared, 1 to confirm",
                        ["esp32_devkit_v1.GPIO4 (3.3 V) drives ws2812b_ring8.DIN, a 5 V input: "
                         "it may not reach the level that input needs. See the part's notes"])
        self.pipe(StubRouter()).stage_pack([StageResult("electrical", True, [levels])])
        text = self.project.build_md.read_text(encoding="utf-8")
        self.assertIn("- [electrical] confirm: esp32_devkit_v1.GPIO4 (3.3 V) drives "
                      "ws2812b_ring8.DIN", text[text.index("## Open questions"):])

    def test_it_has_a_plain_name_for_the_window(self):
        from nemo.gui import controller as C
        names = [v for v in vars(C).values() if isinstance(v, dict) and "harness_pins" in v][0]
        self.assertEqual(names["harness_levels"], "Signal voltages suit both ends")


class TestAProjectAtOneVoltage(WeatherCase):
    def test_passes_with_nothing_to_confirm(self):
        text, _ = harness.build(good(), self.parts)
        r = Pipeline.check_harness_levels(self.harness(text), self.parts)
        self.assertEqual((r.status, r.items), (PASS, []))


if __name__ == "__main__":
    unittest.main()
