"""checks.generate_schematic against what real SKiDL does.

D104 made the pipeline run the model's SKiDL script, but SKiDL was not
installed where that was written, so it was tested only with stand-in
scripts. First run for real on the AH531 (SKiDL 2.3.0, KiCad 10.0.6,
Windows 11), 2026-10-04. What that showed:

  - As shipped, every real script failed at its first Part(): SKiDL finds
    KiCad's symbols only through KICAD<n>_SYMBOL_DIR and nothing set it
    (D118).
  - With it set, generate_netlist() and generate_schematic() both run
    without raising. The script's own folder gains <stem>.kicad_sch,
    <stem>.net, <stem>.erc, <stem>.log and <stem>_sklib.py, where <stem>
    is the script's name, so "schematic.py" yields "schematic.kicad_sch"
    and the relocation D104 added picks the right file.
  - The netlist carries pin NUMBERS only. There are no pin names in it.

The first class needs neither tool and fails on the unfixed code anywhere.
The second runs the real thing and is skipped where it is not installed.
"""
from __future__ import annotations

import importlib.util
import os, re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import checks
from nemo.checks import runners
from nemo.checks.deterministic import FAIL, PASS

# Writes a schematic only if it was told where KiCad's symbols are, which
# is the one thing a real SKiDL script needs from its environment.
NEEDS_SYMBOLS = """
import os, sys
d = os.environ.get("KICAD10_SYMBOL_DIR", "")
if not os.path.isdir(d):
    sys.exit("FileNotFoundError: Can't open file: Device.")
open("schematic.kicad_sch", "w").write("(kicad_sch " + d + ")")
"""

REAL_SCRIPT = """
from skidl import *

set_default_tool(KICAD)

vcc = Net("+5V")
gnd = Net("GND")
mid = Net("LED_A")

r1 = Part("Device", "R", value="330", footprint="Resistor_SMD:R_0805_2012Metric")
d1 = Part("Device", "LED", value="red", footprint="LED_SMD:LED_0805_2012Metric")

vcc += r1[1]
mid += r1[2], d1["A"]
gnd += d1["K"]

generate_netlist()
generate_schematic()
"""


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / "electrical"
        self.work.mkdir()
        self.script = self.work / "schematic.py"
        self.dest = self.work / "project.kicad_sch"


class TestSymbolFolderIsHandedToTheScript(Case):
    def fake_kicad(self, with_symbols=True) -> str:
        prefix = Path(self.tmp.name) / "KiCad"
        (prefix / "bin").mkdir(parents=True)
        cli = prefix / "bin" / "kicad-cli"
        cli.write_text("")
        if with_symbols:
            (prefix / "share" / "kicad" / "symbols").mkdir(parents=True)
        return str(cli)

    def clean_env(self):
        keep = {k: v for k, v in os.environ.items()
                if not re.fullmatch(r"KICAD\d*_SYMBOL_DIR", k)}
        return mock.patch.dict(os.environ, keep, clear=True)

    def test_a_script_that_needs_the_symbols_gets_them(self):
        self.script.write_text(NEEDS_SYMBOLS)
        cli = self.fake_kicad()
        with self.clean_env(), mock.patch.object(runners, "_kicad", return_value=cli):
            r = checks.generate_schematic(self.script, self.dest)
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn(str(Path(cli).resolve().parent.parent / "share" / "kicad" / "symbols"),
                      self.dest.read_text())

    def test_a_folder_the_user_already_chose_is_left_alone(self):
        self.script.write_text(NEEDS_SYMBOLS)
        mine = Path(self.tmp.name) / "my-symbols"
        mine.mkdir()
        cli = self.fake_kicad()
        with self.clean_env(), mock.patch.object(runners, "_kicad", return_value=cli):
            os.environ["KICAD10_SYMBOL_DIR"] = str(mine)
            r = checks.generate_schematic(self.script, self.dest)
        self.assertEqual(r.status, PASS, r.render())
        self.assertIn(str(mine), self.dest.read_text())

    def test_every_version_spelling_is_set_and_our_own_environment_is_not(self):
        cli = self.fake_kicad()
        with self.clean_env(), mock.patch.object(runners, "_kicad", return_value=cli):
            env, symbols = runners._skidl_env()
            self.assertNotIn("KICAD10_SYMBOL_DIR", os.environ)
        for name in ("KICAD_SYMBOL_DIR", "KICAD8_SYMBOL_DIR",
                     "KICAD9_SYMBOL_DIR", "KICAD10_SYMBOL_DIR"):
            self.assertEqual(env[name], str(symbols), name)

    def test_no_symbols_beside_kicad_fails_and_says_why(self):
        self.script.write_text(NEEDS_SYMBOLS)
        cli = self.fake_kicad(with_symbols=False)
        with self.clean_env(), mock.patch.object(runners, "_kicad", return_value=cli):
            r = checks.generate_schematic(self.script, self.dest)
        self.assertEqual(r.status, FAIL)
        self.assertIn("symbol libraries were not found", r.render())
        self.assertFalse(self.dest.exists())

    def test_no_kicad_at_all_still_runs_the_script(self):
        self.script.write_text('open("schematic.kicad_sch", "w").write("(kicad_sch)")')
        with mock.patch.object(runners, "_kicad", return_value=None):
            r = checks.generate_schematic(self.script, self.dest)
        self.assertEqual(r.status, PASS, r.render())


