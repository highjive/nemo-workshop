"""Tests for the desktop interface.

The logic (controller) is tested with no display at all. The window itself
is exercised only when a display is available, and skipped otherwise.
"""
from __future__ import annotations

import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.gui import controller as C
from nemo.project import Brief


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self._env = mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home),
                                                 "NEMO_HOME": str(home / ".nemo")})
        self._env.start()
        self.cfg = C.config()

    def tearDown(self):
        self._env.stop(); self.tmp.cleanup()


class TestProjects(Env):
    def test_create_and_list(self):
        C.create_project("Treasure chest player", self.cfg)
        self.assertEqual(C.list_projects(self.cfg), ["treasure-chest-player"])
        self.assertEqual(C.display_name("treasure-chest-player", self.cfg),
                         "Treasure chest player")

    def test_names_that_would_escape_the_folder_are_refused(self):
        for bad in ("", "../etc", "a/b", "x" * 60, ".hidden"):
            self.assertIsNotNone(C.validate_name(bad), bad)

    def test_duplicate_is_refused(self):
        C.create_project("Chest", self.cfg)
        with self.assertRaises(ValueError):
            C.create_project("chest", self.cfg)

    def test_brief_problems_are_plain_words(self):
        missing = C.brief_problems(Brief(name="x"))
        self.assertIn("the power source", missing)
        self.assertIn("the supply rating in mA", missing)

    def test_number_parsing_accepts_how_people_type(self):
        self.assertEqual(C.parse_numbers("140 x 100 x 70"), [140, 100, 70])
        self.assertEqual(C.parse_numbers("5, 3.3"), [5, 3.3])
        self.assertEqual(C.parse_numbers(""), [])


class TestSteps(Env):
    def test_fresh_project_state(self):
        p = C.create_project("P", self.cfg)
        rows = C.step_rows(p)
        self.assertEqual([r.stage for r in rows][0], "brief")
        self.assertEqual(rows[0].status, "done")
        self.assertTrue(all(r.status == "not run" for r in rows[1:]))
        self.assertEqual(C.next_step(p), "parts")

    def test_skipped_checks_are_not_shown_as_passed(self):
        p = C.create_project("P", self.cfg)
        (p.root / ".nemo").mkdir(exist_ok=True)
        (p.root / ".nemo" / "results.json").write_text(json.dumps({
            "electrical": {"ok": True, "when": 1, "checks": [
                {"name": "erc", "status": "SKIP", "detail": "", "items": []}]}}))
        row = next(r for r in C.step_rows(p) if r.stage == "electrical")
        self.assertEqual(row.status, "unchecked")

    def test_failed_step_is_next(self):
        p = C.create_project("P", self.cfg)
        (p.root / ".nemo").mkdir(exist_ok=True)
        (p.root / ".nemo" / "results.json").write_text(json.dumps({
            "parts": {"ok": False, "when": 1, "checks": []}}))
        self.assertEqual(C.next_step(p), "parts")

    def test_model_steps_are_marked(self):
        rows = {r.stage: r for r in C.step_rows(C.create_project("P", self.cfg))}
        self.assertTrue(rows["electrical"].needs_model)
        self.assertFalse(rows["parts"].needs_model)
        self.assertFalse(rows["pack"].needs_model)


class TestWords(unittest.TestCase):
    def test_every_check_has_a_plain_name(self):
        import re
        root = Path(__file__).resolve().parent.parent / "nemo"
        names = set()
        for f in list((root / "checks").glob("*.py")) + [root / "pipeline.py"]:
            # (?<!Stage): StageResult names steps, not checks.
            names |= set(re.findall(r'(?<!Stage)Result\(\s*"(\w+)"', f.read_text()))
            names |= set(re.findall(r'_missing\(\s*"(\w+)"', f.read_text()))
        missing = sorted(n for n in names if n not in C.CHECK_NAMES)
        self.assertEqual(missing, [], "checks with no plain-language name")

    def test_finding_lines_lose_their_rule_ids(self):
        self.assertEqual(
            C.plain_item("note  enclosure_vent_required_above_ma: 560 mA exceeds 500 mA"),
            "Note: 560 mA exceeds 500 mA")
        self.assertTrue(C.plain_item("BLOCK  max_design_voltage_v: 230 V").startswith("Blocked"))
        self.assertEqual(C.plain_item("rc522: 100 mA"), "rc522: 100 mA")


