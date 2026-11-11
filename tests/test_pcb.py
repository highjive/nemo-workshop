"""The PCB Designer (owner, 2026-11-04): nets to a routed, checked board and
its Gerbers; parts without real footprints are named, never guessed."""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import pcb
from nemo.parts import Part, Pin, PartsLibrary, _build_part

ROOT = Path(__file__).resolve().parent.parent
HEADER = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"


def circuit():
    """An invented test circuit on standard KiCad footprints: a supply header,
    a resistor and an LED."""
    parts = [
        Part("j1", "Power header", "connector", footprint=HEADER,
             pins=[Pin("V+", "power"), Pin("GND", "gnd")], pads={"V+": "1", "GND": "2"}),
        Part("r1", "Resistor", "logic", footprint="Resistor_SMD:R_0805_2012Metric",
             pins=[Pin("A", "io"), Pin("B", "io")], pads={"A": "1", "B": "2"}),
        Part("d1", "LED", "display", footprint="LED_SMD:LED_0805_2012Metric",
             pins=[Pin("K", "io"), Pin("A", "io")], pads={"K": "1", "A": "2"}),
    ]
    nets = {"VCC": [("j1", "V+"), ("r1", "A")], "LED_A": [("r1", "B"), ("d1", "A")],
            "GND": [("d1", "K"), ("j1", "GND")]}
    return parts, nets


def _tools():
    try:
        return pcb.tools()
    except pcb.PcbError:
        return None


class TestWhatABoardNeeds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        lib = self.root / "Connector_PinHeader_2.54mm.pretty"
        lib.mkdir()
        (lib / "PinHeader_1x02_P2.54mm_Vertical.kicad_mod").write_text("(footprint)", encoding="utf-8")

    def test_a_part_with_no_footprint_is_named(self):
        parts, nets = circuit()
        parts[1].footprint = ""
        self.assertIn("r1: no footprint in its library entry", pcb.missing(parts, nets, self.root))

    def test_a_footprint_kicad_does_not_have_is_named(self):
        parts, nets = circuit()
        parts[0].footprint = "Connector_PinHeader_2.54mm:Nonesuch"
        self.assertTrue(any("not in KiCad's libraries" in m for m in pcb.missing(parts, nets, self.root)))

    def test_a_wired_pin_with_no_pad_is_named(self):
        parts, nets = circuit()
        parts[0].pads = {"V+": "1"}
        self.assertIn("j1: no pad given for GND", pcb.missing([parts[0]], nets, self.root))

    def test_every_footprint_has_its_source_and_covers_every_pin(self):
        with_fp = [p for p in PartsLibrary.load() if p.footprint]
        self.assertEqual(sorted(p.ref for p in with_fp),
                         ["ds18b20", "esp32c3_devkit", "rp2040_pico", "sn74ahct125"])
        for p in with_fp:
            self.assertTrue(p.footprint_source, p.ref)
            self.assertEqual(sorted(p.pads), sorted(q.name for q in p.pins), p.ref)

    def test_the_esp32c3_pads_are_espressifs_header_tables(self):
        # Espressif's ESP32-C3-DevKitM-1 user guide (read 2026-11-04): pads
        # 1-15 down the left are J1 1-15, pads 16-30 up the right J3 15..1.
        j1 = ["GND", "3V3", "3V3", "IO2", "IO3", "GND", "RST", "GND", "IO0", "IO1", "IO10", "GND", "5V", "5V", "GND"]
        j3 = ["GND", "TX", "RX", "GND", "IO9", "IO8", "GND", "IO7", "IO6", "IO5", "IO4", "GND", "IO18", "IO19", "GND"]
        pad_of = {}
        for no, n in enumerate(j1, 1):
            pad_of.setdefault(n, str(no))
        for no, n in enumerate(j3, 1):
            pad_of.setdefault(n, str(31 - no))
        part = PartsLibrary.load().get("esp32c3_devkit")
        for pin, pad in part.pads.items():
            self.assertEqual(pad, pad_of[pin.replace("GPIO", "IO")], pin)

    def test_the_buffers_pads_are_tis_table(self):
        # TI SCLS264R Table 4-1 (14-pin packages).
        ti = ["1OE", "1A", "1Y", "2OE", "2A", "2Y", "GND", "3Y", "3A", "3OE", "4Y", "4A", "4OE", "VCC"]
        self.assertEqual(PartsLibrary.load().get("sn74ahct125").pads, {n: str(i + 1) for i, n in enumerate(ti)})


