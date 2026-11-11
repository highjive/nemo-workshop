"""The enclosure, written by code from a layout.

Three real runs on the laptop asked the 1.7B model for a CadQuery script.
The first ran out of time, the second was never executed (D131), and the
third, executed at last, called a method CadQuery does not have. The same
model had no trouble choosing which pin goes to which pin once that was
all it was asked.

So the model is asked the one thing about an enclosure that is a design
decision: where each part sits on the floor. Its answer is a pair of
numbers per part, held to a schema that keeps them inside the box. Code
then checks the layout (inside the walls, nothing overlapping, enough
height), and if the model's layout is no good twice running, lays the
parts out itself. Every line of CadQuery is written here.

What is drawn is deliberately modest, and everything in it traces to a
figure the parts library or the brief already holds:

  - an open tray, to the brief's outer envelope, walls a whole number of
    nozzle widths and no thinner than the printer's minimum
  - a low locating rim round each part's footprint
  - a cable notch in one wall, open to the top
  - ventilation slots, open to the top, if any part draws over 200 mA
  - an opening named cutout_<ref> for each panel-mounted part

No lid, and no screw standoffs: the library does not record where a
part's mounting holes are, and Nemo does not guess a hole position.
Nothing overhangs: every opening is open to the top edge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .parts import Part

RIM_H = 2.0             # locating rim height, mm
RIM_GAP = 0.5           # slack between a part and its rim
CLEARANCE = 1.0         # least space between a rim and anything else
HEADROOM = 2.0          # least space above the tallest part
NOTCH = (12.0, 7.0)     # cable notch, width x depth from the top edge
VENT = (2.0, 10.0)      # one ventilation slot, width x depth from the top edge
VENT_OVER_MA = 200.0
EPS = 1e-6              # two parts exactly the required distance apart are not too close


class EnclosureError(ValueError):
    """No enclosure can be drawn for this. For the owner."""


@dataclass
class Box:
    length: float
    width: float
    height: float
    wall: float

    @property
    def inner(self) -> tuple[float, float, float]:
        return (self.length - 2 * self.wall, self.width - 2 * self.wall,
                self.height - self.wall)


@dataclass
class Placed:
    ref: str
    x: float            # lower-left corner of the footprint, from the inner
    y: float            # floor's own lower-left corner
    dx: float           # footprint along x after any turn
    dy: float
    dz: float


def wall_thickness(min_wall: float, nozzle: float) -> float:
    """The thinnest wall that is a whole number of nozzle widths, at least
    two of them, and no thinner than the printer's minimum."""
    lines = max(2, math.ceil(round(min_wall / nozzle, 6)))
    return round(lines * nozzle, 3)


def box_for(envelope_mm: list[float], hw: dict) -> Box:
    if len(envelope_mm or []) != 3 or min(envelope_mm) <= 0:
        raise EnclosureError("the brief gives no usable envelope (length, width, height)")
    wall = wall_thickness(float(hw.get("min_wall_mm", 1.2)), float(hw.get("nozzle_mm", 0.4)))
    box = Box(float(envelope_mm[0]), float(envelope_mm[1]), float(envelope_mm[2]), wall)
    volume = hw.get("build_volume_mm") or []
    if len(volume) == 3 and (box.length > volume[0] or box.width > volume[1]
                             or box.height > volume[2]):
        raise EnclosureError(f"the envelope {envelope_mm} mm is larger than the "
                             f"printer's build volume {volume} mm")
    if min(box.inner) <= 0:
        raise EnclosureError("the envelope is too small to have an inside")
    return box


def sized(parts: list[Part]) -> list[Part]:
    """Parts that take up floor: those the library gives a size for."""
    return [p for p in parts if len(p.size_mm or []) == 3 and min(p.size_mm) > 0]


def margin() -> float:
    """What a part needs round it: its rim, and clearance beyond."""
    return RIM_GAP + 1.2 + CLEARANCE / 2


