"""D142: parts the library says must be kept apart, kept apart by code.

The tag player's speaker carries the note "Magnet will affect the RC522
antenna. Keep at least 25 mm apart." On the real laptop the model's order
put the two 4.4 mm apart, four runs running, and nothing but a sentence in
the build guide said so. The distance is now a field of the part, the
enclosure step lays the parts out to honour it, and a check reads the
layout that was actually written.
"""
from __future__ import annotations

import json, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks, enclosure
from nemo.checks.deterministic import PASS, Result
from nemo.parts import PartsLibrary, _build_part
from nemo.pipeline import Pipeline
from nemo.project import Brief
from test_enclosure_layout import LayoutRouter
from test_gates_real import WeatherCase
from test_pipeline import PipelineCase

REFS = ("esp32_devkit_v1", "rc522", "dfplayer_mini", "speaker_8ohm_20mm")
# The order qwen3-1.7b chose on the AH531, all four times it was asked.
REAL_ORDER = ["dfplayer_mini", "esp32_devkit_v1", "rc522", "speaker_8ohm_20mm"]
HW = {"min_wall_mm": 1.2, "nozzle_mm": 0.4}
PAIR = ("rc522", "speaker_8ohm_20mm")


def gap(placed, pair=PAIR):
    return next(d for a, b, d in enclosure.gaps(placed) if {a, b} == set(pair))


