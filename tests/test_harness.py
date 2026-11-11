"""The wiring harness: the model chooses connections, code writes the file.

On the first real run (AH531, qwen3-1.7b) the wiring step asked the model
for a whole WireViz document and got one for a different project, under a
key WireViz does not read, joining connectors it had not defined. Every
one of those mistakes was in something a model should never have been
asked to produce. harness.py asks it only which pin goes to which pin, as
JSON held to a schema built from the brief's own parts, and writes the
WireViz file itself.
"""
from __future__ import annotations

import json, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

import yaml

from nemo import checks, harness
from nemo import router as router_mod
from nemo.checks.deterministic import PASS, Result
from nemo.config import Config
from nemo.pipeline import Pipeline
from nemo.router import Reply, Router
from test_gates_real import REAL_BAD_HARNESS, WeatherCase
from test_pipeline import StubRouter


def good() -> dict:
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "bme280", "gauge_awg": 26, "length_mm": 80, "wires": [
            {"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
            {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
            {"from_pin": "GPIO22", "to_pin": "SCL", "colour": "yellow"},
            {"from_pin": "GPIO21", "to_pin": "SDA", "colour": "green"}]},
        {"from": "esp32_devkit_v1", "to": "ssd1306_oled_096", "gauge_awg": 22, "length_mm": 60,
         "wires": [{"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
                   {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
                   {"from_pin": "GPIO22", "to_pin": "SCL", "colour": "yellow"},
                   {"from_pin": "GPIO21", "to_pin": "SDA", "colour": "green"}]}]}


class SchemaRouter:
    """A router that can constrain a reply, and records how it was asked."""
    supports_schema = True
    timeout = 1800

    def __init__(self, *replies):
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        self.asked = []

    def ask(self, task, system, user, **kw):
        self.asked.append({"task": task, "system": system, "user": user, **kw})
        # The last reply repeats, like a model that will not change its mind.
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return Reply(text, "local", "stub")

    def local_up(self):
        return True


class TestSchema(WeatherCase):
    def variants(self):
        return harness.harness_schema(self.parts)["properties"]["cables"]["items"]["anyOf"]

    def test_only_this_projects_parts_can_be_named(self):
        ends = {(v["properties"]["from"]["const"], v["properties"]["to"]["const"])
                for v in self.variants()}
        refs = {"esp32_devkit_v1", "bme280", "ssd1306_oled_096"}
        self.assertEqual(ends, {(a, b) for a in refs for b in refs if a != b})
        self.assertNotIn("rc522", json.dumps(harness.harness_schema(self.parts)))

    def test_a_wires_pins_are_limited_to_the_part_at_that_end(self):
        v = next(x for x in self.variants()
                 if (x["properties"]["from"]["const"], x["properties"]["to"]["const"])
                 == ("bme280", "ssd1306_oled_096"))
        wire = v["properties"]["wires"]["items"]["properties"]
        self.assertEqual(wire["from_pin"], {"enum": ["VCC", "GND", "SCL", "SDA"]})
        self.assertEqual(wire["to_pin"], {"enum": ["VCC", "GND", "SCL", "SDA"]})

    def test_the_board_takes_only_the_pins_the_library_lists_for_it(self):
        # D135: it took any short name, and the 4B model wrote SCL and SDA.
        # D144: it took any GPIO number, and the 1.7B model used GPIO0.
        v = next(x for x in self.variants() if x["properties"]["from"]["const"] == "esp32_devkit_v1")
        pin = v["properties"]["wires"]["items"]["properties"]["from_pin"]
        self.assertEqual(pin, {"enum": ["3V3", "VIN", "GND", "GPIO4", "GPIO18", "GPIO19", "GPIO21", "GPIO22", "GPIO23",
                                    "GPIO25", "GPIO26", "GPIO27", "GPIO32", "GPIO33"]})

    def test_a_board_with_no_pin_list_takes_a_power_name_or_a_gpio_number_only(self):
        from nemo.parts import PartsLibrary
        bare = PartsLibrary.load().get("waveshare_esp32s3_lcd_128")
        self.assertEqual(bare.pins, [])
        self.assertEqual(harness._pin_schema(bare),
                         {"type": "string", "pattern": harness.MCU_PIN})

    def test_nothing_extra_can_be_added_anywhere(self):
        s = harness.harness_schema(self.parts)
        self.assertIs(s["additionalProperties"], False)
        for v in self.variants():
            self.assertIs(v["additionalProperties"], False)
            self.assertIs(v["properties"]["wires"]["items"]["additionalProperties"], False)

    def test_the_facts_given_to_the_model_name_every_part_and_its_pins(self):
        facts = harness.part_facts(self.parts)
        self.assertIn("- bme280 (", facts); self.assertIn("VCC, GND, SCL, SDA", facts)
        self.assertIn("- esp32_devkit_v1 (ESP32 DevKit v1 (30-pin)): 3V3, VIN, GND, GPIO4,", facts)


class TestBuild(WeatherCase):
    def write(self, doc):
        text, notes = harness.build(doc, self.parts)
        return self.harness(text), yaml.safe_load(text), notes

    def test_a_cable_list_becomes_a_harness_every_check_accepts(self):
        path, doc, notes = self.write(good())
        self.assertEqual(sorted(doc), ["cables", "connections", "connectors"])
        self.assertEqual(Pipeline.check_harness_pins(path, self.parts).status, PASS)
        covers = Pipeline.check_harness_covers(path, self.parts)
        self.assertEqual(covers.status, PASS, covers.render())
        self.assertEqual(checks.check_wire_gauges(Pipeline._harness_runs(path, self.parts)).status, PASS)

    def test_connectors_carry_the_librarys_pin_list_not_the_models(self):
        _, doc, _ = self.write(good())
        self.assertEqual(doc["connectors"]["bme280"]["pinlabels"], ["VCC", "GND", "SCL", "SDA"])
        # The board too, since D144 gave it one.
        self.assertEqual(doc["connectors"]["esp32_devkit_v1"]["pinlabels"],
                         ["3V3", "VIN", "GND", "GPIO4", "GPIO18", "GPIO19", "GPIO21", "GPIO22", "GPIO23",
                          "GPIO25", "GPIO26", "GPIO27", "GPIO32", "GPIO33"])

    def test_a_cable_carrying_power_is_made_22_awg_whatever_was_asked(self):
        _, doc, notes = self.write(good())
        self.assertEqual(doc["cables"]["W1"]["gauge"], "22 AWG")        # asked for 26
        self.assertTrue(any("22 AWG instead of 26" in n for n in notes))

    def test_a_signal_only_cable_keeps_its_thinner_gauge(self):
        doc = {"cables": [{"from": "bme280", "to": "ssd1306_oled_096", "gauge_awg": 26,
                           "length_mm": 50, "wires": [
                               {"from_pin": "SCL", "to_pin": "SCL", "colour": "yellow"},
                               {"from_pin": "SDA", "to_pin": "SDA", "colour": "green"}]}]}
        text, notes = harness.build(doc, self.parts)
        self.assertEqual(yaml.safe_load(text)["cables"]["W1"]["gauge"], "26 AWG")
        self.assertFalse(any("22 AWG instead" in n for n in notes))

    def test_lengths_are_metres_and_colours_are_wirevizs_codes(self):
        _, doc, _ = self.write(good())
        self.assertEqual(doc["cables"]["W1"]["length"], 0.08)
        self.assertEqual(doc["cables"]["W1"]["colors"], ["RD", "BK", "YE", "GN"])

    def test_a_part_left_off_every_cable_is_noted_and_then_fails_the_gate(self):
        doc = good(); doc["cables"].pop()
        path, _, notes = self.write(doc)
        self.assertIn("ssd1306_oled_096 is not on any cable", notes)
        self.assertEqual(Pipeline.check_harness_covers(path, self.parts).status, "FAIL")

    def refuse(self, doc, *words):
        with self.assertRaises(harness.HarnessError) as ctx:
            harness.build(doc, self.parts)
        for w in words:
            self.assertIn(w, str(ctx.exception))

    def test_a_part_that_is_not_in_the_brief_is_refused_by_name(self):
        doc = good(); doc["cables"][0]["to"] = "rc522"
        self.refuse(doc, "'rc522'", "not a part in the brief", "bme280")

    def test_a_pin_the_part_does_not_have_is_refused_with_the_real_ones(self):
        doc = good(); doc["cables"][0]["wires"][2]["to_pin"] = "MISO"
        self.refuse(doc, "bme280 has no pin 'MISO'", "VCC, GND, SCL, SDA")

    def test_other_shapes_that_are_not_a_harness(self):
        self.refuse({}, "lists no cables")
        self.refuse({"cables": []}, "lists no cables")
        doc = good(); doc["cables"][0]["to"] = "esp32_devkit_v1"
        self.refuse(doc, "to itself")
        doc = good(); doc["cables"][0]["wires"] = []
        self.refuse(doc, "has no wires")
        doc = good(); doc["cables"][0]["wires"][0]["from_pin"] = "rm -rf / ; drop"
        self.refuse(doc, "esp32_devkit_v1 has no pin 'rm -rf / ; drop'")

    def test_a_missing_gauge_or_length_gets_a_stated_default(self):
        doc = good()
        # A value that cannot be used is said; a key that is simply absent is
        # not, since the model is no longer asked for either (D164).
        doc["cables"][1]["gauge_awg"] = 99; doc["cables"][1]["length_mm"] = "long"
        _, out, notes = self.write(doc)
        self.assertEqual(out["cables"]["W2"]["gauge"], "22 AWG")
        self.assertEqual(out["cables"]["W2"]["length"], 0.1)
        self.assertEqual(sum("cable 2" in n for n in notes), 2)


def real_reply() -> dict:
    """What qwen3-1.7b returned on the AH531 under the schema, 2026-10-05.
    Only real parts, only real pins, valid in every way the schema can see.
    The display has no power and the bus never reaches the ESP32."""
    return {"cables": [
        {"from": "esp32_devkit_v1", "to": "bme280", "gauge_awg": 22, "length_mm": 100, "wires": [
            {"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
            {"from_pin": "GND", "to_pin": "GND", "colour": "black"}]},
        {"from": "bme280", "to": "ssd1306_oled_096", "gauge_awg": 24, "length_mm": 80, "wires": [
            {"from_pin": "SDA", "to_pin": "SDA", "colour": "blue"},
            {"from_pin": "SCL", "to_pin": "SCL", "colour": "blue"}]}]}


class TestElectrical(WeatherCase):
    """D130: a harness can name only real pins and still not be a circuit."""

    def check(self, doc):
        text, _ = harness.build(doc, self.parts)
        return Pipeline.check_harness_electrical(self.harness(text), self.parts)

    def test_the_real_reply_passed_every_older_check(self):
        text, _ = harness.build(real_reply(), self.parts)
        path = self.harness(text)
        self.assertEqual(Pipeline.check_harness_pins(path, self.parts).status, PASS)
        self.assertEqual(Pipeline.check_harness_covers(path, self.parts).status, PASS)

    def test_and_fails_this_one_naming_each_pin(self):
        r = self.check(real_reply())
        self.assertEqual(r.status, "FAIL")
        text = r.render()
        self.assertIn("ssd1306_oled_096.VCC is not connected: the part has no supply", text)
        self.assertIn("ssd1306_oled_096.GND is not connected: the part has no ground", text)
        self.assertIn("bme280.SDA does not reach esp32_devkit_v1", text)
        self.assertIn("ssd1306_oled_096.SCL does not reach esp32_devkit_v1", text)
        self.assertNotIn("bme280.VCC", text)             # that one is wired properly
        self.assertEqual(len(r.items), 6)

    def test_a_complete_harness_passes(self):
        r = self.check(good())
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn("2 part(s)", r.detail)             # the dev board has no pin list

    def test_power_passed_on_from_one_module_to_the_next_counts(self):
        # Daisy-chained supply and bus: every net still leads to the ESP32.
        doc = {"cables": [
            {"from": "esp32_devkit_v1", "to": "bme280", "gauge_awg": 22, "length_mm": 80, "wires": [
                {"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
                {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
                {"from_pin": "GPIO22", "to_pin": "SCL", "colour": "yellow"},
                {"from_pin": "GPIO21", "to_pin": "SDA", "colour": "green"}]},
            {"from": "bme280", "to": "ssd1306_oled_096", "gauge_awg": 22, "length_mm": 60, "wires": [
                {"from_pin": "VCC", "to_pin": "VCC", "colour": "red"},
                {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
                {"from_pin": "SCL", "to_pin": "SCL", "colour": "yellow"},
                {"from_pin": "SDA", "to_pin": "SDA", "colour": "green"}]}]}
        self.assertEqual(self.check(doc).status, PASS)

    def test_power_joined_only_between_two_loads_is_caught(self):
        doc = good()
        doc["cables"] = [{"from": "bme280", "to": "ssd1306_oled_096", "gauge_awg": 22,
                          "length_mm": 60, "wires": [
                              {"from_pin": "VCC", "to_pin": "VCC", "colour": "red"}]}]
        text = self.check(doc).render()
        self.assertIn("bme280.VCC is joined only to ssd1306_oled_096", text)
        self.assertIn("no wire brings it a supply from esp32_devkit_v1", text)

    def test_nothing_to_check_is_a_skip_not_a_pass(self):
        self.assertEqual(Pipeline.check_harness_electrical(self.project.harness, self.parts).status,
                         checks.SKIP)

    def test_it_has_a_plain_name_for_the_interface(self):
        from nemo.gui import controller as C
        names = [v for v in vars(C).values() if isinstance(v, dict) and "harness_pins" in v][0]
        self.assertEqual(names["harness_electrical"], "Every part has power and data")


class TestWiringRetry(WeatherCase):
    def run_step(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_a_faulty_harness_is_sent_back_once_with_its_faults(self):
        r = SchemaRouter(real_reply(), good())
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 2)
        second = r.asked[1]["user"]
        self.assertIn("Your last wiring had these faults", second)
        # D145: the display's missing power is no longer sent back. Code wires
        # power and ground itself; the data lines are still the model's to fix.
        self.assertNotIn("ssd1306_oled_096.VCC is not connected", second)
        self.assertIn("bme280.SCL does not reach esp32_devkit_v1", second)
        self.assertIn("the first attempt had 4 fault(s), the second has 0", sr.render())
        doc = yaml.safe_load(self.project.harness.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["connections"][1]["ssd1306_oled_096"]
                             if "ssd1306_oled_096" in doc["connections"][1] else
                             doc["connections"][1][2]["ssd1306_oled_096"]), 4)

    def test_a_good_first_harness_costs_one_call(self):
        r = SchemaRouter(good())
        self.assertTrue(self.run_step(r).ok)
        self.assertEqual(len(r.asked), 1)

    def test_a_second_attempt_that_is_no_better_keeps_the_first_and_fails(self):
        r = SchemaRouter(real_reply())                   # the same answer both times
        sr = self.run_step(r)
        self.assertFalse(sr.ok)
        self.assertEqual(len(r.asked), 2)                # and no third
        self.assertIn("no better, so the first is kept", sr.render())
        self.assertEqual(sr.go_back_to, "wiring")

    def test_a_second_attempt_that_is_no_better_does_not_replace_the_file(self):
        # Was "drops the only power cable": power is code's since D145, so a
        # second answer can no longer be worse that way. Its data lines can.
        other = {"cables": [real_reply()["cables"][1]]}
        other["cables"][0]["wires"] = other["cables"][0]["wires"][:1]
        sr = self.run_step(SchemaRouter(real_reply(), other))
        self.assertFalse(sr.ok)
        first, _ = harness.build(harness.wire_power(real_reply(), self.parts)[0], self.parts)
        self.assertEqual(self.project.harness.read_text(encoding="utf-8"), first)

    def test_an_unusable_second_attempt_keeps_the_first(self):
        sr = self.run_step(SchemaRouter(real_reply(), "I give up."))
        self.assertFalse(sr.ok)
        self.assertTrue(self.project.harness.exists())
        self.assertIn("second attempt could not be used", sr.render())


class TestParseReply(unittest.TestCase):
    def test_bare_fenced_and_wrapped_in_prose(self):
        body = json.dumps(good())
        for text in (body, f"```json\n{body}\n```", f"Here you go:\n{body}\nHope that helps."):
            self.assertEqual(harness.parse_reply(text), good())

    def test_what_is_not_json_says_so(self):
        for text, word in (("I cannot do that.", "no JSON object"),
                           ('{"cables": [', "no JSON object"),
                           ('{"cables": [}', "not valid JSON"),
                           (REAL_BAD_HARNESS, "no JSON object")):
            with self.assertRaises(harness.HarnessError) as ctx:
                harness.parse_reply(text)
            self.assertIn(word, str(ctx.exception), text[:20])


class TestWiringStep(WeatherCase):
    def run_step(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_the_model_is_asked_for_json_under_this_projects_schema(self):
        r = SchemaRouter(good())
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        asked = r.asked[0]
        self.assertEqual(asked["schema"], harness.pin_choice_schema(self.parts))   # D164, D171
        self.assertIn("one JSON object", asked["system"])
        self.assertIn("- bme280 (", asked["user"])
        self.assertLessEqual(asked["max_tokens"], 1200)   # a cable list is short

    def test_the_file_on_disk_is_the_one_code_wrote(self):
        self.run_step(SchemaRouter(good()))
        doc = yaml.safe_load(self.project.harness.read_text(encoding="utf-8"))
        self.assertEqual(sorted(doc), ["cables", "connections", "connectors"])
        self.assertEqual(len(doc["connections"]), 2)

    def test_what_code_decided_is_told_to_the_owner(self):
        sr = self.run_step(SchemaRouter(good()))
        self.assertIn("22 AWG instead of 26", sr.render())

    def test_a_reply_that_cannot_be_used_fails_with_the_reason_and_is_kept(self):
        bad = good(); bad["cables"][0]["to"] = "rc522"
        sr = self.run_step(SchemaRouter(bad))
        self.assertFalse(sr.ok)
        self.assertIn("'rc522', which is not a part in the brief", sr.render())
        self.assertEqual(sr.go_back_to, "wiring")
        self.assertFalse(self.project.harness.exists())         # nothing half-written
        self.assertIn("rc522", self.project.harness.with_name("connections.raw.txt")
                      .read_text(encoding="utf-8"))

    def test_the_real_reply_from_the_laptop_can_no_longer_pass(self):
        sr = self.run_step(SchemaRouter(REAL_BAD_HARNESS))
        self.assertFalse(sr.ok)
        self.assertIn("no JSON object", sr.render())

    def test_a_router_that_cannot_constrain_gets_the_old_request(self):
        r = StubRouter("```yaml\nconnectors: {}\n```")
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            self.pipe(r).stage_wiring()
        self.assertEqual(r.calls, ["template_fill"])
        self.assertIn("connectors", self.project.harness.read_text(encoding="utf-8"))

    def test_the_owner_can_switch_it_off(self):
        self.cfg.data["engine"]["constrain_output"] = False
        r = SchemaRouter("```yaml\nconnectors: {}\n```")
        self.run_step(r)
        self.assertNotIn("schema", r.asked[0])
        self.assertIn("WireViz", r.asked[0]["system"])

    def test_a_failed_harness_is_this_steps_to_redo(self):
        doc = good(); doc["cables"].pop()
        sr = self.run_step(SchemaRouter(doc))
        self.assertFalse(sr.ok)
        self.assertEqual(sr.go_back_to, "wiring")


class TestRouterPassesTheSchema(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load(Path("/nonexistent"))
        self.bodies = []
        p = mock.patch.object(router_mod, "_post", lambda url, payload, key, timeout:
                              (self.bodies.append((url, payload)),
                               {"choices": [{"message": {"content": "{}"}}]})[1])
        p.start(); self.addCleanup(p.stop)

    def test_it_reaches_the_server_as_a_response_format(self):
        schema = {"type": "object"}
        Router(self.cfg).ask("template_fill", "s", "u", schema=schema, max_tokens=900)
        url, body = self.bodies[0]
        self.assertEqual(body["response_format"],
                         {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}})
        self.assertEqual(body["max_tokens"], 900)
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})

    def test_a_schemad_request_stays_on_this_machine_whatever_its_route(self):
        self.cfg.data["routing"]["template_fill"] = "remote"
        self.cfg.data["engine"]["review"] = "somewhere/some-model"
        Router(self.cfg).ask("template_fill", "s", "u", schema={"type": "object"})
        self.assertEqual(len(self.bodies), 1)
        self.assertTrue(self.bodies[0][0].startswith(self.cfg.get("engine.local")))

    def test_no_schema_no_response_format(self):
        Router(self.cfg).ask("story", "s", "u")
        self.assertNotIn("response_format", self.bodies[0][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
