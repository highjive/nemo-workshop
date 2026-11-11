"""O7: the harness and the schematic describe the same circuit, pin by pin.

Both are drawn by code from electrical/connections.json, but the wiring step
decides the connections afresh when that file is missing or stale, and the
electrical step can be re-run after it; then the two can differ while every
other check passes. The bridge O7 lacked (netlist pins are numbers, the
library has names) is the numbering schematic.skidl_script writes in its
'# J1 = ref: 1=VCC, ...' comments.

The netlist below is cut from KiCad 10.0.6's real `sch export netlist
--format kicadxml` of a schematic SKiDL 2.3.0 drew from skidl_script, on the
AH531, 2026-10-20 (a Pico and a BME280).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import harness, schematic
from nemo.checks import runners
from nemo.parts import PartsLibrary
from nemo.pipeline import Pipeline

REAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components>
    <comp ref="J1">
      <value>rp2040_pico</value>
      <libsource lib="Connector_Generic" part="Conn_01x27" description="Generic connector"/>
    </comp>
    <comp ref="J2">
      <value>bme280</value>
      <libsource lib="Connector_Generic" part="Conn_01x04" description="Generic connector"/>
    </comp>
  </components>
  <nets>
    <net code="1" name="+3V3" class="Default">
      <node ref="J1" pin="1" pinfunction="Pin_1_1" pintype="passive"/>
      <node ref="J2" pin="1" pinfunction="Pin_1_1" pintype="passive"/>
    </net>
    <net code="2" name="GND" class="Default">
      <node ref="J1" pin="3" pinfunction="Pin_3_3" pintype="passive"/>
      <node ref="J2" pin="2" pinfunction="Pin_2_2" pintype="passive"/>
    </net>
    <net code="3" name="GPIO4" class="Default">
      <node ref="J1" pin="6" pinfunction="Pin_6_6" pintype="passive"/>
      <node ref="J2" pin="4" pinfunction="Pin_4_4" pintype="passive"/>
    </net>
    <net code="4" name="GPIO5" class="Default">
      <node ref="J1" pin="7" pinfunction="Pin_7_7" pintype="passive"/>
      <node ref="J2" pin="3" pinfunction="Pin_3_3" pintype="passive"/>
    </net>
    <net code="5" name="unconnected-(J1-Pin_2-Pad2)" class="Default">
      <node ref="J1" pin="2" pinfunction="Pin_2_2" pintype="passive+no_connect"/>
    </net>
  </nets>
</export>
"""

WIRES = [("3V3", "VCC"), ("GND", "GND"), ("GPIO4", "SDA"), ("GPIO5", "SCL")]


def parts():
    lib = PartsLibrary.load()
    return [lib.get("rp2040_pico"), lib.get("bme280")]


def doc(wires=WIRES):
    return {"cables": [{"from": "rp2040_pico", "to": "bme280", "wires": [
        {"from_pin": a, "to_pin": b} for a, b in wires]}]}


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.sch = self.dir / "project.kicad_sch"
        self.sch.write_text("(kicad_sch)", encoding="utf-8")
        self.script = self.dir / "schematic.py"
        self.script.write_text(schematic.skidl_script(doc(), parts()), encoding="utf-8")
        self.harness = self.dir / "harness.yaml"

    def wire(self, wires=WIRES):
        self.harness.write_text(harness.build(doc(wires), parts())[0], encoding="utf-8")

    def check(self):
        groups = [("+3V3", {("rp2040_pico", "1"), ("bme280", "1")}),
                  ("GND", {("rp2040_pico", "3"), ("bme280", "2")}),
                  ("GPIO4", {("rp2040_pico", "6"), ("bme280", "4")}),
                  ("GPIO5", {("rp2040_pico", "7"), ("bme280", "3")})]
        with mock.patch("nemo.checks.netlist_groups", return_value=(groups, "")):
            return Pipeline.check_harness_netlist(self.harness, self.sch, self.script)


class TestReadingKiCadsNetlist(unittest.TestCase):
    def test_the_real_layout(self):
        d = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d, True)
        sch = d / "project.kicad_sch"; sch.write_text("x", encoding="utf-8")

        def export(cmd, **kw):
            Path(cmd[cmd.index("--output") + 1]).write_text(REAL_XML, encoding="utf-8")
            return 0, "", ""
        with mock.patch.object(runners, "_kicad", return_value="kicad-cli"), \
             mock.patch.object(runners, "_run", side_effect=export):
            groups, why = runners.netlist_groups(sch)
        self.assertEqual(why, "")
        self.assertEqual(dict(groups), {
            "+3V3": {("rp2040_pico", "1"), ("bme280", "1")},
            "GND": {("rp2040_pico", "3"), ("bme280", "2")},
            "GPIO4": {("rp2040_pico", "6"), ("bme280", "4")},
            "GPIO5": {("rp2040_pico", "7"), ("bme280", "3")}})   # no one-pin nets

    def test_no_kicad_and_a_failed_export_say_why(self):
        d = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d, True)
        sch = d / "p.kicad_sch"; sch.write_text("x", encoding="utf-8")
        with mock.patch.object(runners, "_kicad", return_value=None):
            self.assertEqual(runners.netlist_groups(sch)[0], None)
        with mock.patch.object(runners, "_kicad", return_value="kicad-cli"), \
             mock.patch.object(runners, "_run", return_value=(1, "", "boom")):
            groups, why = runners.netlist_groups(sch)
        self.assertIsNone(groups); self.assertIn("boom", why)


