"""Joints: a model too big for the printer, split into pieces that fit and
pinned back together (owner, 2026-11-04: "objects for 3D printing including
any joints needed"; until then the Editor failed such a model and nothing
more could be done, O38).

The Art Studio's Designer does it (no new employee). All of it is code; the model of language is asked
nothing (docs/design-rules.md 4d):

  1. Plan, from the built mesh (model.stl), with numpy: the axis that is too
     long, how many pieces, where to cut, and where on each cut face the
     alignment pins go. A pin goes only where there is solid round it, a
     wall of hardware.min_wall_mm, for its whole depth on both sides.
     The largest pin that leaves room for two is chosen (two stop a piece
     turning); else one; else none, and the joint is glued, which is said.
  2. Code writes the CadQuery script (joints.py beside model.py): the same
     shapes, the holes bored, the model cut into pieces, the pins made as
     parts of their own. CadQuery cuts exactly; the mesh only plans.
  3. The Editor checks every piece (closed, walls, fits the printer).

Pins are printed apart, lying down on a flat filed into one side: printed
upright, a pin's layers would lie across the joint, where it shears.
Holes are bored CLEARANCE_MM wider than the pin all round. That figure is a
RULE OF THUMB for FDM printers, not measured on this printer: if the pins
are too tight or loose, change joints.clearance_mm in config.yaml.

Only one axis may be too long: a model too big two ways is refused, saying
so. Pieces are cut square across; a cut through a thin part may leave no
room for a pin, and the planner moves the cut a little to find some.
"""
from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

CLEARANCE_MM = 0.15          # per side; a rule of thumb for FDM pins (see above)
PIN_DIAMETERS = (6.0, 5.0, 4.0, 3.0)
PIN_DEPTH_MM = 8.0           # into each piece
EDGE_MM = 5.0                # kept clear at each end of the bed (the slicer's skirt, the border)
GRID_MM = 1.0                # where pins are looked for: a grid this fine
FLAT_MM = 0.4                # filed off one side of a pin so it lies still to print


class SplitError(ValueError):
    """The model cannot be split as asked; the message says why."""


@dataclass
class Pin:
    u: float
    v: float
    diameter: float


@dataclass
class Cut:
    axis: int                # 0 x, 1 y, 2 z: the cut is square across this axis
    at: float
    pins: list[Pin] = field(default_factory=list)
    moved: float = 0.0       # how far the cut was moved from even spacing


@dataclass
class Plan:
    lo: list[float]          # the model's bounds
    hi: list[float]
    cuts: list[Cut]
    clearance: float
    depth: float
    notes: list[str] = field(default_factory=list)
    # Parts of cut faces with none of the model on them: [axis, at, u0, u1, v0, v1].
    # The pieces either side do not meet there; they are not a joint.
    apart: list[list[float]] = field(default_factory=list)
    # Cells of the grid with none of the model in them, [ix, iy, iz]: no piece.
    empty: list[list[int]] = field(default_factory=list)

    def at(self, axis: int) -> list[float]:
        return sorted(c.at for c in self.cuts if c.axis == axis)

    @property
    def axes(self) -> list[int]:
        return sorted({c.axis for c in self.cuts})

    @property
    def pieces(self) -> int:
        return len(self.cells())

    def ranges(self, axis: int) -> list[tuple[float, float]]:
        e = [self.lo[axis]] + self.at(axis) + [self.hi[axis]]
        return list(zip(e, e[1:]))

    def _grid(self) -> list[tuple[tuple[int, int, int], list[tuple[float, float]]]]:
        """Every cell of the cuts' grid, x fastest, then y, then z."""
        return [((ix, iy, iz), [rx, ry, rz])
                for iz, rz in enumerate(self.ranges(2))
                for iy, ry in enumerate(self.ranges(1))
                for ix, rx in enumerate(self.ranges(0))]

    def cells(self) -> list[tuple[int, list[tuple[float, float]]]]:
        """Each piece: its number (1 up, x fastest, then y, then z) and its
        span on each axis. A cell with none of the model in it is no piece,
        and is not numbered."""
        out = []
        for idx, spans in self._grid():
            if list(idx) not in self.empty:
                out.append((len(out) + 1, spans))
        return out

    def piece_at(self, point) -> int:
        """The number of the piece a point is in; 0 in an empty cell."""
        idx = [sum(1 for c in self.at(a) if point[a] > c) for a in range(3)]
        n = 0
        for cell, _ in self._grid():
            if list(cell) in self.empty:
                continue
            n += 1
            if list(cell) == idx:
                return n
        return 0


