"""D192: the README told the owner that eight older parts say "source not
recorded" and to check them. No part says it: every one of the 24 records
its source, and the phrase appears nowhere in Nemo. Found 2026-10-20 while
comparing the library's pinouts with Fritzing's parts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.parts import PartsLibrary

ROOT = Path(__file__).resolve().parent.parent


def bundled():
    lib = PartsLibrary.load()
    return list(lib.parts.values()) if hasattr(lib, "parts") else list(lib.all())


class TestSourcesAsTheReadmeSays(unittest.TestCase):
    def test_every_bundled_part_records_its_source(self):
        missing = [p.ref for p in bundled() if not (p.datasheet or "").strip()]
        self.assertEqual(missing, [])

    def test_the_readme_names_no_unsourced_parts_that_do_not_exist(self):
        readme = (ROOT / "docs" / "user-guide.md").read_text(encoding="utf-8")
        self.assertNotIn("source not recorded", readme)

    def test_the_readme_count_is_the_librarys(self):
        readme = (ROOT / "docs" / "user-guide.md").read_text(encoding="utf-8")
        self.assertIn(f"The library has {len(bundled())} parts", readme)


if __name__ == "__main__":
    unittest.main()
