"""A USB socket wired by code to a board's USB pins (owner, 2026-10-29:
the wireless dock, a Wacom tablet read by an ESP32-S3 as USB host).

USB data is not a choice: only the chip's USB pins carry it. The board's
GPIO19/GPIO20 and the socket's D-/D+ are marked usb_dm/usb_dp in the
library, never offered to the model, and harness.wire_usb wires them.
Before it, a dock of a board and a socket had nothing the model could be
asked for and nothing code wired, and the electrical step failed with
"the reply lists no cables".
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, harness
from nemo.checks.deterministic import PASS, FAIL, Result
from nemo.parts import PartsLibrary
from nemo.project import Brief
from test_harness import SchemaRouter
from test_pipeline import PipelineCase

LIB = PartsLibrary.load()
DOCK = ("esp32s3_devkitc_1", "usb_a_socket")


def P(refs):
    return [LIB.get(r) for r in refs]


def wires(doc):
    return {(c["from"], w["from_pin"], c["to"], w["to_pin"]) for c in doc["cables"]
            for w in c["wires"]}


class TestTheLibrary(unittest.TestCase):
    def test_the_board_and_socket_mark_their_usb_pins(self):
        self.assertEqual(harness.usb_pins(LIB.get("esp32s3_devkitc_1")),
                         {"usb_dm": "GPIO19", "usb_dp": "GPIO20"})
        self.assertEqual(harness.usb_pins(LIB.get("usb_a_socket")),
                         {"usb_dm": "D-", "usb_dp": "D+"})

    def test_no_usb_pin_is_offered_to_the_model(self):
        board, socket = P(DOCK)
        for signals_only in (True, False):
            self.assertNotIn("GPIO19", harness.offered_pins(board, signals_only))
            self.assertNotIn("GPIO20", harness.offered_pins(board, signals_only))
            self.assertFalse({"D-", "D+"} & set(harness.offered_pins(socket, signals_only)))

    def test_the_board_leaves_out_the_pins_its_sources_warn_of(self):
        offered = set(harness.offered_pins(LIB.get("esp32s3_devkitc_1"), True))
        for pin in (0, 3, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46):
            self.assertNotIn(f"GPIO{pin}", offered)


class TestWireUsb(unittest.TestCase):
    def test_code_wires_data_and_power(self):
        doc, notes = harness.wire_usb({"cables": []}, P(DOCK))
        doc, _ = harness.wire_power(doc, P(DOCK), asked=False)
        self.assertEqual(wires(doc), {
            ("esp32s3_devkitc_1", "GPIO19", "usb_a_socket", "D-"),
            ("esp32s3_devkitc_1", "GPIO20", "usb_a_socket", "D+"),
            ("esp32s3_devkitc_1", "5V", "usb_a_socket", "VBUS"),
            ("esp32s3_devkitc_1", "GND", "usb_a_socket", "GND")})
        self.assertIn("GPIO19 to D-, GPIO20 to D+", " ".join(notes))

    def test_a_model_wire_to_a_usb_pin_is_set_aside(self):
        reply = {"cables": [{"from": "esp32s3_devkitc_1", "to": "usb_a_socket",
                             "wires": [{"from_pin": "GPIO4", "to_pin": "D+"}]}]}
        doc, notes = harness.wire_usb(reply, P(DOCK))
        self.assertNotIn(("esp32s3_devkitc_1", "GPIO4", "usb_a_socket", "D+"), wires(doc))
        self.assertIn("Set aside 1 wire(s) the model ran to a USB data pin", " ".join(notes))

    def test_without_usb_parts_nothing_changes(self):
        doc = {"cables": []}
        self.assertEqual(harness.wire_usb(doc, P(("esp32_devkit_v1", "rc522"))), (doc, []))

    def test_a_socket_without_a_usb_board_is_left_and_said(self):
        doc, notes = harness.wire_usb({"cables": []}, P(("esp32_devkit_v1", "usb_a_socket")))
        self.assertEqual(doc["cables"], [])
        self.assertIn("USB data not wired by Nemo", " ".join(notes))


class TestTheDock(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="dock", function="A dock that reads a USB pen tablet and sends it to the "
            "PC by Bluetooth.", power="USB-C 5 V 3 A", supply_ma=3000, rails=[5.0, 3.3],
            envelope_mm=[120, 90, 30], parts=list(DOCK), mcu="esp32s3_devkitc_1",
            done_when="The pointer moves."))

    def test_the_wiring_step_passes_without_asking_the_model(self):
        r = SchemaRouter({"cables": []})
        with mock.patch.object(checks, "wireviz", return_value=Result("wireviz", PASS, "rendered")):
            sr = self.pipe(r).stage_wiring()
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(r.asked, [])
        self.assertIn("usb_a_socket is wired by Nemo to esp32s3_devkitc_1's USB pins", sr.render())

    def test_the_signal_check_passes_the_usb_wires(self):
        doc, _ = harness.wire_usb({"cables": []}, P(DOCK))
        doc, _ = harness.wire_power(doc, P(DOCK), asked=False)
        text, _ = harness.build(doc, P(DOCK))
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        from nemo.pipeline import Pipeline
        r = Pipeline.check_harness_signals(self.project.harness, P(DOCK))
        self.assertNotEqual(r.status, FAIL, r.items)


class TestTheFirmwareNames(unittest.TestCase):
    """D203: D+ and D- both became PIN_USB_A_SOCKET_D, defined twice; the
    dock's bring-up firmware did not compile (real run, 2026-10-29)."""

    def test_a_signed_pair_keeps_its_sign(self):
        from nemo.firmware import _ident
        self.assertEqual((_ident("D+"), _ident("D-")), ("D_P", "D_N"))
        self.assertEqual(_ident("GPIO19"), "GPIO19")

    def test_every_constant_of_the_dock_is_named_once(self):
        from nemo import firmware
        doc, _ = harness.wire_usb({"cables": []}, P(DOCK))
        doc, _ = harness.wire_power(doc, P(DOCK), asked=False)
        names = [w.const for w in firmware.plan(doc, P(DOCK)).pins]
        self.assertEqual(sorted(names), ["PIN_USB_A_SOCKET_D_N", "PIN_USB_A_SOCKET_D_P"])


if __name__ == "__main__":
    unittest.main()
