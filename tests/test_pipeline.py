"""Pipeline integration tests with a stubbed model.

No network, no llama.cpp, no KiCad. The point is to prove the stage
plumbing, the gates and the rollback behaviour work -- the parts that are
Nemo's own logic rather than someone else's tool.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import


from nemo import checks
from nemo.config import Config
from nemo.parts import PartsLibrary
from nemo.pipeline import Pipeline
from nemo.project import Brief, Project
from nemo.router import Reply

GOOD_BRIEF = """```yaml
name: treasure-chest-player
function: >
  An RFID card player in a treasure-chest enclosure with a fixed open lid.
  Placing a card on the chest plays the audio track bound to that card.
user: Used at home, single user, cards handled loosely.
power: USB 5 V 1 A
supply_ma: 1000
rails: [5.0, 3.3]
envelope_mm: [140, 100, 70]
parts: [esp32_devkit_v1, rc522, dfplayer_mini, speaker_8ohm_20mm]
mcu: esp32
done_when: >
  Three different cards each play their own track within one second, ten
  times in a row, with the lid fixed open.
constraints:
  - Lid is fixed open; no moving parts.
  - Speaker magnet must sit at least 25 mm from the RFID antenna.
open_questions:
  - How many cards should be supported before storage becomes a problem?
```"""

THIN_BRIEF = """```yaml
name: half-baked
function: Something that beeps.
parts: [rc522]
```"""


class StubRouter:
    """Returns canned replies. Records what was asked of it."""

    def __init__(self, reply_text: str = "```yaml\n{}\n```",
                 degraded: bool = False):
        self.reply_text = reply_text
        self.degraded = degraded
        self.calls: list[str] = []

    def ask(self, task, system, user, **kw) -> Reply:
        self.calls.append(task)
        return Reply(self.reply_text, "local", "stub", self.degraded)

    def local_up(self) -> bool:
        return True


class PipelineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = Config.load(Path("/nonexistent"))
        self.lib = PartsLibrary.load()
        self.project = Project(self.tmp / "proj")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pipe(self, router):
        return Pipeline(self.project, self.cfg, router, self.lib)


class TestBriefStage(PipelineCase):
    def test_complete_brief_passes_gate(self):
        self.project.create(Brief(name="x"))
        r = self.pipe(StubRouter(GOOD_BRIEF)).stage_brief("rfid player")
        self.assertTrue(r.ok, r.render())
        brief = self.project.load_brief()
        self.assertEqual(brief.supply_ma, 1000)
        self.assertIn("rc522", brief.parts)

    def test_incomplete_brief_fails_and_names_gaps(self):
        self.project.create(Brief(name="x"))
        r = self.pipe(StubRouter(THIN_BRIEF)).stage_brief("beeper")
        self.assertFalse(r.ok)
        joined = " ".join(r.notes)
        self.assertIn("power", joined)
        self.assertIn("envelope_mm", joined)

    def test_bad_yaml_fails_cleanly(self):
        self.project.create(Brief(name="x"))
        r = self.pipe(StubRouter("```yaml\n:::not yaml:::\n```")).stage_brief("x")
        self.assertFalse(r.ok)

    def test_degraded_flag_propagates(self):
        self.project.create(Brief(name="x"))
        r = self.pipe(StubRouter(GOOD_BRIEF, degraded=True)).stage_brief("x")
        self.assertTrue(r.degraded)
        self.assertIn("local model", r.render())


class TestPartsStage(PipelineCase):
    def _seed(self, **over):
        data = dict(
            name="t", function="f", power="USB 5 V 1 A", supply_ma=1000,
            rails=[5.0, 3.3], envelope_mm=[140, 100, 70],
            parts=["esp32_devkit_v1", "rc522", "dfplayer_mini",
                   "speaker_8ohm_20mm"],
            mcu="esp32", done_when="plays")
        data.update(over)
        self.project.create(Brief(**data))

    def test_writes_bom_and_budget(self):
        self._seed()
        r = self.pipe(StubRouter()).stage_parts()
        self.assertTrue(r.ok, r.render())
        self.assertTrue(self.project.bom_path.exists())
        self.assertIn("Peak total", self.project.power_path.read_text())

    def test_undersized_supply_fails_gate(self):
        self._seed(supply_ma=300)
        r = self.pipe(StubRouter()).stage_parts()
        self.assertFalse(r.ok)
        self.assertEqual(r.go_back_to, "brief")

    def test_unknown_part_raises_rather_than_guessing(self):
        self._seed(parts=["rc522", "some_module_i_made_up"])
        with self.assertRaises(KeyError) as ctx:
            self.pipe(StubRouter()).stage_parts()
        self.assertIn("datasheet", str(ctx.exception))

    def test_tiny_envelope_fails(self):
        self._seed(envelope_mm=[20, 20, 10])
        r = self.pipe(StubRouter()).stage_parts()
        self.assertFalse(r.ok)


class TestPackStage(PipelineCase):
    """stage_pack lists every open safety sign-off in the build guide it
    writes. D103: it built that list straight from the original safety
    findings and never once checked signoffs.json -- the file the GUI's
    Sign-off tab actually writes to -- so nothing the user did there could
    ever be reflected here. Signing off, in effect, did nothing."""

    def _seed_with_lipo(self):
        self.project.create(Brief(
            name="t", function="f", power="LiPo 500 mAh", supply_ma=1000,
            rails=[3.7], envelope_mm=[80, 50, 25],
            parts=["eemb_lipo_500", "tp4056_protected"],
            mcu="esp32", done_when="runs"))

    def _run_parts_then_pack(self):
        self._seed_with_lipo()
        pipe = self.pipe(StubRouter())
        parts_result = pipe.stage_parts()
        self.assertTrue(parts_result.ok, parts_result.render())
        pack_result = pipe.stage_pack([parts_result])
        return pack_result

    def test_an_unsigned_item_is_listed_as_open(self):
        r = self._run_parts_then_pack()
        self.assertTrue(r.ok)          # pack itself never blocks; see D103's note
        guide = self.project.build_md.read_text()
        self.assertIn("lipo_forbids_sealed_enclosure", guide)

    def test_signing_off_actually_removes_it_from_the_open_list(self):
        from nemo.gui import controller as C
        self._seed_with_lipo()
        pipe = self.pipe(StubRouter())
        parts_result = pipe.stage_parts()
        # Sign off the way the GUI's Sign-off tab does.
        C.set_signoff(self.project, "safety_lipo_forbids_sealed_enclosure",
                      "Highjive", True)
        pipe.stage_pack([parts_result])
        guide = self.project.build_md.read_text()
        self.assertNotIn("lipo_forbids_sealed_enclosure", guide)
        self.assertIn("None recorded", guide)

    def test_withdrawing_a_signoff_makes_it_reappear(self):
        from nemo.gui import controller as C
        self._seed_with_lipo()
        pipe = self.pipe(StubRouter())
        parts_result = pipe.stage_parts()
        key = "safety_lipo_forbids_sealed_enclosure"
        C.set_signoff(self.project, key, "Highjive", True)
        C.set_signoff(self.project, key, "Highjive", False)
        pipe.stage_pack([parts_result])
        self.assertIn("lipo_forbids_sealed_enclosure", self.project.build_md.read_text())

    def test_given_signoffs_reads_what_the_gui_actually_wrote(self):
        # The shared read path (Project.given_signoffs) must agree with the
        # GUI's own read (controller.signoffs), since pipeline.py cannot
        # import the GUI layer -- that split is exactly what let this drift.
        from nemo.gui import controller as C
        self._seed_with_lipo()
        C.set_signoff(self.project, "safety_x", "A", True)
        self.assertEqual(self.project.given_signoffs(), C.signoffs(self.project))

    def test_a_missing_signoffs_file_is_not_an_error(self):
        self._seed_with_lipo()
        self.assertEqual(self.project.given_signoffs(), {})

    def test_a_corrupt_signoffs_file_is_not_an_error(self):
        self._seed_with_lipo()
        (self.project.root / "signoffs.json").write_text("{not valid json")
        self.assertEqual(self.project.given_signoffs(), {})

    def test_a_damaged_safety_record_fails_closed(self):
        # 2026-11-08 (after Claude Code Game Studios' "a missing config falls
        # back to defaults silently"): a damaged .nemo/safety.json was read as
        # no findings, so a pack made on its own listed no safety sign-off.
        from nemo.gui import controller as C
        from nemo.results import load_safety
        self._seed_with_lipo()
        parts_result = self.pipe(StubRouter()).stage_parts()
        record = self.project.root / ".nemo" / "safety.json"
        self.assertTrue(record.exists())
        for damage in ('[{"severity": "signoff", "rule": "lipo_forb', '{"a": 1}', '[1, 2]'):
            record.write_text(damage, encoding="utf-8")
            self.assertEqual([f["rule"] for f in load_safety(self.project.root)],
                             ["record_unreadable"], damage)
        # Ticking it in the Sign-off tab does not clear it: only a new check does.
        C.set_signoff(self.project, "safety_record_unreadable", "Highjive", True)
        self.pipe(StubRouter()).stage_pack([parts_result])
        self.assertIn("record_unreadable", self.project.build_md.read_text(encoding="utf-8"))

    def test_the_safety_record_is_written_whole(self):
        from nemo.results import load_safety
        self._seed_with_lipo()
        self.pipe(StubRouter()).stage_parts()
        nemo_dir = self.project.root / ".nemo"
        self.assertFalse((nemo_dir / "safety.json.tmp").exists())
        self.assertIn("lipo_forbids_sealed_enclosure",
                      [f["rule"] for f in load_safety(self.project.root)])


class TestElectricalStage(PipelineCase):
    """D104: the schematic script that stage_electrical writes was never
    executed by anything. erc() then always found no schematic and SKIPped
    -- which this codebase's Result.ok treats as passing -- so every
    electrical stage, for every project ever run, reported a checked
    design that had never actually been checked. There was no test at
    this level at all; the gap could not have been caught by running the
    existing suite, only by tracing what actually happens stage by stage.
    """

    def _seed(self):
        self.project.create(Brief(
            name="t", function="f", power="USB 5 V 1 A", supply_ma=1000,
            rails=[5.0, 3.3], envelope_mm=[140, 100, 70],
            parts=["esp32_devkit_v1", "rc522"],
            mcu="esp32", done_when="reads a card"))

    SCRIPT_NAMED_OUTPUT = """```python
open("schematic.kicad_sch", "w").write("(kicad_sch fake but plausible)")
```"""
    RIGHT_NAME_OUTPUT = """```python
open("project.kicad_sch", "w").write("(kicad_sch)")
```"""
    NEVER_CALLS_GENERATE = """```python
print("a script that runs fine and forgets to call generate_schematic()")
```"""
    RAISES = """```python
raise RuntimeError("no module named skidl")
```"""

    def test_the_schematic_file_actually_gets_created(self):
        # This is the direct regression test for D104: before the fix,
        # this file never existed no matter what the script contained.
        self._seed()
        self.pipe(StubRouter(self.SCRIPT_NAMED_OUTPUT)).stage_electrical()
        self.assertTrue(self.project.schematic.exists())
        self.assertIn("(kicad_sch fake but plausible)",
                      self.project.schematic.read_text())

    def test_a_script_that_names_its_own_output_is_still_relocated(self):
        # SKiDL's own default naming follows the invoking script's name,
        # not a fixed target -- this is the exact case that motivated
        # looking at what actually appeared rather than assuming a name.
        self._seed()
        self.pipe(StubRouter(self.SCRIPT_NAMED_OUTPUT)).stage_electrical()
        self.assertTrue(self.project.schematic.exists())
        self.assertFalse((self.project.root / "electrical" / "schematic.kicad_sch").exists(),
                         "the script-named file should have been moved, not left behind")

    def test_a_script_already_using_the_right_name_is_left_alone(self):
        self._seed()
        self.pipe(StubRouter(self.RIGHT_NAME_OUTPUT)).stage_electrical()
        self.assertTrue(self.project.schematic.exists())

    def test_a_script_that_never_generates_anything_fails_the_stage(self):
        # Before the fix this could never happen: a missing schematic was
        # SKIP, and SKIP passes. Now it is a real, visible failure.
        self._seed()
        r = self.pipe(StubRouter(self.NEVER_CALLS_GENERATE)).stage_electrical()
        self.assertFalse(r.ok, r.render())
        self.assertIn("schematic", [x.name for x in r.results])
        # Was "parts". A script that produces nothing is this step's own
        # output, not a fault in the parts list: on the real laptop a syntax
        # error in the model's script sent the owner back to 'parts'.
        self.assertEqual(r.go_back_to, "electrical")

    def test_parts_that_cannot_talk_to_each_other_still_send_you_to_parts(self):
        from nemo.checks.deterministic import FAIL as F, Result as R
        self._seed()
        with mock.patch.object(checks, "voltage_compatibility",
                               return_value=R("voltage_compat", F, "5 V into 3.3 V")):
            r = self.pipe(StubRouter(self.RIGHT_NAME_OUTPUT)).stage_electrical()
        if all(x.ok for x in r.results if x.name in ("schematic", "erc")):
            self.assertEqual(r.go_back_to, "parts")
        else:                       # ERC also failed here: the step's own output comes first
            self.assertEqual(r.go_back_to, "electrical")

    def test_a_script_that_raises_fails_clearly_not_with_a_traceback(self):
        self._seed()
        r = self.pipe(StubRouter(self.RAISES)).stage_electrical()
        self.assertFalse(r.ok)
        schematic_result = next(x for x in r.results if x.name == "schematic")
        self.assertEqual(schematic_result.status, "FAIL")
        self.assertIn("error", schematic_result.detail)

    def test_erc_is_not_run_at_all_when_generation_already_failed(self):
        # Avoids a redundant, confusing "no schematic" SKIP sitting next
        # to the real failure that already explains why.
        self._seed()
        r = self.pipe(StubRouter(self.NEVER_CALLS_GENERATE)).stage_electrical()
        self.assertNotIn("erc", [x.name for x in r.results])

    def test_erc_does_run_once_a_schematic_actually_exists(self):
        self._seed()
        r = self.pipe(StubRouter(self.SCRIPT_NAMED_OUTPUT)).stage_electrical()
        self.assertIn("erc", [x.name for x in r.results])

    def test_voltage_compatibility_still_runs_regardless(self):
        # It depends only on the parts library, never on the schematic file.
        self._seed()
        for reply in (self.SCRIPT_NAMED_OUTPUT, self.NEVER_CALLS_GENERATE):
            r = self.pipe(StubRouter(reply)).stage_electrical()
            self.assertIn("voltage_compat", [x.name for x in r.results])


class TestProjectState(PipelineCase):
    def test_next_stage_advances(self):
        self.project.create(Brief(name="t", function="f"))
        self.assertEqual(self.project.next_stage(), "parts")
        self.project.bom_path.write_text("ref\n")
        self.assertEqual(self.project.next_stage(), "electrical")

    def test_git_commit_per_stage(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with _sandbox.git_on():
            self.project.create(Brief(name="t", function="f"))
            self.project.bom_path.write_text("ref\n")
            self.assertTrue(self.project.commit("parts", "test"))

    def test_rollback_goes_to_the_latest_commit_of_the_stage(self):
        # rollback() had no test: it is a reset --hard, and its docstring
        # says why the latest commit, not the first, is the one to return to.
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with _sandbox.git_on():
            self.project.create(Brief(name="t", function="f"))
            bom = self.project.bom_path
            bom.write_text("first\n"); self.project.commit("parts", "one")
            bom.write_text("second\n"); self.project.commit("parts", "two")
            bom.write_text("third\n"); self.project.commit("electrical", "later")
            self.assertTrue(self.project.rollback("parts"))
            self.assertEqual(bom.read_text(), "second\n")

    def test_with_git_off_nothing_is_committed_and_nothing_fails(self):
        self.project.create(Brief(name="t", function="f"))
        self.assertFalse((self.project.root / ".git").exists())
        self.assertFalse(self.project.commit("parts", "test"))
        self.assertFalse(self.project.rollback("parts"))

    def test_gitignore_excludes_keys(self):
        self.project.create(Brief(name="t"))
        self.assertIn(".env", (self.project.root / ".gitignore").read_text())


class TestExtraction(unittest.TestCase):
    def test_fenced_block(self):
        out = Pipeline._extract("chatter\n```python\nx = 1\n```\nmore",
                                "python")
        self.assertEqual(out, "x = 1")

    def test_unfenced_passthrough(self):
        self.assertEqual(Pipeline._extract("plain text"), "plain text")

    def test_cutout_names_parsed(self):
        import tempfile as tf
        p = Path(tf.mkdtemp()) / "housing.py"
        p.write_text("res = box.cut(cutout_speaker)\n"
                     "res = res.cut(cutout_rc522)\n")
        self.assertEqual(Pipeline._cutouts(p), {"speaker", "rc522"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
