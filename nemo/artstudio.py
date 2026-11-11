"""The Art Studio's Clerk and Writer (owner, 2026-10-22: "sort out each
department's issues"; he chose to build both).

  Clerk   the request as choices from lists: pick what to make (a plaque, an
          open box, a pot, a tag, a stand) and fill in its sizes; the Clerk
          turns that into the Designer's list of shapes and remembers the
          last choices for each kind (~/.nemo/art-clerk.json)
  Writer  a title and a line for each model, and its card: what it is, its
          size as measured from the mesh, its shapes, the Editor's verdict
          and any Print Shop slices (<model>/about.json, <model>/card.txt)

Neither asks the model. What the Clerk makes is still checked by the
Editor when the Designer builds it.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import modelkit
from .modelkit import ModelError


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    default: float | str


@dataclass(frozen=True)
class Kind:
    key: str
    title: str
    about: str
    fields: tuple[Field, ...]


KINDS = {k.key: k for k in (
    Kind("plaque", "Plaque", "a flat plate with raised letters",
         (Field("width", "width mm", 100), Field("height", "height mm", 60),
          Field("thickness", "thickness mm", 4), Field("text", "words", "NEMO"),
          Field("letters", "letter height mm", 18), Field("raised", "letters raised mm", 1.5))),
    Kind("box", "Open box", "a box with no lid: walls and a floor",
         (Field("width", "width mm", 80), Field("depth", "depth mm", 60),
          Field("height", "height mm", 40), Field("wall", "wall mm", 2), Field("floor", "floor mm", 2))),
    Kind("pot", "Round pot", "a round pot or pen holder: a wall and a floor",
         (Field("diameter", "diameter mm", 60), Field("height", "height mm", 50),
          Field("wall", "wall mm", 2), Field("floor", "floor mm", 2))),
    Kind("tag", "Tag", "a rounded tag with a hole, words optional",
         (Field("width", "width mm", 80), Field("height", "height mm", 25),
          Field("thickness", "thickness mm", 3), Field("hole", "hole mm", 5),
          Field("text", "words (may be empty)", ""), Field("letters", "letter height mm", 18),
          Field("raised", "letters raised mm", 1))),
    Kind("stand", "Stand", "a base, a leaning back and a front lip: for a phone, a card, a tablet",
         (Field("width", "width mm", 70), Field("depth", "depth mm", 60),
          Field("thickness", "thickness mm", 4), Field("back", "back height mm", 80),
          Field("lean", "lean degrees", 15), Field("lip", "lip height mm", 10))),
)}


def _nums(kind: Kind, values: dict) -> dict:
    out = {}
    for f in kind.fields:
        v = values.get(f.key, f.default)
        if isinstance(f.default, str):
            out[f.key] = str(v).strip()
            continue
        try:
            out[f.key] = float(v)
        except (TypeError, ValueError):
            raise ModelError(f"{f.label} must be a number, not {v!r}") from None
        if out[f.key] < 0 or (out[f.key] == 0 and f.key not in ("lean",)):
            raise ModelError(f"{f.label} must be more than 0")
    return out


def _fits_text(text: str, letters: float, room: float):
    if text and 0.7 * letters * len(text) > room:      # the kit's own estimate of a word's width
        raise ModelError(f"\"{text}\" at {letters:g} mm letters is about "
                         f"{0.7 * letters * len(text):.0f} mm wide; there is room for {room:.0f}")


# Raised letters, and only big enough ones. Built here (2026-10-22) with
# CadQuery's own font, a letter's strokes measured 0.98 mm at 14 mm and 0.56
# mm at 8 mm: 7 % of its height. Below the printer's minimum wall the Editor
# fails the model, so the Clerk refuses smaller letters first. Letters cut
# in were tried too and fail the same check whatever their size: beside a
# cut letter's sharp corner the plate narrows to nothing (0.09 mm measured).
STROKE = 0.07


def _letters(v: dict, x: float, min_wall: float) -> dict:
    need = min_wall / STROKE
    if v["letters"] < need:
        raise ModelError(f"letters {v['letters']:g} mm tall have strokes about "
                         f"{v['letters'] * STROKE:.1f} mm wide, under the {min_wall:g} mm the "
                         f"printer needs: make them at least {need:.0f} mm")
    return {"shape": "text", "text": v["text"], "size": v["letters"], "depth": v["raised"],
            "at": [x, 0, v["thickness"]]}


def shapes(kind_key: str, values: dict, min_wall: float = 1.2) -> list[dict]:
    """The Designer's list of shapes for this kind and these choices."""
    kind = KINDS.get(kind_key)
    if kind is None:
        raise ModelError(f"the Clerk has no {kind_key!r}; it has {', '.join(KINDS)}")
    v = _nums(kind, values)
    k = kind.key
    if k == "plaque":
        _fits_text(v["text"], v["letters"], v["width"] - 8)
        out = [{"shape": "plate", "size": [v["width"], v["height"]], "thickness": v["thickness"]}]
        if v["text"]:
            out.append(_letters(v, 0, min_wall))
        return out
    if k == "box":
        if 2 * v["wall"] >= min(v["width"], v["depth"]) or v["floor"] >= v["height"]:
            raise ModelError("the walls or floor leave no room inside")
        return [{"shape": "box", "size": [v["width"], v["depth"], v["height"]]},
                {"shape": "box", "op": "cut", "at": [0, 0, v["floor"]],
                 "size": [v["width"] - 2 * v["wall"], v["depth"] - 2 * v["wall"],
                          v["height"] - v["floor"] + 1]}]
    if k == "pot":
        r = v["diameter"] / 2
        if v["wall"] >= r or v["floor"] >= v["height"]:
            raise ModelError("the wall or floor leaves no room inside")
        return [{"shape": "cylinder", "radius": r, "height": v["height"]},
                {"shape": "cylinder", "op": "cut", "radius": r - v["wall"],
                 "height": v["height"] - v["floor"] + 1, "at": [0, 0, v["floor"]]}]
    if k == "tag":
        if v["hole"] >= v["height"] - 2:
            raise ModelError("the hole is as tall as the tag")
        hole_x = -v["width"] / 2 + v["hole"] / 2 + 2.5
        out = [{"shape": "rounded_box", "size": [v["width"], v["height"], v["thickness"]],
                "radius": min(4.0, v["height"] / 2 - 0.5)},
               {"shape": "cylinder", "op": "cut", "radius": v["hole"] / 2,
                "height": v["thickness"] + 2, "at": [hole_x, 0, -1]}]
        if v["text"]:
            room = v["width"] - (v["hole"] + 5) - 4
            _fits_text(v["text"], v["letters"], room)
            out.append(_letters(v, hole_x + v["hole"] / 2 + 2 + room / 2, min_wall))
        return out
    # stand
    if v["lean"] >= 60:
        raise ModelError("a back leaning 60 degrees or more would not hold anything")
    # The back is tipped about the middle of its foot, so one bottom edge goes
    # down by half its thickness x sin(lean): 0.52 mm at 4 mm and 15 degrees,
    # under the base, and the stand stood on that edge with its base off the
    # bed (OrcaSlicer would not slice it, 2026-11-04). Lifted by as much, the
    # edge rests on the bed and the back still sinks into the base.
    import math
    lift = math.ceil(v["thickness"] / 2 * math.sin(math.radians(v["lean"])) * 1e4) / 1e4
    return [{"shape": "plate", "size": [v["width"], v["depth"]], "thickness": v["thickness"]},
            {"shape": "box", "size": [v["width"], v["thickness"], v["back"]],
             "at": [0, -v["depth"] / 2 + v["thickness"] / 2, lift], "rotate": [v["lean"], 0, 0]},
            {"shape": "box", "size": [v["width"], v["thickness"], v["lip"] + v["thickness"]],
             "at": [0, v["depth"] / 2 - v["thickness"] / 2, 0]}]


