"""The Print Shop (owner, 2026-10-22): a model sliced for the Kobra 3 with
OrcaSlicer, and the Writer's card. With a stand-in OrcaSlicer, and once with
the real one where it is installed.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import printshop, staff

GCODE = """; HEADER_BLOCK_START
; total layer number: 100
; HEADER_BLOCK_END
; filament used [mm] = 1200.15
; total filament used [g] = 3.58
; estimated printing time (normal mode) = 1h 14m 49s
"""


def cube(path: Path, at=(0.0, 0.0, 0.0), side=20.0):
    """A cube as ASCII STL, its corner at `at`."""
    v = [(x, y, z) for z in (0, side) for y in (0, side) for x in (0, side)]
    tris = [(0, 3, 1), (0, 2, 3), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4),
            (1, 3, 7), (1, 7, 5), (3, 2, 6), (3, 6, 7), (2, 0, 4), (2, 4, 6)]
    body = "".join("facet normal 0 0 0\nouter loop\n" + "".join(
        "vertex {} {} {}\n".format(*(v[i][k] + at[k] for k in range(3))) for i in t)
        + "endloop\nendfacet\n" for t in tris)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"solid c\n{body}endsolid c\n", encoding="utf-8")
    return path


def fake_orca(root: Path) -> Path:
    """An OrcaSlicer folder with a cut-down Anycubic profile tree."""
    exe = root / "OrcaSlicer" / "orca-slicer.exe"
    prof = exe.parent / "resources" / "profiles"
    files = {
        "machine/fdm_machine_common.json": {"type": "machine", "name": "fdm_machine_common",
                                            "gcode_flavor": "marlin", "printable_height": "100"},
        f"machine/{printshop.PRINTER}.json": {
            "type": "machine", "name": printshop.PRINTER, "inherits": "fdm_machine_common",
            "instantiation": "true", "setting_id": "x", "gcode_flavor": "klipper",
            "printable_area": ["0x0", "255x0", "255x255", "0x255"], "printable_height": "260"},
        "process/fdm_process_common.json": {"type": "process", "name": "fdm_process_common",
                                            "layer_height": "0.3"},
        f"process/{printshop.QUALITY}.json": {
            "type": "process", "name": printshop.QUALITY, "inherits": "fdm_process_common",
            "instantiation": "true", "layer_height": "0.2",
            "compatible_printers": [printshop.PRINTER]},
        "process/0.20mm Standard @Some Other.json": {
            "type": "process", "name": "0.20mm Standard @Some Other", "instantiation": "true",
            "compatible_printers": ["Some Other"]},
        f"filament/{printshop.FILAMENT}.json": {
            "type": "filament", "name": printshop.FILAMENT, "instantiation": "true",
            "compatible_printers": [printshop.PRINTER]},
    }
    for rel, d in files.items():
        p = prof / "Anycubic" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding="utf-8")
    (prof / "Anycubic.json").write_text(json.dumps({"version": "02.04.00.02"}), encoding="utf-8")
    exe.write_bytes(b"x")
    return exe


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        self.exe = fake_orca(self.t)
        self._orca = mock.patch.object(printshop, "orca", return_value=self.exe)
        self._orca.start()

    def tearDown(self):
        self._orca.stop(); self._env.stop()
        shutil.rmtree(self.t, ignore_errors=True)


class TestTheProfiles(AHome):
    def test_a_profile_is_written_out_whole(self):
        root = self.exe.parent / "resources" / "profiles"
        d = printshop.flatten(root, "machine", printshop.PRINTER)
        self.assertEqual(d["gcode_flavor"], "klipper")          # its own value wins
        self.assertEqual(d["printable_height"], "260")
        self.assertEqual(d["from"], "User")
        self.assertEqual(d["inherits"], printshop.PRINTER)        # what the CLI matches on
        self.assertEqual(d["name"], f"Nemo {printshop.PRINTER}")
        self.assertEqual(d["version"], "02.04.00.02")
        self.assertNotIn("setting_id", d)
        with self.assertRaises(printshop.PrintShopError):
            printshop.flatten(root, "process", "no such quality")

    def test_the_profiles_are_read_once_per_orcaslicer(self):
        # 2026-11-08: every slice read OrcaSlicer's 12,260 profile files, 50 s
        # cold for a 1.2 s slice. Kept in ~/.nemo; read again when it changes.
        root = self.exe.parent / "resources" / "profiles"
        with mock.patch("nemo.config.CONFIG_HOME", self.t / ".nemo"):
            first = printshop._index(root)
            self.assertTrue((self.t / ".nemo" / "printshop-index.json").is_file())
            with mock.patch.object(printshop, "_read_index", side_effect=AssertionError("read")):
                self.assertEqual(printshop._index(root), first)          # from the cache
            self.exe.write_bytes(b"a newer OrcaSlicer")                  # changed: read again
            with mock.patch.object(printshop, "_read_index", wraps=printshop._read_index) as read:
                self.assertEqual(printshop._index(root), first)
                self.assertEqual(read.call_count, 1)
            (self.t / ".nemo" / "printshop-index.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(printshop._index(root), first)              # damaged: read again

    def test_only_the_kobra_3_s_choices(self):
        c = printshop.choices(self.exe)
        self.assertEqual(c["process"], [printshop.QUALITY])
        self.assertEqual(c["filament"], [printshop.FILAMENT])


class TestTheMesh(AHome):
    MACHINE = {"printable_area": ["0x0", "255x0", "255x255", "0x255"], "printable_height": "260"}

    def test_moved_to_the_middle_of_the_bed(self):
        stl = cube(self.t / "c.stl", at=(-50, 300, 7))
        out = self.t / "moved.stl"
        dims = printshop.centre(printshop.read_stl(stl), out, self.MACHINE)
        self.assertEqual([round(d) for d in dims], [20, 20, 20])
        data = out.read_bytes()
        self.assertEqual(len(data), 84 + 50 * 12)                 # binary, 12 triangles
        lo, hi = printshop.size(printshop.read_stl(out))
        self.assertEqual([round(v, 3) for v in lo], [117.5, 117.5, 0.0])
        self.assertEqual([round(v, 3) for v in hi], [137.5, 137.5, 20.0])

    def test_too_big_for_the_printer(self):
        stl = cube(self.t / "big.stl", side=300)
        with self.assertRaises(printshop.PrintShopError) as e:
            printshop.centre(printshop.read_stl(stl), self.t / "x.stl", self.MACHINE)
        self.assertIn("prints up to 255 x 255 x 260 mm", str(e.exception))

    def test_not_a_mesh(self):
        (self.t / "bad.stl").write_text("hello", encoding="utf-8")
        with self.assertRaises(printshop.PrintShopError):
            printshop.read_stl(self.t / "bad.stl")


class TestTheSlicer(AHome):
    def model(self):
        stl = cube(self.cfg.path("paths.models") / "stand" / "model.stl")
        return printshop.Model("stand", stl, "Art Studio")

    def fake_run(self, rc=0):
        def run(cmd, cwd=None, timeout=0):
            self.cmd = cmd
            if rc == 0:
                (Path(cwd) / "plate_1.gcode").write_text(GCODE, encoding="utf-8")
            return rc, "", "Slic3r::CLI::run found error, exit" if rc else ""
        return run

    def test_it_slices_and_the_writer_writes_a_card(self):
        with mock.patch("nemo.checks.runners._run", side_effect=self.fake_run()):
            job = printshop.slice_model(self.cfg, self.model())
        self.assertTrue(job.ok, job.notes)
        self.assertEqual(job.gcode.name, "stand-0.20mm-Anycubic-PLA.gcode")
        self.assertEqual(job.gcode.parent.name, "print")
        self.assertEqual((job.minutes, job.grams, job.metres, job.layers), (74.8, 3.58, 1.2, 100))
        card = job.card.read_text(encoding="utf-8")
        for words in ("stand (Art Studio)", "0.20mm Standard", "1h 14m 49s", "3.58 g",
                      "Nemo never sends a print"):
            self.assertIn(words, card)
        self.assertIn("--slice", self.cmd)
        self.assertNotIn("--arrange", self.cmd)          # it does not move a model
        sent = json.loads((job.gcode.parent / ".work" / "process.json").read_text(encoding="utf-8"))
        self.assertEqual(sent["inherits"], printshop.QUALITY)

    def test_orca_slicer_s_code_in_words(self):
        with mock.patch("nemo.checks.runners._run", side_effect=self.fake_run(2 ** 32 - 50)):
            job = printshop.slice_model(self.cfg, self.model())
        self.assertFalse(job.ok)
        self.assertEqual(job.notes[0], "the model is not wholly on the bed")
        self.assertIsNone(job.gcode)

    def test_no_orca_slicer(self):
        with mock.patch.object(printshop, "orca", return_value=None):
            self.assertIn("not installed", printshop.slice_model(self.cfg, self.model()).notes[0])

    def test_the_models_it_can_slice(self):
        self.model()
        cube(self.cfg.path("paths.projects") / "lamp" / "enclosure" / "housing.stl")
        got = sorted((m.name, m.where) for m in printshop.models(self.cfg))
        self.assertEqual(got, [("lamp", "Workshop"), ("stand", "Art Studio")])

    def test_the_team_and_its_tools(self):
        self.assertEqual([e.title for e in staff.team("printshop")], ["Slicer", "Writer"])
        from nemo import toolkit
        with mock.patch.object(printshop, "orca", return_value=self.exe):
            got = [n.check(self.cfg)[0] for n in toolkit.NEEDS["printshop.slicer"]]
        self.assertEqual(got, [True, True])


class TestTheInstaller(unittest.TestCase):
    def test_nemodoc_fetches_what_printshop_pins(self):
        text = (Path(__file__).resolve().parent.parent / "NemoDoc.ps1").read_text(encoding="utf-8")
        name, size, sha = printshop.SOURCE
        self.assertIn(f'file = "{name}"; sha256 = "{sha}"; bytes = {size}', text)
        self.assertIn("[switch]$SkipPrint", text)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_pick_and_slice(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        TestTheSlicer.model(self)
        app = A.NemoApp(); app.update()
        try:
            app.cfg = self.cfg
            w = A.PrintShop(app); app.update()
            self.assertEqual(w.quality.get(), "0.20mm Standard")
            self.assertEqual(w.filament.get(), "Anycubic PLA")
            w.tree.selection_set("0")
            with mock.patch("nemo.checks.runners._run", side_effect=TestTheSlicer.fake_run(self)):
                w.slice()
                for _ in range(50):
                    app.update(); app.after(100)
                    if w._job is None and str(w.btn.cget("state")) == "normal":
                        break
            self.assertIn("1h 14m 49s", w.out.get("1.0", "end"))
            self.assertIn("Sliced in", w.note.cget("text"))
            w.destroy()
        finally:
            app.destroy()


REAL = Path(r"C:\Nemo\tools\OrcaSlicer\orca-slicer.exe")


@unittest.skipUnless(REAL.is_file(), "OrcaSlicer not installed here")
class TestTheRealSlicer(unittest.TestCase):
    def test_a_cube_for_the_kobra_3(self):
        t = Path(tempfile.mkdtemp())
        try:
            from nemo.config import Config
            stl = cube(t / "cube" / "model.stl")            # its corner at 0,0: not on the bed
            with mock.patch.object(printshop, "orca", return_value=REAL):
                job = printshop.slice_model(Config.load(Path("/nonexistent")),
                                            printshop.Model("cube", stl, "Art Studio"))
            self.assertTrue(job.ok, job.notes)
            self.assertEqual(job.layers, 100)
            self.assertGreater(job.grams, 1)
            self.assertIn("; printer_model = Anycubic Kobra 3",
                          job.gcode.read_text(encoding="utf-8", errors="replace"))
        finally:
            shutil.rmtree(t, ignore_errors=True)

    def test_a_round_pot_slices(self):
        # 2026-11-04: every cylinder was refused ("no object is fully inside
        # the print volume") while every box sliced: the Kobra 3 profile's
        # 2 mm border, drawn out round the bed and back in as one polygon.
        import trimesh
        t = Path(tempfile.mkdtemp())
        try:
            from nemo.config import Config
            stl = t / "pot" / "model.stl"; stl.parent.mkdir()
            trimesh.creation.cylinder(radius=15, height=10, sections=48).export(stl)
            with mock.patch.object(printshop, "orca", return_value=REAL):
                job = printshop.slice_model(Config.load(Path("/nonexistent")),
                                            printshop.Model("pot", stl, "Art Studio"))
            self.assertTrue(job.ok, job.notes)
        finally:
            shutil.rmtree(t, ignore_errors=True)


KOBRA = {"printable_area": ["0x0", "255x0", "255x255", "0x255"], "printable_height": "260",
         "bed_exclude_area": ["0x0", "255x0", "255x255", "0x255", "0x0",
                              "2x2", "2x253", "253x253", "253x2", "2x2"]}


class TestTheBedsBorder(unittest.TestCase):
    """Anycubic's own Kobra 3 profile (OrcaSlicer 2.4.2) marks a 2 mm border
    as one polygon; OrcaSlicer's command line then sliced only upright boxes."""

    def test_the_border_is_read_and_taken_out(self):
        self.assertEqual(printshop.border(KOBRA), 2.0)
        given, margin = printshop.without_border(KOBRA)
        self.assertEqual((given["bed_exclude_area"], margin), ([], 2.0))
        self.assertEqual(len(KOBRA["bed_exclude_area"]), 10)          # the profile untouched

    def test_another_excluded_area_is_left_alone(self):
        other = {**KOBRA, "bed_exclude_area": ["0x0", "30x0", "30x30", "0x30"]}
        self.assertIsNone(printshop.border(other))
        self.assertEqual(printshop.without_border(other), (other, 0.0))
        uneven = {**KOBRA, "bed_exclude_area": KOBRA["bed_exclude_area"][:5] +
                  ["2x2", "2x250", "253x250", "253x2", "2x2"]}
        self.assertIsNone(printshop.border(uneven))
        self.assertIsNone(printshop.border({**KOBRA, "bed_exclude_area": []}))

    def test_nemo_keeps_the_model_inside_the_border(self):
        pts = [(0, 0, 0), (252, 0, 0), (0, 10, 5)]            # 252 wide: fits 255, not 251
        with tempfile.TemporaryDirectory() as t:
            printshop.centre(pts, Path(t) / "m.stl", KOBRA)
            with self.assertRaises(printshop.PrintShopError):
                printshop.centre(pts, Path(t) / "m.stl", KOBRA, margin=2.0)


if __name__ == "__main__":
    unittest.main()
