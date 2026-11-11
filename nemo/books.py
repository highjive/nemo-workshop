"""A finished story bound as a book, by WordCraft (owner, 2026-11-11:
"continue till final stage"; stage 4 of docs/artcraft-plan.md).

story.md (the title, then "## N. Chapter" and its paragraphs) becomes
book.html by code: the cover the Artist painted (cover.png) on the first
page, then each chapter on a page of its own. wordcraft-cli turns that into
book.docx (to open and change in Word or WordCraft) and book.pdf (A4, to
print). Then a gate reads the DOCX back through WordCraft itself: the title,
every chapter heading in order and every paragraph must be there word for
word, and the PDF must have a page for the cover and for each chapter.

WordCraft (github.com/storytold/wordcraft, MIT OR Apache-2.0) is optional:
where wordcraft-cli is not installed the story is still story.md, as before.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

VERSION = "0.17.0"
# GitHub's own sha256 for each asset (2026-11-11). NemoDoc.ps1 and
# build-iso.sh carry the same; a test holds them together.
SOURCES = {
    "windows": ("wordcraft-0.17.0-windows-x64-portable.zip", 117678204,
                "ad05af39d62504ddb382f93f9b7e2e7e9ce92938d132c18c4fb43e10822108ce"),
    "linux": ("wordcraft-0.17.0-linux-x86_64.tar.gz", 118118832,
              "9c744c0c31a3ce25df82680fc75e645d682846faccbe103f4f91a758b19f3687"),
}
URL = "https://github.com/storytold/wordcraft/releases/download/v{v}/{name}"
HOME_WIN = Path(r"C:\Nemo\tools\wordcraft")
HOME_LINUX = Path("/opt/nemo/wordcraft")
NOT_INSTALLED = ("No book: WordCraft (wordcraft-cli) is not installed here. NemoDoc installs it "
                 "(-SkipBooks leaves it out). The story is in story.md.")


class BookError(RuntimeError):
    """The book could not be made. For the owner."""


def cli() -> Path | None:
    """wordcraft-cli, where NemoDoc (Windows) or build-iso (NemoIso) puts it, or on the PATH."""
    from .platform_probe import find_tool
    if os.environ.get("NEMO_WORDCRAFT", "").lower() == "off":     # the test sandbox
        return None
    for p in (HOME_WIN / "wordcraft-cli.exe", HOME_LINUX / "wordcraft-cli"):
        if p.is_file():
            return p
    hit = find_tool("wordcraft-cli")
    return Path(hit) if hit else None


@dataclass
class Story:
    title: str
    chapters: list[tuple[str, list[str]]]      # (heading as written, its paragraphs)


def _flat(text: str) -> str:
    return " ".join(text.split())


def read_story(text: str) -> Story:
    """story.md as stories.write_story writes it."""
    title, chapters = "", []
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if block.startswith("## "):
            chapters.append((_flat(block[3:]), []))
        elif block.startswith("# ") and not title:
            title = _flat(block[2:])
        elif block and chapters:
            chapters[-1][1].append(_flat(block))
    if not title or not chapters:
        raise BookError("story.md has no title or no chapters to bind")
    return Story(title, chapters)


def book_html(story: Story, cover: str | None = None) -> str:
    """The book as HTML, for WordCraft: the cover page, then a page per chapter."""
    e = html.escape
    out = ['<!doctype html><html><head><meta charset="utf-8">',
           f"<title>{e(story.title)}</title></head><body>", f"<h1>{e(story.title)}</h1>"]
    if cover:
        out.append(f'<p><img src="{e(cover)}" width="440"></p>')
    for heading, paras in story.chapters:
        out.append(f'<h2 style="page-break-before: always">{e(heading)}</h2>')
        out += [f"<p>{e(p)}</p>" for p in paras]
    out.append("</body></html>")
    return "\n".join(out) + "\n"


def _run(exe: Path, args: list[str], timeout: float = 180) -> str:
    try:
        p = subprocess.run([str(exe), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise BookError(f"wordcraft-cli did not finish in {timeout:g} s") from exc
    except OSError as exc:
        raise BookError(f"wordcraft-cli could not be started: {exc}") from exc
    if p.returncode != 0:
        raise BookError("wordcraft-cli stopped: " + ((p.stderr or p.stdout).strip()[-400:]
                                                     or f"exit {p.returncode}"))
    return p.stdout


def check(story: Story, blocks: list[dict], pdf_pages: int, pdf_images: int,
          cover: bool) -> list[str]:
    """The DOCX's blocks (wordcraft-cli inspect) and the PDF against the story."""
    faults = []
    got = [(b.get("style", ""), _flat(b.get("text", ""))) for b in blocks
           if b.get("type") == "paragraph" and _flat(b.get("text", ""))]
    want = [("Heading1", story.title)]
    for heading, paras in story.chapters:
        want.append(("Heading2", heading))
        want += [("Normal", p) for p in paras]
    if got != want:
        missing = [w for w in want if w not in got]
        extra = [g for g in got if g not in want]
        if missing:
            faults.append(f"{len(missing)} of the story's {len(want)} headings and paragraphs are "
                          f"not in book.docx as written, the first: {missing[0][1][:60]!r}")
        if extra:
            faults.append(f"book.docx has {len(extra)} paragraph(s) the story does not, the first: "
                          f"{extra[0][1][:60]!r}")
        if not missing and not extra:
            faults.append("book.docx has the story's paragraphs in another order")
    need = len(story.chapters) + 1
    if pdf_pages < need:
        faults.append(f"book.pdf has {pdf_pages} page(s); a title page and {len(story.chapters)} "
                      f"chapter(s) need at least {need}")
    if cover and pdf_images < 1:
        faults.append("the cover is not in book.pdf")
    return faults


