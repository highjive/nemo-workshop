"""Power suggestions and fixes: they help, and they never loosen safety."""
from __future__ import annotations

import ast, os, sys, tempfile, unittest
from dataclasses import fields
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.checks import current_sum, fits_envelope, supply_rails
from nemo.fixes import (Fix, apply_fix, apply_power, power_plan,
                        suggest_fixes)
from nemo.parts import PartsLibrary
from nemo.project import Brief

LIB = PartsLibrary.load()
CHEST = ["esp32_devkit_v1", "rc522", "dfplayer_mini", "speaker_8ohm_20mm"]
PENDANT = ["waveshare_esp32s3_lcd_128", "sph0645lm4h", "max98357a",
           "eemb_lipo_500", "tp4056_protected"]
P = lambda refs: [LIB.get(r) for r in refs]


def rec(name, status, detail="", items=()):
    return {"ok": status != "FAIL",
            "checks": [{"name": name, "status": status, "detail": detail,
                        "items": list(items)}]}


class TestPowerPlan(unittest.TestCase):
    def test_recommendation_passes_the_real_check(self):
        plan = power_plan(P(CHEST), LIB, "USB")
        best = next(o for o in plan.options if o.verdict == "recommended")
        b = apply_power(Brief(name="x", parts=list(CHEST)), best)
        self.assertEqual(current_sum(P(b.parts), b.supply_ma).status, "PASS")

    def test_smallest_adequate_is_recommended(self):
        plan = power_plan(P(CHEST), LIB, "USB")
        best = next(o for o in plan.options if o.verdict == "recommended")
        self.assertEqual(best.supply.ma, 1000)

    def test_margin_matches_the_check(self):
        plan = power_plan(P(CHEST), LIB, "USB")
        self.assertEqual(plan.need_ma, 747)        # 560 / 0.75, rounded up

    def test_battery_device_is_never_switched_to_mains(self):
        plan = power_plan(P(PENDANT), LIB, "500 mAh LiPo")
        rec_ = [o for o in plan.options if o.verdict == "recommended"]
        self.assertTrue(all(o.supply.battery for o in rec_))

    def test_battery_needs_a_protected_charger_in_the_library(self):
        lib = PartsLibrary({k: v for k, v in LIB.parts.items()
                            if k != "tp4056_protected"})
        plan = power_plan(P(CHEST), lib, "USB")
        self.assertFalse(any(o.supply.battery for o in plan.options))

    def test_battery_option_adds_cell_and_protection(self):
        plan = power_plan(P(["waveshare_esp32s3_lcd_128", "sph0645lm4h"]), LIB, "LiPo")
        bat = next(o for o in plan.options if o.supply.battery)
        self.assertIn("tp4056_protected", bat.add_parts)

    def test_5v_only_part_is_now_fed_via_the_boost_converter(self):
        # O21/D108: this used to assert "not suitable" here, which was the
        # defect, not the correct behaviour -- a 5 V-only part on a LiPo
        # cell is exactly what boost_5v_mt3608 in the library is for.
        from nemo.parts import Part
        five = Part(ref="five_volt_only", name="5 V only thing", category="audio",
                    supply_v=[5.0], current_ma=10, peak_ma=20)
        mcu = LIB.get("esp32_devkit_v1")
        bat = next(o for o in power_plan([mcu, five], LIB, "").options if o.supply.battery)
        self.assertEqual(bat.verdict, "enough")
        self.assertIn("boost_5v_mt3608", bat.add_parts)
        self.assertIn("boost_5v_mt3608", bat.why)

    def test_a_voltage_no_converter_in_the_library_makes_is_still_not_suitable(self):
        # The library's only converter outputs 5 V; a part needing a
        # voltage nothing converts to must still be correctly refused.
        from nemo.parts import Part
        nine = Part(ref="nine_volt_only", name="9 V only thing", category="audio",
                    supply_v=[9.0], current_ma=10, peak_ma=20)
        mcu = LIB.get("esp32_devkit_v1")
        bat = next(o for o in power_plan([mcu, nine], LIB, "").options if o.supply.battery)
        self.assertEqual(bat.verdict, "not suitable")
        self.assertIn("nine_volt_only", bat.why)

    def test_boost_converter_runtime_reflects_the_real_efficiency_loss(self):
        # Hand-checked: a 480 mA peak load at 5 V from a 3.7 V cell through
        # a 93%-efficient converter draws 480*5/(3.7*0.93) =~ 697.5 mA from
        # the cell, not 480 -- the runtime and margin must reflect that,
        # not the load's own rating.
        from nemo.parts import Part
        five = Part(ref="five_volt_load", name="5 V load", category="audio",
                    supply_v=[5.0], current_ma=480, peak_ma=480)
        mcu = LIB.get("esp32_devkit_v1")
        opt = next(o for o in power_plan([mcu, five], LIB, "").options
                  if o.supply.key == "lipo_2000")
        expected_typical = mcu.current_ma + 480 * 5.0 / (3.7 * 0.93)
        expected_runtime = round(2000 / expected_typical, 1)
        self.assertEqual(opt.runtime_h, expected_runtime)

    def test_dfplayer_accepts_battery_voltage_per_its_datasheet(self):
        # D67: the library said 5 V only; the FN-M16P datasheet says 3.3-5.0 V.
        # The smallest cell in the library now fails on current (the real
        # limit), not on voltage; a bigger cell in the library can supply it.
        opts = {o.supply.key: o for o in power_plan(P(CHEST), LIB, "").options
                if o.supply.battery}
        self.assertEqual(opts["eemb_lipo_500"].verdict, "too small")
        self.assertIn(3.7, LIB.get("dfplayer_mini").supply_v)

    def test_multiple_cells_each_get_their_own_option(self):
        # D69: a second and third LiPo cell in the library used to be
        # ignored -- only the first cell found was ever considered, and its
        # own safety note (mentioning the word "protect") could be mistaken
        # for the protection circuit it was describing the need for.
        opts = {o.supply.key: o for o in power_plan(P(CHEST), LIB, "").options
                if o.supply.battery}
        self.assertEqual(set(opts), {"eemb_lipo_500", "lipo_1000", "lipo_2000"})
        for key, ma in (("eemb_lipo_500", 500), ("lipo_1000", 1000), ("lipo_2000", 2000)):
            self.assertEqual(opts[key].supply.ma, ma)
        # Each pairs with the real charger, never with another cell.
        for o in opts.values():
            self.assertEqual(o.add_parts[1], "tp4056_protected")
        self.assertEqual(opts["lipo_2000"].verdict, "enough")

    def test_smallest_adequate_battery_is_recommended(self):
        plan = power_plan(P(CHEST), LIB, "500 mAh LiPo, USB charging")
        best = next(o for o in plan.options if o.verdict == "recommended")
        self.assertEqual(best.supply.key, "lipo_1000")


