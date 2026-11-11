"""The Storeroom: the parts the owner has to hand (owner, 2026-10-21).

The owner's words: "a department called The Storeroom where i can add
imformation or catalogue of parts i have at hand". The parts library
(nemo/parts.py) says what a part IS: its pins, supply and size, from a
datasheet. The Storeroom says what the owner HAS: how many, where they are
kept, and anything worth noting. The two are kept apart on purpose: a count
in a drawer is not a datasheet figure, and nothing here changes the library.

An item may name the library part it is (`part`, a library ref). Where its
name is exactly a library part's ref or name, code links it; anything less
certain is left unlinked rather than guessed. Nothing here asks the model.

One file, stock.yaml, in paths.storeroom (~/nemo-storeroom). On a live
NemoIso stick nemo-sync keeps that folder in NemoData, as it does stories.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

FILE = "stock.yaml"
_HEADER = ("# Nemo's Storeroom: the parts you have to hand. Edit with "
           "'nemo store' or the Storeroom button; by hand works too.\n")


class StoreroomError(ValueError):
    """Something the owner asked for that cannot be done; the message says why."""


@dataclass
class Item:
    key: str
    name: str
    quantity: int
    part: str = ""          # a parts-library ref, or "" when not linked
    where: str = ""         # where it is kept: "drawer 3", "blue box"
    notes: str = ""
    changed: str = ""       # the date it was last changed, YYYY-MM-DD


def stock_path(root: Path) -> Path:
    return Path(root).expanduser() / FILE


def key_for(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def load(root: Path) -> list[Item]:
    """Every item, in name order. A missing file is an empty storeroom; a
    broken one says so rather than reading as empty, so a save cannot
    overwrite what the owner wrote by hand."""
    path = stock_path(root)
    if not path.is_file():
        return []
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise StoreroomError(f"{path} could not be read ({exc}); fix or move it first") from None
    if not isinstance(doc, dict):
        raise StoreroomError(f"{path} is not a list of items; fix or move it first")
    items = []
    for key, d in doc.items():
        d = d if isinstance(d, dict) else {}
        try:
            qty = int(d.get("quantity", 0))
        except (TypeError, ValueError):
            qty = 0
        items.append(Item(str(key), str(d.get("name") or key), max(qty, 0),
                          str(d.get("part") or ""), str(d.get("where") or ""),
                          str(d.get("notes") or ""), str(d.get("changed") or "")))
    return sorted(items, key=lambda i: i.name.lower())


def _save(root: Path, items: list[Item]) -> Path:
    path = stock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {i.key: {k: v for k, v in asdict(i).items() if k != "key" and v != ""}
           for i in sorted(items, key=lambda i: i.name.lower())}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_HEADER + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def match(name: str, library) -> str:
    """The library ref this name is exactly, by ref or by part name, or ""."""
    if library is None:
        return ""
    n = name.strip().lower()
    if library.get(n):
        return library.get(n).ref
    for p in library:
        if p.name.strip().lower() == n:
            return p.ref
    return ""


def find(items: list[Item], name: str) -> Item | None:
    k = key_for(name)
    return next((i for i in items if i.key == k), None)


def _today() -> str:
    return _dt.date.today().isoformat()


def add(root: Path, name: str, quantity: int = 1, *, part: str = "", where: str = "",
        notes: str = "", library=None) -> Item:
    """Put `quantity` of `name` on the shelves. An item already there gains
    the quantity; a place, note or part given replaces the old one."""
    name = name.strip()
    if not key_for(name):
        raise StoreroomError("give the part a name, such as 'ESP32 DevKit' or 'red LED 5 mm'")
    if not isinstance(quantity, int) or quantity < 1:
        raise StoreroomError("the quantity to add must be a whole number, 1 or more")
    if part:
        if library is not None and not library.get(part):
            raise StoreroomError(f"{part!r} is not in the parts library; leave the part out, "
                                 "or add it to the library first ('nemo part add')")
        part = part.strip().lower()
    items = load(root)
    item = find(items, name)
    if item is None:
        item = Item(key_for(name), name, 0)
        items.append(item)
    item.quantity += quantity
    item.part = part or item.part or match(name, library)
    item.where = where.strip() or item.where
    item.notes = notes.strip() or item.notes
    item.changed = _today()
    _save(root, items)
    return item


def take(root: Path, name: str, quantity: int = 1) -> Item:
    """Take `quantity` off the shelves (used in a build). The item stays at
    0 so its place and notes are kept; remove() takes it off the list."""
    if not isinstance(quantity, int) or quantity < 1:
        raise StoreroomError("the quantity to take must be a whole number, 1 or more")
    items = load(root)
    item = find(items, name)
    if item is None:
        raise StoreroomError(f"there is no {name!r} in the Storeroom")
    if quantity > item.quantity:
        raise StoreroomError(f"there are only {item.quantity} of {item.name!r}")
    item.quantity -= quantity
    item.changed = _today()
    _save(root, items)
    return item


def remove(root: Path, name: str) -> bool:
    """Take an item off the list altogether. False if it was not there."""
    items = load(root)
    item = find(items, name)
    if item is None:
        return False
    items.remove(item)
    _save(root, items)
    return True


# Shelves for files, beside the catalogue (2026-10-21): the Theatre plays
# from videos/ and pictures/, Gaming from games/<console>/, the Music Room
# from music/, the Audio department from audio/.
SHELVES = ("videos", "pictures", "games", "music", "audio")


def shelf(root: Path, name: str) -> Path:
    if name.split("/")[0] not in SHELVES:
        raise StoreroomError(f"there is no shelf called {name!r}; they are {', '.join(SHELVES)}")
    return Path(root).expanduser() / name


def make_shelves(root: Path, extra: tuple[str, ...] = ()) -> list[Path]:
    """Make the shelves (and any `extra`, such as games/nes) if missing."""
    made = []
    for name in SHELVES + tuple(extra):
        p = shelf(root, name)
        if not p.is_dir():
            p.mkdir(parents=True)
            made.append(p)
    return made


def check_parts(root: Path, refs: list[str]) -> tuple[dict[str, list[Item]], list[str]]:
    """Before a part is asked for (owner, 2026-10-21: "before request for
    part is done each department checks on status"): for each library ref,
    the items on the shelves linked to it, and the refs there are none of.
    Only a link counts here; a name alone is not the part."""
    items = [i for i in load(root) if i.quantity > 0 and i.part]
    have = {r: [i for i in items if i.part == r] for r in refs}
    return {r: v for r, v in have.items() if v}, [r for r, v in have.items() if not v]


def on_shelf_named(root: Path, thing: str) -> list[Item]:
    """Items whose name has every word of `thing` (say "RFID reader"), for a
    thing no library part is yet: the Researcher looks on the shelves before
    it looks online. Said to the owner as maybe, never linked by itself."""
    words = [w for w in re.findall(r"[a-z0-9]+", thing.lower()) if len(w) > 1]
    if not words:
        return []
    return [i for i in load(root) if i.quantity > 0
            and all(w in re.findall(r"[a-z0-9]+", i.name.lower()) for w in words)]


def describe_stock(have: dict[str, list[Item]], need: list[str]) -> str:
    parts = []
    for ref, items in have.items():
        where = ", ".join(sorted({i.where for i in items if i.where}))
        parts.append(f"{ref} ({sum(i.quantity for i in items)}" + (f", {where}" if where else "") + ")")
    out = "Storeroom: on hand " + (", ".join(parts) if parts else "none of them")
    if need:
        out += "; to get: " + ", ".join(need)
    return out + "."


def on_hand(root: Path) -> dict[str, int]:
    """How many of each library part the owner has, for parts linked to it."""
    out: dict[str, int] = {}
    for i in load(root):
        if i.part and i.quantity:
            out[i.part] = out.get(i.part, 0) + i.quantity
    return out


# --------------------------------------------------------------------
#  The Researcher (owner, 2026-10-22): which library part an unlinked
#  item may be. It only suggests; an item is linked when the owner picks
#  one (link()). Nothing is fetched and the model is not asked.
# --------------------------------------------------------------------

@dataclass
class Suggestion:
    ref: str
    name: str
    score: float           # 0..1, how alike; for ordering, not a probability
    why: str


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _model_numbers(text: str) -> set[str]:
    """Words mixing letters and digits, as part numbers are ('BME280',
    'MFRC522', 'SG90'); the datasheet library's rule, shorter words allowed."""
    return {n for n in (_norm(w) for w in re.findall(r"[A-Za-z0-9-]+", text))
            if len(n) >= 4 and re.search(r"\d", n) and re.search(r"[a-z]", n)}


# Words every seller puts on a part: alike in them says nothing.
_GENERIC = {"module", "board", "mini", "sensor", "breakout", "kit", "the", "and", "for",
            "with", "pcb", "dev", "devkit", "pack", "pcs", "new"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) >= 3 and w not in _GENERIC}


