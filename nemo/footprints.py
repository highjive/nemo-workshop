"""Footprints for the parts, and where each still needs one (owner, 2026-11-04:
"add footprints to the parts").

Some parts have one from a source anyone can check (the library's own entries:
KiCad's curated footprint with the maker's pin table). A breakout module's
header order differs between makers of "the same" module (BME280 boards come
with 4 pins and with 6, in different orders), and the library does not say
whose board the owner has. So the source for a module is THE MODULE HE HAS:
its pins are printed on it. header() writes what he read off it, in order, as
a pin-socket footprint into HIS parts folder (paths.parts), which overrides
the bundled entry; it never edits the bundled library.

  nemo footprint                         each part: its footprint, or why not
  nemo footprint header <ref> <pin> ...  pins as printed, left to right; "-"
                                         for a header pin Nemo does not use
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from pathlib import Path

import yaml

SOCKET = "Connector_PinSocket_2.54mm:PinSocket_1x{n:02d}_P2.54mm_Vertical"
UNUSED = "-"


def socket_for(n: int) -> str:
    return SOCKET.format(n=n)


def status(lib, kicad_root: Path | None) -> list[tuple[str, str, str]]:
    """(ref, footprint or '', what is missing) for every part."""
    from . import pcb
    out = []
    for p in sorted(lib, key=lambda p: p.ref):
        if not p.footprint:
            out.append((p.ref, "", "no footprint: read its header off your module "
                        "(nemo footprint header), or it is wired by its leads"))
            continue
        why = []
        if kicad_root is not None and pcb.footprint_file(p.footprint, kicad_root) is None:
            why.append("not in KiCad's libraries")
        unpadded = [q.name for q in p.pins if q.name not in p.pads]
        if unpadded:
            why.append("no pad for " + ", ".join(unpadded))
        if not p.footprint_source:
            why.append("no source given")
        out.append((p.ref, p.footprint, "; ".join(why)))
    return out


def header(part, order: list[str], parts_root: Path, today: dt.date | None = None) -> Path:
    """Write `part` with a 1xN pin socket in the order read off the module.
    Raises ValueError for a name the part has not, a pin named twice, or a
    pin of the part's left out."""
    names = [q.name for q in part.pins]
    used = [n for n in order if n != UNUSED]
    unknown = [n for n in used if n not in names]
    if unknown:
        raise ValueError(f"{part.ref} has no pin called {', '.join(unknown)}; its pins are "
                         f"{', '.join(names)} (use - for a header pin Nemo does not use)")
    twice = sorted({n for n in used if used.count(n) > 1})
    if twice:
        raise ValueError(f"named twice: {', '.join(twice)}")
    left = [n for n in names if n not in used]
    if left:
        raise ValueError(f"not on the header you gave: {', '.join(left)}. Every pin of the part "
                         "must be somewhere on it")
    if not 1 <= len(order) <= 40:
        raise ValueError("a header has between 1 and 40 pins")
    raw = {k: v for k, v in asdict(part).items() if k != "ref"}
    raw["pins"] = [{k: v for k, v in pin.items() if v not in (None, "", False)} for pin in raw["pins"]]
    raw = {k: v for k, v in raw.items() if v not in (None, "", [], {}) or k in ("name", "category")}
    raw["footprint"] = socket_for(len(order))
    raw["pads"] = {n: str(i + 1) for i, n in enumerate(order) if n != UNUSED}
    raw["footprint_source"] = (f"read off the owner's own module on {(today or dt.date.today()).isoformat()}, "
                               f"header left to right: {' '.join(order)}")
    out = Path(parts_root) / f"{part.ref}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# The owner's own module (nemo footprint header). Overrides the bundled entry.\n"
                   + yaml.safe_dump({part.ref: raw}, sort_keys=False, allow_unicode=True),
                   encoding="utf-8")
    return out