class TestFixesChangeTheDesignNotTheRules(unittest.TestCase):
    def test_fix_fields_are_all_brief_fields(self):
        brief_fields = {f.name for f in fields(Brief)}
        for f in self._every_fix():
            self.assertTrue(set(f.set_fields) <= brief_fields, f.title)

    def test_rule_blocks_are_advice_not_changes(self):
        for rule in ("max_design_voltage_v", "max_continuous_current_a",
                     "forbidden_domains"):
            safety = [{"severity": "block", "rule": rule, "detail": "d"}]
            fx = suggest_fixes(Brief(name="x"), LIB, "parts",
                               rec("safety", "FAIL"), safety)
            self.assertTrue(fx)
            self.assertTrue(all(f.kind == "info" for f in fx), rule)

    def test_advice_cannot_be_applied(self):
        with self.assertRaises(ValueError):
            apply_fix(Brief(name="x"), Fix("k", "t", "w", "info"))

    def test_fixes_module_does_not_touch_policy(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "fixes.py").read_text()
        for name in ("Policy", "policy.yaml", "floor.signed", "HARD_FLOOR", "save_brief"):
            self.assertNotIn(name, src)

    def _every_fix(self):
        br = Brief(name="x", parts=list(CHEST), supply_ma=100,
                   envelope_mm=[20, 20, 5], rails=[5.0])
        out = []
        for name in ("current_sum", "supply_rails", "fits_envelope", "thickness",
                     "solid", "wire_gauge", "harness_pins", "xref_cutouts",
                     "voltage_compat", "erc", "compile", "wireviz"):
            out += suggest_fixes(br, LIB, "parts", rec(name, "FAIL", "", [
                "x: 1 mA needs 22 AWG", "a.TX (5.0 V) -> b.TX (3.3 V): y",
                "r.M: rc522 has no pin 'M' (has VCC, GND)", "speaker: no cutout",
                "p wants [12.0] V; rails present: [5.0]"]))
        return out


