"""The Print Shop: a model made ready for the owner's Kobra 3 (owner,
2026-10-22; a suggested department he chose).

  Slicer   slices a model (the Art Studio's or a Workshop enclosure) into
           G-code with OrcaSlicer's command line and Anycubic's own Kobra 3
           profiles, which ship inside OrcaSlicer
  Writer   writes a print card beside the G-code: printer, quality,
           filament, time, grams, metres, layers

Nothing here asks the model, and Nemo never sends a print: the owner copies
the G-code to the printer (its USB stick, or Anycubic's own app).

OrcaSlicer 2.4.2 (portable, C:/Nemo/tools/OrcaSlicer) ran on the AH531 with
no AVX: a 20 mm cube for the Kobra 3, 0.20 mm, PLA, came to 14m 49s and
3.58 g (2026-10-22). What its command line needs, found by trying it then:
  - a vendor profile cannot be passed as it is (it holds only what differs
    from its parent): flatten() writes the whole chain out, marked "User"
    and naming the system profile it came from in "inherits", which is
    what the command line matches the printer and quality on (else -17);
  - the model must already sit wholly on the bed: --arrange does not move
    one lying across the bed's edge (else -50), so centre() moves it.
The time and filament are OrcaSlicer's estimate, from its G-code's header.
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

# What NemoDoc.ps1 fetches into <prefix>\tools\OrcaSlicer (a test ties it):
# GitHub's own sha256 for the release file, checked on 2026-10-22.
SOURCE = ("OrcaSlicer_Windows_V2.4.2_x64_portable.zip", 171367668,
          "feba3009dfb9d268779cca5758a1a5bc3b7d0722bf8fa48d5c57340de975d6be")

VENDOR = "Anycubic"
PRINTER = "Anycubic Kobra 3 0.4 nozzle"
QUALITY = "0.20mm Standard @Anycubic Kobra 3 0.4 nozzle"
FILAMENT = "Anycubic PLA @Anycubic Kobra 3 0.4 nozzle"

# OrcaSlicer's own exit codes (src/libslic3r/Utils.hpp, v2.4.2), in words.
CODES = {
    -2: "a file was not found",
    -5: "a profile could not be read",
    -17: "the quality does not suit the printer",
    -50: "the model is not wholly on the bed",
    -51: "the settings do not pass OrcaSlicer's checks",
    -52: "the model is partly over the bed's edge",
}


class PrintShopError(Exception):
    pass


@dataclass
class Model:
    name: str
    stl: Path
    where: str                    # "Art Studio" or "Workshop"


@dataclass
class Job:
    ok: bool
    gcode: Path | None = None
    card: Path | None = None
    minutes: float | None = None
    grams: float | None = None
    metres: float | None = None
    layers: int | None = None
    time_text: str = ""
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0


def orca(cfg=None) -> Path | None:
    """OrcaSlicer: the configured file, Nemo's own copy, or the system's."""
    found = []
    if cfg is not None and cfg.get("paths.orca_slicer"):
        found.append(Path(str(cfg.get("paths.orca_slicer"))).expanduser())
    if cfg is not None and cfg.get("paths.llama_server"):
        engine = Path(str(cfg.get("paths.llama_server"))).expanduser()
        found.append(engine.parent.parent / "tools" / "OrcaSlicer" / "orca-slicer.exe")
    found.append(Path(r"C:\Nemo\tools\OrcaSlicer\orca-slicer.exe"))
    which = shutil.which("orca-slicer")
    if which:
        found.append(Path(which))
    return next((p for p in found if p.is_file()), None)


def _profiles(exe: Path) -> Path:
    return exe.parent / "resources" / "profiles"


def _index_cache() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "printshop-index.json"


def _stamp(root: Path) -> str:
    """What the profiles belong to: OrcaSlicer's folder and its program's
    size and date. The profiles ship in its folder and change with it."""
    exe = root.parent.parent
    progs = sorted(p for p in exe.glob("orca-slicer*") if p.is_file())
    return "|".join([str(root.resolve())] + [f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}"
                                             for p in progs])


def _index(root: Path) -> dict:
    """(type, name) -> its files, the vendor's own first. Read once per
    OrcaSlicer and kept in ~/.nemo (2026-11-08: reading its 12,260 profile
    files took 50 s cold, for a 1.2 s slice)."""
    stamp, cache = _stamp(root), _index_cache()
    try:
        kept = json.loads(cache.read_text(encoding="utf-8"))
        if kept.get("stamp") == stamp:
            index = {tuple(k.split("\t", 1)): [root / f for f in v] for k, v in kept["index"].items()}
            if all(fs[0].is_file() for fs in index.values()):
                return index
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    index = _read_index(root)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"stamp": stamp, "index": {
            f"{t}\t{n}": [str(f.relative_to(root)) for f in fs] for (t, n), fs in index.items()}}),
            encoding="utf-8")
    except (OSError, ValueError):
        pass                                     # slower next time, never wrong
    return index


def _read_index(root: Path) -> dict:
    index: dict = {}
    for f in root.rglob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and "name" in d and "type" in d:
            index.setdefault((d["type"], d["name"]), []).append(f)
    for files in index.values():
        files.sort(key=lambda p: VENDOR not in p.parts)
    return index


def _chain(index: dict, kind: str, name: str) -> dict:
    files = index.get((kind, name))
    if not files:
        raise PrintShopError(f"OrcaSlicer has no {kind} profile named \"{name}\"")
    d = json.loads(files[0].read_text(encoding="utf-8"))
    whole = _chain(index, kind, d["inherits"]) if d.get("inherits") else {}
    whole.update(d)
    return whole


def flatten(root: Path, kind: str, name: str, index: dict | None = None) -> dict:
    """One profile written out whole, as the command line will take it."""
    d = _chain(index if index is not None else _index(root), kind, name)
    for k in ("setting_id", "instantiation"):
        d.pop(k, None)
    try:
        d["version"] = json.loads((root / f"{VENDOR}.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        pass
    d.update({"from": "User", "inherits": name, "name": f"Nemo {name}"})
    return d


def choices(exe: Path) -> dict[str, list[str]]:
    """The qualities and filaments OrcaSlicer has for the printer."""
    out: dict[str, list[str]] = {"process": [], "filament": []}
    for kind in out:
        folder = _profiles(exe) / VENDOR / kind
        for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if d.get("instantiation") == "true" and PRINTER in (d.get("compatible_printers") or []):
                out[kind].append(d["name"])
    return out


# --------------------------------------------------------------------
#  The mesh: read, size, moved onto the bed (standard library only)
# --------------------------------------------------------------------

def read_stl(path: Path) -> list[tuple[float, ...]]:
    """Every corner of every triangle, as (x, y, z), three per triangle."""
    data = Path(path).read_bytes()
    if len(data) >= 84:
        count = struct.unpack("<I", data[80:84])[0]
        if count and len(data) == 84 + 50 * count:
            pts = []
            for i in range(count):
                v = struct.unpack_from("<9f", data, 84 + 50 * i + 12)
                pts += [v[0:3], v[3:6], v[6:9]]
            return pts
    nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data.decode("utf-8", "replace"))
    if not nums or len(nums) % 3:
        raise PrintShopError(f"{Path(path).name} is not a readable STL file")
    return [tuple(float(n) for n in v) for v in nums]


def size(pts) -> tuple[list[float], list[float]]:
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    return lo, hi


def bed(machine: dict) -> tuple[float, float, float, float, float]:
    """x0, y0, x1, y1, height of the printer's bed, from its profile."""
    xy = [tuple(float(n) for n in p.split("x")) for p in machine["printable_area"]]
    return (min(x for x, _ in xy), min(y for _, y in xy), max(x for x, _ in xy),
            max(y for _, y in xy), float(machine["printable_height"]))


