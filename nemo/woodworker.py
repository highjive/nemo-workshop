"""The Workshop's Woodworker (owner, 2026-10-23: "add woodworker to workshop
roster; it gets told flooring or that, but comes up with a plan").

Told a job and its sizes ("flooring 4.2 x 3.6"), it makes a plan by code,
no model: the area, what to buy with a waste allowance, the rows the boards
make and whether the last one comes out too thin, the skirting length, the
steps in order and the tools. Jobs it plans so far: flooring (laminate,
engineered, vinyl plank, solid wood) and skirting. Anything else it says it
cannot plan yet, never a guess.

Figures that belong to a product are NEVER invented: the pack coverage, the
board size, the expansion gap and how long boards rest in the room come from
the maker's packet; where he has not given one the plan says to read it.
The waste allowances and the thin-last-row rule are common rules of thumb
and are labelled so.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Rules of thumb (labelled as such in every plan).
WASTE = {"straight": 0.10, "diagonal": 0.15, "herringbone": 0.15}
THIN_ROW = 1 / 3            # a last row under a third of a board's width
MATERIALS = ("laminate", "engineered", "vinyl", "solid")


@dataclass
class Plan:
    job: str
    lines: list[str] = field(default_factory=list)
    buy: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    read_the_packet: list[str] = field(default_factory=list)
    room_mm: tuple[float, float] | None = None      # length, width (a floor with a board size)
    board_mm: tuple[int, int] | None = None

    def text(self) -> str:
        out = [f"Woodworker's plan: {self.job}", ""] + self.lines
        if self.buy:
            out += ["", "To buy:"] + [f"  - {b}" for b in self.buy]
        if self.read_the_packet:
            out += ["", "From the maker's packet (not guessed here):"] + [f"  - {r}" for r in self.read_the_packet]
        if self.steps:
            out += ["", "Steps:"] + [f"  {i}. {s}" for i, s in enumerate(self.steps, 1)]
        if self.tools:
            out += ["", "Tools: " + ", ".join(self.tools) + "."]
        return "\n".join(out)


def rows(width_mm: float, board_w_mm: float) -> list[float]:
    """The width of each row of boards across the room, wall to wall, in mm,
    first to last: whole boards, then what is left; a last row under
    THIN_ROW of a board is shared with the first instead (the plan's text
    says the same; nemo/drawings.py draws it)."""
    whole = int(width_mm // board_w_mm)
    last = round(width_mm - whole * board_w_mm, 3)
    if last <= 0:
        return [board_w_mm] * whole
    if last < board_w_mm * THIN_ROW and whole >= 1:
        even = round((last + board_w_mm) / 2, 3)
        return [even] + [board_w_mm] * (whole - 1) + [even]
    return [board_w_mm] * whole + [last]


class WoodworkerError(ValueError):
    """What it needs to know, said plainly."""


_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(m|cm|mm)?\s*(?:x|by|×)\s*(\d+(?:\.\d+)?)\s*(m|cm|mm)?", re.I)


def _metres(value: str, unit: str | None) -> float:
    v = float(value)
    unit = (unit or "").lower()
    if unit == "mm":
        return v / 1000
    if unit == "cm":
        return v / 100
    if unit == "m" or v < 30:          # plain numbers under 30 are metres (a room)
        return v
    return v / 1000                    # bigger plain numbers: millimetres


def room_size(text: str) -> tuple[float, float]:
    m = _SIZE.search(text)
    if not m:
        raise WoodworkerError("give the room's length and width, e.g. 'flooring 4.2 x 3.6 m'")
    a = _metres(m.group(1), m.group(2) or m.group(4))
    b = _metres(m.group(3), m.group(4) or m.group(2))
    if not (0.3 <= a <= 50 and 0.3 <= b <= 50):
        raise WoodworkerError(f"{a:g} m by {b:g} m does not look like a room; check the sizes")
    return max(a, b), min(a, b)


def job_of(text: str) -> str:
    low = text.lower()
    if re.search(r"\bskirting|\bscotia|\bbeading", low) and not re.search(r"\bfloor", low):
        return "skirting"
    if re.search(r"\bfloor|\blaminate|\bplank|\bboards?\b", low):
        return "flooring"
    return ""


_COUNTS = {"no": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def doors_in(text: str) -> int | None:
    """The doorways the job's own words give ("with 2 doors", "two doorways",
    "no door"), or None (2026-11-08: "skirting ... with 2 doors" was planned
    for the default one door)."""
    m = re.search(r"\b(\d+|no|one|a|an|two|three|four|five)\s+(?:doors?|doorways?)\b",
                  text.lower())
    if not m:
        return None
    w = m.group(1)
    return int(w) if w.isdigit() else _COUNTS[w]


def plan(text: str, *, pack_m2: float | None = None, board_mm: tuple[int, int] | None = None,
         doors: int | None = None, door_m: float = 0.8, lay: str = "straight") -> Plan:
    """A plan for the job described in `text`. `doors`: given, else the
    text's own count, else one."""
    if doors is None:
        doors = doors_in(text)
    doors = 1 if doors is None else doors
    job = job_of(text)
    if not job:
        raise WoodworkerError("I plan flooring and skirting so far. Say the job and the "
                              "room's size, e.g. 'flooring 4.2 x 3.6 m'")
    length, width = room_size(text)
    low = text.lower()
    lay = next((k for k in WASTE if k in low), lay)
    material = next((m for m in MATERIALS if m in low), "laminate")
    perimeter = 2 * (length + width)
    skirting = max(0.0, perimeter - doors * door_m)
    if job == "skirting":
        p = Plan(f"skirting for a {length:g} x {width:g} m room")
        p.lines = [f"Wall length: {perimeter:.2f} m, less {doors} doorway(s) of {door_m:g} m "
                   f"(a usual inside door, not measured: measure yours): {skirting:.2f} m."]
        p.buy = [f"skirting: {skirting * 1.1:.1f} m (10 % over for cuts and mitres; rule of thumb)",
                 "adhesive or fixings for your walls, filler, caulk"]
        p.steps = ["Measure each wall again where the skirting will sit.",
                   "Cut internal corners scribed or mitred, external corners mitred.",
                   "Fix, fill the nail holes, caulk the top edge, paint or finish."]
        p.tools = ["mitre saw or mitre box", "coping saw", "tape", "pencil", "adhesive gun"]
        return p

    area = length * width
    waste = WASTE[lay]
    need = area * (1 + waste)
    p = Plan(f"{material} flooring, {lay}, {length:g} x {width:g} m")
    p.lines = [f"Floor area: {area:.2f} m2. With {int(waste * 100)} % for cuts and waste "
               f"({lay} laying; rule of thumb): {need:.2f} m2."]
    if pack_m2:
        packs = math.ceil(need / pack_m2)
        p.buy.append(f"{material}: {packs} pack(s) of {pack_m2:g} m2 ({packs * pack_m2:.2f} m2)")
    else:
        p.buy.append(f"{material}: {need:.2f} m2")
        p.read_the_packet.append("how many m2 a pack covers (tell me and I count the packs)")
    if material in ("laminate", "engineered"):
        p.buy.append(f"underlay: {area:.2f} m2 (the kind the flooring's maker names)")
    if material in ("laminate", "engineered", "solid"):
        p.read_the_packet.append("the expansion gap to leave at every wall")
        p.read_the_packet.append("how long the packs rest in the room before laying")
    p.buy.append(f"skirting or scotia to cover the gap: {skirting * 1.1:.1f} m "
                 "(10 % over; rule of thumb)")
    p.buy.append(f"door bar(s): {doors}")
    if board_mm:
        p.room_mm, p.board_mm = (round(length * 1000, 1), round(width * 1000, 1)), board_mm
        board_w = board_mm[1] / 1000
        rows = width / board_w
        whole, last = int(rows), (rows - int(rows)) * board_w
        p.lines.append(f"Across the {width:g} m width: {whole} whole row(s) of "
                       f"{board_mm[1]} mm boards and a last row of {last * 1000:.0f} mm.")
        if 0 < last < board_w * THIN_ROW:
            even = (last + board_w) / 2 * 1000
            p.lines.append(f"That last row is under a third of a board (rule of thumb: too thin "
                           f"to hold). Cut the first and last rows to about {even:.0f} mm each instead.")
    else:
        p.read_the_packet.append("the board's width (tell me and I check the last row is not too thin)")
    p.steps = [
        "Let the packs rest in the room as long as the maker says.",
        "Check the floor below is clean, dry and flat; fix high and low spots first.",
        "Take off the skirting (or plan scotia) and undercut door frames to the board's height.",
        "Lay the underlay, joints taped, not overlapped." if material in ("laminate", "engineered")
        else "Prepare the base the maker asks for.",
        "Start along the longest straight wall, spacers at the gap the maker gives.",
        "Stagger the ends of neighbouring rows; start each row with the last row's offcut where it fits.",
        "Cut the last row to width, keeping the gap at the wall.",
        "Fit door bars, then skirting or scotia over the gap (fixed to the wall, never to the floor).",
    ]
    p.tools = ["tape", "pencil", "square", "saw (jigsaw or mitre saw)", "spacers",
               "tapping block and pull bar", "utility knife", "safety glasses"]
    return p
