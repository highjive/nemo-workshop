"""The Writer (owner's request, 2026-10-21).

  Build mode  owns the brief: drafts it (the "Describe it" step), checks its
              spelling, and before the Designer starts writes assignment.md,
              the brief made into a clear handoff. A misspelling is offered
              as a fix, never made silently: the brief's words are the
              owner's. ("A replica Blunderbust gun" went to the image model
              misspelt, and the impressions came back unlike a blunderbuss.)
  Stories     writes each chapter, fixes its own slips (a repeated word, a
              misspelt ordinary word; never a capitalised word, which may be
              a name), and hands it to the Editor to review.

Spelling and grammar are Harper's (github.com/Automattic/harper, Apache-2.0):
an offline checker, one program, no model and no Java. Measured on the AH531
(v2.12.0, 2026-10-21): 1.6 s for a three-sentence check from a cold start;
it found "Blunderbust" (Blunderbuss), "the the" and "Its" (It's) and let
British "colour" pass; it missed "a mechanism that simulate". British
spelling (DIALECT). Where it is not installed every check here says so and
changes nothing.

Where it looks: paths.harper, else harper-cli on the PATH or beside Nemo,
else C:/Nemo/writer (NemoWin) or /opt/nemo/writer (NemoIso).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DIALECT = "british"
HARPER_TAG = "v2.12.0"
# Fields of the brief that are prose (name and parts are identifiers).
BRIEF_FIELDS = ("function", "user", "done_when", "constraints", "open_questions")


@dataclass
class Lint:
    rule: str
    kind: str
    message: str
    start: int
    end: int
    matched: str
    suggestions: list[str] = field(default_factory=list)

    @property
    def replacement(self) -> str | None:
        """The first suggested replacement text, if it is one."""
        for s in self.suggestions:
            m = re.match(r"Replace with: [\"\u201c](.*)[\"\u201d]$", s)
            if m:
                return m.group(1)
        return None


def harper(cfg=None) -> str | None:
    """The harper-cli to run, or None. NEMO_WRITER_CHECK=off (the test
    sandbox sets it) is the same as not installed."""
    if os.environ.get("NEMO_WRITER_CHECK") == "off":
        return None
    configured = cfg.get("paths.harper") if cfg is not None else None
    if configured and Path(str(configured)).is_file():
        return str(configured)
    from .platform_probe import find_tool
    found = find_tool("harper-cli")
    if found:
        return found
    exe = "harper-cli.exe" if sys.platform.startswith("win") else "harper-cli"
    roots = ([Path("C:/Nemo/writer")] if sys.platform.startswith("win")
             else [Path("/opt/nemo/writer")])
    for r in roots:
        for p in (r / exe, r / "win" / exe):
            if p.is_file():
                return str(p)
    return None


def check(text: str, words=(), cfg=None, run=None) -> list[Lint] | None:
    """Harper's findings in `text`, with `words` known (part names, say).
    None where Harper is not installed or did not answer."""
    run = run or subprocess.run
    exe = harper(cfg)
    if exe is None or not text.strip():
        return None if exe is None else []
    with tempfile.TemporaryDirectory(prefix="nemo-writer-") as d:
        src = Path(d) / "text.txt"
        # newline="\n": Windows wrote CR LF, and Harper's offsets then ran one
        # ahead per line break, so every fix after the first paragraph was
        # skipped as not lining up (2026-11-08).
        src.write_text(text, encoding="utf-8", newline="\n")
        user = Path(d) / "words.txt"
        user.write_text("\n".join(sorted(set(words))) + "\n", encoding="utf-8")
        # Its own home, with the folders it looks for. Harper v2.12.0 crashed
        # (an unwrap at main.rs:81) when the home folder had no AppData, as
        # under the test sandbox (2026-10-21); and the owner's own Harper
        # settings, if any, must not change Nemo's answers.
        home = Path(d) / "home"
        for sub in ("AppData/Roaming", "AppData/Local", ".config", ".local/share"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, USERPROFILE=str(home), HOME=str(home),
                   APPDATA=str(home / "AppData/Roaming"),
                   LOCALAPPDATA=str(home / "AppData/Local"),
                   XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_DATA_HOME=str(home / ".local/share"))
        try:
            p = run([exe, "lint", "--format", "json", "--dialect", DIALECT, "--quiet",
                     "--user-dict-path", str(user), "--file-dict-path", str(Path(d) / "f"),
                     str(src)], capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120, env=env)
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        doc = json.loads(p.stdout[p.stdout.find("["):])
    except ValueError:
        return None
    out = []
    for f in doc if isinstance(doc, list) else []:
        for x in f.get("lints", []):
            sp = x.get("span") or {}
            out.append(Lint(str(x.get("rule", "")), str(x.get("kind", "")),
                            str(x.get("message", "")), int(sp.get("char_start", 0)),
                            int(sp.get("char_end", 0)), str(x.get("matched_text", "")),
                            [str(s) for s in x.get("suggestions", [])]))
    return sorted(out, key=lambda l: l.start)


# ---------------------------------------------------------------- stories
def _plain_slip(word: str, fix: str) -> bool:
    """Two neighbouring letters swapped (recieved), or one letter doubled
    (beautifull). Not a dropped letter: Harper's first guess for "ovr" was
    "or" (2026-10-21), and "over" was not among its guesses at all."""
    if len(word) < 5 or word.lower() == fix.lower():
        return False
    w, f = word.lower(), fix.lower()
    if len(w) == len(f):
        d = [i for i in range(len(w)) if w[i] != f[i]]
        return len(d) == 2 and d[1] == d[0] + 1 and w[d[0]] == f[d[1]] and w[d[1]] == f[d[0]]
    if len(w) == len(f) + 1:
        for i in range(1, len(w)):
            if w[i] == w[i - 1] and w[:i] + w[i + 1:] == f:
                return True
    return False


def safe_to_fix(l: Lint) -> bool:
    """What the Writer corrects in its own chapter without asking: a word
    said twice, and a misspelt ordinary word whose fix cannot change its
    meaning (one guess only, or a plain slip). Never a capitalised word: it
    may be a character's name the dictionary does not know. The rest goes
    to the Editor as it is."""
    if l.replacement is None:
        return False
    if l.rule == "RepeatedWords":
        return True
    # Two spaces for one (2026-11-08: a 4B chapter went back for "  " six
    # times over): nothing a reader would see changes.
    if l.kind == "Formatting" and not l.matched.strip() and l.replacement == " ":
        return True
    # A sentence begun in lower case (2026-11-08, a 4B draft): its first
    # letter made a capital, nothing else.
    if (l.rule == "SentenceCapitalization" and l.matched[:1].islower()
            and l.replacement == l.matched[:1].upper() + l.matched[1:]):
        return True
    if l.kind != "Spelling" or not l.matched[:1].islower():
        return False
    # A change of capital only is not a slip: "the clockmaker said" became
    # "the Clockmaker said" because the title's "Clockmaker" was a known word
    # (2026-11-08).
    if l.replacement.lower() == l.matched.lower():
        return False
    guesses = [s for s in l.suggestions if s.startswith("Replace with")]
    return len(guesses) == 1 or _plain_slip(l.matched, l.replacement)


def fix_text(text: str, lints: list[Lint], keep=safe_to_fix) -> tuple[str, list[str]]:
    """`text` with the chosen findings corrected, and what was changed."""
    changes = []
    for l in sorted((l for l in lints if keep(l)), key=lambda l: -l.start):
        if text[l.start:l.end] != l.matched:
            continue                                  # spans no longer line up
        text = text[:l.start] + l.replacement + text[l.end:]
        changes.append(f"{l.matched} -> {l.replacement}")
    return text, list(reversed(changes))


# ------------------------------------------------------------------ brief
def known_words(brief, library) -> set[str]:
    """Words a brief may use that a dictionary does not know: the parts'
    references and the words of their names."""
    out = set()
    for p in getattr(library, "parts", {}).values():
        out.add(p.ref)
        out.update(w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]+", p.name) if len(w) > 2)
        # And the pieces of a hyphened name: Harper reads "ESP32-C3" as two
        # words and called "C3" a misspelling of "Co" (2026-11-08).
        out.update(w for w in re.findall(r"[A-Za-z0-9]+", p.name)
                   if len(w) >= 2 and any(c.isdigit() for c in w) and w[0].isalpha())
    out.update(re.findall(r"[A-Za-z][\w-]+", brief.name or ""))
    # A part's word written small is still that word: Gemma 4 wrote "oled", and the
    # Writer stopped the brief, "did you mean 'old'?" (2026-11-11). Only words that are
    # all capitals or carry a digit (OLED, BME280): a name like "Mini" stays as it is.
    out |= {w.lower() for w in out if (w.isupper() or any(c.isdigit() for c in w)) and len(w) > 2}
    return out


def _brief_texts(brief) -> list[tuple[str, int, str]]:
    out = []
    for f in BRIEF_FIELDS:
        v = getattr(brief, f, None)
        if isinstance(v, list):
            out += [(f, i, str(x)) for i, x in enumerate(v) if str(x).strip()]
        elif v and str(v).strip():
            out.append((f, -1, str(v)))
    return out


@dataclass
class Spelling:
    field: str
    index: int              # -1 for a single-text field
    old: str
    new: str
    message: str


def brief_spelling(brief, library=None, cfg=None, run=None) -> list[Spelling] | None:
    """Misspelt words in the brief's prose, each with Harper's one
    replacement. None where Harper is not installed."""
    texts = _brief_texts(brief)
    joined, spans, at = "", [], 0
    for f, i, t in texts:
        spans.append((f, i, at, at + len(t)))
        joined += t + "\n\n"
        at = len(joined)
    lints = check(joined, known_words(brief, library) if library else (), cfg, run)
    if lints is None:
        return None
    out = []
    for l in lints:
        if l.kind != "Spelling" or l.replacement is None:
            continue
        for f, i, a, b in spans:
            if a <= l.start < b:
                out.append(Spelling(f, i, l.matched, l.replacement, l.message))
    return out


def corrected(brief, s: Spelling):
    """The value of `s.field` with `s` corrected, for a fix to set."""
    v = getattr(brief, s.field)
    pat = re.compile(rf"\b{re.escape(s.old)}\b")
    if s.index < 0:
        return pat.sub(s.new, str(v), count=1)
    v = list(v)
    v[s.index] = pat.sub(s.new, str(v[s.index]), count=1)
    return v


# ------------------------------------------------------------- assignment
_IDENT = re.compile(r"^[A-Za-z_][\w.-]*$")


def assignment(brief, parts, spelling: list[Spelling] | None) -> str:
    """The brief as a handoff to the Designer: what to make and for whom,
    with what, how big, how to know it works, and what is not yet settled.
    Written from the brief alone; nothing is added to it."""
    flags = []
    done = (brief.done_when or "").strip()
    if not done:
        flags.append("No done-when: say what you would do and what you would see if it works.")
    elif _IDENT.match(done) or len(done.split()) < 3:
        flags.append(f"Done-when is \u201c{done}\u201d, a name rather than a test: say what "
                     "you would do and what you would see if it works.")
    if spelling:
        flags += [f"\u201c{s.old}\u201d in the {s.field.replace('_', ' ')}: did you mean "
                  f"\u201c{s.new}\u201d?" for s in spelling]
    elif spelling is None:
        flags.append("Spelling was not checked: Harper is not installed.")
    vague = [w for w in ("etc", "something", "somehow", "maybe", "some kind of", "and so on",
                         "nice", "good", "safe")
             if re.search(rf"\b{w}\b", (brief.function or "") + " " +
                          " ".join(map(str, brief.constraints or [])), re.I)]
    if vague:
        flags.append("Vague words the Designer cannot act on: " + ", ".join(vague)
                     + ". Say what is meant, in numbers where you can.")
    lines = [f"# Assignment: {brief.name}", "",
             "_Written by the Writer from the brief, for the Designer. Nothing here is "
             "new: where the brief is unclear, that is said below._", "",
             "## What to make", "", (brief.function or "(not said)").strip(), ""]
    if (brief.user or "").strip():
        lines += ["## For whom", "", brief.user.strip(), ""]
    lines += ["## With", ""]
    if getattr(brief, "no_parts", False):
        lines.append("- No parts: nothing electrical.")
    else:
        lines += [f"- {p.ref}: {p.name}" for p in parts] or ["- (no parts chosen yet)"]
    if getattr(brief, "no_power", False):
        lines.append("- No power needed.")
    elif brief.power or brief.supply_ma:
        lines.append(f"- Power: {brief.power or '(not said)'}, "
                     f"{brief.supply_ma:g} mA supply" if brief.supply_ma else
                     f"- Power: {brief.power}")
    env = brief.envelope_mm or []
    lines += ["", "## Size", "", (f"Inside {env[0]:g} x {env[1]:g} x {env[2]:g} mm."
                                  if len(env) == 3 else "(not said)"), "",
              "## Done when", "", done or "(not said)", ""]
    if brief.constraints:
        lines += ["## Constraints", ""] + [f"- {c}" for c in brief.constraints] + [""]
    if brief.open_questions:
        lines += ["## Not yet settled", ""] + [f"- {q}" for q in brief.open_questions] + [""]
    lines += ["## The Writer's notes", ""] + ([f"- {f}" for f in flags] or
                                              ["- The brief reads clearly: nothing to ask."])
    return "\n".join(lines) + "\n"


def write_assignment(project, library, cfg=None) -> tuple[Path, list[str]]:
    """Write <project>/assignment.md; (its path, the Writer's notes)."""
    brief = project.load_brief()
    parts = [p for p in (library.get(r) for r in brief.parts) if p]
    sp = brief_spelling(brief, library, cfg)
    text = assignment(brief, parts, sp)
    path = Path(project.root) / "assignment.md"
    path.write_text(text, encoding="utf-8")
    notes = [l[2:] for l in text.split("## The Writer's notes", 1)[1].splitlines()
             if l.startswith("- ")]
    return path, notes
