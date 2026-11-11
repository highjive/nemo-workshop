"""A shaped object's concept as shapes: the geometry, checks and drawings
(owner, 2026-10-28: concepts the Art Studio's Designer can build).

A concept is a modelkit spec (nemo/modelkit.py: boxes, rounded boxes,
plates, cylinders, cones, spheres, prisms), each shape with its size in
millimetres and where it sits. Since 2026-11-04 (owner: "remove blockout")
the shapes are built by code from the object's anatomy (nemo/anatomy.py);
the language model is no longer asked to place them, which it could not do
recognisably. This module still holds what works on the shapes:

  - their extents, bounds, uniform scaling (fit),
  - checks that every added shape touches the rest and none is buried,
  - the blueprint (and the older marker sketch) drawn from the same numbers
    the Designer builds from, so what is chosen is what is made,
  - their triangles and meshes, for the drawings and the joints.

The module keeps its name: saved projects call the kind "blockout".
"""
from __future__ import annotations

from pathlib import Path

from .modelkit import ModelError, validate

TOUCH_MM = 0.5                 # shapes this close count as joined


def extent(s: dict) -> tuple[list[float], list[float]]:
    """A shape's box, low and high corners, as modelkit places it."""
    rot = list(s.get("rotate") or [0, 0, 0])
    if s["shape"] == "prism" or (rot not in ([0, 0, 0], [0, 90, 0]) and s["shape"] != "sphere"):
        # Turned some other way (a butt that drops, a trigger guard across the
        # gun, 2026-11-04): its box from its own triangles, as it is placed.
        t = _placed_tris(s).reshape(-1, 3)
        return [float(v) for v in t.min(axis=0)], [float(v) for v in t.max(axis=0)]
    x, y, z = s["at"]
    k = s["shape"]
    if k == "sphere":
        r = s["radius"]
        return [x - r, y - r, z - r], [x + r, y + r, z + r]
    if k in ("cylinder", "cone"):
        r = max(s["radius"], s.get("top_radius", 0))
        if s.get("rotate") == [0, 90, 0]:
            return [x, y - r, z - r], [x + s["height"], y + r, z + r]
        return [x - r, y - r, z], [x + r, y + r, z + s["height"]]
    if k == "plate":
        (a, b), c = s["size"], s["thickness"]
    else:
        a, b, c = s["size"]
    return [x - a / 2, y - b / 2, z], [x + a / 2, y + b / 2, z + c]


def bounds(doc: dict) -> tuple[list[float], list[float]]:
    ext = [extent(s) for s in doc["shapes"] if s["op"] == "add"]
    return ([min(e[0][i] for e in ext) for i in range(3)],
            [max(e[1][i] for e in ext) for i in range(3)])


def fit(doc: dict, size_mm: list[float] | None, shrink_only: bool = False) -> float:
    """Scale the whole uniformly into `size_mm` (in place; only made smaller
    when shrink_only), set it on the floor and centre it; returns the scale.
    A size of 0 on an axis is not given: the others set the scale (a real
    object's length alone, 2026-11-04). No size at all keeps the size the
    shapes were given: a model too big for the printer is split to print
    (nemo/joints.py), not shrunk (owner, 2026-11-04)."""
    lo, hi = bounds(doc)
    span = [max(h - l, 0.01) for l, h in zip(lo, hi)]
    given = [i for i in range(3) if size_mm and len(size_mm) > i and size_mm[i] > 0]
    k = min(size_mm[i] / span[i] for i in given) if given else 1.0
    if shrink_only:
        k = min(k, 1.0)
    mid = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]]
    for s in doc["shapes"]:
        s["at"] = [round((s["at"][i] - mid[i]) * k, 2) for i in range(3)]
        for key in ("radius", "top_radius", "height", "thickness", "width"):
            if key in s and isinstance(s[key], (int, float)):
                s[key] = round(s[key] * k, 2)
        if "points" in s:
            s["points"] = [[round(v * k, 2) for v in p] for p in s["points"]]
        if "size" in s:
            s["size"] = [round(v * k, 2) for v in s["size"]]
    return k


def _loose(doc: dict) -> list[int]:
    """Indices (among the added shapes) of those not joined to the first."""
    adds = [s for s in doc["shapes"] if s["op"] == "add"]
    ext = [extent(s) for s in adds]

    def touch(a, b) -> bool:
        return all(a[0][i] <= b[1][i] + TOUCH_MM and b[0][i] <= a[1][i] + TOUCH_MM for i in range(3))
    joined, todo = {0}, [0]
    while todo:
        i = todo.pop()
        for j in range(len(adds)):
            if j not in joined and touch(ext[i], ext[j]):
                joined.add(j); todo.append(j)
    return [j for j in range(len(adds)) if j not in joined]


def floating(doc: dict) -> list[str]:
    """Added shapes not joined to the first one, through the others."""
    adds = [s for s in doc["shapes"] if s["op"] == "add"]
    return [adds[j].get("label") or adds[j]["shape"] for j in _loose(doc)]