class TestTheLibrary(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()

    def test_the_speaker_carries_the_distance_its_own_note_gives(self):
        spk = self.lib.get("speaker_8ohm_20mm")
        self.assertEqual(spk.keep_apart, {"rc522": 25.0})
        self.assertIn("Keep at least 25 mm apart", spk.notes)

    def test_no_other_part_has_one_because_no_other_note_gives_a_distance(self):
        others = {p.ref: p.keep_apart for p in self.lib.parts.values() if p.keep_apart}
        self.assertEqual(list(others), ["speaker_8ohm_20mm"])

    def test_every_part_named_in_one_exists(self):
        for p in self.lib.parts.values():
            for other in p.keep_apart:
                self.assertIsNotNone(self.lib.get(other), f"{p.ref} -> {other}")

    def test_a_mistyped_field_is_refused_when_the_library_loads(self):
        for bad in ({"rc522": "far"}, {"rc522": 0}, {"rc522": -5}, {"rc522": True}, ["rc522"], 25):
            with self.assertRaises(ValueError, msg=repr(bad)) as ctx:
                _build_part("x", {"name": "X", "category": "sensor", "keep_apart": bad})
            self.assertIn("keep_apart", str(ctx.exception))

    def test_a_part_without_the_field_has_none(self):
        self.assertEqual(_build_part("x", {"name": "X", "category": "sensor"}).keep_apart, {})


class TagParts(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()
        self.parts = [self.lib.get(r) for r in REFS]
        self.box = enclosure.box_for([120, 80, 40], HW)


class TestWhichPairs(TagParts):
    def test_the_pair_is_found_whichever_part_says_so(self):
        self.assertEqual(enclosure.keep_apart_pairs(self.parts), [(*PAIR, 25.0)])
        self.assertEqual(enclosure.keep_apart_pairs(list(reversed(self.parts))), [(*PAIR, 25.0)])

    def test_there_is_none_when_the_other_part_is_not_in_the_project(self):
        without = [p for p in self.parts if p.ref != "rc522"]
        self.assertEqual(enclosure.keep_apart_pairs(without), [])


class TestTheLayout(TagParts):
    def test_the_models_order_left_them_4_4_mm_apart(self):
        placed = enclosure.auto_layout(self.parts, self.box, REAL_ORDER)
        self.assertEqual(enclosure.too_close(placed, self.parts), [(*PAIR, 25.0, 4.4)])

    def test_a_layout_is_found_that_keeps_them_apart_and_is_sound(self):
        placed, order, short = enclosure.layout_keeping_apart(self.parts, self.box, [REAL_ORDER])
        self.assertIsNotNone(placed)
        self.assertEqual(short, 0.0)
        self.assertEqual(enclosure.faults(placed, self.box), [])
        self.assertEqual(enclosure.too_close(placed, self.parts), [])
        self.assertGreaterEqual(gap(placed), 25.0)
        self.assertEqual(sorted(a.ref for a in placed), sorted(REFS))

    def test_spreading_a_layout_keeps_it_sound_and_moves_no_part_nearer_the_origin(self):
        base = enclosure.auto_layout(self.parts, self.box, REAL_ORDER)
        wide = {a.ref: a for a in enclosure.spread(base, self.box)}
        self.assertEqual(enclosure.faults(list(wide.values()), self.box), [])
        for a in base:
            self.assertGreaterEqual(wide[a.ref].x, a.x)
            self.assertGreaterEqual(wide[a.ref].y, a.y)

    def test_where_no_layout_will_do_it_says_by_how_much(self):
        two = [self.lib.get(r) for r in PAIR]
        small = enclosure.box_for([100, 50, 40], HW)
        enclosure.auto_layout(two, small)                    # they do fit
        placed, order, short = enclosure.layout_keeping_apart(two, small, [])
        self.assertIsNone(placed)
        self.assertEqual(order, [])
        self.assertGreater(short, 5)
        self.assertLess(short, 25)

    def test_parts_with_nothing_to_keep_apart_are_laid_out_as_before(self):
        plain = [p for p in self.parts if p.ref != "speaker_8ohm_20mm"]
        placed = enclosure.auto_layout(plain, self.box)
        self.assertEqual(enclosure.too_close(placed, plain), [])


class TestTheCheck(TagParts):
    def write(self, placed):
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        path = self.tmp / "layout.json"
        sizes = {p.ref: p.size_mm[0] for p in self.parts}
        path.write_text(json.dumps({a.ref: {"x_mm": a.x, "y_mm": a.y,
                                            "turned": a.dx != sizes[a.ref]} for a in placed}),
                        encoding="utf-8")
        return path

    def test_the_layout_from_the_real_run_fails_with_both_figures_and_the_reason(self):
        r = Pipeline.check_keep_apart(
            self.write(enclosure.auto_layout(self.parts, self.box, REAL_ORDER)), self.parts)
        self.assertEqual(r.status, "FAIL")
        text = r.render()
        self.assertIn("rc522 and speaker_8ohm_20mm: 4.4 mm apart, at least 25 mm needed", text)
        self.assertIn("Magnet will affect the RC522 antenna", text)

    def test_the_layout_code_makes_passes_and_says_how_far(self):
        placed, _, _ = enclosure.layout_keeping_apart(self.parts, self.box, [REAL_ORDER])
        r = Pipeline.check_keep_apart(self.write(placed), self.parts)
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn("1 pair(s) far enough apart", r.detail)
        self.assertIn(f"{gap(placed):g} mm apart", r.render())

    def test_it_reads_the_file_not_what_the_step_meant_to_write(self):
        path = self.write(enclosure.layout_keeping_apart(self.parts, self.box, [REAL_ORDER])[0])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["speaker_8ohm_20mm"] = {"x_mm": 66.6, "y_mm": 35.1, "turned": False}   # run 1
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(Pipeline.check_keep_apart(path, self.parts).status, "FAIL")

    def test_nothing_to_keep_apart_or_nothing_to_read_is_a_skip(self):
        plain = [p for p in self.parts if p.ref != "rc522"]
        self.assertEqual(Pipeline.check_keep_apart(Path("nowhere.json"), plain).status, checks.SKIP)
        self.assertEqual(Pipeline.check_keep_apart(Path("nowhere.json"), self.parts).status,
                         checks.SKIP)


class StepCase(PipelineCase):
    PARTS, ENVELOPE = REFS, [120, 80, 40]

    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="tag-player", function="Plays a sound track when a tag is held near it.",
            power="USB 5 V 1 A", supply_ma=1000, rails=[5.0, 3.3], envelope_mm=self.ENVELOPE,
            parts=list(self.PARTS), mcu="esp32", done_when="A tag plays its track.",
            # With no constraint the model is not asked for an order (D172),
            # and these are about what is done with the order it gives.
            constraints=["The speaker must not sit beside the reader."]))
        self.parts = [self.lib.get(r) for r in self.PARTS]

    def run_step(self, order):
        gen = Result("enclosure_script", PASS, "generated housing.stl")
        with mock.patch.object(checks, "generate_enclosure", return_value=gen), \
             mock.patch.object(checks, "solid", return_value=Result("solid", PASS, "ok")), \
             mock.patch.object(checks, "thickness", return_value=Result("thickness", PASS, "ok")):
            return self.pipe(LayoutRouter({"order": order})).stage_enclosure()

    def layout(self):
        return enclosure.placed_from(json.loads(
            (self.project.housing_script.parent / "layout.json").read_text(encoding="utf-8")),
            self.parts)


