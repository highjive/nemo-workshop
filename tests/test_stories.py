"""Stories written by the employees (redesign, 2026-10-17), with a stand-in
model: what each employee is asked, and what the Reviewer sends back."""
from __future__ import annotations

import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import stories as S
from nemo.gui import prompt_logic as L
from nemo.router import Reply


def outline(n, title="The Keeper's Map"):
    return json.dumps({"title": title, "chapters": [
        {"title": f"Part {i}", "summary": f"Event number {i} happens to the keeper."}
        for i in range(1, n + 1)]})


def prose(seed, words=S.WORDS):
    return " ".join(f"{seed}{i}" for i in range(words))


class Model:
    """Answers the plan from `plans`, then chapters from `chapters`, and
    records every question."""

    def __init__(self, plans, chapters, drift=()):
        self.plans, self.chapters, self.asked = list(plans), list(chapters), []
        self.drift = list(drift)              # the Reviewer's question; "no" when run out

    def ask(self, task, system, user, **kw):
        schema = kw.get("schema") or {}
        if "answer" in schema.get("properties", {}):
            self.asked.append({"task": task, "system": system, "user": user, "drift": True, **kw})
            return Reply(json.dumps({"answer": self.drift.pop(0) if self.drift else "no"}),
                         "local", "stub")
        self.asked.append({"task": task, "system": system, "user": user, **kw})
        src = self.plans if schema else self.chapters
        return Reply(src.pop(0), "local", "stub")

    def written(self):
        """The Editor's questions only."""
        return [a for a in self.asked if "schema" not in a]


def story(request):
    root = Path(tempfile.mkdtemp())
    return L.file_story(root, request)


class TestHowMany(unittest.TestCase):
    def test_from_the_requests_words(self):
        self.assertEqual(S.chapter_count("a short story about a fox"), 3)
        self.assertEqual(S.chapter_count("a novel about a fox"), 10)
        self.assertEqual(S.chapter_count("a story in 7 chapters"), 7)
        self.assertEqual(S.chapter_count("a story in four chapters"), 4)
        self.assertEqual(S.chapter_count("a story about a fox"), 5)
        self.assertEqual(S.chapter_count("a story in 99 chapters"), S.MAX_CHAPTERS)


