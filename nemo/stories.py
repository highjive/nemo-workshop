"""Stories written by the Library's employees (owner's redesign, 2026-10-17;
the Library, 2026-10-21).

A story is a folder under paths.stories (on the stick, NemoData keeps it),
started from the prompt window with the request in request.md. Then:

  Writer    plans it: a title, and a title and a line for each chapter,
            held to a schema. Code decides how many chapters; the model
            only fills them (docs/design-rules.md 4d).
  Editor    checks the plan in code: the right number, none empty, none
            repeated, nothing from the prompt's own shape.
  Writer    writes one chapter at a time (the Editor's job until
            2026-10-21). It is shown the request, the story's title and
            THIS chapter's line only: shown the whole plan, the model wrote
            its neighbours instead (D168). It then spell-checks the chapter
            (Harper, nemo/writer.py) and corrects only what cannot change a
            meaning: a doubled word, two swapped letters, a doubled letter.
  Editor    reviews each chapter in code: not empty, near the length asked,
            not the previous chapter again, no notes to the reader, not
            full of spelling or grammar the Writer could not settle, and
            (2026-11-06) the same names, and he or she, as earlier chapters,
            which each later chapter is told; (2026-11-08) no line of
            seven words or more taken from an earlier chapter. A length in the request
            ("about 600 words") is shared among the chapters. A
            chapter that fails goes back to the Writer once, with the
            reason; if it fails again it is kept and the reason recorded.

The model is asked nothing by the Editor: reading costs
minutes here.
The CANON (2026-11-08, after Claude Code Game Studios' world-builder: a
record of what is established, every new piece checked against it). canon.json
and canon.md hold each person's name, he or she and the chapter that first
named them, and each chapter's line and the words it ended on. A chapter is
told the PLAN's line for the chapter before it, as already told (never that
chapter's own words: quoted its last sentences, the model wrote them again,
mistake 4b) and, unless it is the last, that it does not end the story: the
request tells the whole plot, and the first chapter of a sample told all of it.

Everything lands in the folder: outline.md, chapters/NN-*.md, story.md,
canon.json, canon.md and work.jsonl, the log of who did what.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .prompts import load_prompt

TASK = "story"            # routed to the local model only, reasoning off
WORDS = 350               # per chapter: a few minutes each on the AH531
MAX_CHAPTERS = 12


def chapter_count(request: str) -> int:
    """How many chapters, from the request's own words."""
    t = request.lower()
    m = re.search(r"\b(\d{1,2})\s+chapters?\b", t)
    if m:
        return max(1, min(MAX_CHAPTERS, int(m.group(1))))
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
    m = re.search(r"\b(" + "|".join(words) + r")\s+chapters?\b", t)
    if m:
        return words[m.group(1)]
    if re.search(r"\bnovel\b", t):
        return 10
    if re.search(r"\bnovella\b", t):
        return 6
    if re.search(r"\b(short story|bedtime story|fable|tale)\b", t):
        return 3
    return 5


MIN_WORDS = 120           # per chapter, however short the story asked for


def asked_words(request: str) -> int | None:
    """The whole story's length, where the request gives one ("about 600
    words", "a 1,500-word story"); None where it does not."""
    m = re.search(r"\b(\d{1,3}(?:,\d{3})+|\d{2,6})\s*-?\s*words?\b", request.lower())
    return int(m.group(1).replace(",", "")) if m else None


def chapter_words(request: str, n: int, default: int = WORDS) -> int:
    """Words per chapter: the request's own length shared among its chapters
    (2026-11-06: "About 600 words" in 3 chapters was written at 350 each,
    1,012 in all), else the default."""
    total = asked_words(request)
    return max(MIN_WORDS, round(total / n)) if total else default


# A capitalised word that is not the first of a sentence, a title and its
# name, or a word in quotes: the story's people and places, as code can see
# them. Common capitalised words are not names.
_NOT_NAMES = {"i", "i'm", "i'd", "i'll", "i've", "god", "the", "and", "but", "then", "when",
              "this", "that", "there", "their", "they", "she", "her", "his", "him", "its", "monday", "tuesday", "wednesday",
              "thursday", "friday", "saturday", "sunday", "january", "february", "march",
              "april", "may", "june", "july", "august", "september", "october",
              "november", "december", "english", "christmas", "ok", "oh", "tv"}