class TestTheStep(StepCase):
    def test_the_models_order_is_laid_out_again_and_the_step_says_why(self):
        sr = self.run_step(REAL_ORDER)
        self.assertTrue(sr.ok, sr.render())
        text = sr.render()
        self.assertIn("The parts library says to keep rc522 and speaker_8ohm_20mm at least "
                      "25 mm (they were 4.4) apart, so Nemo kept that order and pushed the "
                      "end of each row to the far wall.", text)
        self.assertGreaterEqual(gap(self.layout()), 25.0)
        check = next(r for r in sr.results if r.name == "keep_apart")
        self.assertEqual(check.status, PASS)

    def test_an_order_that_cannot_do_it_is_replaced_and_the_new_one_named(self):
        # Reader and speaker side by side at the start of the first row.
        sr = self.run_step(["rc522", "speaker_8ohm_20mm", "dfplayer_mini", "esp32_devkit_v1"])
        self.assertTrue(sr.ok, sr.render())
        self.assertGreaterEqual(gap(self.layout()), 25.0)
        self.assertRegex(sr.render(), r"so Nemo (laid the parts out again: |kept that order)")

    def test_the_script_that_is_written_is_of_that_layout(self):
        self.run_step(REAL_ORDER)
        spk = next(a for a in self.layout() if a.ref == "speaker_8ohm_20mm")
        script = self.project.housing_script.read_text(encoding="utf-8")
        self.assertIn(f"p_speaker_8ohm_20mm = ({spk.x:g}, {spk.y:g}, ", script)

    def test_the_distances_reported_are_of_what_was_built(self):
        sr = self.run_step(REAL_ORDER)
        self.assertNotIn("rc522 to speaker_8ohm_20mm 4.4 mm", sr.render())

    def test_it_has_a_plain_name_for_the_window(self):
        from nemo.gui import controller as C
        names = [v for v in vars(C).values() if isinstance(v, dict) and "harness_pins" in v][0]
        self.assertEqual(names["keep_apart"], "Parts that must be apart are")


class TestAnEnvelopeTooSmallForIt(StepCase):
    PARTS, ENVELOPE = PAIR, [100, 50, 40]

    def test_the_step_fails_says_by_how_much_and_sends_the_owner_to_the_brief(self):
        sr = self.run_step(list(PAIR))
        self.assertFalse(sr.ok)
        self.assertEqual(sr.go_back_to, "brief")
        text = sr.render()
        self.assertIn("no layout of these parts in this envelope does it", text)
        self.assertIn("Make the envelope larger", text)
        self.assertIn("Magnet will affect the RC522 antenna", text)
        self.assertEqual(next(r for r in sr.results if r.name == "keep_apart").status, "FAIL")


class TestAProjectWithNoSuchParts(WeatherCase):
    def test_gets_no_extra_line_in_its_results(self):
        gen = Result("enclosure_script", PASS, "generated housing.stl")
        order = {"order": ["bme280", "ssd1306_oled_096", "esp32_devkit_v1"]}
        with mock.patch.object(checks, "generate_enclosure", return_value=gen), \
             mock.patch.object(checks, "solid", return_value=Result("solid", PASS, "ok")), \
             mock.patch.object(checks, "thickness", return_value=Result("thickness", PASS, "ok")):
            sr = self.pipe(LayoutRouter(order)).stage_enclosure()
        self.assertTrue(sr.ok, sr.render())
        self.assertNotIn("keep_apart", [r.name for r in sr.results])
        self.assertNotIn("laid the parts out again", sr.render())


if __name__ == "__main__":
    unittest.main()
