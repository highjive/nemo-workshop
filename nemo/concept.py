"""The Artist's concepts: two ways the enclosure could be, to choose from
before the Designer models it (owner's request, 2026-10-20).

Drawn by code from real geometry, not imagined: each concept is a layout
the enclosure step can build (enclosure.auto_layout and its checks) and a
style it can build (enclosure.cadquery_script's corners and cable-notch
wall), rendered from the CadQuery model itself. What is picked is what is
made. An image model was not used for this on purpose: a picture of a box
that cannot be built would be a promise the Designer cannot keep.

  A  what Nemo builds unasked: its own order (sensors away from the warm
     part, keep-apart distances kept), square corners, the cable notch in
     the left wall.
  B  a different arrangement that keeps the same rules, rounded corners,
     the notch in the front wall. Where no other sound arrangement exists
     (one part, a full box), B differs in style only and says so.

The owner picks one and may change it: the corners and the notch wall are
bounded choices, applied as given; anything said about where parts go is
passed to the Designer as a constraint, so the model is asked for an order
only then (D172).

Files, in <project>/concept: A.json and B.json (layout and style),
A-plan.svg and B-plan.svg (the floor plan, parts labelled), A-iso.png and
B-iso.png (the rendered model, where CadQuery and numpy are installed), and
choice.json. A concept or choice made for other parts or another envelope
is stale and is not used.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import enclosure
from .enclosure import Box, EnclosureError, Placed
from .parts import Part

KEYS = ("A", "B")
STYLES = {"A": ("square", "left"), "B": ("rounded", "front")}
CORNER_WORDS = {"square": "square corners", "rounded": "rounded corners"}
NOTCH_WORDS = {"left": "the cable opening in the left wall",
               "front": "the cable opening in the front wall"}


@dataclass
class Concept:
    key: str
    title: str
    corners: str
    notch_wall: str
    order: list[str]
    placed: list[dict]              # Placed as dicts
    said: list[str] = field(default_factory=list)
    # "tray": built from geometry, as above. "painted": an impression of a
    # shaped object Nemo cannot model (a replica, a prop), painted by the
    # image model from `prompt`; its picture is <key>-painted.png.
    kind: str = "tray"
    prompt: str = ""
    # "blockout" (owner, 2026-10-28): the object built from the Art Studio's
    # kit of shapes (nemo/blockout.py), the modelkit spec it is; the
    # Designer builds the one chosen. <key>-sketch.png, <key>-spec.json.
    spec: dict = field(default_factory=dict)

    def layout(self) -> list[Placed]:
        return [Placed(**p) for p in self.placed]


def signature(parts: list[Part], envelope) -> str:
    """What a concept was drawn for: the parts and the brief's envelope (a
    Box or [l, w, h]). Different parts, sizes or envelope: stale. The wall
    is not in it; the enclosure step checks a layout against the real
    walls before using it."""
    if isinstance(envelope, Box):
        envelope = [envelope.length, envelope.width, envelope.height]
    data = [[p.ref, list(p.size_mm), p.mount, p.category, round(p.draw_ma, 3),
             sorted((p.keep_apart or {}).items())] for p in parts]
    data.append([float(x) for x in (envelope or [])])
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def painted_signature(brief) -> str:
    """What a shaped object's concepts were made for: the words describing it,
    its real size and its facts, and the anatomy they were built by. Any change
    draws them again (code, in a moment; the model is not asked)."""
    from .anatomy import VERSION
    data = [f"anatomy-{VERSION}", brief.name or "", brief.function or "",
            [str(c) for c in (brief.constraints or [])],
            [float(v) for v in (getattr(brief, "shape_size_mm", None) or [])],
            dict(sorted((getattr(brief, "shape_facts", None) or {}).items()))]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]


def current_signature(brief, parts: list[Part]) -> str:
    """The signature a concept or choice must carry to count now: painted
    for a shaped object (review.shape_asked), else the parts and envelope."""
    from .review import shape_asked
    return painted_signature(brief) if shape_asked(brief) else signature(parts, brief.envelope_mm)


# Two ways to see the object, for the owner to choose between. Shown the
# subject only; nothing here is a fact about what Nemo will build.
PAINT = {"A": ("A workshop sketch", "concept art, clean product design sketch, side view, "
               "pencil and marker on paper", 11),
         "B": ("A painted render", "concept art, painted render, three-quarter view, "
               "dramatic workshop lighting, detailed", 23)}


def subject(brief) -> str:
    """What the object is, in the brief's own words, trimmed for the image
    model's text encoder (77 tokens)."""
    words = " ".join(f"{brief.function or brief.name}".split())
    first = words.split(". ")[0]
    return " ".join(first.split()[:28])


