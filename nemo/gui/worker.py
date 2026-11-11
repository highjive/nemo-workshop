"""Run a 'nemo' command in the background and stream its output.

A model step can take several minutes on the AH531. Running it in a child
process keeps the window responsive, and means Stop can end it for real:
a thread cannot be killed, a process can. The child and anything it starts
(KiCad, PlatformIO) share a process group so they are stopped together.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time


class Job:
    def __init__(self, argv: list[str], cwd: str | None = None):
        self.argv = argv
        self.cwd = cwd
        self.lines: "queue.Queue[str]" = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self.returncode: int | None = None
        self.started = 0.0
        self.stopped = False

    def start(self) -> "Job":
        kw = {}
        if sys.platform.startswith("win"):
            # No console window flashing up, and a group we can end as one.
            kw["creationflags"] = (subprocess.CREATE_NO_WINDOW |
                                   subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            kw["start_new_session"] = True
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            self.argv, cwd=self.cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **kw)
        self.started = time.time()
        threading.Thread(target=self._pump, daemon=True).start()
        return self

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            for line in self.proc.stdout:
                self.lines.put(line.rstrip("\n"))
        finally:
            # Popen does not close its pipe file objects on its own -- only
            # communicate() or a context manager does that. Left open, each
            # Job (one per draft, outline, or mode-load) leaked a file
            # descriptor for the life of the GUI process; a long session of
            # story drafting would eventually run out of them.
            self.proc.stdout.close()
            self.returncode = self.proc.wait()

    @property
    def running(self) -> bool:
        return self.proc is not None and self.returncode is None

    @property
    def elapsed(self) -> float:
        return time.time() - self.started if self.started else 0.0

    def drain(self) -> list[str]:
        out = []
        while True:
            try:
                out.append(self.lines.get_nowait())
            except queue.Empty:
                return out

    def stop(self) -> None:
        if not self.running or not self.proc:
            return
        self.stopped = True
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/T", "/F", "/PID",
                                str(self.proc.pid)],
                               capture_output=True, creationflags=0x08000000)
            else:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
