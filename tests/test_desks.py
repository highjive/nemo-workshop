"""Every department laid out like the Workshop: its own list, a "New" button, its
tabs, the painted room as the Team tab (nemo/desks.py; owner, 2026-11-18)."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import desks
from nemo.staff import DEPARTMENTS


class Parsed(Exception):
    pass


def parses(argv) -> bool:
    """Does `nemo <argv>` get past the command line's own parser?"""
    from nemo import cli
    with mock.patch.object(cli.Config, "load", side_effect=Parsed), \
            mock.patch("sys.stderr"):
        try:
            cli.main(list(argv))
        except Parsed:
            return True
        except SystemExit:
            return False
    return False


class TestEachDepartmentsList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name)); env.start()
        self.addCleanup(env.stop)
        from nemo.config import Config
        self.cfg = Config.load()
        # The Doctors' case notes are in a folder fixed when the sandbox starts, which
        # other tests write to: this test's own, empty.
        notes = mock.patch("nemo.clinic.notes_path",
                           return_value=Path(self.tmp.name) / "clinic" / "cases.jsonl")
        notes.start(); self.addCleanup(notes.stop)

    def test_every_department_has_its_list(self):
        self.assertEqual(set(desks.DESKS), set(DEPARTMENTS))
        for key, d in desks.DESKS.items():
            self.assertTrue(d.title and d.tab and d.new and d.hint and d.empty, key)

    def test_an_empty_home_reads_without_a_fault(self):
        for key in desks.DESKS:
            entries, problem = desks.entries(key, self.cfg)
            self.assertEqual(problem, "", key)
            self.assertEqual(entries, [], key)

    def test_a_list_that_cannot_be_read_is_said_not_raised(self):
        with mock.patch.object(desks.DESKS["library"], "entries", side_effect=OSError("disk gone")):
            entries, problem = desks.entries("library", self.cfg)
        self.assertEqual(entries, [])
        self.assertIn("disk gone", problem)

    def test_what_is_there_is_listed_with_real_commands(self):
        story = self.cfg.path("paths.stories") / "a-fox"
        (story / "chapters").mkdir(parents=True)
        (story / "request.md").write_text("# Asked for\n\na story about a fox\n", encoding="utf-8")
        (story / "story.md").write_text("# A Fox\n", encoding="utf-8")
        model = self.cfg.path("paths.models") / "shed-tag"
        model.mkdir(parents=True)
        (model / "spec.json").write_text(json.dumps({"name": "Shed Tag", "shapes": []}), encoding="utf-8")
        (model / "checks.json").write_text("[]", encoding="utf-8")
        (model / "model.stl").write_bytes(b"\0" * 84)
        proj = self.cfg.path("paths.projects") / "lamp"
        (proj / "firmware").mkdir(parents=True)
        (proj / "brief.yaml").write_text("name: lamp\n", encoding="utf-8")
        seen = {}
        for key in desks.DESKS:
            entries, problem = desks.entries(key, self.cfg)
            self.assertEqual(problem, "", key)
            seen[key] = entries
            for e in entries:
                for a in e.actions:
                    if a.argv:
                        self.assertTrue(parses(a.argv), f"{key}: {a.label}: nemo {a.argv}")
        lib = seen["library"][0]
        self.assertEqual(lib.label, "a-fox")
        self.assertIn("a story about a fox", lib.about)
        self.assertIn(["story", "cover", "a-fox"], [a.argv for a in lib.actions])
        art = seen["art_studio"][0]
        self.assertIn(["print", "slice", "shed-tag"], [a.argv for a in art.actions])  # its folder
        self.assertEqual([e.id for e in seen["workshop"]], ["lamp"])
        self.assertEqual([a.project for a in seen["workshop"][0].actions if a.project], ["lamp"])
        self.assertEqual([e.id for e in seen["bench"]], ["lamp"])
        self.assertIn("shed-tag (Art Studio)", [e.label for e in seen["printshop"]])

    def test_casting_is_a_lit_button_never_a_command(self):
        for d in desks.DESKS.values():
            self.assertNotIn("cast", d.hint.lower().split())
        with mock.patch("nemo.theatre.videos", return_value=[
                mock.Mock(name="v", path=Path("film.mp4"), kind="video", source="Storeroom")]), \
                mock.patch("nemo.theatre.photos", return_value=[]):
            entries, _ = desks.entries("theatre", self.cfg)
        cast = [a for a in entries[0].actions if "Cast" in a.label]
        self.assertEqual([(a.button, a.argv) for a in cast], [("Cast", [])])