def layout_schema(parts: list[Part], box: Box) -> dict:
    """One entry per part, each position bounded by the inside of the box."""
    il, iw, _ = box.inner
    props = {}
    for p in sized(parts):
        props[p.ref] = {
            "type": "object", "additionalProperties": False,
            "required": ["x_mm", "y_mm", "turned"],
            "properties": {"x_mm": {"type": "integer", "minimum": 0, "maximum": int(il)},
                           "y_mm": {"type": "integer", "minimum": 0, "maximum": int(iw)},
                           "turned": {"type": "boolean"}},
        }
    return {"type": "object", "additionalProperties": False, "required": list(props),
            "properties": props}


def part_facts(parts: list[Part], box: Box) -> str:
    il, iw, ih = box.inner
    lines = [f"The floor inside the walls is {il:.0f} mm along x and {iw:.0f} mm along y. "
             f"x_mm and y_mm give a part's corner nearest (0, 0).",
             "Parts (length x width x height, mm):"]
    for p in sized(parts):
        lines.append(f"- {p.ref} ({p.name}): {p.size_mm[0]:g} x {p.size_mm[1]:g} x "
                     f"{p.size_mm[2]:g}, draws {p.draw_ma:g} mA")
    return "\n".join(lines)


def placed_from(doc: dict, parts: list[Part]) -> list[Placed]:
    out = []
    for p in sized(parts):
        at = doc.get(p.ref)
        if not isinstance(at, dict):
            raise EnclosureError(f"the layout does not place {p.ref}")
        x, y = at.get("x_mm"), at.get("y_mm")
        for v in (x, y):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise EnclosureError(f"the layout gives no position for {p.ref}")
        length, width, height = p.size_mm
        if at.get("turned") is True:
            length, width = width, length
        out.append(Placed(p.ref, float(x), float(y), float(length), float(width), float(height)))
    return out


def faults(placed: list[Placed], box: Box) -> list[str]:
    """Everything wrong with a layout, in plain words. [] if it is sound."""
    il, iw, ih = box.inner
    m = margin()
    out = []
    for a in placed:
        if (a.x < m - EPS or a.y < m - EPS or a.x + a.dx > il - m + EPS
                or a.y + a.dy > iw - m + EPS):
            out.append(f"{a.ref} at ({a.x:g}, {a.y:g}) is {a.dx:g} x {a.dy:g} mm and does "
                       f"not fit inside the walls with {m:g} mm to spare (the floor is "
                       f"{il:g} x {iw:g} mm)")
        if a.dz + RIM_H + HEADROOM > ih:
            out.append(f"{a.ref} is {a.dz:g} mm tall and the box is {ih:g} mm deep inside: "
                       "too little room above it")
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            if (a.x - m < b.x + b.dx + m - EPS and b.x - m < a.x + a.dx + m - EPS
                    and a.y - m < b.y + b.dy + m - EPS and b.y - m < a.y + a.dy + m - EPS):
                out.append(f"{a.ref} and {b.ref} overlap or sit closer than "
                           f"{2 * m:g} mm apart")
    return out


def order_schema(parts: list[Part]) -> dict:
    """The parts, each once, in order from one end of the box to the other."""
    refs = [p.ref for p in sized(parts)]
    return {"type": "object", "additionalProperties": False, "required": ["order"],
            "properties": {"order": {"type": "array", "minItems": len(refs),
                                     "maxItems": len(refs), "items": {"enum": refs}}}}


def order_from(doc: dict, parts: list[Part]) -> list[str]:
    """The order the model gave, if it is each part exactly once."""
    refs = [p.ref for p in sized(parts)]
    order = doc.get("order")
    if not isinstance(order, list) or sorted(map(str, order)) != sorted(refs):
        raise EnclosureError("the order does not name each part exactly once")
    return [str(r) for r in order]