def _clerk_path() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "art-clerk.json"


def last(kind_key: str) -> dict:
    """The choices made the last time for this kind, else the defaults."""
    kind = KINDS[kind_key]
    try:
        kept = json.loads(_clerk_path().read_text(encoding="utf-8")).get(kind_key, {})
    except (OSError, ValueError, AttributeError):
        kept = {}
    return {f.key: kept.get(f.key, f.default) for f in kind.fields}


def request(name: str, kind_key: str, values: dict, min_wall: float = 1.2) -> dict:
    """The Clerk: a model the Designer can build, from choices. The choices
    are kept for next time once they make a valid model."""
    doc = {"name": name, "shapes": shapes(kind_key, values, min_wall)}
    modelkit.validate(doc)
    p = _clerk_path()
    try:
        kept = json.loads(p.read_text(encoding="utf-8"))
        kept = kept if isinstance(kept, dict) else {}
    except (OSError, ValueError):
        kept = {}
    kept[kind_key] = {f.key: _nums(KINDS[kind_key], values)[f.key] for f in KINDS[kind_key].fields}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(kept, indent=1), encoding="utf-8")
    doc["from"] = {"kind": kind_key, "choices": kept[kind_key]}
    return doc


# --------------------------------------------------------------------
#  The Writer
# --------------------------------------------------------------------

