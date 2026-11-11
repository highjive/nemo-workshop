"""D137-D140: what the second brief put to the real model showed.

Every earlier real run used one brief: three parts on one I2C bus. On
2026-10-06 a different one went through the whole pipeline on the AH531
with qwen3-1.7b: an RFID tag player (ESP32, RC522 on SPI, a serial MP3
module, a panel speaker). Every step passed, in 15 minutes, and the
design was wrong:

  esp32 -> rc522:      VIN-VCC, GND-GND, GPIO21-SDA, GPIO19-SCK, GPIO18-MOSI, GPIO17-MISO
  rc522 -> dfplayer:   VCC-VCC, GND-GND, SDA-RX, SCK-TX
  dfplayer -> speaker: SPK_1-speaker_8ohm, SPK_2-GND
  speaker -> esp32:    speaker_8ohm-GPIO26

One GPIO for two signals, twice; a 3.3 V part on the 5 V pin; an amplifier
output on a GPIO through pin names the model made up; and a constraint in
the brief that nothing read, in a guide that said "None recorded".
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
from test_harness import SchemaRouter, good
from test_gates_real import WeatherCase
from test_pipeline import PipelineCase, StubRouter

REFS = ("esp32_devkit_v1", "rc522", "dfplayer_mini", "speaker_8ohm_20mm")
MAGNET = "Keep the speaker magnet at least 25 mm from the tag reader."


def wires(*pairs):
    return [{"from_pin": a, "to_pin": b, "colour": "white"} for a, b in pairs]


def cable(a, b, *pairs):
    return {"from": a, "to": b, "gauge_awg": 22, "length_mm": 80, "wires": wires(*pairs)}


def real_reply(speaker=("SPK_A", "SPK_B")) -> dict:
    """The model's wiring. The speaker's two pin names are the library's
    (it had none then); pass the model's own to see those. Its GPIO17 is
    GPIO23 here: 17 is not a pin the board offers since D144."""
    one, two = speaker
    return {"cables": [
        cable("esp32_devkit_v1", "rc522", ("VIN", "VCC"), ("GND", "GND"), ("GPIO21", "SDA"),
              ("GPIO19", "SCK"), ("GPIO18", "MOSI"), ("GPIO23", "MISO")),
        cable("rc522", "dfplayer_mini", ("VCC", "VCC"), ("GND", "GND"), ("SDA", "RX"),
              ("SCK", "TX")),
        cable("dfplayer_mini", "speaker_8ohm_20mm", ("SPK_1", one), ("SPK_2", two)),
        cable("speaker_8ohm_20mm", "esp32_devkit_v1", (one, "GPIO26"))]}


def sound_reply() -> dict:
    """The same project wired so that it could work."""
    return {"cables": [
        cable("esp32_devkit_v1", "rc522", ("3V3", "VCC"), ("GND", "GND"), ("GPIO4", "SDA"),
              ("GPIO18", "SCK"), ("GPIO23", "MOSI"), ("GPIO19", "MISO"), ("GPIO22", "RST")),
        cable("esp32_devkit_v1", "dfplayer_mini", ("VIN", "VCC"), ("GND", "GND"),
              ("GPIO26", "RX"), ("GPIO27", "TX")),
        cable("dfplayer_mini", "speaker_8ohm_20mm", ("SPK_1", "SPK_A"), ("SPK_2", "SPK_B"))]}


class TagCase(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="tag-player", function="Plays a sound track when a tag is held near it.",
            power="USB 5 V 1 A", supply_ma=1000, rails=[5.0, 3.3], envelope_mm=[120, 80, 40],
            parts=list(REFS), mcu="esp32", done_when="A tag plays its track.",
            constraints=["The speaker faces out through the front panel.", MAGNET]))
        self.parts = [self.lib.get(r) for r in REFS]

    def path(self, doc):
        text, _ = harness.build(doc, self.parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        return self.project.harness


class TestItPassedEverythingThereWas(TagCase):
    def test_pins_cover_and_power_all_passed(self):
        p = self.path(real_reply())
        for check in (Pipeline.check_harness_pins, Pipeline.check_harness_covers,
                      Pipeline.check_harness_electrical):
            self.assertEqual(check(p, self.parts).status, PASS, check.__name__)


class TestOnePinTwoSignals(TagCase):
    """D137."""

    def result(self, doc):
        return Pipeline.check_harness_signals(self.path(doc), self.parts)

    def test_the_real_wiring_fails_naming_each_shared_pin(self):
        r = self.result(real_reply())
        self.assertEqual(r.status, "FAIL")
        text = r.render()
        self.assertIn("esp32_devkit_v1.GPIO21 is wired to dfplayer_mini.RX and rc522.SDA", text)
        self.assertIn("esp32_devkit_v1.GPIO19 is wired to dfplayer_mini.TX and rc522.SCK", text)
        self.assertIn("one microcontroller pin cannot carry 2 different signals", text)
        # Said as what it is since D166: a speaker terminal on a board pin.
        self.assertIn("dfplayer_mini.SPK_1 is a speaker terminal and is wired to "
                      "esp32_devkit_v1.GPIO26", text)
        self.assertEqual(len(r.items), 3)
        self.assertNotIn("GPIO18", text)                # MOSI alone on its pin is fine
        self.assertNotIn("GPIO23", text)

    def test_the_sound_wiring_passes(self):
        r = self.result(sound_reply())
        self.assertEqual(r.status, PASS, r.render())

    def test_two_modules_passing_a_signal_between_them_is_not_a_fault(self):
        # TX of one into RX of another, with no microcontroller pin on the wire.
        doc = sound_reply()
        self.assertEqual(self.result(doc).status, PASS)
        self.assertIn(("SPK_1", "SPK_A"),
                      [(w["from_pin"], w["to_pin"]) for w in doc["cables"][2]["wires"]])

    def test_nothing_to_check_is_a_skip(self):
        self.assertEqual(Pipeline.check_harness_signals(self.project.harness, self.parts).status,
                         checks.SKIP)


class TestABusIsStillABus(WeatherCase):
    def path(self, doc):
        text, _ = harness.build(doc, self.parts)
        return self.harness(text)

    def test_two_modules_on_one_i2c_bus_share_a_pin_and_pass(self):
        r = Pipeline.check_harness_signals(self.path(good()), self.parts)
        self.assertEqual(r.status, PASS, r.render())

    def test_a_bus_pin_wired_to_a_rail_fails(self):
        doc = good()
        doc["cables"][0]["wires"][3]["from_pin"] = "3V3"          # bme280.SDA
        r = Pipeline.check_harness_signals(self.path(doc), self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("bme280.SDA is a signal and is wired to", r.render())
        self.assertIn("which is a supply or ground", r.render())

    def test_an_input_strapped_to_a_rail_is_left_alone(self):
        parts = [self.lib.get("esp32_devkit_v1"), self.lib.get("mpu6050")]
        self.assertEqual(self.lib.get("mpu6050").pin("AD0").function, "io")
        doc = {"cables": [{"from": "esp32_devkit_v1", "to": "mpu6050", "gauge_awg": 22,
                           "length_mm": 80, "wires": [
                               {"from_pin": "3V3", "to_pin": "VCC", "colour": "red"},
                               {"from_pin": "GND", "to_pin": "GND", "colour": "black"},
                               {"from_pin": "GND", "to_pin": "AD0", "colour": "black"},
                               {"from_pin": "GPIO22", "to_pin": "SCL", "colour": "yellow"},
                               {"from_pin": "GPIO21", "to_pin": "SDA", "colour": "green"}]}]}
        text, _ = harness.build(doc, parts)
        r = Pipeline.check_harness_signals(self.harness(text), parts)
        self.assertEqual(r.status, PASS, r.render())


class TestSupplyVoltage(TagCase):
    """D138: the voltage check said "0 links checked" and passed."""

    def result(self, doc):
        return Pipeline.check_harness_supply(self.path(doc), self.parts)

    def test_the_library_says_what_each_part_takes(self):
        self.assertEqual(self.lib.get("rc522").supply_v, [3.3])
        self.assertEqual(max(self.lib.get("esp32_devkit_v1").supply_v), 5.0)

    def test_what_a_boards_supply_pin_gives(self):
        esp = self.lib.get("esp32_devkit_v1")
        self.assertEqual(harness.supply_pin_volts(esp, "3V3"), 3.3)
        self.assertEqual(harness.supply_pin_volts(esp, "5V"), 5.0)
        self.assertEqual(harness.supply_pin_volts(esp, "VIN"), 5.0)
        self.assertIsNone(harness.supply_pin_volts(esp, "GND"))
        self.assertIsNone(harness.supply_pin_volts(esp, "GPIO21"))

    def test_the_reader_on_the_five_volt_pin_fails_and_says_both_voltages(self):
        r = self.result(real_reply())
        self.assertEqual(r.status, "FAIL")
        self.assertIn("rc522.VCC is fed from esp32_devkit_v1.VIN, which is 5 V. "
                      "The part runs from 3.3 V", r.render())
        self.assertNotIn("dfplayer_mini.VCC is fed", r.render())   # 3.3 to 5 V: fine on 5

    def test_each_part_on_a_pin_it_can_take_passes(self):
        r = self.result(sound_reply())
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn("2 supply pin(s)", r.detail)

    def test_a_supply_whose_voltage_is_unknown_is_not_called_a_pass(self):
        doc = {"cables": [cable("rc522", "dfplayer_mini", ("VCC", "VCC"), ("GND", "GND"))]}
        r = self.result(doc)
        self.assertEqual(r.status, checks.SKIP)
        self.assertIn("its voltage is not checked", r.render())


def second_reply() -> dict:
    """The model's wiring on the rerun, with the first three faults caught:
    sound except that the reader is still on the 5 V pin. (GPIO17 and 16
    in the real answer are 23 and 32 here, as above.)"""
    return {"cables": [
        cable("esp32_devkit_v1", "rc522", ("VIN", "VCC"), ("GND", "GND"), ("GPIO21", "SDA"),
              ("GPIO19", "SCK"), ("GPIO18", "MOSI"), ("GPIO23", "MISO")),
        cable("esp32_devkit_v1", "dfplayer_mini", ("VIN", "VCC"), ("GND", "GND"),
              ("GPIO26", "RX"), ("GPIO25", "TX"), ("GPIO32", "BUSY")),
        cable("dfplayer_mini", "speaker_8ohm_20mm", ("SPK_1", "SPK_A"), ("SPK_2", "SPK_B"))]}


class TestSupplyPinIsCodesToChoose(TagCase):
    """D141: told "rc522.VCC is fed from esp32_devkit_v1.VIN, which is 5 V.
    The part runs from 3.3 V", the model wired it to VIN again."""

    def test_the_second_real_wiring_failed_on_that_alone(self):
        p = self.path(second_reply())
        self.assertEqual(Pipeline.check_harness_signals(p, self.parts).status, PASS)
        r = Pipeline.check_harness_supply(p, self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertEqual(len(r.items), 1)

    def test_the_wire_is_moved_to_the_pin_the_part_can_take_and_it_is_said(self):
        fixed, notes = harness.fix_supply_pins(second_reply(), self.parts)
        self.assertEqual(fixed["cables"][0]["wires"][0], {"from_pin": "3V3", "to_pin": "VCC",
                                                          "colour": "white"})
        self.assertEqual(notes, ["rc522.VCC was wired to esp32_devkit_v1.VIN (5 V). The part "
                                 "runs from 3.3 V, so Nemo moved that wire to "
                                 "esp32_devkit_v1.3V3."])
        self.assertEqual(Pipeline.check_harness_supply(self.path(fixed), self.parts).status, PASS)

    def test_a_part_that_takes_five_volts_is_left_on_it(self):
        fixed, _ = harness.fix_supply_pins(second_reply(), self.parts)
        self.assertEqual(fixed["cables"][1]["wires"][0]["from_pin"], "VIN")

    def test_the_answer_it_was_given_is_not_altered(self):
        doc = second_reply()
        harness.fix_supply_pins(doc, self.parts)
        self.assertEqual(doc, second_reply())

    def test_a_sound_wiring_is_returned_as_it_was_with_nothing_to_say(self):
        self.assertEqual(harness.fix_supply_pins(sound_reply(), self.parts), (sound_reply(), []))

    def test_it_is_not_moved_where_that_would_join_two_supplies(self):
        doc = second_reply()
        doc["cables"].append(cable("rc522", "dfplayer_mini", ("VCC", "VCC")))
        fixed, notes = harness.fix_supply_pins(doc, self.parts)
        self.assertEqual(notes, [])
        self.assertEqual(fixed, doc)
        self.assertEqual(Pipeline.check_harness_supply(self.path(fixed), self.parts).status, "FAIL")

    def test_two_supplies_wired_together_fail_the_check(self):
        doc = sound_reply()
        doc["cables"].append(cable("rc522", "dfplayer_mini", ("VCC", "VCC")))
        r = Pipeline.check_harness_supply(self.path(doc), self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("esp32_devkit_v1.3V3 (3.3 V) and esp32_devkit_v1.VIN (5 V) are wired "
                      "together: two different supplies on one wire", r.render())

    def test_the_step_passes_at_the_first_asking_and_says_what_it_moved(self):
        r = SchemaRouter(second_reply())
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            sr = self.pipe(r).stage_wiring()
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        self.assertIn("so Nemo moved that wire to esp32_devkit_v1.3V3", sr.render())

    def test_the_model_is_not_told_voltages_it_would_then_wire(self):
        # Told "Its 3V3 pin gives 3.3 V; VIN and 5V give 5 V", it wired
        # 3V3-VCC, VIN-VCC and 5V-VCC onto the one reader.
        facts = harness.part_facts(self.parts)
        self.assertNotIn("gives", facts)
        self.assertNotIn("Runs from", facts)
        self.assertNotRegex(facts, r"\d V\b")

    def test_what_it_wired_then_fails_as_supplies_joined_on_one_wire(self):
        # It also wired 5V-VCC; the board has no pin of that name since D144.
        doc = {"cables": [cable("esp32_devkit_v1", "rc522", ("3V3", "VCC"), ("GND", "GND"),
                                ("VIN", "VCC"), ("GND", "GND"))]}
        r = Pipeline.check_harness_supply(self.path(doc), self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("are wired together: two different supplies on one wire", r.render())
        # Moving the 5 V wire to 3V3 leaves the part on one supply, twice over.
        fixed, notes = harness.fix_supply_pins(doc, self.parts)
        self.assertEqual(len(notes), 1)
        self.assertEqual(Pipeline.check_harness_supply(self.path(fixed), self.parts).status, PASS)


class TestSpeakerHasItsTerminals(TagCase):
    """D139."""

    def test_the_names_the_model_made_up_are_refused(self):
        with self.assertRaises(harness.HarnessError) as ctx:
            harness.build(real_reply(speaker=("speaker_8ohm", "GND")), self.parts)
        self.assertIn("speaker_8ohm_20mm has no pin 'speaker_8ohm'", str(ctx.exception))

    def test_and_cannot_be_written_under_the_schema(self):
        # Since D166 the speaker is not offered at all: code wires it to the
        # part that drives it, so no pin of it can be written, made up or not.
        ends = {x["properties"][k]["const"] for k in ("from", "to") for x in
                harness.harness_schema(self.parts)["properties"]["cables"]["items"]["anyOf"]}
        self.assertNotIn("speaker_8ohm_20mm", ends)
        self.assertIn("dfplayer_mini", ends)
        self.assertEqual(harness.speaker_pins(self.parts[-1] if self.parts[-1].ref ==
                         "speaker_8ohm_20mm" else PartsLibrary.load().get("speaker_8ohm_20mm")),
                         ["SPK_A", "SPK_B"])

    def test_every_bundled_part_that_is_wired_by_pin_has_its_pins_listed(self):
        # Boards and batteries are the known exceptions; anything else with
        # no pins would again have them made up.
        bare = [p.ref for p in PartsLibrary.load().parts.values()
                if not p.pins and p.category not in ("mcu", "power")]
        self.assertEqual(bare, [])


class TestTheStepSendsItBack(TagCase):
    def run_step(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()

    def test_the_real_wiring_goes_back_with_its_faults_and_the_sound_one_is_kept(self):
        r = SchemaRouter(real_reply(), sound_reply())
        sr = self.run_step(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 2)
        again = r.asked[1]["user"]
        self.assertIn("one microcontroller pin cannot carry 2 different signals", again)
        # The supply pin is not sent back: code had already moved it (D141).
        self.assertNotIn("rc522.VCC is fed from", again)
        names = [x.name for x in sr.results]
        self.assertIn("harness_signals", names)
        self.assertIn("harness_supply", names)

    def test_if_it_comes_back_the_same_the_step_fails(self):
        sr = self.run_step(SchemaRouter(real_reply()))
        self.assertFalse(sr.ok)
        self.assertIn("harness_signals", [x.name for x in sr.results if not x.ok])

    def test_the_sound_wiring_gives_a_firmware_with_a_pin_for_each_signal(self):
        plan = firmware.plan(sound_reply(), self.parts)
        self.assertEqual(plan.mcu, "esp32_devkit_v1")
        source = firmware.scaffold(sound_reply(), self.parts, "tag-player", "esp32dev", 1000)
        self.assertIn("PIN_DFPLAYER_MINI_RX", source)
        self.assertIn("= 26;", source)
        self.assertIn("PIN_SPI_SCK  = 18;", source)

    def test_they_have_plain_names_for_the_window(self):
        from nemo.gui import controller as C
        names = [v for v in vars(C).values() if isinstance(v, dict) and "harness_pins" in v][0]
        self.assertEqual(names["harness_signals"], "No wire does two jobs")
        self.assertEqual(names["harness_supply"], "Every part gets a voltage it can take")


class TestNothingComparedIsNotAPass(TagCase):
    """D143: "PASS voltage_compat -- 0 links checked", on every run of this
    brief, beside a 3.3 V part on a 5 V pin."""

    def test_no_links_is_a_skip_that_says_nothing_was_compared(self):
        r = checks.voltage_compatibility([])
        self.assertEqual(r.status, checks.SKIP)
        self.assertIn("no logic levels were compared", r.detail)

    def test_this_briefs_parts_give_it_no_links(self):
        self.assertEqual(Pipeline._declared_links(self.parts), [])

    def test_with_links_it_still_passes_and_fails_as_before(self):
        esp, reader = self.lib.get("esp32_devkit_v1"), self.lib.get("rc522")
        self.assertEqual(checks.voltage_compatibility([(esp, "GPIO18", reader, "SCK")]).status,
                         PASS)
        ring = self.lib.get("ws2812b_ring8")
        self.assertEqual(checks.voltage_compatibility([(ring, "DOUT", reader, "SCK")]).status,
                         "FAIL")


class TestConstraintsReachTheGuide(TagCase):
    """D140."""

    def test_each_constraint_is_an_open_question_that_says_it_was_not_checked(self):
        sr = self.pipe(StubRouter()).stage_pack([])
        text = self.project.build_md.read_text(encoding="utf-8")
        tail = text[text.index("## Open questions"):]
        self.assertIn(f"- [brief] not checked by Nemo, confirm it yourself: {MAGNET}", tail)
        self.assertIn("The speaker faces out through the front panel.", tail)
        self.assertNotIn("None recorded", tail)
        self.assertIn("2 open question(s)", sr.notes[0])

    def test_a_brief_with_no_constraints_adds_nothing(self):
        brief = self.project.load_brief()
        brief.constraints = []
        self.project.save_brief(brief)
        self.pipe(StubRouter()).stage_pack([])
        self.assertIn("- None recorded.", self.project.build_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