def names(text: str) -> set[str]:
    """The names a text uses (not the first word of a sentence, unless it
    is a title such as Mr.)."""
    found = set()
    for m in re.finditer(r"\b(?:(Mr|Mrs|Ms|Miss|Dr|Captain|Aunt|Uncle)\.?\s+)?([A-Z][a-z]{2,})\b",
                         text):
        title, word = m.group(1), m.group(2)
        before = text[:m.start()].rstrip(" \t*_")
        start = not before or before[-1] in ".!?\n\"\u201c:\u2014" or before.endswith("##")
        if word.lower() in _NOT_NAMES or (start and not title):
            continue
        found.add(f"{title}. {word}" if title else word)
    return found


def pronouns(text: str, known: set[str] = frozenset()) -> dict[str, str]:
    """he or she for each name, where the text says: a sentence that begins
    with the name, followed by one that begins He or She (2026-11-06: the
    cat was "she" in chapter 1 and "he" in chapter 2). Where both are seen,
    or neither, the name has none. known: the names already known (a name
    that only ever begins a sentence is not seen as one by names())."""
    seen: dict[str, set[str]] = {}
    known = set(known) | names(text)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for a, b in zip(sentences, sentences[1:] + [""]):
        a = a.lstrip("\"“ ")
        subject = [n for n in known if a.startswith(n) or a.startswith(n.split()[-1])]
        if not subject or len([n for n in known if n.split()[-1] in a]) > 1:
            continue                          # not about one named person
        # Its own pronoun ("Whiskers leaped, her paws ..."), else the next
        # sentence's subject ("Whiskers sat. She had heard ...").
        m = re.search(r"\b(he|his|him|she|her|hers)\b", a, re.I)
        if m:
            p = "she" if m.group(1).lower() in ("she", "her", "hers") else "he"
        else:
            b = b.lstrip("\"“ ")
            p = "he" if re.match(r"He\b", b) else "she" if re.match(r"She\b", b) else ""
        if p:
            seen.setdefault(subject[0], set()).add(p)
    return {n: next(iter(ps)) for n, ps in seen.items() if len(ps) == 1}


def regendered(text: str, gender: dict[str, str], known: set[str]) -> list[str]:
    """The Editor's he-or-she check: a chapter that calls someone otherwise
    than earlier chapters did (2026-11-06: the cat, "she" in chapter 1, was
    "he" in chapters 2 and 3)."""
    now = pronouns(text, known)
    changed = [f"{n} {now[n]}, where earlier chapters said {gender[n]}"
               for n in sorted(now) if n in gender and now[n] != gender[n]]
    return ([f"it calls {'; '.join(changed)}: keep each one as the story began"]
            if changed else [])


def renamed(text: str, earlier: set[str], allowed: set[str]) -> list[str]:
    """The Editor's name check: a chapter that drops every name an earlier
    chapter gave a person and brings in a new one has renamed someone
    (2026-11-06: the keeper was "Mr. Grady" in chapter 1, "Thomas" in 2)."""
    if not earlier:
        return []
    now = names(text)
    new = sorted(now - earlier - allowed)
    gone = sorted(n for n in earlier - now
                  if not any(n.split()[-1] == m.split()[-1] for m in now))
    if new and gone:
        return [f"it calls someone {', '.join(new)}, where earlier chapters said "
                f"{', '.join(gone)}: the story's people keep their names"]
    return []


REPEAT_WORDS = 7          # a line this long, in an earlier chapter, is a repeat


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower().replace("\u2019", "'"))


def repeated(text: str, earlier: list[str], allowed: str = "", quote: bool = True) -> list[str]:
    """The Editor's repeat check: a line of REPEAT_WORDS words or more that an
    earlier chapter already has (2026-11-08: all three chapters of a sample
    opened "The wind howled like a wounded beast"). Words of the request or
    plan (`allowed`) are not repeats. The faults name the lines and chapters;
    quote=False names only the chapters, for the Writer: quoted the line, the
    4B wrote it again in 3 of 3 rewrites (2026-11-08, mistake 4b)."""
    n = REPEAT_WORDS
    mine = _words(text)
    if len(mine) < n:
        return []
    free = {tuple(g) for g in _ngrams(_words(allowed), n)}
    where: dict[tuple, int] = {}
    for k, other in enumerate(earlier, 1):
        for g in _ngrams(_words(other), n):
            where.setdefault(tuple(g), k)
    spans, i = [], 0
    while i <= len(mine) - n:
        g = tuple(mine[i:i + n])
        if g in where and g not in free:
            j = i + 1
            while j <= len(mine) - n and tuple(mine[j:j + n]) in where:
                j += 1
            spans.append((" ".join(mine[i:j + n - 1]), where[g]))
            i = j + n - 1
        else:
            i += 1
    if not spans:
        return []
    lines = f"{len(spans)} line{'s' if len(spans) > 1 else ''}"
    if not quote:
        where = ", ".join(str(k) for k in sorted({k for _, k in spans}))
        return [f"it copies {lines} word for word from chapter {where}: write every "
                "sentence of this chapter in new words"]
    shown = "; ".join(f"'{t}' (chapter {k})" for t, k in spans[:3])
    return [f"it repeats {lines} from earlier chapters: {shown}: tell it in new words or "
            "leave it out"]


