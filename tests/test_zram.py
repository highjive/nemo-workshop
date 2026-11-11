"""zram on NemoIso (owner, 2026-11-04: "add zram to nemoiso")."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import platform_probe as P

BUILD = Path(__file__).resolve().parent.parent / "install" / "live-build" / "build-iso.sh"

SWAPS = """Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority
/dev/zram0                              partition\t4054136\t\t0\t\t100
/dev/sda3                               partition\t2097148\t\t0\t\t-2
"""


@unittest.skipUnless(BUILD.is_file(), "build-iso.sh not in this layout")
class TestTheImage(unittest.TestCase):
    def setUp(self):
        text = BUILD.read_text(encoding="utf-8")
        self.code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))

    def test_zram_tools_is_installed_and_switched_on(self):
        self.assertIn("apt-get install -y -q zram-tools", self.code)
        self.assertIn("systemctl enable zramswap.service", self.code)

    def test_it_is_in_every_image_not_only_the_desktop_one(self):
        # Before the "$MINIMAL" branch: a minimal image needs it as much.
        self.assertLess(self.code.index("zram-tools"), self.code.index('if [ "$MINIMAL" -eq 0 ]'))

    def test_its_settings(self):
        conf = re.search(r'cat > "\$ROOT/etc/default/zramswap" <<.EOF.\n(.*?)\nEOF', BUILD.read_text(
            encoding="utf-8"), re.S).group(1)
        self.assertIn("ALGO=lz4", conf)          # light on the B960's two threads
        self.assertIn("PERCENT=50", conf)
        self.assertIn("PRIORITY=100", conf)

    def test_swappiness_is_not_guessed(self):
        # Not measured on the AH531 (O37), so Debian's default stands.
        self.assertNotIn("vm.swappiness", self.code)


class TestSeeingIt(unittest.TestCase):
    def test_only_zram_devices_are_counted(self):
        self.assertEqual(P.zram_swap_mb(SWAPS), 4054136 // 1024)
        self.assertEqual(P.zram_swap_mb(SWAPS.splitlines()[0] + "\n"), 0)
        self.assertEqual(P.zram_swap_mb(""), 0)

    def test_the_doctor_says_so_on_linux(self):
        from nemo import doctor
        with mock.patch.object(doctor, "IS_WINDOWS", False), \
             mock.patch.object(doctor, "memory_sticks", return_value=["4 GB", "4 GB"]), \
             mock.patch.object(doctor, "mem_total_mb", return_value=7900), \
             mock.patch.object(doctor, "mem_available_mb", return_value=5000), \
             mock.patch.object(doctor, "llama_binary_runs", return_value=(True, "ok")), \
             mock.patch("nemo.platform_probe.find_tool", return_value=None), \
             mock.patch("nemo.machine.gpus", return_value=()), \
             mock.patch.object(P, "zram_swap_mb", return_value=3959):
            text = "\n".join(f.line() for f in doctor.run())
        self.assertIn("zram swap", text)
        self.assertIn("3959 MB", text)


if __name__ == "__main__":
    unittest.main()
