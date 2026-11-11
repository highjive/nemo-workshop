"""The schematic is written by code from the connections the model chose.

Twice on the real AH531 the electrical step asked the 1.7B model for a
SKiDL script and got Python importing names SKiDL does not have. Asked
only which pin goes to which pin, the same model answered correctly. A
schematic's nets ARE that answer, so schematic.py writes the SKiDL itself
and the model is not asked for any. The wiring step then reuses the same
connections, so the schematic and the harness describe one circuit.

The last class runs real SKiDL and real KiCad and is skipped without them.
"""
from __future__ import annotations

import importlib.util
import json, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, schematic
from nemo.checks import runners
from nemo.checks.deterministic import FAIL, PASS, Result
from test_gates_real import WeatherCase
from test_harness import SchemaRouter, good, real_reply
from test_pipeline import StubRouter


def rfid() -> dict:
    return {"cables": [{"from": "esp32_devkit_v1", "to": "rc522", "gauge_awg": 22,
                        "length_mm": 80, "wires": [
                            {"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
                            {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
                            {"from_pin": "GPIO19", "to_pin": "MISO", "colour": "blue"},
                            {"from_pin": "GPIO23", "to_pin": "MOSI", "colour": "green"},
                            {"from_pin": "GPIO18", "to_pin": "SCK", "colour": "yellow"},
                            {"from_pin": "GPIO5", "to_pin": "SDA", "colour": "white"}]}]}


class TestNets(WeatherCase):
    def test_pins_joined_by_wires_are_one_net_named_by_code(self):
        nets = schematic.nets(good(), self.parts)
        self.assertEqual(sorted(nets), ["+3V3", "GND", "GPIO21", "GPIO22"])
        self.assertEqual(sorted(nets["+3V3"]),
                         [("bme280", "VCC"), ("esp32_devkit_v1", "3V3"),
                          ("ssd1306_oled_096", "VCC")])
        self.assertEqual(sorted(nets["GPIO22"]),
                         [("bme280", "SCL"), ("esp32_devkit_v1", "GPIO22"),
                          ("ssd1306_oled_096", "SCL")])

    def test_a_net_that_never_reaches_the_microcontroller_is_named_after_a_pin(self):
        nets = schematic.nets(real_reply(), self.parts)
        self.assertIn("BME280_SCL", nets)
        self.assertEqual(sorted(nets["BME280_SCL"]),
                         [("bme280", "SCL"), ("ssd1306_oled_096", "SCL")])

    def test_the_supply_rail_is_named_from_the_voltage_not_by_the_model(self):
        self.assertEqual(schematic._rail_name(3.3), "+3V3")
        self.assertEqual(schematic._rail_name(5.0), "+5V")
        self.assertEqual(schematic._rail_name(3.7), "+3V7")
        self.assertEqual(schematic._volts_from_name("3V3"), 3.3)
        self.assertEqual(schematic._volts_from_name("5V"), 5.0)
        self.assertIsNone(schematic._volts_from_name("GPIO5"))

    def test_symbol_pin_numbers_follow_the_librarys_pin_order(self):
        numbers = schematic.pin_numbers(good(), self.parts)
        self.assertEqual(numbers["bme280"], ["VCC", "GND", "SCL", "SDA"])
        self.assertEqual(numbers["esp32_devkit_v1"][:4], ["3V3", "VIN", "GND", "GPIO4"])
        self.assertEqual(len(numbers["esp32_devkit_v1"]), 14)      # D144: the board's own list

    def test_a_part_that_is_not_in_the_brief_cannot_be_drawn(self):
        doc = good(); doc["cables"][0]["to"] = "rc522"
        with self.assertRaises(schematic.SchematicError):
            schematic.nets(doc, self.parts)


class TestScript(WeatherCase):
    def test_it_is_python_and_uses_only_the_skidl_that_was_proved(self):
        text = schematic.skidl_script(good(), self.parts)
        compile(text, "schematic.py", "exec")            # valid Python, at least
        calls = set(__import__("re").findall(r"\b([A-Za-z_]+)\(", text))
        self.assertLessEqual(calls, {"set_default_tool", "Net", "Part",
                                     "generate_netlist", "generate_schematic"})
        self.assertTrue(text.rstrip().endswith("generate_schematic()"))

    def test_every_net_is_a_label_not_a_routed_wire(self):
        # SKiDL's wire router raised RoutingFailure on this very circuit.
        text = schematic.skidl_script(good(), self.parts)
        self.assertEqual(text.count("stub=True"), 4)
        self.assertNotRegex(text, r'Net\("[^"]+"\)')

    def test_each_part_is_a_connector_with_one_pin_per_library_pin(self):
        text = schematic.skidl_script(good(), self.parts)
        self.assertIn('Part("Connector_Generic", "Conn_01x04", ref="J2", value="bme280")', text)
        self.assertIn("# J2 = bme280: 1=VCC, 2=GND, 3=SCL, 4=SDA", text)
        self.assertIn("n_gpio22 += j2[3]    # SCL", text)

    def test_supply_and_ground_each_get_a_power_flag(self):
        text = schematic.skidl_script(good(), self.parts)
        self.assertEqual(text.count('Part("power", "PWR_FLAG")'), 2)
        self.assertIn("n_3v3 += flag1[1]", text)
        self.assertIn("n_gnd += flag2[1]", text)

    def test_a_pin_the_design_does_not_use_is_marked_no_connect(self):
        parts = [self.lib.get("esp32_devkit_v1"), self.lib.get("rc522")]
        text = schematic.skidl_script(rfid(), parts)
        self.assertIn("j2[2] += NC    # RST: not used in this design", text)
        self.assertIn('"Conn_01x07"', text)

    def test_nothing_to_draw_is_refused(self):
        with self.assertRaises(schematic.SchematicError):
            schematic.skidl_script({"cables": []}, self.parts)


class TestElectricalStep(WeatherCase):
    def run_step(self, router, generated=None):
        gen = generated or Result("schematic", PASS, "generated project.kicad_sch")
        with mock.patch.object(checks, "generate_schematic", return_value=gen) as g, \
             mock.patch.object(checks, "erc", return_value=Result("erc", PASS, "clean")):
            sr = self.pipe(router).stage_electrical()
        return sr, g

    def test_the_model_is_asked_for_connections_and_never_for_skidl(self):
        r = SchemaRouter(good())
        sr, _ = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        self.assertIn("schema", r.asked[0])
        self.assertNotIn("SKiDL", r.asked[0]["system"])

    def test_the_script_on_disk_is_codes_and_the_connections_are_saved(self):
        self.run_step(SchemaRouter(good()))
        script = (self.project.root / "electrical" / "schematic.py").read_text(encoding="utf-8")
        self.assertEqual(script, schematic.skidl_script(good(), self.parts))
        self.assertEqual(json.loads(self.project.connections.read_text(encoding="utf-8")), good())

    def test_a_circuit_that_cannot_work_fails_here_before_any_drawing(self):
        sr, _ = self.run_step(SchemaRouter(real_reply()))
        self.assertFalse(sr.ok)
        # The display's power is wired by code now (D145); its data is not.
        # Said once for the design, not once a pin, since the model is no
        # longer asked for supply wires (D164).
        self.assertIn("Power and ground wired by Nemo from the parts library, each part to "
                      "esp32_devkit_v1: ssd1306_oled_096.VCC from 3V3; every ground to GND.",
                      sr.render())
        self.assertIn("bme280.SCL does not reach esp32_devkit_v1", sr.render())
        self.assertEqual(sr.go_back_to, "electrical")

    def test_a_faulty_first_answer_is_retried_with_its_faults(self):
        r = SchemaRouter(real_reply(), good())
        sr, _ = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 2)
        self.assertIn("the first attempt had 4 fault(s), the second has 0", sr.render())

    def test_a_schematic_that_will_not_generate_still_fails_the_step(self):
        bad = Result("schematic", FAIL, "the SKiDL script exited with an error (code 1)")
        sr, _ = self.run_step(SchemaRouter(good()), generated=bad)
        self.assertFalse(sr.ok)
        self.assertEqual(sr.go_back_to, "electrical")

    def test_a_router_that_cannot_constrain_still_gets_the_old_request(self):
        r = StubRouter('```python\nopen("project.kicad_sch", "w").write("(kicad_sch)")\n```')
        self.run_step(r)
        self.assertEqual(r.calls, ["cad_script"])
        self.assertFalse(self.project.connections.exists())


class TestWiringReusesThem(WeatherCase):
    def wiring(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_after_the_electrical_step_the_model_is_not_asked_again(self):
        self.project.connections.parent.mkdir(parents=True, exist_ok=True)
        self.project.connections.write_text(json.dumps(good()), encoding="utf-8")
        r = SchemaRouter(real_reply())                   # would be wrong if it were asked
        sr = self.wiring(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(r.asked, [])
        self.assertIn("connections chosen in the electrical step", sr.render())

    def test_the_schematic_and_the_harness_then_describe_the_same_circuit(self):
        import yaml
        from nemo.pipeline import Pipeline
        self.project.connections.parent.mkdir(parents=True, exist_ok=True)
        self.project.connections.write_text(json.dumps(good()), encoding="utf-8")
        self.wiring(SchemaRouter(good()))
        harness_doc = yaml.safe_load(self.project.harness.read_text(encoding="utf-8"))
        wires = {frozenset(pair) for pair in Pipeline._wire_pairs(harness_doc)}
        nets = schematic.nets(good(), self.parts)
        for pair in wires:
            a, b = tuple(pair)
            self.assertTrue(any(a in members and b in members for members in nets.values()),
                            f"{a} to {b} is in the harness and not in one net")

    def test_saved_connections_for_other_parts_are_ignored_not_trusted(self):
        doc = good(); doc["cables"][0]["to"] = "rc522"
        self.project.connections.parent.mkdir(parents=True, exist_ok=True)
        self.project.connections.write_text(json.dumps(doc), encoding="utf-8")
        r = SchemaRouter(good())
        self.assertTrue(self.wiring(r).ok)
        self.assertEqual(len(r.asked), 1)                # decided afresh

    def test_with_no_electrical_step_it_decides_them_itself(self):
        r = SchemaRouter(good())
        self.assertTrue(self.wiring(r).ok)
        self.assertEqual(len(r.asked), 1)


HAVE_REAL = importlib.util.find_spec("skidl") is not None and runners._skidl_env()[1] is not None


@unittest.skipUnless(HAVE_REAL, "needs SKiDL and KiCad's symbol libraries")
class TestAgainstRealSkidlAndKicad(WeatherCase):
    """Slow: about 40 s a circuit on the AH531."""

    def generate(self, doc, parts):
        work = self.tmp / "electrical"
        work.mkdir(parents=True, exist_ok=True)
        script, dest = work / "schematic.py", work / "project.kicad_sch"
        script.write_text(schematic.skidl_script(doc, parts), encoding="utf-8")
        g = checks.generate_schematic(script, dest)
        self.assertEqual(g.status, PASS, g.render())
        return dest

    def test_the_circuit_that_broke_skidls_router_generates_and_passes_erc(self):
        dest = self.generate(good(), self.parts)
        e = checks.erc(dest)
        self.assertEqual(e.status, PASS, e.render())
        named = {n for n in checks.netlist_nets(dest) if not n.startswith("unconnected")}
        self.assertEqual(named, {"+3V3", "GND", "GPIO21", "GPIO22"})

    def test_a_part_with_an_unused_pin_passes_erc_too(self):
        parts = [self.lib.get("esp32_devkit_v1"), self.lib.get("rc522")]
        dest = self.generate(rfid(), parts)
        e = checks.erc(dest)
        self.assertEqual(e.status, PASS, e.render())
        named = {n for n in checks.netlist_nets(dest) if not n.startswith("unconnected")}
        self.assertEqual(named, {"+3V3", "GND", "GPIO5", "GPIO18", "GPIO19", "GPIO23"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