class TestSignoffs(Env):
    def test_gates_always_present(self):
        keys = [k for k, _ in C.signoff_items(C.create_project("P", self.cfg))]
        for gate in ("gate_print", "gate_order", "gate_battery"):
            self.assertIn(gate, keys)

    def test_safety_signoffs_are_added(self):
        p = C.create_project("P", self.cfg)
        (p.root / ".nemo").mkdir(exist_ok=True)
        (p.root / ".nemo" / "safety.json").write_text(json.dumps([
            {"severity": "signoff", "rule": "lipo_forbids_sealed_enclosure",
             "detail": "cell must not be sealed"},
            {"severity": "note", "rule": "x", "detail": "just a note"}]))
        texts = [t for _, t in C.signoff_items(p)]
        self.assertIn("cell must not be sealed", texts)
        self.assertNotIn("just a note", texts)

    def test_signing_needs_a_name(self):
        p = C.create_project("P", self.cfg)
        with self.assertRaises(ValueError):
            C.set_signoff(p, "gate_print", "  ", True)

    def test_sign_and_withdraw_are_recorded_and_audited(self):
        from nemo.admin import AdminStore
        from nemo.authority import store_dir
        p = C.create_project("P", self.cfg)
        C.set_signoff(p, "gate_print", "Highjive", True)
        self.assertEqual(C.signoffs(p)["gate_print"]["by"], "Highjive")
        C.set_signoff(p, "gate_print", "Highjive", False)
        self.assertNotIn("gate_print", C.signoffs(p))
        events = [e["event"] for e in AdminStore(store_dir()).audit_entries(10)]
        self.assertIn("signoff", events)
        self.assertIn("signoff_withdrawn", events)
        self.assertTrue(AdminStore(store_dir()).verify_audit()[0])


class TestRunning(unittest.TestCase):
    def test_children_use_python_not_pythonw(self):
        with mock.patch.object(sys, "executable", r"C:\Nemo\venv\Scripts\pythonw.exe"), \
             mock.patch("os.path.exists", return_value=True):
            self.assertTrue(C.python_for_children().lower().endswith("python.exe"))

    def test_argv_is_unbuffered_module_call(self):
        argv = C.nemo_argv("run", "--only", "parts")
        self.assertEqual(argv[1:4], ["-u", "-m", "nemo.cli"])

    def test_events_parse_and_ordinary_lines_do_not(self):
        self.assertEqual(C.parse_event('@@NEMO {"stage": "parts"}'), {"stage": "parts"})
        self.assertIsNone(C.parse_event("PASS current_sum"))
        self.assertIsNone(C.parse_event("@@NEMO {broken"))

    def test_stop_ends_a_real_job(self):
        import time
        from nemo.gui.worker import Job
        j = Job([sys.executable, "-c", "import time; print('go', flush=True); time.sleep(60)"]).start()
        t = time.time()
        while j.lines.empty() and time.time() - t < 10:
            time.sleep(0.05)
        j.stop()
        t = time.time()
        while j.running and time.time() - t < 10:
            time.sleep(0.05)
        self.assertFalse(j.running)
        self.assertTrue(j.stopped)


class TestPlatformIOBoard(unittest.TestCase):
    """D58: the pendant's ESP32-S3 board compiled for the plain ESP32."""
    def test_boards(self):
        from nemo.pipeline import pio_board
        self.assertEqual(pio_board("waveshare_esp32s3_lcd_128"), "esp32-s3-devkitc-1")
        self.assertEqual(pio_board("esp32_devkit_v1"), "esp32dev")
        self.assertEqual(pio_board("rp2040"), "pico")


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestWindow(Env):
    def test_window_opens_with_and_without_projects(self):
        try:
            from nemo.gui.app import NemoApp
        except ImportError:
            self.skipTest("tkinter not installed")
        app = NemoApp(); app.update()
        self.assertTrue(app.empty.winfo_ismapped())       # no projects: invitation
        app.destroy()
        C.create_project("P", self.cfg)
        app = NemoApp(); app.update()
        self.assertTrue(app.tabs.winfo_ismapped())
        self.assertEqual(len(app.traveller.rows), 8)   # with the Concept step (2026-10-20)
        app.destroy()


