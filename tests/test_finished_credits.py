"""The Storeroom's Finished shelf and the credits (owner, 2026-11-11: "Finished projects
from which ever department gets sent to storehouse with way to view all parts of project
from that department"; "Any parts or code used in creating Nemo has a link at end of
nemodoc run to storehouse where shows all programmers and creators of programs used to
create it"; "My creative title in list will be only known as Highjive")."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import credits as K, finished as F
from nemo.config import Config

APP = Path(__file__).resolve().parent.parent


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, _sandbox.home_env(self.tmp.name))
        self.env.start()
        self.cfg = Config.load(Path("/nonexistent"))
        for key in ("projects", "stories", "storeroom", "models", "studio"):
            self.cfg.data["paths"][key] = str(self.home / key)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def put(self, rel: str, text: str = "x"):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class TestTheFinishedShelf(Home):
    def test_every_department_finished_work_and_nothing_unfinished(self):
        self.put("projects/desk/BUILD.md"); self.put("projects/desk/enclosure/housing.stl")
        self.put("projects/desk/enclosure/drawings/housing.pdf")
        self.put("projects/half-done/brief.yaml")                      # no build guide: not finished
        self.put("stories/cat/story.md", "# The Keeper's Cat\n\n## 1. Night\n\nWords.\n")
        self.put("storeroom/film-studio/River/film.json", "{}")
        self.put("models/tag/model.stl"); self.put("models/tag/spec.json", json.dumps({"title": "Shed key tag"}))
        self.put("projects/.git/HEAD")                                  # hidden: never a piece
        found = F.gather(self.cfg)
        by = F.by_department(found)
        self.assertEqual(sorted(by), ["art_studio", "film", "library", "workshop"])
        self.assertEqual([p.title for p in by["workshop"]], ["desk"])
        self.assertEqual(by["library"][0].title, "The Keeper's Cat")
        self.assertEqual(by["art_studio"][0].title, "Shed key tag")
        self.assertTrue((self.home / "storeroom" / "finished" / "shelf.json").is_file())

    def test_all_the_parts_of_a_piece_folder_by_folder(self):
        self.put("projects/desk/BUILD.md"); self.put("projects/desk/enclosure/housing.stl")
        self.put("projects/desk/enclosure/drawings/housing.pdf")
        self.put("projects/desk/.speech/last.wav")                      # hidden folders left out
        piece = F.gather(self.cfg)[0]
        self.assertEqual(piece.parts, 3)
        self.assertEqual([(g, f.name) for g, f in F.parts(piece)],
                         [("", "BUILD.md"), ("enclosure", "housing.stl"),
                          ("enclosure/drawings", "housing.pdf")])

    def test_a_department_sends_what_it_finishes(self):
        folder = self.put("stories/cat/story.md", "# Cat\n\n## 1. A\n\nB\n").parent
        self.assertIsNone(F.send(self.cfg, "studio", folder))          # not a game
        sent = F.send(self.cfg, "library", folder)
        self.assertTrue(sent.sent)
        again = F.gather(self.cfg)[0]
        self.assertEqual(again.sent, sent.sent)                         # remembered by the shelf

    def test_where_the_departments_send_it(self):
        cli = (APP / "nemo" / "cli.py").read_text(encoding="utf-8")
        for dept in ("art_studio", "studio", "workshop", "library"):
            self.assertIn(f'_send_finished(cfg, "{dept}"', cli)
        self.assertIn('finished.send(self.cfg, "workshop", self.p.root)',
                      (APP / "nemo" / "pipeline.py").read_text(encoding="utf-8"))
        self.assertIn('"finished"])', cli)                              # nemo store finished


class TestTheCredits(Home):
    def test_nemo_is_highjives_and_every_maker_is_named_without_an_email(self):
        self.put("storeroom/games/HOMEBREW.txt",
                 "NES: Thwaite.nes\n  by Damian Yerrick (pinobatch); licence GPL-3.0\n"
                 "  from https://github.com/pinobatch/thwaite-nes/releases/x.nes\n")
        cs = K.everyone(self.cfg)
        self.assertEqual(K.CREATOR, "Highjive")
        self.assertEqual((cs[0].name, cs[0].by), ("Nemo", "Created by Highjive"))
        groups = {c.group for c in cs}
        for g in ("Tools Nemo fetches and pins", "Programs on NemoIso and Windows",
                  "Language models", "Python packages", "Homebrew games"):
            self.assertIn(g, groups)
        self.assertFalse([c for c in cs if "@" in c.by])
        game = next(c for c in cs if c.group == "Homebrew games")
        self.assertEqual((game.name, game.by, game.licence),
                         ("Thwaite.nes", "Damian Yerrick (pinobatch)", "GPL-3.0"))
        self.assertIn("llama.cpp", [c.name for c in cs])

    def test_names_only(self):
        self.assertEqual(K._people("Ann Lee <ann@x.org>, Bo <bo@y.io>"), "Ann Lee, Bo")
        self.assertEqual(K._people("dev@z.com"), "")

    def test_the_page_is_in_the_storeroom(self):
        page = K.write(self.cfg)
        self.assertEqual(page, self.home / "storeroom" / "credits" / "index.html")
        self.assertIn("Nemo was created by Highjive", page.read_text(encoding="utf-8"))
        self.assertTrue((page.parent / "credits.txt").is_file())

    def test_nemodoc_ends_with_its_link(self):
        doc = (APP / "install" / "linux" / "nemodoc").read_text(encoding="utf-8")
        self.assertIn('"$VENV/bin/nemo" credits', doc)
        self.assertIn("Who made what Nemo is built from:", doc)
        ps = (APP / "NemoDoc.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("& $NemoCmd credits", ps)
        self.assertIn("Who made what Nemo is built from: ", ps)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestInTheStoreroomWindow(Home):
    def test_finished_work_and_its_parts(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.put("projects/desk/BUILD.md"); self.put("projects/desk/enclosure/housing.stl")
        app = A.NemoApp(); app.update()
        try:
            app.cfg = self.cfg
            w = A.FinishedWork(app); app.update()
            top = w.pieces.get_children()[0]
            self.assertEqual(w.pieces.item(top, "text"), "Workshop (1)")
            piece = w.pieces.get_children(top)[0]
            w.pieces.selection_set(piece); w.show()
            names = [w.parts.item(i, "text") for g in w.parts.get_children()
                     for i in w.parts.get_children(g)]
            self.assertEqual(names, ["BUILD.md", "housing.stl"])
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
