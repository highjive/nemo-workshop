"""Three gates that let the first real pipeline run on the AH531 through.

2026-10-05, a small real brief (an ESP32, a BME280, a small OLED), the
Talk model, real WireViz and real PlatformIO:

  D126  every firmware build ended with the compiler failing to start
        (`CreateProcess: No such file or directory`). That was fed back to
        the model as an error in its code, three times, forty minutes.
  D127  the wiring step passed a harness for a different project that
        joined nothing: WireViz drew an empty picture, the pin check
        verified zero pins, both counted as passes.
  D128  `nemo status` then showed wiring and firmware as done, because a
        step was "done" if its file existed.

The fixtures below are what that run actually produced.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks
from nemo.checks import runners
from nemo.checks.deterministic import FAIL, PASS, Result
from nemo.pipeline import Pipeline, StageResult
from nemo.project import Brief
from nemo.results import save_result
from test_pipeline import PipelineCase, StubRouter

# firmware/build.log from the run, the two lines that matter.
REAL_TOOL_FAILURE = [
    "xtensa-esp32-elf-g++: error: CreateProcess: No such file or directory",
    "xtensa-esp32-elf-g++: error: CreateProcess: No such file or directory",
]
# The same source through a shorter path: a real mistake in the code.
REAL_CODE_ERROR = ["src/main.cpp:4:10: fatal error: SSD1306_OLED.h: No such file or directory"]

# wiring/harness.yaml from the run, shortened only in the pin lists.
REAL_BAD_HARNESS = """\
structure:
  connectors:
    RC522:
      type: header
      pincount: 20
      pinlabels: [VCC, "NO", "NC", COM]
    DFPLAYER:
      type: header
      pincount: 20
      pinlabels: [VCC, "NO", "NC", COM]
    ESP32:
      type: header
      pincount: 20
      pinlabels: [VCC, "NO", "NC", COM]
  cables:
    ESP32_to_BME280:
      wirecount: 1
      gauge: 22 AWG
      length: 100mm
      colors: [blue]
  connections:
    ESP32:12 -> BME280:12
    BME280:11 -> SSD1306:11
"""

GOOD_HARNESS = """\
connectors:
  ESP32:
    pinlabels: [3V3, GND, GPIO21, GPIO22]
  BME280:
    pinlabels: [VCC, GND, SCL, SDA]
  SSD1306:
    pinlabels: [VCC, GND, SCL, SDA]
cables:
  W1:
    wirecount: 4
    gauge: 26 AWG
  W2:
    wirecount: 4
    gauge: 26 AWG
connections:
  - - ESP32: [3V3, GND, GPIO22, GPIO21]
    - W1: [1-4]
    - BME280: [VCC, GND, SCL, SDA]
  - - ESP32: [3V3, GND, GPIO22, GPIO21]
    - W2: [1-4]
    - SSD1306: [VCC, GND, SCL, SDA]
