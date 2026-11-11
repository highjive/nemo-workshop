"""The schematic, written by code from the connections the model chose.

Twice on the real laptop the electrical step asked the 1.7B model for a
SKiDL script and got Python that imports names SKiDL does not have. The
same model, asked only which pin goes to which pin, gave a complete and
correct answer (harness.py). A schematic's content IS that answer: the
nets are the groups of pins joined by wires. So nothing more is asked of
the model. This module turns the same connection list into a SKiDL
script, with every line of SKiDL written here, once, and tested against
the real library.

Modules such as a sensor breakout have no symbol in KiCad's libraries, so
each part is drawn as a generic single-row connector with one pin per pin
of the part, numbered in the order the parts library lists them. That
numbering is the bridge O7 asked for: pin N of the symbol is the Nth name
in the library's pin list, and `pin_numbers()` returns it.
"""

from __future__ import annotations

import re

from .parts import Part

MAX_CONNECTOR = 40             # Connector_Generic goes up to Conn_01x40


class SchematicError(ValueError):
    """These connections cannot be drawn. For the owner."""


def _pairs(doc: dict) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    out = []
    for c in doc.get("cables") or []:
        a, b = c.get("from"), c.get("to")
        for w in c.get("wires") or []:
            out.append(((a, str(w.get("from_pin"))), (b, str(w.get("to_pin")))))
    return out


def pin_numbers(doc: dict, parts: list[Part]) -> dict[str, list[str]]:
    """For each part, its pin names in symbol-pin order (pin 1 first).

    A part whose pins the library lists keeps the library's order. A part
    with no list (most microcontroller boards) gets the pins the
    connections use, in the order they first appear.
    """
    used: dict[str, list[str]] = {p.ref: [] for p in parts}
    for end_a, end_b in _pairs(doc):
        for ref, pin in (end_a, end_b):
            if ref in used and pin not in used[ref]:
                used[ref].append(pin)
    out = {}
    for p in parts:
        names = [x.name for x in p.pins] or used[p.ref]
        if names:
            out[p.ref] = names
    return out


def _rail_name(volts: float) -> str:
    whole, frac = divmod(round(volts * 10), 10)
    return f"+{whole}V{frac}" if frac else f"+{whole}V"


def _volts_from_name(pin: str) -> float | None:
    m = re.fullmatch(r"\+?(\d+)V(\d)?", pin, re.I)
    if m:
        return int(m.group(1)) + (int(m.group(2)) / 10 if m.group(2) else 0)
    return None


def nets(doc: dict, parts: list[Part]) -> dict[str, list[tuple[str, str]]]:
    """Net name -> the pins on it. Pins joined by wires, however many hops.

    Names are decided here, not by the model: GND for a net with a ground
    pin on it, +3V3 or +5V for a supply net (from the voltage the library
    records, or from a pin called 3V3 or 5V), the microcontroller's pin
    name for a signal that reaches one, otherwise PART_PIN.
    """
    by_ref = {p.ref: p for p in parts}
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in _pairs(doc):
        for ref, _ in (a, b):
            if ref not in by_ref:
                raise SchematicError(f"'{ref}' is not a part in the brief")
        parent[find(a)] = find(b)
    groups: dict = {}
    for end in parent:
        groups.setdefault(find(end), []).append(end)

    def function(end):
        part = by_ref[end[0]]
        pin = part.pin(end[1]) if part.pins else None
        if pin is not None:
            return pin.function, pin.voltage
        if re.fullmatch(r"A?D?GND", end[1], re.I):
            return "gnd", None
        v = _volts_from_name(end[1])
        return ("power", v) if v else ("", None)

    named: dict[str, list[tuple[str, str]]] = {}
    for members in groups.values():
        members = sorted(members)
        kinds = [function(m) for m in members]
        mcu_pins = [m[1] for m in members if by_ref[m[0]].category == "mcu"]
        if any(k == "gnd" for k, _ in kinds):
            name = "GND"
        elif any(k == "power" for k, _ in kinds):
            volts = [v for k, v in kinds if k == "power" and v]
            name = _rail_name(max(volts)) if volts else "+VCC"
        elif mcu_pins:
            name = re.sub(r"\W", "_", mcu_pins[0]).upper()
        else:
            name = re.sub(r"\W", "_", f"{members[0][0]}_{members[0][1]}").upper()
        base, n = name, 2
        while name in named and name not in ("GND",) and not name.startswith("+"):
            name, n = f"{base}_{n}", n + 1
        named.setdefault(name, []).extend(members)
    return named


def skidl_script(doc: dict, parts: list[Part]) -> str:
    """A complete SKiDL script for these connections.

    Every SKiDL call in it was run against real SKiDL 2.3.0 and KiCad
    10.0.6 on the AH531. Supply rails and ground each carry a PWR_FLAG:
    measured there, KiCad's rules check fails a correct circuit without
    one.
    """
    numbers = pin_numbers(doc, parts)
    netmap = nets(doc, parts)
    if not netmap:
        raise SchematicError("there are no connections to draw")
    by_ref = {p.ref: p for p in parts}
    for ref, names in numbers.items():
        if len(names) > MAX_CONNECTOR:
            raise SchematicError(f"{ref} has {len(names)} pins; the generic connector "
                                 f"symbol stops at {MAX_CONNECTOR}")

    def var(name: str) -> str:
        return "n_" + re.sub(r"\W", "_", name).strip("_").lower()

    lines = [
        "# Written by Nemo from the connections chosen for this project.",
        "# Do not edit by hand: the electrical step rewrites it. Change the",
        "# connections instead (electrical/connections.json).",
        "from skidl import *",
        "",
        "set_default_tool(KICAD)",
        "",
        "# Nets. A net is every pin joined by wires, however many hops.",
    ]
    for name in netmap:
        lines.append(f'{var(name)} = Net("{name}", stub=True)')
    lines.append("")
    lines.append("# Parts. A module has no symbol of its own in KiCad's libraries, so each")
    lines.append("# is a single-row connector; pin N is the Nth pin name in the comment.")
    where = {end: name for name, members in netmap.items() for end in members}
    for i, (ref, names) in enumerate(numbers.items(), 1):
        part = by_ref[ref]
        label = part.name.replace('"', "'")
        lines.append(f"# J{i} = {ref}: " + ", ".join(f"{n}={pin}" for n, pin in enumerate(names, 1)))
        lines.append(f'j{i} = Part("Connector_Generic", "Conn_01x{len(names):02d}", '
                     f'ref="J{i}", value="{ref}")')
        lines.append(f'j{i}.fields["Description"] = "{label}"')
        for n, pin in enumerate(names, 1):
            net = where.get((ref, pin))
            if net:
                lines.append(f"{var(net)} += j{i}[{n}]    # {pin}")
            else:
                lines.append(f"j{i}[{n}] += NC    # {pin}: not used in this design")
        lines.append("")
    rails = [n for n in netmap if n == "GND" or n.startswith("+")]
    if rails:
        lines.append("# KiCad's rules check wants every supply net marked as driven.")
        for k, name in enumerate(rails, 1):
            lines.append(f'flag{k} = Part("power", "PWR_FLAG")')
            lines.append(f"{var(name)} += flag{k}[1]")
        lines.append("")
    lines += ["generate_netlist()", "generate_schematic()", ""]
    return "\n".join(lines)
