"""The Nurse, Doctors phase 2 (owner, 2026-10-21): "the Nurse applies one
remedy at a time only after my yes, keeps a copy to undo it, starting with
the safe remedies".

Held here: nothing without a yes to the very plan shown; a copy before any
change, and an undo that gives back every byte; an undo that will not
overwrite later work; a failed remedy put back at once; and a list of files
outside which the Nurse cannot reach, keys and safety store included.
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

from nemo import backup, cli, clinic, nurse
from nemo.clinic import Finding, LOOK, NEEDS

USER_CONFIG = """engine:
  local: http://127.0.0.1:8080/v1
  # the owner's own note
  timeout_s: 1800
modes: &id001
  talk:
    model: qwen3-1.7b
modes_windows: *id001
"""


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        nemo_home = self.home / ".nemo"
        self.patches = [
            mock.patch.dict(os.environ, _sandbox.home_env(self.home)),
            mock.patch("nemo.config.CONFIG_HOME", nemo_home),
            mock.patch("nemo.config.CONFIG_PATH", nemo_home / "config.yaml"),
            mock.patch("nemo.modes.STATE", nemo_home / "mode.pid"),
        ]
        for p in self.patches:
            p.start()
        self.state = nemo_home / "mode.pid"
        self.config = nemo_home / "config.yaml"
        self.stock = self.home / "nemo-storeroom" / "stock.yaml"

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.t.cleanup()

    @property
    def cfg(self):
        from nemo.config import Config
        return Config.load()

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def snapshot(self) -> dict:
        skip = self.home / ".nemo" / "clinic"
        return {p: p.read_bytes() for p in self.home.rglob("*")
                if p.is_file() and skip not in p.parents}

    def finding(self, remedy: str) -> Finding:
        return Finding("doctors.gp", NEEDS, f"something for {remedy}", "why", "advice",
                       remedy=remedy)

    def say_yes(self, f: Finding) -> dict:
        p = nurse.plan(self.cfg, f)
        self.assertIsNotNone(p)
        return nurse.treat(self.cfg, f, p.token, p.stamp)


class TestNothingWithoutAYes(AHome):
    def test_no_yes_and_a_wrong_yes_change_nothing(self):
        self.write(self.stock, "a: [unclosed")
        f = self.finding("set_aside_stock")
        p = nurse.plan(self.cfg, f)
        before = self.snapshot()
        for consent in ("", "yes", "0" * 10):
            with self.assertRaises(nurse.NurseError):
                nurse.treat(self.cfg, f, consent, p.stamp)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(nurse.treatments(), [])

    def test_a_yes_to_one_plan_cannot_apply_another(self):
        # Shown 1800 -> 3600; the setting changes before the yes arrives.
        self.write(self.config, USER_CONFIG)
        f = self.finding("raise_timeout")
        shown = nurse.plan(self.cfg, f)
        self.write(self.config, USER_CONFIG.replace("1800", "2400"))
        with self.assertRaises(nurse.NurseError) as cm:
            nurse.treat(self.cfg, f, shown.token, shown.stamp)
        self.assertIn("not to this plan", str(cm.exception))
        self.assertIn("timeout_s: 2400", self.config.read_text(encoding="utf-8"))

    def test_the_yes_still_holds_while_the_owner_reads(self):
        # A plan that names a file by the time keeps its name until the yes.
        self.write(self.stock, "a: [unclosed")
        f = self.finding("set_aside_stock")
        shown = nurse.plan(self.cfg, f, stamp="2026-10-21T09:00:00")
        rec = nurse.treat(self.cfg, f, shown.token, shown.stamp)
        self.assertTrue(rec["files"][1]["path"].endswith("unreadable-2026-10-21T090000"))

    def test_a_finding_that_no_longer_holds_is_not_treated(self):
        f = self.finding("set_aside_stock")
        self.assertIsNone(nurse.plan(self.cfg, f))               # the catalogue reads
        with self.assertRaises(nurse.NurseError):
            nurse.treat(self.cfg, f, "x", "2026-10-21T09:00:00")

    def test_a_finding_without_a_remedy_has_no_plan(self):
        self.assertIsNone(nurse.plan(self.cfg, Finding("doctors.gp", LOOK, "a", "b", "c")))


class TestTheFourRemedies(AHome):
    def treat_and_undo(self, f: Finding, check):
        before = self.snapshot()
        rec = self.say_yes(f)
        check()
        self.assertNotEqual(self.snapshot(), before)
        nurse.undo(rec["id"], agreed=True)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(nurse.treatments()[0]["undone"])

    def test_clear_record(self):
        self.write(self.state, f"talk\n{2 ** 22 + 7}\nqwen3-1.7b")
        self.treat_and_undo(self.finding("clear_record"),
                            lambda: self.assertFalse(self.state.exists()))

    def test_clear_record_leaves_a_running_model_alone(self):
        self.write(self.state, f"talk\n{os.getpid()}\nqwen3-1.7b")      # this process lives
        self.assertIsNone(nurse.plan(self.cfg, self.finding("clear_record")))

    def test_set_aside_stock(self):
        self.write(self.stock, "a: [unclosed")
        def check():
            self.assertFalse(self.stock.exists())
            aside = list(self.stock.parent.glob("stock.yaml.unreadable-*"))
            self.assertEqual(aside[0].read_text(encoding="utf-8"), "a: [unclosed")
        self.treat_and_undo(self.finding("set_aside_stock"), check)

    def test_backup(self):
        self.write(self.home / "nemo-projects" / "lamp" / "brief.yaml", "name: lamp\n")
        def check():
            made = backup.listing()
            self.assertEqual(len(made), 1)
            self.assertEqual(backup.verify(made[0]), [])
        self.treat_and_undo(self.finding("backup"), check)
        self.assertEqual(backup.listing(), [])

    def test_raise_timeout_changes_that_one_line_only(self):
        self.write(self.config, USER_CONFIG)
        def check():
            after = self.config.read_text(encoding="utf-8").splitlines()
            was = USER_CONFIG.splitlines()
            self.assertEqual([a for a, b in zip(after, was) if a != b], ["  timeout_s: 3600"])
            self.assertEqual(self.cfg.get("engine.timeout_s"), 3600)
        self.treat_and_undo(self.finding("raise_timeout"), check)

    def test_raise_timeout_with_no_settings_file_writes_only_that(self):
        self.treat_and_undo(self.finding("raise_timeout"),
                            lambda: self.assertEqual(self.config.read_text(encoding="utf-8"),
                                                     "engine:\n  timeout_s: 3600\n"))
        self.assertFalse(self.config.exists())

    def test_raise_timeout_is_not_offered_where_it_would_guess(self):
        self.write(self.config, USER_CONFIG + "other:\n  timeout_s: 5\n")
        self.assertIsNotNone(nurse.plan(self.cfg, self.finding("raise_timeout")))
        self.write(self.config, USER_CONFIG.replace("  timeout_s: 1800\n",
                                                    "  timeout_s: 1800\n  timeout_s: 900\n"))
        self.assertIsNone(nurse.plan(self.cfg, self.finding("raise_timeout")))
        self.write(self.config, USER_CONFIG.replace("1800", str(nurse.TIMEOUT_CAP_S)))
        self.assertIsNone(nurse.plan(self.cfg, self.finding("raise_timeout")))


class TestTheUndo(AHome):
    def test_it_needs_a_yes(self):
        self.write(self.stock, "a: [unclosed")
        rec = self.say_yes(self.finding("set_aside_stock"))
        with self.assertRaises(nurse.NurseError):
            nurse.undo(rec["id"])
        self.assertFalse(nurse.treatments()[0]["undone"])

    def test_it_will_not_overwrite_later_work(self):
        self.write(self.stock, "a: [unclosed")
        rec = self.say_yes(self.finding("set_aside_stock"))
        self.write(self.stock, "led:\n  name: LED\n  quantity: 4\n")   # a new catalogue
        with self.assertRaises(nurse.NurseError) as cm:
            nurse.undo(rec["id"], agreed=True)
        self.assertIn("stock.yaml", str(cm.exception))
        self.assertIn("quantity: 4", self.stock.read_text(encoding="utf-8"))

    def test_nothing_to_undo(self):
        with self.assertRaises(nurse.NurseError):
            nurse.undo(agreed=True)


class TestWhereTheNurseCannotReach(AHome):
    def fake(self, touches, apply):
        def plan_fn(cfg, finding, stamp):
            return nurse.Plan("fake", "Fake", finding.what, ["change it"],
                              [str(t) for t in touches])
        return mock.patch.dict(nurse.REMEDIES, {"fake": (plan_fn, apply)})

    def test_the_keys_and_the_safety_store_are_out_of_reach(self):
        key = self.write(self.home / ".nemo" / "keys" / "mouser.key", "SECRET")
        safety = self.write(self.home / ".nemo" / "safety.json", "{}")
        admin = self.write(self.home / ".nemo" / "admin" / "state.json", "{}")
        for target in (key, safety, admin, self.home / "nemo-projects" / "x.txt"):
            hit = []
            with self.fake([target], lambda cfg, p: hit.append(1)):
                f = self.finding("fake")
                p = nurse.plan(self.cfg, f)
                with self.assertRaises(nurse.NurseError) as cm:
                    nurse.treat(self.cfg, f, p.token, p.stamp)
            self.assertIn("may not change", str(cm.exception))
            self.assertEqual(hit, [], target)
        self.assertEqual(key.read_text(encoding="utf-8"), "SECRET")
        self.assertEqual(nurse.treatments(), [])

    def test_a_remedy_that_fails_part_way_is_put_back(self):
        self.write(self.stock, "kept: {name: kept, quantity: 1}\n")
        def half(cfg, p):
            self.stock.write_text("half written", encoding="utf-8")
            raise OSError("disk full")
        with self.fake([self.stock], half):
            f = self.finding("fake")
            p = nurse.plan(self.cfg, f)
            with self.assertRaises(nurse.NurseError) as cm:
                nurse.treat(self.cfg, f, p.token, p.stamp)
        self.assertIn("put back", str(cm.exception))
        self.assertEqual(self.stock.read_text(encoding="utf-8"),
                         "kept: {name: kept, quantity: 1}\n")
        self.assertEqual(nurse.treatments(), [])


class TestTheRecords(AHome):
    def test_each_treatment_and_undo_is_in_the_case_notes(self):
        self.write(self.stock, "a: [unclosed")
        rec = self.say_yes(self.finding("set_aside_stock"))
        nurse.undo(rec["id"], agreed=True)
        lines = [json.loads(l) for l in
                 clinic.notes_path().read_text(encoding="utf-8").splitlines()]
        self.assertEqual([l.get("treated") or l.get("undone") for l in lines],
                         [rec["id"], rec["id"]])
        self.assertEqual(clinic.past(), [])       # visits only: treatments are listed apart

    def test_the_doctors_offer_it_by_number(self):
        self.write(self.stock, "a: [unclosed")
        with mock.patch.object(clinic, "SPECIALISTS", (("doctors.gp", clinic.records),)):
            case = clinic.examine(self.cfg)
        text = clinic.describe(case)
        self.assertIn("nemo clinic treat 1", text)
        self.assertEqual(case.findings[0].remedy, "set_aside_stock")


class TestTheCommand(AHome):
    def run_cli(self, *argv, tty=False, typed="") -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out), \
             mock.patch.object(clinic, "SPECIALISTS", (("doctors.gp", clinic.records),)), \
             mock.patch("sys.stdin.isatty", return_value=tty), \
             mock.patch("builtins.input", return_value=typed):
            rc = cli.main(["clinic", *argv])
        return rc, out.getvalue()

    def test_treat_asks_and_no_means_no(self):
        self.write(self.stock, "a: [unclosed")
        rc, out = self.run_cli("treat", "1")
        self.assertEqual(rc, 1)
        self.assertIn("add --yes", out)
        rc, out = self.run_cli("treat", "1", tty=True, typed="no")
        self.assertIn("Not applied", out)
        self.assertTrue(self.stock.exists())

    def test_treat_on_a_typed_yes_then_undo(self):
        self.write(self.stock, "a: [unclosed")
        rc, out = self.run_cli("treat", "1", tty=True, typed="yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("A copy of every file", out)
        self.assertFalse(self.stock.exists())
        self.assertIn("Set the unreadable", self.run_cli("treatments")[1])
        rc, out = self.run_cli("undo", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stock.read_text(encoding="utf-8"), "a: [unclosed")

    def test_a_finding_number_out_of_range(self):
        rc, out = self.run_cli("treat", "9")
        self.assertEqual(rc, 1)
        self.assertIn("Choose a finding by its number", out)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_ask_the_nurse_and_undo(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.write(self.stock, "a: [unclosed")
        f = self.finding("set_aside_stock")
        app = A.NemoApp(); app.update()
        try:
            with mock.patch.object(clinic, "SPECIALISTS", ()):
                w = A.Clinic(app)
                asked = []
                w.ask = lambda title, text, parent=None: asked.append(text) or False
                self.assertIsNone(w.treat(f))
                self.assertTrue(self.stock.exists())
                self.assertIn("Rename stock.yaml", asked[0])
                w.ask = lambda title, text, parent=None: True
                self.assertIsNotNone(w.treat(f))
                self.assertFalse(self.stock.exists())
                self.assertIsNotNone(w.undo_last())
                self.assertTrue(self.stock.exists())
                w.destroy(); app.update()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