def gaps(placed: list[Placed]) -> list[tuple[str, str, float]]:
    """How far apart each pair of parts is, edge to edge, in mm."""
    out = []
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            dx = max(b.x - (a.x + a.dx), a.x - (b.x + b.dx), 0.0)
            dy = max(b.y - (a.y + a.dy), a.y - (b.y + b.dy), 0.0)
            out.append((a.ref, b.ref, round(math.hypot(dx, dy), 1)))
    return out


def warm_part(parts: list[Part]) -> Part | None:
    """The part that will warm the box: the one drawing the most current,
    if it draws enough to matter."""
    # Not a battery, charger or converter: their figure is what they can
    # deliver, not what they draw (D152: the first battery design had the
    # cell named as the part that "draws the most current").
    hot = max((p for p in sized(parts) if p.category != "power"),
              key=lambda p: p.draw_ma, default=None)
    return hot if hot is not None and hot.draw_ma > VENT_OVER_MA else None


def thermal_order(parts: list[Part]) -> list[str] | None:
    """Sensors at one end, the warm part at the other, the rest between.
    None if the project has no warm part or no sensor, so there is nothing
    to keep apart.

    Not left to the model. On the real laptop, given a brief that said
    "the sensor must sit away from the warm ESP32 module", it put the
    sensor in the middle, 4.4 mm from the ESP32. Which part is warm and
    which is a sensor are both in the parts library.
    """
    hot = warm_part(parts)
    sensors = [p for p in sized(parts) if p.category == "sensor" and p is not hot]
    if hot is None or not sensors:
        return None
    rest = [p for p in sized(parts) if p is not hot and p not in sensors]
    rest.sort(key=lambda p: p.size_mm[0] * p.size_mm[1])
    return [p.ref for p in sensors] + [p.ref for p in rest] + [hot.ref]


def nearest_sensor_gap(placed: list[Placed], parts: list[Part]) -> tuple[str, str, float] | None:
    """(sensor, warm part, mm between them) for the sensor nearest the warm
    part, or None if there is no such pair."""
    hot = warm_part(parts)
    if hot is None:
        return None
    sensors = {p.ref for p in sized(parts) if p.category == "sensor" and p is not hot}
    found = [(a if a in sensors else b, hot.ref, d) for a, b, d in gaps(placed)
             if hot.ref in (a, b) and (a in sensors or b in sensors)]
    return min(found, key=lambda t: t[2]) if found else None


def auto_layout(parts: list[Part], box: Box, order: list[str] | None = None) -> list[Placed]:
    """A sound layout made by code: the parts in rows, in the order given,
    or largest first if no order is given.

    The geometry is always code's. Asked for positions, the 1.7B model put
    three parts on top of one another twice running (real run, AH531); so
    it is asked only for the order, which is where the brief's wishes
    about what sits near or far from what can be expressed, and the
    packing is done here.
    """
    il, iw, _ = box.inner
    m = margin()
    todo = sorted(sized(parts), key=lambda p: -(p.size_mm[0] * p.size_mm[1]))
    if order:
        by_ref = {p.ref: p for p in todo}
        todo = [by_ref[r] for r in order if r in by_ref]
    if len(todo) > 10:
        raise EnclosureError("more than ten parts: lay this one out by hand")

    def rows(turns: int) -> list[Placed] | None:
        out: list[Placed] = []
        x, y, row = m, m, 0.0
        for i, p in enumerate(todo):
            length, width, height = p.size_mm
            if turns >> i & 1:
                length, width = width, length
            if x + length > il - m + EPS:           # next row
                x, y, row = m, y + row + 2 * m, 0.0
            if x + length > il - m + EPS or y + width > iw - m + EPS:
                return None
            out.append(Placed(p.ref, round(x, 2), round(y, 2), float(length), float(width),
                              float(height)))
            x += length + 2 * m
            row = max(row, width)
        return out

    # Each part either way round: a board that will not go in lengthways
    # often goes in turned. Fewest turned parts first.
    for turns in sorted(range(1 << len(todo)), key=lambda t: bin(t).count("1")):
        out = rows(turns)
        if out is not None and not faults(out, box):
            return out
    tall = [p.ref for p in todo if p.size_mm[2] + RIM_H + HEADROOM > box.inner[2]]
    if tall:
        raise EnclosureError(f"{tall[0]} is too tall for a box {box.inner[2]:g} mm deep inside")
    raise EnclosureError(
        f"the parts do not fit on a {il:g} x {iw:g} mm floor with room for their "
        "rims, whichever way round they are turned. Make the envelope larger.")