# Solids whose outline box IS the solid: a shape inside one is inside the
# solid. (Inside a cylinder's or a sphere's box it may stick out at a corner,
# so it is never called hidden there.)
SOLID_BOXES = ("box", "rounded_box", "plate")


def hidden(doc: dict, tol: float = TOUCH_MM) -> list[str]:
    """Added shapes wholly inside another, so they add nothing that shows:
    10 of a 12-shape answer sat inside its stock box, and the sketch showed
    two (qwen3-8b's blunderbuss, 2026-11-04)."""
    return [s.get("label") or s["shape"] for s in hidden_shapes(doc, tol)]


def hidden_shapes(doc: dict, tol: float = TOUCH_MM) -> list[dict]:
    """The shapes themselves (hidden() gives their names, which an
    unlabelled answer shares: a blueprint dashed every box by name)."""
    adds = [s for s in doc["shapes"] if s["op"] == "add"]
    out = []
    for i, s in enumerate(adds):
        lo, hi = extent(s)
        for j, t in enumerate(adds):
            if i == j or t["shape"] not in SOLID_BOXES:
                continue
            if list(t.get("rotate") or [0, 0, 0]) != [0, 0, 0]:
                continue                  # a turned box's outline box is more than the box
            tl, th = extent(t)
            if all(tl[k] - tol <= lo[k] and hi[k] <= th[k] + tol for k in range(3)):
                # Two the same (B's Stock and Base, 2026-11-04): each is inside
                # the other, and the first one shows.
                mutual = s["shape"] in SOLID_BOXES and \
                    all(lo[k] - tol <= tl[k] and th[k] <= hi[k] + tol for k in range(3))
                if mutual and j > i:
                    continue
                out.append(s)
                break
    return out


def check(doc: dict) -> dict:
    """The blockout as modelkit will build it, or ModelError saying why not."""
    labels = [s.pop("label", "") for s in doc["shapes"]]
    try:
        spec = validate(doc)
    finally:
        for s, lab in zip(doc["shapes"], labels):
            s["label"] = lab
    loose = floating(doc)
    if loose:
        raise ModelError("not joined to the rest: " + ", ".join(loose))
    return {"name": spec.name, "shapes": doc["shapes"]}


def buildable(doc: dict) -> dict:
    """The spec modelkit takes: the labels kept apart, in `parts`."""
    return {"name": doc["name"], "shapes": [{k: v for k, v in s.items() if k != "label"}
                                            for s in doc["shapes"]],
            "parts": [s.get("label", "") for s in doc["shapes"]]}


# ---------------------------------------------------------------- the views
def views_png(doc: dict, path: Path, title: str, px: int = 210) -> Path:
    """Front, side and top views with the overall measurements, drawn from
    the same numbers the Designer builds from."""
    from PIL import Image, ImageDraw
    lo, hi = bounds(doc)
    span = [h - l for l, h in zip(lo, hi)]
    big = max(span) or 1
    k = (px - 60) / big
    W, H = px * 3 + 40, px + 90
    img = Image.new("RGB", (W, H), (246, 241, 230))
    d = ImageDraw.Draw(img)
    d.text((14, 10), title, fill=(40, 30, 20))
    d.text((14, 26), f"{span[0]:.0f} x {span[1]:.0f} x {span[2]:.0f} mm  (length x width x height)",
           fill=(90, 70, 50))
    views = (("Front", 0, 2), ("Side", 1, 2), ("Top", 0, 1))
    for n, (label, a, b) in enumerate(views):
        ox, oy = 20 + n * (px + 10), 60
        d.rectangle([ox, oy, ox + px - 10, oy + px - 10], outline=(200, 190, 170))
        d.text((ox + 6, oy + 4), label, fill=(90, 70, 50))
        cx = ox + (px - 10) / 2 - (lo[a] + hi[a]) / 2 * k
        base = oy + px - 40

        def P(u, v):
            # v is up for front/side (z), and "down the page" for the top view (y)
            return (cx + u * k, base - (v - lo[b]) * k) if b == 2 else \
                   (cx + u * k, oy + (px - 10) / 2 + (v - (lo[1] + hi[1]) / 2) * k)
        for s in doc["shapes"]:
            outline, kind = (70, 50, 30), _seen_as(s, label)
            fill = (214, 186, 140) if s["op"] == "add" else None
            e0, e1 = extent(s)
            if kind == "trapezoid":
                x, y, z = s["at"]
                r0, r1, h = s["radius"], s.get("top_radius", 0), s["height"]
                if s.get("rotate") == [0, 90, 0]:
                    c = y if label == "Top" else z
                    pts = [P(x, c - r0), P(x + h, c - r1), P(x + h, c + r1), P(x, c + r0)]
                else:
                    c = x if a == 0 else y
                    pts = [P(c - r0, z), P(c + r0, z), P(c + r1, z + h), P(c - r1, z + h)]
                d.polygon(pts, fill=fill, outline=outline)
                continue
            x0, y0 = P(e0[a], e0[b]); x1, y1 = P(e1[a], e1[b])
            box = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
            if kind == "circle":
                d.ellipse(box, fill=fill, outline=outline, width=2)
            else:
                d.rectangle(box, fill=fill, outline=outline, width=2)
        d.text((ox + 6, oy + px - 28), f"{span[a]:.0f} mm wide, {span[b]:.0f} mm "
               + ("high" if b == 2 else "deep"), fill=(90, 70, 50))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


