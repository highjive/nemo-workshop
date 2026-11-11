"""Story requests must tell the local model not to think first.

D119, measured on the real AH531 with qwen3-1.7b on 2026-10-05. Qwen3
reasons before it answers unless told not to, and llama-server counts that
reasoning against max_tokens. Story mode sizes max_tokens to the words it
asked for. Asked for a 60-word synopsis with a 220-token limit, the model
used all 220 tokens reasoning and returned an empty reply after 129 s; the
first real synopsis from the planning step took 324 s and was cut off mid
sentence. With thinking off the same small request came back whole in
26 s. Suggest beats and Draft it go through the same call.

No model is needed here: these check what is sent.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import router as router_mod
from nemo.config import Config
from nemo.router import Router

REPLY = {"choices": [{"message": {"content": "Text."}}]}


class Sent(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load(Path("/nonexistent"))
        self.bodies = []

        def post(url, payload, key, timeout):
            self.bodies.append(payload)
            return REPLY
        p = mock.patch.object(router_mod, "_post", post)
        p.start(); self.addCleanup(p.stop)


class TestThinkingOff(Sent):
    def test_a_story_request_switches_thinking_off(self):
        Router(self.cfg).ask("story", "system", "user", max_tokens=220)
        self.assertEqual(self.bodies[0].get("chat_template_kwargs"),
                         {"enable_thinking": False})
        self.assertEqual(self.bodies[0]["max_tokens"], 220)

    def test_a_task_that_is_not_listed_is_sent_as_before(self):
        Router(self.cfg).ask("something_else", "system", "user")
        self.assertNotIn("chat_template_kwargs", self.bodies[0])

    def test_the_design_tasks_are_listed_too(self):
        # D129: with reasoning on, the electrical step ran its whole 900 s
        # on the real laptop and returned nothing.
        for task in ("template_fill", "cad_script", "firmware"):
            self.bodies.clear()
            self.cfg.data["routing"][task] = "local"
            Router(self.cfg).ask(task, "system", "user")
            self.assertEqual(self.bodies[0].get("chat_template_kwargs"),
                             {"enable_thinking": False}, task)
        self.assertNotIn("design_reason", self.cfg.get("engine.thinking_off"))

    def test_the_default_limit_covers_a_full_reply_from_the_talk_model(self):
        # 2048 tokens at the measured 2.0 tokens/s is 1024 s, plus the prompt.
        self.assertGreaterEqual(self.cfg.get("engine.timeout_s"), 1024 + 300)

    def test_the_owner_can_turn_it_back_on_or_add_a_task(self):
        self.cfg.data["engine"]["thinking_off"] = []
        Router(self.cfg).ask("story", "s", "u")
        self.assertNotIn("chat_template_kwargs", self.bodies[0])
        self.cfg.data["engine"]["thinking_off"] = ["template_fill"]
        Router(self.cfg).ask("template_fill", "s", "u")
        self.assertIn("chat_template_kwargs", self.bodies[1])

    def test_a_config_file_without_the_setting_still_gets_the_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "config.yaml"
            f.write_text("engine:\n  timeout_s: 60\n", encoding="utf-8")
            cfg = Config.load(f)
        self.assertEqual(cfg.get("engine.thinking_off")[0], "story")
        self.assertEqual(cfg.get("engine.timeout_s"), 60)

    def test_a_missing_or_null_setting_is_not_a_crash(self):
        self.cfg.data["engine"]["thinking_off"] = None
        Router(self.cfg).ask("story", "s", "u")
        self.assertNotIn("chat_template_kwargs", self.bodies[0])

    def test_the_local_draft_of_a_reviewed_task_follows_the_same_rule(self):
        self.cfg.data["routing"]["story"] = "local_then_review"
        with mock.patch.object(Router, "review", side_effect=OSError("offline")):
            try:
                Router(self.cfg).ask("story", "s", "u")
            except OSError:
                pass
        self.assertIn("chat_template_kwargs", self.bodies[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
