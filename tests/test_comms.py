"""Communications (owner, 2026-10-22): the web, letters, email and social
media. Nemo drafts, opens and copies; it never sends, posts or logs in.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import comms, staff


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.root))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))
        self._spell = mock.patch.object(comms, "spell", return_value=[])
        self._spell.start()

    def tearDown(self):
        self._spell.stop(); self._env.stop()
        self.t.cleanup()


class TestTheBrowser(AHome):
    def test_bookmarks_are_kept_and_opened(self):
        comms.add_bookmark(self.cfg, "Club", "example.org/club")
        comms.add_bookmark(self.cfg, "Pictures", "https://photos.example.com", "social")
        self.assertEqual([(b.name, b.url, b.kind) for b in comms.bookmarks(self.cfg)],
                         [("Club", "https://example.org/club", "web"),
                          ("Pictures", "https://photos.example.com", "social")])
        opened = []
        self.assertEqual(comms.open_web("club", self.cfg, opener=lambda u: opened.append(u) or "chrome"),
                         "chrome")
        self.assertEqual(opened, ["https://example.org/club"])
        self.assertTrue(comms.remove_bookmark(self.cfg, "Club"))

    def test_what_is_not_a_web_address(self):
        for bad in ("", "not a site", "http://"):
            with self.assertRaises(comms.CommsError, msg=bad):
                comms.add_bookmark(self.cfg, "x", bad)
        with self.assertRaises(comms.CommsError):
            comms.add_bookmark(self.cfg, "x", "example.org", "spam")


class TestThePostman(AHome):
    def test_the_mail_program_opens_with_the_draft_and_nothing_is_sent(self):
        comms.add_contact(self.cfg, "Ann Smith", "ann@example.org")
        d = comms.save_draft(self.cfg, comms.Draft("email", "Ann Smith", "The lamp", "It works & glows."))
        links = []
        said = comms.send_by_mail_program(self.cfg, d, starter=links.append)
        self.assertIn("press Send", said)
        parts = urllib.parse.urlsplit(links[0])
        self.assertEqual((parts.scheme, parts.path), ("mailto", "ann@example.org"))
        q = urllib.parse.parse_qs(parts.query)
        self.assertEqual((q["subject"], q["body"]), (["The lamp"], ["It works & glows."]))
        self.assertTrue(d.path.is_file())

    def test_a_long_draft_is_pasted_not_put_in_the_link(self):
        comms.add_contact(self.cfg, "Ann", "ann@example.org")
        d = comms.Draft("email", "Ann", "Long", "word " * 1000)
        links = []
        self.assertIn("paste the text", comms.send_by_mail_program(self.cfg, d, starter=links.append))
        self.assertNotIn("body=word", links[0])

    def test_what_cannot_be_sent(self):
        comms.add_contact(self.cfg, "Bob")                         # no address
        with self.assertRaises(comms.CommsError):
            comms.send_by_mail_program(self.cfg, comms.Draft("email", "Bob", "", "hi"), starter=print)
        with self.assertRaises(comms.CommsError):
            comms.add_contact(self.cfg, "Eve", "not-an-address")
        with self.assertRaises(comms.CommsError):
            comms.save_draft(self.cfg, comms.Draft("email", "Bob", "", "  "))


class TestTheWriter(AHome):
    def test_a_letter_laid_out_in_british_style(self):
        comms.add_contact(self.cfg, "Ann Smith", address="1 High Street\nTownsville")
        text = comms.letter(self.cfg, "Ann Smith", "Thank you for the parts.", "Highjive", when="22 October 2026")
        self.assertEqual(text.splitlines()[:6],
                         ["22 October 2026", "", "Ann Smith", "1 High Street", "Townsville", ""])
        self.assertIn("Dear Ann,", text)
        self.assertIn("Yours sincerely,", text)
        self.assertTrue(text.rstrip().endswith("Highjive"))
        to_nobody = comms.letter(self.cfg, "", "To whom it may concern.", when="1 May 2026")
        self.assertIn("Dear Sir or Madam,", to_nobody)
        self.assertIn("Yours faithfully,", to_nobody)

    def test_a_letter_to_a_firm_has_no_first_name(self):
        # 2026-11-06: "Sample Garden Centre" was greeted "Dear Sample,".
        text = comms.letter(self.cfg, "Sample Garden Centre", "Where is my order?", "A. Owner",
                            when="6 November 2026")
        self.assertIn("Dear Sir or Madam,", text)
        self.assertIn("Yours faithfully,", text)
        self.assertNotIn("Dear Sample", text)
        for firm in ("Example Ltd", "Customer Services", "the Council"):
            self.assertTrue(comms.organisation(firm), firm)
        for person in ("Ann Smith", "Jo Example", "Dr Lee"):
            self.assertFalse(comms.organisation(person), person)

    def test_an_initial_is_not_a_misspelling(self):
        # 2026-11-06: the sender "A. Owner" was flagged ("Did you mean to spell `A.`").
        self._spell.stop()
        try:
            lints = [mock.Mock(matched="A.", message="Did you mean to spell `A.` this way?",
                               suggestions=["A"]),
                     mock.Mock(matched="teh", message="Did you mean the?", suggestions=["the"])]
            with mock.patch("nemo.writer.check", return_value=lints):
                self.assertEqual(comms.spell("teh lamp\n\nA. Owner"),
                                 ['"teh": Did you mean the? (perhaps the)'])
        finally:
            self._spell.start()

    def test_spelling_says_when_it_was_not_checked(self):
        self._spell.stop()
        try:
            with mock.patch("nemo.writer.check", return_value=None):
                self.assertIn("not checked", comms.spell("teh lamp")[0])
            lint = mock.Mock(matched="teh", message="Did you mean the?", suggestions=["the"])
            with mock.patch("nemo.writer.check", return_value=[lint]):
                self.assertEqual(comms.spell("teh lamp"), ['"teh": Did you mean the? (perhaps the)'])
        finally:
            self._spell.start()

    def test_the_team(self):
        self.assertEqual([e.title for e in staff.team("comms")], ["Browser", "Postman", "Social", "Writer"])


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheLetterSamples(AHome):
    """Samples, 2026-11-08: a letter to "Mrs Ada Fenwick" began "Dear Mrs,", and
    her own name, town and postcode were called misspellings."""

    def test_a_title_takes_the_surname(self):
        self.assertEqual(comms.greeting("Mrs Ada Fenwick"), "Mrs Fenwick")
        self.assertEqual(comms.greeting("Dr. Owen Price"), "Dr. Price")
        self.assertEqual(comms.greeting("Ada Fenwick"), "Ada")
        self.assertEqual(comms.greeting("Miss"), "Miss")
        comms.add_contact(self.cfg, "Mrs Ada Fenwick", address="4 Lock Lane\nTetbury\nGL8 0AA")
        text = comms.letter(self.cfg, "Mrs Ada Fenwick", "Thank you.", "Highjive", when="8 November 2026")
        self.assertIn("Dear Mrs Fenwick,", text)
        self.assertIn("Yours sincerely,", text)

    def test_the_contacts_own_words_are_known(self):
        self._spell.stop()
        comms.add_contact(self.cfg, "Mrs Ada Fenwick", address="4 Lock Lane\nTetbury\nGL8 0AA")
        seen = []
        with mock.patch("nemo.writer.check", side_effect=lambda text, words=(), cfg=None:
                        seen.append(list(words)) or []):
            comms.save_draft(self.cfg, comms.Draft("letter", "Mrs Ada Fenwick", "Boat", "Thank you."))
        self._spell.start()
        for w in ("Fenwick", "Tetbury", "GL8"):
            self.assertIn(w, seen[0])


class TestTheWindow(AHome):
    def test_letter_mail_and_post(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        app = A.NemoApp(); app.update()
        try:
            app.cfg = self.cfg
            w = A.CommsRoom(app); app.update()
            answers = iter(["Ann Smith", "ann@example.org"])
            w.add_contact(ask=lambda *a: next(answers))
            self.assertEqual(w.to.get(), "Ann Smith")
            w.subject.insert(0, "Hello")
            w.body.insert("1.0", "The lamp works.")
            links = []
            self.assertIn("press Send", w.mail(starter=links.append))
            self.assertTrue(links[0].startswith("mailto:ann@example.org?"))
            self.assertEqual(app.clipboard_get(), "The lamp works.")
            w.make_letter()
            self.assertIn("Dear Ann,", w.body.get("1.0", "end"))
            w.copy_post()
            self.assertIn("Nemo does not post", w.note.cget("text"))
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
