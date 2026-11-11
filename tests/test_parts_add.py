"""More parts: library data quality, adding parts, and the fixes it exposed."""
from __future__ import annotations

import io, os, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.parts import (KNOWN_CATEGORIES, PartsLibrary, delete_user_part,
                        save_part, user_parts_path, validate_part)

ROOT = Path(__file__).resolve().parent.parent
LIB = PartsLibrary.load()

NEW_PARTS = ["lipo_1000", "lipo_2000", "boost_5v_mt3608", "bme280", "mpu6050",
             "vl53l0x", "ds18b20", "ssd1306_oled_096", "drv8833",
             "ws2812b_ring8", "sg90_servo", "relay_5v_1ch", "rp2040_pico",
             "esp32c3_devkit"]


class TestLibraryDataQuality(unittest.TestCase):
    """A wrong figure here is worse than a missing part: every check trusts
    it. These run over the whole library, so they cover parts added later."""

    def test_library_loads_without_errors(self):
        self.assertEqual(LIB.errors, [])

    def test_every_new_part_is_present(self):
        for ref in NEW_PARTS:
            self.assertIsNotNone(LIB.get(ref), ref)

    def test_every_part_records_where_its_figures_came_from(self):
        missing = [p.ref for p in LIB if not p.datasheet.strip()]
        self.assertEqual(missing, [], "parts with no source field")

    def test_pin_names_are_text(self):
        # D70: a relay pin written as bare NO loaded as False.
        for p in LIB:
            for pin in p.pins:
                self.assertIsInstance(pin.name, str, f"{p.ref}: {pin.name!r}")

    def test_no_duplicate_pin_names(self):
        for p in LIB:
            names = [x.name.lower() for x in p.pins]
            self.assertEqual(len(names), len(set(names)), p.ref)

    def test_peak_never_below_typical(self):
        for p in LIB:
            if p.peak_ma:
                self.assertGreaterEqual(p.peak_ma, p.current_ma, p.ref)

    def test_sizes_are_three_positive_numbers_or_absent(self):
        for p in LIB:
            if p.size_mm:
                self.assertEqual(len(p.size_mm), 3, p.ref)
                self.assertTrue(all(v > 0 for v in p.size_mm), p.ref)

    def test_supply_voltages_positive(self):
        for p in LIB:
            self.assertTrue(all(v > 0 for v in p.supply_v), p.ref)

    def test_categories_are_known(self):
        for p in LIB:
            self.assertIn(p.category, KNOWN_CATEGORIES, p.ref)

    def test_pin_functions_are_recognised(self):
        ok = {"", "power", "gnd", "io", "analog", "bus", "contact", "speaker",   # D159, D166
              "usb_dm", "usb_dp"}                                        # the USB socket
        for p in LIB:
            for pin in p.pins:
                self.assertIn(pin.function, ok, f"{p.ref}.{pin.name}")

    def test_parts_named_in_notes_exist(self):
        # The relay's note points at nothing; the DRV8833 placeholder is
        # flagged in its own notes, since its current is a stand-in.
        self.assertIn("NOT the driver's own draw", LIB.get("drv8833").notes)

    def test_relay_pin_no_is_findable(self):
        self.assertIsNotNone(LIB.get("relay_5v_1ch").pin("NO"))
        self.assertIsNotNone(LIB.get("relay_5v_1ch").pin("NC"))

    def test_sourced_figures_match_what_was_read(self):
        # Spot checks against numbers read from the actual datasheets.
        self.assertEqual(LIB.get("vl53l0x").peak_ma, 40)         # ST DocID029104
        self.assertEqual(LIB.get("mpu6050").current_ma, 4)       # 3.9 mA, InvenSense
        self.assertEqual(LIB.get("ds18b20").supply_v, [3.0, 5.0])
        self.assertEqual(LIB.get("dfplayer_mini").current_ma, 15)  # FN-M16P p2


