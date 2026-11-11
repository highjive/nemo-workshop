"""Bring-up firmware, written by code from the connections.

Three times on the real laptop the firmware step asked the 1.7B model for
src/main.cpp. It invented pin numbers, included headers that do not
exist, and on the last attempt wrote statements outside any function. The
same model, asked only which pin goes to which pin, was right.

So the part of a firmware that must be exactly right, and that follows
entirely from the wiring, is written here: the pin constants, the serial
banner, the bus set up on the pins that were actually wired, and a loop
that never blocks. It also scans the I2C bus and reports which addresses
answer, which is the quickest proof on the bench that the harness was
built as drawn.

What it deliberately does NOT write is each part's own logic: reading the
sensor, drawing on the display. That needs register addresses and
sequences from the part's datasheet, and Nemo does not invent those. Each
part gets a clearly marked empty function and a line on the serial port
saying so. This is a firmware to bring a board up with, not the finished
application, and it says that at the top of the file.

Only ESP32-family boards for now: how a bus is put on chosen pins differs
between Arduino cores, and only the ESP32 core's was checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import schematic
from .parts import Part

DEFAULT_UPDATE_MS = 1000
UPDATE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["update_every_ms"],
    "properties": {"update_every_ms": {"type": "integer", "minimum": 20,
                                       "maximum": 3600000}},
}
_SUPPLY_PIN = re.compile(r"^(\+?\d+V\d*|VCC|VDD|VIN|VBUS|VBAT|A?D?GND|3V|5V)$", re.I)
_GPIO = re.compile(r"^(?:GPIO|IO|GP|D)?_?(\d{1,2})$", re.I)
_SELECT_NAMES = ("SS", "CS", "NSS", "CSN", "SDA")      # on an SPI part, SDA is its select


_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                 "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
                 "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90, "half a": 0.5,
                 "a": 1, "an": 1, "each": 1}
_UNIT_MS = {"ms": 1, "millisecond": 1, "milliseconds": 1,
            "s": 1000, "sec": 1000, "secs": 1000, "second": 1000, "seconds": 1000,
            "min": 60000, "mins": 60000, "minute": 60000, "minutes": 60000,
            "hour": 3600000, "hours": 3600000}
_UNITS = "|".join(sorted(_UNIT_MS, key=len, reverse=True))
_EVERY = re.compile(
    r"\b(?:every|each)\s+(?:(\d+(?:\.\d+)?|half a|[a-z]+)\s+)?(" + _UNITS + r")\b", re.I)
_PER = re.compile(r"\b(once|twice|\d+ times|[a-z]+ times)\s+(?:a|an|per|every)\s+("
                  + _UNITS + r")\b", re.I)


def interval_from_text(text: str) -> tuple[int, str] | None:
    """(milliseconds, the words it was read from), if the text states how
    often something happens. None if it does not, or not in a way this can
    read with certainty.

    On the first real run the brief said "updates every ten seconds", the
    model was asked for the interval, and it answered 1000. A period
    written out in the brief is not a judgement call.
    """
    m = _EVERY.search(text or "")
    if m:
        raw = (m.group(1) or "a").lower()
        try:
            n = float(raw)
        except ValueError:
            if raw not in _NUMBER_WORDS:
                return None
            n = _NUMBER_WORDS[raw]
        ms = int(n * _UNIT_MS[m.group(2).lower()])
        return (ms, m.group(0)) if 20 <= ms <= 3600000 else None
    m = _PER.search(text or "")
    if m:
        how = m.group(1).lower()
        times = {"once": 1, "twice": 2}.get(how)
        if times is None:
            word = how.split()[0]
            times = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
        if not times:
            return None
        ms = int(_UNIT_MS[m.group(2).lower()] / times)
        return (ms, m.group(0)) if 20 <= ms <= 3600000 else None
    return None


class FirmwareError(ValueError):
    """A firmware cannot be written from these connections. For the owner."""


@dataclass
class Wired:
    const: str          # PIN_BME280_SCL
    gpio: int
    mcu_pin: str        # GPIO21
    part: str
    part_pin: str
    net: str


@dataclass
class Plan:
    mcu: str
    pins: list[Wired] = field(default_factory=list)
    i2c: tuple[int, int] | None = None                  # (sda, scl)
    i2c_parts: list[str] = field(default_factory=list)
    spi: tuple[int, int, int] | None = None             # (sck, miso, mosi)
    spi_selects: list[tuple[str, int]] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)      # everything but the mcu and supplies


def _ident(text: str) -> str:
    # D203: a pair named by a trailing sign (D+/D-, IN+/IN-) keeps the sign
    # as P/N. Both became "D", and the dock's firmware defined
    # PIN_USB_A_SOCKET_D twice and did not compile.
    text = re.sub(r"\+$", "_P", re.sub(r"-$", "_N", text.strip()))
    return re.sub(r"\W+", "_", text).strip("_").upper()


def plan(doc: dict, parts: list[Part]) -> Plan:
    by_ref = {p.ref: p for p in parts}
    mcus = [p for p in parts if p.category == "mcu"]
    if len(mcus) != 1:
        raise FirmwareError("the brief needs exactly one microcontroller, and has "
                            f"{len(mcus)}")
    mcu = mcus[0]
    netmap = schematic.nets(doc, parts)
    # A level shifter has no logic of its own: it is a wire that changes
    # voltage. The pin it is driven from belongs to the part on its far side.
    out = Plan(mcu.ref, parts=[p.ref for p in parts
                               if p.category not in ("mcu", "power") and p.pins
                               and not p.gates])
    net_of = {m: name for name, members in netmap.items() for m in members}

    def gpio_of(net_members) -> tuple[int, str] | None:
        for ref, pin in net_members:
            if ref == mcu.ref and not _SUPPLY_PIN.match(pin):
                m = _GPIO.match(pin)
                if not m:
                    raise FirmwareError(
                        f"the microcontroller pin '{pin}' is not a GPIO number "
                        "(expected something like GPIO21), so no pin constant can "
                        "be written for it")
                return int(m.group(1)), pin
        return None

    on_net: dict[tuple[str, str], tuple[int, str, str]] = {}
    for name, members in netmap.items():
        found = gpio_of(members)
        if found is None:
            continue
        reached = []
        for ref, pin in members:
            if ref == mcu.ref:
                continue
            gates = by_ref[ref].gates if ref in by_ref else []
            if not gates:
                reached.append((ref, pin, name))
                continue
            for gate in gates:                    # through the gate to what it drives
                if str(gate.get("in")) != pin:
                    continue
                far = net_of.get((ref, str(gate.get("out"))))
                reached += [(r, q, f"{name} through {ref}") for r, q in netmap.get(far, [])
                            if r not in (ref, mcu.ref)]
        for ref, pin, via in reached:
            on_net[(ref, pin)] = (found[0], found[1], via)
            out.pins.append(Wired(f"PIN_{_ident(ref)}_{_ident(pin)}", found[0],
                                  found[1], ref, pin, via))
    out.pins.sort(key=lambda w: (w.part, w.part_pin))

    for ref in out.parts:
        part = by_ref[ref]
        names = {x.name.upper() for x in part.pins}
        if {"MISO", "MOSI", "SCK"} <= names:
            bus = []
            for want in ("SCK", "MISO", "MOSI"):
                real = next(x.name for x in part.pins if x.name.upper() == want)
                if (ref, real) not in on_net:
                    raise FirmwareError(f"{ref}.{real} is not wired to {mcu.ref}")
                bus.append(on_net[(ref, real)][0])
            if out.spi and out.spi != tuple(bus):
                raise FirmwareError(
                    f"{ref} is on SPI pins {tuple(bus)} and another part on "
                    f"{out.spi}: one SPI bus is all this firmware sets up")
            out.spi = tuple(bus)
            sel = next((x.name for x in part.pins
                        if x.name.upper() in _SELECT_NAMES and (ref, x.name) in on_net), None)
            if sel:
                out.spi_selects.append((ref, on_net[(ref, sel)][0]))
        elif {"SDA", "SCL"} <= names:
            sda = next(x.name for x in part.pins if x.name.upper() == "SDA")
            scl = next(x.name for x in part.pins if x.name.upper() == "SCL")
            for real in (sda, scl):
                if (ref, real) not in on_net:
                    raise FirmwareError(f"{ref}.{real} is not wired to {mcu.ref}")
            pair = (on_net[(ref, sda)][0], on_net[(ref, scl)][0])
            if out.i2c and out.i2c != pair:
                raise FirmwareError(
                    f"{ref} has SDA/SCL on GPIO {pair} and {out.i2c_parts[0]} on "
                    f"{out.i2c}: both must share one pair of pins")
            out.i2c = pair
            out.i2c_parts.append(ref)
    return out


def scaffold(doc: dict, parts: list[Part], name: str, board: str,
             update_ms: int = DEFAULT_UPDATE_MS) -> str:
    """The whole of src/main.cpp for these connections."""
    if not board.startswith("esp32"):
        raise FirmwareError(f"bring-up firmware is only written for ESP32 boards so "
                            f"far, not {board}")
    p = plan(doc, parts)
    title = re.sub(r'[^\w .-]', "", name) or "project"
    L: list[str] = [
        "// Bring-up firmware for " + title + ", written by Nemo from",
        "// electrical/connections.json. It sets the board up on the pins that were",
        "// actually wired and proves the wiring. It is NOT the finished application:",
        "// each part's own logic is an empty function below, because writing it",
        "// needs register addresses from the part's datasheet, and Nemo does not",
        "// invent those.",
        "#include <Arduino.h>",
    ]
    if p.i2c:
        L.append("#include <Wire.h>")
    if p.spi:
        L.append("#include <SPI.h>")
    L += ["", "// One constant for every wire that reaches the microcontroller."]
    width = max((len(w.const) for w in p.pins), default=0)
    for w in p.pins:
        L.append(f"const int {w.const.ljust(width)} = {w.gpio:>2};   "
                 f"// {w.part}.{w.part_pin} on {p.mcu} {w.mcu_pin}, net {w.net}")
    if p.i2c:
        L += ["", f"const int PIN_I2C_SDA = {p.i2c[0]};   // " + ", ".join(p.i2c_parts),
              f"const int PIN_I2C_SCL = {p.i2c[1]};"]
    if p.spi:
        L += ["", f"const int PIN_SPI_SCK  = {p.spi[0]};",
              f"const int PIN_SPI_MISO = {p.spi[1]};",
              f"const int PIN_SPI_MOSI = {p.spi[2]};"]
        for ref, gpio in p.spi_selects:
            L.append(f"const int PIN_SPI_SELECT_{_ident(ref)} = {gpio};")
    L += ["", f"const unsigned long UPDATE_EVERY_MS = {int(update_ms)}UL;",
          "unsigned long lastUpdate = 0;", ""]

    if p.i2c:
        L += [
            "// Which addresses on the I2C bus answer. A part that is wired and",
            "// powered shows up here; one that is not, does not.",
            "int scanI2C() {",
            "  int found = 0;",
            "  for (uint8_t address = 1; address < 127; address++) {",
            "    Wire.beginTransmission(address);",
            "    if (Wire.endTransmission() == 0) {",
            '      Serial.printf("I2C device answers at 0x%02X\\n", address);',
            "      found++;",
            "    }",
            "  }",
            f'  Serial.printf("I2C scan: %d device(s) found, {len(p.i2c_parts)} expected '
            f'({", ".join(p.i2c_parts)})\\n", found);',
            "  return found;",
            "}",
            "",
        ]
    for ref in p.parts:
        L += [f"// NOT GENERATED. What {ref} does each update goes here.",
              f"void update_{_ident(ref).lower()}() {{", "}", ""]

    L += ["void setup() {",
          "  Serial.begin(115200);",
          f'  Serial.println("{title} bring-up firmware, built " __DATE__ " " __TIME__);']
    if p.i2c:
        L += ["  if (!Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL)) {",
              '    Serial.println("I2C did not start: check PIN_I2C_SDA and PIN_I2C_SCL");',
              "  } else {",
              "    scanI2C();",
              "  }"]
    if p.spi:
        for ref, _ in p.spi_selects:
            L += [f"  pinMode(PIN_SPI_SELECT_{_ident(ref)}, OUTPUT);",
                  f"  digitalWrite(PIN_SPI_SELECT_{_ident(ref)}, HIGH);   // not selected"]
        L.append("  SPI.begin(PIN_SPI_SCK, PIN_SPI_MISO, PIN_SPI_MOSI);")
        L.append('  Serial.println("SPI started");')
    for ref in p.parts:
        L.append(f'  Serial.println("{ref}: its own logic is not generated yet");')
    L += ["}", "",
          "void loop() {",
          "  unsigned long now = millis();",
          "  if (now - lastUpdate >= UPDATE_EVERY_MS) {      // never blocks",
          "    lastUpdate = now;"]
    for ref in p.parts:
        L.append(f"    update_{_ident(ref).lower()}();")
    L += ['    Serial.printf("alive, %lu s\\n", now / 1000UL);',
          "  }", "}", ""]
    return "\n".join(L)