class TestNetNamesFromEitherNetlistLayout(unittest.TestCase):
    """D124: netlist_nets() returned nothing for any KiCad 10 schematic."""

    # Copied from `kicad-cli sch export netlist` on KiCad 10.0.6, run on the
    # complex_hierarchy demo on the AH531. Tabs as written.
    KICAD_10 = (
        '(export\n\t(version "E")\n'
        '\t(components\n\t\t(comp\n\t\t\t(ref "C104")\n\t\t\t(value "100nF")\n'
        '\t\t\t(libsource\n\t\t\t\t(lib "Device")\n\t\t\t\t(part "C")\n\t\t\t)\n\t\t)\n\t)\n'
        '\t(libparts\n\t\t(libpart\n\t\t\t(lib "Device")\n\t\t\t(part "C")\n'
        '\t\t\t(pins\n\t\t\t\t(pin\n\t\t\t\t\t(num "1")\n\t\t\t\t\t(name "~")\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
        '\t(nets\n'
        '\t\t(net\n\t\t\t(code "1")\n\t\t\t(name "+12V")\n\t\t\t(class "Default")\n'
        '\t\t\t(node\n\t\t\t\t(ref "C104")\n\t\t\t\t(pin "1")\n\t\t\t\t(pintype "passive")\n\t\t\t)\n'
        '\t\t\t(node\n\t\t\t\t(ref "D101")\n\t\t\t\t(pin "1")\n\t\t\t\t(pinfunction "K_1")\n'
        '\t\t\t\t(pintype "passive")\n\t\t\t)\n\t\t)\n'
        '\t\t(net\n\t\t\t(code "2")\n\t\t\t(name "/ampli_ht_vertical/HT_OUT")\n\t\t\t(class "Default")\n\t\t)\n'
        '\t\t(net\n\t\t\t(code "3")\n\t\t\t(name "GND")\n\t\t)\n'
        '\t)\n)\n')
    # The layout the old reader was written for.
    KICAD_9 = ('(export (version "E")\n'
               '  (components\n    (comp (ref "R1") (value "330"))\n  )\n'
               '  (nets\n'
               '    (net (code "1") (name "+5V")\n      (node (ref "R1") (pin "1") (pintype "passive")))\n'
               '    (net (code "2") (name "Net-(D1-A)")\n      (node (ref "R1") (pin "2")))\n'
               '    (net (code "3") (name "GND"))))\n')

    def test_the_kicad_10_layout(self):
        self.assertEqual(runners.parse_net_names(self.KICAD_10),
                         {"+12V", "/ampli_ht_vertical/HT_OUT", "GND"})

    def test_the_older_one_line_layout_still_reads(self):
        self.assertEqual(runners.parse_net_names(self.KICAD_9),
                         {"+5V", "Net-(D1-A)", "GND"})

    def test_names_that_are_not_nets_are_not_returned(self):
        names = runners.parse_net_names(self.KICAD_10)
        for not_a_net in ("~", "Device", "C", "C104", "K_1", "Default"):
            self.assertNotIn(not_a_net, names)

    def test_nothing_in_nothing_out(self):
        self.assertEqual(runners.parse_net_names(""), set())
        self.assertEqual(runners.parse_net_names("(export (version \"E\"))"), set())


