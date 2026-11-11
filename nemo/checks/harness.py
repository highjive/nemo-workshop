"""The wiring harness's checks: the WireViz harness read back and held to
the parts' pins, nets, supply, logic levels and pin currents, and to the
schematic (2026-10-20: moved out of nemo/pipeline.py, where they were static
methods of Pipeline; Pipeline keeps their names for what calls them).

nemo/harness.py writes the harness; this module only reads and judges it.
Each check_* returns one Result.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .. import checks, harness
from ..parts import Part
from . import FAIL, Result


def _schematic_pin_names(script: Path) -> dict[tuple[str, str], str]:
    """(part ref, symbol pin number) -> pin name, from the comment that
    schematic.skidl_script writes above each part: '# J1 = ref: 1=VCC, ...'."""
    names: dict[tuple[str, str], str] = {}
    if not script.exists():
        return names
    for line in script.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"# J\d+ = (\S+): (.*)$", line)
        if not m:
            continue
        for item in m.group(2).split(", "):
            num, _, pin = item.partition("=")
            if num.strip().isdigit() and pin:
                names[(m.group(1), num.strip())] = pin
    return names


def _harness_groups(doc: dict) -> tuple[list[set], list[str]]:
    """The harness's nets: pins joined by its wires, however many hops,
    as sets of (connector, pin name). And chains it could not read."""
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    connectors = set((doc.get("connectors") or {}).keys())
    odd = []
    for n, chain in enumerate(doc.get("connections") or [], 1):
        ends = [(name, pins if isinstance(pins, list) else [pins])
                for hop in (chain if isinstance(chain, list) else [])
                if isinstance(hop, dict) for name, pins in hop.items()
                if name in connectors]
        for (a, pa), (b, pb) in zip(ends, ends[1:]):
            if len(pa) != len(pb):
                odd.append(f"connection {n}: {a} and {b} list different numbers of pins")
                continue
            for x, y in zip(pa, pb):
                parent[find((a, str(x)))] = find((b, str(y)))
    groups: dict = {}
    for end in parent:
        groups.setdefault(find(end), set()).add(end)
    return [g for g in groups.values() if len(g) > 1], odd


def check_harness_netlist(harness_path: Path, schematic_path: Path,
                          script: Path) -> Result:
    """The harness and the schematic describe the same circuit, pin by pin.

    Both are drawn by code from electrical/connections.json, but the
    wiring step decides the connections afresh when that file is
    missing or no longer fits the parts, and the electrical step can be
    run again after the wiring step. Either way the two files could
    describe different circuits and every other check would pass, since
    each is checked only against itself. This reads the schematic's
    nets back out of KiCad and compares them with the harness's.
    """
    name = "harness_netlist"
    doc = _load_harness(harness_path)
    if not doc:
        return Result(name, checks.SKIP, "no harness yet")
    if not schematic_path.exists():
        return Result(name, checks.SKIP,
                      "no schematic to compare with: the electrical step has not drawn one")
    pin_names = _schematic_pin_names(script)
    if not pin_names:
        return Result(name, checks.SKIP,
                      "the schematic was not drawn by Nemo's code, so its pin "
                      "numbers cannot be named")
    nets, why = checks.netlist_groups(schematic_path)
    if nets is None:
        return Result(name, checks.SKIP, f"the schematic's nets could not be read: {why}")

    unnamed = []
    sch_net: dict[tuple[str, str], str] = {}
    for net, ends in nets:
        for ref, num in ends:
            pin = pin_names.get((ref, num))
            if pin is None:
                unnamed.append(f"{ref} pin {num} on net {net}")
            else:
                sch_net[(ref, pin)] = net
    groups, odd = _harness_groups(doc)
    har_group = {end: i for i, g in enumerate(groups) for end in g}

    def show(ends) -> str:
        return ", ".join(f"{r}.{p}" for r, p in sorted(ends))

    problems: list[str] = []
    for g in groups:
        on = {sch_net.get(e) for e in g}
        if len(on) > 1 or None in on:
            apart = "; ".join(
                f"{r}.{p} " + (f"on {sch_net[(r, p)]}" if (r, p) in sch_net
                               else "on no net")
                for r, p in sorted(g))
            problems.append(f"the harness joins {show(g)}; in the schematic {apart}")
    by_net: dict[str, set] = {}
    for end, net in sch_net.items():
        by_net.setdefault(net, set()).add(end)
    for net, ends in sorted(by_net.items()):
        if len(ends) > 1 and (len({har_group.get(e) for e in ends}) > 1
                              or any(e not in har_group for e in ends)):
            problems.append(f"the schematic joins {show(ends)} (net {net}); "
                            "the harness does not")
    notes = odd + [f"{u}: no pin name for it in schematic.py, unchecked"
                   for u in unnamed]
    if problems:
        return Result(name, FAIL,
                      f"the harness and the schematic differ in {len(problems)} place(s)",
                      problems + notes + [
                          "Run the electrical step again, then this one, so both "
                          "are drawn from the same connections."])
    return Result(name, checks.PASS,
                  f"{len(groups)} connection(s) agree with the schematic", notes)



# --- harness structure -----------------------------------------
#
# Rewritten after the first run against real WireViz output. The earlier
# parser (a) took connector and cable NAMES as if they were nets and
# compared them with schematic net names, so the wiring gate could never
# pass once KiCad was installed; (b) looked for part names inside cable
# definitions, where they never appear, so every cable got the 100 mA
# default; and (c) called int() on WireViz's own "26 AWG" notation.
# This version reads the connections list, which is where WireViz
# actually records which connector each cable joins.


def _load_harness(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _topology(doc: dict) -> tuple[dict, list]:
    """cable -> connectors it joins; and every (connector, pin) used."""
    joins: dict[str, set] = {}
    endpoints: list[tuple[str, str]] = []
    connectors = set((doc.get("connectors") or {}).keys())
    cables = set((doc.get("cables") or {}).keys())
    for chain in doc.get("connections") or []:
        if not isinstance(chain, list):
            continue
        here_conn, here_cable = set(), set()
        for hop in chain:
            if not isinstance(hop, dict):
                continue
            for name, pins in hop.items():
                if name in connectors:
                    here_conn.add(name)
                    for pin in (pins if isinstance(pins, list) else [pins]):
                        # Kept as read, not str()'d: a bool here means
                        # YAML turned a pin label like NO into False,
                        # which must be reported, not matched as "False".
                        endpoints.append((name, pin))
                elif name in cables:
                    here_cable.add(name)
        for c in here_cable:
            joins.setdefault(c, set()).update(here_conn)
    return joins, endpoints


def _match_part(connector: str, parts: list[Part]) -> Part | None:
    """Connector name -> library part, only when unambiguous.

    Exact ref match first, then a unique prefix of ref or name. Anything
    ambiguous returns None and is reported as unchecked rather than
    guessed -- a wrong guess here would fail correct harnesses.
    """
    key = connector.lower().replace("-", "_").replace(" ", "_")
    exact = [p for p in parts if p.ref.lower() == key]
    if len(exact) == 1:
        return exact[0]
    pref = [p for p in parts if p.ref.lower().startswith(key)
            or p.name.lower().replace(" ", "_").startswith(key)]
    return pref[0] if len(pref) == 1 else None


def _harness_nets(path: Path) -> set[str]:
    """Pin endpoints, as CONNECTOR.PIN. Not net names."""
    _, endpoints = _topology(_load_harness(path))
    return {f"{c}.{p}" for c, p in endpoints}   # str() of each pin


def _harness_runs(path: Path, parts: list[Part]) -> list[dict]:
    """Per-cable current from the parts the cable actually joins."""
    from .deterministic import parse_awg
    doc = _load_harness(path)
    joins, _ = _topology(doc)
    runs = []
    for name, cable in (doc.get("cables") or {}).items():
        if not isinstance(cable, dict):
            continue
        touched = [_match_part(c, parts)
                   for c in sorted(joins.get(name, ()))]
        # The MCU is the source of a harness's current, not a load on it.
        loads = [p.draw_ma for p in touched
                 if p is not None and p.category not in ("mcu", "power")]
        runs.append({
            "name": name,
            "current_ma": max(loads) if loads else 100.0,
            "estimated": not loads,
            "awg": parse_awg(cable.get("gauge"), cable.get("gauge_unit")),
        })
    return runs


def check_harness_pins(path: Path, parts: list[Part]) -> Result:
    """Every wire lands on a pin that exists on the part it names.

    This is the documented intent of the wiring cross-check, and it can
    be done deterministically from the parts library without KiCad.
    """
    doc = _load_harness(path)
    if not doc:
        return Result("harness_pins", checks.SKIP, "no harness yet")
    _, endpoints = _topology(doc)
    bad, unchecked, ok = [], set(), 0
    for conn, pin in endpoints:
        if isinstance(pin, bool):
            bad.append(f"{conn}: a pin label was read as {pin} -- YAML "
                       "treats bare NO/ON/OFF/YES/Y/N as true/false. "
                       "Quote such pin names in the harness, e.g. \"NO\".")
            continue
        pin = str(pin)
        part = _match_part(conn, parts)
        if part is None or not part.pins:
            unchecked.add(conn)
            continue
        if part.pin(pin) is None:
            bad.append(f"{conn}.{pin}: {part.ref} has no pin '{pin}' "
                       f"(has {', '.join(x.name for x in part.pins)})")
        else:
            ok += 1
    items = bad + [f"{c}: not matched to a library part with a pin "
                   "list, unchecked" for c in sorted(unchecked)]
    if bad:
        return Result("harness_pins", FAIL,
                      f"{len(bad)} wire(s) land on pins that do not exist",
                      items)
    return Result("harness_pins", checks.PASS,
                  f"{ok} pin(s) verified", items)


def check_harness_covers(path: Path, parts: list[Part]) -> Result:
    """The harness wires THIS project: it joins something, and every
    part that has pins is on at least one wire.

    D127, from the first real wiring step on the AH531. The model
    returned a harness for a different project (connectors RC522 and
    DFPLAYER, neither in the brief), nested under a key WireViz does
    not read, joining connectors it had not defined. WireViz drew an
    empty picture and called it rendered; the pin check verified zero
    pins and passed; the step passed. Nothing asked whether the
    harness had anything to do with the parts in the brief.
    """
    doc = _load_harness(path)
    if not doc:
        return Result("harness_covers", checks.SKIP, "no harness yet")
    _, endpoints = _topology(doc)
    if not endpoints:
        found = ", ".join(sorted(map(str, doc))) or "nothing"
        return Result(
            "harness_covers", FAIL, "the harness joins nothing",
            ["No connection in it runs between connectors it defines. A "
             "WireViz harness has 'connectors', 'cables' and 'connections' "
             f"at the top level; this one has: {found}."])
    wired = {p.ref for conn, _ in endpoints
             if (p := _match_part(conn, parts)) is not None}
    missing = [p.ref for p in parts if p.pins and p.ref not in wired]
    strangers = sorted({str(conn) for conn, _ in endpoints
                        if _match_part(conn, parts) is None})
    items = [f"{c}: a connector that is not one of this project's parts"
             for c in strangers]
    if missing:
        return Result("harness_covers", FAIL,
                      f"{len(missing)} part(s) in the brief are not wired at all",
                      [f"{ref}: no wire in the harness reaches it"
                       for ref in missing] + items)
    return Result("harness_covers", checks.PASS,
                  f"all {len(wired)} part(s) with pins are wired", items)


def _wire_pairs(doc: dict) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """Every wire as ((connector, pin), (connector, pin))."""
    connectors = set((doc.get("connectors") or {}).keys())
    pairs = []
    for chain in doc.get("connections") or []:
        if not isinstance(chain, list):
            continue
        ends = []
        for hop in chain:
            if isinstance(hop, dict):
                for name, pins in hop.items():
                    if name in connectors:
                        ends.append((name, pins if isinstance(pins, list) else [pins]))
        for (a, pa), (b, pb) in zip(ends, ends[1:]):
            for x, y in zip(pa, pb):
                pairs.append(((a, str(x)), (b, str(y))))
    return pairs


def check_harness_electrical(path: Path, parts: list[Part]) -> Result:
    """Every part can actually work: its supply and ground pins are wired
    back to something that supplies them, and its bus pins reach the
    microcontroller.

    D130, from the first real harness made under the schema (AH531,
    qwen3-1.7b). It named only real parts and real pins, rendered, and
    passed every check there was. It also left the display with no
    power and no ground, and ran the data lines from the sensor to the
    display and never to the ESP32. "Every part is on a wire" was true
    and the circuit could not have worked.

    Decided from the parts library alone, which records what each pin
    is for. A part with no pin list (most microcontroller boards,
    batteries) cannot be checked pin by pin; it counts as a supply if
    it is a microcontroller or a power part, and as the place bus
    pins must reach if it is a microcontroller.
    """
    doc = _load_harness(path)
    pairs = _wire_pairs(doc) if doc else []
    if not pairs:
        return Result("harness_electrical", checks.SKIP, "no connections to check")

    # Nets: pins joined by wires, however many hops.
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def to_part(end):
        part = _match_part(end[0], parts)
        return (part.ref if part else None, end[1])

    for a, b in pairs:
        a, b = to_part(a), to_part(b)
        parent[find(a)] = find(b)
    nets: dict = {}
    for end in list(parent):
        nets.setdefault(find(end), set()).add(end)
    net_of = {end: members for members in nets.values() for end in members}

    by_ref = {p.ref: p for p in parts}
    supplies = {p.ref for p in parts if p.category in ("mcu", "power")}
    mcus = {p.ref for p in parts if p.category == "mcu"}
    bad = []
    for part in parts:
        if not part.pins or part.ref in supplies:
            continue
        for pin in part.pins:
            here = (part.ref, pin.name)
            others = {ref for ref, _ in net_of.get(here, ()) if ref != part.ref}
            if pin.function in ("power", "gnd"):
                what = "supply" if pin.function == "power" else "ground"
                if here not in net_of:
                    bad.append(f"{part.ref}.{pin.name} is not connected: the part "
                               f"has no {what}")
                elif supplies and not (others & supplies):
                    bad.append(f"{part.ref}.{pin.name} is joined only to "
                               f"{', '.join(sorted(o for o in others if o)) or 'nothing'}: "
                               f"no wire brings it a {what} from "
                               f"{' or '.join(sorted(supplies))}")
            elif pin.function == "bus" and mcus:
                if here not in net_of:
                    bad.append(f"{part.ref}.{pin.name} is not connected: it must "
                               f"go to {' or '.join(sorted(mcus))}")
                elif not (others & mcus):
                    bad.append(f"{part.ref}.{pin.name} does not reach "
                               f"{' or '.join(sorted(mcus))}: it is joined only to "
                               f"{', '.join(sorted(o for o in others if o)) or 'nothing'}")
    # D148: a part with no bus is controlled through its plain signal
    # pins, and one of them must reach the microcontroller, directly or
    # through a level shifter's gate. The LED ring passed every check
    # with its data input wired to a shifter's INPUT and to nothing else.
    reaches = {id(m) for m in nets.values() if any(ref in mcus for ref, _ in m)}
    for part in parts:
        for gate in part.gates:
            src = net_of.get((part.ref, str(gate.get("in"))))
            dst = net_of.get((part.ref, str(gate.get("out"))))
            if src is not None and dst is not None and id(src) in reaches:
                reaches.add(id(dst))
    for part in parts:
        if part.ref in supplies or part.gates or not mcus:
            continue
        signals = [x for x in part.pins if x.function == "io"]
        if not signals or any(x.function == "bus" for x in part.pins):
            continue
        if not any(id(net_of.get((part.ref, x.name))) in reaches for x in signals):
            bad.append(f"{part.ref} has no signal wire that reaches "
                       f"{' or '.join(sorted(mcus))}: nothing can control it or "
                       "read it")
    checked = sum(1 for p in parts if p.pins and p.ref not in supplies)
    if bad:
        return Result("harness_electrical", FAIL,
                      f"{len(bad)} pin(s) that the part needs are not properly wired",
                      bad)
    return Result("harness_electrical", checks.PASS,
                  f"power, ground and bus pins of {checked} part(s) all connected")


# --- what the wires carry ----------------------------------------
#
# D137, D138. The second brief put to the real model (an RFID tag
# player: ESP32, RC522 on SPI, a serial MP3 module, a speaker) passed
# every check and was wrong three ways. One GPIO was wired to both the
# reader's select pin and the player's RX, another to the reader's
# clock and the player's TX; the 3.3 V reader was fed from the board's
# 5 V VIN pin; an amplifier output was joined to a GPIO. Each pin was a
# real pin and every part had power and reached the microcontroller,
# which is all that was being asked.


def _pin_nets(path: Path, parts: list[Part]) -> list[set]:
    """Pins joined by wires, however many hops: a list of sets of
    (part ref, pin name). Empty if there is nothing to read."""
    doc = _load_harness(path)
    pairs = _wire_pairs(doc) if doc else []
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ends = []
        for end in (a, b):
            part = _match_part(end[0], parts)
            ends.append((part.ref if part else None, end[1]))
        parent[find(ends[0])] = find(ends[1])
    nets: dict = {}
    for end in list(parent):
        nets.setdefault(find(end), set()).add(end)
    return list(nets.values())


def check_harness_signals(path: Path, parts: list[Part]) -> Result:
    """No wire is asked to carry two different things.

    From the library's record of what each pin is for:
    - a microcontroller pin joined to differently named signal pins of
      other parts is doing two jobs (SDA and SCL of two modules on one
      pin each is a bus, and fine; a reader's SCK and a player's TX on
      one pin is not);
    - a bus or analogue pin joined to a supply or ground pin is shorted
      to a rail. A plain input strapped to a rail is ordinary, and is
      left alone.

    Limits: two pins with the same name on different buses (an I2C SDA
    and an SPI reader's SDA) look like one bus to this; and whether an
    analogue pin belongs on a given microcontroller pin is not judged.
    """
    nets = _pin_nets(path, parts)
    if not nets:
        return Result("harness_signals", checks.SKIP, "no connections to check")
    by_ref = {p.ref: p for p in parts}
    mcus = {p.ref for p in parts if p.category == "mcu"}
    bad = []
    for net in nets:
        signals, rails, mcu_pins, loud = [], [], [], []
        for ref, name in sorted(net, key=lambda e: (str(e[0]), e[1])):
            part = by_ref.get(ref)
            if part is None:
                continue
            if ref in mcus:
                (rails if harness.POWER_NAMES.match(name) else mcu_pins).append((ref, name))
                continue
            pin = part.pin(name)
            if pin is None:
                continue
            if pin.function in ("power", "gnd"):
                rails.append((ref, name))
            elif pin.function in ("io", "bus", "analog"):
                signals.append((ref, name, pin.function))
            elif pin.function == "speaker":
                loud.append((ref, name))
        if loud and (mcu_pins or rails or signals):               # D166
            other = (mcu_pins + rails + [(r, n) for r, n, _ in signals])[0]
            bad.append(f"{loud[0][0]}.{loud[0][1]} is a speaker terminal and is wired to "
                       f"{other[0]}.{other[1]}: it goes to an amplifier's output and "
                       "nothing else")
        ways = [by_ref[r].pin(n).direction for r, n, _ in signals]
        if len(signals) > 1 and not mcu_pins and not rails \
                and all(d == "in" for d in ways):          # tied to a rail is driven
            bad.append(" and ".join(f"{r}.{n}" for r, n, _ in signals)
                       + " are all inputs: nothing drives this wire")
        names = {name.upper() for _, name, _ in signals}
        if mcu_pins and len(names) > 1:
            where = " and ".join(f"{r}.{n}" for r, n in mcu_pins)
            bad.append(f"{where} is wired to "
                       + " and ".join(f"{r}.{n}" for r, n, _ in signals)
                       + ": one microcontroller pin cannot carry "
                       f"{len(names)} different signals. Give each its own pin")
        part_rails = [(r, n) for r, n in rails if r not in mcus]
        if mcu_pins and part_rails and not signals:
            bad.append(" and ".join(f"{r}.{n}" for r, n in mcu_pins) + " is wired to "
                       + ", ".join(f"{r}.{n}" for r, n in part_rails[:2])
                       + ", which is a supply or ground pin, not a signal")
        if rails:
            for r, n, fn in signals:
                if fn in ("bus", "analog"):
                    rail = ", ".join(f"{a}.{b}" for a, b in rails[:2])
                    bad.append(f"{r}.{n} is a signal and is wired to {rail}, "
                               "which is a supply or ground")
    if bad:
        return Result("harness_signals", FAIL,
                      f"{len(bad)} wire(s) carrying things that cannot share one", bad)
    return Result("harness_signals", checks.PASS, f"{len(nets)} net(s), one job each")


def check_harness_supply(path: Path, parts: list[Part]) -> Result:
    """Every supply pin is fed a voltage the part can run from.

    A microcontroller board's supply pins say what they give: 3V3 is
    3.3 V, 5V and VBUS are 5 V, VIN is the board's own highest supply.
    A part runs from anything between the lowest and highest voltage
    the library lists for it. A battery or converter with no pin list
    has no voltage this can read, so a pin fed only from one of those
    is counted as unchecked, not as passed.
    """
    nets = _pin_nets(path, parts)
    if not nets:
        return Result("harness_supply", checks.SKIP, "no connections to check")
    by_ref = {p.ref: p for p in parts}
    bad, checked, unknown = [], 0, []
    for net in nets:
        sources = []
        for ref, name in net:
            part = by_ref.get(ref)
            if part is None:
                continue
            pin = part.pin(name)
            if part.category == "power" and pin is not None and pin.voltage \
                    and pin.function == "power" and pin.direction == "out":
                sources.append((ref, name, float(pin.voltage)))     # D150
            if part.category != "mcu":
                continue
            volts = harness.supply_pin_volts(part, name)
            if volts:
                sources.append((ref, name, volts))
        grounds = sorted(f"{r}.{n}" for r, n in net if r in by_ref and (
            (by_ref[r].category == "mcu" and n.upper() in ("GND", "AGND", "DGND"))
            or (by_ref[r].pin(n) is not None and by_ref[r].pin(n).function == "gnd")))
        if sources and grounds:
            bad.append(f"{sources[0][0]}.{sources[0][1]} ({sources[0][2]:g} V) is wired to "
                       f"{grounds[0]}: a supply joined to ground is a short circuit")
        if len({v for _, _, v in sources}) > 1:
            bad.append(" and ".join(f"{r}.{n} ({v:g} V)" for r, n, v in sorted(sources))
                       + " are wired together: two different supplies on one wire")
        for ref, name in sorted(net, key=lambda e: (str(e[0]), e[1])):
            part = by_ref.get(ref)
            pin = part.pin(name) if part is not None else None
            if pin is not None and part.category == "power" and pin.function == "power" \
                    and pin.direction == "in" and pin.voltage:
                feeds = [s for s in sources if s[0] != ref]
                if feeds:
                    checked += 1
                for sref, sname, volts in feeds:
                    if abs(volts - float(pin.voltage)) > 0.35:
                        bad.append(f"{ref}.{name} takes {pin.voltage:g} V and is fed "
                                   f"from {sref}.{sname}, which is {volts:g} V")
                continue
            if pin is None or pin.function != "power" or part.category in ("mcu", "power"):
                continue
            if not part.supply_v:
                continue
            if not sources:
                unknown.append(f"{ref}.{name}: not fed from a microcontroller "
                               "supply pin, so its voltage is not checked")
                continue
            checked += 1
            low, high = min(part.supply_v) - 0.35, max(part.supply_v) + 0.35
            for sref, sname, volts in sources:
                if not low <= volts <= high:
                    takes = (f"{part.supply_v[0]:g} V" if len(set(part.supply_v)) == 1 else
                             f"{min(part.supply_v):g} to {max(part.supply_v):g} V")
                    bad.append(f"{ref}.{name} is fed from {sref}.{sname}, which is "
                               f"{volts:g} V. The part runs from {takes}")
    if bad:
        return Result("harness_supply", FAIL,
                      f"{len(bad)} part(s) fed a voltage they cannot take", bad + unknown)
    if not checked:
        return Result("harness_supply", checks.SKIP,
                      "no supply pin is fed from a pin whose voltage is known", unknown)
    return Result("harness_supply", checks.PASS,
                  f"{checked} supply pin(s) within the part's range", unknown)


def check_harness_levels(path: Path, parts: list[Part]) -> Result:
    """Signal pins joined by a wire work at voltages that suit both.

    D147, and what D143 left undone: the old voltage check compared
    only same-named bus pins of parts sharing an interface, never the
    wires. This reads the wires. From the library: each signal pin's
    voltage (its own, or its part's logic voltage) and, where the
    pin's name says so, which way it drives.

    - A higher-voltage OUTPUT on a lower-voltage pin FAILS: it can
      damage the pin.
    - A lower-voltage pin driving a higher-voltage INPUT, or two
      voltages on a wire where the library does not say which side
      drives, is not a fault this can prove. It passes, and is listed
      for a person to confirm.
    """
    nets = _pin_nets(path, parts)
    if not nets:
        return Result("harness_levels", checks.SKIP, "no connections to check")
    by_ref = {p.ref: p for p in parts}
    bad, confirm, compared = [], [], 0
    for net in nets:
        pins = []
        for ref, name in sorted(net, key=lambda e: (str(e[0]), e[1])):
            part = by_ref.get(ref)
            level = harness.signal_level(part, name) if part is not None else None
            if level is not None:
                pins.append((ref, name, level[0], level[1]))
        for i, x in enumerate(pins):
            for y in pins[i + 1:]:
                if x[0] == y[0]:
                    continue
                compared += 1
                hi, lo = (x, y) if x[2] >= y[2] else (y, x)
                if hi[2] - lo[2] <= 0.35:
                    continue
                if hi[2] <= harness.pin_tolerates(by_ref[lo[0]], lo[1]) + 0.35:
                    continue                     # an input made to take it
                if hi[3] == "out":
                    bad.append(f"{hi[0]}.{hi[1]} is a {hi[2]:g} V output wired to "
                               f"{lo[0]}.{lo[1]}, a {lo[2]:g} V pin: more than that pin "
                               "is made for. It needs a level shifter, or no wire")
                elif hi[3] == "in":
                    confirm.append(f"{lo[0]}.{lo[1]} ({lo[2]:g} V) drives {hi[0]}.{hi[1]}, "
                                   f"a {hi[2]:g} V input: it may not reach the level "
                                   "that input needs. See the part's notes")
                else:
                    confirm.append(f"{lo[0]}.{lo[1]} ({lo[2]:g} V) and {hi[0]}.{hi[1]} "
                                   f"({hi[2]:g} V) share a wire and the library does not "
                                   "say which drives: if the higher one does, it can "
                                   "damage the other")
    if bad:
        return Result("harness_levels", FAIL,
                      f"{len(bad)} output(s) wired to a pin of lower voltage", bad + confirm)
    if not compared:
        return Result("harness_levels", checks.SKIP,
                      "no two signal pins of known voltage share a wire")
    if confirm:
        return Result("harness_levels", checks.PASS,
                      f"{compared} signal wire(s) compared, {len(confirm)} to confirm",
                      confirm)
    return Result("harness_levels", checks.PASS,
                  f"{compared} signal wire(s) compared, voltages match")

SURGING = harness.SURGING


def check_pin_current(path: Path, parts: list[Part]) -> Result:
    """What each supply pin of the board is asked to carry, added up.

    D160. The first real design with a servo and a relay fed both, and
    a sensor, from the board's VIN pin: 730 mA at peak through one
    header pin and whatever sits between it and the USB socket. Every
    check passed, because the only current check compares the whole
    design with the supply, and the servo's own library note says not
    to feed it from the board.

    The library records no limit for any board pin, and none is
    invented here. So this cannot fail: it states the sum, and where a
    pin feeds a part whose current surges it lists the pin for a
    person to confirm. A contact wire is never counted.
    """
    nets = _pin_nets(path, parts)
    if not nets:
        return Result("pin_current", checks.SKIP, "no connections to check")
    fed = harness.pin_loads(nets, parts)
    if not fed:
        return Result("pin_current", checks.SKIP,
                      "no part is fed from a supply pin of the board")
    sums, confirm = [], []
    for board, pin, loads in fed:
        total = sum(p.draw_ma for p in loads)
        each = ", ".join(f"{p.ref} {p.draw_ma:.0f}" for p in loads)
        sums.append(f"{board}.{pin} {total:.0f} mA")
        surging = [p.ref for p in loads if p.category in SURGING]
        if surging:
            confirm.append(
                f"{board}.{pin} carries {total:.0f} mA at peak ({each}) and the library "
                f"records no limit for that pin. {', '.join(surging)} "
                f"draw{'s' if len(surging) == 1 else ''} in surges: confirm the pin and "
                "the board's own supply path can carry it, or feed "
                f"{'it' if len(surging) == 1 else 'them'} straight from the supply")
    return Result("pin_current", checks.PASS,
                  "at peak: " + "; ".join(sums)
                  + (f"; {len(confirm)} to confirm" if confirm else ""), confirm)