class TestPinNamesFromTheScript(Case):
    def test_the_numbering_skidl_script_writes_is_read_back(self):
        names = Pipeline._schematic_pin_names(self.script)
        self.assertEqual(names[("bme280", "4")], "SDA")
        self.assertEqual(names[("rp2040_pico", "6")], "GPIO4")
        self.assertEqual(names[("rp2040_pico", "1")], "3V3")


class TestTheComparison(Case):
    def test_the_same_circuit_passes(self):
        self.wire()
        r = self.check()
        self.assertEqual(r.status, "PASS", r.items)
        self.assertIn("4 connection", r.detail)

    def test_two_signal_wires_swapped_fail_naming_them(self):
        self.wire([("3V3", "VCC"), ("GND", "GND"), ("GPIO4", "SCL"), ("GPIO5", "SDA")])
        r = self.check()
        self.assertEqual(r.status, "FAIL")
        text = "\n".join(r.items)
        self.assertIn("bme280.SCL, rp2040_pico.GPIO4", text)
        self.assertIn("Run the electrical step again", text)

    def test_a_wire_the_schematic_lacks_fails(self):
        self.wire(WIRES + [("GPIO6", "SDA")])
        r = self.check()
        self.assertEqual(r.status, "FAIL")
        self.assertIn("rp2040_pico.GPIO6 on no net", "\n".join(r.items))

    def test_a_wire_the_harness_lacks_fails(self):
        self.wire(WIRES[:3])
        r = self.check()
        self.assertEqual(r.status, "FAIL")
        self.assertIn("the harness does not", "\n".join(r.items))

    def test_nothing_to_compare_skips_never_passes(self):
        self.assertEqual(self.check().status, "SKIP")              # no harness
        self.wire()
        self.sch.unlink()
        self.assertEqual(self.check().status, "SKIP")              # no schematic
        self.sch.write_text("x", encoding="utf-8")
        self.script.write_text("from skidl import *\n", encoding="utf-8")
        r = self.check()
        self.assertEqual(r.status, "SKIP")                          # not drawn by Nemo
        self.assertIn("not drawn by Nemo", r.detail)

    def test_an_unreadable_netlist_skips(self):
        self.wire()
        with mock.patch("nemo.checks.netlist_groups", return_value=(None, "no kicad")):
            r = Pipeline.check_harness_netlist(self.harness, self.sch, self.script)
        self.assertEqual(r.status, "SKIP"); self.assertIn("no kicad", r.detail)


class TestTheWiringStepRunsIt(unittest.TestCase):
    def test_it_is_among_the_harness_checks(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "pipeline.py").read_text(encoding="utf-8")
        # The checks themselves are in nemo/checks/harness.py since 2026-10-20.
        seg = src[src.index("def _harness_results"):src.index("# The harness checks live in")]
        self.assertIn("check_harness_netlist", seg)

    def test_only_a_disagreement_sends_the_owner_back_to_electrical(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"electrical" if failed == {"harness_netlist"} else "wiring"', src)


def _real_tools() -> bool:
    import importlib.util
    return bool(runners._kicad()) and importlib.util.find_spec("skidl") is not None


@unittest.skipUnless(_real_tools(), "needs SKiDL and kicad-cli")
class TestWithRealSkidlAndKiCad(Case):
    """Run on the AH531 with SKiDL 2.3.0 and KiCad 10.0.6."""

    def test_drawn_and_read_back_agree_and_a_swap_is_caught(self):
        made = runners.generate_schematic(self.script, self.sch, timeout=900)
        self.assertTrue(made.ok, made.items)
        self.wire()
        r = Pipeline.check_harness_netlist(self.harness, self.sch, self.script)
        self.assertEqual(r.status, "PASS", (r.detail, r.items))
        self.wire([("3V3", "VCC"), ("GND", "GND"), ("GPIO4", "SCL"), ("GPIO5", "SDA")])
        r = Pipeline.check_harness_netlist(self.harness, self.sch, self.script)
        self.assertEqual(r.status, "FAIL")


if __name__ == "__main__":
    unittest.main()