# ONE answer to "do these parts fit this box?" (2026-11-08, mistake 3): the
# parts step summed floor areas and passed a desk weather display at 63 % of
# its floor, and then the concept step, which packs the real parts with their
# rims, said they could not fit. Every check and fix asks this now.
DEFAULT_HW = {"min_wall_mm": 1.2, "nozzle_mm": 0.4}


def layout_fault(parts: list[Part], envelope_mm: list[float], hw: dict | None = None) -> str | None:
    """Why auto_layout cannot place `parts` in this envelope, or None if it can."""
    try:
        auto_layout(parts, box_for(envelope_mm, dict(hw or DEFAULT_HW)))
    except EnclosureError as exc:
        return str(exc)
    return None


def fitting_size(parts: list[Part], envelope_mm: list[float] | None, hw: dict | None = None,
                 step: float = 5.0) -> list[float] | None:
    """The smallest envelope, grown from `envelope_mm` (its proportions kept;
    a 3:2 floor if none) in `step` mm, that auto_layout can pack the parts
    into; None if none up to the printer's build volume does."""
    hw = dict(hw or DEFAULT_HW)
    s = sized(parts)
    if not s:
        return None
    need_h = max(p.size_mm[2] for p in s) + RIM_H + HEADROOM + wall_thickness(
        float(hw.get("min_wall_mm", 1.2)), float(hw.get("nozzle_mm", 0.4)))
    env = list(envelope_mm or [])
    if len(env) != 3 or min(env) <= 0:
        widest = max(max(p.size_mm[0], p.size_mm[1]) for p in s)
        env = [widest * 1.5, widest, need_h]
    L, W = env[0], env[1]
    H = max(env[2], math.ceil(need_h / step) * step)
    for _ in range(200):
        if layout_fault(parts, [L, W, H], hw) is None:
            return [float(L), float(W), float(H)]
        L, W = math.ceil((L + step) / step) * step, math.ceil((W + step * W / L) / step) * step
        volume = hw.get("build_volume_mm") or []
        if len(volume) == 3 and (L > volume[0] or W > volume[1]):
            return None
    return None


def keep_apart_pairs(parts: list[Part]) -> list[tuple[str, str, float]]:
    """(a, b, least mm) for every pair of parts here that the library says
    must be kept apart. Either part may be the one that says so."""
    here = {p.ref for p in sized(parts)}
    need: dict[tuple[str, str], float] = {}
    for p in sized(parts):
        for other, mm in (p.keep_apart or {}).items():
            if other in here and other != p.ref:
                key = tuple(sorted((p.ref, other)))
                need[key] = max(need.get(key, 0.0), float(mm))
    return [(a, b, mm) for (a, b), mm in sorted(need.items())]


def too_close(placed: list[Placed], parts: list[Part]) -> list[tuple[str, str, float, float]]:
    """(a, b, least mm, actual mm) for each such pair this layout puts too
    near. Edge to edge of the two footprints, so it errs on the far side."""
    got = {tuple(sorted((a, b))): d for a, b, d in gaps(placed)}
    return [(a, b, mm, got[(a, b)]) for a, b, mm in keep_apart_pairs(parts)
            if (a, b) in got and got[(a, b)] < mm - EPS]