class TestTheTeam(unittest.TestCase):
    def test_a_story_is_planned_written_and_kept(self):
        f = story("Write me a short story about a lighthouse keeper who finds a map")
        m = Model([outline(3)], [prose("a"), prose("b"), prose("c")])
        self.assertTrue(S.write_story(f, m, say=lambda s: None))
        self.assertTrue((f / "outline.md").read_text(encoding="utf-8").startswith("# The Keeper's Map"))
        self.assertEqual(len(list((f / "chapters").glob("*.md"))), 3)
        whole = (f / "story.md").read_text(encoding="utf-8")
        self.assertIn("## 3. Part 3", whole)
        log = [json.loads(l) for l in (f / "work.jsonl").read_text(encoding="utf-8").splitlines()]
        # The Library: the Writer plans and writes, the Editor checks (2026-10-21).
        self.assertEqual({e["who"] for e in log}, {"Writer", "Editor"})
        self.assertEqual({e["department"] for e in log}, {"Library"})

    def test_every_call_is_the_local_story_task_and_the_plan_is_held_to_a_schema(self):
        f = story("A short story about a fox")
        m = Model([outline(3)], [prose("a"), prose("b"), prose("c")])
        S.write_story(f, m, say=lambda s: None)
        self.assertTrue(all(a["task"] == "story" for a in m.asked))
        self.assertEqual(m.asked[0]["schema"]["properties"]["chapters"]["minItems"], 3)

    def test_the_editor_sees_its_own_chapter_only(self):
        f = story("A short story about a fox")
        m = Model([outline(3)], [prose("a"), prose("b"), prose("c")])
        S.write_story(f, m, say=lambda s: None)
        second = m.written()[1]["user"]
        self.assertIn("Event number 2", second)
        # Since 2026-11-08 the chapter before is named as ALREADY TOLD (its plan
        # line, never its words); a later chapter is still never shown (D168).
        self.assertIn("has already told: Event number 1", second)
        self.assertNotIn("Event number 3", second)
        self.assertNotIn("a0 a1 a2", second)                 # not chapter 1's own words
        self.assertIn("ends the story", m.written()[2]["user"])      # the last one is told

    def test_a_bad_plan_goes_back_once_with_the_reason(self):
        f = story("A short story about a fox")
        bad = json.dumps({"title": "T", "chapters": [{"title": "<chapter title>",
                                                      "summary": "<what happens>"}] * 3})
        m = Model([bad, outline(3)], [prose("a"), prose("b"), prose("c")])
        self.assertTrue(S.write_story(f, m, say=lambda s: None))
        self.assertIn("could not be used", m.asked[1]["user"])
        self.assertIn("placeholder", m.asked[1]["user"])

    def test_a_plan_that_fails_twice_stops_the_story(self):
        f = story("A short story about a fox")
        m = Model(["not json", "still not"], [])
        self.assertFalse(S.write_story(f, m, say=lambda s: None))
        self.assertFalse((f / "story.md").exists())

    def test_a_chapter_goes_back_once_then_is_kept_with_the_reason(self):
        f = story("A short story about a fox")
        m = Model([outline(3)], ["Too short.", prose("a"),              # ch 1: back, then fine
                                 "Here is chapter two: " + prose("b"),  # ch 2: back, then fine
                                 prose("b"),
                                 prose("b"), prose("b")])               # ch 3: repeats ch 2 twice
        ok = S.write_story(f, m, say=lambda s: None)
        self.assertFalse(ok)
        users = [a["user"] for a in m.written()]
        self.assertIn("far short", users[1])
        self.assertIn("talks to the reader", users[3])
        self.assertIn("repeats the previous chapter", users[5])
        self.assertEqual(len(list((f / "chapters").glob("*.md"))), 3)   # kept all the same
        log = (f / "work.jsonl").read_text(encoding="utf-8")
        self.assertIn("repeats the previous chapter", log)

    def test_the_reviewers_chapter_checks(self):
        self.assertEqual(S.review_chapter(prose("x"), S.WORDS), [])
        self.assertTrue(S.review_chapter("", S.WORDS))
        self.assertTrue(any("repeats" in f for f in S.review_chapter(prose("x"), S.WORDS, prose("x"))))
        self.assertTrue(any("reader" in f for f in S.review_chapter("Sure! " + prose("x"), S.WORDS)))


LIGHTHOUSE = ("A short story for children about a lighthouse keeper's cat who keeps the lamp lit "
              "during a storm when the keeper falls ill. About 600 words.")
# From qwen3-8b's chapters of it, 2026-11-06 (story run 1, then run 3).
CH1 = ("The wind howled. Inside the tower, the lighthouse keeper, old Mr. Grady, sat by the "
       "window. In the corner, Whiskers, the lighthouse cat, had been watching. Whiskers leaped "
       "onto the desk, her paws finding the switch. Whiskers had been sitting by the window. "
       "She had heard the lamp go out.")
CH2 = ("The wind howled. Inside, the lighthouse keeper, Thomas, lay curled on the floor. "
       "Whiskers climbed the spiral staircase with steady paws, his fur dusted with sea salt.")


