"""The Test Bench (owner, 2026-10-21): flashing the board and listening to
it. With stand-ins: no board was plugged in when it was written.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import bench, staff
from nemo.project import Brief, Project


class AProject(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t))
        self._env.start()
        self.project = Project(self.t / "lamp")
        self.project.create(Brief(name="lamp"))
        self.project.firmware.mkdir(parents=True, exist_ok=True)
        (self.project.firmware / "platformio.ini").write_text(
            "[env:esp32dev]\nboard = esp32dev\nmonitor_speed = 9600\n", encoding="utf-8")

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.t, ignore_errors=True)


class FakeSerial:
    def __init__(self, lines):
        self.lines = [l.encode() for l in lines]
        self.closed = False

    def readline(self):
        return self.lines.pop(0) if self.lines else b""

    def close(self):
        self.closed = True


class TestThePorts(unittest.TestCase):
    def test_a_guess_at_each(self):
        ps = [mock.Mock(device="COM5", description="Silicon Labs CP210x", vid=0x10C4, pid=0xEA60),
              mock.Mock(device="COM7", description="USB Serial Device", vid=0x2E8A, pid=0x000A),
              mock.Mock(device="COM1", description="Communications Port", vid=None, pid=None)]
        with mock.patch("serial.tools.list_ports.comports", return_value=ps):
            got = bench.ports()
        self.assertIn("CP2102", got[0].hint)
        self.assertIn("Pico", got[1].hint)
        self.assertEqual(got[2].hint, "")

    def test_a_bluetooth_link_is_never_the_board(self):
        # 2026-11-06: a desktop's only ports were Bluetooth links, and the first
        # was the one used when none was named.
        bt = [mock.Mock(device=f"COM{n}", description=f"Standard Serial over Bluetooth link (COM{n})",
                        vid=None, pid=None, hwid="BTHENUM\\{00001101}") for n in (6, 4)]
        board = mock.Mock(device="COM9", description="USB-SERIAL CH340", vid=0x1A86, pid=0x7523,
                          hwid="USB VID:PID=1A86:7523")
        with mock.patch("serial.tools.list_ports.comports", return_value=bt):
            only_bt = bench.ports()
        self.assertTrue(all(p.bluetooth for p in only_bt))
        self.assertIsNone(bench.board_port(only_bt))
        with mock.patch("serial.tools.list_ports.comports", return_value=bt + [board]):
            mixed = bench.ports()
        self.assertEqual(mixed[0].device, "COM9")                    # the board first
        self.assertEqual(bench.board_port(mixed).device, "COM9")


class TestTheFlasher(AProject):
    def test_it_uploads_and_keeps_a_log(self):
        with mock.patch("nemo.platform_probe.find_tool", return_value="pio"), \
             mock.patch("nemo.checks.runners._run", return_value=(0, "Writing at 0x0001\nSUCCESS", "")) as run:
            r = bench.flash(self.project, "COM5")
        self.assertTrue(r.ok)
        self.assertEqual(run.call_args[0][0], ["pio", "run", "-t", "upload", "--upload-port", "COM5"])
        self.assertIn("SUCCESS", r.log.read_text(encoding="utf-8"))
        from nemo import review
        self.assertEqual(review.work_log(self.project.root)[-1]["event"], "flashed")

    def test_a_board_not_reached_says_what_to_check(self):
        with mock.patch("nemo.platform_probe.find_tool", return_value="pio"), \
             mock.patch("nemo.checks.runners._run",
                        return_value=(1, "", "could not open port 'COM5': PermissionError")):
            r = bench.flash(self.project, "COM5")
        self.assertFalse(r.ok)
        self.assertIn("is it plugged in", r.notes[0])

    def test_no_firmware_yet(self):
        (self.project.firmware / "platformio.ini").unlink()
        self.assertIn("firmware step", bench.flash(self.project).notes[0])


class TestTheSerialMonitor(AProject):
    def test_it_hears_the_board_at_the_project_s_speed(self):
        self.assertEqual(bench.speed(self.project.firmware), 9600)
        conn = FakeSerial(["boot", "hello from the lamp"])
        r = bench.listen(self.project, "COM5", seconds=0.3, opener=lambda: conn)
        self.assertTrue(r.ok)
        self.assertEqual(r.lines, ["boot", "hello from the lamp"])
        self.assertTrue(conn.closed)

    def test_a_crash_and_silence_are_said(self):
        r = bench.listen(self.project, "COM5", 0.3, opener=lambda: FakeSerial(
            ["Guru Meditation Error: Core 1 panic'ed", "Backtrace: 0x400"]))
        self.assertFalse(r.ok)
        self.assertTrue(any("crashed" in n for n in r.notes))
        r = bench.listen(self.project, "COM5", 0.2, opener=lambda: FakeSerial([]))
        self.assertIn("nothing was printed", r.notes[0])
        r = bench.listen(self.project, "COM9", 0.2, opener=mock.Mock(side_effect=OSError("busy")))
        self.assertIn("could not be opened", r.notes[0])

    def test_the_team(self):
        self.assertEqual([e.title for e in staff.team("bench")],
                         ["Flasher", "Serial Monitor", "Writer"])


if __name__ == "__main__":
    unittest.main()
