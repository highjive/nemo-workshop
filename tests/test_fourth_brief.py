"""D159-D161: the first real design with a servo and a relay.

Real run (AH531, qwen3-4b, Design mode, 2026-10-07), a lid opened by a
servo when a distance sensor sees a hand, with a relay for a fan. Every
check of every step passed. What the model answered, before code wired the
power:

  esp32 -> servo:  GND-GND, GPIO4-PWM (coloured red)
  esp32 -> sensor: VIN-VIN, GND-GND, GPIO18-SCL, GPIO19-SDA, GPIO21-XSHUT
  esp32 -> relay:  VIN-VCC, GND-GND, GPIO25-IN
  relay -> servo:  NO-VCC, COM-GND

D159. The relay's contacts were in the library as plain signal pins, so
they were offered to the model, which used them. Those two wires were set
aside only because their far ends were supply pins. The guide then said
nothing of the contacts, or of the fan the brief names and no part is.

D160. Servo, relay and sensor all take their 5 V from the board's VIN
pin: 730 mA at peak through one header pin. Nothing added that up.

D161. The servo's signal wire was red, beside the red 5 V wire in a
three-wire cable.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, harness
from nemo.checks.deterministic import PASS, Result
from nemo.parts import PartsLibrary
from nemo.pipeline import Pipeline, StageResult
from nemo.project import Brief
from test_gates_real import WeatherCase
from test_harness import SchemaRouter, good
from test_pipeline import PipelineCase, StubRouter

REFS = ("esp32_devkit_v1", "vl53l0x", "sg90_servo", "relay_5v_1ch")
BOARD = "esp32_devkit_v1"


def w(a, b, colour="blue"):
    return {"from_pin": a, "to_pin": b, "colour": colour}


def real_reply() -> dict:
    return {"cables": [
        {"from": BOARD, "to": "sg90_servo", "gauge_awg": 22, "length_mm": 100,
         "wires": [w("GND", "GND", "black"), w("GPIO4", "PWM", "red")]},
        {"from": BOARD, "to": "vl53l0x", "gauge_awg": 22, "length_mm": 150,
         "wires": [w("VIN", "VIN", "red"), w("GND", "GND", "black"), w("GPIO18", "SCL"),
                   w("GPIO19", "SDA"), w("GPIO21", "XSHUT")]},
        {"from": BOARD, "to": "relay_5v_1ch", "gauge_awg": 22, "length_mm": 100,
         "wires": [w("VIN", "VCC", "red"), w("GND", "GND", "black"), w("GPIO25", "IN")]},
        {"from": "relay_5v_1ch", "to": "sg90_servo", "gauge_awg": 22, "length_mm": 100,
         "wires": [w("NO", "VCC", "red"), w("COM", "GND", "black")]}]}


def wires(doc):
    return {(c["from"], x["from_pin"], c["to"], x["to_pin"]): x["colour"]
            for c in doc["cables"] for x in c["wires"]}


class LidCase(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="hand-lid", function="A lid that a servo opens when a hand comes near, "
            "with a relay that switches a fan.", power="USB 5 V 2 A", supply_ma=2000,
            rails=[5.0, 3.3], envelope_mm=[150, 100, 50], parts=list(REFS), mcu="esp32",
            done_when="The lid opens."))
        self.parts = [self.lib.get(r) for r in REFS]

    def path(self, doc):
        text, _ = harness.build(doc, self.parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        return self.project.harness

    def decided(self, doc):
        doc, _ = harness.without_contact_wires(doc, self.parts)
        doc, _ = harness.wire_power(doc, self.parts)
        return doc


# ----------------------------------------------------------------- D159
class TestARelaysSwitchedSideIsNotASignal(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()
        self.parts = [self.lib.get(r) for r in REFS]
        self.relay = self.lib.get("relay_5v_1ch")

    def test_the_library_says_which_pins_they_are(self):
        self.assertEqual(harness.contact_pins(self.relay), ["NO", "NC", "COM"])
        self.assertEqual([p.ref for p in self.lib.parts.values() if harness.contact_pins(p)],
                         ["relay_5v_1ch"])

    def test_the_coil_side_is_as_it_was(self):
        self.assertEqual([(p.name, p.function) for p in self.relay.pins[:3]],
                         [("VCC", "power"), ("GND", "gnd"), ("IN", "io")])

    def test_they_are_not_in_what_the_model_may_choose(self):
        schema = harness.harness_schema(self.parts)
        for pair in schema["properties"]["cables"]["items"]["anyOf"]:
            for end, key in (("from", "from_pin"), ("to", "to_pin")):
                if pair["properties"][end]["const"] == "relay_5v_1ch":
                    self.assertEqual(
                        pair["properties"]["wires"]["items"]["properties"][key]["enum"],
                        ["VCC", "GND", "IN"])

    def test_nor_in_what_it_is_told(self):
        line = [x for x in harness.part_facts(self.parts).split("\n") if "relay_5v_1ch" in x][0]
        self.assertTrue(line.endswith(": VCC, GND, IN"), line)

    def test_the_real_answers_two_wires_are_set_aside_and_named(self):
        doc, notes = harness.without_contact_wires(real_reply(), self.parts)
        self.assertEqual(len(doc["cables"]), 3)
        self.assertEqual(notes, ["Set aside 2 wire(s) the model ran to a relay's switched side: "
                                 "relay_5v_1ch.NO to sg90_servo.VCC; relay_5v_1ch.COM to "
                                 "sg90_servo.GND. Nemo does not wire that side."])

    def test_a_contact_run_to_a_gpio_is_set_aside_too(self):
        # The case nothing caught before: neither end is a supply pin.
        doc = real_reply()
        doc["cables"][2]["wires"].append(w("GPIO26", "COM"))
        out, notes = harness.without_contact_wires(doc, self.parts)
        self.assertNotIn((BOARD, "GPIO26", "relay_5v_1ch", "COM"), wires(out))
        self.assertIn("esp32_devkit_v1.GPIO26 to relay_5v_1ch.COM", notes[0])
        self.assertIn((BOARD, "GPIO25", "relay_5v_1ch", "IN"), wires(out))

    def test_any_case_of_the_name_and_either_end(self):
        doc = {"cables": [{"from": "relay_5v_1ch", "to": BOARD, "gauge_awg": 22,
                           "length_mm": 50, "wires": [w("nc", "GPIO27"), w("IN", "GPIO25")]}]}
        out, notes = harness.without_contact_wires(doc, self.parts)
        self.assertEqual(list(wires(out)), [("relay_5v_1ch", "IN", BOARD, "GPIO25")])
        self.assertEqual(len(notes), 1)

    def test_a_design_with_no_relay_is_returned_as_it_came(self):
        parts = [self.lib.get(r) for r in ("esp32_devkit_v1", "bme280", "ssd1306_oled_096")]
        self.assertEqual(harness.without_contact_wires(good(), parts), (good(), []))


class TestTheStepAndTheGuideForTheRelay(LidCase):
    def run_step(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_the_real_answer_passes_at_the_first_asking_and_says_what_was_dropped(self):
        r = SchemaRouter(real_reply())
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        self.assertIn("ran to a relay's switched side", sr.render())
        self.assertNotIn("COM", r.asked[0]["user"])

    def test_the_guide_says_the_switched_side_is_nobodys(self):
        self.pipe(StubRouter()).stage_pack([])
        text = self.project.build_md.read_text(encoding="utf-8")
        self.assertIn("- [electrical] not wired by Nemo: relay_5v_1ch NO, NC, COM, its switched "
                      "side. What it switches is not in the parts list, its current is not in "
                      "the power budget, and no check here has looked at it",
                      text[text.index("## Open questions"):])


class TestAGuideWithNoRelay(WeatherCase):
    def test_gains_no_such_line(self):
        self.pipe(StubRouter()).stage_pack([])
        self.assertNotIn("switched side", self.project.build_md.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- D160
class TestWhatABoardPinCarries(LidCase):
    def test_the_real_design_has_its_sum_and_a_question(self):
        r = Pipeline.check_pin_current(self.path(self.decided(real_reply())), self.parts)
        self.assertEqual(r.status, PASS)
        self.assertEqual(r.detail, "at peak: esp32_devkit_v1.VIN 730 mA; 1 to confirm")
        self.assertEqual(r.items, [
            "esp32_devkit_v1.VIN carries 730 mA at peak (relay_5v_1ch 190, sg90_servo 500, "
            "vl53l0x 40) and the library records no limit for that pin. relay_5v_1ch, "
            "sg90_servo draw in surges: confirm the pin and the board's own supply path can "
            "carry it, or feed them straight from the supply"])

    def test_the_figures_are_the_librarys_peaks(self):
        self.assertEqual([self.lib.get(r).draw_ma for r in REFS[1:]], [40, 500, 190])

    def test_it_never_fails_because_no_limit_is_recorded(self):
        from nemo.parts import Pin
        self.assertNotIn("max_ma", Pin.__dataclass_fields__)
        for p in self.lib.parts.values():
            if p.category == "mcu":
                self.assertFalse(any(hasattr(x, "max_ma") for x in p.pins))

    def test_it_is_one_of_the_checks_on_the_connections(self):
        found = self.pipe(StubRouter())._connection_results(self.decided(real_reply()),
                                                            self.parts)
        self.assertEqual(found[-1].name, "pin_current")

    def test_the_question_reaches_the_guide(self):
        r = Pipeline.check_pin_current(self.path(self.decided(real_reply())), self.parts)
        self.pipe(StubRouter()).stage_pack([StageResult("electrical", True, [r])])
        text = self.project.build_md.read_text(encoding="utf-8")
        self.assertIn("- [electrical] confirm: esp32_devkit_v1.VIN carries 730 mA at peak",
                      text[text.index("## Open questions"):])

    def test_nothing_to_check_is_a_skip(self):
        missing = self.project.root / "none.yaml"
        self.assertEqual(Pipeline.check_pin_current(missing, self.parts).status, checks.SKIP)

    def test_it_has_a_plain_name_for_the_window(self):
        from nemo.gui import controller as C
        names = [v for v in vars(C).values() if isinstance(v, dict) and "harness_pins" in v][0]
        self.assertEqual(names["pin_current"], "Current through each supply pin of the board")


class TestSensorsOnAPinAreSummedAndNotAsked(WeatherCase):
    def test_two_small_parts_on_3v3(self):
        doc, _ = harness.wire_power(good(), self.parts)
        text, _ = harness.build(doc, self.parts)
        r = Pipeline.check_pin_current(self.harness(text), self.parts)
        self.assertEqual((r.status, r.items), (PASS, []))
        self.assertRegex(r.detail, r"^at peak: esp32_devkit_v1\.3V3 \d+ mA$")


# ----------------------------------------------------------------- D161
class TestASignalWireIsNotInASupplyColour(LidCase):
    def test_the_real_answers_red_signal_wire_is_given_another_colour(self):
        doc, notes = harness.recolour_signals(self.decided(real_reply()), self.parts)
        got = wires(doc)
        self.assertEqual(got[(BOARD, "GPIO4", "sg90_servo", "PWM")], "yellow")
        self.assertEqual(notes, ["The signal wire from esp32_devkit_v1.GPIO4 to sg90_servo.PWM "
                                 "was red, a supply colour, so Nemo made it yellow."])

    def test_supply_and_ground_keep_theirs(self):
        got = wires(harness.recolour_signals(self.decided(real_reply()), self.parts)[0])
        self.assertEqual(got[(BOARD, "VIN", "sg90_servo", "VCC")], "red")
        self.assertEqual(got[(BOARD, "GND", "sg90_servo", "GND")], "black")
        self.assertEqual(got[(BOARD, "VIN", "relay_5v_1ch", "VCC")], "red")

    def test_black_is_changed_as_red_is_and_two_get_two_colours(self):
        doc = {"cables": [{"from": BOARD, "to": "vl53l0x", "gauge_awg": 22, "length_mm": 80,
                           "wires": [w("GPIO18", "SCL", "black"), w("GPIO19", "SDA", "red"),
                                     w("GPIO21", "XSHUT", "yellow")]}]}
        out, notes = harness.recolour_signals(doc, self.parts)
        self.assertEqual([x["colour"] for x in out["cables"][0]["wires"]],
                         ["green", "blue", "yellow"])
        self.assertEqual(len(notes), 2)

    def test_a_cable_using_every_colour_still_gets_one_that_is_not_a_supplys(self):
        spare = [c for c in harness.COLOURS if c not in ("red", "black")]
        doc = {"cables": [{"from": BOARD, "to": "vl53l0x", "gauge_awg": 22, "length_mm": 80,
                           "wires": [w("GPIO18", "SCL", "red")]
                           + [w(f"GPIO{n}", "SDA", c) for n, c in zip((19, 21, 22, 23, 25, 26),
                                                                      spare)]}]}
        out, _ = harness.recolour_signals(doc, self.parts)
        self.assertIn(out["cables"][0]["wires"][0]["colour"], spare)

    def test_a_design_with_none_is_returned_as_it_came(self):
        parts = [self.lib.get(r) for r in ("esp32_devkit_v1", "bme280", "ssd1306_oled_096")]
        doc, _ = harness.wire_power(good(), parts)
        out, notes = harness.recolour_signals(doc, parts)
        self.assertEqual((out, notes), (doc, []))

    def test_the_step_does_it_and_says_so(self):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            sr = self.pipe(SchemaRouter(real_reply())).stage_wiring()
        self.assertIn("was red, a supply colour, so Nemo made it yellow", sr.render())
        import yaml
        drawn = yaml.safe_load(self.project.harness.read_text(encoding="utf-8"))
        servo = next(c for c in drawn["connections"] if "sg90_servo" in c[2])
        self.assertEqual(servo[2]["sg90_servo"], ["VCC", "GND", "PWM"])
        self.assertEqual(drawn["cables"][next(iter(servo[1]))]["colors"], ["RD", "BK", "YE"])


if __name__ == "__main__":
    unittest.main()
