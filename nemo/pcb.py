"""The PCB Designer (owner, 2026-11-04): from a project's nets to a routed
circuit board, checked, and its Gerbers.

  place    code places each part's KiCad footprint on a grid (a first layout,
           not an optimised one) and gives each pad its net; nothing here is
           asked of the model.
  route    Freerouting (Specctra DSN in, SES out) lays the copper.
  check    KiCad's own rules check (kicad-cli pcb drc) judges the result.
  make     kicad-cli exports the Gerbers and drill files.

Physical data is never invented (docs/design-rules.md): a part's footprint and which
pad each pin is come from its library entry (footprint, pads), added part by
part from a source. A part without them is NAMED and the board is not made:
the owner chose this on 2026-11-04 rather than a board laid out from guessed
header positions. On 2026-11-04 none of Nemo's 26 parts had them yet.

KiCad's own Python runs the board work (its pcbnew module); Freerouting 2.5.0
needs Java 25 (class files 69): C:/Nemo/tools/jdk-25*.
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

FREEROUTING = ("freerouting-2.5.0.jar", 64599107,
               "f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7")
JRE25 = ("OpenJDK25U-jre_x64_windows_hotspot_25.0.5_8.zip", 58589419,
         "da78d54a2fcdbba1e92d5e3f07dd30236f96297891c4a21a781c3f38f5c0beae")
GRID_MM = 6.0          # space between parts as first placed
ROW_MM = 100.0         # a row of parts is at most this wide before the next begins
MARGIN_MM = 4.0        # board edge beyond the parts


class PcbError(RuntimeError):
    pass


@dataclass
class Tools:
    kicad_cli: Path
    python: Path               # KiCad's own, with pcbnew
    footprints: Path           # KiCad's footprint libraries
    java: Path | None
    freerouting: Path | None


def tools() -> Tools:
    from .platform_probe import find_tool
    cli = find_tool("kicad-cli")
    if not cli:
        raise PcbError("KiCad is not installed (kicad-cli not found)")
    cli = Path(cli)
    py = cli.parent / ("python.exe" if sys.platform.startswith("win") else "python3")
    if not py.is_file():
        py = Path(sys.executable)          # Linux: the system's python3 carries pcbnew
    share = [cli.parent.parent / "share" / "kicad" / "footprints", Path("/usr/share/kicad/footprints")]
    fps = next((s for s in share if s.is_dir()), share[0])
    javas = sorted(glob.glob(r"C:\Nemo\tools\jdk-25*\bin\java.exe")) + sorted(glob.glob("/opt/nemo/tools/jdk-25*/bin/java"))
    jars = [Path(r"C:\Nemo\tools\freerouting") / FREEROUTING[0], Path("/opt/nemo/tools/freerouting") / FREEROUTING[0]]
    return Tools(cli, py, fps, Path(javas[-1]) if javas else None, next((j for j in jars if j.is_file()), None))


def footprint_file(fp: str, root: Path) -> Path | None:
    """'Library:Name' -> its .kicad_mod in KiCad's libraries, or None."""
    lib, _, name = fp.partition(":")
    if not lib or not name:
        return None
    f = Path(root) / f"{lib}.pretty" / f"{name}.kicad_mod"
    return f if f.is_file() else None


def missing(parts: list, nets: dict[str, list[tuple[str, str]]], root: Path) -> list[str]:
    """Why a board cannot be made yet, part by part; [] when it can."""
    used: dict[str, set[str]] = {}
    for pins in nets.values():
        for ref, pin in pins:
            used.setdefault(ref, set()).add(pin)
    out = []
    for p in parts:
        if p.ref not in used:
            continue
        if not p.footprint:
            out.append(f"{p.ref}: no footprint in its library entry")
            continue
        if footprint_file(p.footprint, root) is None:
            out.append(f"{p.ref}: footprint {p.footprint} is not in KiCad's libraries")
        unpadded = sorted(n for n in used[p.ref] if n not in p.pads)
        if unpadded:
            out.append(f"{p.ref}: no pad given for {', '.join(unpadded)}")
    return out