def real_size(brief) -> list[float] | None:
    """The object's own size from the brief (shape_size_mm), 0 where not
    known; None if not given."""
    real = [float(v) for v in (getattr(brief, "shape_size_mm", None) or [])][:3]
    if real and any(v > 0 for v in real) and all(v >= 0 for v in real):
        return real + [0.0] * (3 - len(real))
    return None


def size_for(brief) -> list[float] | None:
    """The size a shaped object's concepts are drawn: its real size where the
    brief gives one (shape_size_mm, 0 = not known on that axis), else the
    brief's inside size, else None: the size the model's shapes have."""
    real = real_size(brief)
    if real:
        return real
    env = [float(v) for v in (brief.envelope_mm or [])][:3]
    return env if len(env) == 3 and all(v > 0 for v in env) else None


def make_built(brief) -> list[Concept]:
    """Two concepts of a shaped object, built by code from its anatomy
    (nemo/anatomy.py; owner, 2026-11-04: "remove blockout"): A the main forms,
    B more detail. anatomy.UnknownObject, saying why, where Nemo's code does
    not know the object or its size is not given."""
    from . import anatomy
    size = size_for(brief)
    out = []
    for key in KEYS:
        doc, said = anatomy.build(brief, size, detail=(key == "B"))
        doc["name"] = f"{brief.name or 'object'} concept {key}"
        title = "The main forms" if key == "A" else "More detail"
        out.append(Concept(key, title, "square", "left", [], [], said, kind="blockout",
                           prompt=f"{PAINT[key][1]}: {subject(brief)}, plain background", spec=doc))
    return out


def save_painted(project_root: Path, concepts: list[Concept], sig: str) -> None:
    d = folder(project_root)
    d.mkdir(parents=True, exist_ok=True)
    for c in concepts:
        (d / f"{c.key}.json").write_text(json.dumps({"signature": sig, **asdict(c)}, indent=2),
                                         encoding="utf-8")
        if c.kind == "blockout":
            from . import blockout
            (d / f"{c.key}-spec.json").write_text(json.dumps(blockout.buildable(c.spec), indent=1),
                                                  encoding="utf-8")
            draw_blueprint(c, d)


SPLIT_WORDS = ("Printed in ", "Too big to print whole", "Prints whole")


def plan_joints(c: Concept, d: Path):
    """A concept bigger than the printer: its pieces and pins, planned now so
    the blueprint shows them (owner, 2026-11-04: "if parts are too large for
    printer have them separated so can be printed in parts and have concept
    show this with joints parts"). Kept in <key>-joints.json, which the
    Designer's build uses as it is. Returns (plan or None, a note); says it in
    the concept's own words (c.said)."""
    from . import joints
    from .config import Config
    path = d / f"{c.key}-joints.json"
    path.unlink(missing_ok=True)                       # an old plan is for other shapes
    try:
        plan = joints.plan_concept(Config.load(), c.spec)
    except joints.SplitError as exc:
        plan, note = None, f"Too big to print whole, and cannot be split: {exc}."
    except ImportError as exc:                          # no numpy/trimesh: said, not guessed
        plan, note = None, f"Too big to print whole? Not worked out here ({exc})."
    else:
        if plan is None:
            note = ""
        else:
            path.write_text(json.dumps(asdict(plan), indent=1), encoding="utf-8")
            pairs = joints.joint_pins(plan)
            pins = sum(len(v) for v in pairs.values())
            note = (f"Printed in {plan.pieces} pieces, cut along "
                    + " and ".join("xyz"[a] for a in plan.axes)
                    + f", {len(pairs)} joints with {pins} alignment pins; "
                    "the blueprint shows them in amber.")
            if plan.notes:
                note += " " + "; ".join(plan.notes) + "."
    c.said = [s for s in c.said if not s.startswith(SPLIT_WORDS)] + ([note] if note else [])
    return plan, note


def joints_plan(project_root: Path, key: str):
    """The plan saved with a concept, or None."""
    from . import joints
    path = folder(project_root) / f"{key}-joints.json"
    try:
        return joints.plan_from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None