@dataclass
class Bound:
    files: list[Path]
    pages: int
    faults: list[str]

    @property
    def ok(self) -> bool:
        return not self.faults


def bind(folder: Path, exe: Path | None = None) -> Bound | None:
    """Bind folder/story.md as book.docx and book.pdf, and check them. None
    where WordCraft is not installed."""
    exe = exe or cli()
    if exe is None:
        return None
    src = folder / "story.md"
    if not src.is_file():
        raise BookError("there is no story.md yet: write the story first")
    story = read_story(src.read_text(encoding="utf-8", errors="replace"))
    cover = (folder / "cover.png").is_file()
    page = folder / "book.html"
    page.write_text(book_html(story, "cover.png" if cover else None), encoding="utf-8")
    docx, pdf = folder / "book.docx", folder / "book.pdf"
    _run(exe, ["convert", str(page), str(docx)])
    _run(exe, ["convert", str(page), str(pdf)])
    blocks = json.loads(_run(exe, ["inspect", str(docx)])).get("blocks", [])
    try:
        import pypdf
        r = pypdf.PdfReader(str(pdf))
        pages, images = len(r.pages), len(r.pages[0].images) if r.pages else 0
    except Exception as exc:                       # pypdf missing, or a PDF it cannot read
        raise BookError(f"book.pdf could not be read back: {exc}") from exc
    return Bound([docx, pdf], pages, check(story, blocks, pages, images, cover))


def bind_and_say(folder: Path, say=print) -> bool:
    """bind(), said plainly. True when a checked book was made."""
    try:
        b = bind(folder)
    except BookError as exc:
        say(f"No book: {exc}.")
        return False
    if b is None:
        say(NOT_INSTALLED)
        return False
    if not b.ok:
        say("The book does not read back as the story, so it is not offered: " + "; ".join(b.faults))
        return False
    say(f"Bound as a book: book.pdf ({b.pages} pages, A4, to print) and book.docx (to open in Word).")
    return True


def pack_pdf(root: Path, exe: Path | None = None) -> tuple[Path | None, str]:
    """A project's build guide as one PDF to print: BUILD.md by WordCraft,
    then the enclosure's drawing (drawings/housing.pdf, at 1:1) after it,
    joined by pypdf. Checked: every heading of the guide is in the PDF's
    text, and its pages are the guide's and the drawing's. (path or None,
    what to say)."""
    exe = exe or cli()
    guide = root / "BUILD.md"
    if exe is None or not guide.is_file():
        return None, ""
    import pypdf
    part = root / ".pack-guide.pdf"
    out = root / "pack.pdf"
    try:
        _run(exe, ["convert", str(guide), str(part)])
        w = pypdf.PdfWriter()
        r = pypdf.PdfReader(str(part))
        for pg in r.pages:
            w.add_page(pg)
        drawing = root / "enclosure" / "drawings" / "housing.pdf"
        d = pypdf.PdfReader(str(drawing)) if drawing.is_file() else None
        for pg in (d.pages if d else []):
            w.add_page(pg)
        with out.open("wb") as f:
            w.write(f)
        back = pypdf.PdfReader(str(out))
        text = _flat(" ".join(pg.extract_text() or "" for pg in back.pages))
        want_pages = len(r.pages) + (len(d.pages) if d else 0)
    except (BookError, OSError, ValueError) as exc:
        return None, f"No pack PDF: {exc}."
    finally:
        part.unlink(missing_ok=True)
    heads = [_flat(re.sub(r"[`*_]", "", ln.lstrip("#"))) for ln in
             guide.read_text(encoding="utf-8", errors="replace").splitlines() if ln.startswith("## ")]
    lost = [h for h in heads if h not in text]
    if lost or len(back.pages) != want_pages:
        out.unlink(missing_ok=True)
        return None, ("The pack PDF did not read back as the guide, so it is not kept: "
                      + (f"heading {lost[0]!r} is not in it" if lost else
                         f"{len(back.pages)} pages, not {want_pages}"))
    return out, (f"pack.pdf: the build guide and the enclosure drawing in one PDF to print "
                 f"({len(back.pages)} pages)." if d else
                 f"pack.pdf: the build guide as a PDF to print ({len(back.pages)} pages).")
