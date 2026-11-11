"""D154: the build guide says what must be done before a part is wired in.

The boost converter's own entry in the parts library: "it powers up at
whatever voltage it was last adjusted to, not a safe default". The first
battery designs through the real pipeline had one feeding the board's 5 V
pin, and the guide's wiring order did not mention setting it. The cell's
negative lead, which must reach only the protection board, was not
mentioned either, under a step that says "Connect grounds first".
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.project import Brief
from test_gates_real import WeatherCase
from test_pipeline import PipelineCase, StubRouter


class BatteryCase(PipelineCase):
    PARTS = ("esp32_devkit_v1", "bme280", "ws2812b_ring8", "lipo_2000", "tp4056_protected",
             "boost_5v_mt3608")

    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="pocket-lamp", function="A battery lamp that shows the temperature.",
            power="LiPo 3.7 V 2000 mAh", supply_ma=2000, rails=[5.0, 3.3],
            envelope_mm=[150, 100, 40], parts=list(self.PARTS), mcu="esp32",
            done_when="The ring changes colour."))
        self.pipe(StubRouter()).stage_pack([])
        self.text = self.project.build_md.read_text(encoding="utf-8")
        start = self.text.index("## Wiring order")
        self.order = self.text[start:self.text.index("##", start + 5)]


class TestTheConverterIsSetFirst(BatteryCase):
    def test_setting_it_is_the_first_step_and_names_the_voltage(self):
        self.assertIn("1. Before boost_5v_mt3608 is wired to anything else, power it on its "
                      "own and set its output to 5 V with a meter. It gives whatever it was "
                      "last adjusted to, which may be far more.", self.order)

    def test_the_steps_that_were_there_follow_renumbered(self):
        self.assertIn("2. Check continuity on the harness before powering anything.", self.order)
        self.assertIn("5. Attach modules one at a time, checking current draw.", self.order)

    def test_the_cell_goes_on_last_and_only_to_the_protection_board(self):
        self.assertIn("6. Connect lipo_2000 last of all, and only to tp4056_protected: its "
                      "negative lead must not go to the common ground.", self.order)


class TestThePartsOwnNotesAreInTheGuide(BatteryCase):
    def test_each_part_with_a_note_has_it_in_the_librarys_words(self):
        notes = self.text[self.text.index("## Notes on the parts"):
                          self.text.index("## Flashing")]
        self.assertIn("- **boost_5v_mt3608**: Steps a LiPo's 3.0-4.2 V up to a fixed 5 V, set "
                      "once with the onboard potentiometer before connecting anything", notes)
        self.assertIn("- **lipo_2000**:", notes)
        self.assertIn("- **ws2812b_ring8**: Data line wants to see at least 70% of the supply "
                      "voltage", notes)

    def test_it_comes_before_flashing_and_after_the_wiring_order(self):
        self.assertLess(self.text.index("## Wiring order"),
                        self.text.index("## Notes on the parts"))
        self.assertLess(self.text.index("## Notes on the parts"), self.text.index("## Flashing"))


class TestAProjectWithNoConverter(WeatherCase):
    def test_keeps_the_four_steps_it_had_and_gains_no_others(self):
        self.pipe(StubRouter()).stage_pack([])
        text = self.project.build_md.read_text(encoding="utf-8")
        start = text.index("## Wiring order")
        order = text[start:text.index("##", start + 5)]
        self.assertIn("1. Check continuity on the harness before powering anything.", order)
        self.assertIn("4. Attach modules one at a time, checking current draw.", order)
        self.assertNotIn("5.", order)
        self.assertNotIn("set its output", order)


if __name__ == "__main__":
    unittest.main()
