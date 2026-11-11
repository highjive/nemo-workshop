"""The Computer Lab's Tester: compiles a project's firmware on its own and
says how it went (owner, 2026-10-21). No model is asked.

The firmware step compiles the code it writes; the Tester does the same for
the code as it is now, whenever the owner wants (after editing main.cpp by
hand, say), and reads more out of the build:
  compile    it builds or it does not (checks.runners.compile_firmware)
  warnings   how many the compiler gave, and the first few
  memory     the RAM and flash PlatformIO reports; over FULL percent fails,
             over TIGHT percent is a note, as a board that is nearly full
             has no room for the next change
A build that passes is recorded as the board having built here
(offline.record_build), so the readiness list stays true.
The result is kept in <project>/.nemo/test.json and the work log.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

FULL = 95.0          # percent of RAM or flash: fails
TIGHT = 80.0         # percent: a note

_USE = re.compile(r"^(RAM|Flash):.*?([\d.]+)%\s*\(used (\d+) bytes from (\d+) bytes\)")


def memory(lines: list[str]) -> dict[str, tuple[float, int, int]]:
    """{'RAM': (percent, used, of), 'Flash': ...} from PlatformIO's size lines."""
    out = {}
    for ln in lines:
        m = _USE.match(ln.strip())
        if m:
            out[m[1]] = (float(m[2]), int(m[3]), int(m[4]))
    return out


def warnings(log_text: str) -> list[str]:
    return [ln.strip() for ln in log_text.splitlines() if "warning:" in ln.lower()]


def board_of(fw: Path) -> str | None:
    try:
        text = (fw / "platformio.ini").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^\s*board\s*=\s*(\S+)", text, re.M)
    return m[1] if m else None


def test(project) -> list:
    """Compile the project's firmware now; returns the check results."""
    from .checks import FAIL, PASS, SKIP, Result
    from .checks.runners import compile_firmware
    fw = Path(project.firmware)
    results = [compile_firmware(fw)]
    built = results[0].status == PASS
    log = fw / "build.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    if built:
        warn = warnings(text)
        results.append(Result("warnings", PASS, f"{len(warn)} compiler warning(s)", warn[:8]))
        use = memory(results[0].items)
        if not use:
            results.append(Result("memory", SKIP, "PlatformIO gave no RAM or flash figures"))
        for kind, (pct, used, of) in use.items():
            status = FAIL if pct > FULL else PASS
            note = (" (tight: little room for the next change)" if TIGHT < pct <= FULL else "")
            results.append(Result(f"{kind.lower()}_use", status,
                                  f"{kind} {pct:.1f}%: {used} of {of} bytes{note}"))
        board = board_of(fw)
        if board:
            from . import offline
            offline.record_build(board, True)
    rec = {"at": int(time.time()), "results": [
        {"name": r.name, "status": r.status, "detail": r.detail, "items": list(r.items)}
        for r in results]}
    out = Path(project.root) / ".nemo" / "test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    from . import review
    review.record(project.root, "firmware", "tested", by="Tester",
                  ok=all(r.status != FAIL for r in results))
    return results
