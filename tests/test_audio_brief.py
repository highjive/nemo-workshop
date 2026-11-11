"""D166: the first real design with a microphone, an amplifier and a speaker.

Real run (AH531, qwen3-4b, Design mode, 2026-10-07), asked for signal
wires only. What the model answered:

  esp32 -> mic:     GPIO25-BCLK, GPIO26-DOUT, GPIO27-LRCL, GPIO32-SEL
  esp32 -> amp:     GPIO4-SD, GPIO18-DIN, GPIO19-BCLK, GPIO21-LRC
  esp32 -> speaker: GPIO22-SPK_A, GPIO23-SPK_B
  esp32 -> sensor:  GPIO21-SCL, GPIO22-SDA, GPIO23-XSHUT, GPIO25-GPIO1

Three things, none of them the model's to know:

- The speaker went to two pins of the board. The amplifier's entry had no
  outputs, so there was nowhere right to put it.
- Fourteen signals for a board that offers eleven pins. Five of them are
  pins their part works without; the library did not say so.
- Asked for no supply wires, code fed the amplifier, 700 mA at peak, from
  the board's 3.3 V pin: the lowest that suits, a rule made for sensors.
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
from nemo.pipeline import Pipeline
from nemo.project import Brief
from test_harness import SchemaRouter
from test_pipeline import PipelineCase

LIB = PartsLibrary.load()
BOARD = "esp32_devkit_v1"
MEMO = (BOARD, "sph0645lm4h", "max98357a", "speaker_8ohm_20mm", "vl53l0x")
TAG = (BOARD, "rc522", "dfplayer_mini", "speaker_8ohm_20mm")


def P(refs):
    return [LIB.get(r) for r in refs]


def cable(a, b, *wires):
    return {"from": a, "to": b, "wires": [{"from_pin": x, "to_pin": y} for x, y in wires]}


def real_reply() -> dict:
    return {"cables": [
        cable(BOARD, "sph0645lm4h", ("GPIO25", "BCLK"), ("GPIO26", "DOUT"), ("GPIO27", "LRCL"),
              ("GPIO32", "SEL")),
        cable(BOARD, "max98357a", ("GPIO4", "SD"), ("GPIO18", "DIN"), ("GPIO19", "BCLK"),
              ("GPIO21", "LRC")),
        cable(BOARD, "speaker_8ohm_20mm", ("GPIO22", "SPK_A"), ("GPIO23", "SPK_B")),
        cable(BOARD, "vl53l0x", ("GPIO21", "SCL"), ("GPIO22", "SDA"), ("GPIO23", "XSHUT"),
              ("GPIO25", "GPIO1"))]}


def lean_reply() -> dict:
    """What can be answered now: no speaker, no pin a part works without."""
    return {"cables": [
        cable(BOARD, "sph0645lm4h", ("GPIO25", "BCLK"), ("GPIO26", "DOUT"), ("GPIO27", "LRCL")),
        cable(BOARD, "max98357a", ("GPIO18", "DIN"), ("GPIO19", "BCLK"), ("GPIO4", "LRC")),
        cable(BOARD, "vl53l0x", ("GPIO21", "SCL"), ("GPIO22", "SDA"))]}


def wires(doc):
    return {(c["from"], w["from_pin"], c["to"], w["to_pin"]) for c in doc["cables"]
            for w in c["wires"]}


class TestTheLibrary(unittest.TestCase):
    def test_the_amplifier_has_outputs_and_they_are_speaker_terminals(self):
        self.assertEqual(harness.speaker_pins(LIB.get("max98357a")), ["OUT+", "OUT-"])
        self.assertEqual(harness.speaker_pins(LIB.get("dfplayer_mini")), ["SPK_1", "SPK_2"])
        self.assertEqual(harness.speaker_pins(LIB.get("speaker_8ohm_20mm")), ["SPK_A", "SPK_B"])

    def test_no_other_part_has_any(self):
        self.assertEqual(sorted(p.ref for p in LIB.parts.values() if harness.speaker_pins(p)),
                         ["dfplayer_mini", "max98357a", "speaker_8ohm_20mm"])

    def test_the_pins_marked_optional_are_the_five_a_source_was_read_for(self):
        got = {(p.ref, x.name) for p in LIB.parts.values() for x in p.pins if x.optional}
        self.assertEqual(got, {("max98357a", "SD"), ("max98357a", "GAIN"),
                               ("sph0645lm4h", "SEL"), ("vl53l0x", "XSHUT"),
                               ("vl53l0x", "GPIO1")})

    def test_each_entry_quotes_what_it_read(self):
        data = Path(harness.__file__).parent / "data" / "parts"
        pendant = (data / "pendant.yaml").read_text(encoding="utf-8")
        common = (data / "maker-common.yaml").read_text(encoding="utf-8")
        self.assertIn('"when not connected to anything"', pendant)
        self.assertIn('"a 1Mohm resistor from SD to Vin"', pendant)
        self.assertIn('"By default this pin is low', pendant)
        self.assertIn("OUT+ and OUT- are this library's names", pendant)
        self.assertIn('"By default it\'s pulled high"', common)

    def test_no_bus_supply_or_ground_pin_is_optional(self):
        for p in LIB.parts.values():
            for x in p.pins:
                if x.optional:
                    self.assertEqual(x.function, "io", (p.ref, x.name))


class TestWhatTheModelIsOffered(unittest.TestCase):
    def offered(self, signals_only):
        out = {}
        for pair in harness.harness_schema(P(MEMO), signals_only)["properties"]["cables"][
                "items"]["anyOf"]:
            out[pair["properties"]["from"]["const"]] = \
                pair["properties"]["wires"]["items"]["properties"]["from_pin"]["enum"]
        return out

    def test_asked_for_signals_it_gets_eight_pins_to_place_on_eleven(self):
        got = self.offered(True)
        self.assertEqual(got["sph0645lm4h"], ["BCLK", "DOUT", "LRCL"])
        self.assertEqual(got["max98357a"], ["DIN", "BCLK", "LRC"])
        self.assertEqual(got["vl53l0x"], ["SCL", "SDA"])
        self.assertNotIn("speaker_8ohm_20mm", got)
        self.assertEqual(sum(len(v) for k, v in got.items() if k != BOARD), 8)
        self.assertEqual(len(got[BOARD]), 11)

    def test_it_was_fourteen(self):
        self.assertEqual(len([w for c in real_reply()["cables"] for w in c["wires"]]), 14)

    def test_the_speaker_and_the_outputs_are_not_offered_the_long_way_either(self):
        got = self.offered(False)
        self.assertNotIn("speaker_8ohm_20mm", got)
        self.assertNotIn("OUT+", got["max98357a"])
        self.assertIn("SD", got["max98357a"])          # optional pins are, the long way

    def test_the_parts_list_it_reads_has_no_speaker_and_no_optional_pin(self):
        facts = harness.part_facts(P(MEMO), True)
        for word in ("speaker_8ohm_20mm", "SPK_A", "OUT+", "SEL", "XSHUT", "GAIN"):
            self.assertNotIn(word, facts)
        self.assertNotIn("speaker_8ohm_20mm", harness.part_facts(P(MEMO)))

    def test_which_were_left_is_said(self):
        self.assertEqual(harness.left_optional(P(MEMO)),
                         ["sph0645lm4h SEL", "max98357a SD, GAIN", "vl53l0x XSHUT, GPIO1"])


class TestTheSpeakerIsWiredByCode(unittest.TestCase):
    def test_the_real_answers_two_wires_to_the_board_are_set_aside(self):
        doc, notes = harness.wire_speakers(real_reply(), P(MEMO))
        got = wires(doc)
        self.assertFalse([w for w in got if "SPK_A" in w and BOARD in w])
        self.assertIn("Set aside 2 wire(s) the model ran to a speaker terminal or an "
                      "amplifier's output: esp32_devkit_v1.GPIO22 to speaker_8ohm_20mm.SPK_A; "
                      "esp32_devkit_v1.GPIO23 to speaker_8ohm_20mm.SPK_B.", notes)

    def test_and_it_goes_to_the_amplifier_and_nowhere_else(self):
        doc, notes = harness.wire_speakers(real_reply(), P(MEMO))
        got = wires(doc)
        self.assertIn(("max98357a", "OUT+", "speaker_8ohm_20mm", "SPK_A"), got)
        self.assertIn(("max98357a", "OUT-", "speaker_8ohm_20mm", "SPK_B"), got)
        self.assertEqual(len([w for w in got if "speaker_8ohm_20mm" in w]), 2)
        self.assertIn("speaker_8ohm_20mm is wired by Nemo to max98357a (OUT+ and OUT-), the "
                      "part that drives a speaker. Neither wire goes to ground or to the "
                      "board.", notes)

    def test_the_tag_player_is_wired_the_same_way_to_its_player(self):
        doc = {"cables": [cable(BOARD, "dfplayer_mini", ("GPIO4", "RX"), ("GPIO18", "TX"))]}
        got = wires(harness.wire_speakers(doc, P(TAG))[0])
        self.assertIn(("dfplayer_mini", "SPK_1", "speaker_8ohm_20mm", "SPK_A"), got)
        self.assertIn(("dfplayer_mini", "SPK_2", "speaker_8ohm_20mm", "SPK_B"), got)

    def test_an_answer_that_already_had_it_right_ends_with_one_cable_not_two(self):
        doc = {"cables": [cable("dfplayer_mini", "speaker_8ohm_20mm", ("SPK_1", "SPK_A"),
                                ("SPK_2", "SPK_B"))]}
        out, notes = harness.wire_speakers(doc, P(TAG))
        self.assertEqual(len(out["cables"]), 1)
        self.assertEqual(len(wires(out)), 2)
        self.assertFalse([n for n in notes if n.startswith("Set aside")])

    def test_two_parts_that_could_drive_it_and_it_is_left_and_said(self):
        parts = P((BOARD, "dfplayer_mini", "max98357a", "speaker_8ohm_20mm"))
        out, notes = harness.wire_speakers({"cables": [cable(BOARD, "dfplayer_mini",
                                                             ("GPIO4", "RX"))]}, parts)
        self.assertFalse([w for w in wires(out) if "speaker_8ohm_20mm" in w])
        self.assertIn("It wires one speaker to one part that can drive it, and here there "
                      "are 1 and 2.", notes[-1])

    def test_a_project_with_no_sound_is_returned_as_it_came(self):
        parts = P((BOARD, "bme280"))
        doc = {"cables": [cable(BOARD, "bme280", ("GPIO21", "SDA"))]}
        self.assertEqual(harness.wire_speakers(doc, parts), (doc, []))


class TestWhichSupplyPinAPartGets(unittest.TestCase):
    def fed(self, refs, doc):
        out, _ = harness.wire_power(doc, P(refs), asked=False)
        return {(c["to"], w["to_pin"]): w["from_pin"] for c in out["cables"]
                for w in c["wires"] if w["from_pin"] in ("3V3", "VIN")}

    def test_the_amplifier_is_on_the_supply_and_the_sensors_on_the_regulator(self):
        got = self.fed(MEMO, lean_reply())
        self.assertEqual(got[("max98357a", "VIN")], "VIN")
        self.assertEqual(got[("sph0645lm4h", "3V")], "3V3")
        self.assertEqual(got[("vl53l0x", "VIN")], "3V3")

    def test_the_rule_is_by_kind_of_part_and_is_the_one_the_current_check_uses(self):
        self.assertEqual(harness.SURGING, ("actuator", "driver", "audio"))
        self.assertIs(Pipeline.SURGING, harness.SURGING)

    def test_a_surging_part_that_only_takes_3v3_still_gets_3v3(self):
        amp = LIB.get("max98357a")
        low = type(amp)(**{**amp.__dict__, "supply_v": [3.3]})
        out, _ = harness.wire_power(lean_reply(), [LIB.get(BOARD), LIB.get("sph0645lm4h"), low,
                                                   LIB.get("speaker_8ohm_20mm"),
                                                   LIB.get("vl53l0x")], asked=False)
        got = {(c["to"], w["to_pin"]): w["from_pin"] for c in out["cables"] for w in c["wires"]}
        self.assertEqual(got[("max98357a", "VIN")], "3V3")


class MemoCase(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="voice-memo", function="A desk recorder that plays the last ten seconds back "
            "when a hand comes near.", power="USB 5 V 2 A", supply_ma=2000, rails=[5.0, 3.3],
            envelope_mm=[120, 80, 40], parts=list(MEMO), mcu="esp32",
            done_when="A hand starts playback."))
        self.parts = P(MEMO)

    def path(self, doc):
        text, _ = harness.build(doc, self.parts)
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        return self.project.harness

    def wiring(self, router):
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            return self.pipe(router).stage_wiring()


class TestTheCheck(MemoCase):
    def test_a_speaker_on_a_board_pin_fails_saying_what_it_is(self):
        doc, _ = harness.wire_power(real_reply(), self.parts, asked=False)
        r = Pipeline.check_harness_signals(self.path(doc), self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("speaker_8ohm_20mm.SPK_A is a speaker terminal and is wired to "
                      "esp32_devkit_v1.GPIO22: it goes to an amplifier's output and nothing "
                      "else", r.render())

    def test_a_speaker_on_its_amplifier_passes(self):
        doc, _ = harness.wire_speakers(lean_reply(), self.parts)
        doc, _ = harness.wire_power(doc, self.parts, asked=False)
        r = Pipeline.check_harness_signals(self.path(doc), self.parts)
        self.assertEqual(r.status, PASS, r.render())


class TestTheStep(MemoCase):
    def test_the_lean_answer_passes_every_check_at_the_first_asking(self):
        r = SchemaRouter(lean_reply())
        sr = self.wiring(r)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(len(r.asked), 1)
        text = sr.render()
        self.assertIn("speaker_8ohm_20mm is wired by Nemo to max98357a", text)
        self.assertIn("Left unwired, because the library says each part works without them: "
                      "sph0645lm4h SEL; max98357a SD, GAIN; vl53l0x XSHUT, GPIO1. Wire one "
                      "yourself if the project needs what it does.", text)
        self.assertIn("max98357a.VIN from VIN", text)

    def test_the_real_answer_is_mended_where_code_can_and_fails_only_on_what_is_left(self):
        sr = self.wiring(SchemaRouter(real_reply()))
        text = sr.render()
        self.assertIn("Set aside 2 wire(s) the model ran to a speaker terminal", text)
        self.assertNotIn("SPK_A is a speaker terminal and is wired", text)


if __name__ == "__main__":
    unittest.main()