# ------------------------------------------------------------ the blueprint
# Owner, 2026-11-04: "change from blockout to blueprint in concept". The
# concept is drawn as a blueprint: white lines on blueprint blue, the front,
# top and side views in third-angle projection at one scale (top above the
# front, side to its right), so they line up and measure true; the overall
# length, width and height dimensioned; an isometric view traced from the
# same geometry; a title block. A shape wholly inside another is drawn dashed,
# as hidden detail is in drafting, instead of vanishing.
BP_BLUE = (28, 78, 138)
BP_GRID = (44, 96, 160)
BP_INK = (236, 244, 255)
BP_FAINT = (150, 186, 230)


def _dashed(d, a, b, fill, width=1, dash=6):
    import math
    (x0, y0), (x1, y1) = a, b
    n = max(1, int(math.hypot(x1 - x0, y1 - y0) // dash))
    for i in range(0, n, 2):
        t0, t1 = i / n, min(1.0, (i + 1) / n)
        d.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)], fill=fill, width=width)


def _outline(d, kind, pts_or_box, dashed, width=2):
    if kind == "circle":
        if dashed:
            import math
            x0, y0, x1, y1 = pts_or_box
            cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
            for i in range(0, 48, 2):
                a0, a1 = i / 48 * 2 * math.pi, (i + 1) / 48 * 2 * math.pi
                d.line([(cx + rx * math.cos(a0), cy + ry * math.sin(a0)),
                        (cx + rx * math.cos(a1), cy + ry * math.sin(a1))], fill=BP_FAINT, width=1)
        else:
            d.ellipse(pts_or_box, outline=BP_INK, width=width)
        return
    if kind == "rectangle":
        x0, y0, x1, y1 = pts_or_box
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    else:
        pts = pts_or_box
    for a, b in zip(pts, pts[1:] + pts[:1]):
        if dashed:
            _dashed(d, a, b, BP_FAINT)
        else:
            d.line([a, b], fill=BP_INK, width=width)


def _arrow_dim(d, a, b, text, font, horizontal=True):
    """A dimension line with arrowheads at both ends and its figure."""
    (x0, y0), (x1, y1) = a, b
    d.line([a, b], fill=BP_INK, width=1)
    for (px, py), sgn in (((x0, y0), 1), ((x1, y1), -1)):
        if horizontal:
            d.polygon([(px, py), (px + 7 * sgn, py - 3), (px + 7 * sgn, py + 3)], fill=BP_INK)
        else:
            d.polygon([(px, py), (px - 3, py + 7 * sgn), (px + 3, py + 7 * sgn)], fill=BP_INK)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    tw = d.textlength(text, font=font)
    if horizontal:
        d.rectangle([mx - tw / 2 - 3, my - 8, mx + tw / 2 + 3, my + 8], fill=BP_BLUE)
        d.text((mx - tw / 2, my - 7), text, fill=BP_INK, font=font)
    else:
        d.rectangle([mx - tw / 2 - 3, my - 8, mx + tw / 2 + 3, my + 8], fill=BP_BLUE)
        d.text((mx - tw / 2, my - 7), text, fill=BP_INK, font=font)


