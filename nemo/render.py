"""Pictures of the real enclosure, made by geometry and not by a model.

An image-generation model asked for "the enclosure" draws a plausible box.
This draws *the* box: the STL the design step produced, projected exactly,
so a wall, a cutout or a boss appears where the file has it and nowhere
else. It is a review tool, not an illustration: a person can see that the
speaker hole is on the wrong face before anything is printed.

What it is:
  * orthographic views (iso, top, bottom, front, right) of housing.stl
  * flat-shaded, with dark lines where the surface bends or ends
  * the same STL always gives the same bytes, so a render can be compared
    with an earlier one and is safe to keep in git

What it is not: no textures, no perspective, no labels (numbers live in the
text report), and no software-renderer speed miracles -- it is a numpy
z-buffer. Measured on the target machine (Pentium B960): the four default
views plus the sheet of a 30,272-triangle part take 20 s, and of a
60,512-triangle part 37 s, so about 5 s a view at 30k triangles. (An
earlier line here promised "a fraction of a second per view"; that was
never timed.)

Needs numpy, which is in the optional `cad` extra like every other CAD tool
here, and reads STL itself (binary or ASCII) so it does not also need
trimesh.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

VIEWS = {
    # name: (direction from the object toward the camera, up)
    "iso":    ((1.0, -1.0, 0.9), (0.0, 0.0, 1.0)),
    "top":    ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "front":  ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right":  ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
}
DEFAULT_VIEWS = ["iso", "top", "front", "right"]
BACKGROUND = (247, 247, 243)
BASE = (0.60, 0.69, 0.78)          # the material colour, before shading


class RenderError(Exception):
    """Something a person can act on, never a traceback."""


def _np():
    try:
        import numpy as np
    except ImportError:
        raise RenderError("Rendering needs numpy. Install it with:  pip install numpy  "
                          "(it is part of the optional cad extra).")
    return np


# ====================================================================
#  STL in
# ====================================================================

def read_stl(path: Path):
    """Triangles as an (n, 3, 3) float array: n triangles, 3 corners, xyz."""
    np = _np()
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise RenderError(f"{Path(path).name} is too short to be an STL file.")
    count = struct.unpack("<I", data[80:84])[0]
    if len(data) == 84 + 50 * count and count > 0:            # binary, exact size
        rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        return np.frombuffer(data, dtype=rec, count=count, offset=84)["v"].astype(np.float64)
    text = data.decode("utf-8", errors="replace")
    if "facet" in text[:2000] or "vertex" in text:
        nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
        if not nums or len(nums) % 3:
            raise RenderError(f"{Path(path).name}: the ASCII STL has an incomplete triangle.")
        return np.array(nums, dtype=np.float64).reshape(-1, 3, 3)
    raise RenderError(f"{Path(path).name} is not a readable STL (neither binary nor ASCII).")


# ====================================================================
#  PNG out (standard library only)
# ====================================================================

def png_bytes(rgb) -> bytes:
    np = _np()
    h, w, _ = rgb.shape

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + np.ascontiguousarray(rgb[y]).tobytes() for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ====================================================================
#  The rasteriser
# ====================================================================

def _unit(v):
    np = _np()
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def render_view(tris, view: str, size: int = 480, ssaa: int = 2):
    """One view as an (size, size, 3) uint8 array."""
    np = _np()
    if view not in VIEWS:
        raise RenderError(f"Unknown view '{view}'. Choose from: {', '.join(VIEWS)}.")
    eye, up = _unit(VIEWS[view][0]), _unit(VIEWS[view][1])
    fwd = -eye
    right = _unit(np.cross(fwd, up))
    up2 = np.cross(right, fwd)

    ctr = (tris.reshape(-1, 3).max(0) + tris.reshape(-1, 3).min(0)) / 2
    p = tris - ctr
    sx, sy, depth = p @ right, p @ up2, p @ eye                # each (n, 3)
    S = size * ssaa
    margin = int(S * 0.07)
    span = max(sx.max() - sx.min(), sy.max() - sy.min(), 1e-9)
    scale = (S - 2 * margin) / span
    px = (sx - (sx.max() + sx.min()) / 2) * scale + S / 2
    py = S / 2 - (sy - (sy.max() + sy.min()) / 2) * scale

    # Flat shading from a light above-left of the camera. Two-sided, so a
    # mesh with flipped normals is not rendered black.
    e1, e2 = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    nrm = np.cross(e1, e2)
    ln = np.linalg.norm(nrm, axis=1)
    nrm = nrm / np.where(ln == 0, 1, ln)[:, None]
    light = _unit(0.75 * eye + 0.55 * up2 - 0.35 * right)
    lit = 0.34 + 0.66 * np.abs(nrm @ light)
    colours = (np.array(BASE)[None, :] * lit[:, None])

    zbuf = np.full((S, S), -np.inf)
    img = np.tile(np.array(BACKGROUND, dtype=np.float64) / 255, (S, S, 1))
    x0, x1, x2 = px[:, 0], px[:, 1], px[:, 2]
    y0, y1, y2 = py[:, 0], py[:, 1], py[:, 2]
    den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    xmin = np.clip(np.floor(px.min(1)), 0, S - 1).astype(int)
    xmax = np.clip(np.ceil(px.max(1)), 0, S - 1).astype(int)
    ymin = np.clip(np.floor(py.min(1)), 0, S - 1).astype(int)
    ymax = np.clip(np.ceil(py.max(1)), 0, S - 1).astype(int)
    for i in np.nonzero(np.abs(den) > 1e-12)[0]:
        xs = np.arange(xmin[i], xmax[i] + 1) + 0.5
        ys = (np.arange(ymin[i], ymax[i] + 1) + 0.5)[:, None]
        a = ((y1[i] - y2[i]) * (xs - x2[i]) + (x2[i] - x1[i]) * (ys - y2[i])) / den[i]
        b = ((y2[i] - y0[i]) * (xs - x2[i]) + (x0[i] - x2[i]) * (ys - y2[i])) / den[i]
        c = 1 - a - b
        inside = (a >= -1e-9) & (b >= -1e-9) & (c >= -1e-9)
        if not inside.any():
            continue
        z = a * depth[i, 0] + b * depth[i, 1] + c * depth[i, 2]
        sl = (slice(ymin[i], ymax[i] + 1), slice(xmin[i], xmax[i] + 1))
        m = inside & (z > zbuf[sl])
        if m.any():
            zbuf[sl][m] = z[m]
            img[sl][m] = colours[i]

    covered = np.isfinite(zbuf)
    if covered.any():
        # Flat shading alone cannot show that a tray is hollow from above:
        # the floor and the rim face the same way and shade the same. So
        # nearer surfaces are drawn slightly lighter than farther ones, and
        # a line is drawn wherever the depth jumps.
        zmin = zbuf[covered].min()
        zr = max(zbuf[covered].max() - zmin, 1e-9)
        zz = np.where(covered, zbuf, zmin - 10 * zr)
        cue = 0.78 + 0.22 * (np.where(covered, zbuf, zmin) - zmin) / zr
        img = np.where(covered[..., None], img * cue[..., None], img)
        g = img.mean(2)
        edge = np.zeros(g.shape, dtype=bool)
        for axis in (0, 1):
            d = (np.abs(np.diff(g, axis=axis)) > 0.05) | (np.abs(np.diff(zz, axis=axis)) > 0.03 * zr)
            lo = [slice(None)] * 2
            hi = [slice(None)] * 2
            lo[axis], hi[axis] = slice(0, -1), slice(1, None)
            edge[tuple(lo)] |= d          # both sides of every transition, so an
            edge[tuple(hi)] |= d          # outline is not lopsided
        img[edge & covered] *= 0.5

    out = img.reshape(size, ssaa, size, ssaa, 3).mean((1, 3))
    return np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)


def contact_sheet(images: list, columns: int = 2):
    np = _np()
    h, w, _ = images[0].shape
    rows = (len(images) + columns - 1) // columns
    sheet = np.full((rows * h, columns * w, 3), BACKGROUND, dtype=np.uint8)
    for k, im in enumerate(images):
        r, c = divmod(k, columns)
        sheet[r * h:(r + 1) * h, c * w:(c + 1) * w] = im
    return sheet


# ====================================================================
#  A whole render
# ====================================================================

@dataclass
class RenderResult:
    files: list[Path]
    size_mm: tuple[float, float, float]      # x, y, z extent of the STL
    triangles: int
    report: str


def render_stl(stl: Path, outdir: Path, views: list[str] | None = None,
               size: int = 480, name: str = "enclosure",
               envelope_mm: list[float] | None = None) -> RenderResult:
    _np()                                    # fail early, with the install hint
    stl, outdir = Path(stl), Path(outdir)
    if not stl.exists():
        raise RenderError(f"{stl} does not exist. Run the enclosure step first.")
    tris = read_stl(stl)
    if len(tris) == 0:
        raise RenderError(f"{stl.name} has no triangles.")
    views = views or DEFAULT_VIEWS
    outdir.mkdir(parents=True, exist_ok=True)
    ext = tris.reshape(-1, 3).max(0) - tris.reshape(-1, 3).min(0)
    files, images = [], []
    for v in views:
        im = render_view(tris, v, size)
        images.append(im)
        f = outdir / f"{name}-{v}.png"
        f.write_bytes(png_bytes(im))
        files.append(f)
    if len(images) > 1:
        f = outdir / f"{name}-sheet.png"
        f.write_bytes(png_bytes(contact_sheet(images)))
        files.insert(0, f)
    lines = [f"{stl.name}: {len(tris):,} triangles",
             f"Extent: {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm (X x Y x Z)"]
    if envelope_mm and len(envelope_mm) == 3:
        env = sorted(envelope_mm)
        mine = sorted(float(x) for x in ext)
        over = [f"{m - e:.1f} mm" for m, e in zip(mine, env) if m > e + 1e-6]
        lines.append("Fits the brief's envelope (any orientation): "
                     + ("yes" if not over else "NO, over by " + ", ".join(over)
                        + " on the sorted sides"))
    lines.append("Views: " + ", ".join(views) + f"  ({size} px, orthographic, flat shaded)")
    report = "\n".join(lines) + "\n"
    (outdir / f"{name}-render.txt").write_text(report, encoding="utf-8")
    return RenderResult(files, tuple(float(x) for x in ext), len(tris), report)


def box_stl(path: Path, x: float, y: float, z: float, binary: bool = True) -> Path:
    """A plain box, for tests and examples."""
    np = _np()
    v = np.array([[a, b, c] for a in (0, x) for b in (0, y) for c in (0, z)], dtype=float)
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    tris = v[np.array(faces)]
    return write_stl(path, tris, binary)


def write_stl(path: Path, tris, binary: bool = True) -> Path:
    np = _np()
    path = Path(path)
    if binary:
        rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        arr = np.zeros(len(tris), dtype=rec)
        arr["v"] = tris
        path.write_bytes(b"nemo".ljust(80, b"\0") + struct.pack("<I", len(tris)) + arr.tobytes())
    else:
        out = ["solid nemo"]
        for t in tris:
            out.append("facet normal 0 0 0\n outer loop")
            out += [f"  vertex {a} {b} {c}" for a, b, c in t]
            out.append(" endloop\nendfacet")
        out.append("endsolid nemo")
        path.write_text("\n".join(out), encoding="utf-8")
    return path
