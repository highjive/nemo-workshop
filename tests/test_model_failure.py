"""A model call that fails is a failed step that says why, not a traceback.

D125, from the first real pipeline run on the AH531 (2026-10-05). The
electrical step asked the Talk model for a schematic. Fifteen minutes later
the 900 s limit passed with the model still writing, and `nemo run` ended
in a sixty-line traceback: `TimeoutError: timed out`. No result was saved
for the step, `--keep-going` made no difference, and nothing told the
owner what had happened or what to change.
"""
from __future__ import annotations

import io, os, socket, sys, tempfile, unittest, urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.pipeline import Pipeline
from nemo.project import Brief
from nemo.router import ModelCallFailed, RouterError, explain_failure
from test_pipeline import PipelineCase


class FailingRouter:
    timeout = 900

    def __init__(self, exc):
        self.exc = exc

    def ask(self, *a, **k):
        raise self.exc

    def local_up(self):
        return True


class TestExplainFailure(unittest.TestCase):
    def test_a_timeout_names_the_limit_and_what_to_change(self):
        for exc in (TimeoutError("timed out"), socket.timeout("timed out"),
                    urllib.error.URLError(TimeoutError("timed out"))):
            why = explain_failure(exc, 900)
            self.assertIn("900 s", why)
            self.assertIn("engine.timeout_s", why)
            self.assertIn("Nothing was written", why)

    def test_a_server_that_went_away(self):
        # Refused outright is no model at all (2026-11-04); this said it had
        # "stopped answering", which it never began.
        why = explain_failure(urllib.error.URLError(ConnectionRefusedError(10061, "refused")), 900)
        self.assertIn("No language model is loaded", why); self.assertIn("nemo mode", why)
        dropped = explain_failure(urllib.error.URLError(ConnectionResetError(10054, "reset")), 900)
        self.assertIn("stopped answering", dropped); self.assertIn("nemo mode", dropped)

    def test_a_router_error_keeps_its_own_words(self):
        self.assertIn("no remote model configured",
                      explain_failure(RouterError("no remote model configured"), 900))

    def test_a_bug_is_not_explained_away(self):
        for exc in (ValueError("x"), KeyError("y"), AttributeError("z"), ZeroDivisionError()):
            self.assertIsNone(explain_failure(exc, 900))


class TestAStageTurnsItIntoItsOwnError(PipelineCase):
    def _seed(self):
        self.project.create(Brief(
            name="t", function="Reads an RFID card.", power="USB 5 V 1 A", supply_ma=1000,
            rails=[5.0, 3.3], envelope_mm=[140, 100, 70],
            parts=["esp32_devkit_v1", "rc522"], mcu="esp32", done_when="reads a card"))

    def test_a_timeout_in_the_electrical_step(self):
        self._seed()
        pipe = Pipeline(self.project, self.cfg, FailingRouter(TimeoutError("timed out")), self.lib)
        with self.assertRaises(ModelCallFailed) as ctx:
            pipe.stage_electrical()
        self.assertIn("900 s", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, TimeoutError)   # the real cause is kept

    def test_a_bug_inside_the_router_still_raises_as_itself(self):
        self._seed()
        pipe = Pipeline(self.project, self.cfg, FailingRouter(ZeroDivisionError()), self.lib)
        with self.assertRaises(ZeroDivisionError):
            pipe.stage_electrical()


class TestTheCommandsReportIt(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        from nemo.config import Config
        from nemo.project import Project
        cfg = Config.load(Path("/nonexistent"))
        self.root = cfg.path("paths.projects") / "t"
        Project(self.root).create(Brief(
            name="t", function="Reads an RFID card.", power="USB 5 V 1 A", supply_ma=1000,
            rails=[5.0, 3.3], envelope_mm=[140, 100, 70],
            parts=["esp32_devkit_v1", "rc522"], mcu="esp32", done_when="reads a card"))
        # The Reviewer lets a step start only on the one it builds on: the
        # parts step has passed, as it would have in a real run.
        from nemo.pipeline import StageResult
        from nemo.results import save_result
        save_result(self.root, StageResult("parts", True))

    def tearDown(self):
        self._env.stop(); self.t.cleanup()

    def run_cli(self, *a, exc=TimeoutError("timed out")):
        from nemo import cli
        out = io.StringIO()
        with redirect_stdout(out), \
             mock.patch("nemo.router.Router.local_up", return_value=True), \
             mock.patch("nemo.router.Router.ask", side_effect=exc):
            try:
                rc = cli.main(list(a))
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 1
        return rc, out.getvalue()

    def test_run_shows_a_failed_step_with_the_reason_and_saves_it(self):
        rc, out = self.run_cli("--project", "t", "run", "--from", "electrical")
        self.assertEqual(rc, 1)
        self.assertIn("=== electrical", out)
        self.assertRegex(out, r"had not finished after \d+ s")
        self.assertNotIn("Traceback", out)
        from nemo.results import load_results
        saved = load_results(self.root)
        self.assertIn("electrical", str(saved))
        self.assertIn("had not finished", str(saved))

    def test_keep_going_really_keeps_going(self):
        rc, out = self.run_cli("--project", "t", "run", "--from", "electrical", "--keep-going")
        for stage in ("electrical", "wiring", "enclosure", "firmware", "pack"):
            self.assertIn(f"--- {stage} ---", out, stage)
        self.assertNotIn("Traceback", out)

    def test_draft_reports_it(self):
        rc, out = self.run_cli("--project", "t", "draft", "a thing that beeps")
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"had not finished after \d+ s")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestARefusalIsSaidAsOne(unittest.TestCase):
    """D177, the AH531 on 2026-10-16: llama-server answered step 3 with 400
    Bad Request. The window said the model had "stopped answering part way
    through", which it had not, and threw away the server's reason."""

    def refused(self, body=b'{"error":{"code":400,"message":"failed to parse grammar","type":"invalid_request_error"}}'):
        return urllib.error.HTTPError("http://127.0.0.1:8080/v1/chat/completions", 400,
                                      "Bad Request", {}, io.BytesIO(body))

    def test_the_servers_reason_is_shown(self):
        msg = explain_failure(self.refused(), 900)
        self.assertIn("failed to parse grammar", msg)
        self.assertIn("400", msg)
        self.assertNotIn("stopped answering", msg)

    def test_a_body_that_is_not_json_is_still_shown(self):
        msg = explain_failure(self.refused(b"context too long"), 900)
        self.assertIn("context too long", msg)

    def test_the_refused_request_is_kept(self):
        from nemo import router as R
        from nemo.config import Config
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.dict(os.environ, {"NEMO_HOME": home}), \
             mock.patch.object(R, "_post", side_effect=self.refused()):
            with self.assertRaises(urllib.error.HTTPError):
                R.Router(Config.load(Path("/nonexistent")))._call_local(
                    [{"role": "user", "content": "q"}], 0.2, 10, schema={"type": "object"})
            kept = Path(home) / "refused-request.json"
            self.assertTrue(kept.exists())
            self.assertIn("json_schema", kept.read_text(encoding="utf-8"))
