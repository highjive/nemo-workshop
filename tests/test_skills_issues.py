"""In a department only its people (owner, 2026-11-04): they say their
problems with the project and the fixes, and ask what they can help with
from their skills."""
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

from nemo import issues, skills
from nemo.staff import STAFF
from nemo.steps import STEPS

APP = Path(__file__).resolve().parent.parent / "nemo" / "gui" / "app.py"
WINDOW_CLASS = {"library": "StoryList", "art_studio": "ArtStudio", "storeroom": "VideoStore",
                "theatre": "Theatre", "gaming": "Gaming", "music": "MusicRoom", "audio": "AudioRoom",
                "bench": "TestBench", "printshop": "PrintShop", "film": "FilmStudio",
                "home": "HomeRoom", "comms": "CommsRoom", "science": "ScienceRoom", "doctors": "Clinic"}


def class_source(name: str) -> str:
    src = APP.read_text(encoding="utf-8")
    start = src.index(f"\nclass {name}(")
    end = src.find("\nclass ", start + 1)
    return src[start:end if end > 0 else None]


class TestTheSkillTree(unittest.TestCase):
    def test_every_employee_offers_something_and_says_what_it_needs(self):
        for key in STAFF:
            got = skills.skills_for(key)
            self.assertGreaterEqual(len(got), 2, key)
            self.assertEqual(got[-1].kind, skills.NEEDS, key)

    def test_every_window_skill_is_a_button_that_exists(self):
        # A renamed button would leave the skill lighting nothing.
        for key, offers in skills.WINDOW_SKILLS.items():
            body = class_source(WINDOW_CLASS[key.split(".")[0]])
            for label, button in offers:
                self.assertIn(f'text="{button}"', body, f"{key}: {button}")

    def test_every_dialog_skill_is_one_of_nemos_dialogs(self):
        src = APP.read_text(encoding="utf-8")
        for key, offers in skills.DIALOG_SKILLS.items():
            for _, target in offers:
                cls = target.partition(":")[0]             # "Class:Button" lights a button
                self.assertIn(f"\nclass {cls}(", src, key)

    def test_the_steps_offered_are_the_ones_it_owns(self):
        for key in STAFF:
            offered = [s.target for s in skills.skills_for(key) if s.kind == skills.STEP]
            self.assertEqual(offered, [s.key for s in STEPS if s.owner == key], key)

    def test_casting_is_never_a_skill_that_acts(self):
        # A window skill lights its button; it never presses it (docs/design-rules.md:
        # never cast to the owner's Chromecast without asking).
        self.assertIn("never presses it", skills.__doc__)
        from nemo.gui import app as A
        self.assertNotIn("invoke(", A.light_button.__code__.co_names)


def _project_with(results: dict):
    from nemo.gui import controller as C
    from nemo.config import Config
    p = C.create_project("lamp", Config.load())
    (p.root / ".nemo").mkdir(exist_ok=True)
    (p.root / ".nemo" / "results.json").write_text(json.dumps(results), encoding="utf-8")
    return p


def _rec(stage, ok, *checks):
    return {"stage": stage, "ok": ok, "when": 0, "degraded": False, "go_back_to": None,
            "artifacts": [], "notes": [],
            "checks": [{"name": n, "status": s, "detail": d, "items": []} for n, s, d in checks]}


class TestWhoHasAProblem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name)); env.start()
        self.addCleanup(env.stop)

    def issues_of(self, results):
        from nemo.parts import PartsLibrary
        p = _project_with(results)
        return issues.for_project(p.root, p.load_brief(), PartsLibrary.load())

    def test_a_failed_step_is_its_owners_with_what_went_wrong(self):
        got = self.issues_of({"electrical": _rec("electrical", False, ("erc", "FAIL", "GPIO9 driven twice"),
                                                 ("current_sum", "PASS", ""))})
        owner = next(s.owner for s in STEPS if s.key == "electrical")
        self.assertEqual(list(got), [owner])
        i = got[owner][0]
        self.assertEqual((i.stage, i.state), ("electrical", issues.FAILED))
        self.assertEqual(i.problems, ["erc failed: GPIO9 driven twice"])
        self.assertTrue(i.fixes)                           # the Workshop's own suggestions

    def test_a_check_that_could_not_be_made_is_said_too(self):
        got = self.issues_of({"enclosure": _rec("enclosure", True, ("solid", "SKIP", "no CadQuery"))})
        i = next(iter(got.values()))[0]
        self.assertEqual(i.state, issues.UNCHECKED)

    def test_a_step_that_passed_is_nobodys_problem(self):
        self.assertEqual(self.issues_of({"parts": _rec("parts", True, ("current_sum", "PASS", ""))}), {})

    def test_they_count_by_department(self):
        got = self.issues_of({"electrical": _rec("electrical", False, ("erc", "FAIL", "x")),
                              "firmware": _rec("firmware", False, ("compile", "FAIL", "y"))})
        counts = issues.count_by_department(got)
        self.assertEqual(sum(counts.values()), 2)