def spread(placed: list[Placed], box: Box) -> list[Placed]:
    """The same rows, with the last part of each row pushed to the far wall
    and the last row pushed to the far side. Rows packed from one corner
    leave the spare floor empty at the other; this uses it for distance."""
    il, iw, _ = box.inner
    m = margin()
    rows: dict[float, list[Placed]] = {}
    for a in placed:
        rows.setdefault(a.y, []).append(a)
    out = []
    last_y = max(rows)
    for y, row in sorted(rows.items()):
        row = sorted(row, key=lambda a: a.x)
        new_y = y
        if y == last_y and len(rows) > 1:
            new_y = round(iw - m - max(a.dy for a in row), 2)
        for i, a in enumerate(row):
            x = round(il - m - a.dx, 2) if i == len(row) - 1 and len(row) > 1 else a.x
            out.append(Placed(a.ref, x, new_y, a.dx, a.dy, a.dz))
    return out


def layout_keeping_apart(parts: list[Part], box: Box, prefer: list[list[str]]
                         ) -> tuple[list[Placed] | None, list[str], float]:
    """A sound layout in which every keep-apart pair is far enough apart.

    Tries the orders in `prefer` first, as they are and then spread, and
    after them every order of the parts (up to six parts; 720 orders).
    Among layouts that satisfy every pair, the first found is taken unless
    a sensor can be put further from the warm part. Returns (layout, its
    order, 0.0), or (None, [], the shortfall in mm of the best layout
    found) when nothing in this envelope will do.
    """
    import itertools
    refs = [p.ref for p in sized(parts)]
    orders = [o for o in prefer if o]
    if len(refs) <= 6:
        orders += [list(o) for o in itertools.permutations(refs)]
    best, best_key, least_short = None, None, float("inf")
    seen = set()
    for n, order in enumerate(orders):
        if tuple(order) in seen:
            continue
        seen.add(tuple(order))
        try:
            base = auto_layout(parts, box, order)
        except EnclosureError:
            continue
        for candidate in (base, spread(base, box)):
            if faults(candidate, box):
                continue
            short = too_close(candidate, parts)
            if short:
                least_short = min(least_short, max(mm - got for _, _, mm, got in short))
                continue
            gap = nearest_sensor_gap(candidate, parts)
            key = (gap[2] if gap else 0.0, -n)
            if best is None or key > best_key:
                best, best_key = (candidate, list(order)), key
        if best is not None and n < len(prefer) and nearest_sensor_gap(best[0], parts) is None:
            break                       # a preferred order works; nothing to improve on
    if best is None:
        return None, [], (least_short if least_short != float("inf") else 0.0)
    return best[0], best[1], 0.0


CORNER_R = 4.0          # outer corner radius of a rounded tray, mm
NOTCH_WALLS = ("left", "front")


def corner_radius(box: Box) -> float:
    """A rounded tray's outer corner radius: CORNER_R, and always more than
    the wall, so the inside corner (this less the wall) is rounded too."""
    return max(CORNER_R, round(box.wall + 1.0, 3))


@dataclass(frozen=True)
class WallCut:
    """A cut in a wall, open to its top edge: what cadquery_script cuts,
    in numbers (nemo/drawings.py draws them; a test holds the two together)."""
    name: str           # "cable notch", "vent 1", or the part's ref
    wall: str           # "left" (x = 0), "right" (x = length), "front" (y = 0), "back" (y = width)
    centre: float       # along the wall: x for front/back, y for left/right, from the outer corner
    width: float
    depth: float        # down from the top edge


