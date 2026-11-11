"""The Workshop's drawings by CADCraft (owner, 2026-11-11: "yes download cadcraft-cli
and do stage 1"; docs/artcraft-plan.md). Code draws the enclosure from the layout and
the cuts the CadQuery script makes; a gate reads the saved DXF back. One real drawing
is made and measured where cadcraft-cli is installed (the desktop)."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import drawings as D, enclosure as E, toolupdates
from nemo.checks import FAIL, PASS
from nemo.parts import Part

APP = Path(__file__).resolve().parent.parent

# desk-weather-3's real layout (2026-11-11): the vents come from the ESP32's 350 mA peak
PARTS = [Part("bme280", "BME280", "sensor", size_mm=[15, 13, 3], current_ma=1),
         Part("ssd1306_oled_096", "OLED", "display", size_mm=[30, 30, 4], current_ma=20),
         Part("esp32c3_devkit", "ESP32-C3", "mcu", size_mm=[52, 18, 8], peak_ma=350)]
PLACED = [E.Placed("bme280", 2.2, 2.2, 15, 13, 3),
          E.Placed("ssd1306_oled_096", 21.6, 2.2, 30, 30, 4),
          E.Placed("esp32c3_devkit", 2.2, 36.6, 52, 18, 8)]
BOX = E.Box(90, 60, 20, 1.2)
JACK = Part("jack", "3.5 mm jack", "audio", size_mm=[12, 10, 9], mount="panel", current_ma=1)


def script_numbers(script: str) -> dict:
    """The plain number assignments at the top level of a CadQuery script, evaluated."""
    ns: dict = {}
    for line in script.splitlines():
        if re.match(r"^(length|wall|notch_\w+|vent_\w+)(, \w+)* = [-\d.+*/ ()\w,]+$", line):
            exec(line, {}, ns)
    return ns


class TestTheCutsAreTheScriptsCuts(unittest.TestCase):
    def test_notch_and_vents_by_the_same_numbers(self):
        for wall in ("left", "front"):
            script = E.cadquery_script(PLACED, PARTS, BOX, notch_wall=wall)
            n = script_numbers(script)
            cuts = {c.name: c for c in E.wall_cuts(PLACED, PARTS, BOX, wall)}
            notch = cuts["cable notch"]
            self.assertEqual(notch.wall, wall)
            self.assertAlmostEqual(notch.centre, n["notch_y" if wall == "left" else "notch_x"])
            self.assertEqual((notch.width, notch.depth), (n["notch_width"], n["notch_depth"]))
            for k in range(3):
                self.assertAlmostEqual(cuts[f"vent {k + 1}"].centre,
                                       n["width"] / 2 + (k - 1) * 3 * n["vent_width"])

    def test_a_panel_cut_where_the_script_cuts_it(self):
        parts = PARTS + [JACK]
        placed = PLACED + [E.Placed("jack", 60, 40, 12, 10, 9)]
        script = E.cadquery_script(placed, parts, BOX)
        m = re.search(r"cutout_jack = .*?\.translate\(\(wall \+ ([\d.]+) \+ ([\d.]+) / 2", script, re.S)
        cut = next(c for c in E.wall_cuts(placed, parts, BOX) if c.name == "jack")
        self.assertEqual(cut.wall, "back")
        self.assertAlmostEqual(cut.centre, BOX.wall + float(m.group(1)) + float(m.group(2)) / 2)
        self.assertEqual((cut.width, cut.depth), (12, 9))

    def test_no_parts_no_cuts(self):
        self.assertEqual(E.wall_cuts([], [], BOX), [])


class TestTheSheet(unittest.TestCase):
    def setUp(self):
        self.s = D.enclosure_sheet(PLACED, PARTS, BOX, title="desk weather")

    def test_the_tray_and_each_part_from_above(self):
        self.assertIn((0, 0, 90, 60), self.s.rects)
        self.assertIn((1.2, 1.2, 88.8, 58.8), self.s.rects)               # the inside
        self.assertIn((3.4, 37.8, 55.4, 55.8), self.s.rects)              # the ESP32, from the outer corner
        self.assertEqual([d[0] for d in self.s.dims[:3]], [90, 60, 1.2])

    def test_a_long_name_is_drawn_inside_its_part(self):
        for name, args in self.s.commands:
            if name == "text" and args["text"] in {a.ref for a in PLACED}:
                a = next(p for p in PLACED if p.ref == args["text"])
                self.assertLessEqual(args["height"] * 0.9 * len(a.ref), a.dx)

    def test_each_wall_seen_from_outside(self):
        # The left wall from outside runs from y = width to y = 0: the notch,
        # centred at y 46.8, starts 60 - 46.8 - 6 = 7.2 from that wall's left edge.
        self.assertIn(7.2, [d[0] for d in self.s.dims])
        for t in ("LEFT WALL (x = 0), FROM OUTSIDE", "RIGHT WALL (x = length), FROM OUTSIDE"):
            self.assertIn(t, self.s.texts)
        self.assertNotIn("FRONT WALL (y = 0), FROM OUTSIDE", self.s.texts)   # nothing cut there

    def test_paper(self):
        self.assertEqual(D.paper_for([[0, 0], [200, 150]])[0], "A4")
        self.assertEqual(D.paper_for([[0, 0], [300, 150]])[0], "A3")
        with self.assertRaises(D.DrawingError):
            D.paper_for([[0, 0], [500, 150]])


class TestTheGate(unittest.TestCase):
    """What CADCraft reads back from the saved DXF against what Nemo meant."""

    def sheet(self):
        s = D.Sheet()
        s.rect(0, 0, 100, 60)
        s.dim((0, 0), (100, 0), (50, -10))
        s.text((0, 70), "TOP")
        return s

    def read(self, width=100.0, measured=100.0, extra=False):
        rect = {"type": "Polyline", "geometry": {"vertices": [
            {"p": {"x": x, "y": y}} for x, y in ((0, 0), (width, 0), (width, 60), (0, 60))]}}
        dim = {"type": "Dimension", "geometry": {"measurement": measured,
                                                 "p13": {"x": 0, "y": 0}, "p14": {"x": 100, "y": 0}}}
        text = {"type": "Text", "geometry": {"value": "TOP"}}
        return [rect, dim, text] + ([text] if extra else [])

    def test_read_back_as_drawn(self):
        self.assertEqual(D.check(self.sheet(), self.read()), [])

    def test_a_wrong_outline_a_wrong_dimension_and_an_extra_are_each_said(self):
        self.assertIn("is not in the saved drawing", D.check(self.sheet(), self.read(width=100.5))[0])
        self.assertIn("does not read back as 100 mm",
                      D.check(self.sheet(), self.read(measured=99.9))[0])
        self.assertIn("Nemo did not draw", D.check(self.sheet(), self.read(extra=True))[-1])


class TestItsPlaceInNemo(unittest.TestCase):
    def test_not_installed_is_a_note_not_an_open_question(self):
        # The first version made it a SKIP, which every project's guide listed
        # as "unchecked" under its open questions (test_not_applicable caught it).
        self.assertIsNone(D.enclosure_drawing(Path("."), PLACED, PARTS, BOX, "square", "left", "x"))
        src = (APP / "nemo" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("notes.append(drawings.NOT_INSTALLED)", src)
        self.assertIn("NemoDoc installs it", D.NOT_INSTALLED)

    def test_the_enclosure_step_carries_it_as_its_own_check(self):
        src = (APP / "nemo" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("self._drawing = drawings.enclosure_drawing(", src)
        self.assertIn('"thickness", "drawing")', src)

    def test_pinned_alike_in_nemodoc_and_the_doctors_look(self):
        doc = (APP / "NemoDoc.ps1").read_text(encoding="utf-8-sig")
        name, size, sha = D.SOURCES["windows"]
        self.assertIn(f'file = "{name}"; sha256 = "{sha}"; bytes = {size}', doc)
        self.assertIn(D.URL.format(v=D.VERSION, name=name), doc)
        self.assertIn("[switch]$SkipDrawings", doc)
        tool = next(t for t in toolupdates.TOOLS if t.key == "cadcraft")
        self.assertEqual((tool.feed, tool.ours()), ("github:storytold/cadcraft", D.VERSION))


class TestOnNemoIso(unittest.TestCase):
    """Stage 2: the image carries the Linux build, pinned alike; nemodoc reports it."""

    def test_the_image_fetches_the_pinned_linux_build(self):
        iso = (APP / "install" / "live-build" / "build-iso.sh").read_text(encoding="utf-8")
        name, _, sha = D.SOURCES["linux"]
        self.assertIn(f"CAD_V={D.VERSION}", iso)
        self.assertIn(f"CAD_SHA={sha}", iso)
        self.assertEqual(name, f"cadcraft-{D.VERSION}-linux-x86_64.tar.gz")
        self.assertIn('"$ROOT/opt/nemo/cadcraft/cadcraft-cli"', iso)
        self.assertEqual(D.HOME_LINUX, Path("/opt/nemo/cadcraft"))

    def test_nemodoc_reports_it(self):
        doc = (APP / "install" / "linux" / "nemodoc").read_text(encoding="utf-8")
        self.assertIn('"$PREFIX/cadcraft/cadcraft-cli" --version', doc)


class TestTheFloor(unittest.TestCase):
    """The Woodworker's floor, drawn to scale (stage 1's last part)."""

    def test_rows_wall_to_wall_as_the_plan_says(self):
        from nemo import woodworker as Wd
        r = Wd.rows(3100, 193)
        self.assertAlmostEqual(sum(r), 3100)
        self.assertEqual((len(r), r[0], r[-1]), (17, 102.5, 102.5))  # the thin last row shared
        text = Wd.plan("laminate flooring 4.2 x 3.1 m", board_mm=(1380, 193)).text()
        self.assertIn("about 103 mm each", text)
        self.assertEqual(Wd.rows(1000, 200), [200] * 5)                 # whole boards only
        self.assertEqual(Wd.rows(1100, 200), [200] * 5 + [100])        # a last row thick enough

    def test_drawn_at_the_first_scale_that_fits_a4(self):
        s = D.floor_sheet((4200, 3100), [193] * 16 + [12], (1380, 193), "x")
        self.assertEqual(s.scale, 25)
        self.assertEqual(s.commands[0], ("setvar", {"name": "DIMSCALE", "value": 25}))
        self.assertIn(("rectang", {"p1": [0, 0], "p2": [4200, 3100]}), s.commands)
        self.assertEqual(D.floor_sheet((2000, 1200), [150] * 8, (1200, 150), "x").scale, 10)

    def test_no_board_size_no_drawing(self):
        from nemo import woodworker as Wd
        self.assertIsNone(D.floor_drawing(Wd.plan("laminate flooring 4 x 3 m"), Path(".")))


def _installed() -> Path | None:
    with mock.patch.dict(os.environ, {"NEMO_CADCRAFT": "on"}):
        return D.cli()


@unittest.skipUnless(_installed(), "cadcraft-cli is not installed here")
class TestARealDrawing(unittest.TestCase):
    """Drawn by cadcraft-cli 0.19.0, read back, and the PDF measured (the desktop, 2026-11-11)."""

    def test_drawn_read_back_and_full_size(self):
        import pypdf
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"NEMO_CADCRAFT": "on"}):
            r = D.enclosure_drawing(Path(d), PLACED, PARTS, BOX, "rounded", "left", "desk weather")
            self.assertEqual(r.status, PASS, r.items)
            self.assertIn("full size on A4", r.detail)
            for ext in ("dxf", "pdf", "png"):
                self.assertGreater((Path(d) / "drawings" / f"housing.{ext}").stat().st_size, 1000)
            s = pypdf.PdfReader(str(Path(d) / "drawings" / "housing.pdf")).pages[0] \
                .get_contents().get_data().decode("latin1")
        pts = [(float(a), float(b)) for a, b in re.findall(r"(-?[\d.]+) (-?[\d.]+) [ml]\b", s)]
        across = {round(abs(pts[i + 1][0] - pts[i][0]) * 25.4 / 72, 2)
                  for i in range(len(pts) - 1) if abs(pts[i + 1][1] - pts[i][1]) < 1e-3}
        for mm in (52.0, 30.0, 15.0):                     # each part's outline, printed full size
            self.assertIn(mm, across)

    def test_a_floor_drawn_to_scale(self):
        import pypdf
        from nemo import woodworker as Wd
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"NEMO_CADCRAFT": "on"}):
            made = D.floor_drawing(Wd.plan("laminate flooring 4.2 x 3.1 m", board_mm=(1380, 193)),
                                   Path(d))
            self.assertTrue(made.ok, made.faults)
            s = pypdf.PdfReader(str(made.files[1])).pages[0].get_contents().get_data().decode("latin1")
        pts = [(float(a), float(b)) for a, b in re.findall(r"(-?[\d.]+) (-?[\d.]+) [ml]\b", s)]
        across = {round(abs(pts[i + 1][0] - pts[i][0]) * 25.4 / 72, 2)
                  for i in range(len(pts) - 1) if abs(pts[i + 1][1] - pts[i][1]) < 1e-3}
        self.assertIn(168.0, across)                      # 4200 mm at 1:25

    def test_a_drawing_that_cannot_be_made_fails_the_check(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"NEMO_CADCRAFT": "on"}), \
             mock.patch.object(D, "_run", side_effect=D.DrawingError("cadcraft-cli stopped: x")):
            r = D.enclosure_drawing(Path(d), PLACED, PARTS, BOX, "square", "left", "x")
        self.assertEqual((r.status, r.detail), (FAIL, "cadcraft-cli stopped: x"))


if __name__ == "__main__":
    unittest.main()
