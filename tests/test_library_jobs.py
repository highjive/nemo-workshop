"""The Library's jobs built when it was gone through (owner, 2026-10-21):
the Timekeeper, the Researcher, the Archivist and the Foreman, and the tools
check (`nemo staff`) that found them missing.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import archivist, cli, facts, foreman, staff, timekeeper, toolkit

# The form llama-server wrote on the AH531 (talk.log, 2026-10-21).
LOG = """\
1.00.325.439 I slot print_timing: id  0 | task 0 | prompt eval time =   54489.81 ms /   162 tokens (  336.36 ms per token,     2.97 tokens per second)
1.00.325.455 I slot print_timing: id  0 | task 0 |        eval time =     669.38 ms /     2 tokens (  669.38 ms per token,     1.49 tokens per second)
1.00.325.458 I slot print_timing: id  0 | task 0 |       total time =   55159.18 ms /   164 tokens
some other line
1.53.711.148 I slot print_timing: id  0 | task 3 | prompt eval time =   52730.00 ms /   157 tokens (  335.86 ms per token,     2.98 tokens per second)
1.53.711.166 I slot print_timing: id  0 | task 3 |        eval time =     609.51 ms /     2 tokens (  609.51 ms per token,     1.64 tokens per second)
1.53.711.168 I slot print_timing: id  0 | task 3 |       total time =   53339.51 ms /   159 tokens
"""


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self.patches = [mock.patch.dict(os.environ, _sandbox.home_env(self.home)),
                        mock.patch("nemo.config.CONFIG_HOME", self.home / ".nemo"),
                        mock.patch("nemo.modes.STATE", self.home / ".nemo" / "mode.pid")]
        for p in self.patches:
            p.start()
        (self.home / ".nemo").mkdir()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        archivist.drop()
        self.t.cleanup()

    @property
    def cfg(self):
        from nemo.config import Config
        return Config.load(Path("/nonexistent"))


class TestTheTimekeeper(AHome):
    def test_the_server_s_own_figures(self):
        (self.home / ".nemo" / "talk.log").write_text(LOG, encoding="utf-8")
        (self.home / ".nemo" / "design.log").write_text("no timings here\n", encoding="utf-8")
        found = timekeeper.times()
        self.assertEqual([t.mode for t in found], ["talk"])
        t = found[0]
        self.assertEqual(len(t.requests), 2)
        self.assertAlmostEqual(t.reading, (162 + 157) / ((54489.81 + 52730.00) / 1000), places=4)
        self.assertAlmostEqual(t.total_s, (55159.18 + 53339.51) / 1000, places=4)
        self.assertIn("talk", timekeeper.describe(found))

    def test_nothing_measured_says_so(self):
        self.assertIn("No model timings yet", timekeeper.describe(timekeeper.times()))


class TestTheResearcher(AHome):
    def fake_wikipedia(self, url):
        if "list=search" in url:
            return {"query": {"search": [{"title": "Lighthouse keeper"}]}}
        return {"title": "Lighthouse keeper", "extract": "A person who tends a lighthouse.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Lighthouse_keeper"}}}

    def test_only_the_words_are_sent(self):
        with mock.patch.object(facts, "_get", side_effect=self.fake_wikipedia) as get:
            found = facts.look_up("  lighthouse   keeper ")
        self.assertEqual(found[0].title, "Lighthouse keeper")
        self.assertIn("srsearch=lighthouse+keeper", get.call_args_list[0][0][0])
        self.assertTrue(all(u[0][0].startswith("https://en.wikipedia.org/")
                            for u in get.call_args_list))
        self.assertNotIn("@", facts.AGENT)                  # no address of the owner's

    def test_no_connection_says_so(self):
        import urllib.error
        with mock.patch.object(facts, "_get", side_effect=urllib.error.URLError("no route")):
            with self.assertRaises(facts.LookupError_) as cm:
                facts.look_up("lighthouse")
        self.assertIn("needs a connection", str(cm.exception))

    def test_kept_with_the_story(self):
        story = self.home / "nemo-stories" / "fox"
        story.mkdir(parents=True)
        f = facts.Fact("Red fox", "A fox.", "https://en.wikipedia.org/wiki/Red_fox")
        facts.keep(story, "red fox", [f])
        facts.keep(story, "den", [])
        text = (story / "research.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("# What the Researcher found"), 1)
        self.assertIn("**Red fox**: A fox.", text)
        self.assertIn("## den", text)


class TestTheArchivist(AHome):
    def setUp(self):
        super().setUp()
        self.patches.append(mock.patch.dict(os.environ, {"NEMO_ARCHIVE": ""}))
        self.patches[-1].start()

    def router(self):
        from nemo.router import Router
        return Router(self.cfg)

    def ask(self, r, user="Which pin?", answer='{"pin": "D4"}'):
        with mock.patch("nemo.router._post",
                        return_value={"choices": [{"message": {"content": answer}}]}) as post:
            reply = r.ask("wiring", "You choose pins.", user, schema={"type": "object"})
        return reply, post

    def test_a_passed_step_s_answer_is_reused_for_the_same_request_only(self):
        r = self.router()
        archivist.begin()
        reply, post = self.ask(r)
        self.assertEqual((reply.source, post.call_count), ("local", 1))
        self.assertEqual(archivist.keep("wiring"), 1)
        again, post = self.ask(r, answer="SHOULD NOT BE ASKED")
        self.assertEqual((again.source, again.text, post.call_count), ("archive", '{"pin": "D4"}', 0))
        other, post = self.ask(r, user="Which pin for the LED?")
        self.assertEqual((other.source, post.call_count), ("local", 1))

    def test_a_failed_step_s_answer_is_not_kept(self):
        r = self.router()
        archivist.begin()
        self.ask(r)
        archivist.drop()
        self.assertEqual(archivist.count(), 0)
        self.assertEqual(self.ask(r)[1].call_count, 1)

    def test_another_model_is_asked_afresh(self):
        r = self.router()
        archivist.begin(); self.ask(r); archivist.keep("wiring")
        from nemo.modes import ModeStatus
        with mock.patch("nemo.modes.current", return_value=ModeStatus("design", 1, "qwen3-4b")):
            self.assertEqual(self.ask(r)[1].call_count, 1)

    def test_turned_off_it_neither_keeps_nor_reuses(self):
        r = self.router()
        archivist.begin(); self.ask(r); archivist.keep("wiring")
        with mock.patch.dict(os.environ, {"NEMO_ARCHIVE": "off"}):
            self.assertEqual(self.ask(r)[1].call_count, 1)
        self.assertEqual(archivist.clear(), 1)
        self.assertEqual(archivist.count(), 0)

    def test_the_step_loop_keeps_on_pass_and_drops_on_fail(self):
        from nemo import workflow
        from nemo.pipeline import StageResult
        project = mock.Mock(root=self.home / "p")
        for ok, kept in ((True, 1), (False, 0)):
            archivist.clear()
            pipe = mock.Mock()
            pipe.stage_wiring.side_effect = lambda ok=ok: (
                archivist.note("k", "answer", "wiring"), StageResult("wiring", ok))[1]
            with mock.patch("nemo.review.before", return_value=([], [])), \
                 mock.patch("nemo.review.record"), \
                 mock.patch("nemo.review.researchable", return_value=[]):
                workflow.run_step("wiring", project, pipe, [], lambda s: None)
            self.assertEqual(archivist.count(), kept, ok)


class TestTheForeman(AHome):
    def jobs(self):
        J = foreman.Job
        return [foreman.step_job("lamp", "electrical"), J("story", "fox", "write", "talk", []),
                foreman.step_job("lamp", "wiring"), foreman.step_job("fan", "electrical"),
                J("story", "owl", "write", "talk", []), foreman.step_job("lamp", "firmware")]

    def test_fewer_loads_and_each_project_in_its_own_order(self):
        q = self.jobs()
        o = foreman.order(q)
        self.assertEqual((foreman.loads(q), foreman.loads(o)), (5, 3))
        lamp = [j.what for j in o if j.owner == "lamp"]
        self.assertEqual(lamp, ["electrical", "wiring", "firmware"])
        # A model already loaded is used first.
        self.assertEqual(foreman.order(q, loaded="talk")[0].owner, "fox")

    def test_a_job_with_no_model_never_loads_one(self):
        J = foreman.Job
        q = [J("cover", "fox", "cover", None, []), foreman.step_job("lamp", "parts")]
        self.assertEqual(foreman.loads(foreman.order(q)), 0)

    def test_running_it(self):
        foreman.save(self.jobs())
        loaded, said = [], []
        def run_job(j):
            return not (j.owner == "lamp" and j.what == "wiring")      # lamp's wiring fails
        done = foreman.run(self.cfg, say=said.append,
                           start_mode=lambda m: (loaded.append(m) or True, ""), run_job=run_job)
        # lamp's firmware is skipped after its wiring failed, so the build
        # model, wanted by nothing else, is never loaded.
        self.assertEqual(loaded, ["design", "talk"])
        result = {j.label: ok for j, ok in done}
        self.assertFalse(result["lamp: firmware"])                     # skipped, not run
        self.assertTrue(result["fan: electrical"])
        self.assertTrue(any("skipped lamp: firmware" in s for s in said))
        self.assertEqual(foreman.load(), [])

    def test_a_model_that_will_not_load_stops_it_and_keeps_the_rest(self):
        foreman.save(self.jobs())
        done = foreman.run(self.cfg, say=lambda s: None,
                           start_mode=lambda m: (False, "too little memory"),
                           run_job=lambda j: True)
        self.assertEqual(done, [])
        self.assertEqual(len(foreman.load()), 6)

    def test_the_command(self):
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(["queue", "add", "lamp", "electrical", "wiring"])
            cli.main(["queue", "story", "fox"])
            cli.main(["queue"])
        self.assertIn("3 job(s)", out.getvalue())
        self.assertIn("lamp: electrical", out.getvalue())
        with redirect_stdout(io.StringIO()):
            cli.main(["queue", "clear"])
        self.assertEqual(foreman.load(), [])


class TestTheToolsCheck(AHome):
    def test_every_library_employee_is_checked(self):
        rows = toolkit.check(self.cfg, "library")
        self.assertEqual({r.employee for r in rows},
                         {e.key for e in staff.team("library")})

    def test_a_job_not_built_is_not_ready(self):
        need = toolkit.not_built("a thing")
        self.assertEqual(need.check(None), (False, "not built yet: a thing"))

    def test_a_check_that_breaks_is_missing_not_a_crash(self):
        def broken(cfg):
            raise OSError("disk gone")
        with mock.patch.dict(toolkit.NEEDS, {"library.editor": (toolkit.Need("x", broken),)}):
            row = next(r for r in toolkit.check(self.cfg, "library") if r.employee == "library.editor")
        self.assertFalse(row.ok)
        self.assertIn("disk gone", row.detail)

    def test_looking_makes_nothing(self):
        before = sorted(p for p in self.home.rglob("*"))
        toolkit.check(self.cfg, "library")
        self.assertEqual(sorted(p for p in self.home.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
