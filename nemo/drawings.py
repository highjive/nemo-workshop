"""Workshop drawings, drawn by CADCraft (owner, 2026-11-11: "yes download
cadcraft-cli and do stage 1"; docs/artcraft-plan.md).

Nemo's blueprints are pictures. This draws the enclosure as a real 2D
drawing: the tray seen from above with each part's place, and every wall
that has a cut seen from outside, with dimensions. Saved as DXF (what a
laser cutter, a CNC or any CAD program opens), PDF at 1:1 on A4 or A3 (so
a printout can be measured with a ruler, or used as a drilling template)
and PNG (for the window).

Code writes every line and number, from the same layout and the same cuts
the CadQuery script makes (enclosure.wall_cuts); no model is asked. Then a
gate reads the saved DXF back through CADCraft itself: every outline, every
dimension's measurement and every label must be what Nemo meant, to a
hundredth of a millimetre. A drawing that disagrees is said, not shipped
as right.

CADCraft (github.com/storytold/cadcraft, MIT OR Apache-2.0) is an optional
tool: where cadcraft-cli is not installed the step says so and the rest of
the design goes on.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .enclosure import Box, Placed, WallCut, corner_radius, wall_cuts
from .parts import Part

VERSION = "0.19.0"
# Pinned like every tool: GitHub's own sha256 for each asset (2026-11-11),
# which the release's SHA256SUMS.txt repeats. NemoDoc.ps1 carries the same.
SOURCES = {
    "windows": ("cadcraft-0.19.0-windows-x64-portable.zip", 74495039,
                "38fa68aafef23e0ebbef78721180634e8a24ce6f7c590bbaabf003e7e9d88731"),
    "linux": ("cadcraft-0.19.0-linux-x86_64.tar.gz", 75368179,
              "a654df8c3e447c62c490c0a8aad8c42a9fafab010ca4d25bc3504ed45b3c8f51"),
}
URL = "https://github.com/storytold/cadcraft/releases/download/v{v}/{name}"
HOME_WIN = Path(r"C:\Nemo\tools\cadcraft")
HOME_LINUX = Path("/opt/nemo/cadcraft")

NOT_INSTALLED = ("No dimensioned drawing: CADCraft (cadcraft-cli) is not installed here. "
                 "NemoDoc installs it (-SkipDrawings leaves it out).")
TOLERANCE = 0.01        # mm: what the gate allows between what was meant and what was read back
TEXT_H = 2.5            # mm, the ISO-25 dimension style's own text height
BATCH = 40              # commands per cadcraft-cli run (the Windows command line has a limit)
PAPERS = (("A4", 297.0, 210.0), ("A3", 420.0, 297.0))
PAPER_MARGIN = 12.0     # mm left clear round the drawing on the page

WALL_NAMES = {"front": "FRONT WALL (y = 0)", "back": "BACK WALL (y = width)",
              "left": "LEFT WALL (x = 0)", "right": "RIGHT WALL (x = length)"}


class DrawingError(RuntimeError):
    """The drawing could not be made. For the owner."""


def cli() -> Path | None:
    """cadcraft-cli, where NemoDoc (Windows) or build-iso (NemoIso) puts it, or on the PATH."""
    from .platform_probe import find_tool
    if os.environ.get("NEMO_CADCRAFT", "").lower() == "off":     # the test sandbox
        return None
    for p in (HOME_WIN / "cadcraft-cli.exe", HOME_LINUX / "cadcraft-cli"):
        if p.is_file():
            return p
    hit = find_tool("cadcraft-cli")
    return Path(hit) if hit else None


# ------------------------------------------------------------ the drawing
@dataclass
class Sheet:
    """The commands for one drawing, and what each one should read back as."""
    commands: list[tuple[str, dict]] = field(default_factory=list)
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)
    dims: list[tuple[float, tuple[float, float], tuple[float, float]]] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    scale: int = 1          # printed at 1:scale; text and dimensions are scaled to print the same size

    def rect(self, x0, y0, x1, y1, fillet: float = 0.0):
        x0, y0, x1, y1 = (round(v, 3) for v in (x0, y0, x1, y1))
        args = {"p1": [x0, y0], "p2": [x1, y1]}
        if fillet > 0:
            args["fillet"] = round(fillet, 3)
        self.commands.append(("rectang", args))
        self.rects.append((x0, y0, x1, y1))

    def dim(self, p1, p2, at, vertical: bool = False):
        p1 = (round(p1[0], 3), round(p1[1], 3))
        p2 = (round(p2[0], 3), round(p2[1], 3))
        args = {"p1": list(p1), "p2": list(p2), "at": [round(at[0], 3), round(at[1], 3)],
                "rotation": 90 if vertical else 0}
        self.commands.append(("dimlinear", args))
        meant = abs(p2[1] - p1[1]) if vertical else abs(p2[0] - p1[0])
        self.dims.append((round(meant, 3), p1, p2))

    def text(self, at, words: str, height: float = TEXT_H, justify: str = "BL"):
        self.commands.append(("text", {"at": [round(at[0], 3), round(at[1], 3)], "text": words,
                                       "height": height, "justify": justify}))
        self.texts.append(words)


def _along(cut: WallCut, box: Box) -> tuple[float, float]:
    """(where the cut's centre is along the wall as seen from OUTSIDE, the wall's length)."""
    if cut.wall == "front":
        return cut.centre, box.length
    if cut.wall == "back":
        return box.length - cut.centre, box.length
    if cut.wall == "left":
        return box.width - cut.centre, box.width
    return cut.centre, box.width                       # right


def enclosure_sheet(placed: list[Placed], parts: list[Part], box: Box,
                    corners: str = "square", notch_wall: str = "left",
                    title: str = "") -> Sheet:
    """The tray from above, then each wall with a cut, from outside. Origin:
    the outer corner at x = 0, y = 0, as in the CadQuery script."""
    s = Sheet()
    L, W, H, t = box.length, box.width, box.height, box.wall
    r = corner_radius(box) if corners == "rounded" else 0.0
    # Plan
    s.text((0, W + 22), f"{title or 'ENCLOSURE'}: FROM ABOVE".upper(), 3.5)
    s.text((0, W + 16), "Millimetres. Full size (1:1) on the PDF.", 2.5)
    s.rect(0, 0, L, W, r)
    s.rect(t, t, L - t, W - t, max(r - t, 0.0))
    for a in placed:
        s.rect(t + a.x, t + a.y, t + a.x + a.dx, t + a.y + a.dy)
        # The stroke font is about 0.9 of its height wide a letter: a name
        # longer than its part is drawn smaller, never over the outline.
        h = round(min(TEXT_H, a.dy * 0.4, (a.dx - 1) / (0.9 * len(a.ref))), 2)
        s.text((t + a.x + a.dx / 2, t + a.y + a.dy / 2), a.ref, h, "MC")
    s.dim((0, 0), (L, 0), (L / 2, -10))
    s.dim((0, 0), (0, W), (-10, W / 2), vertical=True)
    s.dim((0, W), (t, W), (t / 2, W + 8))
    # Where each part sits, as a list beside the plan
    x0 = L + 20
    s.text((x0, W), "PARTS (from the inside corner)", 3.0)
    for i, a in enumerate(placed):
        s.text((x0, W - 6 * (i + 1)),
               f"{a.ref}: x {a.x:g}, y {a.y:g}; {a.dx:g} x {a.dy:g} mm")
    # Walls
    cuts = wall_cuts(placed, parts, box, notch_wall)
    walls = [w for w in ("front", "back", "left", "right") if any(c.wall == w for c in cuts)]
    most = max((sum(1 for c in cuts if c.wall == w) for w in walls), default=0)
    # Below the plan's length dimension (10 mm under it), with room above
    # each wall for its title and one position dimension per cut.
    ox, oy = 0.0, -(H + 40 + 7 * most)
    for w in walls:
        mine = sorted((c for c in cuts if c.wall == w), key=lambda c: _along(c, box)[0])
        length = _along(mine[0], box)[1]
        s.text((ox, oy + H + 18 + 7 * most), f"{WALL_NAMES[w]}, FROM OUTSIDE", 3.0)
        s.rect(ox, oy, ox + length, oy + H)
        s.dim((ox, oy), (ox + length, oy), (ox + length / 2, oy - 10))
        s.dim((ox, oy), (ox, oy + H), (ox - 10, oy + H / 2), vertical=True)
        for i, c in enumerate(mine):
            u = _along(c, box)[0]
            left, right = ox + u - c.width / 2, ox + u + c.width / 2
            s.rect(left, oy + H - c.depth, right, oy + H)
            # Each cut's name under it, one line lower than the last, so
            # narrow cuts side by side (the vents) do not write over each other.
            s.text((left, oy + H - c.depth - 4 - 3.5 * i), c.name, 2.0)
            s.dim((left, oy + H), (right, oy + H), (u + ox, oy + H + 5))
            s.dim((right, oy + H - c.depth), (right, oy + H), (right + 4, oy + H - c.depth / 2),
                  vertical=True)
            s.dim((ox, oy + H), (left, oy + H), ((ox + left) / 2, oy + H + 11 + 7 * i))
        ox += length + 40
    return s


def paper_for(extents: list[list[float]], scale: int = 1) -> tuple[str, float, float]:
    """The smallest page (landscape) a drawing of these extents (CADCraft's
    own, [[x0, y0], [x1, y1]]) fits at 1:scale, with its size."""
    xs = (extents[1][0] - extents[0][0]) / scale
    ys = (extents[1][1] - extents[0][1]) / scale
    for name, w, h in PAPERS:
        if xs + 2 * PAPER_MARGIN <= w and ys + 2 * PAPER_MARGIN <= h:
            return name, w, h
    at = "full size" if scale == 1 else f"1:{scale}"
    raise DrawingError(f"the drawing is {xs:.0f} x {ys:.0f} mm at {at}, larger than A3")


# Scales a room is drawn at, the first that fits A4 (else A3) being used.
ROOM_SCALES = (10, 20, 25, 50, 100)


def floor_sheet(room_mm: tuple[float, float], row_widths: list[float],
                board_mm: tuple[int, int], title: str) -> Sheet:
    """A floor seen from above: the room wall to wall, each row of boards
    along its length, the width of the first, a whole and the last row.
    The rows are the Woodworker's (woodworker.rows). The expansion gap is
    not drawn: it is the maker's figure, read on the packet."""
    L, W = room_mm
    scale = next((k for k in ROOM_SCALES
                  if L / k + 50 + 2 * PAPER_MARGIN <= PAPERS[0][1]
                  and W / k + 45 + 2 * PAPER_MARGIN <= PAPERS[0][2]), None) \
        or next((k for k in ROOM_SCALES
                 if L / k + 50 + 2 * PAPER_MARGIN <= PAPERS[1][1]
                 and W / k + 45 + 2 * PAPER_MARGIN <= PAPERS[1][2]), ROOM_SCALES[-1])
    s = Sheet(scale=scale)
    # Dimension text, arrows and offsets drawn to print as at 1:1.
    s.commands.append(("setvar", {"name": "DIMSCALE", "value": scale}))
    t = TEXT_H * scale
    s.text((0, W + 7 * t), title.upper(), 1.4 * t)
    s.text((0, W + 5 * t), f"Millimetres. Scale 1:{scale}. Boards {board_mm[0]} x {board_mm[1]} mm; "
                           f"{len(row_widths)} rows, wall to wall.", t)
    s.text((0, W + 3 * t), "The expansion gap at each wall is not drawn: leave the gap "
                           "the packet gives.", t)
    s.rect(0, 0, L, W)
    y = 0.0
    for rw in row_widths:
        s.rect(0, y, L, y + rw)
        y += rw
    s.dim((0, 0), (L, 0), (L / 2, -4 * t))
    s.dim((0, 0), (0, W), (-4 * t, W / 2), vertical=True)
    tops = [sum(row_widths[:i + 1]) for i in range(len(row_widths))]
    s.dim((L, 0), (L, tops[0]), (L + 3 * t, tops[0] / 2), vertical=True)
    if len(row_widths) > 2:
        s.dim((L, tops[0]), (L, tops[1]), (L + 6 * t, (tops[0] + tops[1]) / 2), vertical=True)
    if len(row_widths) > 1:
        s.dim((L, tops[-2]), (L, W), (L + 3 * t, (tops[-2] + W) / 2), vertical=True)
    return s