def about(folder: Path) -> dict:
    try:
        d = json.loads((Path(folder) / "about.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_about(folder: Path, title: str | None = None, line: str | None = None,
                made_from: dict | None = None) -> dict:
    """Keep a title and a line for the model (empty clears them)."""
    d = about(folder)
    for key, v in (("title", title), ("line", line)):
        if v is not None:
            if v.strip():
                d[key] = v.strip()
            else:
                d.pop(key, None)
    if made_from is not None:
        d["from"] = made_from
    (Path(folder) / "about.json").write_text(json.dumps(d, indent=1), encoding="utf-8")
    return d


def card(folder: Path) -> str:
    """The Writer's card for one model, written to card.txt as well."""
    folder = Path(folder)
    try:
        spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ModelError(f"{folder.name} has no spec.json: it was never built") from None
    a = about(folder)
    lines = [a.get("title") or spec.get("name", folder.name)]
    if a.get("line"):
        lines.append(a["line"])
    lines.append("")
    made = a.get("from")
    if made and made.get("kind") in KINDS:
        lines.append(f"Made from   {KINDS[made['kind']].title} ("
                     + ", ".join(f"{k} {v:g}" if isinstance(v, (int, float)) else f"{k} \"{v}\""
                                 for k, v in made["choices"].items()) + ")")
    counts: dict[str, int] = {}
    for s in spec.get("shapes", []):
        name = s["shape"] + (" cut" if s.get("op") == "cut" else "")
        counts[name] = counts.get(name, 0) + 1
    lines.append("Shapes      " + ", ".join(f"{n} x{c}" if c > 1 else n for n, c in counts.items()))
    stl = folder / "model.stl"
    if stl.is_file():
        from . import printshop
        try:
            lo, hi = printshop.size(printshop.read_stl(stl))
            lines.append("Size        " + " x ".join(f"{h - l:.1f}" for l, h in zip(lo, hi))
                         + " mm (measured from the mesh)")
        except printshop.PrintShopError:
            lines.append("Size        the mesh could not be read")
    else:
        lines.append("Size        not built yet")
    try:
        checks = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
        failed = [c["name"] for c in checks if c["status"] == "FAIL"]
        lines.append("Editor      " + ("passed it" if checks and not failed
                                       else "found a problem: " + ", ".join(failed)))
    except (OSError, ValueError, KeyError, TypeError):
        lines.append("Editor      not checked yet")
    slices = sorted((folder / "print").glob("*-card.txt")) if (folder / "print").is_dir() else []
    for c in slices:
        t = next((l.split(None, 1)[1] for l in c.read_text(encoding="utf-8").splitlines()
                  if l.startswith("Time")), "?")
        lines.append(f"Sliced      {c.name[:-len('-card.txt')]}: {t}")
    if not slices:
        lines.append("Sliced      not yet (the Print Shop)")
    lines.append(f"Written {time.strftime('%Y-%m-%d %H:%M')}.")
    text = "\n".join(lines) + "\n"
    (folder / "card.txt").write_text(text, encoding="utf-8")
    return text
