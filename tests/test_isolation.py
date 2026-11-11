"""The suite must not be able to reach the real home directory.

D112, found on the first run on the real AH531 (Windows 11): the tests
patched HOME only. Windows resolves `~` from USERPROFILE, so the run
created projects and stories in the owner's own folders, appended test
sign-offs to his real audit log, and overwrote the running mode's log.
On Linux the same patches worked, which is why the sandbox never saw it.
"""
from __future__ import annotations

import os, re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import config, modes
from nemo.config import Config

TESTS = Path(__file__).resolve().parent


def inside(path, root) -> bool:
    path, root = Path(path).resolve(), Path(root).resolve()
    return path == root or root in path.parents


class TestProcessHomeIsASandbox(unittest.TestCase):
    def test_home_is_not_the_real_home(self):
        home = _sandbox.activate()
        self.assertNotEqual(home, _sandbox.REAL_HOME)
        self.assertEqual(Path.home().resolve(), home)
        self.assertEqual(Path(os.path.expanduser("~")).resolve(), home)

    def test_default_data_folders_land_in_the_sandbox(self):
        cfg = Config.load(Path("/nonexistent"))
        for key in ("paths.projects", "paths.parts", "paths.datasheets",
                    "paths.stories"):
            self.assertTrue(inside(cfg.path(key), _sandbox.activate()),
                            f"{key} resolves to {cfg.path(key)}")

    def test_module_level_paths_were_computed_inside_the_sandbox(self):
        # These are fixed at import time, so no later patch can move them.
        for name, p in (("config.CONFIG_HOME", config.CONFIG_HOME),
                        ("modes.STATE", modes.STATE)):
            self.assertFalse(inside(p, _sandbox.REAL_HOME / ".nemo"),
                             f"{name} points at the real home: {p}")


class TestPerTestPatchesRedirectTilde(unittest.TestCase):
    def test_home_env_moves_tilde_on_this_platform(self):
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.dict(os.environ, _sandbox.home_env(t)):
                self.assertEqual(Path.home().resolve(), Path(t).resolve())
                self.assertTrue(inside(
                    Config.load(Path("/nonexistent")).path("paths.stories"), t))
                self.assertTrue(inside(os.environ["NEMO_HOME"], t))

    def test_every_home_patch_in_the_suite_also_sets_userprofile(self):
        bad = []
        for f in sorted(TESTS.glob("test_*.py")):
            if f.name == Path(__file__).name:
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r'"HOME"\s*:', line) and "USERPROFILE" not in line:
                    bad.append(f"{f.name}:{n}")
        self.assertEqual(bad, [], "HOME patched without USERPROFILE; on "
                         "Windows that leaves `~` pointing at the real home")

    def test_every_test_module_activates_the_sandbox_before_importing_nemo(self):
        bad = []
        for f in sorted(TESTS.glob("test_*.py")):
            lines = f.read_text(encoding="utf-8").splitlines()
            hook = next((i for i, l in enumerate(lines)
                         if "_sandbox.activate()" in l), None)
            first = next((i for i, l in enumerate(lines)
                          if re.match(r"\s*(from|import) nemo\b", l)), None)
            if hook is None or (first is not None and first < hook):
                bad.append(f.name)
        self.assertEqual(bad, [])


class TestWindowTestsRunOnWindows(unittest.TestCase):
    """D117: every window test was guarded by the X11 DISPLAY variable,
    which Windows never sets, so on the real laptop all 61 skipped and the
    desktop interface had never been exercised on its own operating system.
    """

    def test_no_test_module_asks_for_the_x11_variable_directly(self):
        needle = "environ.get(" + '"DISPLAY")'
        bad = [f.name for f in sorted(TESTS.glob("test_*.py"))
               if needle in f.read_text(encoding="utf-8")]
        self.assertEqual(bad, [], "use _sandbox.has_display() instead")

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows only")
    def test_a_windows_desktop_counts_as_a_display(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("DISPLAY", None)
            os.environ.pop("NEMO_TEST_NO_DISPLAY", None)
            self.assertTrue(_sandbox.has_display())

    def test_elsewhere_it_is_still_the_x11_variable(self):
        # Checked on any machine: Linux is what the platform check is told.
        with mock.patch.dict(os.environ), mock.patch.object(_sandbox.sys, "platform", "linux"):
            os.environ.pop("DISPLAY", None)
            self.assertFalse(_sandbox.has_display())
            os.environ["DISPLAY"] = ":0"
            self.assertTrue(_sandbox.has_display())


if __name__ == "__main__":
    unittest.main()