"""


class WeatherCase(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="desk-weather", function="Shows temperature and humidity.",
            power="USB 5 V 1 A", supply_ma=1000, rails=[5.0, 3.3], envelope_mm=[90, 60, 35],
            parts=["esp32_devkit_v1", "bme280", "ssd1306_oled_096"], mcu="esp32",
            done_when="updates every ten seconds"))
        self.parts = [self.lib.get(r) for r in ("esp32_devkit_v1", "bme280", "ssd1306_oled_096")]

    def harness(self, text: str) -> Path:
        self.project.harness.parent.mkdir(parents=True, exist_ok=True)
        self.project.harness.write_text(text, encoding="utf-8")
        return self.project.harness


# ---------------------------------------------------------------- D126
class TestBuildToolFailure(unittest.TestCase):
    def test_the_real_failure_is_recognised(self):
        self.assertTrue(runners.build_tools_failed(REAL_TOOL_FAILURE))

    def test_a_real_code_error_is_not(self):
        self.assertFalse(runners.build_tools_failed(REAL_CODE_ERROR))
        self.assertFalse(runners.build_tools_failed(
            ["src\\main.cpp:12:5: error: 'foo' was not declared in this scope"]))

    def test_if_any_line_names_the_code_it_is_treated_as_the_code(self):
        self.assertFalse(runners.build_tools_failed(REAL_TOOL_FAILURE + REAL_CODE_ERROR))

    def test_link_errors_and_nothing_at_all_are_not_tool_failures(self):
        self.assertFalse(runners.build_tools_failed(
            ["main.cpp.o: undefined reference to `setup()'",
             "collect2.exe: error: ld returned 1 exit status"]))
        self.assertFalse(runners.build_tools_failed([]))
        self.assertFalse(runners.build_tools_failed(["Error: Unknown board ID 'nope'"]))


class TestCompileReportsIt(WeatherCase):
    def compile(self, lines):
        fw = self.project.firmware
        (fw / "src").mkdir(parents=True, exist_ok=True)
        (fw / "platformio.ini").write_text("[env:esp32dev]\n", encoding="utf-8")
        with mock.patch("nemo.platform_probe.find_tool", return_value="pio"), \
             mock.patch.object(runners, "_run", return_value=(1, "\n".join(lines), "")):
            return checks.compile_firmware(fw)

    def test_a_tool_failure_says_what_it_is_and_what_usually_causes_it(self):
        r = self.compile(REAL_TOOL_FAILURE)
        self.assertEqual((r.status, r.detail), (FAIL, runners.TOOLS_FAILED))
        text = r.render()
        self.assertIn("not a fault in the code", text)
        self.assertIn("short paths", text)
        self.assertIn("CreateProcess", text)

    def test_a_code_error_is_reported_as_before(self):
        r = self.compile(REAL_CODE_ERROR)
        self.assertEqual(r.status, FAIL)
        self.assertNotEqual(r.detail, runners.TOOLS_FAILED)
        self.assertIn("SSD1306_OLED.h", r.render())


class TestFirmwareLoop(WeatherCase):
    def run_stage(self, result):
        router = StubRouter("```cpp\nvoid setup(){}\nvoid loop(){}\n```")
        with mock.patch.object(checks, "compile_firmware", return_value=result):
            return self.pipe(router).stage_firmware(), router

    def test_a_tool_failure_is_not_sent_back_to_the_model(self):
        sr, router = self.run_stage(Result("compile", FAIL, runners.TOOLS_FAILED, REAL_TOOL_FAILURE))
        self.assertEqual(len(router.calls), 1)           # it was three
        self.assertFalse(sr.ok)
        self.assertIsNone(sr.go_back_to)                 # not the schematic's fault
        self.assertIn("stopped without asking the model again", " ".join(sr.notes))

    def test_a_code_error_still_gets_its_three_rounds(self):
        sr, router = self.run_stage(Result("compile", FAIL, "build failed (rc=1)", REAL_CODE_ERROR))
        self.assertEqual(len(router.calls), 3)
        self.assertEqual(sr.go_back_to, "electrical")


# ---------------------------------------------------------------- D127
class TestHarnessCoversTheProject(WeatherCase):
    def test_the_real_harness_that_passed_now_fails_and_says_why(self):
        r = Pipeline.check_harness_covers(self.harness(REAL_BAD_HARNESS), self.parts)
        self.assertEqual(r.status, FAIL)
        self.assertIn("joins nothing", r.detail)
        self.assertIn("structure", r.render())           # what it found instead

    def test_it_is_what_the_old_checks_let_through(self):
        # The check this defect is about: zero pins verified, and a pass.
        old = Pipeline.check_harness_pins(self.harness(REAL_BAD_HARNESS), self.parts)
        self.assertEqual((old.status, old.detail), (PASS, "0 pin(s) verified"))

    def test_a_harness_that_wires_every_part_passes(self):
        r = Pipeline.check_harness_covers(self.harness(GOOD_HARNESS), self.parts)
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn("all 3 part(s)", r.detail)

    def test_a_part_left_out_is_named(self):
        without = GOOD_HARNESS.split("  - - ESP32: [3V3, GND, GPIO22, GPIO21]\n    - W2")[0]
        r = Pipeline.check_harness_covers(self.harness(without), self.parts)
        self.assertEqual(r.status, FAIL)
        self.assertIn("ssd1306_oled_096: no wire in the harness reaches it", r.render())
        self.assertNotIn("bme280: no wire", r.render())

    def test_a_connector_that_is_not_a_part_is_noted_not_failed(self):
        extra = GOOD_HARNESS.replace("connectors:\n", "connectors:\n  USB:\n    pinlabels: [5V, GND]\n") \
            + "  - - USB: [5V, GND]\n    - W1: [1-2]\n    - ESP32: [3V3, GND]\n"
        r = Pipeline.check_harness_covers(self.harness(extra), self.parts)
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn("USB: a connector that is not one of this project's parts", r.render())

    def test_no_harness_yet_is_a_skip(self):
        self.assertEqual(Pipeline.check_harness_covers(self.project.harness, self.parts).status,
                         checks.SKIP)

    def test_the_wiring_step_fails_on_the_real_reply(self):
        fake_viz = Result("wireviz", PASS, "rendered")
        with mock.patch.object(checks, "wireviz", return_value=fake_viz):
            sr = self.pipe(StubRouter(f"```yaml\n{REAL_BAD_HARNESS}```")).stage_wiring()
        self.assertFalse(sr.ok)
        self.assertIn("harness_covers", [r.name for r in sr.results if r.status == FAIL])


# ---------------------------------------------------------------- D128
class TestStatusBelievesTheResultNotTheFile(WeatherCase):
    def test_a_failed_step_whose_file_exists_is_not_done(self):
        self.harness(REAL_BAD_HARNESS)
        self.assertTrue(self.project.status()["wiring"])         # no result yet: the file decides
        save_result(self.project.root, StageResult("wiring", False))
        self.assertFalse(self.project.status()["wiring"])

    def test_resuming_starts_at_the_failed_step(self):
        self.project.bom_path.write_text("ref\n", encoding="utf-8")
        self.project.schematic.parent.mkdir(parents=True, exist_ok=True)
        self.project.schematic.write_text("(kicad_sch)", encoding="utf-8")
        self.harness(GOOD_HARNESS)
        save_result(self.project.root, StageResult("electrical", False))
        self.assertEqual(self.project.next_stage(), "electrical")
        save_result(self.project.root, StageResult("electrical", True))
        # The Artist's concept step comes between wiring and enclosure (2026-10-20).
        self.assertEqual(self.project.next_stage(), "concept")

    def test_a_passing_result_without_its_file_is_still_not_done(self):
        save_result(self.project.root, StageResult("wiring", True))
        self.assertFalse(self.project.status()["wiring"])

    def test_a_corrupt_results_file_falls_back_to_the_files(self):
        self.harness(GOOD_HARNESS)
        (self.project.root / ".nemo").mkdir(exist_ok=True)
        (self.project.root / ".nemo" / "results.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(self.project.status()["wiring"])


class TestWiringPromptCannotBeMistakenForTheAnswer(unittest.TestCase):
    """The old prompt named RC522, DFPLAYER and ESP32 as examples and showed
    pinlabels [VCC, "NO", "NC", COM]. The real reply contained exactly those
    connectors and exactly those labels, for a project with none of them."""

    def test_it_names_no_real_part_and_no_real_pin_list(self):
        from nemo.prompts import load_prompt
        text = load_prompt("wiring")
        for leaked in ("RC522", "DFPLAYER", "ESP32", 'pinlabels: [VCC', "COM]"):
            self.assertNotIn(leaked, text)

    def test_it_states_the_shape_the_checks_read(self):
        from nemo.prompts import load_prompt
        text = load_prompt("wiring")
        for key in ("\nconnectors:\n", "\ncables:\n", "\nconnections:\n"):
            self.assertIn(key, text)
        self.assertIn("exactly three keys", text)
        self.assertIn("Every part must be on at least one connection", text)
        self.assertIn("22 AWG", text)


class TestARealBuildIsRemembered(WeatherCase):
    def test_a_firmware_step_that_builds_marks_the_board_ready(self):
        import os, tempfile
        from nemo import offline
        with tempfile.TemporaryDirectory() as t, \
             mock.patch.dict(os.environ, _sandbox.home_env(t)):
            (Path(t) / ".platformio" / "platforms" / "espressif32").mkdir(parents=True)
            self.assertFalse(offline.board_ready("esp32dev")[0])
            ok = Result("compile", PASS, "builds clean")
            with mock.patch.object(checks, "compile_firmware", return_value=ok):
                self.pipe(StubRouter("```cpp\nvoid setup(){}\nvoid loop(){}\n```")).stage_firmware()
            ready, why = offline.board_ready("esp32dev")
        self.assertTrue(ready, why)

    def test_a_build_that_fails_does_not(self):
        import os, tempfile
        from nemo import offline
        with tempfile.TemporaryDirectory() as t, \
             mock.patch.dict(os.environ, _sandbox.home_env(t)):
            bad = Result("compile", FAIL, "build failed (rc=1)", REAL_CODE_ERROR)
            with mock.patch.object(checks, "compile_firmware", return_value=bad):
                self.pipe(StubRouter("```cpp\nx\n```")).stage_firmware()
            self.assertFalse(offline.board_ready("esp32dev")[0])


class TestBuildGuideCarriesWhatTheStepsSaid(WeatherCase):
    """The first run on the AH531 where every step passed produced a
    bring-up firmware and an enclosure laid out by code. Both caveats were
    printed on screen and neither was in BUILD.md."""

    FW = "Each part's own logic is NOT generated; its function is empty."
    ENC = "The model's layout was unsound twice, so Nemo laid the parts out itself."

    def guide(self):
        return self.project.build_md.read_text(encoding="utf-8")

    def test_notes_from_this_run_are_in_the_guide(self):
        prior = [StageResult("enclosure", True, notes=[self.ENC]),
                 StageResult("firmware", True, notes=[self.FW])]
        self.pipe(StubRouter()).stage_pack(prior)
        text = self.guide()
        self.assertIn("## What each step did, and did not do", text)
        self.assertIn(f"- [firmware] {self.FW}", text)
        self.assertIn(f"- [enclosure] {self.ENC}", text)
        self.assertLess(text.index("What each step did"), text.index("## Open questions"))

    def test_packing_on_its_own_later_reads_them_from_the_saved_results(self):
        save_result(self.project.root, StageResult("firmware", True, notes=[self.FW]))
        self.pipe(StubRouter()).stage_pack([])
        self.assertIn(f"- [firmware] {self.FW}", self.guide())

    def test_this_runs_notes_win_over_an_older_saved_result(self):
        save_result(self.project.root, StageResult("firmware", True, notes=["an older note"]))
        self.pipe(StubRouter()).stage_pack([StageResult("firmware", True, notes=[self.FW])])
        text = self.guide()
        self.assertIn(self.FW, text); self.assertNotIn("an older note", text)

    def test_nothing_to_report_says_so(self):
        self.pipe(StubRouter()).stage_pack([])
        self.assertIn("- Nothing recorded.", self.guide())


class TestNoSecondOpinionIsNotCalledUnreachable(unittest.TestCase):
    def test_the_wording(self):
        text = StageResult("electrical", True, degraded=True).render()
        self.assertIn("local model only", text)
        self.assertNotIn("unreachable", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