class TestFixesActuallyFix(unittest.TestCase):
    def test_power_fix_passes(self):
        br = Brief(name="x", parts=list(CHEST), supply_ma=500, power="USB 5 V 0.5 A")
        f = suggest_fixes(br, LIB, "parts", rec("current_sum", "FAIL"))[0]
        b = apply_fix(br, f)
        self.assertEqual(current_sum(P(b.parts), b.supply_ma).status, "PASS")

    def test_envelope_fix_passes(self):
        br = Brief(name="x", parts=list(CHEST), envelope_mm=[60, 40, 10])
        fe = fits_envelope(P(CHEST), br.envelope_mm)
        f = suggest_fixes(br, LIB, "parts", rec("fits_envelope", "FAIL", fe.detail, fe.items))[0]
        b = apply_fix(br, f)
        self.assertEqual(fits_envelope(P(b.parts), b.envelope_mm).status, "PASS")

    def test_rails_fix_passes(self):
        parts = P(["rc522"]); br = Brief(name="x", parts=["rc522"], rails=[5.0])
        sr = supply_rails(parts, br.rails)
        f = suggest_fixes(br, LIB, "parts", rec("supply_rails", "FAIL", sr.detail, sr.items))[0]
        self.assertEqual(supply_rails(parts, apply_fix(br, f).rails).status, "PASS")

    def test_protection_fix_adds_the_charger(self):
        safety = [{"severity": "block", "rule": "lipo_requires_protection_circuit", "detail": ""}]
        f = suggest_fixes(Brief(name="x", parts=["eemb_lipo_500"]), LIB, "parts",
                          rec("safety", "FAIL"), safety)[0]
        self.assertIn("tp4056_protected", apply_fix(Brief(name="x", parts=["eemb_lipo_500"]), f).parts)

    def test_apply_does_not_mutate_the_original(self):
        br = Brief(name="x", parts=list(CHEST), supply_ma=500)
        f = suggest_fixes(br, LIB, "parts", rec("current_sum", "FAIL"))[0]
        apply_fix(br, f)
        self.assertEqual(br.supply_ma, 500)

    def test_constraint_fixes_parse_real_check_output(self):
        f = suggest_fixes(Brief(name="x"), LIB, "wiring", rec(
            "harness_pins", "FAIL", "", ["RC522.MOSQ: rc522 has no pin 'MOSQ' (has VCC, RST, GND)"]))[0]
        self.assertIn("rc522 pins are exactly: VCC, RST, GND", f.add_constraints)
        g = suggest_fixes(Brief(name="x"), LIB, "wiring", rec(
            "wire_gauge", "FAIL", "", ["W_AUDIO: 700 mA needs 22 AWG or thicker, harness says 30 AWG"]))[0]
        self.assertIn("Use 22 AWG or thicker for W_AUDIO", g.add_constraints)

    def test_changes_are_in_plain_words(self):
        br = Brief(name="x", parts=list(CHEST), supply_ma=500)
        f = suggest_fixes(br, LIB, "parts", rec("current_sum", "FAIL"))[0]
        self.assertTrue(any("supply rating: 1000 mA" in c for c in f.changes))