@dataclass
class Board:
    pcb: Path
    routed: bool
    unrouted: int
    drc_errors: list[str] = field(default_factory=list)
    gerbers: list[Path] = field(default_factory=list)
    outside: list[str] = field(default_factory=list)     # parts off the board (Nemo's own look)
    tracks: int = 0
    size_mm: tuple[float, float] = (0.0, 0.0)

    @property
    def ok(self) -> bool:
        return self.routed and not self.drc_errors and not self.outside and self.tracks > 0


PLACE = r'''
import json, sys, pcbnew
spec = json.load(open(sys.argv[1], encoding="utf-8"))
board = pcbnew.BOARD()
nets = {}
for name in spec["nets"]:
    n = pcbnew.NETINFO_ITEM(board, name); board.Add(n); nets[name] = n
mm = pcbnew.FromMM
# Side by side, by each footprint's own outline (its courtyard and pads as
# loaded): a footprint's origin is not its corner (the Pico's is its pin 1),
# and placing by catalogue sizes put two parts on the Pico (2026-11-04).
gap, row_w = mm(spec["gap"]), mm(spec["row_width"])
x = y = row_h = 0
for part in spec["parts"]:
    lib, name = part["footprint"].split(":", 1)
    fp = pcbnew.FootprintLoad(spec["libraries"] + "/" + lib + ".pretty", name)
    if fp is None:
        raise SystemExit("no footprint " + part["footprint"])
    fp.SetReference(part["ref"]); fp.SetValue(part["value"])
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    b = fp.GetBoundingBox(False)
    if x and x + b.GetWidth() > row_w:          # next row
        x, y, row_h = 0, y + row_h + gap, 0
    fp.SetPosition(pcbnew.VECTOR2I(x - b.GetLeft(), y - b.GetTop()))
    x += b.GetWidth() + gap
    row_h = max(row_h, b.GetHeight())
    board.Add(fp)
    for pad in fp.Pads():
        net = part["pads"].get(pad.GetNumber())
        if net:
            pad.SetNet(nets[net])
# The outline goes round the parts. (ComputeBoundingBox(True) measures board
# edges only, and there are none yet: the first board's outline was 8 mm
# square round nothing, its parts outside it, 2026-11-04.)
boxes = [fp.GetBoundingBox(False) for fp in board.GetFootprints()]
m = mm(spec["margin"])
x0 = min(b.GetLeft() for b in boxes) - m
y0 = min(b.GetTop() for b in boxes) - m
x1 = max(b.GetRight() for b in boxes) + m
y1 = max(b.GetBottom() for b in boxes) + m
for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts)
    s.SetStart(pcbnew.VECTOR2I(*a)); s.SetEnd(pcbnew.VECTOR2I(*b)); s.SetWidth(mm(0.1)); board.Add(s)
board.SetFileName(spec["pcb"])
pcbnew.SaveBoard(spec["pcb"], board)
if not pcbnew.ExportSpecctraDSN(board, spec["dsn"]):
    raise SystemExit("the DSN export failed")
'''

IMPORT = r'''
import json, sys, pcbnew
board = pcbnew.LoadBoard(sys.argv[1])
if not pcbnew.ImportSpecctraSES(board, sys.argv[2]):
    raise SystemExit("the SES import failed")
pcbnew.SaveBoard(sys.argv[1], board)
# Nemo's own look, as KiCad's error check does not count a part off the board:
# every footprint inside the Edge.Cuts outline.
edge = board.GetBoardEdgesBoundingBox()
out = [fp.GetReference() for fp in board.GetFootprints()
       if not edge.Contains(fp.GetBoundingBox(False))]
tracks = sum(1 for t in board.GetTracks())
json.dump({"outside": out, "tracks": tracks,
           "edge_mm": [pcbnew.ToMM(edge.GetWidth()), pcbnew.ToMM(edge.GetHeight())]},
          open(sys.argv[3], "w", encoding="utf-8"))
'''


