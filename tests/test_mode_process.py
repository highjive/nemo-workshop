"""Is the mode's model server running, and can it be stopped.

D113, found on the real AH531 (Windows 11). ModeStatus.running asked with
os.kill(pid, 0). On Linux signal 0 is the "does it exist" probe. On Windows
0 is CTRL_C_EVENT: the call never fails for a process that has exited, so a
stale pid file read as "running", and it sends a Ctrl+C to the console,
which interrupted the calling process. stop() then went on to
signal.SIGKILL, which Windows does not have.

These use real, trivial child processes, because the defect was in what
the operating system does with the call, which a mock cannot show.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import modes
from nemo.platform_probe import IS_WINDOWS, pid_alive


class ModeProcessCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "mode.pid"
        p = mock.patch.object(modes, "STATE", self.state)
        p.start(); self.addCleanup(p.stop)

    def sleeper(self) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(60)"])
        self.addCleanup(self._reap, proc)
        return proc

    @staticmethod
    def _reap(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)

    def exited(self) -> subprocess.Popen:
        # The Popen object keeps the pid from being reused while we hold it.
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=30)
        self.addCleanup(lambda: proc)
        return proc

    def record(self, pid: int):
        self.state.write_text(f"talk\n{pid}\nm\n")


class TestRunning(ModeProcessCase):
    def test_an_exited_process_is_not_running(self):
        proc = self.exited()
        self.assertFalse(modes.ModeStatus("talk", proc.pid, "m").running)
        self.assertFalse(pid_alive(proc.pid))

    def test_a_live_process_is_running_and_survives_being_asked(self):
        proc = self.sleeper()
        st = modes.ModeStatus("talk", proc.pid, "m")
        for _ in range(5):
            self.assertTrue(st.running)
        time.sleep(0.5)
        self.assertIsNone(proc.poll(), "asking whether it runs ended it")

    def test_no_pid_is_not_running(self):
        self.assertFalse(modes.ModeStatus(None, None, None).running)
        self.assertFalse(pid_alive(0))

    @unittest.skipUnless(IS_WINDOWS, "os.kill(pid, 0) is the right probe on Linux")
    def test_the_check_sends_nothing_on_windows(self):
        proc = self.sleeper()
        with mock.patch("os.kill") as kill:
            self.assertTrue(modes.ModeStatus("talk", proc.pid, "m").running)
        kill.assert_not_called()


class TestStop(ModeProcessCase):
    def test_stop_ends_the_process_and_removes_the_state_file(self):
        proc = self.sleeper()
        self.record(proc.pid)
        self.assertTrue(modes.current().running)
        self.assertTrue(modes.stop())
        self.assertIsNotNone(proc.wait(timeout=10))
        self.assertFalse(self.state.exists())

    def test_a_stale_state_file_is_cleaned_up_and_nothing_is_signalled(self):
        proc = self.exited()
        self.record(proc.pid)
        with mock.patch("os.kill") as kill:
            self.assertFalse(modes.stop())
        kill.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_stop_with_no_state_file_is_quiet(self):
        self.assertFalse(modes.stop())

    def test_a_process_that_ignores_the_first_request_is_still_stopped(self):
        # The fallback used signal.SIGKILL by name; Windows has no such name.
        proc = self.sleeper()
        self.record(proc.pid)
        real_alive = modes.pid_alive
        calls = {"n": 0}

        def slow_to_die(pid):
            calls["n"] += 1
            return True if calls["n"] < 60 else real_alive(pid)
        with mock.patch.object(modes, "pid_alive", slow_to_die), \
             mock.patch.object(modes.time, "sleep"):
            self.assertTrue(modes.stop())
        self.assertIsNotNone(proc.wait(timeout=10))
        self.assertFalse(self.state.exists())


class _Proc:
    """Stands in for the server process: alive until told otherwise."""
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


class TestWaitsUntilTheServerAnswers(unittest.TestCase):
    """D121, measured on the real AH531: `nemo mode talk` printed "up" and
    returned while the server was still answering 503; a story command sent
    2 s later was told no model was loaded. It answered 2.6 s after that."""

    def serve(self, delay=0.0, loading_for=0.0):
        """A real local HTTP server that appears after `delay` and answers
        503 for `loading_for` seconds before answering 200."""
        import http.server, socket, threading
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        ready_at = time.time() + delay + loading_for

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if time.time() >= ready_at else 503)
                self.end_headers(); self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        def run():
            time.sleep(delay)
            srv = http.server.HTTPServer(("127.0.0.1", port), H)
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            srv.serve_forever()
        threading.Thread(target=run, daemon=True).start()
        return f"http://127.0.0.1:{port}/v1"

    def test_it_waits_for_a_server_that_is_not_listening_yet(self):
        base = self.serve(delay=1.0)
        t = time.time()
        self.assertTrue(modes._wait_ready(base, _Proc(), 20))
        self.assertGreaterEqual(time.time() - t, 0.9)

    def test_a_503_while_the_model_loads_is_not_ready(self):
        base = self.serve(loading_for=1.5)
        t = time.time()
        self.assertTrue(modes._wait_ready(base, _Proc(), 20))
        self.assertGreaterEqual(time.time() - t, 1.2)

    def test_a_server_that_dies_ends_the_wait_at_once(self):
        proc = _Proc(); proc.code = 1
        t = time.time()
        self.assertFalse(modes._wait_ready("http://127.0.0.1:9/v1", proc, 20))
        self.assertLess(time.time() - t, 3)

    def test_the_wait_is_bounded(self):
        t = time.time()
        self.assertFalse(modes._wait_ready("http://127.0.0.1:9/v1", _Proc(), 1.5))
        self.assertLess(time.time() - t, 12)

    def started(self, ready: bool):
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))
        cfg.data["modes_windows"]["talk"] = cfg.data["modes"]["talk"] = {"model": "m", "ram_mb": 1}
        state = Path(tempfile.mkdtemp()) / "mode.pid"
        waited = mock.Mock(return_value=ready)
        with mock.patch.object(modes, "STATE", state), \
             mock.patch.object(modes, "mem_available_mb", return_value=8000), \
             mock.patch.object(modes, "engine_path", return_value="llama-server"), \
             mock.patch.object(modes, "llama_binary_runs", return_value=(True, "")), \
             mock.patch.object(modes, "model_path", return_value=Path("model.gguf")), \
             mock.patch.object(modes, "stop"), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="", stderr="")), \
             mock.patch("subprocess.Popen", return_value=mock.Mock(pid=4242, poll=lambda: None)), \
             mock.patch.object(modes, "_wait_ready", waited):
            ok, msg = modes.start(cfg, "talk")
        return ok, msg, waited

    def test_start_says_up_only_after_the_server_answered(self):
        ok, msg, waited = self.started(ready=True)
        self.assertTrue(waited.called)
        self.assertTrue(ok); self.assertIn("up:", msg)

    def test_start_is_honest_when_it_is_still_loading_at_the_limit(self):
        ok, msg, _ = self.started(ready=False)
        self.assertTrue(ok)
        self.assertNotIn("up:", msg)
        self.assertIn("still loading", msg); self.assertIn("not answering yet", msg)


class TestRefusalPointsAtAFileThatExists(unittest.TestCase):
    """D123, read off the real laptop's screen: the 'not enough memory'
    refusal sent the owner to install/windows/trim.ps1. That folder is from
    the old source tree. In what ships, trim.ps1 sits beside NemoDoc.cmd."""

    def refusal(self) -> str:
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))
        with mock.patch.object(modes, "mem_available_mb", return_value=500), \
             mock.patch.object(modes, "mem_total_mb", return_value=8104), \
             mock.patch.object(modes, "IS_WINDOWS", True):
            ok, msg = modes.start(cfg, "design")
        self.assertFalse(ok)
        return msg

    def test_it_does_not_name_a_folder_that_is_not_shipped(self):
        msg = self.refusal()
        self.assertIn("trim.ps1", msg)
        self.assertNotIn("install/windows", msg)

    def test_any_script_path_it_names_exists_in_this_layout(self):
        import re
        root = Path(__file__).resolve().parent.parent
        for path in re.findall(r"[\w./\\-]+\.ps1", self.refusal()):
            if "/" in path or "\\" in path:
                self.assertTrue((root / path).exists(), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestStartFindsTheEngineWhereTheDoctorDoes(unittest.TestCase):
    """D176, the first real NemoIso run on the AH531 (2026-10-15): the model
    would not load. llama-server is in /opt/nemo/bin, on nobody's PATH.
    nemodoc and the doctor look there and said it was installed; starting
    a mode ran the bare name "llama-server" and could not find it."""

    def start(self, found):
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))      # paths.llama_server: "llama-server"
        cfg.data["modes_windows"]["talk"] = cfg.data["modes"]["talk"] = {"model": "m", "ram_mb": 1}
        state = Path(tempfile.mkdtemp()) / "mode.pid"
        popen = mock.Mock(return_value=mock.Mock(pid=4242, poll=lambda: None))
        runs = lambda b: (True, "") if b == found else (False, "not installed")
        with mock.patch.object(modes, "STATE", state), \
             mock.patch.object(modes, "mem_available_mb", return_value=8000), \
             mock.patch.object(modes, "find_tool", return_value=found, create=True), \
             mock.patch.object(modes, "llama_binary_runs", side_effect=runs), \
             mock.patch.object(modes, "model_path", return_value=Path("model.gguf")), \
             mock.patch.object(modes, "stop"), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="", stderr="")), \
             mock.patch("subprocess.Popen", popen), \
             mock.patch.object(modes, "_wait_ready", return_value=True):
            ok, msg = modes.start(cfg, "talk")
        return ok, msg, popen

    def test_the_engine_off_the_path_is_the_one_run(self):
        ok, msg, popen = self.start("/opt/nemo/bin/llama-server")
        self.assertTrue(ok, msg)
        self.assertEqual(popen.call_args[0][0][0], "/opt/nemo/bin/llama-server")

    def test_no_engine_anywhere_is_said_and_nothing_is_run(self):
        ok, msg, popen = self.start(None)
        self.assertFalse(ok)
        self.assertIn("/opt/nemo/bin", msg)
        popen.assert_not_called()


class TestMemoryComingBack(unittest.TestCase):
    """D191, the AH531 on 2026-10-19: talk mode was stopped and started
    again, and the start was refused: 1995 MB available, 2800 needed. Two
    seconds later 3958 MB were. Windows gives a stopped server's memory
    back over a second or two. And a mode already running is stopped by
    start() itself, yet its memory was counted as gone, so switching modes
    was refused for memory the old one was about to free."""

    NEED = 2800                      # talk: 2100 + 400 + 300

    def start(self, avail, old=None, held=0, stopped_ago=None, engine="llama-server"):
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))
        cfg.data["engine"]["prompt_cache"] = False
        state = Path(tempfile.mkdtemp()) / "mode.pid"
        if stopped_ago is not None:
            marker = state.with_name(modes.STOPPED_NAME)
            marker.write_text("x", encoding="utf-8")
            t = time.time() - stopped_ago
            import os; os.utime(marker, (t, t))
        readings = list(avail)
        mem = mock.Mock(side_effect=lambda: readings.pop(0) if len(readings) > 1 else readings[0])
        status = old or modes.ModeStatus(None, None, None)
        stop = mock.Mock()
        popen = mock.Mock(return_value=mock.Mock(pid=4242, poll=lambda: None))
        with mock.patch.object(modes, "STATE", state), \
             mock.patch.object(modes, "mem_available_mb", mem), \
             mock.patch.object(modes, "mem_total_mb", return_value=8104), \
             mock.patch.object(modes, "current", return_value=status), \
             mock.patch.object(modes, "process_rss_mb", return_value=held), \
             mock.patch("nemo.modes.pid_alive", return_value=old is not None), \
             mock.patch.object(modes, "MEMORY_RETURN_S", 2), \
             mock.patch.object(modes, "engine_path", return_value=engine), \
             mock.patch.object(modes, "llama_binary_runs", return_value=(True, "")), \
             mock.patch.object(modes, "model_path", return_value=Path("qwen3-1.7b.gguf")), \
             mock.patch.object(modes, "stop", stop), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="", stderr="")), \
             mock.patch("subprocess.Popen", popen), \
             mock.patch.object(modes, "_wait_ready", return_value=True):
            ok, msg = modes.start(cfg, "talk")
        return ok, msg, stop, popen

    def running(self):
        return modes.ModeStatus("design", 777, "qwen3-4b")

    def test_switching_counts_the_running_modes_memory_as_coming_back(self):
        ok, msg, stop, popen = self.start([1995, 1995, 3958], old=self.running(), held=2400)
        self.assertTrue(ok, msg)
        stop.assert_called(); popen.assert_called()

    def test_it_says_so_when_the_memory_did_not_come_back(self):
        ok, msg, stop, popen = self.start([1995], old=self.running(), held=2400)
        self.assertFalse(ok)
        self.assertIn("'design' was stopped to make room", msg)
        self.assertIn("1995 MB", msg)
        popen.assert_not_called()

    def test_a_mode_too_small_to_make_room_is_left_running(self):
        ok, msg, stop, popen = self.start([1995], old=self.running(), held=300)
        self.assertFalse(ok)
        stop.assert_not_called()
        self.assertNotIn("stopped to make room", msg)

    def test_another_refusal_leaves_the_running_mode_alone(self):
        ok, msg, stop, popen = self.start([1995], old=self.running(), held=2400, engine=None)
        self.assertFalse(ok)
        self.assertIn("not installed", msg)
        stop.assert_not_called()

    def test_a_start_just_after_a_stop_waits_for_the_memory(self):
        ok, msg, stop, popen = self.start([1995, 1995, 3958], stopped_ago=1)
        self.assertTrue(ok, msg)

    def test_with_no_recent_stop_a_refusal_does_not_wait(self):
        t = time.time()
        ok, msg, stop, popen = self.start([1995, 3958], stopped_ago=600)
        self.assertFalse(ok)
        self.assertLess(time.time() - t, 1.5)

    def test_stop_leaves_the_marker(self):
        state = Path(tempfile.mkdtemp()) / "mode.pid"
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(proc.kill)
        state.write_text(f"talk\n{proc.pid}\nm\n", encoding="utf-8")
        with mock.patch.object(modes, "STATE", state):
            self.assertTrue(modes.stop())
        marker = state.with_name(modes.STOPPED_NAME)
        self.assertTrue(marker.is_file())
        self.assertLess(time.time() - marker.stat().st_mtime, 30)
