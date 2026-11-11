"""What the second real pipeline run on the AH531 let through.

2026-10-05, the same three-part brief, after D125-D130:

  D131  The enclosure step wrote housing.py and never ran it. With no
        mesh, its three checks skipped, and the step was recorded as
        passed. D104 fixed exactly this for the schematic script and the
        enclosure script was left as it was. CadQuery was not installed.

  Also from that run, in the firmware step: the model was told "the
  netlist is authoritative for pins" and given no netlist and no wiring,
  so it invented pin numbers; and it included a header that does not
  exist, was told so by the compiler, and included it again three times.

The enclosure tests use stand-in scripts. generate_enclosure has NOT been
run against real CadQuery: it is not installed on the machine.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks
from nemo.checks.deterministic import FAIL, PASS, SKIP, Result
from nemo.pipeline import Pipeline
from test_gates_real import GOOD_HARNESS, WeatherCase
from test_pipeline import StubRouter

WRITES_MESH = 'open("housing.stl", "w").write("solid x\\nendsolid x\\n")\n'
# What Python says when CadQuery is missing, whether or not it is installed
# here (it is on the AH531, which skipped this test until 2026-10-28).
NO_CADQUERY = "raise ModuleNotFoundError(\"No module named 'cadquery'\")\n"
RAISES = 'raise ValueError("fillet radius too large")\n'
WRITES_NOTHING = 'print("built the model and forgot to export it")\n'
WRONG_NAME = 'open("case.stl", "w").write("solid x\\nendsolid x\\n")\n'


class TestGenerateEnclosure(WeatherCase):
    def run_script(self, source, **kw):
        script = self.project.housing_script
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(source, encoding="utf-8")
        return checks.generate_enclosure(script, self.project.housing_stl, **kw)

    def test_a_script_that_exports_its_mesh_passes(self):
        r = self.run_script(WRITES_MESH)
        self.assertEqual(r.status, PASS, r.render())
        self.assertTrue(self.project.housing_stl.exists())

    def test_a_script_that_raises_fails_with_its_last_lines(self):
        r = self.run_script(RAISES)
        self.assertEqual(r.status, FAIL)
        self.assertIn("fillet radius too large", r.render())

    def test_a_script_that_exports_nothing_fails(self):
        r = self.run_script(WRITES_NOTHING)
        self.assertEqual(r.status, FAIL)
        self.assertIn("wrote no housing.stl", r.detail)

    def test_a_mesh_under_another_name_is_named_in_the_failure(self):
        r = self.run_script(WRONG_NAME)
        self.assertEqual(r.status, FAIL)
        self.assertIn("case.stl", r.render())

    def test_a_mesh_left_by_an_earlier_run_does_not_count(self):
        self.project.housing_stl.parent.mkdir(parents=True, exist_ok=True)
        self.project.housing_stl.write_text("solid old\nendsolid old\n", encoding="utf-8")
        r = self.run_script(WRITES_NOTHING)
        self.assertEqual(r.status, FAIL)
        self.assertFalse(self.project.housing_stl.exists())

    def test_no_cadquery_is_a_skip_that_says_so_not_a_failure_of_the_model(self):
        r = self.run_script(NO_CADQUERY)
        self.assertEqual(r.status, SKIP)
        self.assertIn("CadQuery is not installed", r.detail)
        self.assertIn("no enclosure mesh", r.render())
        self.assertIn("pip install cadquery", r.render())

    def test_a_script_that_never_ends_is_stopped(self):
        r = self.run_script("import time\ntime.sleep(60)\n", timeout=2)
        self.assertEqual(r.status, FAIL)
        self.assertIn("did not finish within 2s", r.detail)

    def test_no_script_at_all(self):
        r = checks.generate_enclosure(self.project.housing_script, self.project.housing_stl)
        self.assertEqual(r.status, FAIL)


REAL_CADQUERY = '''import cadquery as cq
from cadquery import exporters

length, width, height = 90.0, 60.0, 35.0
wall = 2.0

outer = cq.Workplane("XY").box(length, width, height)
inner = cq.Workplane("XY").box(length - 2 * wall, width - 2 * wall, height - wall).translate((0, 0, wall / 2))
housing = outer.cut(inner)

exporters.export(housing, "housing.step")
exporters.export(housing, "housing.stl")
'''


@unittest.skipUnless(__import__("importlib.util").util.find_spec("cadquery") and __import__("importlib.util").util.find_spec("OCP"),
                     "needs CadQuery")
class TestRealCadQuery(TestGenerateEnclosure):
    """D131 against the real library. First run on the AH531 (CadQuery
    2.8.0, no AVX): 48 s, a watertight mesh, and a measured wall of exactly
    the 2.00 mm the script asked for. Slow."""

    def test_a_real_script_makes_a_mesh_the_checks_then_measure(self):
        r = self.run_script(REAL_CADQUERY)
        self.assertEqual(r.status, PASS, r.render())
        self.assertTrue(self.project.housing_stl.with_suffix(".step").exists())
        solid = checks.solid(self.project.housing_stl)
        self.assertEqual(solid.status, PASS, solid.render())
        wall = checks.thickness(self.project.housing_stl, 1.2)
        self.assertEqual(wall.status, PASS, wall.render())
        self.assertIn("2.00 mm", wall.render())

    def test_a_real_script_with_a_cadquery_mistake_fails_with_cadquerys_words(self):
        r = self.run_script(REAL_CADQUERY.replace('.box(length, width, height)',
                                                  '.boxx(length, width, height)'))
        self.assertEqual(r.status, FAIL)
        self.assertIn("boxx", r.render())


class TestEnclosureStage(WeatherCase):
    def stage(self, source, **patches):
        ok = Result("solid", PASS, "watertight")
        with mock.patch.object(checks, "solid", return_value=patches.get("solid", ok)) as solid, \
             mock.patch.object(checks, "thickness", return_value=Result("thickness", PASS, "ok")):
            sr = self.pipe(StubRouter(f"```python\n{source}```")).stage_enclosure()
        return sr, solid

    def test_the_script_is_run_and_its_mesh_is_what_gets_checked(self):
        sr, solid = self.stage(WRITES_MESH)
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual([r.name for r in sr.results][0], "enclosure_script")
        self.assertTrue(solid.called)
        self.assertTrue(self.project.housing_stl.exists())
        self.assertTrue(self.project.status()["enclosure"])

    def test_a_script_that_fails_fails_the_step_and_the_mesh_checks_do_not_run(self):
        sr, solid = self.stage(RAISES)
        self.assertFalse(sr.ok)
        self.assertFalse(solid.called)                   # no "no mesh" skips beside the real reason
        self.assertEqual(sr.go_back_to, "enclosure")
        self.assertIn("fillet radius too large", sr.render())

    def test_the_real_case_nothing_exported_is_no_longer_a_pass(self):
        sr, _ = self.stage(WRITES_NOTHING)
        self.assertFalse(sr.ok)
        self.assertEqual([r.status for r in sr.results if r.name == "enclosure_script"], [FAIL])

    def test_a_mesh_that_fails_its_checks_is_this_steps_to_redo(self):
        sr, _ = self.stage(WRITES_MESH, solid=Result("solid", FAIL, "not watertight"))
        self.assertFalse(sr.ok)
        self.assertEqual(sr.go_back_to, "enclosure")

    def test_it_has_a_plain_name_for_the_interface(self):
        from nemo.gui import controller as C
        names = [v for v in vars(C).values() if isinstance(v, dict) and "harness_pins" in v][0]
        self.assertEqual(names["enclosure_script"], "Enclosure script runs")


class TestFirmwareIsGivenTheWiring(WeatherCase):
    def asked(self):
        router = StubRouter("```cpp\nvoid setup(){}\nvoid loop(){}\n```")
        seen = []
        real = router.ask

        def spy(task, system, user, **kw):
            seen.append((system, user))
            return real(task, system, user, **kw)
        router.ask = spy
        with mock.patch.object(checks, "compile_firmware",
                               return_value=Result("compile", PASS, "builds clean")):
            self.pipe(router).stage_firmware()
        return seen[0]

    def test_with_a_harness_the_prompt_lists_every_wire(self):
        self.harness(GOOD_HARNESS)
        system, user = self.asked()
        self.assertIn("Wiring harness (authoritative for pins", user)
        self.assertIn("- ESP32.GPIO22 is wired to BME280.SCL", user)
        self.assertIn("- ESP32.GPIO21 is wired to SSD1306.SDA", user)
        self.assertEqual(user.count(" is wired to "), 8)

    def test_without_one_nothing_is_invented(self):
        _, user = self.asked()
        self.assertNotIn("Wiring harness", user)

    def test_the_prompt_says_which_headers_exist_and_how_to_use_other_pins(self):
        system, _ = self.asked()
        self.assertIn("Arduino.h, Wire.h and", system)
        self.assertIn("Do not include a header named after a part", system)
        self.assertIn("Wire.begin(SDA, SCL)", system)
        self.assertNotIn("PlatformIO registry", system)  # nothing is fetched from it


class TestMissingHeaderAdvice(WeatherCase):
    REAL = ["src/main.cpp:2:10: fatal error: SSD1306_OLED.h: No such file or directory"]

    def test_the_real_error_gets_told_what_is_there(self):
        advice = Pipeline._missing_header_advice(self.REAL)
        self.assertIn("SSD1306_OLED.h is not installed", advice)
        self.assertIn("Arduino.h, Wire.h and SPI.h", advice)
        self.assertIn("Remove every such #include", advice)

    def test_several_headers_are_all_named(self):
        advice = Pipeline._missing_header_advice(
            self.REAL + ["src/main.cpp:3:10: fatal error: BME280.h: No such file or directory"])
        self.assertIn("BME280.h, SSD1306_OLED.h are not installed", advice)

    def test_any_other_error_gets_no_such_advice(self):
        self.assertEqual(Pipeline._missing_header_advice(
            ["src/main.cpp:12:5: error: 'foo' was not declared in this scope"]), "")

    def test_it_reaches_the_model_on_the_next_round(self):
        router = StubRouter("```cpp\n#include <SSD1306_OLED.h>\n```")
        users = []
        real = router.ask
        router.ask = lambda task, system, user, **kw: (users.append(user), real(task, system, user, **kw))[1]
        with mock.patch.object(checks, "compile_firmware",
                               return_value=Result("compile", FAIL, "build failed (rc=1)", self.REAL)):
            self.pipe(router).stage_firmware()
        self.assertEqual(len(users), 3)
        self.assertNotIn("not installed", users[0])
        self.assertIn("SSD1306_OLED.h is not installed", users[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