def _run(cmd, timeout=600):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if p.returncode != 0:
        raise PcbError(f"{Path(str(cmd[0])).name} failed ({p.returncode}): "
                       f"{(p.stderr or p.stdout).strip()[-400:]}")
    return p


def layout(parts: list, nets: dict[str, list[tuple[str, str]]], out: Path, t: Tools) -> dict:
    """What the placement script needs: each part's footprint and its pads'
    nets. Where they go is decided there, from the footprints' real outlines."""
    on_board = [p for p in parts if any(ref == p.ref for pins in nets.values() for ref, _ in pins)]
    spec_parts = []
    for p in on_board:
        pad_nets = {}
        for net, pins in nets.items():
            for ref, pin in pins:
                if ref == p.ref and pin in p.pads:
                    pad_nets[p.pads[pin]] = net
        spec_parts.append({"ref": p.ref.upper(), "value": p.name[:40], "footprint": p.footprint,
                           "pads": pad_nets})
    return {"nets": sorted(nets), "parts": spec_parts, "libraries": str(t.footprints).replace("\\", "/"),
            "margin": MARGIN_MM, "gap": GRID_MM, "row_width": ROW_MM,
            "pcb": str(out / "board.kicad_pcb"), "dsn": str(out / "board.dsn")}


def make(parts: list, nets: dict[str, list[tuple[str, str]]], out: Path, t: Tools | None = None,
         passes: int = 20) -> Board:
    """Place, route, check and export. Raises PcbError saying why it cannot."""
    t = t or tools()
    why = missing(parts, nets, t.footprints)
    if why:
        raise PcbError("the board cannot be made yet: " + "; ".join(why))
    if t.java is None or t.freerouting is None:
        raise PcbError("Freerouting and Java 25 are not installed (C:\\Nemo\\tools)")
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    spec = layout(parts, nets, out, t)
    (out / "spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    (out / "place.py").write_text(PLACE, encoding="utf-8")
    (out / "import_ses.py").write_text(IMPORT, encoding="utf-8")
    _run([t.python, out / "place.py", out / "spec.json"])
    ses = out / "board.ses"
    ses.unlink(missing_ok=True)
    _run([t.java, "-jar", t.freerouting, "-de", out / "board.dsn", "-do", ses, "-mp", passes,
          "--gui.enabled=false"], timeout=1800)
    if not ses.is_file():
        raise PcbError("Freerouting ended without a routed session (board.ses)")
    _run([t.python, out / "import_ses.py", out / "board.kicad_pcb", ses, out / "look.json"])
    look = json.loads((out / "look.json").read_text(encoding="utf-8"))
    drc = out / "drc.json"
    subprocess.run([str(t.kicad_cli), "pcb", "drc", "--format", "json", "--severity-error",
                    "--output", str(drc), str(out / "board.kicad_pcb")],
                   capture_output=True, text=True, timeout=600)
    errors, unrouted = [], 0
    try:
        report = json.loads(drc.read_text(encoding="utf-8"))
        errors = [f"{v.get('type')}: {v.get('description')}" for v in report.get("violations", [])]
        unrouted = len(report.get("unconnected_items", []))
    except (OSError, ValueError):
        errors = ["KiCad's rules check wrote no report"]
    gerbers = out / "gerbers"
    gerbers.mkdir(exist_ok=True)
    subprocess.run([str(t.kicad_cli), "pcb", "export", "gerbers", "--output", str(gerbers) + "/",
                    str(out / "board.kicad_pcb")], capture_output=True, text=True, timeout=600)
    subprocess.run([str(t.kicad_cli), "pcb", "export", "drill", "--output", str(gerbers) + "/",
                    str(out / "board.kicad_pcb")], capture_output=True, text=True, timeout=600)
    return Board(out / "board.kicad_pcb", unrouted == 0, unrouted, errors, sorted(gerbers.iterdir()),
                 look["outside"], look["tracks"], tuple(look["edge_mm"]))
