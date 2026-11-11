"""The Art Studio's Designer and Editor: 3D printable models from a kit of
shapes (owner, 2026-10-21: "shapes from a list"; the Editor's checks).

A model is a list of shapes, each added or cut, with its size and where it
sits. Code writes the CadQuery script from that list and runs it; the model
of language is never asked to write CadQuery (docs/design-rules.md 4d). It suits
stands, plaques, holders and simple replicas made of plain solids; it cannot
make faces, figures or anything organic, and says so rather than trying.

The shapes (sizes in mm; `at` is [x, y, z]: the middle of the shape's foot
on the x-y plane, and the height of its foot; a sphere's `at` is its middle):

  box          size [x, y, z]
  rounded_box  size [x, y, z], radius (of the upright edges)
  cylinder     radius, height
  cone         radius (foot), top_radius, height
  sphere       radius
  plate        size [x, y], thickness       (a base: a box at the bottom)
  text         text, size (letter height), depth

Each may have `rotate` [rx, ry, rz] in degrees, about its own `at`, and
`op`: "add" (the default) or "cut". Adds are joined, in order, and then
cuts are taken away, in order.

The Editor checks what is made against what was asked (editor_checks): the
mesh is there, closed and manifold, no wall is thinner than the printer's
minimum, it fits the printer, and its size is the size the shapes add up to.

Each model is a folder in paths.models: spec.json, model.py, model.stl,
iso.png, checks.json.
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SHAPES = {
    "box": ("size",),
    "rounded_box": ("size", "radius"),
    "cylinder": ("radius", "height"),
    "cone": ("radius", "top_radius", "height"),
    "sphere": ("radius",),
    "plate": ("size", "thickness"),
    "text": ("text", "size", "depth"),
    # A flat convex outline in the side view (x, z), given a thickness across
    # (y): a butt that tapers to the wrist (2026-11-04, nemo/anatomy.py).
    "prism": ("points", "width"),
}
MAX_SHAPES = 40
SMALLEST = 0.4                # mm: the nozzle; nothing thinner can print


class ModelError(ValueError):
    """The list of shapes cannot be made; the message says why."""


@dataclass
class Spec:
    name: str
    shapes: list[dict] = field(default_factory=list)


def _num(v, what: str, lo: float = SMALLEST, hi: float = 1000.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ModelError(f"{what} must be a number, not {v!r}") from None
    if not lo <= x <= hi:
        raise ModelError(f"{what} must be between {lo:g} and {hi:g} mm, not {x:g}")
    return x


def _vec(v, n: int, what: str, lo: float, hi: float) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise ModelError(f"{what} must be {n} numbers")
    return [_num(x, f"{what} {i + 1}", lo, hi) for i, x in enumerate(v)]


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
    if not s:
        raise ModelError("give the model a name")
    return s


def validate(doc: dict) -> Spec:
    """A list of shapes that can be made, or ModelError saying why not."""
    if not isinstance(doc, dict):
        raise ModelError("a model is a name and a list of shapes")
    name = str(doc.get("name", "")).strip()
    slug(name)
    shapes = doc.get("shapes")
    if not isinstance(shapes, list) or not shapes:
        raise ModelError("a model needs at least one shape")
    if len(shapes) > MAX_SHAPES:
        raise ModelError(f"at most {MAX_SHAPES} shapes")
    out = []
    for i, s in enumerate(shapes, 1):
        if not isinstance(s, dict):
            raise ModelError(f"shape {i} is not a shape")
        kind = s.get("shape")
        if kind not in SHAPES:
            raise ModelError(f"shape {i}: {kind!r} is not in the kit; it has "
                             f"{', '.join(SHAPES)}")
        clean = {"shape": kind, "op": s.get("op", "add")}
        if clean["op"] not in ("add", "cut"):
            raise ModelError(f"shape {i}: op is add or cut, not {clean['op']!r}")
        for key in SHAPES[kind]:
            if key not in s:
                raise ModelError(f"shape {i} ({kind}) needs {key}")
            v = s[key]
            if key == "text":
                v = str(v).strip()
                if not v or len(v) > 40:
                    raise ModelError(f"shape {i}: text of 1 to 40 letters")
            elif key == "points":
                v = _outline(v, i)
            elif key == "size" and kind in ("box", "rounded_box"):
                v = _vec(v, 3, f"shape {i} size", SMALLEST, 1000)
            elif key == "size" and kind == "plate":
                v = _vec(v, 2, f"shape {i} size", SMALLEST, 1000)
            else:
                v = _num(v, f"shape {i} {key}", 0.0 if key == "top_radius" else SMALLEST)
            clean[key] = v
        if kind == "rounded_box" and clean["radius"] * 2 >= min(clean["size"][:2]):
            raise ModelError(f"shape {i}: the radius must be under half the shorter side")
        clean["at"] = _vec(s.get("at", [0, 0, 0]), 3, f"shape {i} at", -1000, 1000)
        clean["rotate"] = _vec(s.get("rotate", [0, 0, 0]), 3, f"shape {i} rotate", -360, 360)
        out.append(clean)
    if out[0]["op"] != "add":
        raise ModelError("the first shape must be added: there is nothing to cut from yet")
    return Spec(name, out)


def _outline(v, i: int) -> list[list[float]]:
    """A prism's outline: 3 to 12 [x, z] corners, in order, convex."""
    if not isinstance(v, list) or not 3 <= len(v) <= 12:
        raise ModelError(f"shape {i}: points is a list of 3 to 12 [x, z] corners")
    pts = [_vec(p, 2, f"shape {i} corner", -1000, 1000) for p in v]
    turns = []
    for j in range(len(pts)):
        (ax, az), (bx, bz), (cx, cz) = pts[j], pts[(j + 1) % len(pts)], pts[(j + 2) % len(pts)]
        turns.append((bx - ax) * (cz - bz) - (bz - az) * (cx - bx))
    if not (all(t > 1e-9 for t in turns) or all(t < -1e-9 for t in turns)):
        raise ModelError(f"shape {i}: the outline must be convex, its corners in order")
    return pts