def wall_cuts(placed: list[Placed], parts: list[Part], box: Box,
              notch_wall: str = "left") -> list[WallCut]:
    """Every cut cadquery_script makes, by the same formulas."""
    if not placed:
        return []
    by_ref = {p.ref: p for p in parts}
    _, _, ih = box.inner
    mcu = next((a for a in placed if by_ref[a.ref].category == "mcu"), placed[0])
    out = []
    if notch_wall == "front":
        out.append(WallCut("cable notch", "front", box.wall + mcu.x + mcu.dx / 2, *NOTCH))
    else:
        out.append(WallCut("cable notch", "left", box.wall + mcu.y + mcu.dy / 2, *NOTCH))
    if any(by_ref[a.ref].draw_ma > VENT_OVER_MA for a in placed):
        for k in range(3):
            out.append(WallCut(f"vent {k + 1}", "right",
                               box.width / 2 + (k - 1) * 3 * VENT[0], *VENT))
    for a in placed:
        if by_ref[a.ref].mount == "panel":
            out.append(WallCut(a.ref, "back", box.wall + a.x + a.dx / 2, a.dx, min(a.dz, ih - 1)))
    return out


def cadquery_script(placed: list[Placed], parts: list[Part], box: Box,
                    corners: str = "square", notch_wall: str = "left") -> str:
    """A complete CadQuery script for this layout.

    Every call in it was run against real CadQuery 2.8.0 on the AH531.
    `corners` ("square" or "rounded": the four upright outer edges given a
    CORNER_R radius) and `notch_wall` ("left", the wall at x = 0, or
    "front", the wall at y = 0) are the Artist's concept (nemo/concept.py);
    the defaults are the tray Nemo has always drawn.
    """
    if corners not in ("square", "rounded"):
        raise EnclosureError(f"unknown corners {corners!r}")
    if notch_wall not in NOTCH_WALLS:
        raise EnclosureError(f"unknown cable-notch wall {notch_wall!r}")
    problems = faults(placed, box)
    if problems:
        raise EnclosureError(problems[0])
    by_ref = {p.ref: p for p in parts}
    il, iw, ih = box.inner
    L = [
        "# Written by Nemo from the layout chosen for this project.",
        "# Do not edit by hand: the enclosure step rewrites it. Every number is a",
        "# named variable; change the layout or the brief instead.",
        "import cadquery as cq",
        "from cadquery import exporters",
        "",
        "# The brief's envelope, and a wall that is a whole number of nozzle widths.",
        f"length, width, height = {box.length:g}, {box.width:g}, {box.height:g}",
        f"wall = {box.wall:g}",
        f"rim_height, rim_gap, rim_wall = {RIM_H:g}, {RIM_GAP:g}, 1.2",
        "",
        "# An open tray: the outside, less the inside, open at the top.",
    ]
    if corners == "rounded":
        # The inside corners are rounded too, about the same centres, so the
        # wall is as thick at a corner as along a side. Rounded outside only,
        # a 4 mm corner over a square inside was 0.6 mm thick at the corner
        # and failed the thickness check (2026-10-20).
        L += [f"corner_radius = {corner_radius(box):g}   # the four upright edges, outside; inside, less the wall",
              "housing = (cq.Workplane(\"XY\").box(length, width, height, centered=(False, False, False))",
              "           .edges(\"|Z\").fillet(corner_radius)",
              "           .cut(cq.Workplane(\"XY\").workplane(offset=wall)",
              "                .box(length - 2 * wall, width - 2 * wall, height,",
              "                     centered=(False, False, False))",
              "                .edges(\"|Z\").fillet(corner_radius - wall).translate((wall, wall, 0))))",
              ""]
    else:
        L += ["housing = (cq.Workplane(\"XY\").box(length, width, height, centered=(False, False, False))",
              "           .cut(cq.Workplane(\"XY\").workplane(offset=wall)",
              "                .box(length - 2 * wall, width - 2 * wall, height,",
              "                     centered=(False, False, False)).translate((wall, wall, 0))))",
              ""]
    L += [
        "# A low rim round each part, so it drops into place and cannot slide.",
    ]
    for a in placed:
        v = "p_" + a.ref
        L += [f"{v} = ({a.x:g}, {a.y:g}, {a.dx:g}, {a.dy:g})   # x, y, size along x, size along y",
              f"rim_{a.ref} = (cq.Workplane(\"XY\").workplane(offset=wall)",
              f"    .center(wall + {v}[0] + {v}[2] / 2, wall + {v}[1] + {v}[3] / 2)",
              f"    .rect({v}[2] + 2 * (rim_gap + rim_wall), {v}[3] + 2 * (rim_gap + rim_wall))",
              f"    .rect({v}[2] + 2 * rim_gap, {v}[3] + 2 * rim_gap)",
              "    .extrude(rim_height))",
              f"housing = housing.union(rim_{a.ref})",
              ""]

    if not placed:
        # No parts (the brief's No parts needed): a plain open tray, with
        # no cable notch, since no cable goes anywhere.
        L += ['exporters.export(housing, "housing.step")',
              'exporters.export(housing, "housing.stl")', ""]
        return "\n".join(L)
    mcu = next((a for a in placed if by_ref[a.ref].category == "mcu"), placed[0])
    if notch_wall == "front":
        L += ["# A notch for the cable, in the wall at y = 0, opposite the microcontroller,",
              "# open to the top edge so that nothing overhangs.",
              f"notch_width, notch_depth = {NOTCH[0]:g}, {NOTCH[1]:g}",
              f"notch_x = wall + {mcu.x:g} + {mcu.dx:g} / 2",
              "cutout_cable = (cq.Workplane(\"XY\")",
              "    .box(notch_width, wall * 3, notch_depth, centered=(True, True, False))",
              "    .translate((notch_x, wall / 2, height - notch_depth)))",
              "housing = housing.cut(cutout_cable)",
              ""]
    else:
        L += ["# A notch for the cable, in the wall at x = 0, opposite the microcontroller,",
              "# open to the top edge so that nothing overhangs.",
              f"notch_width, notch_depth = {NOTCH[0]:g}, {NOTCH[1]:g}",
              f"notch_y = wall + {mcu.y:g} + {mcu.dy:g} / 2",
              "cutout_cable = (cq.Workplane(\"XY\")",
              "    .box(wall * 3, notch_width, notch_depth, centered=(True, True, False))",
              "    .translate((wall / 2, notch_y, height - notch_depth)))",
              "housing = housing.cut(cutout_cable)",
              ""]
    if any(by_ref[a.ref].draw_ma > VENT_OVER_MA for a in placed):
        L += [f"# Ventilation: a part here draws over {VENT_OVER_MA:g} mA. Slots in the wall at",
              "# x = length, open to the top edge.",
              f"vent_width, vent_depth = {VENT[0]:g}, {VENT[1]:g}",
              "for k in range(3):",
              "    slot = (cq.Workplane(\"XY\")",
              "        .box(wall * 3, vent_width, vent_depth, centered=(True, True, False))",
              "        .translate((length - wall / 2, width / 2 + (k - 1) * 3 * vent_width,",
              "                    height - vent_depth)))",
              "    housing = housing.cut(slot)",
              ""]
    for a in placed:
        part = by_ref[a.ref]
        if part.mount == "panel":
            L += [f"# {a.ref} mounts through the wall at y = width.",
                  f"cutout_{a.ref} = (cq.Workplane(\"XY\")",
                  f"    .box({a.dx:g}, wall * 3, {min(a.dz, ih - 1):g}, centered=(True, True, False))",
                  f"    .translate((wall + {a.x:g} + {a.dx:g} / 2, width - wall / 2, "
                  f"height - {min(a.dz, ih - 1):g})))",
                  f"housing = housing.cut(cutout_{a.ref})",
                  ""]
    L += ['exporters.export(housing, "housing.step")',
          'exporters.export(housing, "housing.stl")', ""]
    return "\n".join(L)