def _ngrams(w: list[str], n: int):
    return (w[i:i + n] for i in range(max(0, len(w) - n + 1)))


def ending(text: str, most: int = 45) -> str:
    """A chapter's last sentences, up to `most` words: what the next chapter
    is told it starts from."""
    sentences = [x.strip() for x in re.split(r"(?<=[.!?\u201d\"])\s+", text.strip()) if x.strip()]
    out: list[str] = []
    for x in reversed(sentences):
        if out and len(" ".join(out + [x]).split()) > most:
            break
        out.insert(0, x)
    return " ".join(out)


def write_canon(folder: Path, outline: "Outline", first: dict[str, int],
                gender: dict[str, str], ended: list[str]) -> None:
    """canon.json and canon.md: what the story has established so far."""
    people = {x: {"he_she": gender.get(x, ""), "first_chapter": first[x]}
              for x in sorted(first, key=lambda x: (first[x], x))}
    chapters = [{"chapter": i, "title": c.get("title", ""), "line": c.get("summary", ""),
                 "ended": ended[i - 1] if i <= len(ended) else ""}
                for i, c in enumerate(outline.chapters, 1)]
    (folder / "canon.json").write_text(json.dumps(
        {"title": outline.title, "people": people, "chapters": chapters}, indent=2),
        encoding="utf-8")
    lines = [f"# Canon: {outline.title}", "", "## People and places", ""]
    lines += [f"- {x}" + (f" ({v['he_she']})" if v["he_she"] else "")
              + f", from chapter {v['first_chapter']}" for x, v in people.items()] or ["- none named"]
    lines += ["", "## Chapters", ""]
    for c in chapters:
        lines.append(f"{c['chapter']}. **{c['title']}**: {c['line']}")
        if c["ended"]:
            lines.append(f"   Ended: \"{c['ended']}\"")
    (folder / "canon.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def outline_schema(n: int) -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": ["title", "chapters"],
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 80},
                "chapters": {"type": "array", "minItems": n, "maxItems": n, "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["title", "summary"],
                    "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 60},
                                   "summary": {"type": "string", "minLength": 1,
                                               "maxLength": 320}}}}}}


@dataclass
class Outline:
    title: str
    chapters: list[dict] = field(default_factory=list)


# ------------------------------------------------------------- Editor
_PLACEHOLDER = re.compile(r"<[^>]{1,40}>")
_META = re.compile(r"^\s*(here is|here's|sure[,!]|certainly|chapter \d+\s*[:.-]|"
                   r"as an ai|i hope you|note:)", re.I)


def review_outline(o: Outline, n: int) -> list[str]:
    faults = []
    if not o.title.strip():
        faults.append("the story has no title")
    if len(o.chapters) != n:
        faults.append(f"it has {len(o.chapters)} chapters, not {n}")
    titles = [c.get("title", "").strip().lower() for c in o.chapters]
    for i, c in enumerate(o.chapters, 1):
        if not c.get("title", "").strip() or not c.get("summary", "").strip():
            faults.append(f"chapter {i} is empty")
        if _PLACEHOLDER.search(c.get("title", "") + c.get("summary", "")):
            faults.append(f"chapter {i} is the prompt's placeholder, not a chapter")
        line = c.get("summary", "").strip()
        if line and not re.search(r"[.!?][\"'\u201d\u2019)]*$", line):
            # 2026-11-08: the 4B wrote four sentences; the schema's limit cut
            # them off mid-word ("Intrigued, shep") and the plan was passed.
            faults.append(f"chapter {i}'s line is cut off: give one or two short sentences")
    if len(set(t for t in titles if t)) < len([t for t in titles if t]):
        faults.append("two chapters have the same title")
    return faults