def _extent(s: dict) -> tuple[list[float], list[float]]:
    """The shape's box (low, high) when it is not rotated."""
    x, y, z = s["at"]
    k = s["shape"]
    if k == "prism":
        xs = [p[0] for p in s["points"]]; zs = [p[1] for p in s["points"]]
        w = s["width"] / 2
        return [x + min(xs), y - w, z + min(zs)], [x + max(xs), y + w, z + max(zs)]
    if k in ("box", "rounded_box"):
        a, b, c = s["size"]
    elif k == "plate":
        (a, b), c = s["size"], s["thickness"]
    elif k in ("cylinder", "cone"):
        r = max(s["radius"], s.get("top_radius", 0))
        a = b = 2 * r
        c = s["height"]
    elif k == "sphere":
        r = s["radius"]
        return [x - r, y - r, z - r], [x + r, y + r, z + r]
    else:                                                   # text: an estimate
        a, b, c = 0.7 * s["size"] * len(s["text"]), s["size"], s["depth"]
    return [x - a / 2, y - b / 2, z], [x + a / 2, y + b / 2, z + c]


def expected_size(spec: Spec) -> list[float] | None:
    """What the added shapes span, where none is rotated or text; else None
    (a rotated or lettered shape's span is not worked out here)."""
    adds = [s for s in spec.shapes if s["op"] == "add"]
    if any(s["shape"] == "text" or any(s["rotate"]) for s in adds):
        return None
    lo = [min(_extent(s)[0][i] for s in adds) for i in range(3)]
    hi = [max(_extent(s)[1][i] for s in adds) for i in range(3)]
    return [round(h - l, 3) for l, h in zip(lo, hi)]


def lettered_size(spec: Spec) -> list[float] | None:
    """For a model whose only unworked shapes are letters (none rotated): what
    it should span when the letters sit within the rest across, and stand to
    their own top (2026-11-08: a key tag's size check was SKIPPED though its
    size is plain: 70 x 25 mm, 3 mm and 1 mm of raised letters). The letters'
    width is a font's, not known here: a model wider than the rest is not
    judged."""
    adds = [s for s in spec.shapes if s["op"] == "add"]
    if any(any(s["rotate"]) for s in adds):
        return None
    body = [s for s in adds if s["shape"] != "text"]
    text = [s for s in adds if s["shape"] == "text"]
    if not body or not text:
        return None
    lo = [min(_extent(s)[0][i] for s in body) for i in range(3)]
    hi = [max(_extent(s)[1][i] for s in body) for i in range(3)]
    top = max(hi[2], max(s["at"][2] + s["depth"] for s in text))
    return [round(hi[0] - lo[0], 3), round(hi[1] - lo[1], 3), round(top - lo[2], 3)]