def _font(size: int):
    from PIL import ImageFont
    for name in ("consola.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def view_scale(span, W: int = 960, H: int = 640) -> float:
    """Pixels a millimetre for the blueprint's three views. Front and side sit
    side by side, (length + width) x k plus the room between them; top and
    front are stacked, (width + height) x k. Until 2026-11-04 the first term
    took the width in mm from a width in px: a full-size, 823 mm concept came
    out at the 0.2 floor, a third of the room."""
    area_w, area_h = W * 0.56, H - 150
    k = min((area_w - 70) / max(span[0] + span[1], 1),
            (area_h - 80) / max(span[1] + span[2], 1))
    return max(k, 0.2)


def _hull(points):
    """The convex hull of 2-D points, anticlockwise (Andrew's monotone chain)."""
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _draw_view(d, doc, P, a, b, view, buried, width=2):
    """Every added shape's outline in one orthographic view."""
    for s in doc["shapes"]:
        if s["op"] != "add":
            continue
        dashed = id(s) in buried
        if s["shape"] == "prism" or list(s.get("rotate") or [0, 0, 0]) not in ([0, 0, 0], [0, 90, 0]):
            # Turned some other way: its true outline in this view, the hull of
            # its corners as placed (every kit shape is convex).
            t = _placed_tris(s).reshape(-1, 3)
            hull = _hull([(float(p[a]), float(p[b])) for p in t])
            _outline(d, "poly", [P(u, v) for u, v in hull], dashed, width)
            continue
        kind = _seen_as(s, view)
        if kind == "trapezoid":
            x, y, z = s["at"]
            r0, r1, h = s["radius"], s.get("top_radius", 0), s["height"]
            if s.get("rotate") == [0, 90, 0]:
                pts = [P(x, (y if view == "Top" else z) + o) for o in (-r0, r0)] + \
                      [P(x + h, (y if view == "Top" else z) + o) for o in (r1, -r1)]
            else:
                c = x if a == 0 else y
                pts = [P(c - r0, z), P(c + r0, z), P(c + r1, z + h), P(c - r1, z + h)]
            _outline(d, "poly", pts, dashed, width)
            continue
        e0, e1 = extent(s)
        (x0, y0), (x1, y1) = P(e0[a], e0[b]), P(e1[a], e1[b])
        _outline(d, kind, [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], dashed, width)


BP_JOINT = (255, 204, 92)          # joints and pins: amber, as a checker marks a drawing


def _draw_joints(d, plan, P, a, b, k, font):
    """The joints on one view: each cut as an amber chain line, each pin as a
    dashed dowel through it (or a circle where the view looks along it), and
    the pieces numbered."""
    from .joints import _others
    lo, hi = plan.lo, plan.hi
    for c in plan.cuts:
        if c.axis == a:
            _chain(d, P(c.at, lo[b]), P(c.at, hi[b]))
        elif c.axis == b:
            _chain(d, P(lo[a], c.at), P(hi[a], c.at))
        u, v = _others(c.axis)
        for q in c.pins:
            r = q.diameter / 2
            if c.axis in (a, b):
                other = b if c.axis == a else a
                across = q.u if other == u else q.v
                if c.axis == a:
                    (x0, y0), (x1, y1) = P(c.at - plan.depth, across - r), P(c.at + plan.depth, across + r)
                else:
                    (x0, y0), (x1, y1) = P(across - r, c.at - plan.depth), P(across + r, c.at + plan.depth)
                x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
                for e0, e1 in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                               ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
                    _dashed(d, e0, e1, BP_JOINT, width=1, dash=3)
            else:
                ca, cb = (q.u, q.v) if (u, v) == (a, b) else (q.v, q.u)
                cx, cy = P(ca, cb)
                rr = max(2.0, r * k)
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=BP_JOINT, width=1)
    # Each piece's number, in the views that show it apart from the others.
    third = 3 - a - b
    for n, spans in plan.cells():
        if spans[third][0] != lo[third]:
            continue                                   # behind another piece in this view
        cx, cy = P((spans[a][0] + spans[a][1]) / 2, (spans[b][0] + spans[b][1]) / 2)
        t = str(n)
        tw = d.textlength(t, font=font)
        d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=BP_BLUE, outline=BP_JOINT, width=1)
        d.text((cx - tw / 2, cy - 7), t, fill=BP_JOINT, font=font)


def _chain(d, a, b, width=2):
    """A chain line (long dash, short dash), as a joint is drawn."""
    import math
    (x0, y0), (x1, y1) = a, b
    length = math.hypot(x1 - x0, y1 - y0)
    if length == 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    t, long_dash = 0.0, True
    while t < length:
        e = min(t + (14 if long_dash else 3), length)
        d.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * e, y0 + uy * e)], fill=BP_JOINT, width=width)
        t, long_dash = e + 4, not long_dash


