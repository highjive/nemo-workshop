"""Books and the pack PDF by WordCraft (owner, 2026-11-11: "continue till final stage";
stage 4 of docs/artcraft-plan.md). A finished story bound as book.docx and book.pdf,
read back through WordCraft; a project's guide and drawing as pack.pdf. Real ones are
made where wordcraft-cli is installed (the desktop)."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import books as B, toolupdates

APP = Path(__file__).resolve().parent.parent

STORY = """# The Keeper's Cat

## 1. The Stormy Night

The storm hit the village.
It was "very" loud & wet.

Luna watched <from> the window.

## 2. Luna's Courage

Luna climbed the stairs.
"""


class TestTheBook(unittest.TestCase):
    def test_the_story_read_as_written(self):
        s = B.read_story(STORY)
        self.assertEqual(s.title, "The Keeper's Cat")
        self.assertEqual([c[0] for c in s.chapters], ["1. The Stormy Night", "2. Luna's Courage"])
        self.assertEqual(s.chapters[0][1], ['The storm hit the village. It was "very" loud & wet.',
                                            "Luna watched <from> the window."])
        with self.assertRaises(B.BookError):
            B.read_story("just words")

    def test_a_cover_page_then_a_page_a_chapter_and_nothing_unescaped(self):
        h = B.book_html(B.read_story(STORY), "cover.png")
        self.assertIn('<img src="cover.png"', h)
        self.assertEqual(h.count('style="page-break-before: always"'), 2)
        self.assertIn("&lt;from&gt;", h)
        self.assertIn("&amp; wet", h)
        self.assertNotIn("<img", B.book_html(B.read_story(STORY)))

    def blocks(self, drop=None):
        s = B.read_story(STORY)
        out = [{"type": "paragraph", "style": "Heading1", "text": s.title}]
        for head, paras in s.chapters:
            out.append({"type": "paragraph", "style": "Heading2", "text": head})
            out += [{"type": "paragraph", "style": "Normal", "text": p} for p in paras]
        out.append({"type": "paragraph", "style": "Normal", "text": ""})   # an empty one is ignored
        return [b for b in out if b["text"] != drop]

    def test_the_gate(self):
        s = B.read_story(STORY)
        self.assertEqual(B.check(s, self.blocks(), 3, 1, cover=True), [])
        self.assertIn("not in book.docx as written",
                      B.check(s, self.blocks(drop="Luna climbed the stairs."), 3, 1, True)[0])
        self.assertIn("need at least 3", B.check(s, self.blocks(), 2, 1, True)[0])
        self.assertIn("cover is not in book.pdf", B.check(s, self.blocks(), 3, 0, True)[0])

    def test_not_installed_is_said_and_the_story_stays(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "story.md").write_text(STORY, encoding="utf-8")
            self.assertIsNone(B.bind(Path(d)))                 # the sandbox turns it off
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertFalse(B.bind_and_say(Path(d)))
            self.assertIn("The story is in story.md", out.getvalue())
            self.assertEqual(B.pack_pdf(Path(d)), (None, ""))


class TestItsPlaceInNemo(unittest.TestCase):
    def test_the_story_command_binds_and_the_pack_step_makes_its_pdf(self):
        cli = (APP / "nemo" / "cli.py").read_text(encoding="utf-8")
        self.assertIn('choices=["list", "new", "write", "cover", "book"]', cli)
        self.assertIn("books.bind_and_say(folder", cli)
        self.assertIn("pdf, said = books.pack_pdf(self.p.root)",
                      (APP / "nemo" / "pipeline.py").read_text(encoding="utf-8"))

    def test_pinned_alike_in_nemodoc_the_image_and_the_doctors_look(self):
        doc = (APP / "NemoDoc.ps1").read_text(encoding="utf-8-sig")
        name, size, sha = B.SOURCES["windows"]
        self.assertIn(f'file = "{name}"; sha256 = "{sha}"; bytes = {size}', doc)
        self.assertIn(B.URL.format(v=B.VERSION, name=name), doc)
        self.assertIn("[switch]$SkipBooks", doc)
        iso = (APP / "install" / "live-build" / "build-iso.sh").read_text(encoding="utf-8")
        self.assertIn(f"WC_V={B.VERSION}", iso)
        self.assertIn(f"WC_SHA={B.SOURCES['linux'][2]}", iso)
        self.assertEqual(B.HOME_LINUX, Path("/opt/nemo/wordcraft"))
        self.assertIn('"$PREFIX/wordcraft/wordcraft-cli" --version',
                      (APP / "install" / "linux" / "nemodoc").read_text(encoding="utf-8"))
        tool = next(t for t in toolupdates.TOOLS if t.key == "wordcraft")
        self.assertEqual((tool.feed, tool.ours()), ("github:storytold/wordcraft", B.VERSION))


def _installed() -> Path | None:
    with mock.patch.dict(os.environ, {"NEMO_WORDCRAFT": "on"}):
        return B.cli()


@unittest.skipUnless(_installed(), "wordcraft-cli is not installed here")
class TestARealBook(unittest.TestCase):
    """Bound by wordcraft-cli 0.17.0 and read back (the desktop, 2026-11-11)."""

    def test_bound_and_read_back(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"NEMO_WORDCRAFT": "on"}):
            (Path(d) / "story.md").write_text(STORY, encoding="utf-8")
            b = B.bind(Path(d))
            self.assertTrue(b.ok, b.faults)
            self.assertEqual(b.pages, 3)                       # title page and two chapters
            for f in b.files:
                self.assertGreater(f.stat().st_size, 1000)

    def test_the_pack_pdf(self):
        import pypdf
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"NEMO_WORDCRAFT": "on"}):
            root = Path(d)
            (root / "BUILD.md").write_text("# Desk weather\n\n## Parts\n\n- bme280\n\n## Open questions\n\n"
                                           "- None recorded.\n", encoding="utf-8")
            drawing = root / "enclosure" / "drawings"
            drawing.mkdir(parents=True)
            w = pypdf.PdfWriter()
            w.add_blank_page(842, 595)
            with (drawing / "housing.pdf").open("wb") as f:
                w.write(f)
            pdf, said = B.pack_pdf(root)
            self.assertIsNotNone(pdf, said)
            self.assertIn("the build guide and the enclosure drawing", said)
            self.assertEqual(len(pypdf.PdfReader(str(pdf)).pages), 2)
            self.assertFalse((root / ".pack-guide.pdf").exists())


if __name__ == "__main__":
    unittest.main()