def _solid(s: dict) -> str:
    """CadQuery for one shape, its foot on z=0 and centred, before it moves."""
    k = s["shape"]
    if k == "box":
        a, b, c = s["size"]
        return f"cq.Workplane('XY').box({a}, {b}, {c}, centered=(True, True, False))"
    if k == "rounded_box":
        a, b, c = s["size"]
        return (f"cq.Workplane('XY').box({a}, {b}, {c}, centered=(True, True, False))"
                f".edges('|Z').fillet({s['radius']})")
    if k == "plate":
        (a, b), c = s["size"], s["thickness"]
        return f"cq.Workplane('XY').box({a}, {b}, {c}, centered=(True, True, False))"
    if k == "cylinder":
        return f"cq.Workplane('XY').circle({s['radius']}).extrude({s['height']})"
    if k == "cone":
        return (f"cq.Solid.makeCone({s['radius']}, {s['top_radius']}, {s['height']})")
    if k == "sphere":
        return f"cq.Workplane('XY').sphere({s['radius']})"
    if k == "prism":
        pts = [tuple(p) for p in s["points"]]
        return (f"cq.Workplane('XZ').polyline({pts}).close()"
                f".extrude({s['width'] / 2}, both=True)")
    return (f"cq.Workplane('XY').text({json.dumps(s['text'])}, {s['size']}, {s['depth']}, "
            "halign='center', valign='center', combine=False)")


def script(spec: Spec) -> str:
    """The CadQuery script, written by code from the list of shapes."""
    lines = ["# Written by Nemo's Art Studio Designer from spec.json; not by a model.",
             "import cadquery as cq", "", "def place(w, at, rot):",
             "    if isinstance(w, cq.Shape):",
             "        w = cq.Workplane('XY').add(w)",
             "    for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rot):",
             "        if angle:",
             "            w = w.rotate((0, 0, 0), axis, angle)",
             "    return w.translate(tuple(at))", "", "model = None"]
    for i, s in enumerate(spec.shapes, 1):
        lines.append(f"s{i} = place({_solid(s)}, {s['at']}, {s['rotate']})  # {s['shape']}, {s['op']}")
    adds = [i for i, s in enumerate(spec.shapes, 1) if s["op"] == "add"]
    cuts = [i for i, s in enumerate(spec.shapes, 1) if s["op"] == "cut"]
    lines.append(f"model = s{adds[0]}")
    lines += [f"model = model.union(s{i})" for i in adds[1:]]
    lines += [f"model = model.cut(s{i})" for i in cuts]
    lines += ["cq.exporters.export(model, 'model.stl', tolerance=0.05, angularTolerance=0.1)", ""]
    return "\n".join(lines)


def tidy_stl(path: Path) -> bool:
    """CadQuery's mesh of a sphere left two holes, one at each pole: the pole's
    two vertices were written as 0.0 and -0.0, so they were not one point, and
    the Editor failed every model with a sphere in it ("not a valid solid";
    D224, 2026-11-05). Coincident vertices are made one, and the zero-area
    triangles they leave are dropped. False (the file as it was) where trimesh
    is not installed or the mesh will not read."""
    try:
        import numpy as np
        import trimesh
        m = trimesh.load_mesh(str(path), process=False)
        v = np.array(m.vertices, dtype=float)
        v[np.abs(v) < 1e-9] = 0.0                       # -0.0 and 0.0 are one place
        m = trimesh.Trimesh(vertices=v, faces=m.faces, process=False)
        m.merge_vertices(digits_vertex=6)
        m.update_faces(m.nondegenerate_faces())
        m.update_faces(m.unique_faces())
        m.remove_unreferenced_vertices()
        m.export(str(path))
        return True
    except Exception:                                           # noqa: BLE001
        return False


def folder(cfg, name: str) -> Path:
    return cfg.path("paths.models") / slug(name)


