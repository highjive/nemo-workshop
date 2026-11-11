"""D196: the ESP32 platform pinned, the same in the image and in Nemo.

The firmware step wrote `platform = espressif32` with no version, and so
did the image build's warm-up project. The image therefore carried whatever
PlatformIO's newest ESP32 platform was on the day: 7.1.3 (Arduino-ESP32
2.0.17) in the 2026-10-19 image, 8.0.0 (Arduino-ESP32 3.3) on 2026-10-20,
whose two new compilers (a 2.4 GB RISC-V one the ESP32 dev board never
uses) took the squashfs past 2.9 GB and the build disk to full.
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import offline
from nemo.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "install" / "live-build" / "build-iso.sh"


def written_ini(mcu: str) -> str:
    """The platformio.ini the firmware step writes for this board."""
    t = Path(tempfile.mkdtemp())
    fake = SimpleNamespace(p=SimpleNamespace(firmware=t))
    Pipeline._write_pio(fake, "void setup(){}\nvoid loop(){}\n", SimpleNamespace(mcu=mcu))
    return (t / "platformio.ini").read_text(encoding="utf-8")


class TestPinned(unittest.TestCase):
    def test_the_platform_has_a_version(self):
        self.assertRegex(offline.ESP32_PLATFORM, r"^espressif32@\d+\.\d+\.\d+$")
        self.assertEqual(offline.ESP32_PLATFORM, "espressif32@7.1.3")   # the 2026-10-19 image's

    def test_the_firmware_step_writes_it(self):
        self.assertIn(f"platform = {offline.ESP32_PLATFORM}\n", written_ini("esp32_devkit_v1"))

    def test_the_toolchain_warm_up_uses_it(self):
        self.assertEqual(offline.platform_for("esp32dev"), offline.ESP32_PLATFORM)
        self.assertEqual(offline.platform_for("pico"), "raspberrypi")

    def test_a_pico_project_is_not_given_the_esp32_platform(self):
        self.assertIn("platform = raspberrypi\n", written_ini("rp2040_pico"))


class TestTheImageWarmsUpWhatNemoBuilds(unittest.TestCase):
    def test_the_same_project_file_byte_for_byte(self):
        if not BUILD.exists():
            self.skipTest("build-iso.sh is not in this layout")
        s = BUILD.read_text(encoding="utf-8")
        m = re.search(r"printf '(\[env:esp32dev\][^']*)' \\\n\s*> \"\$ROOT/var/tmp/piotest/platformio.ini\"", s)
        self.assertIsNotNone(m, "the warm-up platformio.ini was not found in build-iso.sh")
        self.assertEqual(m.group(1).replace("\\n", "\n"), written_ini("esp32_devkit_v1"))


if __name__ == "__main__":
    unittest.main()
