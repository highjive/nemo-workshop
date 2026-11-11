"""D132, D133: found by running NemoDoc.cmd against a fresh prefix on the
real laptop (checklist step 3, 2026-10-06).

D132: `-Prefix C:\\NemoClean` downloaded the engine to C:\\NemoClean\\engine
and wrote a config that still named C:/Nemo/engine/llama-server.exe.

D133: with no Start menu or Desktop folder in the profile, the shortcut
loop printed fourteen errors and the pass still said "Everything checks out".
"""
import _sandbox; _sandbox.activate()  # noqa: E702

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def launcher() -> str:
    for base in (ROOT, ROOT / "install" / "windows"):
        if (base / "NemoDoc.ps1").exists():
            return (base / "NemoDoc.ps1").read_text(encoding="utf-8")
    raise unittest.SkipTest("NemoDoc.ps1 not present in this layout")


def function_text(src: str, name: str) -> str:
    start = src.index(f"function {name} {{")
    return src[start:src.index("\n}\n", start) + 3]


class TestConfigFollowsThePrefix(unittest.TestCase):
    def test_the_config_step_points_the_copy_at_this_prefixs_engine(self):
        s = launcher()
        step = s[s.index('Step "Config" {'):s.index("#  3. Verdict")]
        self.assertIn('Set-EnginePath (Join-Path $dest "config.yaml") $EngineDir', step)

    def test_the_shipped_config_names_the_default_prefix_so_this_matters(self):
        cfg = (ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("llama_server: C:/Nemo/engine/llama-server.exe", cfg)

    @unittest.skipUnless(shutil.which("powershell"), "needs Windows PowerShell")
    def test_run_for_real_the_line_is_rewritten_and_nothing_else(self):
        fn = function_text(launcher(), "Set-EnginePath")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.yaml"
            shutil.copy(ROOT / "config.yaml", cfg)
            before = cfg.read_text(encoding="utf-8").splitlines()
            # D212: this was 'D:\Else where\engine', and Join-Path refuses a
            # drive that is not there: with no D: (a USB drive taken out) the
            # line was left alone and the test failed. A real prefix exists.
            engine = Path(tmp) / "Else where" / "engine"
            script = Path(tmp) / "run.ps1"
            script.write_text(
                fn + f"\nSet-EnginePath '{cfg}' '{engine}'\n",
                encoding="utf-8")
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(script)],
                capture_output=True, text=True, errors="replace", timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            after = cfg.read_text(encoding="utf-8").splitlines()
            self.assertFalse(cfg.read_bytes().startswith(b"\xef\xbb\xbf"), "BOM written")
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(before), len(after))
        self.assertEqual(changed, [
            ("  llama_server: C:/Nemo/engine/llama-server.exe",
             "  llama_server: " + str(engine / "llama-server.exe").replace("\\", "/"))])


class TestShortcutWithoutAFolder(unittest.TestCase):
    def test_an_empty_or_missing_folder_is_skipped_with_a_warning(self):
        s = launcher()
        loop = s[s.index('foreach ($dir in @([Environment]::GetFolderPath("Programs")'):
                 s.index("$lnk.Save()")]
        guard = loop.index("if (-not $dir -or -not (Test-Path $dir))")
        self.assertLess(guard, loop.index("CreateShortcut"))
        self.assertIn('Note "WARN" "Nemo shortcut"', loop)
        self.assertIn("continue", loop)


class TestLauncherInstallsWhatTheStepsRun(unittest.TestCase):
    """D134: the electrical step runs a SKiDL script and the enclosure step
    a CadQuery one. A fresh install on the real laptop had neither."""

    def step(self):
        s = launcher()
        start = s.index('Step "Schematic and enclosure tools (SKiDL, CadQuery)"')
        return s[start:s.index("# --- nemo itself", start)]

    def test_both_libraries_are_installed_into_nemos_environment(self):
        step = self.step()
        self.assertIn('foreach ($pkg in @("skidl", "cadquery"))', step)
        self.assertIn("& $VenvPip install --quiet $pkg", step)

    def test_the_check_is_of_the_environment_and_looks_for_both(self):
        step = self.step()
        self.assertIn("& $VenvPy -I -c", step)
        self.assertIn("find_spec('skidl') and u.find_spec('cadquery')", step)

    def test_a_cadquery_without_its_kernel_is_not_taken_for_installed(self):
        # D208: cadquery 2.3.0 sat in the venv without OCP (no OCP wheel for
        # Python 3.15), so find_spec('cadquery') said yes, nothing imported,
        # and NemoDoc never offered to put it right.
        self.assertIn("u.find_spec('OCP')", self.step())

    def test_a_failure_here_does_not_stop_nemo_launching(self):
        self.assertIn("} $false | Out-Null", self.step())

    def test_the_pipeline_really_does_need_them(self):
        runners = (ROOT / "nemo" / "checks" / "runners.py").read_text(encoding="utf-8")
        self.assertIn("skidl", runners)
        self.assertIn("cadquery", runners)


class TestDiskWarningStatesTheMeasuredSize(unittest.TestCase):
    def test_models_are_six_and_a_half_gigabytes_not_five_point_six(self):
        # 806058272 + 1107409472 + 2497280256 + 2104932800 bytes, as downloaded.
        self.assertEqual(round((806058272 + 1107409472 + 2497280256 + 2104932800) / 1e9, 1), 6.5)
        s = launcher()
        self.assertIn("Models alone are about 6.5 GB.", s)
        self.assertNotIn("5.6 GB", s)


if __name__ == "__main__":
    unittest.main()