@unittest.skipUnless(_sandbox.has_display(), "needs a display")
class TestInTheRoom(unittest.TestCase):
    def setUp(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name)); env.start()
        self.addCleanup(env.stop)
        self.app = A.NemoApp(); self.app.update(); self.addCleanup(self.app.destroy)

    def room(self, key="workshop"):
        r = self.app.open_department(key); self.app.update()
        r.end_introductions(); self.app.update()
        return r

    def test_only_the_department_is_in_view_and_it_all_comes_back(self):
        r = self.room()
        self.assertFalse(self.app.header.winfo_ismapped())
        self.assertFalse(self.app.status.winfo_ismapped())
        r.destroy(); self.app.update()
        self.assertTrue(self.app.header.winfo_ismapped())
        self.assertTrue(self.app.status.winfo_ismapped())
        self.assertTrue(self.app.body.winfo_ismapped())

    def test_the_owner_of_a_failed_step_is_marked_and_leads_with_it(self):
        self.app.project = _project_with({"electrical": _rec("electrical", False, ("erc", "FAIL", "x"))})
        owner = next(s.owner for s in STEPS if s.key == "electrical").split(".", 1)[1]
        r = self.room()
        self.assertTrue(r._issues_of(owner))
        self.assertGreater(len(r.canvas.find_withtag(f"face:{owner}")), 4)   # ring, face, name, plate, "!"
        r.show_profile(owner); self.app.update()
        texts = [r.canvas.itemcget(i, "text") for i in r.canvas.find_withtag("profile")
                 if r.canvas.type(i) == "text"]
        self.assertTrue(any(t.startswith("I have a problem: 'Schematic' failed") for t in texts), texts)
        self.assertIn("Do it and run again", texts)

    def test_a_fix_from_the_card_is_the_workshops_apply(self):
        self.app.project = _project_with({"electrical": _rec("electrical", False, ("erc", "FAIL", "x"))})
        r = self.room()
        fix = mock.Mock(title="t", kind="change", rerun="")
        with mock.patch.object(self.A.C, "apply_fix_to_project") as apply:
            r.apply_fix(fix, run=False)
        apply.assert_called_once_with(self.app.project, fix)

    def test_a_step_skill_without_a_project_says_so(self):
        r = self.room()
        r.show_profile("designer"); self.app.update()
        step = next(s for s in skills.skills_for("workshop.designer") if s.kind == skills.STEP)
        with mock.patch.object(self.app, "run_stage") as run:
            r.use_skill(step); self.app.update()
        run.assert_not_called()
        self.assertIn("Open a project first", r._card_note)

    def test_a_window_skill_lights_its_button_and_does_not_press_it(self):
        r = self.room("science")
        win = self.app.real_window("science"); self.app.update()
        pressed = []
        btn = next(w for w in _walk(win) if getattr(w, "cget", None) and _text(w) == "Work it out")
        btn.configure(command=lambda: pressed.append(1))
        self.assertTrue(self.A.light_button(win, "Work it out"))
        self.app.update()
        self.assertEqual(pressed, [])
        self.assertEqual(str(btn.cget("style")), "Primary.TButton")
        r.destroy()

    def test_the_announcement_names_the_employee(self):
        self.app.project = _project_with({"electrical": _rec("electrical", False, ("erc", "FAIL", "x"))})
        said = []
        with mock.patch.object(self.app, "announce", side_effect=lambda t, *a, **k: said.append(t)):
            self.app.job_kind = "run"
            self.app._job_finished(mock.Mock(returncode=1, stopped=False))
        self.assertTrue(re.match(r"The Workshop \w+ has a problem: 'Schematic' failed", said[-1]), said)


def _walk(w):
    yield w
    for child in w.winfo_children():
        yield from _walk(child)


def _text(w):
    try:
        return w.cget("text")
    except Exception:                                        # noqa: BLE001
        return None


if __name__ == "__main__":
    unittest.main()