def _same_number(a: str, b: str) -> bool:
    """One part number is the other, or ends it: RC522 is MFRC522's, but
    ESP32 is not ESP32C3's (a different chip, a letter on the end)."""
    short, long_ = sorted((a, b), key=len)
    return short == long_ or (len(short) >= 4 and long_.endswith(short))


def suggest(name: str, library, limit: int = 3, sheets=None) -> list[Suggestion]:
    """The library parts this item may be, likeliest first. A shared part
    number ('BME280') counts most, then shared words, then how alike the
    names are. `sheets` (a datasheets.Library) adds the parts whose linked
    datasheets mention the item's part number."""
    import difflib
    if library is None:
        return []
    numbers, words, flat = _model_numbers(name), _words(name), _norm(name)
    found: dict[str, Suggestion] = {}
    for p in library:
        theirs = _model_numbers(f"{p.ref} {p.name}")
        shared = sorted(n for n in numbers if any(_same_number(n, t) for t in theirs))
        common = words & _words(f"{p.ref.replace('_', ' ')} {p.name}")
        alike = max(difflib.SequenceMatcher(None, flat, _norm(p.name)).ratio(),
                    difflib.SequenceMatcher(None, flat, _norm(p.ref)).ratio())
        score = (0.6 if shared else 0.0) + min(0.3, 0.1 * len(common)) + 0.1 * alike
        if shared or common or alike >= 0.75:
            why = (f"the part number {', '.join(s.upper() for s in shared)}" if shared
                   else f"the words {', '.join(sorted(common))}" if common
                   else "a similar name")
            found[p.ref] = Suggestion(p.ref, p.name, round(score, 3), why)
    if sheets is not None and numbers:
        for n in sorted(numbers):
            for hit in sheets.search(n, limit=10):
                for s in sheets.sheets():
                    if s.file != hit.file:
                        continue
                    for ref in s.refs:
                        p = library.get(ref)
                        if p is not None and ref not in found:
                            found[ref] = Suggestion(ref, p.name, 0.5,
                                                    f"its datasheet {s.file} mentions {n.upper()}")
    return sorted(found.values(), key=lambda s: (-s.score, s.ref))[:limit]


