"""The Doctors, phase 1: diagnosis and advice only (owner, 2026-10-21).

The owner's words: "within department can diagnose and suggest to errors
only with user agreement". These tests hold the Doctors to reading only, to
saying "not known" rather than guessing, to the same figures the rest of
Nemo decides by, and to keeping case notes of every visit.
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import clinic, cli, modes, router, staff
from nemo.modes import ModeStatus

NOBODY = ()          # examine(who=NOBODY): no specialist at all


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.home))
        self._env.start()
        self._ch = mock.patch("nemo.config.CONFIG_HOME", self.home / ".nemo")
        self._ch.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def tearDown(self):
        self._ch.stop(); self._env.stop(); self.t.cleanup()

    def write(self, rel: str, text: str) -> Path:
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def failed_step(self, project: str, step: str, notes=(), checks=()):
        self.write(f"nemo-projects/{project}/.nemo/results.json", json.dumps({step: {
            "stage": step, "ok": False, "notes": list(notes),
            "checks": [{"name": n, "status": "FAIL"} for n in checks]}}))


class TestTheTeam(unittest.TestCase):
    def test_the_doctors(self):
        self.assertEqual([e.title for e in staff.team("doctors")],
                         ["Memory Checker", "GP", "Machine Specialist", "GPU Specialist", "Model Specialist",
                          "Design Specialist",
                          "Stick Specialist", "Records Clerk", "Nurse", "Writer"])

    def test_the_nurse_and_the_writer_work(self):
        # Phase 2 built the Nurse (tests/test_nurse.py), phase 3 the Writer's report.
        self.assertTrue(staff.STAFF["doctors.nurse"].working)
        self.assertTrue(staff.STAFF["doctors.writer"].working)

    def test_every_specialist_is_on_the_roster(self):
        for key, _ in clinic.SPECIALISTS:
            self.assertTrue(staff.STAFF[key].working, key)


class TestTheModelNotesAreRoutersOwnWords(unittest.TestCase):
    """Each fragment the Doctors look for is the start of what
    router.explain_failure really writes for that failure."""

    def test_each_fragment(self):
        http = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b"{}"))
        self.addCleanup(http.close)
        said = [router.explain_failure(e, 900) for e in (
            socket.timeout("timed out"), http,
            urllib.error.URLError("refused"), router.RouterError("no server"),
            urllib.error.URLError(ConnectionRefusedError(10061, "actively refused")))]
        self.assertEqual(len(said), len(clinic.MODEL_NOTES))
        for frag, text in zip(clinic.MODEL_NOTES, said):
            self.assertTrue(text.startswith(frag), (frag, text))


class TestTheGP(AHome):
    def test_a_specialist_that_fails_is_named_and_the_rest_still_look(self):
        def broken(cfg):
            raise OSError("cannot read")
        def fine(cfg):
            return [clinic.Finding("doctors.gp", clinic.LOOK, "x", "y", "z")]
        case = clinic.examine(self.cfg, (("doctors.stick", broken), ("doctors.gp", fine)))
        self.assertEqual(case.seen_by, ["doctors.gp"])
        self.assertIn("cannot read", case.failed[0])
        self.assertEqual(len(case.findings), 1)
        self.assertFalse(case.healthy)

    def test_worst_first(self):
        def two(cfg):
            return [clinic.Finding("doctors.gp", clinic.LOOK, "a", "", ""),
                    clinic.Finding("doctors.gp", clinic.NEEDS, "b", "", "")]
        case = clinic.examine(self.cfg, (("doctors.gp", two),))
        self.assertEqual([f.what for f in case.findings], ["b", "a"])

    def test_looking_changes_nothing(self):
        self.failed_step("lamp", "wiring", checks=["harness_pins"])
        self.write("nemo-storeroom/stock.yaml", "a: [unclosed")
        self.write(".nemo/talk.log", "error: something odd\n")
        before = {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        with mock.patch("nemo.doctor.run", return_value=[]):
            clinic.examine(self.cfg)
        after = {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class TestTheModelSpecialist(AHome):
    def run_model(self, total=8000, have=6000, status=ModeStatus(None, None, None),
                  on_disk=True):
        def path(cfg, m):
            if not on_disk:
                raise FileNotFoundError(f"no GGUF for {m!r}")
            return Path("m.gguf")
        with mock.patch("nemo.platform_probe.mem_total_mb", return_value=total), \
             mock.patch("nemo.platform_probe.mem_available_mb", return_value=have), \
             mock.patch.object(modes, "current", return_value=status), \
             mock.patch.object(modes, "model_path", side_effect=path),              mock.patch.object(modes, "_stopped_recently", return_value=False):
            return clinic.model(self.cfg)

    def test_a_well_machine_has_nothing(self):
        self.assertEqual(self.run_model(), [])

    def test_a_stale_record(self):
        f = self.run_model(status=ModeStatus("talk", 2 ** 22 + 7, "qwen3-1.7b"))
        self.assertIn("has ended", f[0].what)
        self.assertIn("nemo mode talk", f[0].advice)

    def test_a_missing_model_file(self):
        f = self.run_model(on_disk=False)
        self.assertEqual({x.severity for x in f}, {clinic.NEEDS})
        self.assertEqual(len(f), 3)                  # talk, design, build

    def test_memory_by_the_same_figure_as_loading(self):
        spec = self.cfg.mode("design")
        need, model_mb, tools_mb = modes.memory_need(spec)
        self.assertEqual(need, int(spec["ram_mb"]) + int(spec.get("tools_mb", 0)) + 300)
        self.assertFalse([f for f in self.run_model(have=need) if "design" in f.what])
        short = [f for f in self.run_model(have=need - 1) if "design" in f.what]
        self.assertEqual(short[0].severity, clinic.LOOK)
        never = [f for f in self.run_model(total=need - 1, have=100) if "design" in f.what]
        self.assertEqual(never[0].severity, clinic.NEEDS)

    def test_the_server_s_words_are_shown_not_explained(self):
        self.write(".nemo/talk.log", "loading\nerror: weird thing 42\nready\n")
        with mock.patch.object(modes, "STATE", self.home / ".nemo" / "mode.pid"):
            f = [x for x in self.run_model() if "log" in x.what]
        self.assertIn("Not known", f[0].diagnosis)
        self.assertIn("error: weird thing 42", f[0].evidence)


class TestTheDesignSpecialist(AHome):
    def test_a_model_failure_goes_to_the_model_specialist(self):
        note = router.explain_failure(socket.timeout("timed out"), 900)
        self.failed_step("lamp", "electrical", notes=[note])
        f = clinic.design(self.cfg)
        self.assertEqual(f[0].specialist, "doctors.model")
        self.assertIn("time limit", f[0].what)
        self.assertIn("engine.timeout_s", f[0].advice)

    def test_an_inspector_stop_and_a_failed_check(self):
        self.failed_step("lamp", "parts", checks=["review_no_board"])
        self.failed_step("fan", "wiring", checks=["harness_pins"])
        f = {x.what: x for x in clinic.design(self.cfg)}
        self.assertIn("Inspector stopped it", f["lamp: the parts step failed."].diagnosis)
        self.assertIn("harness_pins", f["fan: the wiring step failed."].diagnosis)
        self.assertIn("nemo --project fan fix --stage wiring", f["fan: the wiring step failed."].advice)

    def test_concepts_waiting_for_a_choice_are_not_a_failure(self):
        # 2026-11-06: two concepts drawn and waiting were "the concept step
        # failed", needing attention.
        self.failed_step("prop", "concept", checks=["concept_choice"])
        f = clinic.design(self.cfg)[0]
        self.assertEqual(f.severity, clinic.LOOK)
        self.assertEqual(f.what, "prop: its concepts are waiting for your choice.")
        self.assertIn("concept choose A", f.advice)
        self.failed_step("box", "concept", checks=["concept_choice", "concept_drawn"])
        self.assertIn("box: the concept step failed.", [x.what for x in clinic.design(self.cfg)])

    def test_a_failure_with_no_reason_is_not_known(self):
        self.failed_step("lamp", "pack")
        self.assertIn("Not known", clinic.design(self.cfg)[0].diagnosis)


class TestTheStickAndTheRecords(AHome):
    def test_off_a_stick_there_is_nothing_to_say(self):
        with mock.patch("nemo.storage.has_stick", return_value=False):
            self.assertEqual(clinic.stick(self.cfg), [])

    def test_a_stick_that_keeps_nothing(self):
        with mock.patch("nemo.storage.has_stick", return_value=True), \
             mock.patch("nemo.storage.status", return_value=(
                 "the boot medium is iso9660, not a writable stick; nothing is kept")):
            f = clinic.stick(self.cfg)
        self.assertEqual(f[0].severity, clinic.NEEDS)
        self.assertIn("iso9660", f[0].diagnosis)

    def test_an_unreadable_storeroom_and_no_backup(self):
        self.write("nemo-storeroom/stock.yaml", "a: [unclosed")
        self.write("nemo-projects/lamp/brief.yaml", "name: lamp\n")
        whats = [f.what for f in clinic.records(self.cfg)]
        self.assertIn("The Storeroom's catalogue cannot be read.", whats)
        self.assertIn("No backup has been made.", whats)
        from nemo import backup
        backup.make(self.cfg)
        self.assertNotIn("No backup has been made.", [f.what for f in clinic.records(self.cfg)])


class TestTheCaseNotes(AHome):
    def test_every_visit_is_kept_and_nothing_applied(self):
        def one(cfg):
            return [clinic.Finding("doctors.gp", clinic.LOOK, "a thing", "why", "do this")]
        for _ in range(2):
            clinic.record(clinic.examine(self.cfg, (("doctors.gp", one),)))
        visits = clinic.past()
        self.assertEqual(len(visits), 2)
        self.assertEqual(visits[0]["findings"][0]["what"], "a thing")
        self.assertTrue(all(v["applied"] == [] for v in visits))
        self.assertTrue(str(clinic.notes_path()).startswith(str(self.home)))

    def test_the_words_say_nothing_was_changed(self):
        text = clinic.describe(clinic.examine(self.cfg, NOBODY))
        self.assertIn("Nothing found that needs attention.", text)
        self.assertIn("Looking changed nothing", text)

    def test_the_command(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(clinic, "SPECIALISTS", ()):
            rc = cli.main(["clinic"])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn("Looking changed nothing", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(["clinic", "notes"])
        self.assertIn("1 visit(s)", out.getvalue())


class TestTheCaseReport(AHome):
    def test_no_project_names_and_no_home_folder(self):
        # Some project names are the owner's private names; the report is for sending.
        self.failed_step("Secret Name Project", "wiring", checks=["harness_pins"])
        self.write("nemo-stories/fox/story.md", "# A private story\n")
        clinic.record(clinic.examine(self.cfg, (("doctors.design", clinic.design),)))
        with mock.patch("nemo.toolkit.check", return_value=[]):
            path = clinic.report(self.cfg)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("Secret Name Project", text)
        self.assertIn("project 1: the wiring step failed", text)
        self.assertNotIn("A private story", text)
        self.assertNotIn(str(self.home), text)
        self.assertIn("Read it before you send it", text)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_it_shows_the_findings_and_closes_cleanly(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        case = clinic.Case(0, [clinic.Finding("doctors.model", clinic.NEEDS,
                                              "The talk model is not on disk.", "why", "do this",
                                              "seen this")])
        app = A.NemoApp(); app.update()
        try:
            with mock.patch.object(clinic, "examine", return_value=case):
                w = A.Clinic(app)
                for _ in range(50):
                    app.update()
                    if "not on disk" in w.text.get("1.0", "end"):
                        break
                    app.after(50)
            body = w.text.get("1.0", "end")
            self.assertIn("Needs attention: The talk model is not on disk.", body)
            self.assertIn("Model Specialist: why", body)
            self.assertIn("Looking changed nothing.", body)
            w.show_notes()
            self.assertIn("Treatments, newest first", w.text.get("1.0", "end"))
            w.run(); w.destroy(); app.update()      # closed mid-look: no stray timer
        finally:
            app.destroy()

    def test_look_for_newer_tools_keeps_the_look_and_sees_the_doctors_again(self):
        # 2026-11-11: the one look that goes on the network; mocked here.
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        from nemo import toolupdates
        looks = [toolupdates.Look("harper", "Harper", "library", "v2.12.0", "v3.1.0", True, "u")]
        app = A.NemoApp(); app.update()
        try:
            with mock.patch.object(clinic, "examine", return_value=clinic.Case(0)), \
                 mock.patch.object(toolupdates, "look", return_value=looks):
                w = A.Clinic(app)
                self.assertEqual(w.newer.cget("text"), "Look for newer tools")
                w.look_for_updates()
                for _ in range(60):
                    app.update()
                    if toolupdates.last() and str(w.newer.cget("state")) == "normal":
                        break
                    app.after(50)
            self.assertEqual(toolupdates.last()[1], looks)
            w.destroy(); app.update()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
