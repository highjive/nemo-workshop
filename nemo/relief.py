"""A relief from a picture: the Art Studio's way to put a face or a painting into
something printable (owner, 2026-11-18: "asked art studio to make a 3d sculture of
mona lisa"; he chose this when told Nemo cannot sculpt a face).

What it is, plainly: a flat panel whose top is raised by the picture's light and
dark, like a coin or a carved plaque. It is NOT a statue: the far side and the
depth of a face are not in a picture, and nothing here guesses them.

Two ways to read the picture:
  relief      light parts stand up, dark parts sink (a carved panel, seen lit from
              the front)
  lithophane  dark parts are thick, light parts thin, so it shows the picture when a
              light is behind it (print it in white, standing up)

Everything is decided by code from the picture and the sizes (docs/design-rules.md
4d): no model is asked. The mesh is written straight from a height grid with numpy,
closed underneath and round the sides, so it is one watertight solid; the Art
Studio's Editor then checks it as it checks any model (solid, walls, fits the
printer, the size asked), and the Print Shop can slice it.

The picture is the owner's: Nemo never downloads one. He puts it on the Storeroom's
pictures shelf (or gives its path).
"""
from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass
from pathlib import Path

MODES = ("relief", "lithophane")
WIDTH_MM = 100.0          # across the picture's width
DEPTH_MM = 3.0            # from the lowest to the highest point of the picture
BASE_MM = 2.0             # the solid back under the lowest point
PITCH_MM = 0.5            # one height every this many mm: about a 0.4 mm nozzle's line
LITHO_THIN_MM = 0.8       # a lithophane's lightest part (light must get through)
BORDER_MM = 3.0           # a flat rim, at the full height, so the edge is not ragged
SMOOTH = 1                # a 3 x 3 average, once: a printer cannot draw single pixels
MAX_CELLS = 400_000       # past this the file is huge and the Editor slow: said, refused
PICTURES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")


class ReliefError(Exception):
    """Something the owner can act on, said plainly."""


@dataclass
class Plan:
    picture: Path
    mode: str
    width_mm: float
    height_mm: float
    depth_mm: float
    base_mm: float
    pitch_mm: float
    cols: int
    rows: int

    @property
    def thickness_mm(self) -> float:
        return self.base_mm + self.depth_mm


# ------------------------------------------------------------------ the picture
def find_picture(cfg, name: str) -> Path:
    """The picture called `name` on the pictures shelf (whole name first, then a
    name containing every word), or `name` as a path. Raises ReliefError, listing
    what is on the shelf, when there is none or more than one."""
    p = Path(name).expanduser()
    if p.is_file() and p.suffix.lower() in PICTURES:
        return p
    from . import storeroom
    shelf = storeroom.shelf(cfg.path("paths.storeroom"), "pictures")
    found = sorted(q for q in shelf.rglob("*") if q.suffix.lower() in PICTURES) if shelf.is_dir() else []
    want = name.lower().strip()
    exact = [q for q in found if q.stem.lower() == want or q.name.lower() == want]
    if len(exact) == 1:
        return exact[0]
    words = [w for w in want.replace("-", " ").replace("_", " ").split() if w]
    some = [q for q in found if all(w in q.stem.lower().replace("-", " ").replace("_", " ")
                                    for w in words)] if words else []
    if len(some) == 1:
        return some[0]
    names = ", ".join(q.stem for q in found[:12]) + (" ..." if len(found) > 12 else "")
    if not some:
        raise ReliefError(f"no picture called {name!r} on the pictures shelf ({shelf}). "
                          "Put the picture there first; Nemo never downloads one"
                          + (f". On the shelf now: {names}" if found else ". The shelf is empty"))
    raise ReliefError(f"{len(some)} pictures match {name!r}: "
                      + ", ".join(q.stem for q in some[:8]) + ". Say which, by its whole name")


