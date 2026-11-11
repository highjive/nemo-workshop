"""The Datasheet Reader (owner, 2026-11-04): a datasheet in the library
read into a DRAFT part entry, every figure with its proof.

docs/design-rules.md: never invent a datasheet figure, pin number or hash. So:

  ask      the model (design mode: the desktop's 8B, 16k context) is given
           the datasheet's own text, page by page, and asked, held to a JSON
           schema, for each value WITH the exact words it came from and their
           page. It is never asked for YAML (mistake 4d).
  check    code then keeps a value only if its quote is really on that page
           (whitespace and case aside) and the value is really in the quote.
           Anything else is dropped and listed as not found: never guessed.
  draft    what survives goes to <paths.parts>/drafts/<ref>.yaml, each line
           with its quote and page as a comment. The parts library reads
           *.yaml in paths.parts only, so a draft is never loaded as a part
           until the owner has looked at it and moved it up himself.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PAGE_CHARS = 36_000        # the text given: about 9k tokens, inside the 16k context
# The parts library's own kinds (data/parts/*.yaml, 2026-11-04).
CATEGORIES = ("actuator", "audio", "connector", "display", "driver", "logic", "mcu", "power", "sensor")
FUNCTIONS = ("power", "gnd", "io", "bus")

_EVIDENCE = {"type": "object", "properties": {"quote": {"type": "string"}, "page": {"type": "integer"}},
             "required": ["quote", "page"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "object", "properties": {"value": {"type": "string"}, **_EVIDENCE["properties"]},
                 "required": ["value", "quote", "page"]},
        "supply_v": {"type": "array", "items": {"type": "object", "properties": {
            "value": {"type": "number"}, **_EVIDENCE["properties"]}, "required": ["value", "quote", "page"]}},
        "current_ma": {"type": "object", "properties": {"value": {"type": "number"}, **_EVIDENCE["properties"]},
                       "required": ["value", "quote", "page"]},
        "logic_v": {"type": "object", "properties": {"value": {"type": "number"}, **_EVIDENCE["properties"]},
                    "required": ["value", "quote", "page"]},
        "pins": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "function": {"type": "string", "enum": list(FUNCTIONS)},
            **_EVIDENCE["properties"]}, "required": ["name", "function", "quote", "page"]}},
    },
    "required": ["name", "supply_v", "current_ma", "logic_v", "pins"],
}

SYSTEM = ("You read electronics datasheets. Report only what the datasheet's text says. For every "
          "value give the exact words it comes from, copied character for character, and the "
          "page number shown before them. If the text does not give a value, give an empty quote.")


@dataclass
class Found:
    what: str
    value: object
    quote: str
    page: int
    ok: bool
    why: str = ""


@dataclass
class Draft:
    file: str
    ref: str
    found: list[Found] = field(default_factory=list)

    @property
    def kept(self) -> list[Found]:
        return [f for f in self.found if f.ok]

    @property
    def dropped(self) -> list[Found]:
        return [f for f in self.found if not f.ok]


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _number_in(value, quote: str) -> bool:
    for n in re.findall(r"\d+(?:\.\d+)?", (quote or "").replace(",", ".")):
        if abs(float(n) - float(value)) < 1e-9:
            return True
    return False


# A pin's job, from its own description in the datasheet (docs/design-rules.md 4d: where
# code can decide, code decides). First match wins. The model's choice is
# only compared with it: on the first real reading (2026-11-04) the 8B called
# I2C's SDA and SCL "io" and an interrupt output "bus".
_FUNCTION_WORDS = (
    ("gnd", r"\bgnd\b|\bground\b|\bvss\b"),
    ("power", r"\bsupply\b|\bvcc\b|\bvdd\b|\bvin\b|\bpower\b|\b3v3\b"),
    ("bus", r"\bi2c\b|\bi²c\b|\bspi\b|\buart\b|\bsda\b|\bscl\b|\bmosi\b|\bmiso\b|\bsck\b|\bcs\b"),
)


def function_from(name: str, quote: str) -> str:
    words = f"{name} {quote}".lower()
    for function, pattern in _FUNCTION_WORDS:
        if re.search(pattern, words):
            return function
    return "io"


def _unquoted(quote: str) -> str:
    """The quote without the quotation marks a model wraps it in."""
    return (quote or "").strip().strip("\"'“”‘’").strip()


def check(what: str, value, quote: str, page: int, pages: dict[int, str]) -> Found:
    """Keep `value` only if `quote` is on `page` and holds the value."""
    quote = _unquoted(quote)
    if not quote or not _flat(quote):
        return Found(what, value, quote, page, False, "the datasheet's text does not give it")
    text = pages.get(page)
    if text is None:
        return Found(what, value, quote, page, False, f"there is no page {page}")
    if _flat(quote) not in _flat(text):
        return Found(what, value, quote, page, False, f"those words are not on page {page}")
    if isinstance(value, (int, float)) and not _number_in(value, quote):
        return Found(what, value, quote, page, False, f"{value:g} is not in those words")
    if isinstance(value, (int, float)) and not re.sub(
            r"\d+(?:[.,]\d+)?|\b(?:v|mv|ma|ua|µa|a|w|mw|hz|khz|mhz|or|to|and)\b|[^a-z]", "", quote.lower()):
        # "3.3 V" proves the number is in the datasheet, not what it is (the
        # supply and the logic level were both "3.3 V" on the first reading).
        return Found(what, value, quote, page, True, "short quote: check what it refers to")
    if isinstance(value, str) and _flat(value) not in _flat(quote):
        return Found(what, value, quote, page, False, f"'{value}' is not in those words")
    return Found(what, value, quote, page, True)


# Words of the sections that hold what the Reader is asked for (2026-11-08,
# after Claude Code Game Studios' "read the section, not the file"). A long
# datasheet's pin table or electrical table can sit after page 30: taking the
# first PAGE_CHARS left it out, whatever it said.
WANTED = ("pin description", "pin configuration", "pin function", "pinout", "pin assignment",
          "terminal function", "electrical characteristics", "recommended operating",
          "operating conditions", "supply voltage", "supply current", "operating current",
          "logic level", "vcc", "vdd", "features", "description")


def _score(text: str) -> int:
    low = text.lower()
    return sum(low.count(w) for w in WANTED)


def chosen_pages(pages: dict[int, str], limit: int = PAGE_CHARS) -> tuple[list[int], list[int]]:
    """The pages given to the model, in page order, and those left out.

    All of them when they fit. Otherwise page 1 (the part's name), then the
    pages that name the wanted sections most, until the text is full: code
    finds the sections, the model reads only them."""
    size = {n: len(f"[page {n}]\n{pages[n].strip()}\n") for n in pages}
    if sum(size.values()) <= limit:
        return sorted(pages), []
    order = sorted(pages, key=lambda n: (n != min(pages), -_score(pages[n]), n))
    keep, used = [], 0
    for n in order:
        if used + size[n] <= limit and (n == min(pages) or _score(pages[n]) > 0):
            keep.append(n); used += size[n]
    return sorted(keep), sorted(set(pages) - set(keep))


def prompt(pages: dict[int, str]) -> str:
    keep, left = chosen_pages(pages)
    out = [f"[page {n}]\n{pages[n].strip()}\n" for n in keep]
    if left:
        out.append(f"[{len(left)} pages were left out as too long to read; pages "
                   f"{', '.join(map(str, left[:12]))}{' ...' if len(left) > 12 else ''}]")
    return ("Read this datasheet and report the part's name, its supply voltages, its typical "
            "current in mA, its logic voltage, and its pins with what each is for (power, gnd, io "
            "or bus).\n\n" + "\n".join(out))


def draft(file: str, pages: dict[int, str], reply: dict, ref: str | None = None) -> Draft:
    """The model's `reply` checked against the datasheet's `pages`."""
    ref = ref or re.sub(r"[^a-z0-9]+", "_", Path(file).stem.lower()).strip("_")
    d = Draft(file, ref)
    n = reply.get("name") or {}
    d.found.append(check("name", n.get("value", ""), n.get("quote", ""), n.get("page", 0), pages))
    for s in reply.get("supply_v") or []:
        d.found.append(check("supply_v", s.get("value"), s.get("quote", ""), s.get("page", 0), pages))
    for key in ("current_ma", "logic_v"):
        v = reply.get(key) or {}
        if v.get("value") is not None:
            d.found.append(check(key, v.get("value"), v.get("quote", ""), v.get("page", 0), pages))
    for p in reply.get("pins") or []:
        f = check(f"pin {p.get('name')}", p.get("name", ""), p.get("quote", ""), p.get("page", 0), pages)
        decided = function_from(p.get("name", ""), f.quote)
        f.value = (p.get("name"), decided)
        if p.get("function") and p.get("function") != decided:
            f.why = f"the model said {p.get('function')}; its description says {decided}"
        d.found.append(f)
    return d


def to_yaml(d: Draft) -> str:
    """The draft, each kept line with its proof; what was dropped, and why."""
    def proof(f):
        note = f"  ({f.why})" if f.why and not f.what.startswith("pin ") else ""
        return f"  # p.{f.page}: \"{_flat(f.quote)[:120]}\"{note}"
    lines = [f"# DRAFT by the Datasheet Reader from {d.file}. Check every line against the",
             "# datasheet, then move this file up into the parts folder to use it.",
             f"{d.ref}:",
             # A datasheet does not say which of the library's kinds a part is; the
             # owner does. Until he does, the library refuses the file (it says so).
             f"  # category: CHOOSE ONE of {', '.join(CATEGORIES)}. The library will not take",
             "  # this part until you write it here, without the #."]
    by = {}
    for f in d.kept:
        by.setdefault(f.what if not f.what.startswith("pin ") else "pins", []).append(f)
    if "name" in by:
        lines.append(f"  name: {json.dumps(by['name'][0].value)}" + proof(by["name"][0]))
    if "supply_v" in by:
        vals = sorted({float(f.value) for f in by["supply_v"]})
        lines.append(f"  supply_v: [{', '.join(f'{v:g}' for v in vals)}]" + proof(by["supply_v"][0]))
    for key in ("current_ma", "logic_v"):
        if key in by:
            lines.append(f"  {key}: {float(by[key][0].value):g}" + proof(by[key][0]))
    if "pins" in by:
        lines.append("  pins:")
        for f in by["pins"]:
            name, function = f.value
            lines.append(f"    - {{name: {json.dumps(name)}, function: {function}}}" + proof(f)
                         + (f"  ({f.why})" if f.why else ""))
    if d.dropped:
        lines.append("# Not found (the model's answer did not hold up against the text):")
        for f in d.dropped:
            lines.append(f"#   {f.what}: {f.why}")
    return "\n".join(lines) + "\n"


def write(d: Draft, parts_root: Path) -> Path:
    out = Path(parts_root) / "drafts" / f"{d.ref}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_yaml(d), encoding="utf-8")
    return out


def ask(base: str, pages: dict[int, str], timeout: int = 600) -> dict:
    """The model's reading, held to SCHEMA by the server's grammar."""
    payload = {"model": "local", "temperature": 0, "max_tokens": 3000,
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": prompt(pages)}],
               "chat_template_kwargs": {"enable_thinking": False},
               "response_format": {"type": "json_schema",
                                   "json_schema": {"name": "datasheet", "schema": SCHEMA}}}
    req = urllib.request.Request(f"{base}/chat/completions", json.dumps(payload).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        reply = json.loads(r.read().decode("utf-8"))
    return json.loads(reply["choices"][0]["message"]["content"])


def pages_of(lib, file: str) -> dict[int, str]:
    """A datasheet's pages from the library's index (nemo/datasheets.py)."""
    return {int(p): t for p, t in lib.db.execute(
        "select page, text from pages where file = ? order by page", (file,))}