@unittest.skipUnless((_k := _tools()) is not None, "needs KiCad")
class TestTheFootprintsAreKiCads(unittest.TestCase):
    def test_each_footprint_and_each_pad_exists_in_kicad(self):
        for p in PartsLibrary.load():
            if not p.footprint:
                continue
            f = pcb.footprint_file(p.footprint, _k.footprints)
            self.assertIsNotNone(f, p.ref)
            pads = set(re.findall(r'\(pad "([^"]+)"', f.read_text(encoding="utf-8")))
            for pin, pad in p.pads.items():
                self.assertIn(pad, pads, f"{p.ref} {pin}")


class TestTheLibrary(unittest.TestCase):
    def test_pads_are_names_even_when_yaml_reads_numbers(self):
        p = _build_part("x", {"name": "X", "category": "logic", "pins": [{"name": "VCC"}],
                              "footprint": HEADER, "pads": {"VCC": 1}})
        self.assertEqual(p.pads, {"VCC": "1"})

    def test_a_pad_for_a_pin_the_part_does_not_have_is_refused(self):
        with self.assertRaisesRegex(ValueError, "pads must map"):
            _build_part("x", {"name": "X", "category": "logic", "pins": [{"name": "VCC"}],
                              "pads": {"VDD": 1}})


@unittest.skipUnless((_t := _tools()) is not None and _t.java is not None and _t.freerouting is not None,
                     "needs KiCad, Freerouting and Java 25")