def draw_blueprint(c: Concept, d: Path, plan=None, note: str | None = None) -> Path:
    """A shaped object's concept as a blueprint (owner, 2026-11-04: "change
    from blockout to blueprint in concept"). The kind stays "blockout" inside,
    so projects drawn before still load. Too big for the printer, it shows the
    pieces and joints it will be printed in."""
    from . import blockout
    if note is None:
        plan, note = plan_joints(c, d)
        saved = d / f"{c.key}.json"
        if saved.is_file():                            # its words now say how it prints
            data = json.loads(saved.read_text(encoding="utf-8"))
            data["said"] = c.said
            saved.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return blockout.blueprint_png(c.spec, d / f"{c.key}-blueprint.png", f"{c.key}: {c.title}",
                                  plan=plan, split_note="" if plan else note)


def ensure_blueprints(project_root: Path, concepts: list) -> None:
    """Concepts drawn before the blueprint (a marker sketch) get one, from the
    shapes already chosen: the model is not asked again."""
    d = folder(project_root)
    for c in concepts:
        if c.kind == "blockout" and c.spec and not (d / f"{c.key}-blueprint.png").exists():
            draw_blueprint(c, d)


def picture(project_root: Path, c: Concept) -> Path:
    """The picture shown for a concept: painted, a blueprint, or rendered from
    the model (an older project's marker sketch where it has no blueprint)."""
    d = folder(project_root)
    if c.kind == "blockout":
        bp = d / f"{c.key}-blueprint.png"
        return bp if bp.exists() or not (d / f"{c.key}-sketch.png").exists() else d / f"{c.key}-sketch.png"
    return d / {"painted": f"{c.key}-painted.png"}.get(c.kind, f"{c.key}-iso.png")



def _sound(placed: list[Placed], box: Box, parts: list[Part]) -> bool:
    return not enclosure.faults(placed, box) and not enclosure.too_close(placed, parts)


def _warmth(placed: list[Placed], parts: list[Part]) -> float:
    g = enclosure.nearest_sensor_gap(placed, parts)
    return g[2] if g else float("inf")


def nemos_layout(parts: list[Part], box: Box) -> tuple[list[Placed], list[str], list[str]]:
    """The layout the enclosure step makes when the model is not asked:
    largest first, or sensors away from the warm part, and the library's
    keep-apart distances. (layout, order, sentences on why)."""
    said: list[str] = []
    order = enclosure.thermal_order(parts)
    placed = enclosure.auto_layout(parts, box, order)
    if order:
        said.append("Sensors at one end, the part that warms the box at the other.")
    else:
        order = [a.ref for a in placed]
        if placed:
            said.append("The parts in rows, largest first.")
    if enclosure.too_close(placed, parts):
        again, order2, short = enclosure.layout_keeping_apart(parts, box, [order])
        if again is not None:
            placed, order = again, order2
            said.append("Parts the library says to keep apart are kept apart.")
        else:
            said.append(f"Parts the library says to keep apart cannot be: {short:g} mm short.")
    return placed, order, said


def other_layout(parts: list[Part], box: Box, first: list[Placed]
                 ) -> tuple[list[Placed], list[str], list[str]] | None:
    """A sound layout that differs from `first` and keeps a sensor no nearer
    the warm part. None if there is none."""
    seen = {tuple((a.ref, a.x, a.y, a.dx) for a in first)}
    floor = _warmth(first, parts)
    refs = [p.ref for p in enclosure.sized(parts)]
    if not first:
        return None                      # no parts: nothing to arrange another way
    candidates: list[tuple[list[Placed], list[str], str]] = [
        (enclosure.spread(first, box), [a.ref for a in first],
         "The same rows, spread to the far walls for room between the parts.")]
    if len(refs) <= 6:
        for order in itertools.permutations(refs):
            try:
                candidates.append((enclosure.auto_layout(parts, box, list(order)), list(order),
                                   "Another order along the box."))
            except EnclosureError:
                continue
    for placed, order, why in candidates:
        key = tuple((a.ref, a.x, a.y, a.dx) for a in placed)
        if key in seen:
            continue
        seen.add(key)
        if not _sound(placed, box, parts):
            continue
        if _warmth(placed, parts) + 0.5 < floor:
            continue
        return placed, order, [why]
    return None


