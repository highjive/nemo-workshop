"""Help that works offline: the installed documents, readable in the window."""

from __future__ import annotations

import re
from pathlib import Path

# (title, path relative to the distribution folder)
DOCS = [
    ("Using Nemo", "docs/user-guide.md"),
    ("Keeping it secure", "docs/security.md"),
    ("Boot and disk protection", "docs/hardening.md"),
    ("Master authority and clones", "docs/master-authority.md"),
]
REPORT = "docs/nemoiso-report.html"


def root() -> Path:
    return Path(__file__).resolve().parent.parent


def available() -> list[tuple[str, Path]]:
    r = root()
    return [(t, r / p) for t, p in DOCS if (r / p).exists()]


def report() -> Path | None:
    p = root() / REPORT
    return p if p.exists() else None


def segments(markdown: str) -> list[tuple[str, str]]:
    """Markdown -> (text, style) runs a text widget can show.

    Deliberately small: headings, code blocks, tables and bullets. Anything
    else is shown as it is written, which for these documents reads fine.
    """
    out: list[tuple[str, str]] = []
    in_code = False
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append((line + "\n", "code")); continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            out.append(("\n" + m.group(2) + "\n", f"h{len(m.group(1))}")); continue
        if line.startswith("|"):
            if re.match(r"^\|[\s|:-]+\|?$", line):
                continue                      # the |---| separator row
            cells = [c.strip() for c in line.strip("|").split("|")]
            out.append(("   ".join(cells) + "\n", "code")); continue
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        if re.match(r"^\s*[-*]\s+", text):
            out.append(("  \u2022 " + re.sub(r"^\s*[-*]\s+", "", text) + "\n", "body"))
        else:
            out.append((text + "\n", "body"))
    return out
