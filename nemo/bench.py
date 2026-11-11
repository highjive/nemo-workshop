"""The Test Bench: proving a design runs, not only that it compiles (owner,
2026-10-21; a suggested department he chose).

  Flasher         puts the project's firmware on the board over USB
                  (PlatformIO's own upload, `pio run -t upload`)
  Serial Monitor  listens to what the board prints, for a few seconds, at the
                  speed the project's platformio.ini gives (or 115200)
  Writer          keeps each bench run: <project>/.nemo/bench/<time>.log and
                  a line in the work log

Nothing here asks the model. NOT YET TRIED WITH A REAL BOARD: none was
plugged in when it was written. The USB names it puts beside a port are the
makers' well-known USB vendor numbers; a port is only a guess at a board.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

# USB vendor (and product) numbers of the bridges on common boards.
USB_HINTS = {
    (0x10C4, 0xEA60): "CP2102 USB-serial (common on ESP32 dev boards)",
    (0x1A86, 0x7523): "CH340 USB-serial (common on ESP32 and clone boards)",
    (0x0403, None): "FTDI USB-serial",
    (0x303A, None): "Espressif's own USB (ESP32-S3/C3)",
    (0x2E8A, None): "Raspberry Pi (Pico)",
}
# What an ESP32 prints when something is wrong (its own messages).
TROUBLE = (("Guru Meditation Error", "the program crashed"),
           ("Brownout detector was triggered", "the supply dipped too low"),
           ("Backtrace:", "a crash's backtrace"),
           ("abort() was called", "the program stopped itself"))


@dataclass
class Port:
    device: str
    description: str
    hint: str = ""
    hwid: str = ""

    @property
    def bluetooth(self) -> bool:
        """A Bluetooth serial link, which is never the board on the bench
        (2026-11-06: a desktop's only ports were four of these, and the
        first was the default)."""
        return "bluetooth" in self.description.lower() or "BTHENUM" in self.hwid.upper()


@dataclass
class Run:
    what: str                     # "flash" or "listen"
    ok: bool
    lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    log: Path | None = None


def ports() -> list[Port]:
    """The serial ports there are now, with a guess at what each is."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        hint = USB_HINTS.get((p.vid, p.pid)) or USB_HINTS.get((p.vid, None), "") if p.vid else ""
        hwid = p.hwid if isinstance(getattr(p, "hwid", None), str) else ""
        out.append(Port(p.device, p.description or "", hint, hwid))
    # A board-like port first: a known USB chip, then any not Bluetooth.
    return sorted(out, key=lambda p: (p.bluetooth, not p.hint))


def board_port(found: list[Port]) -> Port | None:
    """The port to use when none is named: the first that is not a
    Bluetooth link, or None."""
    return next((p for p in found if not p.bluetooth), None)


def speed(fw: Path) -> int:
    try:
        m = re.search(r"^\s*monitor_speed\s*=\s*(\d+)", (Path(fw) / "platformio.ini")
                      .read_text(encoding="utf-8"), re.M)
        return int(m[1]) if m else 115200
    except OSError:
        return 115200


def _keep(project, run: Run) -> Run:
    """The Writer: the run's log, and a line in the work log."""
    folder = Path(project.root) / ".nemo" / "bench"
    folder.mkdir(parents=True, exist_ok=True)
    run.log = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{run.what}.log"
    run.log.write_text("\n".join(run.lines + [""] + [f"note: {n}" for n in run.notes]) + "\n",
                       encoding="utf-8")
    from . import review
    review.record(project.root, "firmware", "flashed" if run.what == "flash" else "listened",
                  by="Flasher" if run.what == "flash" else "Serial Monitor", ok=run.ok)
    return run


def flash(project, port: str | None = None, timeout: int = 900) -> Run:
    """The Flasher: build if need be and upload to the board."""
    from .checks.runners import _run
    from .platform_probe import find_tool
    fw = Path(project.firmware)
    if not (fw / "platformio.ini").is_file():
        return Run("flash", False, notes=["there is no firmware yet: run the firmware step first"])
    pio = find_tool("pio")
    if not pio:
        return Run("flash", False, notes=["PlatformIO is not installed"])
    cmd = [pio, "run", "-t", "upload"] + (["--upload-port", port] if port else [])
    rc, so, se = _run(cmd, cwd=fw, timeout=timeout)
    lines = [l for l in (so + "\n" + se).splitlines() if l.strip()]
    notes = []
    text = "\n".join(lines)
    if rc != 0:
        if re.search(r"could not open port|No serial|Failed to connect|not found|Access is denied",
                     text, re.I):
            notes.append("the board was not reached: is it plugged in, and is no other program "
                         "(a serial monitor) holding its port?")
        else:
            notes.append(f"the upload failed (code {rc}); the log has PlatformIO's words")
    return _keep(project, Run("flash", rc == 0, lines[-40:], notes))


def listen(project, port: str, seconds: float = 10.0, baud: int | None = None,
           opener=None) -> Run:
    """The Serial Monitor: what the board prints for `seconds`."""
    baud = baud or speed(project.firmware)
    if opener is None:
        try:
            import serial
        except ImportError:
            return Run("listen", False, notes=["pyserial is not installed"])
        opener = lambda: serial.Serial(port, baud, timeout=0.5)       # noqa: E731
    try:
        conn = opener()
    except Exception as exc:                                    # noqa: BLE001
        return _keep(project, Run("listen", False, notes=[f"the port could not be opened: {exc}"]))
    lines, end = [], time.time() + seconds
    try:
        while time.time() < end:
            raw = conn.readline()
            if raw:
                lines.append(raw.decode("utf-8", "replace").rstrip())
    finally:
        conn.close()
    notes = [f"{what}: \"{needle}\"" for needle, what in TROUBLE
             if any(needle in l for l in lines)]
    if not lines:
        notes.append(f"nothing was printed in {seconds:g} s at {baud} baud: is the speed right, "
                     "and does the program print?")
    return _keep(project, Run("listen", bool(lines) and not notes, lines, notes))
