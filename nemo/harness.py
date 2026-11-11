"""The wiring harness as constrained data, written out by code.

The wiring step used to ask the model for a whole WireViz document. On the
first real run (AH531, qwen3-1.7b) it returned a document for a different
project, under a key WireViz does not read, joining connectors it had not
defined. Its mistakes were all in things the model has no business
choosing: the file's structure, which parts exist, what their pins are
called.

So the model is now asked only for what is actually a design decision:
which pin of which part goes to which pin of which other part, over what
gauge and colour of wire. It answers in JSON, and the model server is
given a schema built from THIS project's parts, under which a part that
is not in the brief, or a pin that part does not have, cannot be written
at all. Everything else, the WireViz structure, the connector definitions,
their pin lists, is produced here by plain code from the parts library.

The existing checks still run on the result. A schema guarantees the
shape of an answer, not that it is a sensible harness.
"""

from __future__ import annotations

import json
import re

import yaml

from .parts import Part

GAUGES = [22, 24, 26]
# WireViz's own two-letter colour codes.
COLOURS = {"red": "RD", "black": "BK", "yellow": "YE", "green": "GN",
           "blue": "BU", "white": "WH", "orange": "OG", "violet": "VT"}
MAX_CABLES = 12
MAX_WIRES = 8
# A pin on a part whose pins the library does not list (most dev boards):
# the model names it, but only as a short plain token.
FREE_PIN = "^[A-Za-z0-9_+]{1,12}$"
# The same, for a microcontroller: a supply pin by name, anything else by
# its GPIO number. D135: the 4B model wired an ESP32 as SCL and SDA, which
# FREE_PIN allows, every electrical check passed it, and the run failed
# at the firmware step 26 minutes in, where a pin constant needs a
# number. What firmware.py can read is what may be written here.
# One spelling only (D144): with GPIO, GP, IO and D all allowed, the model
# wired GPIO0 to one part and D0 to another, the same pin under two names,
# and no check could see that they were one.
MCU_PIN = "^(3V3|5V|VIN|VBUS|GND|GPIO[0-9]{1,2})$"
# Parts whose current comes in surges: a motor starting or stalling, a
# coil pulling in, lights at full white, an amplifier on a loud note.
SURGING = ("actuator", "driver", "audio")
POWER_NAMES = re.compile(r"^(\+?\d+V\d*|VCC|VDD|VIN|VBUS|VBAT|GND|AGND|DGND|3V3|5V)$", re.I)


def supply_pin_volts(part: Part, pin: str) -> float | None:
    """What a microcontroller board's supply pin gives, read from its name.
    None for ground and for anything that is not a supply pin. VIN is the
    board's input, so it is at the highest supply the library lists for
    the board."""
    name = pin.upper().lstrip("+")
    if name in ("3V3", "3V"):
        return 3.3
    if name in ("5V", "VBUS"):
        return 5.0
    if name == "VIN":
        return max(part.supply_v) if part.supply_v else None
    return None


def takes(part: Part) -> str:
    """'3.3 V' or '3.3 to 5 V': what the library says a part runs from."""
    if not part.supply_v:
        return ""
    low, high = min(part.supply_v), max(part.supply_v)
    return f"{low:g} V" if low == high else f"{low:g} to {high:g} V"


def runs_from(part: Part, volts: float) -> bool:
    return bool(part.supply_v) and \
        min(part.supply_v) - 0.35 <= volts <= max(part.supply_v) + 0.35


def _joined_supplies(doc: dict, parts: list[Part]) -> bool:
    """Does any net join two board supply pins of different voltages?"""
    from . import schematic
    by_ref = {p.ref: p for p in parts}
    for members in schematic.nets(doc, parts).values():
        volts = {supply_pin_volts(by_ref[ref], pin) for ref, pin in members
                 if ref in by_ref and by_ref[ref].category == "mcu"}
        if len(volts - {None}) > 1:
            return True
    return False


