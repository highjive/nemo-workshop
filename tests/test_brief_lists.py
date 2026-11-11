"""D182 and D183, read from the owner's stick after a real NemoIso run on the
AH531 (2026-10-18). Invented content in the shapes found there.

D182: the model gave constraints and open_questions as one sentence each;
they were walked as lists letter by letter, saved one character per line,
and sent to every model step as one-letter constraints.

D183: one line of the model's brief would not parse as YAML
(`open_questions: [Is it compatible?; Is it enough?]`) and the whole brief
was thrown away.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.pipeline import constraints_text, salvage_yaml
from nemo.project import Brief
from test_pipeline import PipelineCase, StubRouter


class TestASentenceIsAList(unittest.TestCase):
    def test_sentences_become_items_not_letters(self):
        b = Brief(name="x", constraints="must be quiet; must fit a pocket",
                  open_questions="Is it waterproof? Is the cable long enough?")
        self.assertEqual(b.constraints, ["must be quiet", "must fit a pocket"])
        self.assertEqual(b.open_questions, ["Is it waterproof?", "Is the cable long enough?"])

    def test_no_prompt_gets_one_letter_constraints(self):
        b = Brief(name="x", constraints="needs a long battery life")
        self.assertIn("- needs a long battery life", constraints_text(b))
        self.assertNotIn("\n- n\n", constraints_text(b))

    def test_a_brief_saved_letter_by_letter_is_mended(self):
        spelt = list("Is it red? Is it blue?")
        self.assertEqual(Brief(name="x", open_questions=spelt).open_questions,
                         ["Is it red?", "Is it blue?"])
        # The window dropped the spaces on the way back; the commas survive.
        glued = list("shortcable,longbattery")
        self.assertEqual(Brief(name="x", constraints=glued).constraints,
                         ["shortcable", "longbattery"])

    def test_short_real_lists_are_left_alone(self):
        self.assertEqual(Brief(name="x", constraints=["a", "b"]).constraints, ["a", "b"])
        self.assertEqual(Brief(name="x", parts=["rc522", "esp32_devkit_v1"]).parts,
                         ["rc522", "esp32_devkit_v1"])

    def test_numbers_given_as_text(self):
        b = Brief(name="x", rails="3.3 and 5", envelope_mm="100 x 60 x 20")
        self.assertEqual(b.rails, [3.3, 5.0])
        self.assertEqual(b.envelope_mm, [100.0, 60.0, 20.0])


BAD = """```yaml
name: tag_player
function: Plays a track when a tag is read.
power: USB 5 V 1 A
supply_ma: 1000
rails: [3.3, 5.0]
envelope_mm: [100, 60, 30]
parts: [rc522, esp32_devkit_v1, dfplayer_mini, speaker_8ohm_20mm]
mcu: esp32_devkit_v1
done_when: a tag plays its track
constraints: needs a reader and a speaker
open_questions: [Is the reader compatible?; Is the storage enough?]
```"""


class TestOneBadLineDoesNotLoseTheBrief(PipelineCase):
    def test_the_rest_of_the_brief_is_kept(self):
        self.project.create(Brief(name="x"))
        r = self.pipe(StubRouter(BAD)).stage_brief("a tag player")
        self.assertTrue(r.ok, r.render())
        b = self.project.load_brief()
        # Kept, and (since 2026-11-08) grown to fit: "a tag player" gives no size,
        # and these four parts do not pack into the model's 100 x 60 mm.
        self.assertEqual(b.envelope_mm[2], 30.0)
        self.assertGreaterEqual(b.envelope_mm[0], 100.0)
        self.assertTrue(any("could not hold the parts" in n for n in r.notes))
        self.assertIn("rc522", b.parts)
        self.assertEqual(b.open_questions, ["Is the reader compatible?", "Is the storage enough?"])

    def test_nothing_usable_is_still_refused(self):
        self.assertEqual(salvage_yaml("::: not a brief :::"), {})