def _exploded(img, doc, plan, buried, box, font):
    """The pieces pulled apart, in one orthographic view (top, or front where
    there is a cut across the height), the pins drawn across the gaps they
    bridge, each piece numbered. The view is drawn once and cut up along the
    joints, so each piece is exactly its part of the drawing."""
    from PIL import Image, ImageDraw
    a, b, view = (0, 1, "Top") if 2 not in plan.axes else (0, 2, "Front")
    lo, hi = plan.lo, plan.hi
    ra, rb = plan.ranges(a), plan.ranges(b)
    gap = 22
    bw, bh = box[2] - box[0], box[3] - box[1]
    k = min((bw - gap * (len(ra) - 1) - 24) / max(hi[a] - lo[a], 1),
            (bh - gap * (len(rb) - 1) - 24) / max(hi[b] - lo[b], 1))
    flip = b == 2                                      # z up the page; y down it

    def P0(u, v):
        return 12 + (u - lo[a]) * k, 12 + ((hi[b] - v) if flip else (v - lo[b])) * k

    def shift(u, v):
        ia = sum(1 for c in plan.at(a) if u > c)
        ib = sum(1 for c in plan.at(b) if v > c)
        row = (len(rb) - 1 - ib) if flip else ib
        return ia * gap, row * gap

    def Q(u, v, side_u=0.0, side_v=0.0):
        x, y = P0(u, v)
        sx, sy = shift(u + side_u, v + side_v)
        return box[0] + x + sx, box[1] + y + sy

    layer = Image.new("RGBA", (int((hi[a] - lo[a]) * k) + 26, int((hi[b] - lo[b]) * k) + 26), (0, 0, 0, 0))
    _draw_view(ImageDraw.Draw(layer), doc, P0, a, b, view, buried)
    third = 3 - a - b
    d = ImageDraw.Draw(img)
    for n, spans in plan.cells():
        if spans[third][0] != lo[third]:
            continue
        (x0, y0), (x1, y1) = P0(spans[a][0], spans[b][0]), P0(spans[a][1], spans[b][1])
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
        x0, y0 = (x0 - 3 if spans[a][0] == lo[a] else x0), (y0 - 3 if y0 <= 12.5 else y0)
        x1 = x1 + 3 if spans[a][1] == hi[a] else x1
        y1 = y1 + 3 if y1 >= layer.height - 14.5 else y1
        piece = layer.crop((int(x0), int(y0), int(x1) + 1, int(y1) + 1))
        mu, mv = (spans[a][0] + spans[a][1]) / 2, (spans[b][0] + spans[b][1]) / 2
        sx, sy = shift(mu, mv)
        img.paste(piece, (int(box[0] + x0 + sx), int(box[1] + y0 + sy)), piece)
        cx, cy = Q(mu, mv)
        t = str(n)
        tw = d.textlength(t, font=font)
        d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=BP_BLUE, outline=BP_JOINT, width=1)
        d.text((cx - tw / 2, cy - 7), t, fill=BP_JOINT, font=font)
    from .joints import _others
    for c in plan.cuts:
        if c.axis not in (a, b):
            continue
        u, v = _others(c.axis)
        other = b if c.axis == a else a
        half = max(2.0, plan.depth * k)                # how far a pin goes into each piece
        for q in c.pins:
            r = max(1.5, q.diameter / 2 * k)
            across = q.u if other == u else q.v
            # Where the joint's two faces are drawn, either side of the gap.
            if c.axis == a:
                lo_face, hi_face = Q(c.at, across, side_u=-0.01), Q(c.at, across, side_u=0.01)
                rect = [lo_face[0] - half, lo_face[1] - r, hi_face[0] + half, lo_face[1] + r]
            else:
                lo_face, hi_face = Q(across, c.at, side_v=-0.01), Q(across, c.at, side_v=0.01)
                y0, y1 = sorted((lo_face[1], hi_face[1]))
                rect = [lo_face[0] - r, y0 - half, lo_face[0] + r, y1 + half]
            d.rectangle(rect, outline=BP_JOINT, width=1)
        _cut_faces(d, doc, plan, c, a, b, third, other, k, Q)
    d.text((box[0], box[1] - 22), f"PIECES, PULLED APART ({view.upper()})", fill=BP_INK, font=font)


