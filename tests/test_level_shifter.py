"""D148: a level shifter in the library, and signals routed through it.

After D147 the tilt lamp passed with one thing left for a person: the
board's 3.3 V pin driving the LED ring's 5 V data input, which the ring's
own note says wants 3.5 V. Nemo could say so and do nothing about it: the
library had no part that raises a signal.

Every figure for the part is from TI's datasheet SCLS264R (revised
February 2024), read on 2026-10-06. The tests below hold the library entry
to what that datasheet says.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, firmware, fixes, harness
from nemo.checks.deterministic import PASS, Result
from nemo.parts import PartsLibrary, _build_part
from nemo.pipeline import Pipeline
from nemo.project import Brief
from test_harness import SchemaRouter
from test_pipeline import PipelineCase

REFS = ("esp32_devkit_v1", "mpu6050", "ws2812b_ring8", "sn74ahct125")
# Table 4-1 of the datasheet, 14-pin packages: name -> pin number.
DATASHEET_PINS = {"1OE": 1, "1A": 2, "1Y": 3, "2OE": 4, "2A": 5, "2Y": 6, "GND": 7,
                  "3Y": 8, "3A": 9, "3OE": 10, "4Y": 11, "4A": 12, "4OE": 13, "VCC": 14}


def w(a, b):
    return {"from_pin": a, "to_pin": b, "colour": "white"}


def model_reply() -> dict:
    """The tilt lamp as the model wired it on the run that passed."""
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 22, "length_mm": 80,
         "wires": [w("VIN", "5V"), w("GND", "GND"), w("GPIO4", "DIN"), w("GPIO18", "DOUT")]},
        {"from": "mpu6050", "to": "esp32_devkit_v1", "gauge_awg": 22, "length_mm": 80,
         "wires": [w("VCC", "3V3"), w("GND", "GND"), w("SCL", "GPIO27"), w("SDA", "GPIO32"),
                   w("INT", "GPIO26"), w("AD0", "GPIO25")]}]}


def pairs(doc, a, b):
    return [(x["from_pin"], x["to_pin"]) for c in doc["cables"]
            if (c["from"], c["to"]) == (a, b) for x in c["wires"]]


class TestTheLibraryEntryIsTheDatasheets(unittest.TestCase):
    def setUp(self):
        self.part = PartsLibrary.load().get("sn74ahct125")

    def test_fourteen_pins_in_the_datasheets_order(self):
        self.assertEqual([p.name for p in self.part.pins],
                         sorted(DATASHEET_PINS, key=DATASHEET_PINS.get))

    def test_supply_is_five_volts(self):
        self.assertEqual(self.part.supply_v, [5.0])           # VCC 4.5 to 5.5 V
        self.assertEqual((self.part.pin("VCC").function, self.part.pin("VCC").voltage),
                         ("power", 5.0))
        self.assertEqual(self.part.pin("GND").function, "gnd")

    def test_inputs_read_a_3v3_high_and_take_up_to_5v5(self):
        for name in ("1A", "2A", "3A", "4A", "1OE", "2OE", "3OE", "4OE"):
            pin = self.part.pin(name)
            self.assertEqual((pin.direction, pin.voltage, pin.tolerates), ("in", 3.3, 5.5), name)

    def test_outputs_swing_to_the_supply(self):
        for name in ("1Y", "2Y", "3Y", "4Y"):
            self.assertEqual((self.part.pin(name).direction, self.part.pin(name).voltage),
                             ("out", 5.0), name)

    def test_four_gates_a_to_y_each_enabled_by_its_own_oe_held_low(self):
        self.assertEqual(self.part.gates, [
            {"in": f"{n}A", "out": f"{n}Y", "enable_low": f"{n}OE"} for n in "1234"])

    def test_it_names_its_source_and_gives_no_size_it_did_not_read(self):
        self.assertIn("SCLS264R", self.part.datasheet)
        self.assertEqual(self.part.size_mm, [])

    def test_a_gate_naming_a_pin_the_part_has_not_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            _build_part("x", {"name": "X", "category": "logic",
                              "pins": [{"name": "A", "function": "io"}],
                              "gates": [{"in": "A", "out": "Y"}]})
        self.assertIn("every pin it names", str(ctx.exception))

    def test_no_other_part_has_gates(self):
        self.assertEqual([p.ref for p in PartsLibrary.load().parts.values() if p.gates],
                         ["sn74ahct125"])


class ShifterCase(PipelineCase):
    PARTS = REFS

    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="tilt-lamp", function="A ring of lights that changes colour as it is tilted.",
            power="USB 5 V 2 A", supply_ma=2000, rails=[5.0, 3.3], envelope_mm=[110, 70, 35],
            parts=list(self.PARTS), mcu="esp32", done_when="Tilting it changes the colour."))
        self.parts = [self.lib.get(r) for r in self.PARTS]

    def settle(self, doc):
        doc, n1 = harness.wire_power(doc, self.parts)
        doc, n2 = harness.drop_overvoltage(doc, self.parts)
        doc, n3 = harness.route_through_shifter(doc, self.parts)
        return doc, n1 + n2 + n3

    def path(self, doc):
        text, _ = harness.build(doc, self.parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        return self.project.harness


class TestTheSignalGoesThroughIt(ShifterCase):
    def setUp(self):
        super().setUp()
        self.doc, self.notes = self.settle(model_reply())

    def test_the_boards_wire_to_the_ring_becomes_one_in_and_one_out(self):
        self.assertNotIn(("GPIO4", "DIN"), pairs(self.doc, "esp32_devkit_v1", "ws2812b_ring8"))
        self.assertIn(("GPIO4", "1A"), pairs(self.doc, "esp32_devkit_v1", "sn74ahct125"))
        self.assertEqual(pairs(self.doc, "sn74ahct125", "ws2812b_ring8"), [("1Y", "DIN")])

    def test_it_says_so(self):
        self.assertIn("esp32_devkit_v1.GPIO4 (3.3 V) drives ws2812b_ring8.DIN, a 5 V input, so "
                      "Nemo routed it through sn74ahct125: in at 1A, out at 1Y.", self.notes)

    def test_the_shifter_is_powered_from_five_volts_and_grounded(self):
        to_shifter = pairs(self.doc, "esp32_devkit_v1", "sn74ahct125")
        self.assertIn(("VIN", "VCC"), to_shifter)
        self.assertIn(("GND", "GND"), to_shifter)

    def test_every_enable_and_every_spare_input_is_tied_to_ground(self):
        # The datasheet: OE low passes A to Y; unused inputs must not float.
        to_shifter = pairs(self.doc, "esp32_devkit_v1", "sn74ahct125")
        for pin in ("1OE", "2OE", "3OE", "4OE", "2A", "3A", "4A"):
            self.assertIn(("GND", pin), to_shifter, pin)
        self.assertNotIn(("GND", "1A"), to_shifter)           # that one carries the signal

    def test_wires_between_parts_at_one_voltage_are_left_alone(self):
        self.assertEqual(pairs(self.doc, "mpu6050", "esp32_devkit_v1")[2:],
                         [("SCL", "GPIO27"), ("SDA", "GPIO32"), ("INT", "GPIO26"),
                          ("AD0", "GPIO25")])

    def test_every_check_passes_and_nothing_is_left_to_confirm(self):
        p = self.path(self.doc)
        for check in (Pipeline.check_harness_pins, Pipeline.check_harness_covers,
                      Pipeline.check_harness_electrical, Pipeline.check_harness_signals,
                      Pipeline.check_harness_supply, Pipeline.check_harness_levels):
            r = check(p, self.parts)
            self.assertEqual(r.status, PASS, f"{check.__name__}: {r.render()}")
        self.assertEqual(Pipeline.check_harness_levels(p, self.parts).items, [])

    def test_done_twice_it_changes_nothing_and_never_grounds_the_signal(self):
        again, notes = harness.route_through_shifter(self.doc, self.parts)
        self.assertEqual(again, self.doc)
        self.assertEqual(notes, [])
        self.assertNotIn(("GND", "1A"), pairs(again, "esp32_devkit_v1", "sn74ahct125"))

    def test_the_answer_it_was_given_is_not_altered(self):
        doc = model_reply()
        harness.route_through_shifter(doc, self.parts)
        self.assertEqual(doc, model_reply())

    def test_a_firmware_can_still_be_written_from_it(self):
        plan = firmware.plan(self.doc, self.parts)
        self.assertEqual(plan.mcu, "esp32_devkit_v1")
        self.assertNotIn("sn74ahct125", plan.parts)           # it has no logic of its own
        ring = next(x for x in plan.pins if x.part == "ws2812b_ring8")
        self.assertEqual((ring.const, ring.gpio), ("PIN_WS2812B_RING8_DIN", 4))
        self.assertEqual(ring.net, "GPIO4 through sn74ahct125")
        self.assertEqual([x for x in plan.pins if x.part == "sn74ahct125"], [])
        source = firmware.scaffold(self.doc, self.parts, "tilt-lamp", "esp32dev", 500)
        self.assertRegex(source, r"PIN_WS2812B_RING8_DIN\s+=\s+4;")
        self.assertNotIn("update_sn74ahct125", source)
        self.assertIn("update_ws2812b_ring8", source)


class TestOtherShapes(ShifterCase):
    def test_more_signals_than_gates_says_which_one_was_left(self):
        ring2 = self.lib.get("ws2812b_ring8")
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 22,
                           "length_mm": 80, "wires": [w("GPIO4", "DIN")]}]}
        short = [self.parts[0], ring2, self.lib.get("sn74ahct125")]
        short[2] = type(short[2])(**{**short[2].__dict__, "gates": []})
        self.assertEqual(harness.route_through_shifter(doc, short), (doc, []))   # no gates: no shifter

    def test_an_output_of_the_part_is_never_sent_through_it(self):
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 22,
                           "length_mm": 80, "wires": [w("GPIO18", "DOUT")]}]}
        fixed, notes = harness.route_through_shifter(doc, self.parts)
        self.assertEqual(pairs(fixed, "esp32_devkit_v1", "ws2812b_ring8"), [("GPIO18", "DOUT")])
        self.assertFalse(any("routed" in n for n in notes))

    def test_a_3v3_part_is_never_sent_through_it(self):
        doc, notes = self.settle({"cables": [model_reply()["cables"][1]]})
        self.assertFalse(any("routed" in n for n in notes))
        self.assertEqual(pairs(doc, "sn74ahct125", "mpu6050"), [])


class TestWithoutOneInTheProject(ShifterCase):
    PARTS = REFS[:3]

    def test_nothing_is_changed(self):
        doc = model_reply()
        self.assertEqual(harness.route_through_shifter(doc, self.parts), (doc, []))

    def test_the_passing_check_offers_to_add_one(self):
        doc, _ = self.settle(model_reply())
        r = Pipeline.check_harness_levels(self.path(doc), self.parts)
        self.assertEqual(r.status, PASS)
        record = {"checks": [{"name": r.name, "status": r.status, "detail": r.detail,
                              "items": r.items}]}
        got = fixes.suggest_fixes(self.project.load_brief(), self.lib, "electrical", record)
        fix = next(f for f in got if f.key == "level_shifter")
        self.assertEqual(fix.add_parts, ["sn74ahct125"])
        self.assertEqual(fix.kind, "change")
        brief = fixes.apply_fix(self.project.load_brief(), fix)
        self.assertIn("sn74ahct125", brief.parts)

    def test_a_check_with_nothing_to_confirm_offers_nothing(self):
        record = {"checks": [{"name": "harness_levels", "status": "PASS",
                              "detail": "4 signal wire(s) compared, voltages match",
                              "items": []}]}
        got = fixes.suggest_fixes(self.project.load_brief(), self.lib, "electrical", record)
        self.assertEqual([f.key for f in got], [])


class TestTheStep(ShifterCase):
    def test_the_models_answer_passes_first_time_with_the_shifter_wired_in(self):
        r = SchemaRouter(model_reply())
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            sr = self.pipe(r).stage_wiring()
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        self.assertIn("so Nemo routed it through sn74ahct125", sr.render())
        levels = next(x for x in sr.results if x.name == "harness_levels")
        self.assertEqual((levels.status, levels.items), (PASS, []))

    def test_and_fixing_it_once_the_project_already_had_one_offers_nothing(self):
        record = {"checks": [{"name": "harness_levels", "status": "PASS", "detail": "x",
                              "items": ["a (3.3 V) drives b, a 5 V input: ..."]}]}
        got = fixes.suggest_fixes(self.project.load_brief(), self.lib, "electrical", record)
        self.assertNotIn("level_shifter", [f.key for f in got])


def real_reply_with_the_shifter_offered() -> dict:
    """What qwen3-1.7b wired on the AH531 when the shifter was listed for it
    like any other part (2026-10-07), power wires left out. Every check
    passed. Nothing drives the ring: DIN goes to a shifter INPUT."""
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "mpu6050", "gauge_awg": 22, "length_mm": 80,
         "wires": [w("GPIO4", "SDA"), w("GPIO18", "SCL"), w("GPIO19", "AD0")]},
        {"from": "sn74ahct125", "to": "ws2812b_ring8", "gauge_awg": 22, "length_mm": 80,
         "wires": [w("1A", "DIN"), w("2A", "DOUT")]}]}


class TestTheModelIsNotOfferedTheShifter(ShifterCase):
    def test_what_it_wired_when_it_was_offered_it_now_fails_two_checks(self):
        doc, _ = harness.wire_power(real_reply_with_the_shifter_offered(), self.parts)
        p = self.path(doc)
        signals = Pipeline.check_harness_signals(p, self.parts)
        self.assertEqual(signals.status, "FAIL")
        self.assertIn("sn74ahct125.1A and ws2812b_ring8.DIN are all inputs: nothing drives "
                      "this wire", signals.render())
        electrical = Pipeline.check_harness_electrical(p, self.parts)
        self.assertEqual(electrical.status, "FAIL")
        self.assertIn("ws2812b_ring8 has no signal wire that reaches esp32_devkit_v1: nothing "
                      "can control it or read it", electrical.render())

    def test_it_is_left_out_of_what_the_model_chooses_between(self):
        self.assertEqual([p.ref for p in harness.chosen_by_model(self.parts)],
                         ["esp32_devkit_v1", "mpu6050", "ws2812b_ring8"])
        r = SchemaRouter(model_reply())
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            self.pipe(r).stage_wiring()
        self.assertNotIn("sn74ahct125", r.asked[0]["user"])
        self.assertNotIn("sn74ahct125", str(r.asked[0]["schema"]))
        self.assertNotIn("1OE", r.asked[0]["user"])

    def test_cables_a_model_runs_to_it_anyway_are_set_aside_and_code_wires_it(self):
        r = SchemaRouter(real_reply_with_the_shifter_offered())
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            sr = self.pipe(r).stage_wiring()
        self.assertIn("Set aside 1 cable(s) the model ran to sn74ahct125: a level shifter is "
                      "wired by Nemo.", sr.render())
        # With that cable gone the ring has no data wire, and the step says so.
        self.assertFalse(sr.ok)
        self.assertIn("ws2812b_ring8 has no signal wire that reaches esp32_devkit_v1",
                      sr.render())

    def test_a_ring_driven_through_a_gate_does_reach_the_board(self):
        doc, _ = self.settle(model_reply())
        r = Pipeline.check_harness_electrical(self.path(doc), self.parts)
        self.assertEqual(r.status, PASS, r.render())

    def test_a_ring_driven_straight_from_the_board_does_too(self):
        parts = self.parts[:3]
        doc, _ = harness.wire_power(model_reply(), parts)
        doc, _ = harness.drop_overvoltage(doc, parts)
        text, _ = harness.build(doc, parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        self.assertEqual(Pipeline.check_harness_electrical(self.project.harness, parts).status,
                         PASS)

    def test_a_wire_from_an_output_to_an_input_is_not_called_undriven(self):
        tag = [self.lib.get(r) for r in ("esp32_devkit_v1", "rc522", "dfplayer_mini")]
        doc = {"cables": [{"from": "rc522", "to": "dfplayer_mini", "gauge_awg": 22,
                           "length_mm": 80, "wires": [w("MISO", "RX")]}]}
        text, _ = harness.build(doc, tag)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        r = Pipeline.check_harness_signals(self.project.harness, tag)
        self.assertNotIn("nothing drives", r.render())


if __name__ == "__main__":
    unittest.main()