class TestLoaderRejectsMistypedYaml(unittest.TestCase):
    def _load(self, text):
        d = Path(tempfile.mkdtemp()); (d / "x.yaml").write_text(text)
        return PartsLibrary.load(d)

    def test_bare_no_pin_name_is_reported_not_loaded(self):
        lib = self._load("relay:\n  name: R\n  category: actuator\n  pins:\n"
                         "    - {name: NO, function: io}\n")
        self.assertIsNone(lib.get("relay"))
        self.assertTrue(any("not text" in e and "relay" in e for e in lib.errors))

    def test_bare_word_reference_is_reported(self):
        lib = self._load("no:\n  name: N\n  category: other\n")
        self.assertTrue(any("not text" in e for e in lib.errors))

    def test_one_bad_part_does_not_take_out_the_rest(self):
        lib = self._load("good:\n  name: G\n  category: other\n"
                         "bad:\n  name: B\n  category: other\n  pins:\n    - {name: NO}\n")
        self.assertIsNotNone(lib.get("good"))
        self.assertIsNone(lib.get("bad"))
        self.assertEqual(len(lib.errors), 1)

    def test_broken_yaml_file_is_reported_with_its_name(self):
        lib = self._load("a: [unclosed\n")
        self.assertTrue(any("x.yaml" in e and "YAML" in e for e in lib.errors))

    def test_unknown_field_is_reported_not_crashed(self):
        lib = self._load("p:\n  name: P\n  category: other\n  colour: red\n")
        self.assertTrue(lib.errors)

    def test_doctor_reports_load_errors(self):
        src = (ROOT / "nemo" / "doctor.py").read_text()
        self.assertIn("A part could not be loaded", src)


class TestValidatePart(unittest.TestCase):
    GOOD = {"ref": "my_part", "name": "My part", "category": "sensor",
            "datasheet": "estimated, not yet verified", "current_ma": 5,
            "peak_ma": 10, "supply_v": [3.3]}

    def test_good_part_passes(self):
        self.assertEqual(validate_part(self.GOOD, existing_refs=set()), [])

    def test_required_fields(self):
        probs = validate_part({})
        self.assertEqual(len(probs), 4)

    def test_source_is_required(self):
        d = dict(self.GOOD, datasheet="  ")
        self.assertTrue(any("where the figures came from" in p
                            for p in validate_part(d)))

    def test_reference_format(self):
        for bad in ("Has Space", "1starts_digit", "a-b", "x" * 60):
            self.assertTrue(validate_part(dict(self.GOOD, ref=bad)), bad)

    def test_reference_is_lowercased_not_rejected(self):
        self.assertEqual(validate_part(dict(self.GOOD, ref="UPPER")), [])
        d = Path(tempfile.mkdtemp())
        save_part(d, dict(self.GOOD, ref="UPPER"))
        self.assertIsNotNone(PartsLibrary.load(d).get("upper"))

    def test_negative_and_non_numeric(self):
        self.assertTrue(any("negative" in p for p in
                            validate_part(dict(self.GOOD, current_ma=-1))))
        self.assertTrue(any("number" in p for p in
                            validate_part(dict(self.GOOD, peak_ma="lots"))))
        self.assertTrue(validate_part(dict(self.GOOD, supply_v=[0])))
        self.assertTrue(validate_part(dict(self.GOOD, supply_v=["x"])))

    def test_duplicate_needs_consent(self):
        self.assertTrue(validate_part(self.GOOD, existing_refs={"my_part"}))
        self.assertEqual(validate_part(self.GOOD, existing_refs={"my_part"},
                                       allow_overwrite=True), [])