def _others(axis: int) -> tuple[int, int]:
    return tuple(i for i in range(3) if i != axis)


# ------------------------------------------------------------ the mesh's sections
def section(mesh, axis: int, at: float):
    """The cross-section at `at` along `axis`, as 2-D segments (n, 2, 2) in
    the other two axes. Empty where the plane misses the mesh."""
    import numpy as np
    from trimesh.intersections import mesh_plane
    normal = [0.0, 0.0, 0.0]; normal[axis] = 1.0
    origin = [0.0, 0.0, 0.0]; origin[axis] = at
    segs = mesh_plane(mesh, normal, origin)
    if len(segs) == 0:
        return np.zeros((0, 2, 2))
    u, v = _others(axis)
    return np.asarray(segs)[:, :, [u, v]]


def inside(points, segs):
    """Each 2-D point inside the closed outline the segments make (even-odd
    rule, a ray along +u)."""
    import numpy as np
    pts = np.asarray(points, dtype=float)
    if len(segs) == 0 or len(pts) == 0:
        return np.zeros(len(pts), dtype=bool)
    a, b = segs[:, 0, :], segs[:, 1, :]
    py = pts[:, 1][:, None]; px = pts[:, 0][:, None]
    ay, by = a[:, 1][None, :], b[:, 1][None, :]
    ax, bx = a[:, 0][None, :], b[:, 0][None, :]
    crosses = (ay > py) != (by > py)
    with np.errstate(divide="ignore", invalid="ignore"):
        x_at = ax + (py - ay) * (bx - ax) / (by - ay)
    hits = crosses & (x_at > px)
    return (hits.sum(axis=1) % 2) == 1


