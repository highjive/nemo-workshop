"""D173: the advice for a missing tool is for the system it is read on.

Seen on the first NemoIso image to boot (2026-10-08, in an emulator):
`nemo doctor` on Debian said KiCad "installs to a folder named for its
version (C:\\Program Files\\KiCad\\10.0\\bin)". The hint was written on
Windows and given everywhere.

These call the hint itself and not the whole machine check. The first
version of this file ran `doctor.run()`, which starts PowerShell; under
the test suite's stand-in home that took 37 seconds and left a
`Microsoft/` folder in whatever directory the tests were run from.
"""
from __future__ import annotations

import inspect, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import doctor


class TestTheHintForAMissingTool(unittest.TestCase):
    def test_on_linux_kicad_is_a_package_and_no_windows_path_is_mentioned(self):
        got = doctor.missing_hint("kicad-cli", windows=False)
        self.assertIn("On Debian: sudo apt install kicad", got)
        self.assertIn("NEMO_KICAD_CLI", got)
        self.assertNotIn("Program Files", got)
        self.assertNotIn("C:\\", got)

    def test_on_windows_it_is_the_advice_it_always_was(self):
        got = doctor.missing_hint("kicad-cli", windows=True)
        self.assertIn("C:\\Program Files\\KiCad\\10.0\\bin", got)
        self.assertNotIn("apt install", got)

    def test_on_linux_platformio_is_said_to_be_what_pio_is_and_how_to_get_it(self):
        self.assertIn("It is PlatformIO: /opt/nemo/venv/bin/pip install platformio",
                      doctor.missing_hint("pio", windows=False))
        self.assertEqual(doctor.missing_hint("pio", windows=True), "")

    def test_a_tool_with_nothing_to_add_gets_nothing(self):
        for name in ("git", "dot", "freecad"):
            for windows in (True, False):
                self.assertEqual(doctor.missing_hint(name, windows), "")

    def test_the_machine_check_uses_it_for_the_system_it_is_on(self):
        src = inspect.getsource(doctor.run)
        self.assertIn("missing_hint(name, IS_WINDOWS)", src)
        self.assertNotIn("Program Files", src)


class TestAnOptionalTool(unittest.TestCase):
    def test_missing_it_is_not_a_finding_for_the_doctors(self):
        """D206 (booted stick, 2026-10-31): "freecad missing" among the
        Doctors' findings. FreeCAD is optional and on no image."""
        from unittest import mock
        from nemo import clinic, doctor
        with mock.patch.object(doctor, "find_tool", create=True,
                               side_effect=lambda n, *a, **k: None if n == "freecad" else "/x/" + n), \
                mock.patch("nemo.platform_probe.find_tool",
                           side_effect=lambda n, *a, **k: None if n == "freecad" else "/x/" + n):
            found = clinic.machine(None)
        self.assertFalse([f for f in found if "freecad" in f.what.lower()])



if __name__ == "__main__":
    unittest.main()