def plan(picture: Path, mode: str = "relief", width_mm: float = WIDTH_MM,
         depth_mm: float = DEPTH_MM, base_mm: float = BASE_MM, pitch_mm: float = PITCH_MM,
         min_wall_mm: float = 1.2) -> Plan:
    """Check the sizes against the picture and the rules; the grid it will be."""
    from PIL import Image
    if mode not in MODES:
        raise ReliefError(f"the way to read the picture is one of {', '.join(MODES)}, not {mode!r}")
    for what, v, lo, hi in (("width", width_mm, 20, 400), ("depth", depth_mm, 0.4, 20),
                            ("base", base_mm, 0.4, 20), ("pitch", pitch_mm, 0.2, 2)):
        if not lo <= v <= hi:
            raise ReliefError(f"the {what} must be between {lo:g} and {hi:g} mm, not {v:g}")
    if mode == "relief" and base_mm < min_wall_mm:
        raise ReliefError(f"the base ({base_mm:g} mm) is thinner than the printer's least wall "
                          f"({min_wall_mm:g} mm, hardware.min_wall_mm)")
    if mode == "lithophane" and LITHO_THIN_MM + depth_mm < min_wall_mm:
        raise ReliefError("a lithophane that thin would not hold together: give a depth of at "
                          f"least {min_wall_mm - LITHO_THIN_MM:g} mm")
    try:
        with Image.open(picture) as im:
            w, h = im.size
    except OSError as exc:
        raise ReliefError(f"{Path(picture).name} could not be read as a picture: {exc}")
    cols = max(8, round(width_mm / pitch_mm) + 1)            # points, so (cols - 1) gaps = the width
    rows = max(8, round(cols * h / w))
    if cols * rows > MAX_CELLS:
        raise ReliefError(f"{cols} x {rows} points is too many to print or check here: make it "
                          f"narrower, or give a coarser pitch (at most {MAX_CELLS:,} points)")
    base = LITHO_THIN_MM if mode == "lithophane" else base_mm
    return Plan(Path(picture), mode, round((cols - 1) * pitch_mm, 3), round((rows - 1) * pitch_mm, 3),
                depth_mm, base, pitch_mm, cols, rows)


