"""The Computer Lab, gone through (owner, 2026-10-21): the Tester compiles a
project's firmware on its own and reads the build; the Technician loads the
next step's model ahead, only where it fits.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import staff, technician, tester, toolkit
from nemo.checks import FAIL, PASS, Result
from nemo.modes import ModeStatus
from nemo.project import Brief, Project

# PlatformIO's own size lines, in the form it prints them.
SIZE = ["RAM:   [=         ]   6.5% (used 21312 bytes from 327680 bytes)",
        "Flash: [==        ]  20.4% (used 267401 bytes from 1310720 bytes)"]


class AProject(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t))
        self._env.start()
        self.project = Project(self.t / "lamp")
        self.project.create(Brief(name="lamp", parts=["esp32_devkit_v1"], mcu="esp32_devkit_v1"))
        fw = self.project.firmware
        fw.mkdir(parents=True, exist_ok=True)
        (fw / "platformio.ini").write_text("[env:esp32dev]\nplatform = espressif32@7.1.3\n"
                                           "board = esp32dev\nframework = arduino\n", encoding="utf-8")

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.t, ignore_errors=True)


class TestTheTester(AProject):
    def fake_compile(self, status, items=(), log=""):
        def run(fw):
            (Path(fw) / "build.log").write_text(log, encoding="utf-8")
            return Result("compile", status, "builds clean" if status == PASS else "build failed",
                          list(items))
        return mock.patch("nemo.checks.runners.compile_firmware", side_effect=run)

    def test_a_clean_build_is_read(self):
        log = "src/main.cpp:4:5: warning: unused variable 'x'\n" + "\n".join(SIZE)
        with self.fake_compile(PASS, SIZE, log), \
             mock.patch("nemo.offline.record_build") as recorded:
            results = tester.test(self.project)
        got = {r.name: r for r in results}
        self.assertEqual(got["compile"].status, PASS)
        self.assertEqual(got["warnings"].detail, "1 compiler warning(s)")
        self.assertEqual(got["ram_use"].detail, "RAM 6.5%: 21312 of 327680 bytes")
        self.assertEqual(got["flash_use"].status, PASS)
        recorded.assert_called_once_with("esp32dev", True)
        rec = json.loads((self.project.root / ".nemo" / "test.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["results"][0]["name"], "compile")

    def test_a_full_board_fails_and_a_tight_one_is_said(self):
        full = ["RAM:   [==========]  97.0% (used 317800 bytes from 327680 bytes)",
                "Flash: [========  ]  85.0% (used 1114112 bytes from 1310720 bytes)"]
        with self.fake_compile(PASS, full, "\n".join(full)), mock.patch("nemo.offline.record_build"):
            got = {r.name: r for r in tester.test(self.project)}
        self.assertEqual(got["ram_use"].status, FAIL)
        self.assertIn("tight", got["flash_use"].detail)

    def test_a_failed_build_is_not_recorded_as_built(self):
        with self.fake_compile(FAIL, ["src/main.cpp:1: error: x"], "error"), \
             mock.patch("nemo.offline.record_build") as recorded:
            results = tester.test(self.project)
        self.assertEqual([r.name for r in results], ["compile"])
        recorded.assert_not_called()

    def test_reading_the_size_lines(self):
        self.assertEqual(tester.memory(SIZE), {"RAM": (6.5, 21312, 327680),
                                               "Flash": (20.4, 267401, 1310720)})
        self.assertEqual(tester.board_of(self.project.firmware), "esp32dev")


class TestTheTechnician(AProject):
    def plan(self, current=ModeStatus(None, None, None), free=8000, held=0, done=()):
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))
        from nemo.results import save_result
        from nemo.pipeline import StageResult
        for s in done:
            save_result(self.project.root, StageResult(s, True))
        with mock.patch("nemo.modes.current", return_value=current), \
             mock.patch("nemo.platform_probe.mem_available_mb", return_value=free), \
             mock.patch("nemo.platform_probe.process_rss_mb", return_value=held):
            return technician.plan(cfg, self.project)

    def test_the_next_step_s_model(self):
        p = self.plan(done=("parts",))
        self.assertEqual(p.mode, "design")                 # electrical is next
        self.assertIn("electrical", p.why)

    def test_nothing_to_load(self):
        p = self.plan()                                    # parts is next: no model
        self.assertIsNone(p.mode)
        self.assertIn("needs no model", p.why)
        p = self.plan(done=("parts",), current=ModeStatus("design", os.getpid(), "q"))
        self.assertIsNone(p.mode)                          # design is loaded already
        self.assertIn("loaded already", p.why)

    def test_never_one_that_will_not_fit(self):
        p = self.plan(done=("parts",), free=500)
        self.assertIsNone(p.mode)
        self.assertIn("only 500 MB", p.why)

    def test_the_loaded_model_s_memory_counts_as_coming_back(self):
        p = self.plan(done=("parts",), free=2000, held=2100,
                      current=ModeStatus("talk", os.getpid(), "q"))
        self.assertEqual(p.mode, "design")


class TestTheRoster(unittest.TestCase):
    def test_built_and_checked(self):
        for key in ("computer_lab.tester", "computer_lab.technician"):
            self.assertTrue(staff.STAFF[key].working, key)
            self.assertTrue(toolkit.NEEDS[key], key)
        self.assertTrue(staff.STAFF["computer_lab.writer"].working)    # 2026-10-22
        for key in ("computer_lab.designer", "computer_lab.foreman", "computer_lab.timekeeper"):
            self.assertFalse(staff.STAFF[key].working, key)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestLoadAhead(unittest.TestCase):
    def test_after_a_run_it_loads_the_next_model_unless_switched_off(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                app.project = mock.Mock()
                with mock.patch("nemo.technician.plan",
                                return_value=technician.Plan("design", "loading the design model")), \
                     mock.patch.object(app, "start_job") as job:
                    self.assertIsNotNone(app.load_next_model())
                    self.assertEqual(job.call_args[0][1], "ahead")
                    self.assertIn("design", job.call_args[0][0])
                    app.load_ahead.set(False); app._ahead_switched()
                    self.assertIsNone(app.load_next_model())
                    self.assertEqual(job.call_count, 1)
                from nemo.gui import controller as C
                self.assertIs(C.load_settings()["load_ahead"], False)
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
