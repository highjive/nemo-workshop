"""The local parts library.

Component facts come from files you control, not from model memory. A 4B
model will cheerfully tell you the RC522 is 5 V tolerant. The library is the
answer to that: if a part is not in here and not in datasheets/, Nemo says so
rather than inventing a pinout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

import yaml

# Inside the package, so it travels with any install method. An earlier
# revision kept it beside the package, where a pip install left it behind:
# the library loaded empty, every design failed at stage 2, and no test
# noticed because the tests import from the source tree.
BUNDLED = Path(__file__).resolve().parent / "data" / "parts"


@dataclass
class Pin:
    name: str
    function: str = ""        # power | gnd | io | analog | bus | contact | speaker | usb_dm | usb_dp
    # "contact" is the switched side of a relay: isolated from the circuit,
    # never offered to the model and never wired by Nemo (D159).
    voltage: float | None = None
    # Which way a signal pin drives, seen from the part: "in" or "out".
    # Empty where it is not known or goes both ways. Set only where the
    # pin's own name says so (DIN, DOUT, RX, TX, IN, MISO, MOSI), D147, or
    # where a datasheet's pin table gives it and the entry cites it.
    direction: str = ""
    # The highest voltage an input may be driven at, where a datasheet
    # gives one above the level it works at (a 5 V-tolerant input).
    tolerates: float | None = None
    # The part works with this pin left unwired, on a source the entry
    # cites. Not offered to the model where it is asked for signals only,
    # and the step says which were left (D166).
    optional: bool = False
    # function "speaker" is a speaker terminal or an amplifier's output to
    # one: wired by code, amplifier to speaker, never offered to the model.
    # function "usb_dm" / "usb_dp" is a USB data line (a board's USB pins,
    # a socket's D-/D+): wired by code, harness.wire_usb, never offered.


@dataclass
class Part:
    ref: str                  # short key, e.g. "rc522"
    name: str
    category: str             # mcu | sensor | audio | power | actuator | ...
    logic_v: float | None = None
    supply_v: list[float] = field(default_factory=list)
    current_ma: float = 0.0          # typical
    peak_ma: float = 0.0
    size_mm: list[float] = field(default_factory=list)   # L, W, H
    mount: str = ""                  # holes | slot | panel | loose
    pins: list[Pin] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)  # spi, i2s, uart...
    datasheet: str = ""
    source: str = ""
    notes: str = ""
    output_v: list[float] = field(default_factory=list)   # a converter's regulated output(s); empty for anything that is not one
    efficiency: float | None = None                       # fraction 0-1, only meaningful alongside output_v
    # Other parts this one must not sit near: {their ref: least distance in
    # mm, edge to edge}. The enclosure step lays the parts out to honour it
    # and fails if it cannot. Only for a distance a source actually gives.
    keep_apart: dict[str, float] = field(default_factory=dict)
    # A level shifter's channels: [{in: pin, out: pin, enable_low: pin}].
    # A signal at the in pin's level comes out at the out pin's. Empty for
    # every other part.
    gates: list[dict] = field(default_factory=list)
    # Where it sits on a circuit board (the PCB Designer, nemo/pcb.py; owner,
    # 2026-11-04): a KiCad footprint "Library:Name", and which pad each named
    # pin is ({pin name: pad number}). Physical facts: added part by part from
    # a source, never guessed; a part without them is said, not laid out.
    footprint: str = ""
    pads: dict[str, str] = field(default_factory=dict)
    footprint_source: str = ""       # where footprint and pads came from (required with them)

    @property
    def draw_ma(self) -> float:
        return self.peak_ma or self.current_ma

    def pin(self, name: str) -> Pin | None:
        low = name.lower()
        return next((p for p in self.pins if p.name.lower() == low), None)


def _build_part(ref, raw) -> Part:
    """Part from a YAML entry, refusing values YAML quietly mistyped.

    YAML 1.1 reads bare NO, NC-adjacent words like ON/OFF/YES/N as booleans,
    so a relay pin written as `name: NO` loaded as False and crashed the
    wiring check with "'bool' object has no attribute 'lower'" -- found by
    a data-quality sweep of the library, not by any user.
    """
    if not isinstance(ref, str):
        raise ValueError(f"the reference {ref!r} is not text -- quote it in "
                         "the YAML (words like no/on/yes read as true/false)")
    if not isinstance(raw, dict):
        raise ValueError("entry is not a set of fields")
    raw = dict(raw)
    pins = []
    for pin in raw.pop("pins", []) or []:
        pin = pin if isinstance(pin, dict) else {"name": pin}
        if not isinstance(pin.get("name"), str):
            raise ValueError(f"pin name {pin.get('name')!r} is not text -- "
                             "quote it in the YAML, e.g. name: \"NO\"")
        if pin.get("direction", "") not in ("", "in", "out"):
            raise ValueError(f"pin {pin['name']}: direction must be in or out, "
                             f"not {pin.get('direction')!r}")
        pins.append(Pin(**pin))
    names = {p.name for p in pins}
    for gate in raw.get("gates") or []:
        if not isinstance(gate, dict) or not {"in", "out"} <= set(gate) \
                or any(str(v) not in names for v in gate.values()):
            raise ValueError("each gate needs an in and an out, and every pin it "
                             "names must be one of the part's pins")
    apart = raw.get("keep_apart") or {}
    if not isinstance(apart, dict) or any(
            not isinstance(k, str) or isinstance(v, bool)
            or not isinstance(v, (int, float)) or v <= 0 for k, v in apart.items()):
        raise ValueError("keep_apart must map a part's reference to a distance "
                         "in mm above zero, e.g. keep_apart: {rc522: 25}")
    raw["keep_apart"] = {k: float(v) for k, v in apart.items()}
    # Pad numbers read as numbers from YAML ({VCC: 1}); a pad is a name.
    pads = raw.get("pads") or {}
    if not isinstance(pads, dict) or any(str(k) not in names for k in pads):
        raise ValueError("pads must map each of the part's pin names to its pad, "
                         "e.g. pads: {VCC: 1, GND: 2}")
    raw["pads"] = {str(k): str(v) for k, v in pads.items()}
    return Part(ref=ref, pins=pins, **raw)


class PartsLibrary:
    def __init__(self, parts: dict[str, Part]):
        self.parts = parts
        self.errors: list[str] = []

    @classmethod
    def load(cls, *dirs: Path, bundled: bool = True) -> "PartsLibrary":
        """The bundled library, extended by any folders given.

        User folders are loaded after the bundled library, so an entry with
        the same ref overrides the bundled one -- correct a figure without
        editing the package. An earlier revision loaded ONLY the folders
        given, so adding a parts folder discarded the whole curated library.
        """
        roots = ([BUNDLED] if bundled else []) + [Path(d) for d in dirs if d]
        found: dict[str, Part] = {}
        errors: list[str] = []
        for root in roots:
            root = Path(root).expanduser()
            if not root.exists():
                continue
            for f in sorted(root.glob("*.yaml")):
                try:
                    doc = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace")) or {}
                except yaml.YAMLError as exc:
                    errors.append(f"{f.name}: not valid YAML ({exc})")
                    continue
                for ref, raw in (doc.items() if isinstance(doc, dict) else []):
                    try:
                        found[str(ref)] = _build_part(ref, raw)
                    except (TypeError, ValueError, KeyError) as exc:
                        # One bad entry must not take the whole library down,
                        # and must not be skipped silently either: it is
                        # kept in .errors for the doctor to report.
                        errors.append(f"{f.name}: {ref}: {exc}")
        lib = cls(found)
        lib.errors = errors
        return lib

    def get(self, ref: str) -> Part | None:
        return self.parts.get(ref.lower())

    def require(self, ref: str) -> Part:
        p = self.get(ref)
        if p is None:
            raise KeyError(
                f"part {ref!r} is not in the library. Add it to parts/ with "
                "figures from the datasheet before using it in a design."
            )
        return p

    def __len__(self) -> int:
        return len(self.parts)

    def __iter__(self):
        return iter(self.parts.values())


# ====================================================================
#  Adding a part by hand (the "Add a part" form and 'nemo part add')
# ====================================================================

_REF_OK = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

# A slightly wider set than the categories the bundled library actually
# uses (mcu/sensor/audio/power/actuator/display/driver): only "mcu" and
# "power" change any check's behaviour (parts.py, fixes.py), so anything
# else is free text -- but the field must not be left empty, and offering
# the known ones first is friendlier than a blank box.
KNOWN_CATEGORIES = ["sensor", "actuator", "display", "driver", "audio",
                    "power", "mcu", "connector", "logic", "other"]


def validate_part(data: dict, existing_refs: set[str] | None = None,
                  allow_overwrite: bool = False) -> list[str]:
    """What is wrong with a part dict before it is saved, in plain words.

    Checked here rather than left to YAML loading or the checks that use
    Part later: those are the wrong place to first discover that someone
    typed a negative current or forgot the part's name, and a check that
    silently produces 0 mA or None for a bad value would make a design
    look safer than it is.
    """
    problems = []
    ref = (data.get("ref") or "").strip().lower()
    if not ref:
        problems.append("Give the part a short reference (letters, "
                        "numbers, underscores -- this is how other parts "
                        "and the model refer to it).")
    elif not _REF_OK.match(ref):
        problems.append("The reference must start with a letter and use "
                        "only lowercase letters, numbers and underscores.")
    elif existing_refs and ref in existing_refs and not allow_overwrite:
        problems.append(f"'{ref}' is already in the library. Choose a "
                        "different reference, or confirm you want to "
                        "replace the existing entry.")

    if not (data.get("name") or "").strip():
        problems.append("Give the part a name -- what you'd search a "
                        "datasheet for.")
    if not (data.get("category") or "").strip():
        problems.append("Choose a category.")

    for field_name, label in (("current_ma", "typical current"),
                              ("peak_ma", "peak current")):
        v = data.get(field_name)
        if v not in (None, ""):
            try:
                if float(v) < 0:
                    problems.append(f"The {label} can't be negative.")
            except (TypeError, ValueError):
                problems.append(f"The {label} must be a number, in mA.")

    for v in data.get("supply_v") or []:
        try:
            if float(v) <= 0:
                problems.append("Supply voltages must be greater than 0.")
                break
        except (TypeError, ValueError):
            problems.append("Supply voltages must be numbers, in volts.")
            break

    for v in data.get("output_v") or []:
        try:
            if float(v) <= 0:
                problems.append("A converter's output voltage must be greater than 0.")
                break
        except (TypeError, ValueError):
            problems.append("A converter's output voltage must be a number, in volts.")
            break

    eff = data.get("efficiency")
    if eff not in (None, ""):
        try:
            if not (0 < float(eff) <= 1):
                problems.append("Efficiency is a fraction between 0 and 1 "
                                "(0.93 for 93%, not 93).")
        except (TypeError, ValueError):
            problems.append("Efficiency must be a number between 0 and 1.")

    lv = data.get("logic_v")
    if lv not in (None, ""):
        try:
            float(lv)
        except (TypeError, ValueError):
            problems.append("Logic voltage must be a number, in volts, or "
                            "left blank.")

    if not (data.get("datasheet") or "").strip():
        problems.append("Say where the figures came from -- a datasheet "
                        "name and revision, or 'estimated, not yet "
                        "verified' if you are not sure yet. This is what "
                        "lets you or someone else check a number later.")
    return problems


def user_parts_path(root: Path) -> Path:
    return Path(root).expanduser() / "user-parts.yaml"


def save_part(root: Path, data: dict) -> Path:
    """Write one part into the user's own parts file, keyed by ref.

    Never touches the bundled library (BUNDLED is read-only after install
    on some platforms, and is meant to stay curated). Adding a part with
    the same ref as one already in this file replaces that entry; adding
    one with the same ref as a BUNDLED part is allowed too -- that is the
    documented way to correct a bundled figure (see PartsLibrary.load) --
    but validate_part() only permits it when the caller passed
    allow_overwrite=True, so it is a choice, not an accident.
    """
    ref = data["ref"].strip().lower()
    path = user_parts_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {}
    if path.exists():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
        except yaml.YAMLError:
            doc = {}
    entry = {k: v for k, v in data.items() if k != "ref" and v not in
             (None, "", [], {})}
    doc[ref] = entry
    path.write_text(yaml.safe_dump(doc, sort_keys=True,
                                   allow_unicode=True, default_flow_style=False), encoding="utf-8")
    return path


def delete_user_part(root: Path, ref: str) -> bool:
    """Remove a part from the user's own file. Never touches BUNDLED, so
    this can never delete a part Nemo ships -- only something added here."""
    path = user_parts_path(root)
    if not path.exists():
        return False
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except yaml.YAMLError:
        return False
    ref = ref.strip().lower()
    if ref not in doc:
        return False
    del doc[ref]
    if doc:
        path.write_text(yaml.safe_dump(doc, sort_keys=True,
                                       allow_unicode=True, default_flow_style=False), encoding="utf-8")
    else:
        path.unlink()
    return True
