"""The Library's Researcher: facts for stories, from Wikipedia (owner's
choice, 2026-10-21: "Wikipedia online").

Only the search words are sent, to Wikipedia's own search and page-summary
services; never the story or the request. With no connection it says it
cannot look, and nothing else happens. What it finds is kept beside the
story, in research.md, with each page's address, for the owner and the
Writer to read. It is not handed to the model by itself: every word the
model reads costs time here (docs/design-rules.md 4f), and a fact shown to it can come
back as the answer (4b).
"""
from __future__ import annotations

import datetime as _dt
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__

API = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
# Wikimedia asks every program to name itself. No address or name of the
# owner is in it.
AGENT = f"Nemo/{__version__} (local workshop assistant; Library Researcher)"
TIMEOUT = 15


class LookupError_(RuntimeError):
    """Nothing could be looked up; the message says why."""


@dataclass
class Fact:
    title: str
    summary: str
    url: str


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def look_up(words: str, limit: int = 3) -> list[Fact]:
    """Wikipedia's best pages for these words, each with its summary."""
    words = " ".join(words.split())
    if not words:
        raise LookupError_("give some words to look up")
    q = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": words,
                                "srlimit": limit, "format": "json"})
    try:
        hits = _get(f"{API}?{q}").get("query", {}).get("search", [])
        out = []
        for h in hits[:limit]:
            page = _get(SUMMARY + urllib.parse.quote(h["title"].replace(" ", "_"), safe=""))
            url = page.get("content_urls", {}).get("desktop", {}).get("page", "")
            out.append(Fact(page.get("title", h["title"]), page.get("extract", "").strip(), url))
        return out
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LookupError_(f"Wikipedia could not be reached ({exc}); the Researcher needs a "
                           "connection") from None


def keep(folder: Path, words: str, found: list[Fact]) -> Path:
    """Add what was found to the story's research.md."""
    path = Path(folder) / "research.md"
    lines = [f"\n## {words} ({_dt.date.today().isoformat()})\n"]
    for f in found:
        lines.append(f"**{f.title}**: {f.summary}\n<{f.url}>\n")
    if not found:
        lines.append("Nothing found.\n")
    new = not path.exists()
    with path.open("a", encoding="utf-8") as fh:
        if new:
            fh.write("# What the Researcher found (from Wikipedia)\n")
        fh.write("\n".join(lines))
    return path
