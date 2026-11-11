"""The GPU Specialist (Doctors) and the Quality Inspector (Computer Lab),
and the harder SHIP-check tasks (owner, 2026-11-04)."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import clinic, machine, shipcheck as S, skills, toolkit
from nemo.config import Config
from nemo.parts import PartsLibrary
from nemo.staff import STAFF

CARD = {"name": "card", "temperature.gpu": 40.0, "memory.free": 7600.0, "memory.used": 500.0}


class TestTheGpuSpecialist(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load(Path("/nonexistent"))

    def look(self, **change):
        with mock.patch("nemo.modes.current", return_value=mock.Mock(running=False)):
            return clinic.gpu(self.cfg, status={**CARD, **change})

    def test_on_the_staff_and_among_the_specialists(self):
        self.assertIn("doctors.gpu", STAFF)
        self.assertIn("doctors.gpu", [k for k, _ in clinic.SPECIALISTS])

    def test_a_healthy_card_says_nothing(self):
        self.assertEqual(self.look(), [])

    def test_heat_is_said_at_the_rule_of_thumb_and_called_one(self):
        self.assertEqual(self.look(**{"temperature.gpu": clinic.GPU_HOT_C - 1}), [])
        f = self.look(**{"temperature.gpu": clinic.GPU_HOT_C})[0]
        self.assertIn("rule of thumb", f.diagnosis)

    def test_too_little_free_for_design_names_the_numbers(self):
        f = self.look(**{"memory.free": 3000.0})[0]
        self.assertIn("3000", f.what)
        self.assertIn("7300", f.diagnosis)                 # 7000 + the margin

    def test_too_little_for_design_says_whether_a_painting_fits_too(self):
        f = self.look(**{"memory.free": 4000.0})
        self.assertEqual(len(f), 1)
        self.assertIn("A painting", f[0].diagnosis)
        self.assertNotIn("A painting", self.look(**{"memory.free": 6000.0})[0].diagnosis)

    def test_without_a_desktop_design_mode_the_painting_is_what_is_measured(self):
        self.cfg.data["modes_desktop"] = {}
        f = self.look(**{"memory.free": 4000.0})
        self.assertEqual([x.what for x in f], ["Too little free on card to paint"])

    def test_nothing_to_say_without_an_nvidia_card(self):
        self.assertEqual(clinic.gpu(self.cfg, status={}), [])

    def test_a_reading_the_card_does_not_give_is_none_not_a_guess(self):
        row = "RTX, [N/A], 3, 10.5, 8192, 400, 7792, 617.42, [N/A]"
        with mock.patch.object(machine, "_query", return_value=[row]):
            s = machine.gpu_status()
        self.assertIsNone(s["temperature.gpu"])
        self.assertIsNone(s["fan.speed"])
        self.assertEqual(s["memory.free"], 7792.0)

    def test_its_tool_is_nvidia_smi(self):
        self.assertEqual([n.name for n in toolkit.NEEDS["doctors.gpu"]], ["nvidia-smi"])


class TestTheQualityInspector(unittest.TestCase):
    def test_on_the_staff_with_its_skills_and_tools(self):
        self.assertIn("computer_lab.quality", STAFF)
        kinds = [(s.kind, s.target) for s in skills.skills_for("computer_lab.quality")]
        self.assertIn((skills.JOB, "eval"), kinds)
        self.assertIn((skills.VERDICTS, ""), kinds)
        self.assertEqual([n.name for n in toolkit.NEEDS["computer_lab.quality"]], ["the task file", "the engine"])

    def test_its_history_is_newest_first_and_skips_what_it_cannot_read(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            for when, verdict in (("2026-11-04 08:00:00", "SHIP"), ("2026-11-04 09:00:00", "DON'T SHIP")):
                run = {"model": "m", "answers": [{"passed": True}, {"passed": False}]}
                (folder / f"{when[-8:-6]}.json").write_text(json.dumps(
                    {"run": when, "when": when, "verdict": verdict, "base": run, "candidate": run}),
                    encoding="utf-8")
            (folder / "broken.json").write_text("{", encoding="utf-8")
            past = S.history(folder)
        self.assertEqual([p["verdict"] for p in past], ["DON'T SHIP", "SHIP"])
        self.assertEqual((past[0]["candidate_passed"], past[0]["of"]), (1, 2))

    def test_an_answer_cut_off_by_the_limit_is_said_as_such(self):
        tasks = [{"prompt": "p", "expected": "97", "category": "runtime", "scoring": "answer"}]
        with tempfile.TemporaryDirectory() as d:
            gguf = Path(d) / "m.gguf"; gguf.write_bytes(b"GGUF")
            base = S.run_mode(Config.load(Path("/nonexistent")), "talk", tasks, say=lambda m: None,
                              post=lambda p: ("= 97.5 hours, rounded down =", True),
                              start=lambda c, m: (True, ""), model_file=gguf)
            cand = S.run_mode(Config.load(Path("/nonexistent")), "talk", tasks, say=lambda m: None,
                              post=lambda p: "97", start=lambda c, m: (True, ""), model_file=gguf)
        self.assertTrue(base.answers[0]["cut_off"])
        line = next(w for w in S.verdict(base, cand)[1] if w.startswith("runtime"))
        self.assertIn("1 cut off at", line)


class TestTheHarderTasks(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()
        self.tasks = S.make_tasks(self.lib)

    def test_each_runtime_is_the_capacity_over_the_draw_rounded_down(self):
        draw = {p.name: p.current_ma for p in self.lib}
        for t in (t for t in self.tasks if t["category"] == "runtime"):
            mah = float(re.search(r"A ([\d.]+) mAh", t["prompt"]).group(1))
            names = re.findall(r"(?:: |; )([^;:]+?): ([\d.]+) mA", t["prompt"].split("the time")[1])
            self.assertEqual(int(t["expected"]), int(mah // sum(draw[n] for n, _ in names)))

    def test_each_supply_answer_is_the_librarys_power_pin(self):
        for t in (t for t in self.tasks if t["category"] == "supply"):
            board = next(p for p in self.lib if t["prompt"].startswith(f"The {p.name} has"))
            volts = float(re.search(r"supplies ([\d.]+) V", t["prompt"]).group(1))
            right = {q.name for q in board.pins if q.function == "power" and q.voltage
                     and abs(float(q.voltage) - volts) < 1e-9}
            for name in right:
                self.assertTrue(S.score(name, t), name)
            for q in board.pins:
                if q.name not in right:
                    self.assertFalse(S.score(q.name, t), q.name)

    def test_a_constraint_task_never_accepts_a_taken_pin(self):
        for t in (t for t in self.tasks if t["category"] == "constraint"):
            taken = re.search(r"(GPIO\d+) and (GPIO\d+) are already used", t["prompt"]).groups()
            for pin in taken:
                self.assertFalse(S.score(f'{{"pin": "{pin}"}}', t))


@unittest.skipUnless(_sandbox.has_display(), "needs a display")
class TestTheVerdictIsSaid(unittest.TestCase):
    def test_the_inspector_says_the_verdict_not_a_failed_check(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                said = []
                last = {"verdict": "DON'T SHIP", "candidate": "qwen3-8b", "candidate_passed": 40,
                        "of": 48, "base": "qwen3-4b", "base_passed": 44}
                with mock.patch.object(app, "announce", side_effect=lambda t, *a, **k: said.append(t)), \
                     mock.patch("nemo.shipcheck.history", return_value=[last]):
                    app.job_kind = "eval"
                    app._job_finished(mock.Mock(returncode=1, stopped=False))
                self.assertTrue(said[-1].startswith("The Quality Inspector says DON'T SHIP"), said)
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
