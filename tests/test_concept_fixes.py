"""The Workshop's concept art (owner, 2026-11-04: "fix concept art in
workshop"): what was wrong, found by running the step for real."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import blockout, router

ROOT = Path(__file__).resolve().parent.parent


def shape(kind, at, **size):
    s = {"shape": kind, "op": "add", "at": list(at), "label": kind}
    s.update(size)
    return s


class TestHiddenShapes(unittest.TestCase):
    def test_a_shape_inside_a_box_is_hidden(self):
        doc = {"shapes": [shape("box", (0, 0, 0), size=[100, 50, 20]),
                          shape("cylinder", (10, 0, 5), radius=3, height=8)]}
        self.assertEqual(blockout.hidden(doc), ["cylinder"])

    def test_one_inside_a_cylinders_outline_is_not_called_hidden(self):
        # A round solid's outline box has empty corners: it may show there.
        doc = {"shapes": [shape("cylinder", (0, 0, 0), radius=20, height=40),
                          shape("box", (15, 15, 30), size=[6, 6, 6])]}
        self.assertEqual(blockout.hidden(doc), [])

    def test_one_that_sticks_out_shows(self):
        doc = {"shapes": [shape("box", (0, 0, 0), size=[100, 50, 20]),
                          shape("cylinder", (40, 0, 5), radius=3, height=30, rotate=[0, 90, 0])]}
        self.assertEqual(blockout.hidden(doc), [])


class TestNoModelIsSaid(unittest.TestCase):
    """With no mode loaded the step said the model 'stopped answering part
    way through', which it never began (2026-11-04)."""

    def test_a_refused_connection_is_no_model(self):
        exc = urllib.error.URLError(ConnectionRefusedError(10061, "actively refused"))
        self.assertTrue(router.explain_failure(exc, 1800).startswith("No language model is loaded"))
        self.assertTrue(router.explain_failure(ConnectionRefusedError(), 1800).startswith("No language"))

    def test_a_dropped_connection_is_still_stopped_part_way(self):
        exc = urllib.error.URLError(ConnectionResetError(10054, "reset"))
        self.assertIn("stopped answering part way through", router.explain_failure(exc, 1800))

    def test_the_doctors_know_the_new_words(self):
        from nemo import clinic
        self.assertIn("No language model is loaded", clinic.MODEL_NOTES)
        self.assertEqual(len(clinic.MODEL_NOTES["No language model is loaded"]), 4)


@unittest.skipUnless(_sandbox.has_display(), "needs a display")
class TestTheChooserFitsTheScreen(unittest.TestCase):
    def test_a_window_reaching_under_the_taskbar_is_moved_up(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                win = A.tk.Toplevel(app); win.geometry("400x500+50+400"); app.update()
                with mock.patch.object(A, "work_area", return_value=(0, 0, 1366, 720)):
                    A._fit_on_screen(win); app.update()
                frame = win.winfo_rooty() - win.winfo_y()
                self.assertLessEqual(win.winfo_y() + frame + win.winfo_height(), 720)
                win.geometry("400x900+50+0"); app.update()
                with mock.patch.object(A, "work_area", return_value=(0, 0, 1366, 720)):
                    A._fit_on_screen(win); app.update()
                self.assertLessEqual(win.winfo_height(), 720)
                win.destroy()
            finally:
                app.destroy()

    def test_every_dialog_is_fitted_and_its_timer_dies_with_it(self):
        src = (ROOT / "nemo" / "gui" / "app.py").read_text(encoding="utf-8")
        body = src[src.index("def _dialog("):src.index("def _dialog(") + 600]
        self.assertIn("_fit_on_screen", body)
        self.assertIn("_cancel(win, job)", body)


class TestTheBlueprint(unittest.TestCase):
    """Owner, 2026-11-04: "change from blockout to blueprint in concept"."""

    def twin_doc(self):
        return {"name": "t", "shapes": [
            shape("box", (0, 0, 0), size=[100, 50, 20]) | {"label": "Stock"},
            shape("box", (0, 0, 0), size=[100, 50, 20]) | {"label": "Base"},
            shape("cylinder", (60, 0, 10), radius=5, height=60, rotate=[0, 90, 0]) | {"label": "Barrel"},
            shape("plate", (0, 0, 5), size=[10, 10], thickness=4) | {"label": "Spring"}]}

    def test_of_two_identical_boxes_the_first_shows(self):
        # B's Stock and Base were the same box: each inside the other, so both
        # were called hidden and the blueprint dashed the whole stock.
        self.assertEqual(blockout.hidden(self.twin_doc()), ["Base", "Spring"])

    def test_it_is_white_on_blue_and_dashes_only_the_hidden(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            p = blockout.blueprint_png(self.twin_doc(), Path(t) / "b.png", "A: test")
            im = Image.open(p).convert("RGB")
            self.assertEqual(im.getpixel((5, 5)), blockout.BP_BLUE)
            # The frame is drawn in ink: the marker render's own INK (near
            # black) once took its place, and the blueprint came out dark.
            self.assertGreater(min(im.getpixel((12, 300))), 200)       # white, not dark
            colours = {c for _, c in im.getcolors(1 << 20)}
            self.assertIn(blockout.BP_FAINT, colours)                # the dashed ones

    def project_with_an_old_sketch(self, t):
        from nemo import concept
        root = Path(t)
        c = concept.Concept(key="A", title="Simple", corners="", notch_wall="", order=[],
                            placed=[], kind="blockout", spec=self.twin_doc())
        d = concept.folder(root); d.mkdir(parents=True)
        (d / "A-sketch.png").write_bytes(b"old")
        return concept, root, c, d

    def test_an_older_project_shows_its_sketch_until_it_has_a_blueprint(self):
        with tempfile.TemporaryDirectory() as t:
            concept, root, c, d = self.project_with_an_old_sketch(t)
            self.assertEqual(concept.picture(root, c).name, "A-sketch.png")
            concept.ensure_blueprints(root, [c])                    # no model asked
            self.assertEqual(concept.picture(root, c).name, "A-blueprint.png")
            self.assertTrue(concept.picture(root, c).stat().st_size > 1000)

    def test_a_new_project_draws_a_blueprint(self):
        from nemo import concept
        with tempfile.TemporaryDirectory() as t:
            c = concept.Concept(key="B", title="More", corners="", notch_wall="", order=[],
                                placed=[], kind="blockout", spec=self.twin_doc())
            concept.save_painted(Path(t), [c], "sig")
            d = concept.folder(Path(t))
            self.assertEqual(sorted(p.name for p in d.glob("*.png")), ["B-blueprint.png"])
            self.assertIn("blueprint", concept.describe(concept.Choice(concept="B", corners="", notch_wall="",
                                                                        kind="blockout", title="More")))

    def test_the_words_say_blueprint(self):
        self.longMessage = False
        for f in ("nemo/pipeline.py", "nemo/review.py", "nemo/gui/app.py", "nemo/staff.py"):
            src = (ROOT / f).read_text(encoding="utf-8")
            self.assertNotIn("two blockouts", src, msg=f)
            self.assertNotIn("blockout chosen", src, msg=f)


if __name__ == "__main__":
    unittest.main()