class TestARealBoard(unittest.TestCase):
    """Placed by code, routed by Freerouting, checked by KiCad, exported."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        parts, nets = circuit()
        cls.board = pcb.make(parts, nets, Path(cls.tmp.name) / "pcb")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_it_is_routed_and_kicad_finds_no_error(self):
        b = self.board
        self.assertTrue(b.routed)
        self.assertEqual(b.drc_errors, [])
        self.assertGreater(b.tracks, 0)
        self.assertTrue(b.ok)

    def test_every_part_is_on_the_board(self):
        # The first board's outline was 8 mm square round nothing, its parts
        # outside it, and KiCad's error check passed it (2026-11-04).
        self.assertEqual(self.board.outside, [])
        # Round the parts, not round nothing: wider than the two margins and
        # the 2.54 mm header's own 2.5 mm courtyard.
        self.assertGreater(min(self.board.size_mm), 2 * pcb.MARGIN_MM + 2.5)

    def test_its_gerbers_and_drill_are_made(self):
        names = {g.name for g in self.board.gerbers}
        for want in ("board-F_Cu.gtl", "board-B_Cu.gbl", "board-Edge_Cuts.gm1", "board.drl"):
            self.assertIn(want, names)


@unittest.skipUnless((_t2 := _tools()) is not None and _t2.java is not None and _t2.freerouting is not None,
                     "needs KiCad, Freerouting and Java 25")
class TestABoardOfNemosOwnParts(unittest.TestCase):
    """The Pico, the DS18B20 and the SN74AHCT125 with their sourced footprints.
    Placed by catalogue size, two of them sat on the Pico and KiCad found 70
    faults (2026-11-04); placed by their real outlines, it is clean."""

    def test_it_is_clean(self):
        lib = PartsLibrary.load()
        parts = [lib.get("rp2040_pico"), lib.get("ds18b20"), lib.get("sn74ahct125")]
        nets = {"+3V3": [("rp2040_pico", "3V3"), ("ds18b20", "VDD")],
                "+5V": [("rp2040_pico", "VBUS"), ("sn74ahct125", "VCC")],
                "GND": [("rp2040_pico", "GND"), ("ds18b20", "GND"), ("sn74ahct125", "GND"),
                        ("sn74ahct125", "1OE")],
                "GPIO2": [("rp2040_pico", "GPIO2"), ("ds18b20", "DQ")],
                "GPIO3": [("rp2040_pico", "GPIO3"), ("sn74ahct125", "1A")]}
        with tempfile.TemporaryDirectory() as d:
            b = pcb.make(parts, nets, Path(d) / "pcb")
        self.assertEqual(b.drc_errors, [])
        self.assertTrue(b.ok, (b.unrouted, b.outside))


class TestReadOffYourModule(unittest.TestCase):
    def setUp(self):
        from nemo import footprints
        self.F = footprints
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.bme = PartsLibrary.load().get("bme280")

    def test_a_header_read_off_the_module_becomes_its_footprint_in_your_parts(self):
        pins = [q.name for q in self.bme.pins]
        order = ["-", *reversed(pins), "-"]                   # two pins Nemo does not use
        out = self.F.header(self.bme, order, Path(self.tmp.name))
        mine = PartsLibrary.load(Path(self.tmp.name)).get("bme280")
        self.assertEqual(out.parent, Path(self.tmp.name))
        self.assertEqual(mine.footprint, f"Connector_PinSocket_2.54mm:PinSocket_1x{len(order):02d}_P2.54mm_Vertical")
        self.assertEqual(mine.pads, {n: str(order.index(n) + 1) for n in pins})
        self.assertIn("read off the owner's own module", mine.footprint_source)
        self.assertEqual(mine.current_ma, self.bme.current_ma)    # the rest of the entry kept
        self.assertEqual(PartsLibrary.load().get("bme280").footprint, "")   # bundled untouched

    def test_a_pin_the_part_has_not_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no pin called XYZ"):
            self.F.header(self.bme, [q.name for q in self.bme.pins] + ["XYZ"], Path(self.tmp.name))

    def test_a_pin_of_the_part_left_out_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not on the header"):
            self.F.header(self.bme, [q.name for q in self.bme.pins][1:], Path(self.tmp.name))

    def test_a_pin_named_twice_is_refused(self):
        names = [q.name for q in self.bme.pins]
        with self.assertRaisesRegex(ValueError, "named twice"):
            self.F.header(self.bme, names + [names[0]], Path(self.tmp.name))

    def test_the_list_says_which_parts_can_go_on_a_board(self):
        rows = {ref: (fp, why) for ref, fp, why in self.F.status(PartsLibrary.load(), None)}
        self.assertEqual(rows["sn74ahct125"], ("Package_DIP:DIP-14_W7.62mm", ""))
        self.assertIn("read its header off your module", rows["bme280"][1])


class TestTheInstaller(unittest.TestCase):
    def test_nemodoc_fetches_the_same_files(self):
        for base in (ROOT, ROOT / "install" / "windows"):
            if (base / "NemoDoc.ps1").exists():
                text = (base / "NemoDoc.ps1").read_text(encoding="utf-8")
                break
        else:
            self.skipTest("NemoDoc.ps1 not in this layout")
        block = text[text.index("$PcbFiles = @("):text.index("$PcbFiles = @(") + 900]
        pinned = set(re.findall(r'file = "([^"]+)"; sha256 = "([0-9a-f]{64})"; bytes = (\d+)', block))
        self.assertEqual(pinned, {(f, h, str(b)) for f, b, h in (pcb.FREEROUTING, pcb.JRE25)})


if __name__ == "__main__":
    unittest.main()