def unlinked(root: Path) -> list[Item]:
    return [i for i in load(root) if not i.part]


def link(root: Path, name: str, ref: str, library) -> Item:
    """Link an item to the library part the owner chose. Its count, place
    and notes are left as they are."""
    if library is None or library.get(ref) is None:
        raise StoreroomError(f"{ref!r} is not in the parts library")
    items = load(root)
    item = find(items, name)
    if item is None:
        raise StoreroomError(f"there is no {name!r} in the Storeroom")
    item.part = library.get(ref).ref
    item.changed = _today()
    _save(root, items)
    return item


# ---------------------------------------------------------------- the view
# The catalogue window's search, sort and grouping (owner, 2026-10-29: "redo
# the Storeroom's catalogue": search, sort and group). Code only; the file is
# not changed by looking.
SORTS = {"name": lambda i: i.name.lower(), "qty": lambda i: i.quantity,
         "where": lambda i: (i.where.lower() or "￿", i.name.lower()),
         "part": lambda i: (i.part.lower() or "￿", i.name.lower()),
         "notes": lambda i: (i.notes.lower() or "￿", i.name.lower()),
         "changed": lambda i: (i.changed or "0000", i.name.lower())}
GROUPS = ("none", "where", "kind")
NOWHERE, UNSORTED = "Not said where", "Not linked to a library part"


def matches(item: Item, query: str) -> bool:
    """Every word of the query is somewhere in the item's name, place,
    library part or notes (any case)."""
    text = " ".join((item.name, item.where, item.part, item.notes)).lower()
    return all(w in text for w in query.lower().split())


def view(items: list[Item], query: str = "", sort: str = "name", descending: bool = False,
         group: str = "none", library=None) -> list[tuple[str, list[Item]]]:
    """The items to show: filtered by the query, sorted by a column, and
    grouped by where they are kept or by kind (the library part's category).
    Returns (group label, items) pairs; one pair labelled "" when not grouped."""
    shown = [i for i in items if matches(i, query)]
    shown.sort(key=SORTS.get(sort, SORTS["name"]), reverse=descending)
    if group == "none":
        return [("", shown)]
    kinds = {}
    if group == "kind" and library is not None:
        kinds = {ref: p.category for ref, p in getattr(library, "parts", {}).items()}
    out: dict[str, list[Item]] = {}
    for i in shown:
        if group == "where":
            label = i.where.strip() or NOWHERE
        else:
            label = (kinds.get(i.part) or "").strip().capitalize() or UNSORTED
        out.setdefault(label, []).append(i)
    last = {NOWHERE, UNSORTED}
    return sorted(out.items(), key=lambda kv: (kv[0] in last, kv[0].lower()))