class TestTheStorysOwnWords(unittest.TestCase):
    """The lighthouse story through Nemo's model, 2026-11-06: 1,012 words for
    "About 600 words", the keeper renamed, the cat she then he."""

    def test_its_length_is_shared_among_the_chapters(self):
        self.assertEqual(S.asked_words(LIGHTHOUSE), 600)
        self.assertEqual(S.asked_words("a 1,500-word story"), 1500)
        self.assertIsNone(S.asked_words("a story about 3 foxes"))
        self.assertEqual(S.chapter_words(LIGHTHOUSE, 3), 200)
        self.assertEqual(S.chapter_words("a fable, 100 words", 3), S.MIN_WORDS)
        self.assertEqual(S.chapter_words("a fable", 3), S.WORDS)

    def test_the_chapters_are_asked_for_that_length(self):
        f = story(LIGHTHOUSE)
        m = Model([outline(3)], [prose("a", 200), prose("b", 200), prose("c", 200)])
        self.assertTrue(S.write_story(f, m, say=lambda s: None))
        self.assertIn("about 200 words", m.written()[0]["system"])

    def test_names_and_who_is_he_or_she(self):
        self.assertEqual(S.names(CH1), {"Mr. Grady", "Whiskers"})
        self.assertEqual(S.pronouns(CH1), {"Whiskers": "she"})
        self.assertEqual(S.pronouns(CH2, {"Whiskers"}), {"Whiskers": "he"})

    def test_the_editor_sends_back_a_renamed_or_regendered_chapter(self):
        self.assertIn("Thomas, where earlier chapters said Mr. Grady",
                      S.renamed(CH2, S.names(CH1), set())[0])
        self.assertEqual(S.renamed(CH1, S.names(CH1), set()), [])
        self.assertIn("Whiskers he, where earlier chapters said she",
                      S.regendered(CH2, {"Whiskers": "she"}, {"Whiskers"})[0])

    def test_later_chapters_are_told_the_names_and_a_renaming_goes_back(self):
        f = story(LIGHTHOUSE)
        m = Model([outline(3)], [CH1 + " " + prose("a", 200), CH2 + " " + prose("b", 200),
                                 CH1 + " " + prose("b", 200), prose("c", 200)])
        S.write_story(f, m, say=lambda s: None)
        users = [a["user"] for a in m.written()]
        self.assertIn("Mr. Grady (he)" if "Mr. Grady" in S.pronouns(CH1) else "Mr. Grady", users[1])
        self.assertIn("Whiskers (she)", users[1])
        self.assertIn("the story's people keep their names", users[2])   # chapter 2 again
        self.assertIn("Whiskers he, where earlier chapters said she", users[2])

    def test_its_folder_name_keeps_an_apostrophe_word_whole(self):
        self.assertEqual(L.name_for(LIGHTHOUSE), "children lighthouse keepers cat")


# Two chapters of the lighthouse story through Nemo's model (2026-11-06):
# both open with the same line.
OPEN1 = ("The wind howled like a wounded beast, tearing at the lighthouse's wooden walls. "
         "Rain lashed the windows. Inside, the keeper coughed.")
OPEN2 = ("The wind howled like a wounded beast, tearing at the lighthouse's stone walls as "
         "the keeper staggered toward the door.")


