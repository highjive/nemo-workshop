"""The Computer Lab's Writer: a firmware guide for a project, written from
what code already decided (owner, 2026-10-22: "instructions, and what the
code does").

<project>/firmware/GUIDE.md says:
  - which board, and which pin of it goes to which part's pin, from the
    electrical step's connections (firmware.plan: the same table the
    bring-up firmware's constants come from, so the two cannot disagree);
  - the buses: the I2C pins and its parts, the SPI pins and each select;
  - what src/main.cpp does: for Nemo's own bring-up firmware, what that
    firmware is known to do; for any other, only what can be read from the
    file itself (its includes and functions), and that it was not written
    by Nemo's code;
  - how to build it, put it on the board and listen to it, with the
    serial speed from platformio.ini;
  - the Test Bench's last runs, from the project's work log.

It asks the model nothing and invents nothing: a part with no connection
is listed as not wired, and a file Nemo did not write is not explained.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

BRING_UP = "// Bring-up firmware for "


class GuideError(Exception):
    pass


def _what_main_does(main: Path, plan) -> list[str]:
    try:
        text = main.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["There is no src/main.cpp yet: run the firmware step."]
    if text.startswith(BRING_UP):
        out = ["Nemo's bring-up firmware, written by code from the connections, not by the model:",
               "",
               "- On start it prints a banner on the serial port and sets each wired pin up.",
               ]
        if plan is not None and plan.i2c:
            out.append(f"- It starts the I2C bus on GPIO {plan.i2c[0]} (SDA) and {plan.i2c[1]} (SCL) "
                       "and prints which addresses answer: a wired, powered part shows up; "
                       "one that does not, is not reached.")
        if plan is not None and plan.spi:
            out.append(f"- It starts the SPI bus on GPIO {plan.spi[0]} (SCK), {plan.spi[1]} (MISO), "
                       f"{plan.spi[2]} (MOSI).")
        m = re.search(r"UPDATE_EVERY_MS\s*=\s*(\d+)", text)
        out.append("- Its loop never blocks" + (f"; it updates every {int(m[1])} ms." if m else "."))
        empty = re.findall(r"// NOT GENERATED\. What (\S+) does", text)
        if empty:
            out.append("- Each part's own logic is an empty function, to be written from its "
                       "datasheet: " + ", ".join(empty) + ". It is not the finished program.")
        return out
    includes = re.findall(r"#include\s*[<\"]([^>\"]+)[>\"]", text)
    funcs = sorted(set(re.findall(r"^\s*(?:void|int|bool|float|uint\w*|long)\s+(\w+)\s*\(", text, re.M)))
    return ["This src/main.cpp was not written by Nemo's code (the model wrote it, or you did), "
            "so the Writer does not say what it does; it only lists what the file holds.",
            "",
            "- Includes: " + (", ".join(includes) or "none"),
            "- Functions: " + (", ".join(funcs) or "none found")]


def guide(project, lib) -> str:
    """The guide's text; also written to firmware/GUIDE.md."""
    import json
    from . import firmware, review
    from .bench import speed
    from .pipeline import pio_board
    brief = project.load_brief()
    if not brief.mcu:
        raise GuideError("the brief names no microcontroller yet")
    parts = [p for p in (lib.get(r) for r in brief.parts) if p is not None]
    board = pio_board(brief.mcu)
    lines = [f"# {brief.name}: firmware guide", "",
             f"Written by the Computer Lab's Writer, {time.strftime('%Y-%m-%d %H:%M')}, from what "
             "Nemo's code decided. Nothing here is a guess; what is not known says so.", "",
             "## The board", "", f"{brief.mcu}, built for PlatformIO's `{board}`.", ""]
    plan, why = None, ""
    try:
        doc = json.loads(project.connections.read_text(encoding="utf-8"))
        plan = firmware.plan(doc, parts)
    except OSError:
        why = "there are no connections yet: run the electrical step"
    except (ValueError, firmware.FirmwareError) as exc:
        why = f"the connections could not be read as a circuit: {exc}"
    lines += ["## Which pin goes where", ""]
    if plan is None:
        lines += [f"Not known: {why}.", ""]
    else:
        lines += ["| Part | Its pin | Board pin | GPIO | Net |", "|---|---|---|---|---|"]
        lines += [f"| {w.part} | {w.part_pin} | {w.mcu_pin} | {w.gpio} | {w.net} |" for w in plan.pins]
        wired = {w.part for w in plan.pins}
        loose = [r for r in plan.parts if r not in wired]
        if loose:
            lines += ["", "No signal wire reaches the board from: " + ", ".join(loose)
                      + " (power only, or not wired)."]
        lines.append("")
        if plan.i2c:
            lines += [f"I2C: SDA on GPIO {plan.i2c[0]}, SCL on GPIO {plan.i2c[1]}; on it: "
                      + ", ".join(plan.i2c_parts) + "."]
        if plan.spi:
            lines += [f"SPI: SCK GPIO {plan.spi[0]}, MISO GPIO {plan.spi[1]}, MOSI GPIO {plan.spi[2]}"
                      + "".join(f"; {ref} selected on GPIO {g}" for ref, g in plan.spi_selects) + "."]
        lines += ["Power and ground are wired by code as the wiring diagram shows "
                  "(wiring/harness.svg); they are not listed here.", ""]
    fw = Path(project.firmware)
    lines += ["## What the code does", ""] + _what_main_does(fw / "src" / "main.cpp", plan) + [""]
    baud = speed(fw)
    lines += ["## Build it, put it on the board, listen to it", "",
              "1. Build: `nemo test` (the Tester: compiles and reads RAM and flash use).",
              "2. Plug the board in by USB.",
              "3. Flash: the Test Bench's **Flash it**, or `nemo bench flash`.",
              f"4. Listen: **Listen 10 s**, or `nemo bench listen`, at {baud} baud "
              "(platformio.ini's monitor_speed" + ("" if (fw / "platformio.ini").is_file()
                                                   else "; there is no platformio.ini yet, so "
                                                   "115200 is assumed") + ").", ""]
    runs = [e for e in review.work_log(project.root)
            if e.get("event") in ("flashed", "listened")][-5:]
    lines += ["## On the Test Bench", ""]
    lines += ([f"- {time.strftime('%Y-%m-%d %H:%M', time.localtime(e.get('at', 0)))}: {e['event']}, "
               f"{'passed' if e.get('ok') else 'did not pass'}" for e in runs]
              or ["Not tried on a board yet."])
    text = "\n".join(lines) + "\n"
    fw.mkdir(parents=True, exist_ok=True)
    (fw / "GUIDE.md").write_text(text, encoding="utf-8")
    return text