WITH_FLAGS = REAL_SCRIPT.replace(
    "generate_netlist()",
    'f1 = Part("power", "PWR_FLAG")\nf2 = Part("power", "PWR_FLAG")\n'
    "vcc += f1[1]\ngnd += f2[1]\n\ngenerate_netlist()")


class TestSchematicPromptAsksForPowerFlags(unittest.TestCase):
    """Measured on the AH531 with SKiDL 2.3.0 and KiCad 10.0.6: a correct
    two-part circuit failed ERC with two "Input Power pin not driven"
    errors as the prompt then stood; with `net.drive = POWER` it still
    failed; with a PWR_FLAG part on each rail it passed. The owner approved
    adding the line."""

    def test_the_prompt_says_so(self):
        from nemo.prompts import load_prompt
        text = load_prompt("schematic", rails="+5V, +3V3, GND")
        self.assertIn('Part("power", "PWR_FLAG")', text)
        self.assertIn("every supply rail and to GND", text)


HAVE_SKIDL = importlib.util.find_spec("skidl") is not None
SYMBOLS = runners._skidl_env()[1]


@unittest.skipUnless(HAVE_SKIDL and SYMBOLS, "needs SKiDL and KiCad's symbol libraries")
class TestRealSkidl(Case):
    """Slow: about 10 to 40 s on the AH531."""

    def test_a_real_script_generates_and_is_relocated(self):
        self.script.write_text(REAL_SCRIPT)
        r = checks.generate_schematic(self.script, self.dest)
        self.assertEqual(r.status, PASS, r.render())
        self.assertTrue(self.dest.read_text(encoding="utf-8").lstrip()
                        .startswith("(kicad_sch"))
        # Named after the script, and moved, not copied.
        self.assertFalse((self.work / "schematic.kicad_sch").exists())

        # What else real SKiDL leaves beside the script.
        names = {p.name for p in self.work.iterdir()}
        self.assertLessEqual({"schematic.net", "schematic.log"}, names, names)

        # O7: the netlist identifies pins by number only.
        net = (self.work / "schematic.net").read_text(encoding="utf-8")
        self.assertIn('(pin "1")', net)
        self.assertNotIn("pinfunction", net)
        for rail in ("+5V", "GND", "LED_A"):
            self.assertIn(f'(name "{rail}")', net)

        # D124, end to end: real kicad-cli exports the schematic real SKiDL
        # just made, and the rails the script declared come back by name.
        if runners._kicad():
            self.assertLessEqual({"+5V", "GND", "LED_A"}, checks.netlist_nets(self.dest))

    @unittest.skipUnless(runners._kicad(), "needs kicad-cli")
    def test_power_flags_are_what_make_erc_pass(self):
        # The measurement behind the prompt line, kept runnable.
        self.script.write_text(REAL_SCRIPT, encoding="utf-8")
        self.assertEqual(checks.generate_schematic(self.script, self.dest).status, PASS)
        without = checks.erc(self.dest)
        self.assertEqual(without.status, FAIL, without.render())
        self.assertIn("Input Power pin not driven", without.render())

        self.dest.unlink()
        self.script.write_text(WITH_FLAGS, encoding="utf-8")
        self.assertEqual(checks.generate_schematic(self.script, self.dest).status, PASS)
        with_flags = checks.erc(self.dest)
        self.assertEqual(with_flags.status, PASS, with_flags.render())


if __name__ == "__main__":
    unittest.main(verbosity=2)