def fix_supply_pins(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """Move a part's supply wire to the board's 3V3 pin where the pin the
    model chose would give it a voltage it cannot take and 3.3 V suits it.

    Not left to the model. On the real laptop it put a 3.3 V reader on
    VIN, was told so in as many words, and did it again. Which pin gives
    what, and what each part runs from, are both known here. Only a wire
    that runs straight from the board's supply pin to the part is moved,
    and not if moving it would join two supplies; anything else is left
    for the supply check to fail.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    out, notes = copy.deepcopy(doc), []
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None:
            continue
        for w in cable.get("wires") or []:
            if not isinstance(w, dict):
                continue
            for board, bkey, part, pkey in ((a, "from_pin", b, "to_pin"),
                                            (b, "to_pin", a, "from_pin")):
                if board.category != "mcu" or part.category in ("mcu", "power"):
                    continue
                was, pin = w.get(bkey), part.pin(str(w.get(pkey)))
                volts = supply_pin_volts(board, str(was))
                if pin is None or pin.function != "power" or volts is None:
                    continue
                if runs_from(part, volts) or not runs_from(part, 3.3):
                    continue
                w[bkey] = "3V3"
                if _joined_supplies(out, parts):
                    w[bkey] = was                      # would short two supplies
                    continue
                notes.append(f"{part.ref}.{pin.name} was wired to {board.ref}.{was} "
                             f"({volts:g} V). The part runs from {takes(part)}, so "
                             f"Nemo moved that wire to {board.ref}.3V3.")
    return out, notes


def board_supplies(board: Part) -> list[tuple[str, float]]:
    """(pin, volts) for each supply pin of a board, lowest voltage first.
    From its pin list where it has one; otherwise the two every board in
    the library has, 3V3 and VIN."""
    listed = [(p.name, float(p.voltage)) for p in board.pins
              if p.function == "power" and p.voltage]
    if not listed:
        listed = [("3V3", 3.3)]
        if board.supply_v:
            listed.append(("VIN", float(max(board.supply_v))))
    return sorted(listed, key=lambda t: t[1])


def _side(part: Part, direction: str) -> tuple[str, str] | None:
    """(supply pin, its ground pin) on the in or the out side of a power
    part: the ground pin listed straight after that supply pin."""
    for i, pin in enumerate(part.pins):
        if pin.function == "power" and pin.direction == direction:
            gnd = next((g.name for g in part.pins[i + 1:] if g.function == "gnd"), None) \
                or next((g.name for g in part.pins if g.function == "gnd"), None)
            return (pin.name, gnd) if gnd else None
    return None


def supply_chain(parts: list[Part]) -> list[Part] | None:
    """The power parts in the order current flows through them, where it
    is an arrangement this understands: one cell, at most one protection
    or charger board, and one converter whose output is the voltage the
    board's highest supply pin takes. None for anything else, and None if
    the project has no power parts at all."""
    boards = [p for p in parts if p.category == "mcu"]
    power = [p for p in parts if p.category == "power"]
    if len(boards) != 1 or not power:
        return None
    cells = [p for p in power if _side(p, "out") and not _side(p, "in") and not p.output_v]
    guards = [p for p in power if _side(p, "out") and _side(p, "in") and not p.output_v]
    convs = [p for p in power if _side(p, "out") and _side(p, "in") and p.output_v]
    if len(cells) != 1 or len(guards) > 1 or len(convs) != 1 \
            or len(cells) + len(guards) + len(convs) != len(power):
        return None
    top = board_supplies(boards[0])[-1]
    if top[0].upper() == "VBUS":
        # D163: VBUS is the USB socket's own 5 V, which comes OUT of that
        # pin. A converter wired to it meets the computer's supply the
        # moment a cable is plugged in. Such a board takes a battery on
        # another pin, which the library does not describe: not wired.
        return None
    out_pin = convs[0].pin(_side(convs[0], "out")[0])
    if not out_pin.voltage or abs(float(out_pin.voltage) - top[1]) > 0.35:
        return None
    return cells + guards + convs


def chain_cables(chain: list[Part], board: Part) -> list[dict]:
    """The cables of a supply chain, each stage's output side to the next
    one's input side, and the last to the board. Positive to positive and
    each stage's own negative to the next: a protection board switches the
    negative side, so the cell's negative must never reach ground direct."""
    cables = []
    for a, b in zip(chain, chain[1:]):
        (ap, ag), (bp, bg) = _side(a, "out"), _side(b, "in")
        cables.append({"from": a.ref, "to": b.ref, "gauge_awg": GAUGES[0], "length_mm": 60,
                       "wires": [{"from_pin": ap, "to_pin": bp, "colour": "red"},
                                 {"from_pin": ag, "to_pin": bg, "colour": "black"}]})
    last = chain[-1]
    lp, lg = _side(last, "out")
    cables.append({"from": last.ref, "to": board.ref, "gauge_awg": GAUGES[0], "length_mm": 80,
                   "wires": [{"from_pin": lp, "to_pin": board_supplies(board)[-1][0],
                              "colour": "red"},
                             {"from_pin": lg, "to_pin": "GND", "colour": "black"}]})
    return cables


def wire_power(doc: dict, parts: list[Part], asked: bool = True) -> tuple[dict, list[str]]:
    """Every part's power and ground, wired by code: see wire_loads for
    the parts that draw power, and here for where it comes from.

    D150. With a battery in the project the supply is a chain: cell,
    protection, converter, board. That order is in the parts library (which
    side of each part is its input, which its output, and at what voltage),
    so it is wired here and the power parts are never offered to the model.
    Where the arrangement is not one this understands, the power parts are
    left unwired and the step says so; it does not guess.
    """
    import copy
    power = [p for p in parts if p.category == "power" and p.pins]
    if not power:
        return wire_loads(doc, parts, asked)
    boards = [p for p in parts if p.category == "mcu"]
    chain = supply_chain(parts)
    if chain is None or len(boards) != 1:
        fixed, notes = fix_supply_pins(doc, parts)
        return fixed, notes + [
            "Nemo does not wire this supply: it understands one cell, at most one "
            "protection or charger board, and one converter to the board's supply "
            "voltage. " + ", ".join(p.ref for p in power) + " are left for you to wire."]
    refs = {p.ref for p in power}
    bare = copy.deepcopy(doc)
    if isinstance(bare.get("cables"), list):
        bare["cables"] = [c for c in bare["cables"] if not isinstance(c, dict)
                          or not ({c.get("from"), c.get("to")} & refs)]
    out, notes = wire_loads(bare, [p for p in parts if p.category != "power"], asked)
    out.setdefault("cables", []).extend(chain_cables(chain, boards[0]))
    if out != doc:
        notes.append(
            "The supply is wired by Nemo, in order: " + " to ".join(p.ref for p in chain)
            + f" to {boards[0].ref}.{board_supplies(boards[0])[-1][0]}. The cell's negative "
            "goes only to the next board in that chain, never straight to ground.")
    return out, notes


def wire_loads(doc: dict, parts: list[Part], asked: bool = True) -> tuple[dict, list[str]]:
    """The model's signal wires, with every part's power and ground wired
    by code. Returns (connections, what was changed and why).

    D145. Shown a board's pins, the 1.7B model put a 5 V ring on the 3.3 V
    pin, wired VIN to a ground pin, and ran three spare GPIOs to ground
    (real run, AH531). None of that is a design choice. Which supply pin
    suits a part is in the library, and its ground goes to ground. So every
    wire the model ran to a supply or ground pin is set aside, and each part
    gets one wire per supply pin, to the pin the model chose if the part can
    take it and otherwise the lowest that it can, and one per ground pin.

    Only for one microcontroller board and no battery, charger or
    converter: with those the supply is a chain this does not understand,
    and the narrower fix_supply_pins is used instead.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    boards = [p for p in parts if p.category == "mcu"]
    if len(boards) != 1 or any(p.category == "power" for p in parts):
        return fix_supply_pins(doc, parts)
    board = boards[0]
    supplies = dict(board_supplies(board))

    def rail(part: Part, name) -> str:
        """'power', 'gnd' or '' for one end of a wire."""
        name = str(name)
        if part.ref == board.ref:
            if name in supplies or supply_pin_volts(board, name) is not None:
                return "power"
            return "gnd" if POWER_NAMES.match(name) else ""
        pin = part.pin(name)
        return pin.function if pin is not None and pin.function in ("power", "gnd") else ""

    out = copy.deepcopy(doc)
    chosen: dict[tuple[str, str], str] = {}      # (part, supply pin) -> board pin it was on
    grounded: set[tuple[str, str]] = set()
    odd: list[str] = []
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None:
            continue
        keep = []
        for w in cable["wires"]:
            if not isinstance(w, dict):
                keep.append(w)
                continue
            ra, rb = rail(a, w.get("from_pin")), rail(b, w.get("to_pin"))
            if not (ra or rb):
                keep.append(w)                       # a signal wire: the model's
                continue
            ends = ((a, str(w.get("from_pin")), ra), (b, str(w.get("to_pin")), rb))
            on_board = [e for e in ends if e[0].ref == board.ref]
            on_part = [e for e in ends if e[0].ref != board.ref]
            if len(on_board) == 1 and len(on_part) == 1 and ra == rb:
                (_, bpin, _), (part, ppin, kind) = on_board[0], on_part[0]
                if kind == "power":
                    chosen.setdefault((part.ref, part.pin(ppin).name), bpin)
                else:
                    grounded.add((part.ref, part.pin(ppin).name))
            elif not (len(on_part) == 2 and ra == rb):   # not a supply passed module to module
                odd.append(f"{a.ref}.{ends[0][1]} to {b.ref}.{ends[1][1]}")
        cable["wires"] = keep

    notes: list[str] = []
    fed: list[str] = []
    for part in parts:
        if part.ref == board.ref or not part.pins:
            continue
        new = []
        for pin in part.pins:
            if pin.function == "power":
                was = chosen.get((part.ref, pin.name))
                was_v = supplies.get(was) if was in supplies else (
                    supply_pin_volts(board, was) if was else None)
                # With no usable choice from the model: the lowest pin that
                # suits, except for a part whose current comes in surges
                # (motor, relay, lights, amplifier), which gets the highest.
                # D166: asked for nothing, the first audio design had a
                # 700 mA amplifier on the board's 3.3 V regulator.
                order = list(supplies.items())
                if part.category in SURGING:
                    order.reverse()
                use = was if was and was_v is not None and runs_from(part, was_v) else next(
                    (name for name, volts in order if runs_from(part, volts)), None)
                if use is None:
                    use = was                        # nothing suits: leave it for the check
                    if use is None:
                        continue
                elif was is None and not asked:
                    fed.append(f"{part.ref}.{pin.name} from {use}")
                elif was is None:
                    notes.append(f"{part.ref}.{pin.name} had no supply wire from the board, "
                                 f"so Nemo wired it to {board.ref}.{use}.")
                elif use != was:
                    notes.append(f"{part.ref}.{pin.name} was wired to {board.ref}.{was} "
                                 f"({was_v:g} V). The part runs from {takes(part)}, so "
                                 f"Nemo moved that wire to {board.ref}.{use}.")
                new.append((use, pin.name, "red"))
            elif pin.function == "gnd":
                if (part.ref, pin.name) not in grounded and asked:
                    notes.append(f"{part.ref}.{pin.name} had no ground wire from the board, "
                                 "so Nemo added one.")
                new.append(("GND", pin.name, "black"))
        if not new:
            continue
        cables = out.setdefault("cables", [])
        home = next((c for c in cables if isinstance(c, dict)
                     and {c.get("from"), c.get("to")} == {board.ref, part.ref}), None)
        if home is None:
            home = {"from": board.ref, "to": part.ref, "gauge_awg": GAUGES[0],
                    "length_mm": 100, "wires": []}
            cables.append(home)
        flip = home.get("from") != board.ref
        home["wires"] = [{"from_pin": p if flip else b, "to_pin": b if flip else p,
                          "colour": colour} for b, p, colour in new] + list(home.get("wires") or [])
    if isinstance(out.get("cables"), list):
        out["cables"] = [c for c in out["cables"]
                         if not isinstance(c, dict) or c.get("wires")]
    if fed:
        # D164: the model was not asked for these, so there is nothing to
        # say it left out. One line for the owner, not one per pin.
        notes.append(f"Power and ground wired by Nemo from the parts library, each part to "
                     f"{board.ref}: " + "; ".join(fed) + "; every ground to GND.")
    if odd:
        notes.append(f"Set aside {len(odd)} wire(s) the model ran to supply or ground pins "
                     "where none belongs: " + "; ".join(odd[:5])
                     + ("; ..." if len(odd) > 5 else "")
                     + ". Power and ground are wired by Nemo from the parts library.")
    return out, notes


def signal_level(part: Part, pin: str) -> tuple[float, str] | None:
    """(volts, direction) of a signal pin, or None if it is not a signal
    or the library gives it no voltage. A pin's own voltage where it has
    one, else the part's logic voltage."""
    found = part.pin(pin)
    if found is not None:
        if found.function not in ("io", "bus"):
            return None
        volts = found.voltage or part.logic_v
        return (float(volts), found.direction) if volts else None
    if part.pins or POWER_NAMES.match(pin) or not part.logic_v:
        return None
    return float(part.logic_v), ""                   # a board with no pin list


def drop_overvoltage(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """Set aside every wire that runs an output straight into a pin made
    for a lower voltage, and say so.

    D147. In the first design of the tilt lamp to pass every check, the
    LED ring's DOUT, a 5 V output, was wired to a 3.3 V pin of the board.
    That can damage the pin, and no retry was going to notice it. Only
    where the library says the higher pin is an output: the other way
    round (a 3.3 V pin driving a 5 V input) harms nothing and is left for
    the levels check to report.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    out, notes = copy.deepcopy(doc), []
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None:
            continue
        keep = []
        for w in cable["wires"]:
            ends = [(a, str(w.get("from_pin"))), (b, str(w.get("to_pin")))] \
                if isinstance(w, dict) else []
            levels = [signal_level(part, pin) for part, pin in ends]
            dropped = False
            if len(levels) == 2 and all(levels):
                for hi, lo in ((0, 1), (1, 0)):
                    if levels[hi][1] == "out" and levels[hi][0] - levels[lo][0] > 0.35 \
                            and levels[hi][0] > pin_tolerates(*ends[lo]) + 0.35:
                        notes.append(
                            f"Set aside the wire from {ends[hi][0].ref}.{ends[hi][1]} to "
                            f"{ends[lo][0].ref}.{ends[lo][1]}: it is a {levels[hi][0]:g} V "
                            f"output and that pin is made for {levels[lo][0]:g} V. If the "
                            "signal is needed it must go through a level shifter.")
                        dropped = True
                        break
            if not dropped:
                keep.append(w)
        cable["wires"] = keep
    if isinstance(out.get("cables"), list):
        out["cables"] = [c for c in out["cables"] if not isinstance(c, dict) or c.get("wires")]
    return out, notes


def pin_tolerates(part: Part, pin: str) -> float:
    """The highest voltage a signal pin may be driven at: what the library
    says it tolerates, else the level it works at."""
    found = part.pin(pin)
    level = signal_level(part, pin)
    return float((found.tolerates if found is not None and found.tolerates else None)
                 or (level[0] if level else 0.0))


def spread_shared_pins(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """Give each signal its own pin of the board where the model put two
    different ones on the same pin, and say so.

    D149. Told "GPIO4 is wired to mpu6050.SDA and ws2812b_ring8.DIN: one
    microcontroller pin cannot carry 2 different signals", the 1.7B model
    answered the same again (real run, AH531), as it had with a supply pin.
    On a board whose pins the library lists, the listed GPIOs are the ones
    with no special duty, so which free one a signal moves to is not a
    design decision. The first signal on a pin keeps it; pins of the same
    name on several parts are a bus and stay together.

    Only for one board that has a pin list. If no pin is free, nothing is
    moved and the check for one pin carrying two signals fails as before.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    boards = [p for p in parts if p.category == "mcu"]
    if len(boards) != 1 or not boards[0].pins:
        return doc, []
    board = boards[0]
    gpios = [p.name for p in board.pins if p.function == "io"]
    out, notes = copy.deepcopy(doc), []
    uses: dict[str, list[tuple[dict, str, Part, str]]] = {}
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None or (a.ref == board.ref) == (b.ref == board.ref):
            continue
        key, far_key, far = ("from_pin", "to_pin", b) if a.ref == board.ref \
            else ("to_pin", "from_pin", a)
        for w in cable["wires"]:
            if not isinstance(w, dict) or str(w.get(key)) not in gpios:
                continue
            pin = far.pin(str(w.get(far_key)))
            if pin is not None and pin.function in ("io", "bus"):
                uses.setdefault(str(w[key]), []).append((w, key, far, pin.name))
    free = [g for g in gpios if g not in uses]
    for pin, wired in uses.items():
        kept = wired[0][3].upper()
        moved_to: dict[str, str] = {}
        for w, key, far, name in wired[1:]:
            if name.upper() == kept:
                continue                              # the same line of a bus
            if name.upper() not in moved_to:
                if not free:
                    break
                moved_to[name.upper()] = free.pop(0)
            w[key] = moved_to[name.upper()]
            notes.append(f"{board.ref}.{pin} was wired to both {wired[0][2].ref}."
                         f"{wired[0][3]} and {far.ref}.{name}. One pin cannot carry two "
                         f"signals, so Nemo moved {far.ref}.{name} to "
                         f"{board.ref}.{w[key]}.")
    return out, notes


def chosen_by_model(parts: list[Part]) -> list[Part]:
    """The parts the model is asked to wire: all but a level shifter and
    the power parts, which code wires or declines to (D150).

    Offered the shifter's fourteen pins like any other part's, the 1.7B
    model wired one of its INPUTS to the LED ring's data input and left
    the ring with nothing driving it (real run, AH531). Where a shifter
    goes follows from the voltages on the wires, which code knows.
    """
    return [p for p in parts if not p.gates and not (p.category == "power" and p.pins)]


def without_shifter_wires(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """Drop any cable the model ran to a level shifter. Under the schema
    it cannot write one; a server that ignores the schema can."""
    import copy
    gated = {p.ref for p in parts if p.gates}
    out = copy.deepcopy(doc)
    cables = out.get("cables")
    if not gated or not isinstance(cables, list):
        return out, []
    keep = [c for c in cables if not isinstance(c, dict)
            or not ({c.get("from"), c.get("to")} & gated)]
    notes = []
    if len(keep) != len(cables):
        notes.append(f"Set aside {len(cables) - len(keep)} cable(s) the model ran to "
                     f"{', '.join(sorted(gated))}: a level shifter is wired by Nemo.")
    out["cables"] = keep
    return out, notes


def route_through_shifter(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """Where the board drives an input that works at a higher voltage, and
    the project has a level shifter, send the signal through it.

    D148. A 3.3 V pin driving a 5 V input is the usual way an LED ring or a
    servo is wired, and it is marginal: the ring's own note says its data
    line wants 3.5 V. With a shifter in the parts list, each such wire is
    replaced by one from the board to a gate's input and one from the
    gate's output to the part. Every enable pin, and the input of every
    gate left over, is tied to ground: the datasheet's rule for unused
    inputs, and what switches a used gate on.

    One board only; and only wires the library shows to be INTO a
    higher-voltage input. Without a shifter in the project nothing is
    changed, and the levels check lists the wire for a person.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    boards = [p for p in parts if p.category == "mcu"]
    shifters = [p for p in parts if p.gates]
    if len(boards) != 1 or not shifters:
        return doc, []
    board, shifter = boards[0], shifters[0]
    out, notes = copy.deepcopy(doc), []
    free = [dict(g) for g in shifter.gates]
    via_in, via_out = [], []                 # (board pin, gate in), (gate out, part, pin)
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None or shifter.ref in (a.ref, b.ref):
            continue
        keep = []
        for w in cable["wires"]:
            moved = False
            if isinstance(w, dict):
                ends = {a.ref: str(w.get("from_pin")), b.ref: str(w.get("to_pin"))}
                other = b if a.ref == board.ref else a if b.ref == board.ref else None
                if other is not None and other.ref != board.ref:
                    drive = signal_level(board, ends[board.ref])
                    load = signal_level(other, ends[other.ref])
                    if (drive and load and load[1] == "in" and load[0] - drive[0] > 0.35):
                        gate_in = signal_level(shifter, str(free[0]["in"])) if free else None
                        if not free:
                            notes.append(
                                f"{board.ref}.{ends[board.ref]} drives {other.ref}."
                                f"{ends[other.ref]}, a {load[0]:g} V input, and "
                                f"{shifter.ref} has no gate left for it.")
                        elif gate_in and abs(gate_in[0] - drive[0]) <= 0.35:
                            gate = free.pop(0)
                            via_in.append((ends[board.ref], str(gate["in"])))
                            via_out.append((str(gate["out"]), other.ref, ends[other.ref]))
                            notes.append(
                                f"{board.ref}.{ends[board.ref]} ({drive[0]:g} V) drives "
                                f"{other.ref}.{ends[other.ref]}, a {load[0]:g} V input, so "
                                f"Nemo routed it through {shifter.ref}: in at "
                                f"{gate['in']}, out at {gate['out']}.")
                            moved = True
            if not moved:
                keep.append(w)
        cable["wires"] = keep

    cables = out.setdefault("cables", [])
    # A gate input that already carries a signal, from this pass or an
    # earlier one, must not also be tied to ground.
    used_in = {g for _, g in via_in}
    for c in cables:
        if isinstance(c, dict) and shifter.ref in (c.get("from"), c.get("to")):
            key, far = ("to_pin", "from_pin") if c.get("to") == shifter.ref \
                else ("from_pin", "to_pin")
            used_in |= {str(w.get(key)) for w in c.get("wires") or []
                        if isinstance(w, dict) and str(w.get(far)) != "GND"}
    straps = [str(g["enable_low"]) for g in shifter.gates if g.get("enable_low")]
    straps += [str(g["in"]) for g in shifter.gates if str(g["in"]) not in used_in]
    home = next((c for c in cables if isinstance(c, dict)
                 and (c.get("from"), c.get("to")) == (board.ref, shifter.ref)), None)
    if home is None:
        home = {"from": board.ref, "to": shifter.ref, "gauge_awg": GAUGES[0],
                "length_mm": 60, "wires": []}
        cables.append(home)
    have = {(w.get("from_pin"), w.get("to_pin")) for w in home["wires"] if isinstance(w, dict)}
    for pair, colour in ([(p, "white") for p in via_in] + [(("GND", s), "black") for s in straps]):
        if pair not in have:
            home["wires"].append({"from_pin": pair[0], "to_pin": pair[1], "colour": colour})
    for gate_out, ref, pin in via_out:
        link = next((c for c in cables if isinstance(c, dict)
                     and (c.get("from"), c.get("to")) == (shifter.ref, ref)), None)
        if link is None:
            link = {"from": shifter.ref, "to": ref, "gauge_awg": GAUGES[0],
                    "length_mm": 60, "wires": []}
            cables.append(link)
        link["wires"].append({"from_pin": gate_out, "to_pin": pin, "colour": "white"})
    cables[:] = [c for c in cables if not isinstance(c, dict) or c.get("wires")]
    return out, notes


def contact_pins(part: Part) -> list[str]:
    """The pins of a part's switched side: a relay's NO, NC and COM. They
    are isolated from the circuit Nemo designs and may carry anything."""
    return [p.name for p in part.pins if p.function == "contact"]


def without_contact_wires(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """Set aside every wire to the switched side of a relay, and say so.

    D159. The contacts were in the library as plain signal pins, so the
    model was offered them, and on the first real design with a relay it
    ran NO and COM to the servo's supply and ground pins. Those two were
    caught only because their other ends were supply pins; a contact wired
    to a GPIO would have passed every check. What a relay switches is not
    in the parts list, and can be at a voltage nothing here is made for.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    out, gone = copy.deepcopy(doc), []
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None:
            continue
        keep = []
        for w in cable["wires"]:
            ends = [(a, str(w.get("from_pin"))), (b, str(w.get("to_pin")))] \
                if isinstance(w, dict) else []
            if any(pin.lower() in (c.lower() for c in contact_pins(part))
                   for part, pin in ends):
                gone.append(f"{a.ref}.{ends[0][1]} to {b.ref}.{ends[1][1]}")
            else:
                keep.append(w)
        cable["wires"] = keep
    if isinstance(out.get("cables"), list):
        out["cables"] = [c for c in out["cables"] if not isinstance(c, dict) or c.get("wires")]
    notes = []
    if gone:
        notes.append(f"Set aside {len(gone)} wire(s) the model ran to a relay's switched "
                     "side: " + "; ".join(gone[:5]) + ("; ..." if len(gone) > 5 else "")
                     + ". Nemo does not wire that side.")
    return out, notes


def _is_rail(part: Part, name: str) -> bool:
    """Is this end of a wire a supply or ground pin?"""
    if part.category == "mcu":
        return bool(POWER_NAMES.match(name))
    pin = part.pin(name)
    return pin is not None and pin.function in ("power", "gnd")


def recolour_signals(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """No signal wire in red or black: those are the supply's colours.

    D161. In the first real design with a servo the model coloured its
    signal wire red, in the same three-wire cable as the red 5 V wire.
    Two reds at one connector, one of them 5 V, is how a supply gets
    pushed onto a signal pin at the bench. The colour is not a design
    choice worth a retry: code gives the wire one the cable does not use.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    out, notes = copy.deepcopy(doc), []
    spare = [c for c in COLOURS if c not in ("red", "black")]
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None:
            continue
        used = {str(w.get("colour", "")).lower() for w in cable["wires"] if isinstance(w, dict)}
        for w in cable["wires"]:
            if not isinstance(w, dict):
                continue
            had = str(w.get("colour", "")).lower()
            if had not in ("red", "black", ""):
                continue
            if _is_rail(a, str(w.get("from_pin"))) or _is_rail(b, str(w.get("to_pin"))):
                continue
            new = next((c for c in spare if c not in used), spare[len(used) % len(spare)])
            if had:                                  # a wire with no colour was not asked for one
                notes.append(f"The signal wire from {a.ref}.{w.get('from_pin')} to "
                             f"{b.ref}.{w.get('to_pin')} was {w.get('colour')}, a supply "
                             f"colour, so Nemo made it {new}.")
            w["colour"] = new
            used.add(new)
    return out, notes


def pin_loads(pairs_nets: list[set], parts: list[Part]) -> list[tuple[str, str, list[Part]]]:
    """(board, supply pin, the parts fed from it) for each supply pin of a
    microcontroller board that feeds anything. From nets of (ref, pin)."""
    by_ref = {p.ref: p for p in parts}
    out = []
    for net in pairs_nets:
        feeds = sorted((ref, name) for ref, name in net
                       if ref in by_ref and by_ref[ref].category == "mcu"
                       and supply_pin_volts(by_ref[ref], str(name)) is not None)
        if not feeds:
            continue
        loads = []
        for ref, name in sorted(net, key=lambda e: (str(e[0]), str(e[1]))):
            part = by_ref.get(ref)
            pin = part.pin(str(name)) if part is not None else None
            if pin is not None and pin.function == "power" \
                    and part.category not in ("mcu", "power") and part not in loads:
                loads.append(part)
        if loads:
            out.append((feeds[0][0], feeds[0][1], loads))
    return out


class HarnessError(ValueError):
    """The model's answer cannot be turned into a harness. For the owner."""


def power_by_code(parts: list[Part]) -> bool:
    """Does code wire every supply and ground wire of this project, so that
    the model need not be asked for any? One board, and either no battery
    parts or a supply chain wire_power understands. See wire_power."""
    if len([p for p in parts if p.category == "mcu"]) != 1:
        return False
    if not [p for p in parts if p.category == "power" and p.pins]:
        return True
    return supply_chain(parts) is not None


SIGNAL_MCU_PIN = "^GPIO[0-9]{1,2}$"
_HIDDEN = ("contact", "speaker", "usb_dm", "usb_dp")
_RAILS = ("power", "gnd")


def offered_pins(part: Part, signals_only: bool = False) -> list[str]:
    """The pins of a part the model may name: never a relay's contacts
    (D159) or a speaker terminal (D166), and with signals_only never a
    supply or ground pin (D164) or one the part works without (D166)."""
    skip = _HIDDEN + (_RAILS if signals_only else ())
    return [p.name for p in part.pins
            if p.function not in skip and not (signals_only and p.optional)]


def left_optional(parts: list[Part]) -> list[str]:
    """'ref PIN, PIN' for each part with pins it works without."""
    out = []
    for p in parts:
        names = [x.name for x in p.pins if x.optional]
        if names:
            out.append(f"{p.ref} {', '.join(names)}")
    return out


def speaker_pins(part: Part) -> list[str]:
    return [p.name for p in part.pins if p.function == "speaker"]


def wire_speakers(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """A speaker's two terminals go to an amplifier's two outputs, and to
    nothing else. Wired here, with whatever the model ran to any of those
    pins set aside.

    D166. The amplifier's entry had no output pins, and the speaker's two
    were plain analogue pins, so on the first real audio design the model
    wired the speaker to two GPIOs of the board. It passed the check for
    shared pins only by failing it for another reason. Which part drives
    a speaker is in the library: the one with speaker outputs.

    Only where there is exactly one speaker and one part that can drive
    it. Anything else is left unwired, and said.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    sinks = [p for p in parts if p.pins and len(speaker_pins(p)) == len(p.pins)]
    sources = [p for p in parts if p not in sinks and len(speaker_pins(p)) >= 2]
    if not sinks and not sources:
        return doc, []
    out, gone = copy.deepcopy(doc), []
    pair = (sources[0], sinks[0]) if len(sinks) == 1 and len(sources) == 1 else None
    want = set()
    if pair:
        want = {(pair[0].ref, a, pair[1].ref, b)
                for a, b in zip(speaker_pins(pair[0]), speaker_pins(pair[1]))}
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None:
            continue
        keep = []
        for w in cable["wires"]:
            if not isinstance(w, dict):
                keep.append(w)
                continue
            fp, tp = str(w.get("from_pin")), str(w.get("to_pin"))
            loud = (a.pin(fp) is not None and a.pin(fp).function == "speaker") or \
                   (b.pin(tp) is not None and b.pin(tp).function == "speaker")
            if not loud:
                keep.append(w)
            elif (a.ref, fp, b.ref, tp) not in want and (b.ref, tp, a.ref, fp) not in want:
                gone.append(f"{a.ref}.{fp} to {b.ref}.{tp}")
        cable["wires"] = keep
    if isinstance(out.get("cables"), list):
        out["cables"] = [c for c in out["cables"] if not isinstance(c, dict) or c.get("wires")]
    notes = []
    if gone:
        notes.append(f"Set aside {len(gone)} wire(s) the model ran to a speaker terminal or "
                     "an amplifier's output: " + "; ".join(gone[:5])
                     + ("; ..." if len(gone) > 5 else "") + ".")
    if pair:
        src, spk = pair
        out.setdefault("cables", []).append({
            "from": src.ref, "to": spk.ref, "gauge_awg": GAUGES[0], "length_mm": 100,
            "wires": [{"from_pin": a, "to_pin": b, "colour": c} for (a, b), c in
                      zip(zip(speaker_pins(src), speaker_pins(spk)), ("white", "violet"))]})
        notes.append(f"{spk.ref} is wired by Nemo to {src.ref} "
                     f"({' and '.join(speaker_pins(src)[:2])}), the part that drives a "
                     "speaker. Neither wire goes to ground or to the board.")
    else:
        notes.append(", ".join(p.ref for p in sinks + sources) + ": not wired to each other "
                     f"by Nemo. It wires one speaker to one part that can drive it, and here "
                     f"there are {len(sinks)} and {len(sources)}.")
    return out, notes


USB_DATA = ("usb_dm", "usb_dp")


def usb_pins(part: Part) -> dict[str, str]:
    """{"usb_dm": pin name, "usb_dp": pin name} for a part with both."""
    found = {p.function: p.name for p in part.pins if p.function in USB_DATA}
    return found if len(found) == 2 else {}


def wire_usb(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """A USB socket's D- and D+ go to the board's own USB pins, and to
    nothing else. Wired here, never offered to the model, with whatever
    it ran to any of those pins set aside.

    Owner, 2026-10-29 (the wireless dock): USB data is not a choice. Only
    the chip's USB pins carry it, and the library says which they are.
    Only where there is exactly one board with USB pins and one socket.
    The socket's VBUS and GND are supply pins: wire_loads wires them.
    """
    import copy
    with_usb = [p for p in parts if usb_pins(p)]
    if not with_usb:
        return doc, []
    boards = [p for p in with_usb if p.category == "mcu"]
    sockets = [p for p in with_usb if p.category != "mcu"]
    by_ref = {p.ref: p for p in parts}
    out, gone = copy.deepcopy(doc), []
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None:
            continue
        keep = []
        for w in cable["wires"]:
            ends = ((a, str(w.get("from_pin"))), (b, str(w.get("to_pin")))) \
                if isinstance(w, dict) else ()
            if any(p.pin(n) is not None and p.pin(n).function in USB_DATA for p, n in ends):
                gone.append(f"{a.ref}.{ends[0][1]} to {b.ref}.{ends[1][1]}")
            else:
                keep.append(w)
        cable["wires"] = keep
    if isinstance(out.get("cables"), list):
        out["cables"] = [c for c in out["cables"] if not isinstance(c, dict) or c.get("wires")]
    notes = []
    if gone:
        notes.append(f"Set aside {len(gone)} wire(s) the model ran to a USB data pin: "
                     + "; ".join(gone[:5]) + ("; ..." if len(gone) > 5 else "") + ".")
    if len(boards) == 1 and len(sockets) == 1:
        board, socket = boards[0], sockets[0]
        b, s = usb_pins(board), usb_pins(socket)
        out.setdefault("cables", []).append({
            "from": board.ref, "to": socket.ref, "gauge_awg": GAUGES[0], "length_mm": 100,
            "wires": [{"from_pin": b[f], "to_pin": s[f], "colour": c}
                      for f, c in (("usb_dm", "white"), ("usb_dp", "green"))]})
        notes.append(f"{socket.ref} is wired by Nemo to {board.ref}'s USB pins "
                     f"({b['usb_dm']} to {s['usb_dm']}, {b['usb_dp']} to {s['usb_dp']}). "
                     "Keep the two wires short and twisted together.")
    else:
        notes.append(", ".join(p.ref for p in with_usb) + ": USB data not wired by Nemo. "
                     f"It wires one socket to one board with USB pins, and here there are "
                     f"{len(sockets)} and {len(boards)}.")
    return out, notes


def _pin_schema(part: Part, signals_only: bool = False) -> dict:
    names = offered_pins(part, signals_only)
    if names or part.pins:
        return {"enum": names}
    if signals_only and part.category == "mcu":
        return {"type": "string", "pattern": SIGNAL_MCU_PIN}
    return {"type": "string", "pattern": free_pin(part)}


def free_pin(part: Part) -> str:
    """The pattern a pin name must match on a part with no pin list."""
    return MCU_PIN if part.category == "mcu" else FREE_PIN


def harness_schema(parts: list[Part], signals_only: bool = False) -> dict:
    """A JSON schema for this project's harness and no other.

    One alternative per ordered pair of parts, so that a wire's two pins
    are each limited to the pins of the part at that end.

    signals_only (D164): for a project whose power code wires. No supply
    or ground pin can be named, a part with no other pin is not offered,
    and a cable is its two parts and its wires, a wire its two pins. The
    first five-part design asked the long way did not finish in the
    thirty minutes a step is allowed: most of what the model was writing
    was supply wires, colours, gauges and lengths that code then replaced.
    """
    if signals_only:
        wired = [p for p in parts if not p.pins or offered_pins(p, True)]
        pairs = [{
            "type": "object", "additionalProperties": False,
            "required": ["from", "to", "wires"],
            "properties": {
                "from": {"const": a.ref}, "to": {"const": b.ref},
                "wires": {
                    "type": "array", "minItems": 1, "maxItems": MAX_WIRES,
                    "items": {"type": "object", "additionalProperties": False,
                              "required": ["from_pin", "to_pin"],
                              "properties": {"from_pin": _pin_schema(a, True),
                                             "to_pin": _pin_schema(b, True)}}}},
        } for a in wired for b in wired if a.ref != b.ref]
        return {"type": "object", "additionalProperties": False, "required": ["cables"],
                "properties": {"cables": {"type": "array", "minItems": 1,
                                          "maxItems": MAX_CABLES,
                                          "items": {"anyOf": pairs}}}}
    wired = [p for p in parts if not p.pins or offered_pins(p)]    # not a bare speaker (D166)
    pairs = []
    for a in wired:
        for b in wired:
            if a.ref == b.ref:
                continue
            pairs.append({
                "type": "object",
                "additionalProperties": False,
                "required": ["from", "to", "gauge_awg", "length_mm", "wires"],
                "properties": {
                    "from": {"const": a.ref},
                    "to": {"const": b.ref},
                    "gauge_awg": {"enum": GAUGES},
                    "length_mm": {"type": "integer", "minimum": 20, "maximum": 600},
                    "wires": {
                        "type": "array", "minItems": 1, "maxItems": MAX_WIRES,
                        "items": {
                            "type": "object", "additionalProperties": False,
                            "required": ["from_pin", "to_pin", "colour"],
                            "properties": {"from_pin": _pin_schema(a),
                                           "to_pin": _pin_schema(b),
                                           "colour": {"enum": sorted(COLOURS)}},
                        },
                    },
                },
            })
    return {
        "type": "object", "additionalProperties": False, "required": ["cables"],
        "properties": {"cables": {"type": "array", "minItems": 1,
                                  "maxItems": MAX_CABLES,
                                  "items": {"anyOf": pairs}}},
    }


def cable_choices(schema: dict) -> list:
    """The cables a harness schema lets the model write: empty when no
    two parts have a pin left to join (D177)."""
    try:
        return schema["properties"]["cables"]["items"]["anyOf"]
    except (KeyError, TypeError):
        return [None]          # not that kind of schema: something to ask


def join_i2c_bus(doc: dict, parts: list[Part]) -> tuple[dict, list[str]]:
    """Put every I2C part on the first one's SDA/SCL pair of the board, and say so.

    D269. Gemma 4 E4B (trial, 2026-11-11) wired the screen's SDA/SCL to GPIO4/3
    and the BME280's to GPIO6/7. The electrical step passed it, and the firmware
    step stopped: one I2C bus is all the bring-up firmware sets up. Parts on an
    I2C bus share its two lines by design, so which pair the second part uses is
    not a choice: code joins it to the first part's. Only for one board.
    """
    import copy
    by_ref = {p.ref: p for p in parts}
    boards = [p for p in parts if p.category == "mcu"]
    if len(boards) != 1:
        return doc, []
    board = boards[0]
    out, notes = copy.deepcopy(doc), []
    bus: dict[str, str] = {}
    first = None
    for cable in out.get("cables") or []:
        if not isinstance(cable, dict) or not isinstance(cable.get("wires"), list):
            continue
        a, b = by_ref.get(cable.get("from")), by_ref.get(cable.get("to"))
        if a is None or b is None or (a.ref == board.ref) == (b.ref == board.ref):
            continue
        key, far_key, far = ("from_pin", "to_pin", b) if a.ref == board.ref \
            else ("to_pin", "from_pin", a)
        lines = {str(w.get(far_key)).upper(): w for w in cable["wires"]
                 if isinstance(w, dict) and str(w.get(far_key)).upper() in ("SDA", "SCL")}
        if set(lines) != {"SDA", "SCL"}:
            continue
        if not bus:
            bus = {name: str(w.get(key)) for name, w in lines.items()}
            first = far.ref
            continue
        was = {name: str(w.get(key)) for name, w in lines.items()}
        if was == bus:
            continue
        for name, w in lines.items():
            w[key] = bus[name]
        notes.append(f"{far.ref} had SDA/SCL on {board.ref}.{was['SDA']}/{was['SCL']} and "
                     f"{first} on {bus['SDA']}/{bus['SCL']}. Parts on I2C share one bus, so "
                     f"Nemo put {far.ref} on {bus['SDA']}/{bus['SCL']}.")
    return out, notes


def pin_choice_schema(parts: list[Part]) -> dict | None:
    """A schema in which the model can only choose a microcontroller pin
    for each signal pin of each other part, or None where that form does
    not fit (no single board, or nothing to place).

    D171. From the model server's own log of a real run: the answer for
    eight wires was 310 tokens at 0.71 a second, seven minutes of it, and
    most of those tokens were the words "from", "to", "wires", "from_pin"
    and "to_pin" over and over. Every signal wire of every design so far
    runs between the board and a part, so the only thing being chosen is
    which board pin. This form says that and nothing else:

        {"<part>": {"<its pin>": "<board pin>", ...}, ...}

    The part and pin names are fixed by the schema; the model writes the
    board pin. Code turns it into the cable list everything else reads.
    """
    boards = [p for p in parts if p.category == "mcu"]
    if len(boards) != 1:
        return None
    board = boards[0]
    choice = _pin_schema(board, True)
    props = {p.ref: {"type": "object", "additionalProperties": False,
                     "required": offered_pins(p, True),
                     "properties": {name: choice for name in offered_pins(p, True)}}
             for p in parts if p.ref != board.ref and offered_pins(p, True)}
    if not props:
        return None
    return {"type": "object", "additionalProperties": False,
            "required": list(props), "properties": props}


def from_pin_choices(doc: dict, parts: list[Part]) -> dict:
    """The cable list for an answer in pin_choice_schema's form. An answer
    that is already a cable list is returned as it is, so a reply in the
    older form is still understood. Raises HarnessError for anything else.
    """
    if isinstance(doc.get("cables"), list):
        return doc
    board = next((p for p in parts if p.category == "mcu"), None)
    by_ref = {p.ref: p for p in parts}
    if board is None:
        raise HarnessError("the reply gives pins and there is no microcontroller to put them on")
    cables = []
    for ref, pins in doc.items():
        if ref not in by_ref or ref == board.ref:
            raise HarnessError(f"the reply names '{ref}', which is not a part to be wired "
                               f"({', '.join(r for r in by_ref if r != board.ref)})")
        if not isinstance(pins, dict) or not pins:
            raise HarnessError(f"the reply gives no pins for {ref}")
        wires = []
        for pin, to in pins.items():
            if not isinstance(to, str) or not to:
                raise HarnessError(f"the reply gives {ref}.{pin} no microcontroller pin")
            wires.append({"from_pin": to, "to_pin": str(pin)})
        cables.append({"from": board.ref, "to": ref, "wires": wires})
    if not cables:
        raise HarnessError("the reply places no pins")
    return {"cables": cables}


def part_facts(parts: list[Part], signals_only: bool = False) -> str:
    lines = []
    for p in parts:
        if p.pins and not offered_pins(p, signals_only):
            continue                                 # nothing on it for the model to wire
        pins = ", ".join(offered_pins(p, signals_only)) or (
            "pins not listed; write each pin you use as GPIO and its number"
            if p.category == "mcu" and signals_only else
            "pins not listed; its power pins are 3V3, 5V, VIN and GND, and "
            "every other pin is written GPIO and its number, never by what "
            "it carries" if p.category == "mcu" else
            "pins not listed; name the pin you use")
        # No voltages here. For one real run the board's line also said
        # "Its 3V3 pin gives 3.3 V; VIN and 5V give 5 V", and the model
        # wired the reader's supply pin to 3V3, VIN and 5V, all three
        # (pitfall 4b). Which supply pin suits a part is fix_supply_pins's.
        lines.append(f"- {p.ref} ({p.name}): {pins}")
    return "\n".join(lines)


def parse_reply(text: str) -> dict:
    """The JSON object out of a reply, tolerating a fence around it."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise HarnessError("the model's reply contains no JSON object")
    try:
        doc = json.loads(t[start:end + 1])
    except json.JSONDecodeError as exc:
        raise HarnessError(f"the model's reply is not valid JSON ({exc.msg} at "
                           f"line {exc.lineno})") from exc
    if not isinstance(doc, dict):
        raise HarnessError("the model's reply is not a JSON object")
    return doc


def build(doc: dict, parts: list[Part]) -> tuple[str, list[str]]:
    """(WireViz YAML, notes for the owner) from the model's cable list.

    Checks what the schema would have enforced, because a reply can reach
    here from a model server that ignored the schema. Raises HarnessError
    naming the first thing that is wrong.
    """
    by_ref = {p.ref: p for p in parts}
    cables = doc.get("cables")
    if not isinstance(cables, list) or not cables:
        raise HarnessError("the reply lists no cables")
    notes: list[str] = []
    used: dict[str, list[str]] = {ref: [] for ref in by_ref}
    out_cables: dict[str, dict] = {}
    connections: list[list[dict]] = []

    for n, c in enumerate(cables, 1):
        if not isinstance(c, dict):
            raise HarnessError(f"cable {n} is not an object")
        a, b = c.get("from"), c.get("to")
        for end in (a, b):
            if end not in by_ref:
                raise HarnessError(f"cable {n} names '{end}', which is not a part "
                                   f"in the brief ({', '.join(by_ref)})")
        if a == b:
            raise HarnessError(f"cable {n} joins {a} to itself")
        wires = c.get("wires")
        if not isinstance(wires, list) or not wires:
            raise HarnessError(f"cable {n} ({a} to {b}) has no wires")
        from_pins, to_pins, colours = [], [], []
        for w in wires:
            if not isinstance(w, dict):
                raise HarnessError(f"a wire in cable {n} is not an object")
            for ref, key, bucket in ((a, "from_pin", from_pins), (b, "to_pin", to_pins)):
                pin = w.get(key)
                part = by_ref[ref]
                if not isinstance(pin, str) or not pin:
                    raise HarnessError(f"a wire in cable {n} has no {key}")
                if part.pins and part.pin(pin) is None:
                    raise HarnessError(
                        f"cable {n}: {ref} has no pin '{pin}' (it has "
                        f"{', '.join(x.name for x in part.pins)})")
                if not part.pins and part.category == "mcu" \
                        and not re.match(MCU_PIN, pin):
                    raise HarnessError(
                        f"cable {n}: '{pin}' is not a pin of the microcontroller "
                        f"{ref}. Write a power pin as 3V3, 5V, VIN or GND and any "
                        "other pin as GPIO and its number")
                if not part.pins and not re.match(free_pin(part), pin):
                    raise HarnessError(f"cable {n}: '{pin}' is not a usable pin name")
                bucket.append(pin)
                if pin not in used[ref]:
                    used[ref].append(pin)
            colours.append(COLOURS.get(str(w.get("colour", "")).lower(), "WH"))

        gauge = c.get("gauge_awg")
        if gauge not in GAUGES:
            if "gauge_awg" in c:                     # not asked for since D164
                notes.append(f"cable {n}: no usable gauge given, so {GAUGES[0]} AWG")
            gauge = GAUGES[0]
        # Thicker is never wrong for a conductor carrying supply current,
        # so this is decided here rather than hoped for.
        if gauge > 22 and any(POWER_NAMES.match(p) for p in from_pins + to_pins):
            notes.append(f"cable {n} ({a} to {b}) carries power or ground, so it "
                         f"was made 22 AWG instead of {gauge}")
            gauge = 22
        length = c.get("length_mm")
        if not isinstance(length, (int, float)) or isinstance(length, bool) \
                or not 20 <= length <= 600:
            if "length_mm" in c:
                notes.append(f"cable {n}: no usable length given, so 100 mm")
            length = 100

        name = f"W{n}"
        out_cables[name] = {"wirecount": len(wires), "gauge": f"{gauge} AWG",
                            "length": round(length / 1000, 3), "colors": colours}
        connections.append([{a: from_pins},
                            {name: list(range(1, len(wires) + 1))},
                            {b: to_pins}])

    unwired = [ref for ref, pins in used.items() if not pins and by_ref[ref].pins]
    for ref in unwired:
        notes.append(f"{ref} is not on any cable")

    connectors = {}
    for ref, part in by_ref.items():
        if not used[ref]:
            continue
        labels = [x.name for x in part.pins] or used[ref]
        connectors[ref] = {"type": part.name, "pinlabels": labels}

    text = yaml.safe_dump({"connectors": connectors, "cables": out_cables,
                           "connections": connections},
                          sort_keys=False, default_flow_style=None, allow_unicode=True)
    return text, notes