def build(cfg, doc: dict, timeout: int = 900) -> tuple[Path, list]:
    """Make the model: spec.json, model.py, model.stl, then the Editor's
    checks and a picture. Returns (folder, check results)."""
    from .checks import FAIL, Result
    from .checks.runners import _run
    spec = validate(doc)
    out = folder(cfg, spec.name)
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.json").write_text(json.dumps({"name": spec.name, "shapes": spec.shapes},
                                              indent=1), encoding="utf-8")
    (out / "model.py").write_text(script(spec), encoding="utf-8")
    if isinstance(doc.get("from"), dict):             # the Clerk's choices, for the Writer
        from . import artstudio
        artstudio.write_about(out, made_from=doc["from"])
    stl = out / "model.stl"
    stl.unlink(missing_ok=True)                 # an old mesh proves nothing
    began = time.time()
    rc, so, se = _run([sys.executable, "model.py"], cwd=out, timeout=timeout)
    if rc != 0 or not stl.exists():
        text = ((se or "") + (so or "")).strip().splitlines()[-6:]
        why = ("CadQuery is not installed" if re.search(r"No module named ['\"](cadquery|OCP)",
                                                         "\n".join(text))
               else f"the script failed (code {rc})" if rc else "the script wrote no model.stl")
        results = [Result("model_made", FAIL, why, text)]
    else:
        tidy_stl(stl)
        results = editor_checks(cfg, out, spec)
    from . import timekeeper
    timekeeper.record("art_studio", "model build", time.time() - began,
                      all(r.status != FAIL for r in results))
    (out / "checks.json").write_text(json.dumps(
        [{"name": r.name, "status": r.status, "detail": r.detail, "items": list(r.items)}
         for r in results], indent=1), encoding="utf-8")
    return out, results


def editor_checks(cfg, out: Path, spec: Spec) -> list:
    """The Editor: does what was made match what was asked, and will it print?"""
    from .checks import FAIL, PASS, SKIP, Result
    from .checks.runners import solid, thickness
    stl = out / "model.stl"
    results = [Result("model_made", PASS, f"{stl.name} written")]
    results.append(solid(stl))
    results.append(thickness(stl, float(cfg.get("hardware.min_wall_mm", 1.2))))
    try:
        from .render import read_stl
        tris = read_stl(stl).reshape(-1, 3)
        size = [round(float(v), 2) for v in tris.max(0) - tris.min(0)]
    except Exception as exc:                                    # noqa: BLE001
        results.append(Result("fits_printer", SKIP, f"could not measure the mesh: {exc}"))
        return results
    volume = [float(v) for v in cfg.get("hardware.build_volume_mm", [250, 250, 260])]
    over = [f"{'xyz'[i]} {size[i]:g} > {volume[i]:g} mm" for i in range(3) if size[i] > volume[i]]
    results.append(Result("fits_printer", FAIL if over else PASS,
                          ("too big for the printer: " + ", ".join(over)) if over
                          else f"{size[0]:g} x {size[1]:g} x {size[2]:g} mm fits "
                               f"{volume[0]:g} x {volume[1]:g} x {volume[2]:g} mm",
                          # The Designer can cut it into pieces that fit (nemo/joints.py).
                          [f"The Designer can split it into pieces that fit, pinned together: "
                           f"nemo model split {spec.name}"] if over else []))
    want = expected_size(spec)
    lettered = lettered_size(spec) if want is None else None
    if lettered is not None and all(size[i] <= lettered[i] + 0.2 for i in range(2)):
        off = [abs(a - b) for a, b in zip(size, lettered)]
        cuts = any(s["op"] == "cut" for s in spec.shapes)
        bad = [i for i in range(3) if size[i] > lettered[i] + 0.2 or (off[i] > 0.2 and not cuts)]
        results.append(Result("size_as_asked", FAIL if bad else PASS,
                              f"made {size}; the base and its letters add up to {lettered}"))
    elif want is None:
        results.append(Result("size_as_asked", SKIP, "a rotated shape, or letters reaching past "
                                                     "the rest: the size it should be is not "
                                                     "worked out", [f"made {size}"]))
    else:
        off = [abs(a - b) for a, b in zip(size, want)]
        # Cut shapes may only take away; so made may be smaller, never larger.
        bad = [i for i in range(3) if size[i] > want[i] + 0.2 or (off[i] > 0.2 and not any(
            s["op"] == "cut" for s in spec.shapes))]
        results.append(Result("size_as_asked", FAIL if bad else PASS,
                              f"made {size}, the shapes add up to {want}"))
    try:
        from .render import render_stl
        render_stl(stl, out, views=["iso"], name="model")
    except Exception:                                           # noqa: BLE001
        pass                                                    # a picture is not a check
    return results


def models(cfg) -> list[dict]:
    """Every model made, newest first, with whether its checks passed."""
    root = cfg.path("paths.models")
    out = []
    for d in sorted(root.glob("*/spec.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if root.is_dir() else []:
        try:
            checks = json.loads((d.parent / "checks.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            checks = []
        out.append({"name": json.loads(d.read_text(encoding="utf-8")).get("name", d.parent.name),
                    "folder": d.parent,
                    "passed": bool(checks) and all(c["status"] != "FAIL" for c in checks)})
    return out

