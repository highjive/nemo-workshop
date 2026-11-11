"""Tests for boot-chain measurement and the lockdown state machine."""
from __future__ import annotations

import sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.admin import AdminStore
from nemo.lockdown import (ALWAYS_ALLOWED, STATE_LOCKED, STATE_OK,
                           STATE_UNSET, Lockdown, Measurement)


def m(**vals) -> Measurement:
    return Measurement(dict(vals), 1000)


BASE = dict(**{"boot:vmlinuz-6.1": "a" * 64,
               "boot:initrd.img-6.1": "b" * 64,
               "efi:bootorder": "c" * 64,
               "bios:version": "1.19",
               "disks": "d" * 64,
               "luks": "yes"})


class TestMeasurement(unittest.TestCase):
    def test_identical_measurements_have_no_diff(self):
        self.assertEqual(m(**BASE).diff(m(**BASE)), [])

    def test_digest_is_order_independent(self):
        a = Measurement({"x": "1", "y": "2"})
        b = Measurement({"y": "2", "x": "1"})
        self.assertEqual(a.digest, b.digest)

    def test_changed_kernel_is_detected(self):
        other = dict(BASE); other["boot:vmlinuz-6.1"] = "z" * 64
        d = m(**other).diff(m(**BASE))
        self.assertEqual(len(d), 1)
        self.assertIn("changed", d[0])

    def test_added_efi_entry_is_detected(self):
        other = dict(BASE); other["efi:Boot0003"] = "e" * 64
        self.assertTrue(any("appeared" in x for x in m(**other).diff(m(**BASE))))

    def test_removed_file_is_detected(self):
        other = dict(BASE); del other["boot:initrd.img-6.1"]
        self.assertTrue(any("disappeared" in x for x in m(**other).diff(m(**BASE))))

    def test_encryption_disappearing_is_detected(self):
        # The loudest possible signal: the machine was reinstalled without
        # full-disk encryption.
        other = dict(BASE); other["luks"] = "no"
        self.assertTrue(m(**other).diff(m(**BASE)))

    def test_firmware_downgrade_is_detected(self):
        other = dict(BASE); other["bios:version"] = "1.06"
        self.assertTrue(m(**other).diff(m(**BASE)))


