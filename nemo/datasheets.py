"""A searchable library of datasheets, entirely offline.

PDFs dropped into the datasheets folder are split into pages, their text
extracted with pypdf (pure Python: no external programs, which matters on
Windows), and indexed in SQLite's built-in full-text search. Answers cite the
file and page, so a figure can always be checked against the source.

Three things are reported rather than hidden:

  * A scanned datasheet has no text layer. Nothing in it can be searched,
    and the library says so instead of quietly returning no results.
  * Text extraction is only as good as the PDF's font encoding; garbled
    pages exist, and the page image is the truth.
  * Linking a datasheet to a part is suggested, not assumed. The DFPlayer
    Mini's datasheet is published as the FN-M16P and never mentions
    "DFPlayer", so matching on names would silently miss it.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path


def default_root() -> Path:
    from .config import Config
    return Config.load().path("paths.datasheets")


def db_path() -> Path:
    return Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo")) / "datasheets.sqlite"


@dataclass
class Hit:
    file: str
    page: int
    snippet: str


@dataclass
class Sheet:
    file: str
    pages: int
    status: str        # ok | no text | error
    detail: str
    parts: list[str]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def part_tokens(part) -> set[str]:
    """Distinctive identifiers for a part: its ref, and model numbers in its
    name -- words mixing letters and digits, at least five characters, so
    'MFRC522' and 'MAX98357A' count and 'MP3' does not."""
    toks = {_norm(part.ref)}
    for w in re.findall(r"[A-Za-z0-9-]+", part.name + " " + (part.datasheet or "")):
        n = _norm(w)
        if len(n) >= 5 and re.search(r"\d", n) and re.search(r"[a-z]", n):
            toks.add(n)
    return {t for t in toks if t}


class Library:
    def __init__(self, root: Path | None = None, db: Path | None = None):
        self.root = Path(root) if root else default_root()
        self.db_file = Path(db) if db else db_path()
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_file)
        self.fts = self._setup()

    # ------------------------------------------------------------ schema
    def _setup(self) -> bool:
        c = self.db
        c.execute("create table if not exists files (file text primary key, "
                  "digest text, pages int, status text, detail text)")
        c.execute("create table if not exists links (file text, ref text, "
                  "primary key (file, ref))")
        try:
            c.execute("create virtual table if not exists pages using "
                      "fts5(file unindexed, page unindexed, text)")
            fts = True
        except sqlite3.OperationalError:
            # A Python built without FTS5 still works, just more slowly.
            c.execute("create table if not exists pages (file text, "
                      "page int, text text)")
            fts = False
        c.commit()
        return fts

    def close(self):
        self.db.close()

    # D114: callers that never closed left the file locked on Windows.
    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ adding
    def add(self, paths) -> list[str]:
        """Copy PDFs into the library folder, then index them."""
        self.root.mkdir(parents=True, exist_ok=True)
        added = []
        for p in map(Path, paths):
            if p.suffix.lower() != ".pdf" or not p.is_file():
                continue
            dest = self.root / p.name
            if p.resolve() != dest.resolve():
                shutil.copy2(p, dest)
            added.append(dest.name)
        self.index()
        return added

    @staticmethod
    def _digest(p: Path) -> str:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def index(self) -> dict:
        """Index new or changed PDFs; forget removed ones. Returns counts."""
        from pypdf import PdfReader
        counts = {"indexed": 0, "unchanged": 0, "removed": 0, "problems": 0}
        present = {p.name: p for p in sorted(self.root.glob("*.pdf"))} \
            if self.root.exists() else {}
        known = {f: d for f, d in self.db.execute("select file, digest from files")}
        for gone in set(known) - set(present):
            self.db.execute("delete from files where file = ?", (gone,))
            self.db.execute("delete from pages where file = ?", (gone,))
            self.db.execute("delete from links where file = ?", (gone,))
            counts["removed"] += 1
        for name, path in present.items():
            digest = self._digest(path)
            if known.get(name) == digest:
                counts["unchanged"] += 1
                continue
            self.db.execute("delete from pages where file = ?", (name,))
            try:
                reader = PdfReader(str(path))
                if reader.is_encrypted:
                    reader.decrypt("")
                texts = [(pg.extract_text() or "") for pg in reader.pages]
            except Exception as exc:                       # noqa: BLE001
                self.db.execute("insert or replace into files values (?,?,?,?,?)",
                                (name, digest, 0, "error", f"could not read: {exc}"))
                counts["problems"] += 1
                continue
            total = sum(len(t.strip()) for t in texts)
            # A scan yields next to nothing: under 20 characters a page.
            if total < 20 * max(1, len(texts)):
                status, detail = "no text", ("no text layer -- probably a "
                                             "scanned document, so nothing "
                                             "in it can be searched")
                counts["problems"] += 1
            else:
                status, detail = "ok", ""
            for i, t in enumerate(texts, 1):
                if t.strip():
                    self.db.execute("insert into pages (file, page, text) "
                                    "values (?,?,?)", (name, i, t))
            self.db.execute("insert or replace into files values (?,?,?,?,?)",
                            (name, digest, len(texts), status, detail))
            counts["indexed"] += 1
        self.db.commit()
        return counts

    # ------------------------------------------------------------ linking
    def suggest_parts(self, file: str, library) -> list[str]:
        """Parts this datasheet is probably for, from filename and first page.
        A suggestion only: nothing is linked until confirmed."""
        first = self.db.execute("select text from pages where file = ? "
                                "order by page limit 1", (file,)).fetchone()
        hay = _norm(file) + " " + _norm(first[0] if first else "")
        return [p.ref for p in library if any(t in hay for t in part_tokens(p))]

    def link(self, file: str, ref: str) -> None:
        self.db.execute("insert or ignore into links values (?, ?)", (file, ref))
        self.db.commit()

    def unlink(self, file: str, ref: str) -> None:
        self.db.execute("delete from links where file = ? and ref = ?", (file, ref))
        self.db.commit()

    def files_for(self, ref: str) -> list[str]:
        return [f for (f,) in self.db.execute(
            "select file from links where ref = ? order by file", (ref,))]

    def sheets(self) -> list[Sheet]:
        out = []
        for f, pages, status, detail in self.db.execute(
                "select file, pages, status, detail from files order by file"):
            refs = [r for (r,) in self.db.execute(
                "select ref from links where file = ? order by ref", (f,))]
            out.append(Sheet(f, pages, status, detail, refs))
        return out

    # ------------------------------------------------------------ search
    @staticmethod
    def _terms(query: str) -> list[str]:
        return [w for w in re.findall(r"[A-Za-z0-9.+-]+", query) if w]

    def search(self, query: str, ref: str | None = None,
               limit: int = 25) -> list[Hit]:
        terms = self._terms(query)
        if not terms:
            return []
        files = self.files_for(ref) if ref else None
        if ref and not files:
            return []
        hits: list[Hit] = []
        if self.fts:
            # Each term quoted, so FTS5 operators typed by accident -- a
            # hyphen, a colon -- are searched for rather than parsed.
            match = " ".join('"' + t.replace('"', "") + '"' for t in terms)
            sql = ("select file, page, snippet(pages, 2, '[', ']', ' ... ', 40) "
                   "from pages where pages match ?")
            args: list = [match]
            if files:
                sql += f" and file in ({','.join('?' * len(files))})"
                args += files
            sql += " order by rank limit ?"
            args.append(limit)
            try:
                rows = self.db.execute(sql, args).fetchall()
            except sqlite3.OperationalError:
                rows = []
            hits = [Hit(f, int(p), " ".join(s.split())) for f, p, s in rows]
        else:
            rows = self.db.execute("select file, page, text from pages").fetchall()
            for f, p, text in rows:
                if files and f not in files:
                    continue
                low = text.lower()
                if all(t.lower() in low for t in terms):
                    i = low.find(terms[0].lower())
                    snip = " ".join(text[max(0, i - 80): i + 120].split())
                    hits.append(Hit(f, int(p), snip))
                if len(hits) >= limit:
                    break
        return hits
