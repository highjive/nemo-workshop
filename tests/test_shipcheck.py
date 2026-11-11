"""SHIP or DON'T SHIP (owner, 2026-11-04: "run soup zero test"): Soup's
task format and scorings, judged against the GGUF models Nemo runs."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import shipcheck as S
from nemo.parts import PartsLibrary

SHIPPED = Path(__file__).resolve().parent.parent / "nemo" / "data" / "evals" / "nemo-tasks.jsonl"


class TestSoupsScorings(unittest.TestCase):
    def test_exact_is_the_whole_answer_in_any_case(self):
        self.assertTrue(S.score(" Yes. ", {"expected": "yes", "scoring": "exact"}))
        self.assertFalse(S.score("yes, it is", {"expected": "yes", "scoring": "exact"}))

    def test_contains_is_a_whole_token(self):
        self.assertTrue(S.score("Use GPIO4 here", {"expected": "gpio4", "scoring": "contains"}))
        self.assertFalse(S.score("Use GPIO44 here", {"expected": "GPIO4", "scoring": "contains"}))

    def test_answer_is_the_last_number_by_value(self):
        t = {"expected": "21.1", "scoring": "answer"}
        self.assertTrue(S.score("1.5 + 0.6 + 19 = **21.10 mA**", t))
        self.assertFalse(S.score("1.5 + 0.6 + 19 = 21", t))
        # The first run's failure: cut off mid-sum is not the answer.
        self.assertFalse(S.score("Total current = 1 + 1 + 15 = **1", {"expected": "17", "scoring": "answer"}))

    def test_regex(self):
        t = {"expected": r'^\{"pin": "(GPIO4|GPIO5)"\}$', "scoring": "regex"}
        self.assertTrue(S.score('{"pin": "GPIO5"}', t))
        self.assertFalse(S.score('{"pin": "GPIO9"}', t))

    def test_an_answer_in_a_code_fence_is_read_inside_it(self):
        # 2026-11-11: Qwen2.5-Coder-7B answered all 8 JSON questions rightly, each in
        # ```json ...```, and scored 0 of 8: the check judged the fence, not the pin.
        t = {"expected": r'^\s*\{\s*"pin"\s*:\s*"(GPIO4|GPIO18)"\s*\}\s*$', "scoring": "regex"}
        self.assertTrue(S.score('```json\n{"pin": "GPIO4"}\n```', t))
        self.assertTrue(S.score('{"pin": "GPIO18"}', t))
        self.assertFalse(S.score('```json\n{"pin": "GPIO2"}\n```', t))
        self.assertFalse(S.score('Here: ```json\n{"pin": "GPIO4"}\n``` and more', t))   # not the whole answer

    def test_an_unknown_scoring_is_refused(self):
        with self.assertRaises(ValueError):
            S.score("x", {"expected": "x", "scoring": "judge"})


class TestNemosTasks(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()
        self.tasks = S.make_tasks(self.lib)

    def test_the_shipped_file_is_what_the_library_makes_now(self):
        # A part changed in the library and not the file would test old facts.
        self.assertEqual(S.read_tasks(SHIPPED), self.tasks)

    def test_every_pin_answer_is_the_librarys(self):
        boards = {p.name: {q.name for q in p.pins} for p in self.lib if p.category == "mcu"}
        for t in (t for t in self.tasks if t["category"] == "pins"):
            board = next(n for n in boards if t["prompt"].startswith(f"The {n} has"))
            pin = re.search(r"Is (GPIO\d+) one", t["prompt"]).group(1)
            self.assertEqual(t["expected"], "yes" if pin in boards[board] else "no")

    def test_every_sum_is_codes(self):
        draw = {p.name: p.current_ma for p in self.lib}
        for t in (t for t in self.tasks if t["category"] == "power"):
            names = re.findall(r"(?:: |; )([^;:]+?): ([\d.]+) mA", t["prompt"])
            self.assertEqual(float(t["expected"]), sum(draw[n] for n, _ in names))

    def test_one_word_every_time_cannot_pass(self):
        # Soup asks whether a metric was gamed: "yes" to everything scores half.
        for cat in ("pins", "voltage"):
            got = Counter(t["expected"] for t in self.tasks if t["category"] == cat)
            self.assertEqual(got["yes"], got["no"], cat)

    def test_soups_format_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            p = S.write_tasks(self.tasks, Path(d) / "t.jsonl")
            for line in p.read_text(encoding="utf-8").splitlines():
                self.assertEqual(set(json.loads(line)), {"prompt", "expected", "category", "scoring"})
            self.assertEqual(S.read_tasks(p), self.tasks)

    def test_a_bad_task_file_says_which_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text('{"prompt": "a", "expected": "b"}\n{"prompt": "c"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 2"):
                S.read_tasks(p)


class TestTheVerdict(unittest.TestCase):
    def run_of(self, model, results):
        r = S.ModelRun("m", model, "0" * 64)
        r.answers = [{"category": c, "passed": ok} for c, ok in results]
        return r

    def test_no_worse_anywhere_ships(self):
        base = self.run_of("4b", [("pins", True), ("power", False)])
        cand = self.run_of("8b", [("pins", True), ("power", True)])
        self.assertEqual(S.verdict(base, cand)[0], "SHIP")

    def test_a_gain_bought_with_a_lost_skill_does_not(self):
        base = self.run_of("4b", [("pins", True), ("power", False), ("power", False)])
        cand = self.run_of("8b", [("pins", False), ("power", True), ("power", True)])
        result, why = S.verdict(base, cand)
        self.assertEqual(result, "DON'T SHIP")
        self.assertIn("pins", why[0])

    def test_fewer_overall_does_not(self):
        base = self.run_of("4b", [("pins", True), ("pins", True)])
        cand = self.run_of("8b", [("pins", True), ("pins", False)])
        self.assertEqual(S.verdict(base, cand)[0], "DON'T SHIP")


class TestARunWithoutAModel(unittest.TestCase):
    def test_it_asks_each_task_thinking_off_at_temperature_0_and_keeps_the_proof(self):
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))
        tasks = [{"prompt": "Is GPIO4 on it? Answer only yes or no.", "expected": "yes",
                  "category": "pins", "scoring": "exact"}]
        seen = []

        def post(payload):
            seen.append(payload)
            return "yes"
        with tempfile.TemporaryDirectory() as d:
            gguf = Path(d) / "m.gguf"; gguf.write_bytes(b"GGUF" + b"\0" * 64)
            run = S.run_mode(cfg, "talk", tasks, say=lambda m: None, post=post,
                             start=lambda c, m: (True, "up"), model_file=gguf)
            self.assertEqual(seen[0]["temperature"], 0)
            self.assertEqual(seen[0]["chat_template_kwargs"], {"enable_thinking": False})
            self.assertEqual(run.passed, 1)
            tf = Path(d) / "t.jsonl"; S.write_tasks(tasks, tf)
            proof = S.evidence(tf, run, run, *S.verdict(run, run), folder=Path(d) / "evals")
            doc = json.loads(proof.read_text(encoding="utf-8"))
            self.assertEqual(doc["verdict"], "SHIP")
            self.assertEqual(len(doc["base"]["model_sha256"]), 64)
            self.assertEqual(doc["candidate"]["answers"][0]["output"], "yes")

    def test_a_mode_that_will_not_start_is_said(self):
        from nemo.config import Config
        with self.assertRaisesRegex(RuntimeError, "would not start"):
            S.run_mode(Config.load(Path("/nonexistent")), "talk", [], say=lambda m: None,
                       start=lambda c, m: (False, "no room"))


if __name__ == "__main__":
    unittest.main()
