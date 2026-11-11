"""Find and replace in a piece of text, as Windows Notepad 11 does it
(owner, 2026-10-28: "understand how search works in the Notes app ... and
build a similar feature"; he chose Notepad).

What Notepad 11.2607.14.0 was seen to have, statically, from its shipped
files (nothing was run): its find bar's settings are FindString,
ReplaceString, IsMatchCase, IsWrapAround and IsReverseFind, and one action,
ExecuteMethod Find, Replace or ReplaceAll (NotepadXamlUI.winmd); its words
are "Find next", "Find previous", "Match case", "Wrap around", "Search up",
"Search down", "Replace all" and the message Cannot find "%%"
(resources.pri). Notepad.exe imports FindNLSString, Windows' locale-aware
substring search, which is the likely engine; that it is the one used for
Find was not confirmed by reading its code. No whole-word or regular
expression option was found in the find bar's settings.

So here: plain text (no patterns), case matched or not, forwards or back
from where the cursor is, wrapping round the ends or stopping there.
Replace replaces the found text when it is what is selected, then finds the
next; Replace all replaces every match in the text and says how many.
"""
from __future__ import annotations


def _norm(s: str, match_case: bool) -> str:
    """Lower case, one character for one, so offsets in it are offsets in s
    (some letters lower into two, such as the dotted capital I)."""
    if match_case:
        return s
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in s)


def find(text: str, query: str, pos: int, *, match_case: bool = False, reverse: bool = False,
         wrap: bool = True) -> tuple[int, int] | None:
    """The next match of `query` in `text` from character offset `pos`
    (forwards: at or after pos; reverse: ending at or before pos), as
    (start, end); None when there is none, or none before the end and
    `wrap` is off."""
    if not query:
        return None
    hay, needle = _norm(text, match_case), _norm(query, match_case)
    pos = max(0, min(pos, len(text)))
    if reverse:
        i = hay.rfind(needle, 0, pos)
        if i < 0 and wrap:
            i = hay.rfind(needle)
    else:
        i = hay.find(needle, pos)
        if i < 0 and wrap:
            i = hay.find(needle)
    return None if i < 0 else (i, i + len(query))


def count(text: str, query: str, *, match_case: bool = False) -> int:
    """How many times `query` is in `text`, not overlapping."""
    if not query:
        return 0
    return _norm(text, match_case).count(_norm(query, match_case))


def replace_all(text: str, query: str, replacement: str, *,
                match_case: bool = False) -> tuple[str, int]:
    """Every match of `query` replaced, left to right, not overlapping;
    returns the new text and how many were replaced."""
    if not query:
        return text, 0
    hay, needle = _norm(text, match_case), _norm(query, match_case)
    out, i, n = [], 0, 0
    while True:
        j = hay.find(needle, i)
        if j < 0:
            break
        out += [text[i:j], replacement]
        i, n = j + len(query), n + 1
    out.append(text[i:])
    return "".join(out), n


def cannot_find(query: str) -> str:
    """Notepad's own words when nothing matches."""
    return f'Cannot find "{query}"'