class TestPowerSourcesAreNotLoads(unittest.TestCase):
    """D65: the parts step counted a battery and its charger as 2 A of load."""
    def test_pendant_passes_current_and_rails(self):
        self.assertEqual(current_sum(P(PENDANT), 1500).status, "PASS")
        self.assertEqual(supply_rails(P(PENDANT), [5.0, 3.3]).status, "PASS")


class TestConstraintsReachEveryModelStep(unittest.TestCase):
    """D66: only the enclosure step showed the model the brief's constraints."""
    def test_every_model_step(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "pipeline.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                    "stage_electrical", "stage_wiring", "stage_enclosure", "stage_firmware"):
                self.assertIn("constraints", ast.get_source_segment(src, node), node.name)


class TestCommandLine(unittest.TestCase):
    def test_fix_lists_and_applies(self):
        import io, json
        from contextlib import redirect_stdout
        from nemo import cli
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"HOME": d, "USERPROFILE": d, "NEMO_HOME": d + "/.nemo"}):
            from nemo.gui import controller as C
            p = C.create_project("Chest", C.config())
            p.save_brief(Brief(name="Chest", parts=list(CHEST), supply_ma=500,
                               power="USB 5 V 0.5 A", rails=[5.0, 3.3]))
            (p.root / ".nemo").mkdir(exist_ok=True)
            (p.root / ".nemo" / "results.json").write_text(json.dumps(
                {"parts": rec("current_sum", "FAIL")}))
            out = io.StringIO()
            with redirect_stdout(out):
                cli.main(["--project", "chest", "fix", "--stage", "parts"])
            self.assertIn("1. Power it from", out.getvalue())
            with redirect_stdout(io.StringIO()):
                cli.main(["--project", "chest", "fix", "--stage", "parts", "1"])
            self.assertEqual(p.load_brief().supply_ma, 1000)


class TestSkippedForWantOfTheBrief(unittest.TestCase):
    """D175: on the AH531 a brief with no supply rating and no enclosure size
    left step 2 'Unchecked' with only greyed-out advice, "'current_sum' could
    not run", and nothing saying where either value goes."""

    def skipped(self, br, name):
        ps = P(br.parts)
        r = (current_sum(ps, br.supply_ma) if name == "current_sum"
             else fits_envelope(ps, br.envelope_mm))
        self.assertEqual(r.status, "SKIP")          # the situation reported
        return suggest_fixes(br, LIB, "parts", rec(name, "SKIP", r.detail, r.items))

    def test_no_supply_rating_offers_a_supply_that_passes(self):
        br = Brief(name="x", parts=list(CHEST), power="USB")
        fs = self.skipped(br, "current_sum")
        change = [f for f in fs if f.kind == "change"]
        self.assertTrue(change)
        b = apply_fix(br, change[0])
        self.assertEqual(current_sum(P(b.parts), b.supply_ma).status, "PASS")

    def test_no_envelope_offers_a_size_the_parts_fit(self):
        br = Brief(name="x", parts=list(CHEST))
        fs = self.skipped(br, "fits_envelope")
        change = [f for f in fs if f.kind == "change"]
        self.assertTrue(change)
        b = apply_fix(br, change[0])
        self.assertEqual(len(b.envelope_mm), 3)
        self.assertEqual(fits_envelope(P(b.parts), b.envelope_mm).status, "PASS")

    def test_the_advice_names_the_field_to_fill(self):
        br = Brief(name="x", parts=list(CHEST))
        for name, fld in (("current_sum", "supply_ma"), ("fits_envelope", "envelope_mm")):
            fs = self.skipped(br, name)
            self.assertIn(fld, [f.brief_field for f in fs if f.kind == "info"])
            self.assertFalse(any("could not run" in f.title for f in fs))

    def test_a_missing_tool_is_still_said_as_one(self):
        f = suggest_fixes(Brief(name="x"), LIB, "electrical",
                          rec("erc", "SKIP", "KiCad not installed"))[0]
        self.assertIn("could not run", f.title)
        self.assertEqual(f.brief_field, "")
