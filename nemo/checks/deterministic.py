"""Tier 0: checks that know when they are wrong.

No model involved, no API key, no network. These run in milliseconds even on
two Sandy Bridge cores, which is exactly why they run first and often.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..parts import Part

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""
    items: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status != FAIL

    def render(self) -> str:
        head = f"{self.status:<4}  {self.name}"
        if self.detail:
            head += f"  -- {self.detail}"
        return "\n".join([head] + [f"        {i}" for i in self.items])


# --------------------------------------------------------------------
# Power
# --------------------------------------------------------------------

def current_sum(parts: list[Part], supply_ma: float,
                headroom: float = 0.25,
                extra: list[tuple[str, float]] | None = None) -> Result:
    """Total peak draw against the supply, with headroom.

    Uses peak, not typical. A design that only works when nothing is
    transmitting is not a design. `extra` is (name, peak mA) for things
    the brief gives a figure for and the library has no part for (D162).
    """
    if supply_ma <= 0:
        return Result("current_sum", SKIP, "no supply rating given")

    # Batteries and chargers supply current; they do not draw it. D8 fixed
    # this in the safety review only, and this check went on counting a
    # 500 mAh cell and its charger as 2 A of load, failing every battery
    # design at the parts step.
    power = [p for p in parts if p.category == "power"]
    parts = [p for p in parts if p.category != "power"]
    total = sum(p.draw_ma for p in parts)
    budget = supply_ma * (1 - headroom)
    items = [f"{p.ref}: {p.draw_ma:.0f} mA" for p in parts if p.draw_ma]
    for name, ma in extra or []:
        total += ma
        items.append(f"{name}: {ma:.0f} mA (the brief's own figure, not the library's)")

    # D151: a cell feeding the design through a step-up converter gives
    # more current than the loads draw, by the step in voltage and the
    # converter's loss. The first battery design put through the pipeline
    # passed as "741 mA of 1000 mA"; those 741 mA are at 5 V, which is
    # about 1077 mA from a 3.7 V cell rated for 1000. The suggested-fix
    # planner already did this sum (O21); this check did not.
    conv = next((p for p in power if p.output_v and p.supply_v), None)
    cell = next((p for p in power if not p.output_v and conv is not None
                 and any(abs(v - conv.supply_v[0]) < 0.35 for v in p.supply_v)), None)
    if conv is not None and cell is not None and total:
        out_v, in_v, eff = max(conv.output_v), conv.supply_v[0], conv.efficiency or 1.0
        at_loads = total
        total = at_loads * out_v / (in_v * eff)
        items.append(f"through {conv.ref}: {at_loads:.0f} mA at {out_v:g} V is "
                     f"{total:.0f} mA from the {in_v:g} V supply ({eff:.0%} efficient; "
                     "more as the cell runs down)")
    items.append(f"total {total:.0f} mA against {supply_ma:.0f} mA "
                 f"({headroom:.0%} headroom -> {budget:.0f} mA usable)")

    if total > supply_ma:
        return Result("current_sum", FAIL,
                      f"peak draw {total:.0f} mA exceeds supply "
                      f"{supply_ma:.0f} mA", items)
    if total > budget:
        return Result("current_sum", FAIL,
                      f"peak draw {total:.0f} mA leaves under {headroom:.0%} "
                      "headroom", items)
    return Result("current_sum", PASS,
                  f"{total:.0f} mA of {supply_ma:.0f} mA", items)


def voltage_compatibility(links: list[tuple[Part, str, Part, str]]) -> Result:
    """Flag logic-level mismatches across every declared connection.

    links: (part_a, pin_a, part_b, pin_b)
    """
    if not links:
        # D143: this returned PASS, "0 links checked", on every real run of
        # the tag player, including the one with a 3.3 V part on a 5 V pin.
        # Nothing examined is not a pass.
        return Result("voltage_compat", SKIP,
                      "no two parts share a bus pin, so no logic levels were compared")
    problems = []
    for a, pa, b, pb in links:
        pin_a, pin_b = a.pin(pa), b.pin(pb)
        va = (pin_a.voltage if pin_a and pin_a.voltage else a.logic_v)
        vb = (pin_b.voltage if pin_b and pin_b.voltage else b.logic_v)
        if va is None or vb is None:
            continue
        if abs(va - vb) > 0.35:
            direction = f"{a.ref}.{pa} ({va} V) -> {b.ref}.{pb} ({vb} V)"
            if va > vb:
                problems.append(
                    f"{direction}: driving a {vb} V input from {va} V. "
                    "Needs level shifting or a series resistor.")
            else:
                problems.append(
                    f"{direction}: {va} V may not reach the {vb} V logic "
                    "threshold reliably.")
    if problems:
        return Result("voltage_compat", FAIL,
                      f"{len(problems)} level mismatch(es)", problems)
    return Result("voltage_compat", PASS, f"{len(links)} links checked")


def supply_rails(parts: list[Part], rails: list[float]) -> Result:
    """Every part must have a rail it can actually run from."""
    missing = []
    for p in parts:
        # A battery or charger is a source, not something a rail must feed.
        if not p.supply_v or p.category == "power":
            continue
        if not any(any(abs(v - r) < 0.2 for r in rails) for v in p.supply_v):
            missing.append(
                f"{p.ref} wants {p.supply_v} V; rails present: {rails}")
    if missing:
        return Result("supply_rails", FAIL, "unsupplied parts", missing)
    return Result("supply_rails", PASS, f"rails {rails} cover all parts")


# --------------------------------------------------------------------
# Wire and trace sizing -- IPC-2221
# --------------------------------------------------------------------

# k, b, c from IPC-2221A for external and internal conductors.
_IPC = {"external": (0.048, 0.44, 0.725), "internal": (0.024, 0.44, 0.725)}

# Power-transmission ampacity for stranded copper, not the chassis-wiring
# column. Chassis ratings assume free air and tolerate a 30 C rise; wire
# bundled inside a sealed printed enclosure does neither. Using the chassis
# figures here would nominate 30 AWG for 700 mA, which is absurd in practice.
_AWG_AMPS = {30: 0.14, 28: 0.23, 26: 0.36, 24: 0.58, 22: 0.92,
             20: 1.5, 18: 2.3, 16: 3.7, 14: 5.9}


def trace_width_mm(current_a: float, temp_rise_c: float = 10.0,
                   thickness_oz: float = 1.0,
                   layer: str = "external") -> float:
    """Minimum trace width by IPC-2221.

    area_mils2 = (I / (k * dT^b)) ^ (1/c)
    """
    if current_a <= 0:
        return 0.0
    k, b, c = _IPC[layer]
    area_mils2 = (current_a / (k * temp_rise_c ** b)) ** (1 / c)
    thickness_mils = 1.378 * thickness_oz
    width_mils = area_mils2 / thickness_mils
    return width_mils * 0.0254


def wire_gauge(current_ma: float) -> int:
    """Smallest sensible AWG for a given current in hookup wire."""
    amps = current_ma / 1000.0
    for awg in sorted(_AWG_AMPS, reverse=True):      # thinnest first
        if _AWG_AMPS[awg] >= amps:
            return awg
    return min(_AWG_AMPS)


# Metric cross-sections to the nearest AWG at or above that capacity, for
# harnesses written in mm2 -- WireViz's own default unit.
_MM2_TO_AWG = [(0.05, 30), (0.08, 28), (0.14, 26), (0.25, 24), (0.34, 22),
               (0.5, 20), (0.75, 18), (1.0, 17), (1.5, 16), (2.5, 14)]


def parse_awg(gauge, unit=None) -> int | None:
    """AWG from WireViz notation: 22, "22 AWG", "0.25 mm2", or gauge+unit.

    Returns None when it cannot tell, which the gauge check reports rather
    than guessing. int() on "26 AWG" crashed the first real run.
    """
    if gauge is None:
        return None
    text = f"{gauge} {unit or ''}".strip().lower().replace("²", "2")
    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*(awg|mm2|mm\^2|mm)?", text)
    if not m:
        return None
    value, u = float(m.group(1)), (m.group(2) or "")
    if u == "awg" or (not u and value >= 8 and value.is_integer()):
        return int(value)
    for mm2, awg in _MM2_TO_AWG:           # metric: smallest that fits
        if value <= mm2 + 1e-9:
            return awg
    return 14


def check_wire_gauges(runs: list[dict]) -> Result:
    """runs: [{name, current_ma, awg}] -- verify each wire is thick enough."""
    if not runs:
        return Result("wire_gauge", SKIP, "no harness runs declared")
    problems, notes = [], []
    for r in runs:
        need = wire_gauge(r["current_ma"])
        have = r.get("awg")
        if have is None:
            notes.append(f"{r['name']}: gauge not stated or not readable; "
                         f"needs {need} AWG or thicker")
            continue
        have = int(have)
        est = " (current estimated)" if r.get("estimated") else ""
        line = (f"{r['name']}: {r['current_ma']:.0f} mA{est} needs "
                f"{need} AWG or thicker, harness says {have} AWG")
        if have > need:      # larger AWG number = thinner wire
            problems.append(line)
        else:
            notes.append(line)
    if problems:
        return Result("wire_gauge", FAIL, "undersized conductors", problems)
    return Result("wire_gauge", PASS, f"{len(runs)} runs", notes)


# --------------------------------------------------------------------
# Cross-file consistency
# --------------------------------------------------------------------

def xref_nets(harness_nets: set[str], schematic_nets: set[str]) -> Result:
    """Every wire in the harness must land on a net the schematic declares."""
    if not harness_nets or not schematic_nets:
        return Result("xref_nets", SKIP, "harness or schematic not built yet")
    orphans = sorted(harness_nets - schematic_nets)
    unwired = sorted(schematic_nets - harness_nets)
    items = []
    if orphans:
        items += [f"harness net not in schematic: {n}" for n in orphans]
    if unwired:
        items += [f"schematic net has no wire: {n}" for n in unwired]
    if orphans:
        return Result("xref_nets", FAIL,
                      f"{len(orphans)} harness net(s) do not exist", items)
    if unwired:
        return Result("xref_nets", PASS,
                      f"{len(unwired)} net(s) not wired (may be intentional)",
                      items)
    return Result("xref_nets", PASS, f"{len(harness_nets)} nets agree")


def xref_cutouts(bom_panel_parts: list[Part],
                 cutouts: set[str]) -> Result:
    """Anything panel-mounted in the BOM needs a hole in the enclosure."""
    needed = {p.ref for p in bom_panel_parts if p.mount == "panel"}
    if not needed:
        return Result("xref_cutouts", SKIP, "no panel-mounted parts")
    missing = sorted(needed - cutouts)
    if missing:
        return Result("xref_cutouts", FAIL,
                      "panel parts with no enclosure opening",
                      [f"{m}: no cutout named for it in housing.py"
                       for m in missing])
    return Result("xref_cutouts", PASS, f"{len(needed)} cutouts present")


def fits_envelope(parts: list[Part], envelope_mm: list[float],
                  clearance_mm: float = 3.0) -> Result:
    """Crude packing sanity: do the footprints plausibly fit the box?"""
    if not envelope_mm or len(envelope_mm) < 3:
        return Result("fits_envelope", SKIP, "no envelope in brief")
    box_area = envelope_mm[0] * envelope_mm[1]
    used = 0.0
    tall = []
    for p in parts:
        if len(p.size_mm) < 3:
            continue
        used += (p.size_mm[0] + clearance_mm) * (p.size_mm[1] + clearance_mm)
        if p.size_mm[2] + clearance_mm > envelope_mm[2]:
            tall.append(f"{p.ref} is {p.size_mm[2]} mm tall, envelope is "
                        f"{envelope_mm[2]} mm")
    items = [f"footprint area {used:.0f} mm2 of {box_area:.0f} mm2 floor"]
    if tall:
        return Result("fits_envelope", FAIL, "part taller than the box",
                      tall + items)
    if used > box_area:
        return Result("fits_envelope", FAIL,
                      "parts cannot lie flat in one layer; stack them or "
                      "grow the enclosure", items)
    # The area sum is a first look; the enclosure's own packing (rims and
    # clearance round each part) decides, as the concept step will.
    from ..enclosure import layout_fault
    fault = layout_fault(parts, envelope_mm)
    if fault:
        return Result("fits_envelope", FAIL, fault, items)
    return Result("fits_envelope", PASS,
                  f"{used / box_area:.0%} of floor area used; the parts pack with their rims",
                  items)


def printability(min_wall_mm: float, wall_mm: float, nozzle_mm: float,
                 overhangs_deg: list[float],
                 limit_deg: float = 50.0) -> Result:
    """Wall thickness against the nozzle, and overhangs against gravity."""
    items, problems = [], []
    lines = max(1, round(wall_mm / nozzle_mm))
    items.append(f"wall {wall_mm} mm = {lines} perimeter(s) at "
                 f"{nozzle_mm} mm nozzle")
    if wall_mm < min_wall_mm:
        problems.append(f"wall {wall_mm} mm is under the {min_wall_mm} mm "
                        "minimum for this printer")
    if wall_mm < nozzle_mm * 2:
        problems.append("wall is under two perimeters; it will be weak and "
                        "may not slice at all")
    steep = [d for d in overhangs_deg if d > limit_deg]
    if steep:
        problems.append(f"overhangs at {steep} degrees exceed the {limit_deg} "
                        "degree supportless limit")
    if problems:
        return Result("printability", FAIL, "not printable as drawn",
                      problems + items)
    return Result("printability", PASS, "prints without supports", items)