class TestTheCanon(unittest.TestCase):
    """2026-11-08, after Claude Code Game Studios' world-builder: what the story
    has established is kept, and each chapter is checked against it. In the
    lighthouse story the first chapter relit the lamp, the second chapter's
    event, and every chapter opened "The wind howled like a wounded beast"."""

    def test_a_line_from_an_earlier_chapter_is_a_repeat(self):
        faults = S.repeated(OPEN2, [OPEN1])
        self.assertEqual(len(faults), 1)
        self.assertIn("'the wind howled like a wounded beast tearing at the lighthouse's' "
                      "(chapter 1)", faults[0])
        self.assertEqual(S.repeated("The sea was calm and the cat slept by the warm fire.",
                                    [OPEN1]), [])
        # The request's or plan's own words are not a repeat.
        self.assertEqual(S.repeated(OPEN2, [OPEN1], allowed=OPEN1), [])

    def test_a_repeating_chapter_goes_back_without_the_line(self):
        # 2026-11-08: told the line, the 4B wrote it again in 3 of 3 rewrites
        # (mistake 4b). The Writer is told only that, and from where; the log
        # keeps the line for the owner.
        f = story(LIGHTHOUSE)
        m = Model([outline(3)], [OPEN1 + " " + prose("a", 200), OPEN2 + " " + prose("b", 200),
                                 prose("b", 200), prose("c", 200)])
        self.assertTrue(S.write_story(f, m, say=lambda s: None))
        again = m.written()[2]["user"]
        self.assertIn("copies 1 line word for word from chapter 1", again)
        self.assertNotIn("wounded beast", again)
        log = (f / "work.jsonl").read_text(encoding="utf-8")
        self.assertIn("the wind howled like a wounded beast", log)

    def test_the_canon_has_the_plans_names_and_no_article(self):
        # 2026-11-08: Clara only ever began sentences and was left out; "The"
        # of "*The Marigold*" was listed as someone.
        self.assertNotIn("The", S.names("The sisters stood on deck of *The Marigold* at dawn."))
        f = story("A story in three chapters about two sisters and a boat")
        plan = json.dumps({"title": "The Boat", "chapters": [
            {"title": f"Part {i}", "summary": "The two sisters, Clara and Lila, mend the boat."}
            for i in (1, 2, 3)]})
        S.write_story(f, Model([plan], ["Clara and Lila came down. " + prose("a"),
                                        prose("b"), prose("c")]), say=lambda s: None)
        people = json.loads((f / "canon.json").read_text(encoding="utf-8"))["people"]
        self.assertEqual(people["Clara"]["first_chapter"], 1)
        self.assertNotIn("The", people)

    def test_no_chapter_but_the_last_may_end_the_story(self):
        f = story("A short story about a fox")
        m = Model([outline(3)], [prose("a"), prose("b"), prose("c")])
        S.write_story(f, m, say=lambda s: None)
        users = [a["user"] for a in m.written()]
        for u in users[:2]:
            self.assertIn("does not end the story", u)
            self.assertNotIn("ends the story.", u)
        self.assertNotIn("does not end the story", users[2])
        self.assertNotIn("already told", users[0])

    def test_the_canon_is_kept(self):
        f = story(LIGHTHOUSE)
        m = Model([outline(3)], [CH1 + " " + prose("a", 200), prose("b", 200),
                                 "Later, Captain Marlow came to see Whiskers and Mr. Grady. " + prose("c", 200)])
        S.write_story(f, m, say=lambda s: None)
        canon = json.loads((f / "canon.json").read_text(encoding="utf-8"))
        self.assertEqual(canon["people"]["Whiskers"], {"he_she": "she", "first_chapter": 1})
        self.assertEqual(canon["people"]["Captain. Marlow"]["first_chapter"], 3)
        self.assertEqual([c["chapter"] for c in canon["chapters"]], [1, 2, 3])
        self.assertTrue(canon["chapters"][2]["ended"].endswith(prose("c", 200)[-20:]))
        self.assertIn("Whiskers (she), from chapter 1", (f / "canon.md").read_text(encoding="utf-8"))

    def test_a_plan_line_cut_off_goes_back(self):
        # 2026-11-08: the 4B wrote four sentences per line; the schema's limit
        # cut them mid-word ("Intrigued, shep") and the plan was passed.
        o = S.Outline("The Clockmaker's Secret", [
            {"title": "One", "summary": "Lila finds a clock. Intrigued, shep"},
            {"title": "Two", "summary": "She follows the map."},
            {"title": "Three", "summary": "She says \u201cIt is mine.\u201d"}])
        self.assertEqual(S.review_outline(o, 3),
                         ["chapter 1's line is cut off: give one or two short sentences"])

    def test_an_ending_is_its_last_sentences(self):
        text = "One. Two is here. " + " ".join(["word"] * 50) + ". Three ends. Four ends too."
        self.assertEqual(S.ending(text, most=10), "Three ends. Four ends too.")


class TestThePromptsShowShapesNotExamples(unittest.TestCase):
    """docs/design-rules.md 4b: an example in a prompt comes back as the answer."""

    def test_the_editor_is_told_to_stop_at_its_chapters_end(self):
        from nemo.prompts import load_prompt
        self.assertIn("belongs to the next", load_prompt("staff_story_chapter", words=350))

    def test_placeholders_only(self):
        from nemo.prompts import load_prompt
        o = load_prompt("staff_story_outline", chapters=3)
        self.assertIn("<story title>", o)
        self.assertNotIn("{{", o)
        c = load_prompt("staff_story_chapter", words=350)
        self.assertIn("350", c)


class TestTheCommand(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()

    def tearDown(self):
        self._env.stop(); self.t.cleanup()

    def test_new_list_and_write_without_a_model(self):
        import io
        from contextlib import redirect_stdout
        from nemo import cli
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(["story", "new", "A short story about a fox"])
            cli.main(["story", "list"])
            with mock.patch("nemo.router.Router.local_up", return_value=False):
                rc = cli.main(["story", "write", "fox"])
        self.assertIn("asked for", out.getvalue())
        self.assertEqual(rc, 3)
        self.assertIn("needs the language model", out.getvalue())
