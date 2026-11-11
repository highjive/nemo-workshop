"""D189, the AH531 on 2026-10-19: "for blunderbuss it kept ignoring no
power no parts". Four ways the owner's ticks were undone: the only fix for
'parts need power' was to untick No power needed; the board left in the
Microcontroller box went back into the parts at every Save; a redraft
rebuilt the brief without them; and the form let the brief contradict them.
Invented content."""
from __future__ import annotations

import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import review
from nemo.fixes import apply_fix
from nemo.parts import PartsLibrary
from nemo.project import Brief, Project
from test_pipeline import PipelineCase, StubRouter

LIB = PartsLibrary.load()
PROP = Brief(name="prop", function="A replica lantern, a prop with nothing inside.",
             envelope_mm=[100, 100, 200], done_when="It stands on a shelf.",
             parts=["rp2040_pico", "ws2812b_ring8"], mcu="rp2040_pico", no_power=True)


class TestTheFirstFixKeepsTheTick(unittest.TestCase):
    def test_remove_the_parts_that_need_power_comes_first(self):
        fixes = review.fixes("parts_need_power", PROP, LIB)
        self.assertEqual(fixes[0].key, "review_drop_powered")
        fixed = apply_fix(PROP, fixes[0])
        self.assertTrue(fixed.no_power)
        self.assertEqual(fixed.parts, [])
        self.assertEqual(fixed.mcu, "")


REPLY = """```yaml
name: lantern
function: A replica lantern, a prop.
power: USB 5 V 1 A
supply_ma: 1000
envelope_mm: [100, 100, 200]
parts: [rp2040_pico, ws2812b_ring8]
mcu: rp2040_pico
done_when: It stands on a shelf.
```"""


class TestARedraftKeepsTheOwnersAnswers(PipelineCase):
    def test_the_ticks_and_what_he_accepted_survive_and_win(self):
        self.project.create(Brief(name="x", no_power=True, no_parts=True,
                                  accepted=["unexplained_parts"]))
        self.pipe(StubRouter(REPLY)).stage_brief("a replica lantern")
        b = self.project.load_brief()
        self.assertTrue(b.no_power and b.no_parts)
        self.assertEqual(b.accepted, ["unexplained_parts"])
        self.assertEqual((b.parts, b.mcu, b.power, b.supply_ma), ([], "", "", 0.0))


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheFormFollowsTheTicks(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        from nemo.config import Config
        Project(Config.load().path("paths.projects") / "prop").create(
            Brief(**{**PROP.__dict__, "no_power": False}))
        self.app = A.NemoApp(); self.app.update()
        self.app.refresh_projects(select="prop"); self.app.update()

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def test_no_parts_clears_the_board_too_and_it_stays_cleared(self):
        self.app.no_parts.set(True)
        with mock.patch.object(self.A.messagebox, "askyesno", return_value=True):
            self.app._ticks_changed()
        b = self.app._form_brief()
        self.assertEqual((b.parts, b.mcu), ([], ""))
        self.app.save_brief(quiet=True)
        self.assertEqual(self.app.project.load_brief().parts, [])
        self.assertEqual(str(self.app.fields["mcu"].cget("state")), "disabled")

    def test_saying_no_keeps_the_parts_and_unticks(self):
        self.app.no_parts.set(True)
        with mock.patch.object(self.A.messagebox, "askyesno", return_value=False):
            self.app._ticks_changed()
        self.assertFalse(self.app.no_parts.get())
        self.assertIn("rp2040_pico", self.app._form_brief().parts)

    def test_no_power_empties_and_greys_the_supply(self):
        self.app._put("supply_ma", "1000")
        self.app.no_power.set(True)
        self.app._ticks_changed()
        self.assertEqual(self.app._form_brief().supply_ma, 0.0)
        self.assertEqual(str(self.app.fields["supply_ma"].cget("state")), "disabled")
