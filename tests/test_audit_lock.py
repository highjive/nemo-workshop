"""The audit log's lock must survive what Windows does to a lock file.

D116, found on the real AH531 (Windows 11). The lock is a file created
with O_CREAT | O_EXCL and removed on release. On Windows a removed file
that another thread still has open lingers as "delete pending", and
creating it again in that state is refused with PermissionError, not
FileExistsError. The code handled only FileExistsError, so under
contention the exception escaped append_audit: the caller crashed and its
record was never written. The 8-thread test lost 3 of 200 writes in one
run on the laptop and 5 writers in another, and passed in two others.

The real-thread test in test_lockdown.py only catches this when the timing
falls that way, on Windows. These inject the refusal directly, so they
fail on the old code every time, on any platform.
"""
from __future__ import annotations

import os, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.admin import AdminStore


def denied(path):
    return PermissionError(13, "Permission denied", str(path))


class LockCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = AdminStore(Path(self.tmp.name))
        self.lock = self.a.audit.with_name(self.a.audit.name + ".lock")

    def lines(self):
        return [l for l in self.a.audit.read_text().splitlines() if l.strip()]


class TestCreateRefused(LockCase):
    def refuse_create(self, times):
        """os.open on the lock file raises PermissionError `times` times."""
        real, left = os.open, {"n": times}

        def fake(path, flags, *a, **k):
            if str(path) == str(self.lock) and flags & os.O_EXCL and left["n"] > 0:
                left["n"] -= 1
                raise denied(path)
            return real(path, flags, *a, **k)
        return mock.patch("os.open", fake), left

    def test_a_refused_create_is_retried_and_the_record_is_written(self):
        patch, left = self.refuse_create(3)
        with patch:
            first = self.a.append_audit("one")
            second = self.a.append_audit("two")
        self.assertEqual(left["n"], 0, "the refusal was never exercised")
        self.assertTrue(first and second)
        self.assertEqual(len(self.lines()), 2)
        self.assertEqual(self.a.verify_audit(), (True, "chain intact"))
        self.assertFalse(self.lock.exists(), "the lock was left behind")

    def test_a_create_that_is_always_refused_gives_up_in_bounded_time(self):
        # A folder we genuinely cannot lock in. The documented behaviour is
        # to proceed unlocked rather than freeze or crash the caller.
        patch, _ = self.refuse_create(10 ** 9)
        entered = False
        t0 = time.time()
        with patch:
            with self.a._locked(timeout=0.3):
                entered = True
        self.assertTrue(entered)
        self.assertLess(time.time() - t0, 5)


class TestStatAndUnlinkRefused(LockCase):
    def test_a_lock_that_cannot_be_examined_is_waited_for_not_fatal(self):
        # Someone else holds it, and looking at it is refused (it is being
        # deleted). Released shortly after.
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text("")
        real_stat, calls = Path.stat, {"n": 0}

        def fake_stat(p, *a, **k):
            if str(p) == str(self.lock) and calls["n"] < 3:
                calls["n"] += 1
                if calls["n"] == 3:
                    os.unlink(self.lock)
                raise denied(p)
            return real_stat(p, *a, **k)
        with mock.patch.object(Path, "stat", fake_stat):
            self.assertTrue(self.a.append_audit("after_a_wait"))
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(self.lines()), 1)

    def test_a_refused_release_does_not_lose_the_record_or_raise(self):
        real_unlink, calls = Path.unlink, {"n": 0}

        def fake_unlink(p, *a, **k):
            if str(p) == str(self.lock) and calls["n"] < 2:
                calls["n"] += 1
                raise denied(p)
            return real_unlink(p, *a, **k)
        with mock.patch.object(Path, "unlink", fake_unlink):
            self.assertTrue(self.a.append_audit("released_late"))
        self.assertEqual(calls["n"], 2)
        self.assertEqual(len(self.lines()), 1)
        self.assertFalse(self.lock.exists(), "the release was not retried")


class TestRealContention(LockCase):
    def test_no_writer_dies_and_no_record_is_lost(self):
        # Heavier than the O8 test, and it reports a dead writer as such
        # rather than as a short count.
        n_threads, n_each, died = 12, 20, []

        def worker(i):
            try:
                for j in range(n_each):
                    self.a.append_audit("t", {"thread": i, "n": j})
            except BaseException as exc:                     # noqa: BLE001
                died.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(n_threads)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(died, [])
        self.assertEqual(len(self.lines()), n_threads * n_each)
        self.assertEqual(self.a.verify_audit(), (True, "chain intact"))

    def test_separate_processes_share_one_intact_chain(self):
        # The lock file exists for this case: the desktop interface and a
        # command line running at once. Threads cannot stand in for it,
        # since they now queue on an in-process lock and never contend here.
        import subprocess
        n_procs, n_each = 4, 12
        code = ("import sys; sys.path.insert(0, sys.argv[1])\n"
                "from pathlib import Path\n"
                "from nemo.admin import AdminStore\n"
                "a = AdminStore(Path(sys.argv[2]))\n"
                "for j in range(int(sys.argv[4])):\n"
                "    a.append_audit('p', {'proc': sys.argv[3], 'n': j})\n")
        root = str(Path(__file__).resolve().parent.parent)
        procs = [subprocess.Popen([sys.executable, "-c", code, root,
                                   self.tmp.name, str(i), str(n_each)],
                                  stderr=subprocess.PIPE, text=True)
                 for i in range(n_procs)]
        errors = [p.communicate(timeout=120)[1] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * n_procs,
                         "\n".join(e[-400:] for e in errors if e))
        self.assertEqual(len(self.lines()), n_procs * n_each)
        self.assertEqual(self.a.verify_audit(), (True, "chain intact"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