def edge_distance(points, segs):
    """Each 2-D point's distance to the nearest segment."""
    import numpy as np
    pts = np.asarray(points, dtype=float)
    if len(segs) == 0:
        return np.full(len(pts), np.inf)
    a, b = segs[:, 0, :][None], segs[:, 1, :][None]
    p = pts[:, None, :]
    ab = b - a
    t = np.clip(((p - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-12), 0, 1)
    nearest = a + t[..., None] * ab
    return np.sqrt(((p - nearest) ** 2).sum(-1)).min(axis=1)


class Body:
    """What is planned on: one closed mesh (a built model.stl), or a concept's
    shapes as they are before they are joined (overlapping adds, then cuts).
    A point is solid if it is in an add and in no cut. Its wall is measured
    to the edge of the add it is in, and to any cut: where shapes overlap the
    real wall can only be thicker, so the plan errs safe."""

    def __init__(self, adds, cuts=()):
        import numpy as np
        self.adds, self.cuts = list(adds), list(cuts)
        b = np.array([m.bounds for m in self.adds])
        self.bounds = (b[:, 0].min(axis=0), b[:, 1].max(axis=0))

    def solid(self, axis, at, pts, walls: bool = True):
        """(inside, wall) for 2-D points on the plane at `at`; wall is not
        measured (zeros) when walls is False. Each shape tests only the points
        inside its own outline's box: testing every point against every shape
        was most of a concept's planning time."""
        import numpy as np
        pts = np.asarray(pts, dtype=float)
        ins = np.zeros(len(pts), dtype=bool)
        wall = np.zeros(len(pts))

        def near(segs):
            flat = segs.reshape(-1, 2)
            lo, hi = flat.min(axis=0), flat.max(axis=0)
            return np.nonzero((pts[:, 0] >= lo[0]) & (pts[:, 0] <= hi[0])
                              & (pts[:, 1] >= lo[1]) & (pts[:, 1] <= hi[1]))[0]
        for m in self.adds:
            segs = section(m, axis, at)
            if len(segs) == 0:
                continue
            idx = near(segs)
            if len(idx) == 0:
                continue
            here = idx[inside(pts[idx], segs)]
            if walls and len(here):
                wall[here] = np.maximum(wall[here], edge_distance(pts[here], segs))
            ins[here] = True
        for m in self.cuts:
            segs = section(m, axis, at)
            if len(segs) == 0:
                continue
            idx = near(segs)
            if len(idx):
                ins[idx[inside(pts[idx], segs)]] = False
            if walls:
                wall = np.minimum(wall, edge_distance(pts, segs))
        return ins, wall


def _body(thing) -> Body:
    return thing if isinstance(thing, Body) else Body([thing])


def _room(body, axis, at, depth, need, grid):
    """Points on the cut face with `need` mm of solid round them at every
    depth a pin reaches, on both sides of the cut."""
    import numpy as np
    body = _body(body)
    u, v = _others(axis)
    lo, hi = body.bounds
    def axis_points(a, b):
        # Centred on the middle, so a part just thick enough gets its pin in
        # the middle, not a grid step off it.
        if b < a:
            return np.zeros(0)
        mid, half = (a + b) / 2, (b - a) / 2
        k = np.arange(-math.floor(half / grid + 1e-9), math.floor(half / grid + 1e-9) + 1)
        return mid + k * grid
    us = axis_points(lo[u] + need, hi[u] - need)
    vs = axis_points(lo[v] + need, hi[v] - need)
    if len(us) == 0 or len(vs) == 0:
        return np.zeros((0, 2))
    pts = np.array([(a, b) for a in us for b in vs])
    for off in (-depth, -depth / 2, -0.5, 0.5, depth / 2, depth):
        ok, wall = body.solid(axis, at + off, pts)
        pts = pts[ok & (wall >= need)]
        if len(pts) == 0:
            break
    return pts


def area(body, axis: int, at: float) -> float:
    """The cut face's area, in mm2, counted on a grid (no polygon library)."""
    import numpy as np
    body = _body(body)
    u, v = _others(axis)
    lo, hi = body.bounds
    step = max(0.25, math.sqrt((hi[u] - lo[u]) * (hi[v] - lo[v]) / 20000))
    us = np.arange(lo[u] + step / 2, hi[u], step)
    vs = np.arange(lo[v] + step / 2, hi[v], step)
    if len(us) == 0 or len(vs) == 0:
        return 0.0
    pts = np.array([(a, b) for a in us for b in vs])
    return float(body.solid(axis, at, pts, walls=False)[0].sum()) * step * step


def _two_apart(pts):
    """Two of the points far apart: the one farthest from their middle, then
    the one farthest from it."""
    import numpy as np
    mid = pts.mean(axis=0)
    a = pts[np.argmax(((pts - mid) ** 2).sum(1))]
    b = pts[np.argmax(((pts - a) ** 2).sum(1))]
    return a, b


def plan(mesh, volume, min_wall: float, clearance: float = CLEARANCE_MM,
         depth: float = PIN_DEPTH_MM, grid: float = GRID_MM) -> Plan:
    """Where to cut and where the pins go; SplitError if it cannot be done.
    `mesh` is a closed mesh or a Body of shapes."""
    mesh = _body(mesh)
    lo, hi = [list(map(float, b)) for b in mesh.bounds]
    size = [h - l for l, h in zip(lo, hi)]
    room = [float(v) - 2 * EDGE_MM for v in volume]
    over = [i for i in range(3) if size[i] > float(volume[i])]
    if not over:
        raise SplitError("it fits the printer whole: nothing to split")
    out = Plan(lo, hi, [], clearance, depth)
    # 1. Where to cut, on every axis that is too long (owner, 2026-11-04: "if
    #    parts are too large for printer have them separated"): as many even
    #    pieces as fit, each cut moved up to a tenth of a piece to where it
    #    crosses least of the model. A sign's cut went through a letter,
    #    leaving a sliver of it on the next piece; counting the face's edges
    #    instead of its area chose a letter's straight stroke.
    for axis in over:
        n = math.ceil(size[axis] / room[axis])
        piece = size[axis] / n
        if piece < 2 * depth + 4:
            raise SplitError(f"the pieces along {'xyz'[axis]} would be too short for pins")
        slack = min(piece * 0.1, (room[axis] - piece) if room[axis] > piece else 0)
        faces = _square_faces(mesh, axis)
        clear = max(2 * min_wall, 2.0)
        for k in range(1, n):
            even = lo[axis] + piece * k
            tries = [0.0] + [s * float(d) for d in range(1, int(slack) + 1) for s in (1, -1)]
            # Never on (or just beside) a face square to the cut: the blunderbuss's
            # cuts fell exactly on its barrel's end and its stock's end, where the
            # face is smallest, and left slivers 0.00 and 0.10 mm thick (2026-11-04).
            ok = [o for o in tries if all(abs(even + o - f) >= clear for f in faces)]
            if not ok:                                  # faces everywhere: half a step off
                ok = [o + clear / 2 for o in tries]
            off = min(ok, key=lambda o: (round(area(mesh, axis, even + o), 1), abs(o)))
            out.cuts.append(Cut(axis, even + off, [], off))
    # Cells the model does not reach (beside a gun's barrel, say) are no piece.
    for idx, spans in out._grid():
        if not _cell_has_model(mesh, spans):
            out.empty.append(list(idx))
    # 2. The pins. A cut face crossed by cuts on other axes is several joints,
    #    each between two other pieces: each gets its own pins, kept clear of
    #    those other cuts. Best first: two pins with twice the minimum wall
    #    round them, then two with the minimum, then one; the largest pin that
    #    does it. None: the joint is glued, and that is said.
    for c in out.cuts:
        u, v = _others(c.axis)
        spans_u = out.ranges(u)
        spans_v = out.ranges(v)
        # The search grid: GRID_MM on a small face, coarser on a big one (about
        # 6000 points): a 370 x 144 mm face at 1 mm took half a minute a cut here.
        step = max(grid, math.sqrt((hi[u] - lo[u]) * (hi[v] - lo[v]) / 6000))
        found = {}
        for wall in (2 * min_wall, min_wall):
            for d_pin in PIN_DIAMETERS:
                need = d_pin / 2 + clearance + wall
                pts = _room(mesh, c.axis, c.at, depth, need, step)
                for su in spans_u:
                    for sv in spans_v:
                        if len(found.get((su, sv), [])) == 2:
                            continue
                        mu = [need if su[0] in out.at(u) else 0, need if su[1] in out.at(u) else 0]
                        mv = [need if sv[0] in out.at(v) else 0, need if sv[1] in out.at(v) else 0]
                        here = pts[(pts[:, 0] >= su[0] + mu[0]) & (pts[:, 0] <= su[1] - mu[1])
                                   & (pts[:, 1] >= sv[0] + mv[0]) & (pts[:, 1] <= sv[1] - mv[1])] \
                            if len(pts) else pts
                        # Clear of every hole already bored for another joint: where two
                        # cuts cross, an x pin's hole and a y pin's ran into each other,
                        # leaving 0.09 mm between them (the blunderbuss, 2026-11-04).
                        here = _clear_of_holes(here, out, c, d_pin, wall, depth)
                        if len(here) >= 2:
                            a, b = _two_apart(here)
                            if math.dist(a, b) >= d_pin + 2 * need:
                                found[(su, sv)] = [Pin(*map(float, a), d_pin), Pin(*map(float, b), d_pin)]
                                continue
                        if len(here) and (su, sv) not in found:
                            found[(su, sv)] = [Pin(*map(float, here[len(here) // 2]), d_pin)]
        for su in spans_u:
            for sv in spans_v:
                pins = found.get((su, sv), [])
                c.pins += pins
                if not _touches(mesh, c, su, sv, u, v):
                    out.apart.append([c.axis, c.at, su[0], su[1], sv[0], sv[1]])
                    continue                           # no model there: no joint
                where = f"{'xyz'[c.axis]} {c.at:.0f}" + (
                    "" if len(spans_u) == len(spans_v) == 1 else
                    f" ({'xyz'[u]} {su[0]:.0f} to {su[1]:.0f}, {'xyz'[v]} {sv[0]:.0f} to {sv[1]:.0f})")
                if not pins:
                    out.notes.append(f"joint at {where}: no room for a pin; glue it")
                elif len(pins) == 1:
                    out.notes.append(f"joint at {where}: room for one pin only; it may turn until glued")
    return out


def _clear_of_holes(pts, out: Plan, c: Cut, d_pin: float, wall: float, depth: float):
    """The candidate points whose hole (along c.axis, depth + 0.5 each side of
    the cut) keeps `wall` of solid from every hole already placed on other cuts."""
    import numpy as np
    if len(pts) == 0:
        return pts
    u, v = _others(c.axis)
    reach = depth + 0.5
    keep = np.ones(len(pts), dtype=bool)
    for o in out.cuts:
        if o is c or not o.pins:
            continue
        ou, ov = _others(o.axis)
        for q in o.pins:
            # The other hole as a segment: along o.axis from o.at - reach to o.at + reach.
            other = [0.0, 0.0, 0.0]
            other[o.axis], other[ou], other[ov] = o.at, q.u, q.v
            need = d_pin / 2 + q.diameter / 2 + 2 * out.clearance + wall
            gap2 = np.zeros(len(pts))
            for ax in range(3):
                # Each candidate hole's centre line, coordinate by coordinate.
                if ax == c.axis:
                    mine_lo, mine_hi = np.full(len(pts), c.at - reach), np.full(len(pts), c.at + reach)
                else:
                    col = pts[:, 0] if ax == u else pts[:, 1]
                    mine_lo = mine_hi = col
                if ax == o.axis:
                    th_lo, th_hi = o.at - reach, o.at + reach
                else:
                    th_lo = th_hi = other[ax]
                # The least distance between two intervals on this axis.
                g = np.maximum(0.0, np.maximum(mine_lo - th_hi, th_lo - mine_hi))
                gap2 += g * g
            keep &= np.sqrt(gap2) >= need
    return pts[keep]


def _square_faces(body, axis: int) -> list[float]:
    """Where along `axis` the model has a flat face square to it (an end of a
    box, a barrel, a stock): a cut there leaves a sliver."""
    import numpy as np
    out = set()
    for m in body.adds + body.cuts:
        n = m.face_normals[:, axis]
        flat = np.abs(n) > 0.999
        if flat.any():
            out.update(np.round(m.triangles_center[flat, axis], 3).tolist())
    return sorted(out)


def _cell_has_model(body, spans) -> bool:
    """Any of the model inside this box: sections across x, a grid on each."""
    import numpy as np
    (x0, x1), (y0, y1), (z0, z1) = spans
    ys = np.linspace(y0, y1, 16)[1:-1]
    zs = np.linspace(z0, z1, 16)[1:-1]
    pts = np.array([(a, b) for a in ys for b in zs])
    return any(body.solid(0, x, pts, walls=False)[0].any() for x in np.linspace(x0, x1, 12)[1:-1])


def _touches(body, c: Cut, su, sv, u: int, v: int) -> bool:
    """Is there any of the model on this part of the cut face?"""
    import numpy as np
    us = np.linspace(su[0], su[1], 24)[1:-1]
    vs = np.linspace(sv[0], sv[1], 24)[1:-1]
    pts = np.array([(a, b) for a in us for b in vs])
    return bool(len(pts) and body.solid(c.axis, c.at, pts, walls=False)[0].any())


# ------------------------------------------------------------ the CadQuery script
def _point(axis: int, at: float, u: float, v: float) -> list[float]:
    p = [0.0, 0.0, 0.0]
    a, b = _others(axis)
    p[axis], p[a], p[b] = at, u, v
    return [round(float(c), 4) for c in p]


def script(base: str, p: Plan) -> str:
    """The model's own script (modelkit.script) with its export taken off,
    then the holes, the pieces and the pins. Written by code."""
    body = [ln for ln in base.splitlines() if not ln.startswith("cq.exporters.export(model")]
    lines = body + [
        "", "# Joints: written by Nemo's Art Studio Designer (nemo/joints.py) from joints.json.",
        "def along(axis, r, length, at):",
        "    w = cq.Workplane('XY').circle(r).extrude(length).translate((0, 0, -length / 2))",
        "    if axis == 0:",
        "        w = w.rotate((0, 0, 0), (0, 1, 0), 90)",
        "    elif axis == 1:",
        "        w = w.rotate((0, 0, 0), (1, 0, 0), -90)",
        "    return w.translate(tuple(at))",
        "",
    ]
    hole_len = 2 * (p.depth + 0.5)
    for c in p.cuts:
        for pin in c.pins:
            at = _point(c.axis, c.at, pin.u, pin.v)
            lines.append(f"model = model.cut(along({c.axis}, {pin.diameter / 2 + p.clearance}, "
                         f"{hole_len}, {at}))")
    for k, spans in p.cells():
        # The outer faces of the model reach a little past it, so nothing is shaved.
        size, mid = [], []
        for a, (s0, s1) in enumerate(spans):
            s0 = s0 - 1 if s0 == p.lo[a] else s0
            s1 = s1 + 1 if s1 == p.hi[a] else s1
            size.append(round(s1 - s0, 4)); mid.append(round((s0 + s1) / 2, 4))
        lines += [f"box = cq.Workplane('XY').box({size[0]}, {size[1]}, {size[2]}).translate({tuple(mid)})",
                  f"cq.exporters.export(model.intersect(box), 'pieces/piece-{k}.stl', "
                  "tolerance=0.05, angularTolerance=0.1)"]
    pins = [pin for c in p.cuts for pin in c.pins]
    if pins:
        lines.append("pins = None")
        y = 0.0
        for pin in pins:
            r, length = pin.diameter / 2, round(2 * p.depth - 0.6, 3)   # 0.3 short each end
            # Lying along x on a flat: the flat is FLAT_MM off one side.
            lines += [f"pin = cq.Workplane('YZ').circle({r}).extrude({length})",
                      f"pin = pin.cut(cq.Workplane('XY').box({length + 2}, {2 * r + 2}, {r}, "
                      f"centered=(False, True, False)).translate((-1, 0, {-2 * r + FLAT_MM})))",
                      f"pin = pin.translate((0, {round(y, 3)}, {r - FLAT_MM}))",
                      "pins = pin if pins is None else pins.union(pin)"]
            y += pin.diameter + 4
        lines.append("cq.exporters.export(pins, 'pieces/pins.stl', tolerance=0.02, angularTolerance=0.1)")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ the split
def settings(cfg) -> tuple[list[float], float, float]:
    """The printer's volume, its least wall and the pins' clearance."""
    return ([float(v) for v in cfg.get("hardware.build_volume_mm", [250, 250, 260])],
            float(cfg.get("hardware.min_wall_mm", 1.2)),
            float(cfg.get("joints.clearance_mm", CLEARANCE_MM)))


def plan_concept(cfg, doc: dict) -> Plan | None:
    """A concept's joints, planned from its shapes before it is built, so its
    blueprint can show the pieces and pins (owner, 2026-11-04: "have concept
    show this with joints parts"). None if it prints whole; SplitError if it
    cannot be split. The build then uses this very plan (split(plan=...)), so
    the pins drawn are the pins made."""
    from .blockout import shape_meshes
    volume, min_wall, clearance = settings(cfg)
    adds, cuts = shape_meshes(doc)
    body = Body(adds, cuts)
    size = [float(h - l) for l, h in zip(*body.bounds)]
    if all(size[i] <= volume[i] for i in range(3)):
        return None
    return plan(body, volume, min_wall, clearance)


def plan_from_json(text: str) -> Plan:
    d = json.loads(text)
    cuts = [Cut(c["axis"], c["at"], [Pin(**q) for q in c["pins"]], c.get("moved", 0.0))
            for c in d["cuts"]]
    return Plan(d["lo"], d["hi"], cuts, d["clearance"], d["depth"], d.get("notes", []),
                d.get("apart", []), d.get("empty", []))


def split(cfg, name: str, timeout: int = 1800, given: Plan | None = None) -> tuple[Path, list, Plan | None]:
    """Split a built model that is too big for the printer. Returns its
    folder, the checks (one per piece, and the plan), and the plan. `given`:
    a plan made earlier (a concept's, shown on its blueprint), used as it is."""
    import trimesh
    from . import modelkit
    from .checks import FAIL, PASS, SKIP, Result
    from .checks.runners import _run, solid, thickness
    out = modelkit.folder(cfg, name)
    stl = out / "model.stl"
    if not stl.is_file():
        raise SplitError(f"no model called {name!r} has been built (nemo model list)")
    spec = modelkit.validate(json.loads((out / "spec.json").read_text(encoding="utf-8")))
    volume, min_wall, clearance = settings(cfg)
    began = time.time()
    p = given or plan(trimesh.load_mesh(str(stl)), volume, min_wall, clearance)
    clearance = p.clearance
    pieces = out / "pieces"
    pieces.mkdir(exist_ok=True)
    for old in pieces.glob("*.stl"):
        old.unlink()                                  # an old piece proves nothing
    (out / "joints.json").write_text(json.dumps(asdict(p), indent=1), encoding="utf-8")
    (out / "joints.py").write_text(script(modelkit.script(spec), p), encoding="utf-8")
    rc, so, se = _run([sys.executable, "joints.py"], cwd=out, timeout=timeout)
    made = sorted(pieces.glob("piece-*.stl"), key=lambda f: int(f.stem.split("-")[1]))
    for f in made + [pieces / "pins.stl"]:
        if f.is_file():
            modelkit.tidy_stl(f)                       # D224: a sphere's poles
    if rc != 0 or len(made) != p.pieces:
        tail = ((se or "") + (so or "")).strip().splitlines()[-6:]
        return out, [Result("pieces_made", FAIL, f"the script failed (code {rc})" if rc
                            else f"{len(made)} of {p.pieces} pieces written", tail)], p
    pins = sum(len(c.pins) for c in p.cuts)
    sizes = ", ".join(sorted({f"{q.diameter:g}" for c in p.cuts for q in c.pins}))
    joined = (f"{pins} pin(s) of {sizes} mm, holes {clearance:g} mm wider all round" if pins
              else "no room for pins: the joints are glued")
    along = " and ".join("xyz"[a] for a in p.axes)
    results = [Result("pieces_made", PASS, f"{p.pieces} pieces, cut along {along}, {joined}",
                      p.notes)]
    from .render import read_stl
    for f in made + ([pieces / "pins.stl"] if pins else []):
        s = solid(f)
        t = thickness(f, min_wall)
        tris = read_stl(f).reshape(-1, 3)
        size = [round(float(v), 1) for v in tris.max(0) - tris.min(0)]
        over = [i for i in range(3) if size[i] > volume[i]]
        status = FAIL if FAIL in (s.status, t.status) or over else \
            SKIP if SKIP in (s.status, t.status) else PASS
        results.append(Result(f.stem, status, f"{size[0]:g} x {size[1]:g} x {size[2]:g} mm; "
                              f"{s.detail}; {t.detail}" + ("; too big for the printer" if over else "")))
    (out / "split-checks.json").write_text(json.dumps(
        [{"name": r.name, "status": r.status, "detail": r.detail, "items": list(r.items)}
         for r in results], indent=1), encoding="utf-8")
    (pieces / "ASSEMBLY.txt").write_text(assembly(name, p), encoding="utf-8")
    from . import timekeeper
    timekeeper.record("art_studio", "model split", time.time() - began,
                      all(r.status != FAIL for r in results))
    return out, results, p


def joint_pins(p: Plan) -> dict[tuple[int, int], list[Pin]]:
    """Every pair of pieces that meet, and the pins between them. A pair
    that meets where the model is thin may have none."""
    out: dict[tuple[int, int], list[Pin]] = {}
    for c in p.cuts:
        u, v = _others(c.axis)
        for su in p.ranges(u):
            for sv in p.ranges(v):
                if [c.axis, c.at, su[0], su[1], sv[0], sv[1]] in p.apart:
                    continue
                mid = [0.0, 0.0, 0.0]
                mid[u], mid[v] = (su[0] + su[1]) / 2, (sv[0] + sv[1]) / 2
                below, above = list(mid), list(mid)
                below[c.axis], above[c.axis] = c.at - 0.5, c.at + 0.5
                pair = (p.piece_at(below), p.piece_at(above))
                if 0 in pair:
                    continue                           # one side is no piece
                here = [q for q in c.pins if su[0] <= q.u <= su[1] and sv[0] <= q.v <= sv[1]]
                out.setdefault(pair, []).extend(here)
    return dict(sorted(out.items()))


def assembly(name: str, p: Plan) -> str:
    """The Writer's note on putting it together."""
    pins = [q for c in p.cuts for q in c.pins]
    along = " and ".join("xyz"[a] for a in p.axes)
    lines = [f"{name}: {p.pieces} pieces, cut along {along}", "",
             f"Print piece-1.stl to piece-{p.pieces}.stl as they lie. Piece 1 is at the low "
             "x, y and z corner; the numbers count along x first, then y, then z."]
    if pins:
        lines += [f"Print pins.stl: {len(pins)} pin(s), lying on their flat side, so the "
                  "layers run along the pin (printed upright it would shear at the joint).",
                  f"Each hole is {p.clearance:g} mm wider than its pin all round. That is a "
                  "rule of thumb, not measured on your printer: try one pin in one hole first. "
                  "Too tight: sand the pin, or raise joints.clearance_mm. Too loose: glue it."]
    for (a, b), got in joint_pins(p).items():
        what = (f"{len(got)} pin(s), {got[0].diameter:g} mm" if got
                else "no pins (no room): glue the faces")
        lines.append(f"piece-{a} to piece-{b}: {what}.")
    lines += ["", "Push the pins half way into one piece, then press the next onto them. "
              "Glue (PLA: cyanoacrylate or epoxy) makes it permanent."]
    return "\n".join(lines) + "\n"
