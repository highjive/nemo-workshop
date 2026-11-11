"""D150: a battery supply, wired by code in the order current flows.

The owner asked for a 5 V supply from a battery. The library had a cell,
a protected charger board and a 5 V boost converter, none with any pins,
so code stepped aside whenever one was in a project and the model wired
the supply, with nothing able to check a voltage along it.

Pad names are from the sources the library entries cite: the boost
module's four pads from components101's page for it, the charger board's
battery and output pads from the page its entry already cited. A cell's
two lead names are Nemo's own.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, firmware, harness
from nemo.checks.deterministic import PASS, Result
from nemo.parts import PartsLibrary
from nemo.pipeline import Pipeline
from nemo.project import Brief
from test_harness import SchemaRouter
from test_pipeline import PipelineCase

REFS = ("esp32_devkit_v1", "bme280", "ws2812b_ring8", "lipo_1000", "tp4056_protected",
        "boost_5v_mt3608")


def w(a, b):
    return {"from_pin": a, "to_pin": b, "colour": "white"}


def signals_only() -> dict:
    """What the model is left to choose: the signal wires."""
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "bme280", "gauge_awg": 24, "length_mm": 80,
         "wires": [w("GPIO21", "SDA"), w("GPIO22", "SCL")]},
        {"from": "esp32_devkit_v1", "to": "ws2812b_ring8", "gauge_awg": 24, "length_mm": 80,
         "wires": [w("GPIO4", "DIN")]}]}


def pairs(doc, a, b):
    return [(x["from_pin"], x["to_pin"]) for c in doc["cables"]
            if (c["from"], c["to"]) == (a, b) for x in c["wires"]]


class TestTheLibrary(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()

    def test_every_cell_has_a_positive_that_supplies_and_a_negative(self):
        for ref in ("lipo_1000", "lipo_2000", "eemb_lipo_500"):
            p = self.lib.get(ref)
            self.assertEqual([(x.name, x.function, x.direction) for x in p.pins],
                             [("BAT+", "power", "out"), ("BAT-", "gnd", "")], ref)
            self.assertEqual(p.pin("BAT+").voltage, 3.7)

    def test_the_charger_board_has_a_battery_side_and_an_output_side(self):
        p = self.lib.get("tp4056_protected")
        self.assertEqual([x.name for x in p.pins], ["B+", "B-", "OUT+", "OUT-"])
        self.assertEqual((p.pin("B+").direction, p.pin("OUT+").direction), ("in", "out"))
        self.assertEqual(harness._side(p, "in"), ("B+", "B-"))
        self.assertEqual(harness._side(p, "out"), ("OUT+", "OUT-"))

    def test_the_converter_takes_the_cell_and_gives_five_volts(self):
        p = self.lib.get("boost_5v_mt3608")
        self.assertEqual([x.name for x in p.pins], ["VIN+", "VIN-", "VOUT+", "VOUT-"])
        self.assertEqual((p.pin("VIN+").voltage, p.pin("VOUT+").voltage), (3.7, 5.0))
        self.assertEqual(p.output_v, [5.0])

    def test_no_power_part_is_left_without_pins(self):
        self.assertEqual([p.ref for p in self.lib.parts.values()
                          if p.category == "power" and not p.pins], [])


class ChainCase(PipelineCase):
    PARTS = REFS

    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="pocket-lamp", function="A battery lamp that shows the temperature as a colour.",
            power="LiPo 3.7 V 1000 mAh", supply_ma=1000, rails=[5.0, 3.3],
            envelope_mm=[120, 80, 40], parts=list(self.PARTS), mcu="esp32",
            done_when="The ring changes colour with the temperature."))
        self.parts = [self.lib.get(r) for r in self.PARTS]

    def path(self, doc):
        text, _ = harness.build(doc, self.parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        return self.project.harness


class TestTheOrder(ChainCase):
    def test_cell_then_protection_then_converter(self):
        self.assertEqual([p.ref for p in harness.supply_chain(self.parts)],
                         ["lipo_1000", "tp4056_protected", "boost_5v_mt3608"])

    def test_the_order_does_not_depend_on_the_order_in_the_brief(self):
        self.assertEqual([p.ref for p in harness.supply_chain(list(reversed(self.parts)))],
                         ["lipo_1000", "tp4056_protected", "boost_5v_mt3608"])

    def test_arrangements_it_does_not_understand_are_none_not_a_guess(self):
        get = self.lib.get
        base = [get("esp32_devkit_v1"), get("bme280")]
        self.assertIsNone(harness.supply_chain(base))                                # no battery
        self.assertIsNone(harness.supply_chain(base + [get("lipo_1000")]))           # no converter
        self.assertIsNone(harness.supply_chain(base + [get("lipo_1000"), get("lipo_2000"),
                                                       get("boost_5v_mt3608")]))     # two cells
        self.assertIsNone(harness.supply_chain(base + [get("boost_5v_mt3608")]))     # no cell
        self.assertIsNone(harness.supply_chain(
            [get("bme280"), get("lipo_1000"), get("boost_5v_mt3608")]))              # no board

    def test_a_cell_straight_into_the_converter_is_understood(self):
        parts = [p for p in self.parts if p.ref != "tp4056_protected"]
        self.assertEqual([p.ref for p in harness.supply_chain(parts)],
                         ["lipo_1000", "boost_5v_mt3608"])


class TestTheWiring(ChainCase):
    def setUp(self):
        super().setUp()
        self.doc, self.notes = harness.wire_power(signals_only(), self.parts)

    def test_each_stage_feeds_the_next_and_the_last_feeds_the_board(self):
        self.assertEqual(pairs(self.doc, "lipo_1000", "tp4056_protected"),
                         [("BAT+", "B+"), ("BAT-", "B-")])
        self.assertEqual(pairs(self.doc, "tp4056_protected", "boost_5v_mt3608"),
                         [("OUT+", "VIN+"), ("OUT-", "VIN-")])
        self.assertEqual(pairs(self.doc, "boost_5v_mt3608", "esp32_devkit_v1"),
                         [("VOUT+", "VIN"), ("VOUT-", "GND")])

    def test_the_cells_negative_reaches_nothing_but_the_protection_board(self):
        touching = [(c["from"], c["to"]) for c in self.doc["cables"]
                    if "lipo_1000" in (c["from"], c["to"])]
        self.assertEqual(touching, [("lipo_1000", "tp4056_protected")])

    def test_the_loads_are_fed_from_the_board_each_at_a_voltage_it_takes(self):
        self.assertEqual(pairs(self.doc, "esp32_devkit_v1", "bme280")[:2],
                         [("3V3", "VCC"), ("GND", "GND")])
        self.assertEqual(pairs(self.doc, "esp32_devkit_v1", "ws2812b_ring8")[:2],
                         [("VIN", "5V"), ("GND", "GND")])

    def test_the_models_signal_wires_are_kept(self):
        self.assertEqual(pairs(self.doc, "esp32_devkit_v1", "bme280")[2:],
                         [("GPIO21", "SDA"), ("GPIO22", "SCL")])

    def test_it_says_what_it_did(self):
        self.assertIn("The supply is wired by Nemo, in order: lipo_1000 to tp4056_protected to "
                      "boost_5v_mt3608 to esp32_devkit_v1.VIN. The cell's negative goes only "
                      "to the next board in that chain, never straight to ground.", self.notes)

    def test_done_twice_it_changes_nothing_and_says_nothing_more(self):
        again, notes = harness.wire_power(self.doc, self.parts)
        self.assertEqual(again, self.doc)
        self.assertEqual(notes, [])

    def test_whatever_the_model_ran_to_a_power_part_is_replaced(self):
        doc = signals_only()
        doc["cables"].append({"from": "lipo_1000", "to": "esp32_devkit_v1", "gauge_awg": 22,
                              "length_mm": 60, "wires": [w("BAT+", "3V3"), w("BAT-", "GND")]})
        fixed, _ = harness.wire_power(doc, self.parts)
        self.assertEqual(pairs(fixed, "lipo_1000", "esp32_devkit_v1"), [])
        self.assertEqual(fixed, self.doc)

    def test_every_check_passes_on_it(self):
        p = self.path(self.doc)
        for check in (Pipeline.check_harness_pins, Pipeline.check_harness_covers,
                      Pipeline.check_harness_electrical, Pipeline.check_harness_signals,
                      Pipeline.check_harness_supply):
            r = check(p, self.parts)
            self.assertEqual(r.status, PASS, f"{check.__name__}: {r.render()}")

    def test_a_firmware_can_be_written_from_it(self):
        plan = firmware.plan(self.doc, self.parts)
        self.assertEqual(plan.parts, ["bme280", "ws2812b_ring8"])


class TestTheSupplyCheckReadsTheChain(ChainCase):
    def setUp(self):
        super().setUp()
        self.doc, _ = harness.wire_power(signals_only(), self.parts)

    def result(self, doc):
        return Pipeline.check_harness_supply(self.path(doc), self.parts)

    def test_the_cell_wired_straight_to_the_boards_five_volt_pin_fails(self):
        doc = {"cables": self.doc["cables"] + [
            {"from": "lipo_1000", "to": "esp32_devkit_v1", "gauge_awg": 22, "length_mm": 60,
             "wires": [w("BAT+", "VIN")]}]}
        r = self.result(doc)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("two different supplies on one wire", r.render())

    def test_the_converter_fed_from_its_own_output_side_voltage_fails(self):
        doc = {"cables": [c for c in self.doc["cables"]
                          if (c["from"], c["to"]) != ("tp4056_protected", "boost_5v_mt3608")]}
        doc["cables"].append({"from": "boost_5v_mt3608", "to": "tp4056_protected",
                              "gauge_awg": 22, "length_mm": 60,
                              "wires": [w("VOUT+", "B+")]})
        r = self.result(doc)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("tp4056_protected.B+ takes 3.7 V and is fed from "
                      "boost_5v_mt3608.VOUT+, which is 5 V", r.render())

    def test_a_cell_positive_wired_to_a_ground_pin_is_a_short(self):
        doc = {"cables": self.doc["cables"] + [
            {"from": "lipo_1000", "to": "tp4056_protected", "gauge_awg": 22, "length_mm": 60,
             "wires": [w("BAT+", "B-")]}]}
        r = self.result(doc)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("a supply joined to ground is a short circuit", r.render())


class TestWhatItDoesNotUnderstand(ChainCase):
    PARTS = ("esp32_devkit_v1", "bme280", "lipo_1000", "tp4056_protected")

    def test_the_power_parts_are_left_unwired_and_it_says_which(self):
        doc, notes = harness.wire_power(signals_only_for(self.PARTS), self.parts)
        self.assertEqual([c for c in doc["cables"] if "lipo_1000" in (c["from"], c["to"])], [])
        self.assertTrue(any("Nemo does not wire this supply" in n and "lipo_1000" in n
                            and "tp4056_protected" in n for n in notes), notes)

    def test_and_the_step_then_fails_rather_than_pass_an_unpowered_board(self):
        r = SchemaRouter(signals_only_for(self.PARTS))
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            sr = self.pipe(r).stage_wiring()
        self.assertFalse(sr.ok)
        self.assertIn("Nemo does not wire this supply", sr.render())


class TestTheBudgetCountsTheConverter(ChainCase):
    """D151. Real run, AH531, 2026-10-07: "PASS current_sum -- 741 mA of
    1000 mA" for 741 mA of 5 V loads on a 3.7 V cell rated for 1000."""

    def test_the_real_design_draws_more_from_the_cell_than_it_can_give(self):
        r = checks.current_sum(self.parts, 1000)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("1077 mA", r.detail)
        self.assertIn("through boost_5v_mt3608: 741 mA at 5 V is 1077 mA from the 3.7 V "
                      "supply (93% efficient; more as the cell runs down)", r.render())

    def test_the_arithmetic(self):
        self.assertEqual(round(741 * 5.0 / (3.7 * 0.93)), 1077)

    def test_a_cell_twice_the_size_passes(self):
        r = checks.current_sum(self.parts, 2000)
        self.assertEqual(r.status, PASS, r.render())
        self.assertEqual(r.detail, "1077 mA of 2000 mA")

    def test_the_same_loads_on_a_five_volt_supply_are_counted_as_before(self):
        usb = [p for p in self.parts if p.category != "power"]
        r = checks.current_sum(usb, 1000)
        self.assertEqual((r.status, r.detail), (PASS, "741 mA of 1000 mA"))
        self.assertNotIn("through", r.render())

    def test_a_converter_with_no_cell_to_feed_it_changes_nothing(self):
        parts = [p for p in self.parts if p.ref not in ("lipo_1000", "tp4056_protected")]
        self.assertEqual(checks.current_sum(parts, 1000).detail, "741 mA of 1000 mA")

    def test_a_cell_with_no_converter_changes_nothing(self):
        parts = [p for p in self.parts if p.ref != "boost_5v_mt3608"]
        self.assertEqual(checks.current_sum(parts, 1000).detail, "741 mA of 1000 mA")