class TestSaveAndDelete(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.d = TestValidatePart.GOOD

    def test_round_trip(self):
        save_part(self.root, self.d)
        p = PartsLibrary.load(self.root).get("my_part")
        self.assertEqual((p.name, p.current_ma, p.supply_v), ("My part", 5, [3.3]))

    def test_second_part_does_not_disturb_the_first(self):
        save_part(self.root, self.d)
        save_part(self.root, dict(self.d, ref="other", name="Other"))
        lib = PartsLibrary.load(self.root)
        self.assertIsNotNone(lib.get("my_part")); self.assertIsNotNone(lib.get("other"))

    def test_bundled_library_is_never_written(self):
        from nemo.parts import BUNDLED
        before = {f.name: f.read_bytes() for f in BUNDLED.glob("*.yaml")}
        save_part(self.root, self.d)
        delete_user_part(self.root, "my_part")
        delete_user_part(self.root, "rc522")           # a bundled part
        after = {f.name: f.read_bytes() for f in BUNDLED.glob("*.yaml")}
        self.assertEqual(before, after)
        self.assertIsNotNone(PartsLibrary.load().get("rc522"))

    def test_deleting_the_last_part_removes_the_file(self):
        save_part(self.root, self.d)
        self.assertTrue(delete_user_part(self.root, "my_part"))
        self.assertFalse(user_parts_path(self.root).exists())
        self.assertFalse(delete_user_part(self.root, "my_part"))

    def test_corrections_override_a_bundled_part(self):
        save_part(self.root, {"ref": "rc522", "name": "corrected",
                              "category": "sensor", "peak_ma": 120,
                              "datasheet": "fixed"})
        self.assertEqual(PartsLibrary.load(self.root).get("rc522").peak_ma, 120)

    def test_empty_values_are_not_written(self):
        save_part(self.root, dict(self.d, notes="", mount="", interfaces=[]))
        text = user_parts_path(self.root).read_text()
        for key in ("notes", "mount", "interfaces"):
            self.assertNotIn(key + ":", text)


class TestConfigDefaults(unittest.TestCase):
    def test_parts_folder_has_a_real_default(self):
        from nemo.config import DEFAULTS
        self.assertTrue(DEFAULTS["paths"]["parts"])

    def test_shipped_config_does_not_override_it_with_none(self):
        # D71: build-dist.py wrote "parts": None into both shipped configs,
        # silently undoing the default, so 'Add a part' had nowhere to write.
        # Checks what a user actually receives: the config.yaml in the
        # distribution folder. (The build script is only in the source tree,
        # so it is checked there and skipped elsewhere -- a first version of
        # this test read it unconditionally and errored in a real install.)
        import yaml
        cfg = ROOT / "config.yaml"
        if not cfg.exists():
            self.skipTest("no config.yaml beside the package (pip install)")
        self.assertTrue(yaml.safe_load(cfg.read_text())["paths"]["parts"])



class TestCommandLine(unittest.TestCase):
    def run_cli(self, *argv):
        from nemo import cli
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                rc = cli.main(list(argv))
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {
            "HOME": self.tmp.name, "USERPROFILE": self.tmp.name, "NEMO_HOME": self.tmp.name + "/.nemo"})
        self._env.start()

    def tearDown(self):
        self._env.stop(); self.tmp.cleanup()

    def test_add_show_overwrite_remove(self):
        rc, out = self.run_cli("part", "add", "btn", "--name", "Button",
                               "--category", "other", "--datasheet", "estimated")
        self.assertEqual(rc, 0, out)
        rc, out = self.run_cli("parts", "btn")
        self.assertIn("Button", out)
        rc, out = self.run_cli("part", "add", "btn", "--name", "B2",
                               "--category", "other", "--datasheet", "x")
        self.assertEqual(rc, 1); self.assertIn("--overwrite", out)
        rc, _ = self.run_cli("part", "add", "btn", "--name", "B2", "--category",
                             "other", "--datasheet", "x", "--overwrite")
        self.assertEqual(rc, 0)
        rc, _ = self.run_cli("part", "remove", "btn")
        self.assertEqual(rc, 0)
        rc, out = self.run_cli("part", "remove", "btn")
        self.assertEqual(rc, 1)

    def test_bundled_part_cannot_be_removed(self):
        rc, out = self.run_cli("part", "remove", "rc522")
        self.assertEqual(rc, 1); self.assertIn("never changed", out)

    def test_missing_source_is_refused(self):
        rc, out = self.run_cli("part", "add", "x", "--name", "X", "--category", "other")
        self.assertEqual(rc, 1); self.assertIn("came from", out)


