"""D178, the AH531 on 2026-10-17 (the owner's photographs).

Step 1 was run again on a project whose brief had passed step 2. The model
put every field inside `blocks: [ {...} ]`; Nemo found none at the top
level, reported function, power, done_when, parts and envelope_mm missing,
and saved that empty brief over the good one.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.pipeline import unwrap_brief
from nemo.project import Brief
from test_pipeline import PipelineCase, StubRouter

# The shape of the real answer, with invented content.
WRAPPED = """```yaml
blocks:
  - name: lantern_player
    function: A lantern that plays a sound when a tag is held to it.
    user: One person at home.
    power: USB 5 V 1 A
    supply_ma: 1000
    rails: [3.3, 5.0]
    envelope_mm: [150, 80, 50]
    parts: [dfplayer_mini, esp32_devkit_v1, speaker_8ohm_20mm]
    mcu: esp32_devkit_v1
    done_when: The sound plays when a tag is held to it.
```"""

GOOD = Brief(name="lantern", function="A lantern that plays a sound.", power="USB 5 V 1 A",
             supply_ma=1000, rails=[5.0, 3.3], envelope_mm=[150, 80, 50],
             parts=["esp32_devkit_v1", "dfplayer_mini", "speaker_8ohm_20mm"], mcu="esp32",
             done_when="It plays.")


class TestAWrappedBriefIsRead(PipelineCase):
    def test_the_fields_inside_the_wrapper_are_found(self):
        self.project.create(Brief(name="x"))
        # The request asks for what the answer describes: since 2026-11-05 a
        # feature the request did not ask for is taken out (nemo/requested.py).
        r = self.pipe(StubRouter(WRAPPED)).stage_brief("a lantern that plays a sound when a tag is held to it")
        self.assertTrue(r.ok, r.render())
        b = self.project.load_brief()
        self.assertEqual(b.envelope_mm, [150, 80, 50])
        self.assertIn("dfplayer_mini", b.parts)

    def test_shapes(self):
        inner = {"function": "f", "power": "p"}
        self.assertEqual(unwrap_brief({"blocks": [inner]}), inner)
        self.assertEqual(unwrap_brief({"brief": inner}), inner)
        self.assertEqual(unwrap_brief([inner]), inner)
        self.assertEqual(unwrap_brief(inner), inner)
        two = {"a": inner, "b": inner}
        self.assertEqual(unwrap_brief(two), two)       # which one is not guessed
        self.assertEqual(unwrap_brief("text"), "text")


class TestAGoodBriefIsNotOverwritten(PipelineCase):
    def test_a_less_complete_answer_does_not_replace_it(self):
        self.project.create(GOOD)
        r = self.pipe(StubRouter("```yaml\nblocks: nothing useful\n```")).stage_brief("x")
        self.assertFalse(r.ok)
        self.assertEqual(self.project.load_brief().envelope_mm, [150, 80, 50])
        self.assertTrue((self.project.root / "brief.rejected.yaml").exists())
        self.assertIn("kept", " ".join(r.notes))

    def test_a_first_partial_brief_is_still_saved(self):
        self.project.create(Brief(name="x"))
        r = self.pipe(StubRouter("```yaml\nfunction: A beeper.\npower: USB\n```")).stage_brief("x")
        self.assertFalse(r.ok)
        self.assertEqual(self.project.load_brief().function, "A beeper.")
