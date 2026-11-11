"""D153: a check with nothing to check is not asked, and so is not listed
in the build guide as unchecked.

Every real run of the weather brief and the tilt lamp ended with these two
lines among the guide's open questions:

  - [electrical] unchecked: voltage_compat -- no two parts share a bus pin, ...
  - [enclosure] unchecked: xref_cutouts -- no panel-mounted parts

and with "A skipped check is not a passed check -- install the missing
tool before trusting the output." No tool was missing. Open questions the
owner can do nothing about teach him to stop reading them.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks
from nemo.checks.deterministic import PASS, SKIP, Result
from nemo.project import Brief
from test_enclosure_layout import LayoutRouter
from test_gates_real import WeatherCase
from test_harness import SchemaRouter, good
from test_pipeline import PipelineCase, StubRouter


def enclosure_step(case, order):
    gen = Result("enclosure_script", PASS, "generated housing.stl")
    with mock.patch.object(checks, "generate_enclosure", return_value=gen), \
         mock.patch.object(checks, "solid", return_value=Result("solid", PASS, "ok")), \
         mock.patch.object(checks, "thickness", return_value=Result("thickness", PASS, "ok")):
        return case.pipe(LayoutRouter({"order": order})).stage_enclosure()


def electrical_step(case, router):
    gen = Result("schematic", PASS, "generated project.kicad_sch")
    with mock.patch.object(checks, "generate_schematic", return_value=gen), \
         mock.patch.object(checks, "erc", return_value=Result("erc", PASS, "clean")):
        return case.pipe(router).stage_electrical()


class TestCutouts(WeatherCase):
    def test_a_project_with_no_panel_part_is_not_asked_about_cutouts(self):
        sr = enclosure_step(self, ["bme280", "ssd1306_oled_096", "esp32_devkit_v1"])
        self.assertTrue(sr.ok, sr.render())
        self.assertNotIn("xref_cutouts", [r.name for r in sr.results])
        self.assertNotIn("SKIP", sr.render())

    def test_the_check_itself_still_skips_when_handed_nothing(self):
        self.assertEqual(checks.xref_cutouts(self.parts, set()).status, SKIP)


class TestCutoutsWhereThereIsAPanelPart(PipelineCase):
    REFS = ("esp32_devkit_v1", "rc522", "dfplayer_mini", "speaker_8ohm_20mm")

    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="tag-player", function="Plays a sound track when a tag is held near it.",
            power="USB 5 V 1 A", supply_ma=1000, rails=[5.0, 3.3], envelope_mm=[120, 80, 40],
            parts=list(self.REFS), mcu="esp32", done_when="A tag plays its track."))

    def test_it_is_asked_and_answers(self):
        sr = enclosure_step(self, ["dfplayer_mini", "esp32_devkit_v1", "rc522",
                                   "speaker_8ohm_20mm"])
        result = next(r for r in sr.results if r.name == "xref_cutouts")
        self.assertEqual(result.status, PASS, sr.render())


class TestLogicLevels(WeatherCase):
    def test_where_the_wires_were_checked_the_older_comparison_is_not_run(self):
        sr = electrical_step(self, SchemaRouter(good()))
        self.assertTrue(sr.ok, sr.render())
        names = [r.name for r in sr.results]
        self.assertIn("harness_levels", names)
        self.assertNotIn("voltage_compat", names)

    def test_where_they_were_not_it_still_is(self):
        # A router that cannot hold a reply to a schema: the old request, the
        # old check, as before.
        r = StubRouter('```python\nopen("project.kicad_sch", "w").write("(kicad_sch)")\n```')
        sr = electrical_step(self, r)
        self.assertIn("voltage_compat", [x.name for x in sr.results])


class TestTheGuide(WeatherCase):
    def test_neither_line_reaches_the_open_questions(self):
        electrical = electrical_step(self, SchemaRouter(good()))
        enclosure = enclosure_step(self, ["bme280", "ssd1306_oled_096", "esp32_devkit_v1"])
        self.pipe(StubRouter()).stage_pack([electrical, enclosure])
        text = self.project.build_md.read_text(encoding="utf-8")
        tail = text[text.index("## Open questions"):]
        self.assertNotIn("unchecked:", tail)
        self.assertIn("- None recorded.", tail)

    def test_a_check_that_really_could_not_run_is_still_listed(self):
        missing = Result("erc", SKIP, "kicad-cli not found", ["install KiCad"])
        from nemo.pipeline import StageResult
        self.pipe(StubRouter()).stage_pack([StageResult("electrical", True, [missing])])
        text = self.project.build_md.read_text(encoding="utf-8")
        self.assertIn("- [electrical] unchecked: erc -- kicad-cli not found", text)


class TestTheSkipLine(unittest.TestCase):
    def test_it_no_longer_blames_a_missing_tool(self):
        text, fails, skips = checks.summarise([Result("x", SKIP, "nothing to compare")])
        self.assertEqual((fails, skips), (0, 1))
        self.assertIn("A skipped check is not a passed check", text)
        self.assertIn("read why each was skipped", text)
        self.assertNotIn("install the missing tool", text)


if __name__ == "__main__":
    unittest.main()