class TestDesignsWithTheNewParts(unittest.TestCase):
    def P(self, refs):
        return [LIB.get(r) for r in refs]

    def test_sensor_node_passes_the_real_checks(self):
        from nemo.checks import current_sum, supply_rails
        parts = self.P(["esp32c3_devkit", "bme280", "ssd1306_oled_096", "vl53l0x"])
        self.assertEqual(current_sum(parts, 1000).status, "PASS")
        self.assertEqual(supply_rails(parts, [5.0, 3.3]).status, "PASS")

    def test_motor_design_uses_the_driver_placeholder_conservatively(self):
        from nemo.checks import current_sum
        parts = self.P(["esp32_devkit_v1", "drv8833", "sg90_servo"])
        self.assertEqual(current_sum(parts, 3000).status, "PASS")
        self.assertEqual(current_sum(parts, 2000).status, "FAIL")   # 1960 mA peak

    HARNESS = ("connectors:\n  relay_5v_1ch: {pinlabels: [VCC, GND, IN, %s, NC, COM]}\n"
               "  esp32c3_devkit: {pinlabels: [GPIO4, GPIO5]}\ncables:\n  W: {wirecount: 2, gauge: 22 AWG}\n"
               "connections:\n  - - esp32c3_devkit: [GPIO4, GPIO5]\n    - W: [1-2]\n"
               "    - relay_5v_1ch: [%s, COM]\n")

    def _pins(self, no):
        from nemo.pipeline import Pipeline
        d = Path(tempfile.mkdtemp()) / "h.yaml"
        d.write_text(self.HARNESS % (no, no))
        return Pipeline.check_harness_pins(d, self.P(["relay_5v_1ch", "esp32c3_devkit"]))

    def test_relay_design_passes_the_wiring_pin_check_when_quoted(self):
        # D70: with pin name False this raised AttributeError in stage 4.
        r = self._pins('"NO"')
        self.assertNotEqual(r.status, "FAIL", r.items)

    def test_unquoted_no_in_a_harness_is_explained_not_reported_as_False(self):
        # D73: the model writes harness YAML too, and a bare NO reads as False.
        r = self._pins("NO")
        self.assertEqual(r.status, "FAIL")
        text = " ".join(r.items)
        self.assertIn("Quote such pin names", text)
        self.assertNotIn("no pin 'False'", text)

    def test_the_fix_tells_the_model_to_quote_them(self):
        from nemo.fixes import suggest_fixes
        from nemo.project import Brief
        r = self._pins("NO")
        fx = suggest_fixes(Brief(name="x"), LIB, "wiring",
                           {"ok": False, "checks": [{"name": "harness_pins", "status": "FAIL",
                                                     "detail": "", "items": r.items}]})
        self.assertTrue(any("Quote pin names" in c for f in fx for c in f.add_constraints))

    def test_wiring_prompt_warns_about_it(self):
        self.assertIn("NO, ON, OFF",
                      (ROOT / "nemo" / "prompts" / "wiring.md").read_text())

    def test_boards_map_to_platformio_boards(self):
        from nemo.pipeline import pio_board
        self.assertEqual(pio_board("esp32c3_devkit"), "esp32-c3-devkitm-1")
        self.assertEqual(pio_board("rp2040_pico"), "pico")