class _FakeJob:
    """A job with no process behind it: running until told otherwise."""
    started = []

    def __init__(self, argv=None, cwd=None):
        self.argv, self.returncode, self.stopped, self.elapsed = argv, None, False, 0.0

    def start(self):
        _FakeJob.started.append(self)
        return self

    @property
    def running(self):
        return self.returncode is None

    def drain(self):
        return []

    def stop(self):
        self.stopped = True


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestModelLoadAfterARun(Env):
    """D174: a run stops at a step that needs the model, the owner says yes
    to loading one, and the window never came back: the job that loads it
    was started and forgotten in the same breath."""

    def setUp(self):
        super().setUp()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        C.create_project("P", self.cfg)
        _FakeJob.started = []
        self.app = A.NemoApp(); self.app.update()
        self.addCleanup(self.app.destroy)

    def tick(self):
        self.app.after_cancel(self.app._timers["job"])     # ours replaces it
        self.app._tick_job()

    def test_the_mode_job_is_kept_and_its_end_frees_the_window(self):
        A, app = self.A, self.app
        run = _FakeJob(); run.returncode = 3
        app.job, app.job_kind = run, "run"
        app.pending_after_job = ("needs_model", "electrical", "talk")
        with mock.patch.object(A, "Job", _FakeJob), \
             mock.patch.object(A.messagebox, "askyesno", return_value=True), \
             mock.patch.object(A.messagebox, "showwarning") as warned:
            self.tick()
            self.assertEqual(len(_FakeJob.started), 1)
            mode = _FakeJob.started[0]
            self.assertEqual(mode.argv[-2:], ["mode", "talk"])
            self.assertIs(app.job, mode)                    # was None: forgotten
            self.assertEqual(str(app.btn_run.cget("state")), "disabled")
            app.stop_job()
            self.assertTrue(mode.stopped)                   # Stop reaches it
            mode.stopped, mode.returncode = False, 1        # no model on disk
            self.tick()
            warned.assert_called_once()
        self.assertIsNone(app.job)
        self.assertEqual(str(app.btn_run.cget("state")), "normal")
        self.assertEqual(str(app.btn_stop.cget("state")), "disabled")

    def test_a_run_that_simply_ends_leaves_no_job(self):
        app = self.app
        run = _FakeJob(); run.returncode = 0
        app.job, app.job_kind = run, "run"
        self.tick()
        self.assertIsNone(app.job)
        self.assertEqual(str(app.btn_run.cget("state")), "normal")


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestAdviceOpensTheBrief(Env):
    """D175: advice whose remedy is a value in the brief left both buttons
    grey, so the owner could not see how to go on. It now opens the brief."""

    def setUp(self):
        super().setUp()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        from nemo.fixes import Fix
        self.app = A.NemoApp(); self.app.update()
        self.addCleanup(self.app.destroy)
        self.app._fixes = [Fix("brief_supply", "Give the supply rating", "why",
                               "info", brief_field="supply_ma"),
                           Fix("tool_erc", "'erc' could not run", "why", "info")]
        for f in self.app._fixes:
            self.app.fix_list.insert("end", f.title)

    def pick(self, i):
        self.app.fix_list.selection_clear(0, "end")
        self.app.fix_list.selection_set(i)
        self.app._fix_selected()

    def test_brief_advice_has_a_working_button(self):
        app = self.app
        self.pick(0)
        self.assertEqual(str(app.btn_fix.cget("state")), "normal")
        self.assertEqual(app.btn_fix.cget("text"), "Open the brief")
        app.project = object()                 # apply_fix needs one open
        app.apply_fix(False)
        app.update()
        self.assertEqual(app.tabs.select(), str(app.tab_brief))

    def test_other_advice_stays_advice(self):
        self.pick(1)
        self.assertEqual(str(self.app.btn_fix.cget("state")), "disabled")
        self.assertEqual(self.app.btn_fix.cget("text"), "Apply only")