def heights(p: Plan):
    """The height of the top at every grid point, in mm (rows x cols)."""
    import numpy as np
    from PIL import Image, ImageOps
    with Image.open(p.picture) as im:
        im = ImageOps.exif_transpose(im).convert("L").resize((p.cols, p.rows), Image.LANCZOS)
        g = np.asarray(im, dtype=float) / 255.0                 # 0 dark .. 1 light
    for _ in range(SMOOTH):
        pad = np.pad(g, 1, mode="edge")
        g = sum(pad[dy:dy + p.rows, dx:dx + p.cols] for dy in range(3) for dx in range(3)) / 9.0
    lo, hi = float(g.min()), float(g.max())
    g = (g - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(g)    # its whole range used
    if p.mode == "lithophane":
        g = 1.0 - g                                             # dark is thick
    z = p.base_mm + p.depth_mm * g
    rim = max(1, round(BORDER_MM / p.pitch_mm))
    z[:rim, :] = z[-rim:, :] = z[:, :rim] = z[:, -rim:] = p.base_mm + p.depth_mm
    return np.flipud(z)                    # row 0 of the picture is its top: y grows upward


# ------------------------------------------------------------------ the mesh
def triangles(z, pitch: float):
    """One closed solid from a height grid: the top, a flat underside at z = 0 and
    four walls. Faces wind outward (counter-clockwise seen from outside)."""
    import numpy as np
    rows, cols = z.shape
    xs, ys = np.meshgrid(np.arange(cols) * pitch, np.arange(rows) * pitch)
    top = np.stack([xs, ys, z], -1)
    bot = np.stack([xs, ys, np.zeros_like(z)], -1)

    def quads(a, b, c, d):          # corners in order round the quad: two triangles
        return np.concatenate([np.stack([a, b, c], -2), np.stack([a, c, d], -2)])

    t00, t10, t01, t11 = top[:-1, :-1], top[:-1, 1:], top[1:, :-1], top[1:, 1:]
    b00, b10, b01, b11 = bot[:-1, :-1], bot[:-1, 1:], bot[1:, :-1], bot[1:, 1:]
    parts = [quads(t00, t10, t11, t01).reshape(-1, 3, 3),            # top, facing up
             quads(b00, b01, b11, b10).reshape(-1, 3, 3)]            # underside, facing down
    # walls: front (y = 0) faces -y, back faces +y, left (x = 0) faces -x, right +x
    f_t, f_b = top[0], bot[0]
    parts.append(quads(f_b[:-1], f_b[1:], f_t[1:], f_t[:-1]).reshape(-1, 3, 3))
    k_t, k_b = top[-1], bot[-1]
    parts.append(quads(k_b[1:], k_b[:-1], k_t[:-1], k_t[1:]).reshape(-1, 3, 3))
    l_t, l_b = top[:, 0], bot[:, 0]
    parts.append(quads(l_b[1:], l_b[:-1], l_t[:-1], l_t[1:]).reshape(-1, 3, 3))
    r_t, r_b = top[:, -1], bot[:, -1]
    parts.append(quads(r_b[:-1], r_b[1:], r_t[1:], r_t[:-1]).reshape(-1, 3, 3))
    return np.concatenate(parts).astype("<f4")


def write_stl(path: Path, tris) -> int:
    """A binary STL of (n, 3, 3) triangles, normals worked out. Returns n."""
    import numpy as np
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    length = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(length > 0, n / np.where(length > 0, length, 1), 0).astype("<f4")
    rec = np.zeros(len(tris), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tris
    with open(path, "wb") as f:
        f.write(b"Nemo Art Studio relief".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        f.write(rec.tobytes())
    return len(tris)


# ------------------------------------------------------------------ the Art Studio
def make(cfg, name: str, picture: str, mode: str = "relief", width_mm: float = WIDTH_MM,
         depth_mm: float = DEPTH_MM, base_mm: float = BASE_MM, pitch_mm: float = PITCH_MM,
         say=print) -> tuple[Path, list]:
    """Build the relief into paths.models/<name>, as the Art Studio builds any model,
    and have its Editor check it. Returns (folder, check results)."""
    from . import modelkit, timekeeper
    from .checks import FAIL, PASS, Result
    from .checks.runners import solid, thickness
    began = time.time()
    pic = find_picture(cfg, picture)
    min_wall = float(cfg.get("hardware.min_wall_mm", 1.2))
    p = plan(pic, mode, width_mm, depth_mm, base_mm, pitch_mm, min_wall)
    out = modelkit.folder(cfg, name)
    out.mkdir(parents=True, exist_ok=True)
    say(f"Designer: a {p.mode} of {pic.name}, {p.width_mm:g} x {p.height_mm:g} mm, "
        f"{p.base_mm:g} mm back + {p.depth_mm:g} mm of picture, a point every {p.pitch_mm:g} mm "
        f"({p.cols} x {p.rows}).")
    (out / "spec.json").write_text(json.dumps(
        {"name": name, "kind": "relief", "mode": p.mode, "picture": str(pic),
         "width_mm": p.width_mm, "height_mm": p.height_mm, "depth_mm": p.depth_mm,
         "base_mm": p.base_mm, "pitch_mm": p.pitch_mm, "shapes": []}, indent=1), encoding="utf-8")
    (out / "model.py").unlink(missing_ok=True)            # not made by a script
    stl = out / "model.stl"
    stl.unlink(missing_ok=True)
    count = write_stl(stl, triangles(heights(p), p.pitch_mm))
    say(f"Designer: {count:,} triangles written to {stl.name}.")
    results = [Result("model_made", PASS, f"{stl.name} written, {count:,} triangles")]
    results.append(solid(stl))
    results.append(thickness(stl, min_wall))
    want = [p.width_mm, p.height_mm, round(p.thickness_mm, 3)]
    try:
        from .render import read_stl
        tris = read_stl(stl).reshape(-1, 3)
        size = [round(float(v), 2) for v in tris.max(0) - tris.min(0)]
        volume = [float(v) for v in cfg.get("hardware.build_volume_mm", [250, 250, 260])]
        over = [f"{'xyz'[i]} {size[i]:g} > {volume[i]:g} mm" for i in range(3) if size[i] > volume[i]]
        results.append(Result("fits_printer", FAIL if over else PASS,
                              ("too big for the printer: " + ", ".join(over)) if over else
                              f"{size[0]:g} x {size[1]:g} x {size[2]:g} mm fits "
                              f"{volume[0]:g} x {volume[1]:g} x {volume[2]:g} mm",
                              ["Make it narrower: width=<mm>"] if over else []))
        bad = [i for i in range(3) if abs(size[i] - want[i]) > 0.05]
        results.append(Result("size_as_asked", FAIL if bad else PASS,
                              f"made {size}, asked {want}"))
    except Exception as exc:                                     # noqa: BLE001
        results.append(Result("fits_printer", FAIL, f"could not measure the mesh: {exc}"))
    try:
        from .render import render_stl
        render_stl(stl, out, views=["iso", "top"], name="model")  # top: the picture itself
    except Exception:                                            # noqa: BLE001
        pass                                                     # a picture is not a check
    (out / "checks.json").write_text(json.dumps(
        [{"name": r.name, "status": r.status, "detail": r.detail, "items": list(r.items)}
         for r in results], indent=1), encoding="utf-8")
    from . import artstudio
    try:
        artstudio.write_about(out, made_from={"kind": "relief", "picture": pic.name, "mode": p.mode})
    except Exception:                                            # noqa: BLE001
        pass
    timekeeper.record("art_studio", "relief build", time.time() - began,
                      all(r.status != FAIL for r in results))
    return out, results
