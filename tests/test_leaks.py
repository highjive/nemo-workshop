"""Leaks a manual review of the shipped build found, none caught by any
earlier test because none of them needed a background job or thread to
still be running at the exact moment a window closed.
"""
from __future__ import annotations

import copy
import gc
import os
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import


class TestJobClosesItsPipe(unittest.TestCase):
    """Popen does not close its own pipe file objects; only communicate() or
    a context manager does. Job's reader thread read proc.stdout to EOF and
    then just called wait(), leaving the file object open until garbage
    collection -- one leaked descriptor per draft, outline, or mode-load in
    a session."""

    def run_and_wait(self, argv):
        from nemo.gui.worker import Job
        j = Job(argv).start()
        end = time.time() + 10
        while j.running and time.time() < end:
            time.sleep(0.02)
        return j

    def test_stdout_is_closed_once_the_process_ends(self):
        j = self.run_and_wait([sys.executable, "-c", "print('a'); print('b')"])
        self.assertEqual(j.returncode, 0)
        self.assertTrue(j.proc.stdout.closed)

    def test_stdout_is_closed_even_when_stopped_early(self):
        # A process that never exits on its own; stop() must still leave
        # the pipe closed once the process actually dies.
        from nemo.gui.worker import Job
        j2 = Job([sys.executable, "-c", "import time\nwhile True: time.sleep(0.05)"]).start()
        time.sleep(0.2)
        j2.stop()
        end = time.time() + 5
        while j2.proc.poll() is None and time.time() < end:
            time.sleep(0.02)
        time.sleep(0.2)          # give the reader thread a moment to notice EOF and close
        self.assertTrue(j2.proc.stdout.closed)

    def test_no_resource_warning_is_raised(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            j = self.run_and_wait([sys.executable, "-c", "print('x')"])
            del j
            gc.collect()          # would raise here, pre-fix, once collected


class TestModeStartClosesItsLogHandle(unittest.TestCase):
    """modes.start() opened its own log file to hand to Popen(stdout=...) and
    never closed its copy; the child has its own duplicated descriptor, so
    the parent's copy was pure waste. Low severity on its own (a one-shot
    CLI process reclaims it at exit), fixed for the same reason as the
    Job leak: closing what you open is not conditional on how much it costs
    you if you don't."""

    def test_the_parent_process_closes_its_handle(self):
        # Everything before the Popen() call is mocked to let a real, trivial
        # process through, so the fix's own finally: block actually runs.
        # What the child does after that does not matter here.
        from nemo import modes
        from nemo.config import Config
        home = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home), "NEMO_HOME": str(home / ".nemo")}):
            cfg = Config.load(Path("/nonexistent"))
            opened = {}
            real_open = Path.open

            def spy_open(path_self, *a, **k):
                fh = real_open(path_self, *a, **k)
                if path_self.suffix == ".log":
                    opened["fh"] = fh
                return fh
            empty = mock.Mock(stdout="", stderr="")
            with mock.patch.object(modes, "mem_available_mb", return_value=8000), \
                 mock.patch.object(modes, "llama_binary_runs", return_value=(True, "")), \
                 mock.patch.object(modes, "model_path", return_value=Path("model.gguf")), \
                 mock.patch.object(modes, "stop"), \
                 mock.patch("subprocess.run", return_value=empty), \
                 mock.patch.object(Path, "open", spy_open):
                # Plain mutation, not mock.patch.dict: Config no longer
                # aliases DEFAULTS (see TestConfigDoesNotAliasDefaults), so
                # this can no longer leak into any other test.
                cfg.data.setdefault("modes", {})["talk"] = {"model": "m", "ram_mb": 1}
                cfg.data.setdefault("paths", {})["llama_server"] = sys.executable
                ok, msg = modes.start(cfg, "talk")
        self.assertIn("fh", opened, "the code never reached the log file at all")
        self.assertTrue(opened["fh"].closed, "the parent's own log file handle "
                        "should be closed once Popen has its own copy")


class TestConfigDoesNotAliasDefaults(unittest.TestCase):
    """Config.load() on a path with no config file returned dict(DEFAULTS):
    a shallow copy, so every nested section (modes, paths, routing) was the
    literal DEFAULTS object. Mutating cfg.data["modes"] on one Config
    silently mutated DEFAULTS for every Config for the rest of the process.
    _merge() has the identical shape for any section a real config.yaml
    does not override, so this was not limited to the no-file case.

    No shipped code currently mutates cfg.data directly -- everything goes
    through get()/path()/route_for()/mode(), which are all read-only -- so
    this had no live-user impact. It was found because a test doing exactly
    that mutation corrupted two unrelated tests in test_offline.py that
    happened to run afterward in the same process.
    """

    def test_two_configs_do_not_share_their_data_dict(self):
        from nemo.config import Config
        a = Config.load(Path("/nonexistent"))
        b = Config.load(Path("/nonexistent"))
        self.assertIsNot(a.data, b.data)

    def test_mutating_one_configs_nested_section_does_not_touch_another(self):
        from nemo.config import Config
        a = Config.load(Path("/nonexistent"))
        b = Config.load(Path("/nonexistent"))
        before = copy.deepcopy(b.data.get("modes"))
        a.data.setdefault("modes", {})["talk"] = {"model": "not-a-real-model"}
        self.assertEqual(b.data.get("modes"), before)

    def test_defaults_itself_is_never_mutated(self):
        from nemo.config import DEFAULTS, Config
        before = copy.deepcopy(DEFAULTS)
        a = Config.load(Path("/nonexistent"))
        a.data.setdefault("modes", {})["talk"] = {"model": "not-a-real-model"}
        a.data.setdefault("paths", {})["parts"] = "/somewhere/else"
        self.assertEqual(DEFAULTS, before)

    def test_a_section_a_real_config_file_does_not_override_is_also_independent(self):
        # _merge() keeps DEFAULTS's own object for any key the file never
        # mentions; this is the path that bug actually took in real use.
        from nemo.config import Config
        d = Path(tempfile.mkdtemp())
        (d / "config.yaml").write_text("paths:\n  parts: /custom/parts\n")
        a = Config.load(d / "config.yaml")
        b = Config.load(d / "config.yaml")
        self.assertIsNot(a.data.get("modes"), b.data.get("modes"))
        a.data.setdefault("modes", {})["talk"] = {"model": "not-a-real-model"}
        self.assertNotEqual(b.data.get("modes", {}).get("talk", {}).get("model"),
                            "not-a-real-model")

    def test_the_default_constructor_is_also_independent(self):
        # Config()'s own dataclass field default had the identical shape.
        from nemo.config import Config
        a, b = Config(), Config()
        self.assertIsNot(a.data, b.data)
        a.data.setdefault("modes", {})["talk"] = {"model": "not-a-real-model"}
        self.assertNotEqual(b.data.get("modes", {}).get("talk", {}).get("model"),
                            "not-a-real-model")


if __name__ == "__main__":
    unittest.main(verbosity=2)