def _grams(text: str, n: int = 6) -> set:
    w = re.findall(r"[a-z']+", text.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def review_chapter(text: str, words: int, previous: str = "") -> list[str]:
    faults = []
    n = len(text.split())
    if n == 0:
        return ["it is empty"]
    if n < words * 0.4:
        faults.append(f"it is {n} words, far short of the {words} asked for")
    if n > words * 2.5:
        faults.append(f"it is {n} words, far over the {words} asked for")
    if _META.search(text):
        faults.append("it talks to the reader about the writing instead of telling the story")
    if _PLACEHOLDER.search(text):
        faults.append("it contains the prompt's placeholder")
    if previous:
        mine, theirs = _grams(text), _grams(previous)
        if mine and len(mine & theirs) / len(mine) > 0.3:
            faults.append("much of it repeats the previous chapter")
    return faults


# ---------------------------------------------------------------- the log
def record(folder: Path, who: str, event: str, **detail) -> None:
    line = {"at": int(time.time()), "who": who, "department": "Library", "event": event,
            **detail}
    with (Path(folder) / "work.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "chapter"


def _request(folder: Path) -> str:
    lines = (folder / "request.md").read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(l for l in lines if not l.startswith("#")).strip()


# ---------------------------------------------------------------- the job
def write_story(folder: Path, router, say=print, words: int = WORDS) -> bool:
    """Plan and write the story in `folder`. True if every chapter passed
    the Editor; the story is written either way, with what failed said."""
    folder = Path(folder)
    request = _request(folder)
    n = chapter_count(request)
    words = chapter_words(request, n, words)

    # The Writer plans; the Editor checks the plan.
    say(f"Writer: planning {n} chapters.")
    record(folder, "Writer", "started", job="outline", chapters=n)
    outline, faults = None, []
    for attempt in (1, 2):
        ask = request + (f"\n\nYour last plan could not be used: {'; '.join(faults)}."
                         if faults else "")
        reply = router.ask(TASK, load_prompt("staff_story_outline", chapters=n), ask,
                           schema=outline_schema(n), max_tokens=120 + 90 * n)
        try:
            doc = json.loads(reply.text[reply.text.find("{"):reply.text.rfind("}") + 1])
            outline = Outline(str(doc.get("title", "")).strip(), list(doc.get("chapters", [])))
            faults = review_outline(outline, n)
        except (ValueError, AttributeError) as exc:
            outline, faults = None, [f"it is not JSON ({exc})"]
        record(folder, "Editor", "checked", job="outline", faults=faults)
        if not faults:
            break
        say("Editor: the plan goes back to the Writer: " + "; ".join(faults))
    if outline is None or faults:
        say("Editor: the plan could not be used: " + "; ".join(faults))
        record(folder, "Editor", "stopped", job="outline", faults=faults)
        return False
    (folder / "outline.md").write_text(
        f"# {outline.title}\n\n" + "\n".join(
            f"{i}. **{c['title']}**: {c['summary']}" for i, c in enumerate(outline.chapters, 1))
        + "\n", encoding="utf-8")
    say(f"Writer: '{outline.title}', {n} chapters. The Editor passed the plan.")

    # The Writer writes a chapter at a time and corrects its own slips; the
    # Editor reviews each and sends it back once (owner, 2026-10-21).
    chapters_dir = folder / "chapters"
    chapters_dir.mkdir(exist_ok=True)
    texts, all_ok, previous = [], True, ""
    ended: list[str] = []                    # the words each chapter ended on
    first: dict[str, int] = {}               # the chapter that first named each
    told: set[str] = set()                   # the names earlier chapters used
    gender: dict[str, str] = {}              # and he or she, where they said
    planned = names(request) | names(outline.title) | {
        x for c in outline.chapters for x in names(c.get("summary", ""))}
    system = load_prompt("staff_story_chapter", words=words)
    from . import writer
    if writer.harper() is None:
        say("Writer: spelling is not checked: Harper is not installed.")
    for i, c in enumerate(outline.chapters, 1):
        say(f"Writer: writing chapter {i} of {n}, '{c['title']}'.")
        record(folder, "Writer", "started", job=f"chapter {i}")
        base = (f"The story: {outline.title}. {request}\n\n"
                f"This chapter ({i} of {n}), '{c['title']}': {c['summary']}")
        if told:
            # Only the names, not the earlier text: shown more, the model
            # wrote its neighbours' chapters (D168).
            base += ("\n\nNames earlier chapters gave the story's people and places "
                     "(keep them; rename no one): "
                     + ", ".join(f"{x} ({gender[x]})" if x in gender else x
                                 for x in sorted(told)) + ".")
        if i > 1:
            # Where the last chapter's PLAN left off, never its words: told the
            # last chapter's closing sentences, the 8B wrote them again, word for
            # word, in 4 of 4 later chapters (2026-11-08, mistake 4b).
            prev = outline.chapters[i - 2]
            base += (f"\n\nThe chapter before this one, '{prev['title']}', has already told: "
                     f"{prev['summary']} Begin after it; do not tell it again.")
        if i == n:
            base += "\n\nThis is the last chapter: it ends the story."
        else:
            # The request tells the whole plot, and a first chapter told it all.
            base += ("\n\nThis chapter does not end the story: stop where this chapter's "
                     "line stops. What happens after it is for later chapters.")
        faults, back, text = [], [], ""
        from . import timekeeper
        clock = timekeeper.Timer("library", "story chapter").__enter__()
        for attempt in (1, 2):
            ask = base + (f"\n\nYour last version could not be used: {'; '.join(back)}. "
                          "Write the chapter again." if back else "")
            text = router.ask(TASK, system, ask, max_tokens=int(words * 1.9)).text.strip()
            text, fixed, left = writer_pass(text, outline.title, told | planned)
            if fixed:
                record(folder, "Writer", "corrected", job=f"chapter {i}", changes=fixed)
                say(f"Writer: corrected {', '.join(fixed)}.")
            others = (review_chapter(text, words, previous) + language_faults(left, words)
                      + renamed(text, told, planned)
                      + regendered(text, gender, told | planned))
            earlier = [t for _, t, _ in texts]
            plan = request + " " + " ".join(c.get("summary", "") for c in outline.chapters)
            faults = others + repeated(text, earlier, plan)          # the log, and the owner
            back = others + repeated(text, earlier, plan, quote=False)   # the Writer
            record(folder, "Editor", "checked", job=f"chapter {i}", faults=faults)
            if not faults:
                break
            if attempt == 1:
                say(f"Editor: chapter {i} goes back to the Writer: " + "; ".join(faults))
        clock.ok = not faults
        clock.__exit__(None, None, None)
        if faults:
            all_ok = False
            say(f"Editor: chapter {i} kept, but: " + "; ".join(faults))
        (chapters_dir / f"{i:02d}-{_slug(c['title'])}.md").write_text(
            f"## {i}. {c['title']}\n\n{text}\n", encoding="utf-8")
        texts.append((c["title"], text, faults))
        previous = text
        # The plan's names too: one that only starts sentences ("Clara and Lila
        # decide ...") is not seen by names() (2026-11-08: Clara was left out).
        for x in (names(text) | {n for n in planned
                                 if re.search(rf"\b{re.escape(n)}\b", text)}) - set(first):
            first.setdefault(x, i)
        told |= names(text)
        for x, p in pronouns(text, told | planned).items():
            gender.setdefault(x, p)              # the first chapter to say decides
        ended.append(ending(text))
        write_canon(folder, outline, first, gender, ended)
    (folder / "story.md").write_text(
        f"# {outline.title}\n\n" + "\n\n".join(
            f"## {i}. {t}\n\n{body}" for i, (t, body, _) in enumerate(texts, 1)) + "\n",
        encoding="utf-8")
    record(folder, "Editor", "finished", ok=all_ok)
    say("Finished: story.md is the whole story." + ("" if all_ok else
        " The Editor's doubts are in work.jsonl."))
    return all_ok


def writer_pass(text: str, title: str = "", people=()) -> tuple[str, list[str], list]:
    """The Writer's check of its own chapter: (text with its plain slips
    corrected, what was corrected, what is left for the Editor). Capitalised
    unknown words are names, not slips, and are not left for the Editor.
    `people`: the story's names; one written in lower case, where the
    dictionary knows no such word, is given its capital (2026-11-08: a 4B
    draft wrote "clara and lila" and went back for it)."""
    from . import writer
    named = {n.split()[-1].lower(): n.split()[-1] for n in people if n.split()}

    def keep(l):
        if l.kind == "Spelling" and l.matched in named:
            return True
        return writer.safe_to_fix(l)
    # The title's words, as written and in lower case: given only as written,
    # "Clockmaker" made "the clockmaker" a misspelling (2026-11-08).
    own = re.findall(r"[A-Za-z]{2,}", title)
    own += [x.lower() for x in own]
    lints = writer.check(text, own)
    if not lints:
        return text, [], []
    for l in lints:
        if l.kind == "Spelling" and l.matched in named:
            l.suggestions = [f"Replace with: \u201c{named[l.matched]}\u201d"]
    text, fixed = writer.fix_text(text, lints, keep=keep)
    rest = writer.check(text, own) or []
    left = [l for l in rest if not (l.kind == "Spelling" and l.matched[:1].isupper())]
    return text, fixed, left


def language_faults(left: list, words: int) -> list[str]:
    """The Editor's reading of what the Writer could not settle: a fault
    only when there is a lot of it, about one a paragraph."""
    if len(left) <= max(4, words // 60):
        return []
    shown = ", ".join(f"'{l.matched}'" for l in left[:6])
    return [f"it has {len(left)} spelling or grammar problems ({shown}); "
            "check the spelling and grammar"]