def floor_drawing(plan, out_dir: Path, name: str = "floor"):
    """The Woodworker's floor drawn (a plan with a room and a board size):
    the Made drawing, or None where CADCraft is not installed or the plan
    has no rows to draw."""
    from .woodworker import rows
    if plan.room_mm is None or plan.board_mm is None:
        return None
    exe = cli()
    if exe is None:
        return None
    sheet = floor_sheet(plan.room_mm, rows(plan.room_mm[1], plan.board_mm[1]),
                        plan.board_mm, plan.job)
    return draw(sheet, out_dir, name, exe)


# ------------------------------------------------------------ running it
def _run(exe: Path, args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run([str(exe), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout,
                           env=dict(os.environ, CADCRAFT_CONFIG_DIR=""))
    except subprocess.TimeoutExpired as exc:
        raise DrawingError(f"cadcraft-cli did not finish in {timeout:g} s") from exc
    except OSError as exc:
        raise DrawingError(f"cadcraft-cli could not be started: {exc}") from exc
    if p.returncode != 0:
        raise DrawingError("cadcraft-cli stopped: " + ((p.stderr or p.stdout).strip()[-400:] or
                                                       f"exit {p.returncode}"))
    return p


def _cmd(c: tuple[str, dict]) -> str:
    return f"{c[0]} {json.dumps(c[1], separators=(',', ':'))}"


@dataclass
class Made:
    files: list[Path]
    paper: str
    faults: list[str]

    @property
    def ok(self) -> bool:
        return not self.faults


def draw(sheet: Sheet, out_dir: Path, name: str, exe: Path | None = None) -> Made:
    """Draw the sheet into out_dir/<name>.dxf, .pdf (1:1) and .png, then check it."""
    exe = exe or cli()
    if exe is None:
        raise DrawingError("CADCraft (cadcraft-cli) is not installed. NemoDoc installs it.")
    out_dir.mkdir(parents=True, exist_ok=True)
    dxf = out_dir / f"{name}.dxf"
    batches = [sheet.commands[i:i + BATCH] for i in range(0, len(sheet.commands), BATCH)]
    for n, batch in enumerate(batches):
        args = ["run", "--metric"] if n == 0 else ["run", str(dxf), "--in-place"]
        for c in batch:
            args += ["--cmd", _cmd(c)]
        _run(exe, args + ["--save", str(dxf)])
    info = json.loads(_run(exe, ["info", str(dxf)]).stdout)
    paper, _, _ = paper_for(info["extents"], sheet.scale)
    pdf, png = out_dir / f"{name}.pdf", out_dir / f"{name}.png"
    _run(exe, ["run", str(dxf), "--cmd", _cmd(("exportpdf", {
        "path": str(pdf), "paper": paper, "landscape": True,
        "scale": 1 if sheet.scale == 1 else f"1:{sheet.scale}", "fit": False}))])
    _run(exe, ["convert", str(dxf), str(png)])
    read = json.loads(_run(exe, ["run", str(dxf), "--cmd", 'entities {"limit":100000}']).stdout
                      .strip().splitlines()[-1])
    faults = check(sheet, read.get("entities", []))
    return Made([dxf, pdf, png], paper, faults)


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def check(sheet: Sheet, entities: list[dict]) -> list[str]:
    """What CADCraft read back from the saved DXF against what Nemo meant."""
    faults: list[str] = []
    got_rects, got_dims, got_texts = [], [], []
    for e in entities:
        g = e.get("geometry", {})
        if e.get("type") == "Polyline":
            xs = [v["p"]["x"] for v in g.get("vertices", [])]
            ys = [v["p"]["y"] for v in g.get("vertices", [])]
            if xs:
                got_rects.append((min(xs), min(ys), max(xs), max(ys)))
        elif e.get("type") == "Dimension":
            got_dims.append((g.get("measurement", -1.0),
                             (g.get("p13", {}).get("x"), g.get("p13", {}).get("y")),
                             (g.get("p14", {}).get("x"), g.get("p14", {}).get("y"))))
        elif e.get("type") == "Text":
            got_texts.append(g.get("value", ""))

    def take(pool, match):
        for i, x in enumerate(pool):
            if match(x):
                return pool.pop(i)
        return None

    for r in sheet.rects:
        if take(got_rects, lambda g: all(_near(a, b) for a, b in zip(g, r))) is None:
            faults.append(f"an outline from ({r[0]:g}, {r[1]:g}) to ({r[2]:g}, {r[3]:g}) "
                          "is not in the saved drawing")
    for meant, p1, p2 in sheet.dims:
        if take(got_dims, lambda g: _near(g[0], meant) and None not in g[1] + g[2]
                and _near(g[1][0], p1[0]) and _near(g[1][1], p1[1])
                and _near(g[2][0], p2[0]) and _near(g[2][1], p2[1])) is None:
            faults.append(f"the {meant:g} mm dimension from {p1} to {p2} does not read back as "
                          f"{meant:g} mm")
    for t in sheet.texts:
        if take(got_texts, lambda g: g == t) is None:
            faults.append(f"the label {t!r} is not in the saved drawing")
    extra = len(got_rects) + len(got_dims) + len(got_texts)
    if extra:
        faults.append(f"{extra} thing(s) in the saved drawing that Nemo did not draw")
    return faults


def enclosure_drawing(root: Path, placed: list[Placed], parts: list[Part], box: Box,
                      corners: str, notch_wall: str, title: str):
    """The enclosure step's drawing, as one of its checks (a checks Result):
    FAIL where the drawing could not be made or does not read back as
    drawn, PASS with the files otherwise. None where CADCraft is not
    installed: an optional tool missing is a note (NOT_INSTALLED), not a
    check that could not run, which every guide would list as an open
    question (D153, D206)."""
    from .checks import FAIL, PASS, Result
    exe = cli()
    if exe is None:
        return None
    try:
        made = draw(enclosure_sheet(placed, parts, box, corners, notch_wall, title),
                    root / "drawings", "housing", exe)
    except DrawingError as exc:
        return Result("drawing", FAIL, str(exc))
    if not made.ok:
        return Result("drawing", FAIL, "the drawing CADCraft saved is not the one Nemo drew",
                      made.faults[:10])
    return Result("drawing", PASS,
                  f"drawings/housing.dxf (for a cutter or any CAD program), housing.pdf "
                  f"(full size on {made.paper}) and housing.png; every line and dimension "
                  "read back as drawn")