class TestBatteryOptionsAcrossCells(unittest.TestCase):
    """D69: only the first LiPo cell in the library was ever considered."""

    def test_every_cell_is_offered_and_paired_with_the_real_charger(self):
        from nemo.fixes import _battery_supplies
        sup = _battery_supplies(LIB)
        self.assertEqual({s.key for s in sup},
                         {"eemb_lipo_500", "lipo_1000", "lipo_2000"})
        for s in sup:
            self.assertEqual(s.needs_parts[1], "tp4056_protected")

    def test_a_cells_own_safety_note_is_not_mistaken_for_a_charger(self):
        from nemo.fixes import _battery_supplies
        only_cells = PartsLibrary({k: v for k, v in LIB.parts.items()
                                   if k != "tp4056_protected"})
        self.assertEqual(_battery_supplies(only_cells), [])

    def test_protection_fix_adds_a_charger_not_a_cell(self):
        from nemo.fixes import suggest_fixes
        from nemo.project import Brief
        fx = suggest_fixes(Brief(name="x", parts=["lipo_1000"]), LIB, "parts",
                           {"ok": False, "checks": [{"name": "safety", "status": "FAIL",
                                                     "detail": "", "items": []}]},
                           [{"severity": "block",
                             "rule": "lipo_requires_protection_circuit", "detail": ""}])
        self.assertEqual(fx[0].add_parts, ["tp4056_protected"])


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestNewPartDialog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {
            "HOME": self.tmp.name, "USERPROFILE": self.tmp.name, "NEMO_HOME": self.tmp.name + "/.nemo"})
        self._env.start()
        try:
            from nemo.gui.app import NemoApp, NewPartDialog
        except ImportError:
            self.skipTest("tkinter not installed")
        self.app = NemoApp(); self.app.update()
        self.D = NewPartDialog

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.tmp.cleanup()

    def fill(self, d, **kw):
        for k, v in kw.items():
            w = d.fields[k]
            if hasattr(w, "insert") and k in ("notes",):
                w.insert("1.0", v)
            elif k in ("category", "mount"):
                w.set(v)
            else:
                w.insert(0, v)

    def test_dialog_fits_its_own_contents(self):
        # D72: a fixed 640x640 was 260 px too narrow and cut off Save.
        d = self.D(self.app); self.app.update()
        d.update_idletasks()
        self.assertGreaterEqual(d.winfo_width(), d.winfo_reqwidth())
        self.assertGreaterEqual(d.winfo_height(), d.winfo_reqheight())
        self.assertLessEqual(d.save_btn.winfo_rooty() + d.save_btn.winfo_height(),
                             d.winfo_rooty() + d.winfo_height())

    def test_empty_save_shows_problems_and_stays_open(self):
        d = self.D(self.app); d.save(); self.app.update()
        self.assertTrue(d.winfo_exists())
        self.assertIn("reference", d.err.get("1.0", "end").lower())

    def test_valid_save_closes_and_reaches_the_catalog(self):
        d = self.D(self.app)
        self.fill(d, ref="t_imu", name="Test IMU", category="sensor",
                  supply_v="3.3", current_ma="5", datasheet="estimated")
        d.save(); self.app.update()
        self.assertFalse(d.winfo_exists())
        self.assertTrue(any(p.ref == "t_imu" for p in self.app.library))
        self.assertIn("t_imu", [self.app._catalog_refs[i]
                                for i in range(len(self.app._catalog_refs))])

    def test_non_numeric_input_is_explained_not_crashed(self):
        d = self.D(self.app)
        self.fill(d, ref="t", name="T", category="other", current_ma="lots",
                  datasheet="x")
        d.save(); self.app.update()
        self.assertTrue(d.winfo_exists())
        self.assertIn("numbers", d.err.get("1.0", "end"))

    def test_duplicate_needs_a_second_press(self):
        d = self.D(self.app)
        self.fill(d, ref="rc522", name="Mine", category="sensor", datasheet="x")
        d.save(); self.app.update()
        self.assertTrue(d.winfo_exists())
        self.assertIn("already exists", d.overwrite_note.cget("text"))
        d.save(); self.app.update()
        self.assertFalse(d.winfo_exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