def _cut_faces(d, doc, plan, c, a, b, third, other, k, Q):
    """The edge of each piece's cut face, on both sides of the gap: where the
    model's section reaches along the view, seen through the third axis."""
    import numpy as np
    from .joints import Body
    adds, cuts = shape_meshes(doc)
    body = Body(adds, cuts)
    step = max(0.5, 1.0 / k)                          # a pixel or so
    along = np.arange(plan.lo[other] + step / 2, plan.hi[other], step)
    deep = np.linspace(plan.lo[third], plan.hi[third], 24)[1:-1]
    from .joints import _others
    u, v = _others(c.axis)
    pts = np.array([(s, t) if (other, third) == (u, v) else (t, s) for s in along for t in deep])
    solid = body.solid(c.axis, c.at, pts, walls=False)[0].reshape(len(along), len(deep)).any(axis=1)
    runs, start = [], None
    for i, on in enumerate(list(solid) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((along[start] - step / 2, along[i - 1] + step / 2)); start = None
    for s0, s1 in runs:
        for side in (-0.01, 0.01):
            if c.axis == a:
                p0, p1 = Q(c.at, s0, side_u=side), Q(c.at, s1 - 1e-6, side_u=side)
            else:
                p0, p1 = Q(s0, c.at, side_v=side), Q(s1 - 1e-6, c.at, side_v=side)
            d.line([p0, p1], fill=BP_JOINT, width=2)


def blueprint_png(doc: dict, path: Path, title: str, W: int = 960, H: int = 640,
                  plan=None, split_note: str = "") -> Path:
    """The concept as a blueprint (see above). Drawn from the same numbers the
    Designer builds from. With `plan` (nemo/joints.py: the concept is bigger
    than the printer), the joints are drawn on the views, the pieces numbered,
    and an exploded view of the pieces takes the isometric's place; a split
    that could not be planned is said in `split_note`."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    lo, hi = bounds(doc)
    span = [h - l for l, h in zip(lo, hi)]
    buried = set(id(s) for s in hidden_shapes(doc))
    img = Image.new("RGB", (W, H), BP_BLUE)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 20):
        d.line([(x, 0), (x, H)], fill=BP_GRID, width=1)
    for y in range(0, H, 20):
        d.line([(0, y), (W, y)], fill=BP_GRID, width=1)
    d.rectangle([10, 10, W - 11, H - 11], outline=BP_INK, width=3)
    d.rectangle([16, 16, W - 17, H - 17], outline=BP_INK, width=1)
    f, fs, fb = _font(14), _font(12), _font(18)

    # One scale for the three views: the front (length x height) and the top
    # (length x width) stacked on the left half, the side (width x height) right of the front.
    k = view_scale(span, W, H)
    left = 70
    top_y = 60                                   # the top view's upper edge
    front_y = top_y + span[1] * k + 50           # the front view's upper edge
    side_x = left + span[0] * k + 50

    def front(u, v):     # x along, z up
        return left + (u - lo[0]) * k, front_y + (hi[2] - v) * k

    def topv(u, v):      # x along, y down the page
        return left + (u - lo[0]) * k, top_y + (v - lo[1]) * k

    def side(u, v):      # y along, z up
        return side_x + (u - lo[1]) * k, front_y + (hi[2] - v) * k

    for label, P, a, b in (("FRONT", front, 0, 2), ("TOP", topv, 0, 1), ("SIDE", side, 1, 2)):
        view = {"FRONT": "Front", "TOP": "Top", "SIDE": "Side"}[label]
        _draw_view(d, doc, P, a, b, view, buried)
        if plan is not None:
            _draw_joints(d, plan, P, a, b, k, fs)
        ox, oy = P(lo[a], hi[b] if b == 2 else lo[b])
        d.text((ox, oy - 22), label, fill=BP_INK, font=fs)

    # Overall dimensions: length under the front, height left of it, width right of the side.
    fl, fr = front(lo[0], lo[2]), front(hi[0], lo[2])
    _arrow_dim(d, (fl[0], fl[1] + 24), (fr[0], fr[1] + 24), f"{span[0]:.0f}", f)
    ft, fbm = front(lo[0], hi[2]), front(lo[0], lo[2])
    _arrow_dim(d, (ft[0] - 26, ft[1]), (fbm[0] - 26, fbm[1]), f"{span[2]:.0f}", f, horizontal=False)
    sl, sr = side(lo[1], lo[2]), side(hi[1], lo[2])
    _arrow_dim(d, (sl[0], sl[1] + 24), (sr[0], sr[1] + 24), f"{span[1]:.0f}", f)

    # The isometric view, traced from the same geometry's render; for a concept
    # built in pieces, the pieces pulled apart instead.
    iso_box = (int(W * 0.60), 40, W - 40, int(H * 0.62))
    # The pieces pulled apart go under the views where there is room (the
    # isometric of the whole stays), else in the isometric's place.
    views_bottom = front(lo[0], lo[2])[1] + 44
    below = (40, int(views_bottom) + 30, int(W * 0.58), H - 30)
    roomy = below[3] - below[1] >= 150
    if plan is not None:
        _exploded(img, doc, plan, buried, below if roomy else iso_box, fs)
    if plan is None or roomy:
        try:
            from .render import render_view
            n = min(iso_box[2] - iso_box[0], iso_box[3] - iso_box[1])
            arr = render_view(triangles(doc), "iso", n)
            grey = ImageOps.grayscale(Image.fromarray(arr))
            edges = grey.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 18 else 0)
            edges.paste(0, (0, 0, n, 4)); edges.paste(0, (0, n - 4, n, n))   # the
            edges.paste(0, (0, 0, 4, n)); edges.paste(0, (n - 4, 0, n, n))   # render's own edge
            mask = edges.filter(ImageFilter.MaxFilter(3))
            img.paste(Image.new("RGB", mask.size, BP_INK), (iso_box[0], iso_box[1]), mask)
        except ImportError:
            d.text((iso_box[0] + 10, iso_box[1] + 10), "(isometric view needs numpy)",
                   fill=BP_FAINT, font=fs)
        d.text((iso_box[0], iso_box[1] - 22), "ISOMETRIC", fill=BP_INK, font=fs)

    # The title block.
    tb = (int(W * 0.60), H - 150, W - 26, H - 26)
    d.rectangle(tb, outline=BP_INK, width=2)
    d.line([(tb[0], tb[1] + 34), (tb[2], tb[1] + 34)], fill=BP_INK, width=1)
    d.line([(tb[0], tb[1] + 68), (tb[2], tb[1] + 68)], fill=BP_INK, width=1)
    d.text((tb[0] + 10, tb[1] + 7), "NEMO  ·  CONCEPT BLUEPRINT", fill=BP_INK, font=fb)
    d.text((tb[0] + 10, tb[1] + 42), title[:52], fill=BP_INK, font=f)
    note = f"{span[0]:.0f} x {span[1]:.0f} x {span[2]:.0f} mm   SCALE {k:.2f} px/mm   THIRD ANGLE"
    d.text((tb[0] + 10, tb[1] + 76), note, fill=BP_INK, font=fs)
    if buried:
        d.text((tb[0] + 10, tb[1] + 89), f"dashed: {len(buried)} shape(s) hidden inside others",
               fill=BP_FAINT, font=fs)
    if plan is not None:
        from .joints import joint_pins
        pins = [q for c in plan.cuts for q in c.pins]
        sizes = "/".join(sorted({f"{q.diameter:g}" for q in pins}))
        text = (f"PRINTED IN {plan.pieces} PIECES, {len(joint_pins(plan))} JOINTS, "
                f"{len(pins)} PINS" + (f" {sizes} mm" if pins else "") + "  (AMBER)")
        d.text((tb[0] + 10, tb[1] + 105), text, fill=BP_JOINT, font=fs)
    elif split_note:
        d.text((tb[0] + 10, tb[1] + 105), split_note[:60], fill=BP_JOINT, font=fs)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def _seen_as(s: dict, view: str) -> str:
    """How a shape looks from a view: circle, trapezoid or rectangle."""
    k = s["shape"]
    if k == "sphere":
        return "circle"
    if k not in ("cylinder", "cone"):
        return "rectangle"
    lying = s.get("rotate") == [0, 90, 0]
    if (view == "Top" and not lying) or (view == "Side" and lying):
        return "circle"                                       # looking along its axis
    return "trapezoid" if k == "cone" else "rectangle"


# ---------------------------------------------------------------- the sketch
# A designer's marker render (owner, 2026-10-28: the flat views were "not
# right", then pencil was changed for marker): the shapes are made into
# triangles here, from the same numbers modelkit builds from, rendered by
# nemo/render.py, and drawn over in ink and grey markers on white. numpy
# only; no CadQuery needed to see a concept.
SEGMENTS = 96          # fine enough that a curve shows no facet lines


def _ring(r: float, z: float, n: int = SEGMENTS):
    import numpy as np
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([r * np.cos(a), r * np.sin(a), np.full(n, z)], 1)


def _solid_tris(s: dict):
    """The shape's triangles, its foot centred on the origin, as modelkit makes it."""
    import numpy as np
    k = s["shape"]
    if k == "prism":
        # A convex outline in x, z, given its width across y: two caps (fans)
        # and a side for each edge.
        pts = [tuple(p) for p in s["points"]]
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
        if area < 0:
            pts = pts[::-1]                      # anticlockwise seen from -y
        w = s["width"] / 2
        near = [(x, -w, z) for x, z in pts]
        far = [(x, w, z) for x, z in pts]
        tris = []
        for j in range(1, len(pts) - 1):
            tris += [(near[0], near[j], near[j + 1]), (far[0], far[j + 1], far[j])]
        for j in range(len(pts)):
            k2 = (j + 1) % len(pts)
            tris += [(near[j], far[j], far[k2]), (near[j], far[k2], near[k2])]
        return np.array(tris, float)
    if k in ("box", "rounded_box", "plate"):
        if k == "plate":
            (a, b), c = s["size"], s["thickness"]
        else:
            a, b, c = s["size"]
        x, y = a / 2, b / 2
        v = np.array([[-x, -y, 0], [x, -y, 0], [x, y, 0], [-x, y, 0],
                      [-x, -y, c], [x, -y, c], [x, y, c], [-x, y, c]], float)
        f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
        return v[np.array(f)]
    if k == "sphere":
        r, n, m = s["radius"], SEGMENTS, SEGMENTS // 2
        th = np.linspace(0, np.pi, m + 1)
        rings = [_ring(r * np.sin(t), r * np.cos(t), n) for t in th]
        tris = []
        for i in range(m):
            for j in range(n):
                p, q = rings[i], rings[i + 1]
                tris += [(p[j], q[j], q[(j + 1) % n]), (p[j], q[(j + 1) % n], p[(j + 1) % n])]
        return np.array(tris)
    r0, h = s["radius"], s["height"]
    r1 = s.get("top_radius", r0) if k == "cone" else r0
    lo, hi = _ring(r0, 0), _ring(max(r1, 1e-6), h)
    n, tris = SEGMENTS, []
    for j in range(n):
        k2 = (j + 1) % n
        tris += [(lo[j], lo[k2], hi[k2]), (lo[j], hi[k2], hi[j]),
                 ((0, 0, 0), lo[k2], lo[j]), ((0, 0, h), hi[j], hi[k2])]
    return np.array(tris, float)


def shape_meshes(doc: dict) -> tuple[list, list]:
    """Each shape as its own closed mesh, placed as modelkit places it:
    (adds, cuts). What a concept's joints are planned on (nemo/joints.py)."""
    import trimesh
    adds, cuts = [], []
    for s in doc["shapes"]:
        tris = _placed_tris(s)
        m = trimesh.Trimesh(**trimesh.triangles.to_kwargs(tris))
        m.merge_vertices()
        (adds if s["op"] == "add" else cuts).append(m)
    return adds, cuts


def triangles(doc: dict):
    """Every added shape's triangles, rotated and placed as modelkit does."""
    import numpy as np
    return np.concatenate([_placed_tris(s) for s in doc["shapes"] if s["op"] == "add"])


def _placed_tris(s: dict):
    """One shape's triangles, rotated and placed as modelkit does."""
    import numpy as np
    t = _solid_tris(s).reshape(-1, 3)
    for axis, ang in enumerate(s.get("rotate") or [0, 0, 0]):
        if ang:
            c, sn = np.cos(np.radians(ang)), np.sin(np.radians(ang))
            if axis == 0:
                m = np.array([[1, 0, 0], [0, c, -sn], [0, sn, c]])
            elif axis == 1:
                m = np.array([[c, 0, sn], [0, 1, 0], [-sn, 0, c]])
            else:
                m = np.array([[c, -sn, 0], [sn, c, 0], [0, 0, 1]])
            t = t @ m.T
    return (t + np.array(s["at"], float)).reshape(-1, 3, 3)


PAPER = (252, 252, 250)
INK = (24, 24, 26)
MARKERS = (0.93, 0.74, 0.52)       # three grey markers, light to dark (of white)


def _marker(rgb, shadow: bool):
    """A rendered view as a designer's marker drawing: bold ink outlines,
    three grey markers with faint strokes, white paper, a soft shadow."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    size = rgb.shape[0]
    g = np.asarray(Image.fromarray(rgb).convert("L"), float) / 255
    bg = np.all(np.abs(rgb.astype(int) - np.array([247, 247, 243])) < 3, axis=2)
    tone = np.where(g > 0.62, MARKERS[0], np.where(g > 0.48, MARKERS[1], MARKERS[2]))
    yy, xx = np.mgrid[0:size, 0:size]
    streak = 0.035 * np.sin((xx * 0.9 + yy * 0.35) / 2.3)          # the marker's strokes
    shade = np.clip(tone + streak, 0, 1)
    edges = np.asarray(Image.fromarray((g * 255).astype(np.uint8)).filter(ImageFilter.FIND_EDGES),
                       float) / 255 > 0.14
    outline = np.asarray(Image.fromarray(((edges & ~bg) * 255).astype(np.uint8))
                         .filter(ImageFilter.MaxFilter(3)), float) > 0
    silhouette = np.asarray(Image.fromarray((~bg * 255).astype(np.uint8))
                            .filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5)), float) > 0
    page = Image.new("RGB", (size, size), PAPER)
    if shadow and (~bg).any():
        ys, xs = np.nonzero(~bg)
        cx, bottom, w = xs.mean(), ys.max(), xs.max() - xs.min()
        sh = Image.new("L", (size, size), 0)
        ImageDraw.Draw(sh).ellipse([cx - w * 0.45, bottom - w * 0.06, cx + w * 0.45, bottom + w * 0.06],
                                   fill=70)
        sh = sh.filter(ImageFilter.GaussianBlur(max(4, size // 40)))
        page = Image.composite(Image.new("RGB", (size, size), (200, 200, 200)), page, sh)
    base = np.asarray(page, float)
    obj = np.stack([shade * 255] * 3, -1)
    img = np.where(bg[..., None], base, obj)
    img = np.where((outline | (silhouette & ~bg))[..., None], np.array(INK, float), img)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def sketch_png(doc: dict, path: Path, title: str, size: int = 360) -> Path:
    """The blockout as a designer's marker render (owner, 2026-10-28): a big
    three-quarter view with a soft shadow, small front and top views beside
    it, the overall size beneath. Falls back to flat views without numpy."""
    try:
        from .render import render_view
        tris = triangles(doc)
    except ImportError:
        return views_png(doc, path, title)
    from PIL import Image, ImageDraw
    small = size // 2 - 6
    big = _marker(render_view(tris, "iso", size), shadow=True)
    front = _marker(render_view(tris, "front", small), shadow=False)
    top = _marker(render_view(tris, "top", small), shadow=False)
    W, H = size + small + 24, size + 48
    out = Image.new("RGB", (W, H), PAPER)
    out.paste(big, (0, 0))
    x = size + 12
    out.paste(front, (x, 14)); out.paste(top, (x, small + 34))
    d = ImageDraw.Draw(out)
    d.line([(size + 4, 10), (size + 4, size - 10)], fill=(220, 220, 216))
    d.text((x + 2, 0), "Front", fill=(120, 120, 120))
    d.text((x + 2, small + 20), "Top", fill=(120, 120, 120))
    lo, hi = bounds(doc)
    span = [h - l for l, h in zip(lo, hi)]
    d.text((12, size + 6), title, fill=INK)
    d.text((12, size + 24), f"{span[0]:.0f} long x {span[1]:.0f} wide x {span[2]:.0f} high, mm",
           fill=(110, 110, 110))
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)
    return path