class TestLockdown(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.l = Lockdown(self.tmp)

    def test_unarmed_reports_no_baseline(self):
        self.assertEqual(self.l.read_state().state, STATE_UNSET)
        self.assertFalse(self.l.read_state().locked)

    def test_arming_then_matching_stays_ok(self):
        self.l.arm(m(**BASE))
        self.assertEqual(self.l.check(m(**BASE)).state, STATE_OK)

    def test_changed_boot_chain_locks(self):
        self.l.arm(m(**BASE))
        other = dict(BASE); other["boot:vmlinuz-6.1"] = "z" * 64
        st = self.l.check(m(**other))
        self.assertEqual(st.state, STATE_LOCKED)
        self.assertTrue(st.changes)

    def test_lock_persists_across_reads(self):
        self.l.arm(m(**BASE))
        other = dict(BASE); other["bios:version"] = "9.99"
        self.l.check(m(**other))
        self.assertTrue(Lockdown(self.tmp).read_state().locked)

    def test_gate_blocks_normal_commands_when_locked(self):
        self.l.arm(m(**BASE))
        other = dict(BASE); other["disks"] = "z" * 64
        self.l.check(m(**other))
        for cmd in ("run", "new", "check", "mode"):
            with self.assertRaises(PermissionError, msg=cmd):
                self.l.gate(cmd)

    def test_gate_allows_recovery_commands_when_locked(self):
        self.l.arm(m(**BASE))
        other = dict(BASE); other["disks"] = "z" * 64
        self.l.check(m(**other))
        for cmd in sorted(ALWAYS_ALLOWED):
            self.l.gate(cmd)          # must not raise

    def test_gate_message_names_the_realistic_cause(self):
        self.l.arm(m(**BASE))
        other = dict(BASE); other["boot:initrd.img-6.1"] = "z" * 64
        self.l.check(m(**other))
        with self.assertRaises(PermissionError) as ctx:
            self.l.gate("run")
        self.assertIn("keylogger", str(ctx.exception))

    def test_unlock_rebaselines(self):
        self.l.arm(m(**BASE))
        other = dict(BASE); other["disks"] = "z" * 64
        self.l.check(m(**other))
        self.assertTrue(self.l.read_state().locked)
        self.l.unlock("investigated, was my own disk swap", m(**other))
        self.assertFalse(self.l.read_state().locked)
        # and the new state is now the accepted one
        self.assertEqual(self.l.check(measure_stub(other)).state, STATE_OK)

    def test_corrupt_state_fails_closed(self):
        self.l.arm(m(**BASE))
        self.l.state_path.write_text("{not json")
        st = self.l.read_state()
        self.assertTrue(st.locked)      # unreadable state is suspicious

    def test_unarmed_gate_never_blocks(self):
        self.l.gate("run")              # must not raise


def measure_stub(vals):
    return Measurement(dict(vals), 2000)


class TestLockdownWithAdmin(unittest.TestCase):
    """The two halves are independent by design; this checks they compose."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.l = Lockdown(self.tmp)
        self.a = AdminStore(self.tmp)
        self.a.set_password("test-admin", "testing-only-123")

    def test_unlock_requires_a_session_in_practice(self):
        self.l.arm(m(**BASE))
        other = dict(BASE); other["luks"] = "no"
        self.l.check(m(**other))
        with self.assertRaises(PermissionError):
            self.a.require_session()            # caller must check this first
        self.a.login("test-admin", "testing-only-123")
        self.a.require_session()
        self.l.unlock()
        self.assertFalse(self.l.read_state().locked)

    def test_lock_events_can_be_audited(self):
        self.l.arm(m(**BASE))
        other = dict(BASE); other["bios:version"] = "9.99"
        st = self.l.check(m(**other))
        self.a.append_audit("boot_lock", {"changes": st.changes})
        ok, msg = self.a.verify_audit()
        self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestRegressions(unittest.TestCase):
    """Bugs found in review."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.l = Lockdown(self.tmp)

    def test_unreadable_field_does_not_lock(self):
        # Baseline taken by the root boot service; check run by the desktop
        # user, where dmidecode returns nothing. This locked a clean machine.
        root = m(**BASE)
        user = dict(BASE)
        user["bios:version"] = "unreadable"
        user["disks"] = "unreadable"
        self.l.arm(root)
        st = self.l.check(m(**user))
        self.assertEqual(st.state, STATE_OK)
        self.assertIn("not readable", st.reason)

    def test_unreadable_is_reported_not_hidden(self):
        self.l.arm(m(**BASE))
        user = dict(BASE); user["disks"] = "unreadable"
        st = self.l.check(m(**user))
        self.assertIn("disks", st.reason)

    def test_real_change_still_locks_alongside_unreadable_fields(self):
        self.l.arm(m(**BASE))
        user = dict(BASE)
        user["bios:version"] = "unreadable"        # privilege
        user["boot:vmlinuz-6.1"] = "z" * 64        # genuine tamper
        self.assertTrue(self.l.check(m(**user)).locked)


class TestAuditConcurrency(unittest.TestCase):
    """O8: append_audit read the last entry's digest, then wrote a new one
    linked to it, with no lock -- two processes racing through that could
    both read the same "last entry" and both link a new record to it,
    forking the chain in a way verify_audit need not catch.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.a = AdminStore(self.tmp)

    def test_many_concurrent_writers_produce_an_intact_chain(self):
        import threading
        n_threads, n_each = 8, 25

        def worker(i):
            for j in range(n_each):
                self.a.append_audit("test_event", {"thread": i, "n": j})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads: t.start()
        for t in threads: t.join()

        lines = [l for l in self.a.audit.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), n_threads * n_each, "a write was lost")
        ok, msg = self.a.verify_audit()
        self.assertTrue(ok, msg)

    def test_a_lock_older_than_the_timeout_is_treated_as_stale(self):
        # A crashed process's lock file must not block every future
        # append forever.
        lock = self.a.audit.with_name(self.a.audit.name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("")
        import os
        old = time.time() - 30
        os.utime(lock, (old, old))
        digest = self.a.append_audit("after_a_stale_lock")
        self.assertTrue(digest)
        self.assertFalse(lock.exists(), "the stale lock should have been cleared")

    def test_a_fresh_lock_held_by_someone_else_does_not_hang_forever(self):
        # proceeds unlocked rather than blocking the caller indefinitely
        lock = self.a.audit.with_name(self.a.audit.name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("")
        t0 = time.time()
        digest = self.a.append_audit("while_locked", )
        self.assertTrue(digest)
        self.assertLess(time.time() - t0, 10)