def border(machine: dict) -> float | None:
    """The margin, if the profile's excluded area is only a border round the
    bed's edge, else None. Anycubic's Kobra 3 profile draws a 2 mm border as
    one polygon, out round the bed and back in, and OrcaSlicer's command line
    then found nothing but an upright box "fully inside the print volume": a
    pot, a cylinder or a stand would not slice (2026-11-04)."""
    ring = machine.get("bed_exclude_area") or []
    try:
        pts = [tuple(float(n) for n in p.split("x")) for p in ring]
    except ValueError:
        return None
    x0, y0, x1, y1, _ = bed(machine)
    if len(pts) != 10 or pts[0] != pts[4] or pts[5] != pts[9]:
        return None
    outer, inner = pts[:4], pts[5:9]
    if {(x0, y0), (x1, y0), (x1, y1), (x0, y1)} != set(outer):
        return None
    ix = sorted({x for x, _ in inner}); iy = sorted({y for _, y in inner})
    if len(ix) != 2 or len(iy) != 2:
        return None
    sides = {ix[0] - x0, x1 - ix[1], iy[0] - y0, y1 - iy[1]}
    if len(sides) != 1:
        return None                       # not the same all round: not a border
    margin = sides.pop()
    return margin if 0 < margin < min(x1 - x0, y1 - y0) / 4 else None


