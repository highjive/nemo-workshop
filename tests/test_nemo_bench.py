"""nemo-bench (owner, 2026-11-04): measure NemoIso against CachyOS and Nobara
on the AH531 before any base OS changes, with one binary and one model."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

SCRIPT = Path(__file__).resolve().parent.parent / "install" / "linux" / "nemo-bench"


@unittest.skipUnless(SCRIPT.is_file(), "nemo-bench not in this layout")
class TestNemoBench(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.code = "\n".join(l for l in self.text.splitlines() if not l.lstrip().startswith("#"))

    @unittest.skipUnless(shutil.which("sh"), "needs sh")
    def test_it_parses(self):
        self.assertEqual(subprocess.run(["sh", "-n", str(SCRIPT)]).returncode, 0)

    def test_every_system_runs_nemoisos_own_binary(self):
        self.assertIn("/opt/nemo/bin/llama-server", self.code)
        self.assertIn('BIN="$HERE/llama-server"', self.code)

    def test_it_waits_for_the_model_not_just_the_port(self):
        # /v1/models answered while the model was still loading: every
        # request then came back "Loading model" (found running it, 2026-11-04).
        self.assertIn("/health", self.code)
        self.assertNotIn("/v1/models\"; do", self.code)

    def test_the_request_is_the_same_every_time(self):
        for fixed in ('"temperature": 0', '"seed": 7', '"n_predict": 128', '"cache_prompt": false'):
            self.assertIn(fixed.replace('"', '\\"'), self.code)

    def test_it_changes_nothing_on_the_system(self):
        for verb in ("apt", "pacman", "dnf", "mount ", "sudo", "rm -rf"):
            self.assertIsNone(re.search(rf"(^|\s){re.escape(verb)}", self.code), verb)


if __name__ == "__main__":
    unittest.main()
