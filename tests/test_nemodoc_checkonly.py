"""D201 (the AH531, 2026-10-29): `NemoDoc.ps1 -CheckOnly` added the test
install's venv Scripts folder to the user PATH, though a check-only pass
must change nothing. Every write to the user PATH is now behind a
-CheckOnly test.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

APP = Path(__file__).resolve().parent.parent


def nemodoc() -> Path:
    for p in (APP / "NemoDoc.ps1", APP / "install" / "windows" / "NemoDoc.ps1"):
        if p.is_file():
            return p
    raise unittest.SkipTest("no NemoDoc.ps1 here")


class TestCheckOnlyChangesNoPath(unittest.TestCase):
    def test_every_user_path_write_is_behind_check_only(self):
        lines = nemodoc().read_text(encoding="utf-8-sig").splitlines()
        writes = [i for i, l in enumerate(lines)
                  if re.search(r'SetEnvironmentVariable\("Path".*"User"\)', l)]
        self.assertGreaterEqual(len(writes), 3)                      # KiCad, Graphviz, nemo
        for i in writes:
            guard = "\n".join(lines[max(0, i - 4):i])
            self.assertIn("$CheckOnly", guard, f"line {i + 1} writes the PATH without asking")

    def test_nemo_is_put_on_path_only_once_its_scripts_exist(self):
        text = nemodoc().read_text(encoding="utf-8-sig")
        self.assertIn("-not (Test-Path $scripts)", text)


if __name__ == "__main__":
    unittest.main()
