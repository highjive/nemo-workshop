"""The Writer (owner's request, 2026-10-21): drafts the brief, checks its
spelling with Harper and hands it to the Designer as an assignment; writes
story chapters, corrects its own plain slips, and passes them to the Editor.

The JSON below is cut from Harper v2.12.0's real output on the AH531 for the
sentence in SAMPLE (harper-cli lint --format json --dialect british)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import review, staff, steps, stories, writer
from nemo.parts import PartsLibrary
from nemo.project import Brief, Project

SAMPLE = ("A replica Blunderbust gun with a mechanical trigger mechanism that simulate the "
          "firing action. The colour of the the wooden stock is brown. Its a toy, it fires "
          "nothing.")
REAL = [{"file": "sample.txt", "lint_count": 3, "lints": [
    {"rule": "ItsContraction", "kind": "Punctuation", "span": {"char_start": 140, "char_end": 143},
     "line": 1, "column": 141, "message": "Use `it's` (short for `it has` or `it is`) here, "
     "not the possessive `its`.", "priority": 54,
     "suggestions": ["Replace with: \u201cIt's\u201d", "Replace with: \u201cIt has\u201d"],
     "matched_text": "Its"},
    {"rule": "RepeatedWords", "kind": "Repetition", "span": {"char_start": 109, "char_end": 116},
     "line": 1, "column": 110, "message": "Did you mean to repeat this word?", "priority": 128,
     "suggestions": ["Replace with: \u201cthe\u201d"], "matched_text": "the the"},
    {"rule": "SpellCheck", "kind": "Spelling", "span": {"char_start": 10, "char_end": 21},
     "line": 1, "column": 11, "message": "Did you mean `Blunderbuss`?", "priority": 63,
     "suggestions": ["Replace with: \u201cBlunderbuss\u201d"], "matched_text": "Blunderbust"}]}]


def harper_says(doc):
    """A stand-in harper-cli: prints `doc` as its JSON and exits 1, as the
    real one does when it finds anything."""
    def run(cmd, **kw):
        return mock.Mock(stdout=json.dumps(doc), stderr="Error: Lints were found", returncode=1)
    return run


def lint(rule, kind, matched, start, *subs):
    return writer.Lint(rule, kind, "", start, start + len(matched), matched,
                       [f"Replace with: \u201c{s}\u201d" for s in subs])


class Installed(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(writer, "harper", return_value="harper-cli")
        p.start(); self.addCleanup(p.stop)


class TestReadingHarper(Installed):
    def test_the_real_output_is_read(self):
        found = writer.check(SAMPLE, run=harper_says(REAL))
        self.assertEqual([(l.rule, l.matched, l.replacement) for l in found], [
            ("SpellCheck", "Blunderbust", "Blunderbuss"),
            ("RepeatedWords", "the the", "the"),
            ("ItsContraction", "Its", "It's")])
        self.assertEqual(SAMPLE[found[0].start:found[0].end], "Blunderbust")

    def test_not_installed_is_none_and_changes_nothing(self):
        with mock.patch.object(writer, "harper", return_value=None):
            self.assertIsNone(writer.check("anything"))
            self.assertIsNone(writer.brief_spelling(Brief(name="x", function="tset")))


class TestTheWriterCorrectsOnlyWhatCannotChangeAMeaning(unittest.TestCase):
    def test_slips_corrected_guesses_left(self):
        text = "The the dragon flew ovr the hills and recieved a gift. It was beautifull. Elowne smiled."
        at = text.index
        lints = [lint("RepeatedWords", "Repetition", "The the", 0, "The"),
                 lint("SpellCheck", "Spelling", "ovr", at("ovr"), "or", "our", "ova"),
                 lint("SpellCheck", "Spelling", "recieved", at("recieved"), "received", "relieved"),
                 lint("SpellCheck", "Spelling", "beautifull", at("beautifull"), "beautiful",
                      "beautifully"),
                 lint("SpellCheck", "Spelling", "Elowne", at("Elowne"), "Elaine")]
        fixed, changes = writer.fix_text(text, lints)
        self.assertEqual(fixed, "The dragon flew ovr the hills and received a gift. "
                                "It was beautiful. Elowne smiled.")
        # "ovr" -> "or" was Harper's first guess for a real slip of "over".
        self.assertEqual(changes, ["The the -> The", "recieved -> received",
                                   "beautifull -> beautiful"])


class TestTheBrief(Installed):
    def brief(self, **kw):
        return Brief(**{"name": "blunderbust-gun", "function": SAMPLE,
                        "done_when": "test_firing_simulation", "envelope_mm": [150, 80, 30],
                        "constraints": ["must be safe"], "no_power": True, "no_parts": True,
                        **kw})

    def test_misspellings_found_in_their_field_and_corrected_there(self):
        b = self.brief()
        with mock.patch("subprocess.run", harper_says(REAL)):
            sp = writer.brief_spelling(b)
        self.assertEqual([(s.field, s.index, s.old, s.new) for s in sp],
                         [("function", -1, "Blunderbust", "Blunderbuss")])
        self.assertTrue(writer.corrected(b, sp[0]).startswith("A replica Blunderbuss gun"))

    def test_a_word_in_a_list_field_is_corrected_in_its_item(self):
        b = self.brief(function="ok", constraints=["one", "must be waterprof"])
        s = writer.Spelling("constraints", 1, "waterprof", "waterproof", "")
        self.assertEqual(writer.corrected(b, s), ["one", "must be waterproof"])

    def test_the_assignment_says_what_is_unclear_and_adds_nothing(self):
        b = self.brief()
        sp = [writer.Spelling("function", -1, "Blunderbust", "Blunderbuss", "")]
        a = writer.assignment(b, [], sp)
        self.assertIn("a name rather than a test", a)
        self.assertIn("did you mean \u201cBlunderbuss\u201d", a)
        self.assertIn("Vague words the Designer cannot act on: safe", a)
        self.assertIn("No parts: nothing electrical.", a)
        self.assertIn("Inside 150 x 80 x 30 mm.", a)
        self.assertIn("Spelling was not checked", writer.assignment(b, [], None))
        clear = self.brief(function="Holds six pens upright on a desk.",
                           done_when="Six pens stand in it without tipping.", constraints=[])
        # Not "None: ...": the Workshop printed it as "Writer: None: the brief reads clearly." (2026-11-08).
        self.assertIn("The brief reads clearly: nothing to ask.", writer.assignment(clear, [], []))
        self.assertNotIn("None", writer.assignment(clear, [], []))


class TestTheReviewerAndItsFixes(Installed):
    def setUp(self):
        super().setUp()
        self.proj = Project(Path(tempfile.mkdtemp()) / "p")
        self.addCleanup(shutil.rmtree, self.proj.root.parent, True)
        self.proj.create(Brief(name="gun", function=SAMPLE, done_when="It clicks when pulled.",
                               envelope_mm=[150, 80, 30], no_power=True, no_parts=True))
        self.lib = PartsLibrary.load()
        p = mock.patch("subprocess.run", harper_says(REAL))
        p.start(); self.addCleanup(p.stop)

    def test_a_misspelling_stops_the_next_step_with_a_fix_for_each_word(self):
        stops = review.before("parts", self.proj, self.lib)[0]
        stop = next(s for s in stops if s.name == "review_brief_spelling")
        self.assertIn("'Blunderbust' (did you mean 'Blunderbuss'?)", stop.detail)
        fx = review.fixes("brief_spelling", self.proj.load_brief(), self.lib)
        self.assertEqual([f.title for f in fx], ["Spell 'Blunderbust' as 'Blunderbuss'",
                                                 "These words are spelt as meant"])
        self.assertTrue(fx[0].set_fields["function"].startswith("A replica Blunderbuss"))

    def test_words_said_to_be_meant_are_let_be(self):
        b = self.proj.load_brief(); b.accepted = ["spelling:blunderbust"]; self.proj.save_brief(b)
        stops = [s.name for s in review.before("parts", self.proj, self.lib)[0]]
        self.assertNotIn("review_brief_spelling", stops)

    def test_the_assignment_is_written_before_the_designer_starts(self):
        path, notes = writer.write_assignment(self.proj, self.lib)
        self.assertEqual(path.name, "assignment.md")
        self.assertTrue(any("Blunderbuss" in n for n in notes))
        src = (Path(__file__).resolve().parent.parent / "nemo" / "workflow.py").read_text(
            encoding="utf-8")
        self.assertIn('if stage == "parts":', src)
        self.assertIn("writer.write_assignment(", src)


class TestStories(unittest.TestCase):
    def test_names_are_not_left_for_the_editor(self):
        lints = [lint("SpellCheck", "Spelling", "Elowne", 0, "Elaine")]
        with mock.patch.object(writer, "check", return_value=lints):
            text, fixed, left = stories.writer_pass("Elowne smiled.")
        self.assertEqual((fixed, left), ([], []))

    def test_a_title_word_in_lower_case_is_not_capitalised(self):
        # 2026-11-08: "the clockmaker said" became "the Clockmaker said": the
        # title's "Clockmaker" was a known word, so Harper's one guess was it.
        text = "The old clockmaker smiled."
        seen = []

        def check(t, words=()):
            seen.append(list(words))
            return [lint("SpellCheck", "Spelling", "clockmaker", t.index("clockmaker"),
                         "Clockmaker")] if "clockmaker" not in words else []
        with mock.patch.object(writer, "check", check):
            out, fixed, left = stories.writer_pass(text, "The Clockmaker's Secret")
        self.assertEqual((out, fixed, left), (text, [], []))
        self.assertIn("clockmaker", seen[0])
        # And a change of capital only is never the Writer's to make.
        only_case = lint("SpellCheck", "Spelling", "clockmaker", 8, "Clockmaker")
        self.assertFalse(writer.safe_to_fix(only_case))

    def test_a_lower_case_draft_is_put_right_not_sent_back(self):
        # 2026-11-08: a 4B draft began "the sun rose ... clara and lila stood"
        # and went back to be written again, minutes on the AH531.
        text = "the sun rose. clara and lila stood by rose bushes."
        lints = [lint("SentenceCapitalization", "Capitalization", "the", 0, "The"),
                 lint("SpellCheck", "Spelling", "clara", text.index("clara"), "Clear"),
                 lint("SpellCheck", "Spelling", "lila", text.index("lila"), "Lilac")]
        with mock.patch.object(writer, "check", side_effect=[lints, []]):
            out, fixed, left = stories.writer_pass(text, "Two Sisters", {"Clara", "Lila", "Rose"})
        self.assertEqual(out, "The sun rose. Clara and Lila stood by rose bushes.")
        self.assertEqual(fixed, ["the -> The", "clara -> Clara", "lila -> Lila"])
        # Not a story's name: an unknown lower-case word is still not the Writer's.
        other = lint("SpellCheck", "Spelling", "clara", 0, "Clear")
        self.assertFalse(writer.safe_to_fix(other) and other.replacement == "Clara")
        self.assertFalse(writer.safe_to_fix(lint("SentenceCapitalization", "Capitalization",
                                                 "the", 0, "A")))

    def test_harper_is_given_the_text_with_its_own_line_breaks(self):
        # 2026-11-08: written with Windows' CR LF, Harper's offsets ran one ahead
        # per line break and every fix after the first paragraph was skipped.
        given = []

        def run(cmd, **kw):
            given.append(Path(cmd[-1]).read_bytes())
            return mock.Mock(stdout="[]", stderr="", returncode=0)
        with mock.patch.object(writer, "harper", return_value="harper"):
            writer.check("One.\n\nTwo recieved.\n", run=run)
        self.assertEqual(given, [b"One.\n\nTwo recieved.\n"])

    def test_two_spaces_are_made_one_not_sent_back(self):
        # 2026-11-08: a 4B chapter went back for "  " six times over.
        text = "She stood.  Then she  left."
        lints = [lint("NoFrenchSpaces", "Formatting", "  ", text.index("  "), " "),
                 lint("Spaces", "Formatting", "  ", text.rindex("  "), " ")]
        fixed, changes = writer.fix_text(text, lints)
        self.assertEqual(fixed, "She stood. Then she left.")
        self.assertEqual(len(changes), 2)

    def test_the_editor_sends_back_only_a_lot(self):
        some = [lint("SpellCheck", "Spelling", "x", 0, "y")] * 4
        self.assertEqual(stories.language_faults(some, 350), [])
        many = [lint("SpellCheck", "Spelling", f"w{i}", 0, "y") for i in range(9)]
        self.assertIn("9 spelling or grammar problems", stories.language_faults(many, 350)[0])


class TestTheStaff(unittest.TestCase):
    def test_the_writer_owns_the_brief(self):
        self.assertEqual(staff.owner("brief").title, "Writer")
        self.assertEqual(steps.get("brief").owner, "workshop.writer")
        self.assertIn("assignment", staff.STAFF["workshop.writer"].job)
        self.assertIn("reviews", staff.STAFF["library.editor"].job)


# Found where Nemo finds it (writer.harper: C:/Nemo/writer or its win/, the
# PATH, or paths.harper). It looked only in win/, the laptop's layout, and
# skipped on a machine whose Harper is unzipped straight into C:/Nemo/writer.
with mock.patch.dict(os.environ, {"NEMO_WRITER_CHECK": "on"}):   # the sandbox has it off
    _HARPER = writer.harper() or shutil.which("harper-cli")


@unittest.skipUnless(_HARPER, "needs Harper")
class TestWithRealHarper(unittest.TestCase):
    """Harper v2.12.0 on the AH531."""

    def test_it_finds_the_blunderbuss_and_lets_british_spelling_be(self):
        with mock.patch.dict(os.environ, {"NEMO_WRITER_CHECK": "on"}):
            found = writer.check(SAMPLE)
        self.assertIn(("Blunderbust", "Blunderbuss"),
                      [(l.matched, l.replacement) for l in found])
        self.assertNotIn("colour", [l.matched for l in found])


if __name__ == "__main__":
    unittest.main()