def make(parts: list[Part], box: Box) -> list[Concept]:
    """Concepts A and B for these parts in this box. Raises EnclosureError
    when no layout fits at all (the enclosure step could not build one)."""
    a_placed, a_order, a_said = nemos_layout(parts, box)
    b = other_layout(parts, box, a_placed)
    out = []
    for key, (placed, order, said) in (("A", (a_placed, a_order, a_said)),
                                       ("B", b or (a_placed, a_order,
                                                   ["No other sound arrangement of these "
                                                    "parts fits this box, so B differs in "
                                                    "style only."]))):
        corners, notch = STYLES[key]
        title = (f"{CORNER_WORDS[corners].capitalize()}, {NOTCH_WORDS[notch]}")
        out.append(Concept(key, title, corners, notch, list(order),
                           [asdict(p) for p in placed], list(said)))
    return out


# -------------------------------------------------------------- drawing
def plan_svg(concept: Concept, box: Box, parts: list[Part], scale: float = 3.0) -> str:
    """The floor plan, seen from above, parts labelled. Standard library."""
    by_ref = {p.ref: p for p in parts}
    pad = 24
    w, h = box.length * scale + 2 * pad, box.width * scale + 2 * pad + 28

    def X(x):
        return pad + x * scale

    def Y(y):                         # y = 0 (the front wall) at the bottom
        return pad + (box.width - y) * scale

    r = enclosure.corner_radius(box) if concept.corners == "rounded" else 0.0
    ri = max(r - box.wall, 0.0)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
           f'viewBox="0 0 {w:.0f} {h:.0f}" font-family="sans-serif">',
           f'<rect width="{w:.0f}" height="{h:.0f}" fill="#F7F7F3"/>',
           f'<rect x="{X(0):.1f}" y="{Y(box.width):.1f}" width="{box.length * scale:.1f}" '
           f'height="{box.width * scale:.1f}" rx="{r * scale:.1f}" fill="#9CB0C6" stroke="#33475B"/>',
           f'<rect x="{X(box.wall):.1f}" y="{Y(box.width - box.wall):.1f}" '
           f'width="{(box.length - 2 * box.wall) * scale:.1f}" '
           f'height="{(box.width - 2 * box.wall) * scale:.1f}" rx="{ri * scale:.1f}" '
           f'fill="#DCE4EC" stroke="#33475B"/>']
    placed = concept.layout()
    for a in placed:
        x, y = box.wall + a.x, box.wall + a.y
        out.append(f'<rect x="{X(x):.1f}" y="{Y(y + a.dy):.1f}" width="{a.dx * scale:.1f}" '
                   f'height="{a.dy * scale:.1f}" fill="#FFFFFF" stroke="#1F3A5F" stroke-width="1.5"/>')
        label = label_for(by_ref.get(a.ref), a.ref, a.dx * scale / 7)
        out.append(f'<text x="{X(x + a.dx / 2):.1f}" y="{Y(y + a.dy / 2) + 4:.1f}" '
                   f'font-size="11" text-anchor="middle" fill="#1F3A5F">{_esc(label)}</text>')
    mcu = next((a for a in placed if by_ref.get(a.ref) and by_ref[a.ref].category == "mcu"),
               placed[0] if placed else None)
    if mcu is not None:
        nw, _ = enclosure.NOTCH
        if concept.notch_wall == "front":
            cx = box.wall + mcu.x + mcu.dx / 2
            out.append(f'<rect x="{X(cx - nw / 2):.1f}" y="{Y(box.wall):.1f}" width="{nw * scale:.1f}" '
                       f'height="{box.wall * scale:.1f}" fill="#E07A1F"/>')
        else:
            cy = box.wall + mcu.y + mcu.dy / 2
            out.append(f'<rect x="{X(0):.1f}" y="{Y(cy + nw / 2):.1f}" width="{box.wall * scale:.1f}" '
                       f'height="{nw * scale:.1f}" fill="#E07A1F"/>')
    out.append(f'<text x="{pad}" y="{h - 10:.0f}" font-size="12" fill="#33475B">'
               f'{concept.key}: {_esc(concept.title)}. Orange: cable opening. '
               f'{box.length:g} x {box.width:g} x {box.height:g} mm.</text>')
    out.append("</svg>")
    return "\n".join(out)


def label_for(part: Part | None, ref: str, room_chars: float) -> str:
    """A part's name for a drawing: the whole name where it fits, else its
    first word (BME280, SSD1306, ESP32), else the reference."""
    if part is None:
        return ref
    name = part.name.split(" (")[0]
    if len(name) <= room_chars:
        return name
    first = name.split()[0]
    return first if len(first) <= max(room_chars, 6) else ref


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------- files
def folder(project_root: Path) -> Path:
    return Path(project_root) / "concept"


