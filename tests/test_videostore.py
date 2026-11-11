"""The Storeroom as a 90s video store, and the Storeroom checked before any
part is asked for (owner, 2026-10-21).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import review, storeroom, videostore


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        self.shelf = self.t / "nemo-storeroom"

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.t, ignore_errors=True)

    def put(self, rel: str, data: bytes = b"x") -> Path:
        p = self.t / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def stock(self):
        self.put("nemo-stories/the-fox/request.md", b"A fox story\n")
        self.put("nemo-stories/the-fox/story.md", b"# The fox\n")
        self.put("nemo-storeroom/games/nes/Cart.nes")
        self.put("nemo-storeroom/videos/Holiday film.mp4")
        self.put("nemo-storeroom/videos/Tape.avi")
        self.put("nemo-storeroom/pictures/Beach.png")
        storeroom.add(self.shelf, "ESP32 board", 2, part="esp32_devkit_v1", where="drawer 3")
        storeroom.add(self.shelf, "RC522 RFID reader", 1, where="drawer 2")


class TestTheAisles(AHome):
    def test_each_kind_on_its_aisle(self):
        self.stock()
        got = videostore.shelves(self.cfg)
        self.assertEqual(list(got), list(videostore.AISLES))
        self.assertEqual([c.title for c in got["BOOKS"]], ["The fox"])
        self.assertEqual(got["BOOKS"][0].actions, ("Read",))
        self.assertEqual([(c.title, c.subtitle) for c in got["GAMES"]], [("Cart", "NES")])
        self.assertEqual({c.title: c.actions for c in got["VIDEOS"]},
                         {"Holiday film": ("Play here", "Cast..."), "Tape": ("Play here",)})
        self.assertEqual([c.title for c in got["PICTURES"]], ["Beach"])
        self.assertEqual([c.subtitle for c in got["PARTS"]], ["x2, drawer 3", "x1, drawer 2"])

    def test_an_aisle_that_cannot_be_read_says_so_and_the_rest_show(self):
        self.stock()
        self.put("nemo-storeroom/stock.yaml", b"a: [unclosed")
        got = videostore.shelves(self.cfg)
        self.assertEqual(got["PARTS"][0].title, "Cannot be read")
        self.assertEqual(len(got["GAMES"]), 1)


class TestPartsAreCheckedFirst(AHome):
    def test_on_hand_and_to_get(self):
        self.stock()
        have, need = storeroom.check_parts(self.shelf, ["esp32_devkit_v1", "rc522"])
        self.assertEqual(list(have), ["esp32_devkit_v1"])
        self.assertEqual(need, ["rc522"])               # a name alone is not the part
        self.assertEqual(storeroom.describe_stock(have, need),
                         "Storeroom: on hand esp32_devkit_v1 (2, drawer 3); to get: rc522.")

    def test_the_inspector_says_it_before_the_parts_step(self):
        self.stock()
        from nemo.project import Brief, Project
        p = Project(self.t / "nemo-projects" / "chest")
        p.create(Brief(name="chest", parts=["esp32_devkit_v1", "rc522"], mcu="esp32_devkit_v1"))
        from nemo.parts import PartsLibrary
        _, notes = review.before("parts", p, PartsLibrary.load())
        self.assertIn("Storeroom: on hand esp32_devkit_v1 (2, drawer 3); to get: rc522.", notes)

    def test_on_the_shelves_by_name_is_not_looked_up_online(self):
        self.stock()
        self.assertEqual([i.name for i in storeroom.on_shelf_named(self.shelf, "RFID reader")],
                         ["RC522 RFID reader"])
        self.assertEqual(storeroom.on_shelf_named(self.shelf, "fingerprint sensor"), [])
        from nemo import workflow
        from nemo.checks import FAIL, Result
        stop = Result("review_missing_rfid", FAIL, "no RFID reader")
        said = []
        project = mock.Mock(root=self.t / "p")
        project.load_brief.return_value = mock.Mock(mcu="esp32_devkit_v1")
        with mock.patch("nemo.review.before", return_value=([stop], [])), \
             mock.patch("nemo.review.record"), \
             mock.patch("nemo.review.researchable", return_value=[("missing_rfid", "RFID reader")]), \
             mock.patch("nemo.research.look_up") as online:
            workflow.run_step("parts", project, mock.Mock(), [], said.append)
        online.assert_not_called()
        self.assertTrue(any("may be on the shelves: RC522 RFID reader (1, drawer 2)" in s
                            for s in said), said)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_cases_and_what_they_do(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.stock()
        app = A.NemoApp(); app.update()
        try:
            w = A.VideoStore(app); app.update()
            self.assertEqual(len(w.cases), 7)
            game = next(i for i, c in enumerate(w.cases) if c.aisle == "GAMES")
            menu = w.clicked(game)
            self.assertEqual(menu.entrycget(0, "label"), "Play")
            with mock.patch("nemo.gaming.play") as play:
                w.act(game, "Play")
            self.assertEqual(play.call_args[0][0].name, "Cart")
            part = next(i for i, c in enumerate(w.cases) if c.title == "ESP32 board")
            w.act(part, "Details")
            self.assertIn("2 on hand, in drawer 3; library part esp32_devkit_v1", w.note.cget("text"))
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