@unittest.skipUnless(_sandbox.has_display(), "needs a display")
class TestTheDepartmentScreen(unittest.TestCase):
    def setUp(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name)); env.start()
        self.addCleanup(env.stop)
        self.app = A.NemoApp(); self.app.update(); self.addCleanup(self.app.destroy)
        story = self.app.cfg.path("paths.stories") / "a-fox"
        story.mkdir(parents=True)
        (story / "request.md").write_text("# Asked for\n\na story about a fox\n", encoding="utf-8")

    def room(self, key):
        r = self.app.open_department(key); self.app.update()
        r.end_introductions(); self.app.update()
        return r

    def test_its_list_and_tabs_with_the_team_last(self):
        r = self.room("library")
        self.assertEqual(r.list_box.get(0, "end"), ("a-fox",))
        self.assertEqual(r.new_button.cget("text"), "New story")
        tabs = [r.tabs.tab(t, "text") for t in r.tabs.tabs()]
        self.assertEqual(tabs, ["Story", "Team"])
        self.assertIs(r.canvas.master, r._team)                    # the room is the Team tab
        self.assertEqual(r.entry_title.cget("text"), "a-fox")
        labels = [w.cget("text") for w in r.entry_actions.winfo_children()]
        self.assertEqual(labels, ["Write it"])                    # not written yet

    def test_an_action_runs_in_the_departments_box(self):
        r = self.room("library")
        from nemo.gui import controller as C
        ran = []
        with mock.patch.object(C, "nemo_argv", side_effect=lambda *a: ran.append(a) or
                               [sys.executable, "-c", "print('written')"]):
            self.assertEqual(r.do_action(r.chosen.actions[0]), "run")
            t0 = time.time()
            while self.app.ask_bar.busy() and time.time() - t0 < 30:
                self.app.update(); time.sleep(0.05)
        self.assertEqual(ran[0][:3], ("story", "write", "a-fox"))
        self.assertIn("> Write it", self.app.ask_bar.reply.get("1.0", "end"))

    def test_a_double_click_plays_it(self):
        # D282 (2026-11-19, "images and videos in theatre wont play when selected"):
        # choosing one only showed its page. A double click or Enter does its first action.
        r = self.room("library")
        self.assertTrue(r.list_box.bind("<Double-Button-1>"))
        self.assertTrue(r.list_box.bind("<Return>"))
        with mock.patch.object(r, "do_action", return_value="run") as act:
            self.assertEqual(r.do_first_action(), "run")
        self.assertEqual(act.call_args.args[0].label, "Write it")

    def test_on_linux_nemo_steps_aside_for_the_player(self):
        # D282: on X11 the department (overrideredirect) stays above every managed window,
        # so VLC and the picture viewer opened under it. A command that opens a window, once
        # it has, has Nemo minimise itself there; Windows is left alone.
        from nemo.gui import askbar
        from nemo.gui import controller as C
        self.assertTrue(askbar.opens_a_window(["theatre", "play", "a.mp4"]))
        self.assertTrue(askbar.opens_a_window(["film", "edit", "A Fox"]))
        self.assertFalse(askbar.opens_a_window(["film", "edit", "A Fox", "--no-open"]))
        self.assertFalse(askbar.opens_a_window(["theatre", "check", "a.mp4"]))
        self.assertFalse(askbar.opens_a_window(["rebuild", "doctor"]))
        self.room("theatre")
        bar = self.app.ask_bar
        for system, iconified in (("win32", False), ("x11", True)):
            with mock.patch.object(self.app, "windowing", return_value=system), \
                    mock.patch.object(self.app, "iconify") as icon, \
                    mock.patch.object(C, "nemo_argv",
                                      return_value=[sys.executable, "-c", "print('playing')"]):
                bar.run(["theatre", "play", "a.mp4"], "theatre")
                t0 = time.time()
                while bar.busy() and time.time() - t0 < 30:
                    self.app.update(); time.sleep(0.05)
                self.app.update()
            self.assertEqual(icon.called, iconified, system)
        self.assertIn("stepped aside", bar.reply.get("1.0", "end"))

    def test_new_says_what_to_type_here(self):
        r = self.room("art_studio")
        r.new_entry(); self.app.update()
        self.assertIn("a relief of <picture>", self.app.ask_bar.reply.get("1.0", "end"))

    def test_the_team_is_shown_while_it_is_introduced(self):
        r = self.room("science")
        r.introduce(); self.app.update()
        self.assertEqual(r.tabs.select(), str(r._team))
        r.end_introductions()


if __name__ == "__main__":
    unittest.main()