def save(project_root: Path, concepts: list[Concept], sig: str, box: Box,
         parts: list[Part]) -> list[Path]:
    d = folder(project_root)
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for c in concepts:
        p = d / f"{c.key}.json"
        p.write_text(json.dumps({"signature": sig, **asdict(c)}, indent=2), encoding="utf-8")
        s = d / f"{c.key}-plan.svg"
        s.write_text(plan_svg(c, box, parts), encoding="utf-8")
        files += [p, s]
    return files


def set_aside(project_root: Path) -> Path | None:
    """The concepts and the choice moved into concept/earlier/<time>, so the
    next concept step asks for new ones (owner, 2026-11-04: "redraw with
    realistic proportions"). Moved, never deleted. Returns where, or None if
    there was nothing to move."""
    import shutil
    import time as _time
    d = folder(project_root)
    files = [f for f in d.glob("*") if f.is_file()] if d.is_dir() else []
    if not files:
        return None
    dest = d / "earlier" / _time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.move(str(f), str(dest / f.name))
    return dest


def load(project_root: Path, sig: str | None = None) -> list[Concept]:
    """The saved concepts; [] if missing, unreadable or (given sig) stale."""
    out = []
    for key in KEYS:
        try:
            d = json.loads((folder(project_root) / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if sig is not None and d.pop("signature", None) != sig:
            return []
        d.pop("signature", None)
        try:
            out.append(Concept(**d))
        except TypeError:
            return []
    return out


@dataclass
class Choice:
    concept: str
    corners: str
    notch_wall: str
    notes: str = ""
    signature: str = ""
    when: int = 0
    kind: str = "tray"
    title: str = ""


def choose(project_root: Path, key: str, sig: str, corners: str | None = None,
           notch_wall: str | None = None, notes: str = "") -> Choice:
    """Record the owner's pick, with any changes. Raises ValueError for a
    concept that is not there or a style Nemo cannot build."""
    concepts = {c.key: c for c in load(project_root, sig)}
    if key not in concepts:
        raise ValueError(f"there is no concept {key!r} for this design; run the concept step")
    c = concepts[key]
    if c.kind in ("painted", "blockout"):
        # Corners and the cable opening belong to a tray; a shaped object
        # has its picture (or blockout) and what the owner says about it.
        ch = Choice(key, c.corners, c.notch_wall, notes.strip(), sig, int(time.time()),
                    c.kind, c.title)
        (folder(project_root) / "choice.json").write_text(json.dumps(asdict(ch), indent=2),
                                                          encoding="utf-8")
        return ch
    corners = corners or c.corners
    notch_wall = notch_wall or c.notch_wall
    if corners not in CORNER_WORDS:
        raise ValueError(f"corners must be one of: {', '.join(CORNER_WORDS)}")
    if notch_wall not in NOTCH_WORDS:
        raise ValueError(f"the cable opening's wall must be one of: {', '.join(NOTCH_WORDS)}")
    ch = Choice(key, corners, notch_wall, notes.strip(), sig, int(time.time()))
    (folder(project_root) / "choice.json").write_text(json.dumps(asdict(ch), indent=2),
                                                      encoding="utf-8")
    return ch


def chosen(project_root: Path, sig: str | None = None) -> Choice | None:
    """The owner's pick; None if there is none, or (given sig) it is stale."""
    try:
        d = json.loads((folder(project_root) / "choice.json").read_text(encoding="utf-8"))
        ch = Choice(**d)
    except (OSError, ValueError, TypeError):
        return None
    if sig is not None and ch.signature != sig:
        return None
    return ch


def describe(ch: Choice) -> str:
    if ch.kind == "blockout":
        s = (f"Concept {ch.concept}, a blueprint from the kit of shapes "
             f"(concept/{ch.concept}-blueprint.png): the Art Studio's Designer builds it from "
             f"concept/{ch.concept}-spec.json")
    elif ch.kind == "painted":
        s = (f"Concept {ch.concept}, a painted impression ({ch.title.lower() or 'painted'}; "
             f"concept/{ch.concept}-painted.png): the shape is to be modelled in a CAD "
             "program from it")
    else:
        s = f"Concept {ch.concept}: {CORNER_WORDS[ch.corners]}, {NOTCH_WORDS[ch.notch_wall]}"
    return s + (f". Changes: {ch.notes}" if ch.notes else ".")
