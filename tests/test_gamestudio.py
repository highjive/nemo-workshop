"""The Game Studio (owner, 2026-11-09): games in Godot from the owner's own idea, no
questions about his gaming history. Kinds built by code (the platformer first); any
other idea by the desktop's model, judged by Godot. One real game is made and run in
Godot where Godot is installed (the desktop)."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import asks, gamestudio as G
from nemo.staff import DEPARTMENTS, team

ACORN = ('A platformer called "Acorn Run" where you play as a red squirrel who collects '
         'acorns and must reach the old oak, 3 levels, a little floaty.')


class TestTheDesigner(unittest.TestCase):
    def test_the_idea_read_by_code(self):
        s = G.design(ACORN)
        self.assertEqual((s.kind, s.title, s.player, s.collect, s.goal, s.levels),
                         ("platformer", "Acorn Run", "red squirrel", "acorns", "the old oak", 3))
        self.assertEqual((s.gravity, s.player_colour), (0.6, "red"))
        self.assertTrue(all("(your words)" in x for x in s.said))

    def test_what_is_not_said_is_chosen_and_said(self):
        s = G.design("a platformer with lots of jumping")
        self.assertEqual((s.player, s.collect, s.goal, s.levels), ("hero", "coins", "the flag", 3))
        self.assertTrue(any("(not said)" in x for x in s.said))

    def test_no_known_kind_is_said_not_guessed(self):
        self.assertIsNone(G.kind_of("a game where you steer a boat around rocks"))
        with self.assertRaises(G.StudioError):
            G.design("a game where you steer a boat around rocks")
        self.assertEqual(G.model_title("a game where you steer a little boat around rocks to "
                                       "collect stars"), "Boat and the Stars")

    def test_a_joining_word_is_not_part_of_the_thing(self):
        # 2026-11-09: "collects acorns and must reach" was read as "acorns and".
        self.assertEqual(G.design("a platformer where you collect berries and then jump").collect,
                         "berries")


class TestTheLevelDesigner(unittest.TestCase):
    def test_every_jump_can_be_made(self):
        for idea in (ACORN, "a fast platformer, 6 levels, heavy jumps", "a slow platformer"):
            s = G.design(idea)
            g, v, speed = G.physics(s)
            levels = G.build_levels(s)
            self.assertEqual(len(levels), s.levels)
            for lv in levels:
                self.assertEqual(G.jump_faults(lv, g, v, speed), [], idea)

    def test_an_impossible_jump_is_found(self):
        lv = G.Level((60, 420), [(0, 480, 320), (2000, 480, 200)], [], (2100, 480))
        self.assertIn("further than the jump carries", G.jump_faults(lv, *G.physics(G.design(ACORN)))[0])
        lv = G.Level((60, 420), [(0, 480, 320), (340, 100, 200)], [], (400, 100))
        self.assertIn("more than the jump's height", G.jump_faults(lv, *G.physics(G.design(ACORN)))[0])


class TestTheProgrammer(unittest.TestCase):
    def test_written_by_code_for_godot_4(self):
        s = G.design(ACORN)
        script = G.platformer_script(s, G.build_levels(s))
        self.assertIn("extends Node2D", script)
        self.assertIn('const TITLE = "Acorn Run"', script)
        self.assertIn("NEMO DONE", script)
        self.assertNotIn("-> ", script)                       # no typed returns (4.7)
        self.assertIn('get_node("Camera").make_current()', script)   # once in the tree

    def test_the_models_slips_put_right_by_code(self):
        text, fixed = G.slips(
            "```gdscript\nextends Node2D\nfunc _ready():\n\tfor _ in range(3):\n\t\tpass\n"
            "\tif OS.get_cmdline_user_args() has \"--x\":\n\t\tpass\n"
            "\ttimer.connect(\"timeout\", self, \"_tick\")\n\tfor i in 0..3:\n\t\tpass\n"
            "\tvar rect = 1\n\tif true:\n\t\tvar rect = 2\n```\n")
        self.assertNotIn("```", text)
        self.assertIn("for _i in range(3):", text)
        self.assertIn('if "--x" in OS.get_cmdline_user_args():', text)
        self.assertIn("timer.timeout.connect(_tick)", text)
        self.assertIn("for i in range(0, 3):", text)
        self.assertIn("\t\trect = 2", text)
        self.assertIn("\tvar rect = 1", text)                 # the first stays
        self.assertEqual(len(fixed), 6)

    def test_sibling_blocks_may_each_declare(self):
        text, fixed = G.redeclared("func a():\n\tif x:\n\t\tvar r = 1\n\telse:\n\t\tvar r = 2\n"
                                   "func b():\n\tvar r = 3\n")
        self.assertEqual(fixed, [])

    def test_godots_own_suggestions(self):
        got = G.godot_suggests([
            'SCRIPT ERROR: Parse Error: Identifier "Sprite" not declared in the current scope. '
            'Did you mean to use "Sprite2D"? (main.gd line 4)',
            'SCRIPT ERROR: Parse Error: Cannot find member "remove" in base "Array". (main.gd line 9)'])
        self.assertEqual(got, {"Sprite": "Sprite2D", ".remove(": ".remove_at("})


class TestTheTester(unittest.TestCase):
    def run_with(self, out, levels=3):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(G, "godot", return_value=Path("godot.exe")):
            return G.test(Path(d), levels=levels,
                          run=lambda *a, **k: mock.Mock(stdout=out, stderr=""))

    def test_every_level_stood_on(self):
        ok = "".join(f"NEMO LEVEL {i} of 3: platforms 8, coins 6, standing true\n" for i in (1, 2, 3))
        self.assertTrue(self.run_with(ok + "NEMO DONE\n").ok)
        self.assertFalse(self.run_with(ok.replace("standing true", "standing false", 1)
                                       + "NEMO DONE\n").ok)
        self.assertFalse(self.run_with(ok).ok)                        # never finished

    def test_godots_errors_fail_it_with_their_line(self):
        out = ('SCRIPT ERROR: Parse Error: Unexpected "`" in class body.\n'
               '   at: GDScript::reload (res://main.gd:17)\nNEMO DONE\n')
        c = self.run_with(out, levels=None)
        self.assertFalse(c.ok)
        self.assertIn("(main.gd line 17)", c.lines[0])

    def test_a_game_that_runs_out_of_time_keeps_what_godot_said(self):
        # 2026-11-09: a model's script that never quit ran 180 s, its error thrown away.
        import subprocess

        def late(*a, **k):
            raise subprocess.TimeoutExpired("godot", 5, output="SCRIPT ERROR: Parse Error: x\n",
                                            stderr="")
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(G, "godot", return_value=Path("godot.exe")):
            c = G.test(Path(d), levels=None, run=late, timeout=5)
        self.assertFalse(c.ok)
        self.assertIn("SCRIPT ERROR: Parse Error: x", c.lines[0])
        self.assertIn("did not finish in 5 s", c.lines[-1])


class TestTheDepartment(unittest.TestCase):
    def test_on_the_roster_with_its_team(self):
        self.assertEqual(DEPARTMENTS["studio"].name, "Game Studio")
        self.assertEqual([e.title for e in team("studio")],
                         ["Game Designer", "Level Designer", "Programmer", "Tester", "Writer"])

    def test_its_box_makes_an_idea_a_game(self):
        r = asks.answer("studio", "a platformer where a fox collects berries")
        self.assertEqual(r.argv, ["studio", "new", "a platformer where a fox collects berries"])
        self.assertEqual(asks.answer("studio", "play Acorn Run").argv, ["studio", "play", "Acorn Run"])
        self.assertEqual(asks.answer("studio", "list").argv, ["studio", "list"])

    def test_home_sends_a_game_idea_here_and_retro_play_to_gaming(self):
        from nemo.gui import prompt_logic as L
        self.assertEqual(L.department_for("make me a game where a fox jumps")[0], "studio")
        self.assertEqual(L.department_for("play the nes game")[0], "gaming")

    def test_the_laptop_is_told_it_is_the_desktops(self):
        with mock.patch("nemo.machine.is_desktop", return_value=False):
            ok, why = G.available()
        self.assertFalse(ok)
        self.assertIn("desktop's", why)


class TestItsModel(unittest.TestCase):
    """Gemma 4 E4B adopted for the Studio's model games only (owner, 2026-11-11:
    "adopt only models that are usefull to nemo"; docs/model-candidates.md)."""

    def setUp(self):
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def test_the_desktop_writes_model_games_in_game_mode_and_the_laptop_has_none(self):
        from nemo import offline
        with mock.patch("nemo.machine.is_desktop", return_value=True):
            self.assertEqual(G.model_mode(self.cfg), "game")
            self.assertEqual(self.cfg.mode("game")["model"], "gemma4-e4b")
        self.assertIn("gemma4-e4b", offline.MODEL_SOURCES)
        with mock.patch("nemo.machine.is_desktop", return_value=False):
            self.assertIsNone(G.model_mode(self.cfg))
        self.assertIsNone(self.cfg.get("modes.game"))          # the laptop's tables untouched

    def test_it_has_that_one_job(self):
        jobs = [k for k, m in self.cfg.get("modes_desktop").items() if m["model"] == "gemma4-e4b"]
        self.assertEqual(jobs, ["game"])

    def test_an_idea_no_code_builds_loads_game_mode_first(self):
        from nemo import cli, modes
        args = mock.Mock(action="new", words=["a", "boat", "among", "rocks"])
        with mock.patch("nemo.machine.is_desktop", return_value=True), \
             mock.patch.object(modes, "current", return_value=mock.Mock(name="x", running=False)) as cur, \
             mock.patch.object(modes, "start", return_value=(True, "mode 'game' up")) as start, \
             mock.patch.object(G, "make", side_effect=G.StudioError("stop here")), \
             redirect_stdout(io.StringIO()):
            cli.cmd_studio(args, self.cfg)
        start.assert_called_once_with(self.cfg, "game")
        with mock.patch("nemo.machine.is_desktop", return_value=True), \
             mock.patch.object(modes, "start") as start, \
             mock.patch.object(G, "make", side_effect=G.StudioError("stop here")), \
             redirect_stdout(io.StringIO()):
            cli.cmd_studio(mock.Mock(action="new", words=[ACORN]), self.cfg)
        start.assert_not_called()                               # a kind code builds needs none


@unittest.skipUnless(G.godot() is not None, "Godot is not installed here")
class TestARealGame(unittest.TestCase):
    """Made by code and run in the real Godot (4.7.2 here, 2026-11-09)."""

    def test_made_and_tested(self):
        from nemo.config import Config
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, _sandbox.home_env(d)), \
             mock.patch("nemo.machine.is_desktop", return_value=True):
            cfg = Config.load(Path("/nonexistent"))
            with redirect_stdout(io.StringIO()):
                made = G.make(cfg, ACORN)
            self.assertTrue(made.check.ok, made.check.lines)
            self.assertEqual(made.check.levels, 3)
            self.assertIn("Left and Right arrows", (made.where / "README.md").read_text(encoding="utf-8"))
            self.assertEqual([g["title"] for g in G.games(cfg)], ["Acorn Run"])


if __name__ == "__main__":
    unittest.main()
