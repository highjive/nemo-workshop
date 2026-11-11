"""Tests for the deterministic layer.

These are the checks that catch real mistakes, so they are the ones worth
testing. Uses stdlib unittest -- no pytest install on a slow machine.

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.checks import (FAIL, PASS, SKIP, check_wire_gauges, current_sum,
                         fits_envelope, printability, supply_rails,
                         trace_width_mm, voltage_compatibility, wire_gauge,
                         xref_cutouts, xref_nets)
from nemo.parts import Part, PartsLibrary, Pin


def mk(ref, **kw) -> Part:
    base = dict(name=ref, category="misc")
    base.update(kw)
    return Part(ref=ref, **base)


class TestPower(unittest.TestCase):
    def test_peak_used_not_typical(self):
        p = mk("amp", current_ma=5, peak_ma=700)
        self.assertEqual(p.draw_ma, 700)

    def test_over_supply_fails(self):
        parts = [mk("a", peak_ma=700), mk("b", peak_ma=400)]
        r = current_sum(parts, supply_ma=1000)
        self.assertEqual(r.status, FAIL)
        self.assertIn("exceeds", r.detail)

    def test_headroom_enforced(self):
        # 800 mA of a 1000 mA supply is under the rating but inside the
        # 25% headroom band, which should still fail.
        r = current_sum([mk("a", peak_ma=800)], supply_ma=1000)
        self.assertEqual(r.status, FAIL)
        self.assertIn("headroom", r.detail)

    def test_comfortable_passes(self):
        r = current_sum([mk("a", peak_ma=300)], supply_ma=1000)
        self.assertEqual(r.status, PASS)

    def test_no_supply_skips(self):
        self.assertEqual(current_sum([mk("a", peak_ma=1)], 0).status, SKIP)

    def test_unsupplied_rail_fails(self):
        r = supply_rails([mk("a", supply_v=[12.0])], rails=[5.0, 3.3])
        self.assertEqual(r.status, FAIL)

    def test_rail_tolerance(self):
        r = supply_rails([mk("a", supply_v=[3.3])], rails=[3.2])
        self.assertEqual(r.status, PASS)


class TestVoltage(unittest.TestCase):
    def test_5v_driving_3v3_flagged(self):
        mcu = mk("mcu", logic_v=5.0,
                 pins=[Pin("TX", "bus", 5.0)])
        mod = mk("mod", logic_v=3.3,
                 pins=[Pin("TX", "bus", 3.3)])
        r = voltage_compatibility([(mcu, "TX", mod, "TX")])
        self.assertEqual(r.status, FAIL)
        self.assertIn("level shifting", r.items[0])

    def test_matched_logic_passes(self):
        a = mk("a", logic_v=3.3, pins=[Pin("SCK", "bus", 3.3)])
        b = mk("b", logic_v=3.3, pins=[Pin("SCK", "bus", 3.3)])
        self.assertEqual(
            voltage_compatibility([(a, "SCK", b, "SCK")]).status, PASS)

    def test_unknown_voltage_ignored(self):
        a = mk("a", pins=[Pin("X", "io")])
        b = mk("b", pins=[Pin("X", "io")])
        self.assertEqual(
            voltage_compatibility([(a, "X", b, "X")]).status, PASS)


class TestIPC2221(unittest.TestCase):
    """Against published IPC-2221A figures."""

    def test_1a_external_10c(self):
        # ~0.30 mm (12 mil) is the widely published value
        self.assertAlmostEqual(trace_width_mm(1.0), 0.30, delta=0.03)

    def test_3a_external_10c(self):
        self.assertAlmostEqual(trace_width_mm(3.0), 1.37, delta=0.15)

    def test_internal_wider_than_external(self):
        self.assertGreater(trace_width_mm(1.0, layer="internal"),
                           trace_width_mm(1.0, layer="external"))

    def test_more_copper_means_narrower(self):
        self.assertLess(trace_width_mm(1.0, thickness_oz=2.0),
                        trace_width_mm(1.0, thickness_oz=1.0))

    def test_zero_current(self):
        self.assertEqual(trace_width_mm(0), 0.0)


class TestWireGauge(unittest.TestCase):
    def test_uses_power_transmission_not_chassis(self):
        # Chassis ratings would nominate 30 AWG here, which is absurd for
        # a 700 mA run bundled inside a sealed enclosure.
        self.assertLessEqual(wire_gauge(700), 22)

    def test_thicker_for_more_current(self):
        self.assertLess(wire_gauge(3000), wire_gauge(300))

    def test_undersized_run_fails(self):
        r = check_wire_gauges([{"name": "spk", "current_ma": 700,
                                "awg": 30}])
        self.assertEqual(r.status, FAIL)

    def test_adequate_run_passes(self):
        r = check_wire_gauges([{"name": "spk", "current_ma": 700,
                                "awg": 20}])
        self.assertEqual(r.status, PASS)

    def test_empty_skips(self):
        self.assertEqual(check_wire_gauges([]).status, SKIP)


class TestXref(unittest.TestCase):
    def test_orphan_harness_net_fails(self):
        r = xref_nets({"GND", "SDA", "GHOST"}, {"GND", "SDA"})
        self.assertEqual(r.status, FAIL)
        self.assertTrue(any("GHOST" in i for i in r.items))

    def test_unwired_schematic_net_passes_with_note(self):
        r = xref_nets({"GND"}, {"GND", "SPARE"})
        self.assertEqual(r.status, PASS)
        self.assertTrue(any("SPARE" in i for i in r.items))

    def test_missing_cutout_fails(self):
        spk = mk("speaker", mount="panel")
        self.assertEqual(xref_cutouts([spk], set()).status, FAIL)

    def test_present_cutout_passes(self):
        spk = mk("speaker", mount="panel")
        self.assertEqual(xref_cutouts([spk], {"speaker"}).status, PASS)

    def test_no_panel_parts_skips(self):
        self.assertEqual(
            xref_cutouts([mk("x", mount="holes")], set()).status, SKIP)


class TestEnvelope(unittest.TestCase):
    def test_too_tall_fails(self):
        p = mk("board", size_mm=[20, 20, 40])
        r = fits_envelope([p], [100, 100, 20])
        self.assertEqual(r.status, FAIL)

    def test_too_much_floor_area_fails(self):
        parts = [mk(f"p{i}", size_mm=[40, 40, 5]) for i in range(6)]
        self.assertEqual(fits_envelope(parts, [80, 80, 20]).status, FAIL)

    def test_comfortable_fit_passes(self):
        p = mk("board", size_mm=[20, 20, 5])
        self.assertEqual(fits_envelope([p], [100, 100, 20]).status, PASS)


class TestPrintability(unittest.TestCase):
    def test_thin_wall_fails(self):
        r = printability(1.2, wall_mm=0.6, nozzle_mm=0.4, overhangs_deg=[])
        self.assertEqual(r.status, FAIL)

    def test_steep_overhang_fails(self):
        r = printability(1.2, wall_mm=2.0, nozzle_mm=0.4,
                         overhangs_deg=[65])
        self.assertEqual(r.status, FAIL)

    def test_good_geometry_passes(self):
        r = printability(1.2, wall_mm=1.6, nozzle_mm=0.4,
                         overhangs_deg=[30, 45])
        self.assertEqual(r.status, PASS)


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()

    def test_bundled_parts_load(self):
        self.assertGreater(len(self.lib), 5)

    def test_rc522_facts(self):
        p = self.lib.require("rc522")
        self.assertEqual(p.logic_v, 3.3)
        self.assertGreater(p.peak_ma, p.current_ma)
        self.assertIn("5 V", p.notes)

    def test_unknown_part_raises_rather_than_guessing(self):
        with self.assertRaises(KeyError) as ctx:
            self.lib.require("totally_made_up_module")
        self.assertIn("datasheet", str(ctx.exception))

    def test_pin_lookup_case_insensitive(self):
        self.assertIsNotNone(self.lib.require("rc522").pin("vcc"))

    def test_real_design_catches_the_rc522_trap(self):
        """The check that matters for the treasure-chest build."""
        rc522 = self.lib.require("rc522")
        dfp = self.lib.require("dfplayer_mini")
        spk = self.lib.require("speaker_8ohm_20mm")
        esp = self.lib.require("esp32_devkit_v1")

        # A 500 mA USB supply is not enough for this set at peak.
        r = current_sum([rc522, dfp, spk, esp], supply_ma=500)
        self.assertEqual(r.status, FAIL)

        # 1 A is.
        r = current_sum([rc522, dfp, spk, esp], supply_ma=1000)
        self.assertEqual(r.status, PASS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