def without_border(machine: dict) -> tuple[dict, float]:
    """The machine profile as OrcaSlicer's command line is given it: a border
    taken out (Nemo keeps the model that far from every edge itself, in
    centre()), and the margin. Any other excluded area is left as it is."""
    m = border(machine)
    if m is None:
        return machine, 0.0
    return {**machine, "bed_exclude_area": []}, m


def centre(pts, out: Path, machine: dict, margin: float = 0.0) -> list[float]:
    """The mesh moved to the middle of the bed, resting on it, written as a
    binary STL. Returns its size; refuses one larger than the printer, or
    than the bed inside its border (margin) where the profile has one."""
    lo, hi = size(pts)
    dims = [hi[i] - lo[i] for i in range(3)]
    x0, y0, x1, y1, h = bed(machine)
    x0, y0, x1, y1 = x0 + margin, y0 + margin, x1 - margin, y1 - margin
    if dims[0] > x1 - x0 or dims[1] > y1 - y0 or dims[2] > h:
        raise PrintShopError(
            f"the model is {dims[0]:.0f} x {dims[1]:.0f} x {dims[2]:.0f} mm; the Kobra 3 "
            f"prints up to {x1 - x0:.0f} x {y1 - y0:.0f} x {h:.0f} mm")
    shift = [(x0 + x1) / 2 - (lo[0] + hi[0]) / 2, (y0 + y1) / 2 - (lo[1] + hi[1]) / 2, -lo[2]]
    body = bytearray(b"Nemo Print Shop".ljust(80, b" "))
    body += struct.pack("<I", len(pts) // 3)
    for i in range(0, len(pts), 3):
        body += struct.pack("<3f", 0.0, 0.0, 0.0)
        for p in pts[i:i + 3]:
            body += struct.pack("<3f", *(p[k] + shift[k] for k in range(3)))
        body += b"\0\0"
    Path(out).write_bytes(bytes(body))
    return dims


# --------------------------------------------------------------------
#  What to print, the slice, and the Writer's card
# --------------------------------------------------------------------

def models(cfg) -> list[Model]:
    """The Art Studio's models and the Workshop's enclosures, newest first."""
    found = []
    root = cfg.path("paths.models")
    for stl in root.glob("*/model.stl") if root.is_dir() else []:
        found.append(Model(stl.parent.name, stl, "Art Studio"))
    # A model the Designer split (nemo/joints.py): each piece and the pins print on their own.
    for stl in root.glob("*/pieces/*.stl") if root.is_dir() else []:
        found.append(Model(f"{stl.parent.parent.name}-{stl.stem}", stl, "Art Studio"))
    root = cfg.path("paths.projects")
    for stl in root.glob("*/enclosure/housing.stl") if root.is_dir() else []:
        found.append(Model(stl.parent.parent.name, stl, "Workshop"))
    return sorted(found, key=lambda m: m.stl.stat().st_mtime, reverse=True)


def _short(name: str) -> str:
    return name.split(" @")[0]


def read_gcode(gcode: Path) -> dict:
    """OrcaSlicer's own estimate, from the comments it writes."""
    text = Path(gcode).read_text(encoding="utf-8", errors="replace")
    got: dict = {}
    m = re.search(r"; estimated printing time \(normal mode\) = (.+)", text)
    if m:
        got["time_text"] = m[1].strip()
        parts = dict((u, float(n)) for n, u in re.findall(r"(\d+)([dhms])", m[1]))
        got["minutes"] = round(parts.get("d", 0) * 1440 + parts.get("h", 0) * 60
                               + parts.get("m", 0) + parts.get("s", 0) / 60, 1)
    m = re.search(r"; total filament used \[g\] = ([\d.]+)", text)
    if m:
        got["grams"] = float(m[1])
    m = re.search(r"; filament used \[mm\] = ([\d.]+)", text)
    if m:
        got["metres"] = round(float(m[1]) / 1000, 2)
    m = re.search(r"; total layer number: (\d+)", text)
    if m:
        got["layers"] = int(m[1])
    return got


def write_card(job: Job, model: Model, quality: str, filament: str, dims) -> Path:
    """The Writer: what the print will take, beside its G-code."""
    lines = [f"{model.name} ({model.where})",
             f"Printer   Anycubic Kobra 3, 0.4 mm nozzle",
             f"Quality   {_short(quality)}",
             f"Filament  {_short(filament)}",
             f"Size      {dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm",
             f"Time      {job.time_text or 'not given'}",
             f"Filament  {job.grams if job.grams is not None else '?'} g, "
             f"{job.metres if job.metres is not None else '?'} m",
             f"Layers    {job.layers if job.layers is not None else '?'}",
             "",
             "OrcaSlicer's estimate. Nemo never sends a print: copy "
             f"{job.gcode.name} to the printer's USB stick, or open it in Anycubic's app.",
             f"Sliced {time.strftime('%Y-%m-%d %H:%M')}."]
    card = job.gcode.with_name(job.gcode.stem + "-card.txt")
    card.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return card


def slice_model(cfg, model: Model, quality: str = QUALITY, filament: str = FILAMENT,
                timeout: int = 1800) -> Job:
    """The Slicer: the model into G-code for the Kobra 3, with the card."""
    from .checks.runners import _run
    exe = orca(cfg)
    if not exe:
        return Job(False, notes=["OrcaSlicer is not installed (C:\\Nemo\\tools\\OrcaSlicer)"])
    root = _profiles(exe)
    out = model.stl.parent / "print"
    work = out / ".work"
    work.mkdir(parents=True, exist_ok=True)
    index = _index(root)
    try:
        machine, margin = without_border(flatten(root, "machine", PRINTER, index))
        files = {}
        for kind, name, d in (("machine", PRINTER, machine),
                              ("process", quality, flatten(root, "process", quality, index)),
                              ("filament", filament, flatten(root, "filament", filament, index))):
            files[kind] = work / f"{kind}.json"
            files[kind].write_text(json.dumps(d, indent=1), encoding="utf-8")
        dims = centre(read_stl(model.stl), work / "model.stl", machine, margin)
    except (PrintShopError, KeyError, ValueError) as exc:
        return Job(False, notes=[str(exc)])
    for old in work.glob("*.gcode"):
        old.unlink()                                  # an old G-code proves nothing
    cmd = [str(exe), "--slice", "0", "--load-settings", f"{files['machine']};{files['process']}",
           "--load-filaments", str(files["filament"]), "--outputdir", str(work), str(work / "model.stl")]
    began = time.time()
    rc, so, se = _run(cmd, cwd=work, timeout=timeout)
    took = round(time.time() - began, 1)
    if rc > 2 ** 31:
        rc -= 2 ** 32                                 # Windows reports it unsigned
    made = sorted(work.glob("*.gcode"))
    from . import timekeeper
    timekeeper.record("printshop", "slice", took, rc == 0 and bool(made))
    if rc != 0 or not made:
        why = CODES.get(rc, f"OrcaSlicer stopped (code {rc})")
        tail = [l for l in (so + "\n" + se).splitlines() if l.strip() and "OpenGL" not in l]
        return Job(False, notes=[why] + tail[-3:], seconds=took)
    stem = f"{model.name}-{_short(quality).split()[0]}-{_short(filament).replace(' ', '-')}"
    gcode = out / f"{stem}.gcode"
    shutil.move(str(made[0]), gcode)
    job = Job(True, gcode, seconds=took, **read_gcode(gcode))
    job.card = write_card(job, model, quality, filament, dims)
    return job
