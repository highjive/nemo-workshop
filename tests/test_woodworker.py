"""The Workshop's Woodworker (owner, 2026-10-23): flooring and skirting
planned by code; a product's own figures are asked for, never guessed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import woodworker as W
from nemo.staff import STAFF


class TestThePlan(unittest.TestCase):
    def test_flooring_sums(self):
        p = W.plan("laminate flooring 4.2 x 3.6 m", pack_m2=2.22, board_mm=(1380, 193))
        text = p.text()
        self.assertIn("Floor area: 15.12 m2", text)
        self.assertIn("16.63 m2", text)                          # 10 % straight
        self.assertIn("8 pack(s) of 2.22 m2", text)              # ceil(16.632 / 2.22)
        self.assertIn("18 whole row(s)", text)
        self.assertIn("last row of 126 mm", text)
        self.assertIn("rule of thumb", text)

    def test_a_thin_last_row_is_shared_out(self):
        p = W.plan("flooring 4 x 2.0 m", board_mm=(1200, 190))   # 10 rows + 100 mm (< 63)? no: 100 > 63
        self.assertNotIn("under a third", p.text())
        p = W.plan("flooring 4 x 1.95 m", board_mm=(1200, 190))  # 10 rows + 50 mm
        self.assertIn("under a third", p.text())
        self.assertIn("about 120 mm each", p.text())

    def test_packet_figures_are_asked_not_guessed(self):
        p = W.plan("engineered flooring 5m x 4m")
        packet = " ".join(p.read_the_packet)
        for need in ("m2 a pack covers", "expansion gap", "rest in the room", "board's width"):
            self.assertIn(need, packet)
        self.assertNotRegex(p.text(), r"\d+\s*mm gap")            # no gap figure made up

    def test_sizes_and_jobs(self):
        self.assertEqual(W.room_size("floor 360cm by 420cm"), (4.2, 3.6))
        self.assertEqual(W.room_size("floor 4200 x 3600"), (4.2, 3.6))
        self.assertIn("15 %", W.plan("herringbone floor 3 x 3").text())
        self.assertIn("13.20 m", W.plan("skirting 4 x 3", doors=1).text())   # 14 - 0.8
        for bad in ("paint the fence 3 x 2", "flooring", "flooring 400 x 300 m"):
            with self.assertRaises(W.WoodworkerError):
                W.plan(bad)

    def test_on_the_roster(self):
        self.assertTrue(STAFF["workshop.woodworker"].working)


class TestTheJobsOwnWords(unittest.TestCase):
    def test_the_doors_the_job_names(self):
        # 2026-11-08: "skirting ... with 2 doors" was planned for one door.
        self.assertEqual(W.doors_in("skirting 4.2 x 3.6 m with 2 doors"), 2)
        self.assertEqual(W.doors_in("two doorways"), 2)
        self.assertEqual(W.doors_in("a box room, no door"), 0)
        self.assertIsNone(W.doors_in("skirting 4.2 x 3.6 m"))
        p = W.plan("skirting for a room 4.2 x 3.6 m with 2 doors")
        self.assertIn("less 2 doorway(s)", p.lines[0])
        self.assertIn("14.00 m", p.lines[0])
        self.assertIn("not measured", p.lines[0])
        self.assertIn("less 3 doorway(s)", W.plan("skirting 4.2 x 3.6 m with 2 doors", doors=3).lines[0])
        self.assertIn("less 1 doorway(s)", W.plan("skirting 4.2 x 3.6 m").lines[0])


if __name__ == "__main__":
    unittest.main()
