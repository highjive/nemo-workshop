"""Which mode a task should use.

modes.suggest() is called every time the running application -- not just
NemoDoc's one-time launch -- needs to recommend a mode for a task. It has
to agree with the launcher's own AVX-downgrade logic, or a no-AVX machine
gets pointed at a mode it can never load, over and over, with no way out
through the normal "Load the model?" flow.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import modes

CAD_TASKS = ("electrical", "wiring", "enclosure")


def with_hardware(avx: bool, total_mb: int):
    return (mock.patch.object(modes, "cpu_flags",
                              return_value=({"avx"} if avx else set())),
            mock.patch.object(modes, "mem_total_mb", return_value=total_mb))


class TestNoAvxDowngradesDesign(unittest.TestCase):
    """D102: found from a real machine. NemoDoc's launcher already
    downgraded design to talk with no AVX; modes.suggest(), used for every
    later in-app recommendation, did not, so every CAD stage kept being
    pointed at a mode that cannot load there -- indistinguishable from the
    pipeline refusing to move past whichever stage asked.
    """

    def test_the_operators_own_numbers(self):
        # 8105 MB total, no AVX: exactly what the real machine reported.
        a, b = with_hardware(avx=False, total_mb=8105)
        with a, b:
            for task in CAD_TASKS:
                self.assertEqual(modes.suggest(task), "talk", task)

    def test_a_capable_machine_is_unaffected(self):
        a, b = with_hardware(avx=True, total_mb=8105)
        with a, b:
            for task in CAD_TASKS:
                self.assertEqual(modes.suggest(task), "design", task)

    def test_avx_is_a_fixed_hardware_fact_not_a_ram_workaround(self):
        # More RAM does not grant instructions the CPU does not have.
        a, b = with_hardware(avx=False, total_mb=32000)
        with a, b:
            for task in CAD_TASKS:
                self.assertEqual(modes.suggest(task), "talk", task)

    def test_the_low_ram_path_is_unchanged_either_way(self):
        for avx in (True, False):
            a, b = with_hardware(avx=avx, total_mb=6000)
            with a, b:
                for task in (*CAD_TASKS, "brief", "firmware", "story"):
                    self.assertEqual(modes.suggest(task), "tiny", (avx, task))

    def test_non_design_tasks_are_untouched_by_the_avx_check(self):
        a, b = with_hardware(avx=False, total_mb=8105)
        with a, b:
            self.assertEqual(modes.suggest("brief"), "talk")
            self.assertEqual(modes.suggest("firmware"), "build")
            self.assertEqual(modes.suggest("story"), "talk")

    def test_an_unrecognised_task_still_falls_back_to_talk(self):
        a, b = with_hardware(avx=False, total_mb=8105)
        with a, b:
            self.assertEqual(modes.suggest("something_new"), "talk")


if __name__ == "__main__":
    unittest.main(verbosity=2)