class TestACellIsNotTheWarmPart(ChainCase):
    """D152. Same run: "bme280 4.4 mm from lipo_1000, which draws the most
    current and will warm it"."""

    def test_the_warm_part_is_the_one_that_draws_most_not_the_one_that_supplies(self):
        from nemo import enclosure
        self.assertEqual(enclosure.warm_part(self.parts).ref, "ws2812b_ring8")
        self.assertEqual(self.lib.get("lipo_1000").draw_ma, 2000)     # why it was picked

    def test_a_project_of_power_parts_and_a_small_sensor_has_none(self):
        from nemo import enclosure
        parts = [self.lib.get(r) for r in ("bme280", "lipo_1000", "tp4056_protected")]
        self.assertIsNone(enclosure.warm_part(parts))


def signals_only_for(refs) -> dict:
    return {"cables": [c for c in signals_only()["cables"] if c["to"] in refs]}


class TestTheStep(ChainCase):
    def run_step(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_the_model_is_not_offered_the_power_parts(self):
        r = SchemaRouter(signals_only())
        self.run_step(r)
        for ref in ("lipo_1000", "tp4056_protected", "boost_5v_mt3608", "BAT+", "VOUT+"):
            self.assertNotIn(ref, r.asked[0]["user"])
            self.assertNotIn(ref, str(r.asked[0]["schema"]))
        self.assertIn("ws2812b_ring8", r.asked[0]["user"])

    def test_signal_wires_from_the_model_and_the_supply_from_code_pass_together(self):
        r = SchemaRouter(signals_only())
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        self.assertIn("The supply is wired by Nemo, in order: lipo_1000", sr.render())


if __name__ == "__main__":
    unittest.main()
