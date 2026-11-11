"""Administrator access to the safety parameters.

Three mechanisms, and it is worth being explicit about what each one can
and cannot do on a laptop that travels.

  Authentication    scrypt, stdlib, no dependency to install on a slow
                    machine. Stops casual access to the admin commands.

  Lockout           exponential backoff on failed attempts. Makes online
                    guessing impractical. Does NOT stop anyone who can
                    read the disk.

  Audit chain       every attempt and every change appended to a
                    hash-chained log. Cannot prevent tampering; makes it
                    detectable, which on this threat model is the
                    achievable goal.

What is deliberately NOT here is a mechanism that destroys data after
failed password attempts. The reasoning is in docs/security.md and in the
paper, but in short: it reliably fires on typos and key-repeat, and never
fires on the actual threat, because anyone with physical access reads the
drive directly rather than typing at a prompt. Confidentiality against
physical access is LUKS full-disk encryption, which the ISO installer
enables. This module assumes that is doing its job and does not pretend to
substitute for it.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# scrypt parameters. n=2**14 costs roughly 100 ms on a Sandy Bridge core --
# slow enough to matter for guessing, fast enough that an administrator who
# knows the password is not left waiting.
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}

# Backoff schedule in seconds, by consecutive failure count. Caps rather
# than escalating indefinitely: an hour is already impractical for guessing,
# and anything longer only ever punishes the legitimate owner.
_BACKOFF = [0, 0, 5, 30, 120, 600, 1800, 3600]

SESSION_SECONDS = 900

# D116: one lock per audit log for the threads of this process. The lock
# file below is for other processes; between threads it starved writers
# into its own give-up path.
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(str(path)))
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@dataclass
class AuthResult:
    ok: bool
    message: str
    wait_s: int = 0


class AdminStore:
    """State on disk: credential, failure counter, audit chain."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.cred = self.root / "admin.cred"
        self.state = self.root / "admin.state"
        self.audit = self.root / "audit.log"
        self.session = self.root / "admin.session"
        self.policy = self.root / "policy.yaml"

    # ----------------------------------------------------------------
    # credential
    # ----------------------------------------------------------------

    def set_password(self, username: str, password: str) -> None:
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "username": username,
            "salt": salt.hex(),
            "hash": digest.hex(),
            "scrypt": {k: v for k, v in _SCRYPT.items()},
            "set_at": int(time.time()),
        }
        self.cred.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self.cred, 0o600)
        except OSError:
            pass          # Windows; ACLs are the installer's job there
        self.append_audit("credential_set", {"username": username})

    def has_password(self) -> bool:
        return self.cred.exists()

    def _verify(self, username: str, password: str) -> bool:
        if not self.cred.exists():
            return False
        try:
            doc = json.loads(self.cred.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if username != doc.get("username"):
            # Still do the work, so a wrong username is not distinguishable
            # from a wrong password by how long the answer takes.
            hashlib.scrypt(password.encode(), salt=b"0" * 16, **_SCRYPT)
            return False
        params = doc.get("scrypt", _SCRYPT)
        try:
            digest = hashlib.scrypt(
                password.encode(), salt=bytes.fromhex(doc["salt"]),
                n=int(params["n"]), r=int(params["r"]),
                p=int(params["p"]), dklen=int(params.get("dklen", 32)))
        except (ValueError, KeyError):
            return False
        return hmac.compare_digest(digest.hex(), doc.get("hash", ""))

    # ----------------------------------------------------------------
    # lockout
    # ----------------------------------------------------------------

    def _read_state(self) -> dict:
        if not self.state.exists():
            return {"failures": 0, "last_failure": 0}
        try:
            return json.loads(self.state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"failures": 0, "last_failure": 0}

    def _write_state(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state.write_text(json.dumps(data), encoding="utf-8")

    def wait_remaining(self) -> int:
        st = self._read_state()
        n = min(int(st.get("failures", 0)), len(_BACKOFF) - 1)
        delay = _BACKOFF[n]
        if delay == 0:
            return 0
        elapsed = time.time() - float(st.get("last_failure", 0))
        return max(0, int(delay - elapsed))

    # ----------------------------------------------------------------
    # audit chain
    # ----------------------------------------------------------------

    @contextlib.contextmanager
    def _locked(self, timeout: float = 5.0):
        """A portable, best-effort exclusive lock for the audit log.

        O8: append_audit reads the last entry's digest, then writes a new
        one linked to it. Two processes racing through that read-then-write
        could both read the same "last entry" and both link a new record
        to it, forking the chain in a way verify_audit need not catch.

        Built from atomic file creation (O_CREAT | O_EXCL) rather than
        fcntl or msvcrt, since that works identically on Windows and
        POSIX with no platform branch and no extra dependency. A lock
        file older than `timeout` is treated as stale -- almost certainly
        a crashed process that never released it, not real contention --
        and cleared rather than left to block every future admin command
        forever. If a fresh lock still will not clear in time, this gives
        up and proceeds unlocked: a missed lock on a single-user laptop is
        far better than a frozen admin command.

        D116: "works identically on Windows" was not true. A lock file
        that has been removed while another thread still has it open
        lingers there as delete-pending, and creating, examining or
        removing it in that state is refused with PermissionError rather
        than FileExistsError or FileNotFoundError. That escaped
        append_audit, so the caller crashed and its record was never
        written. A refusal is now waited out like any other contention,
        inside the same timeout.

        The second half of D116: with the crash gone, writers still forked
        the chain. Polling every 20 ms is not a queue, so among a dozen
        threads on the real laptop one could go unserved for the whole
        timeout (4.6 s was measured), give up, and write unlocked. Threads
        of one process now wait on an ordinary threading.Lock first, which
        has no give-up, and only its holder touches the lock file. The
        give-up remains for a lock file held by ANOTHER process, so
        between processes this is still best effort, as stated above.
        """
        with _thread_lock(self.audit):
            with self._file_locked(timeout):
                yield

    @contextlib.contextmanager
    def _file_locked(self, timeout: float):
        lock_path = self.audit.with_name(self.audit.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()
        fd = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                try:
                    stale = time.time() - lock_path.stat().st_mtime > timeout
                except FileNotFoundError:
                    continue                      # it was released between the two calls
                except PermissionError:
                    stale = False                 # being deleted; it will be gone shortly
                if stale:
                    try:
                        lock_path.unlink()
                        continue
                    except FileNotFoundError:
                        continue
                    except PermissionError:
                        pass                      # someone has it open; wait below
            except PermissionError:
                pass                              # delete-pending, or a folder we cannot write
            if time.time() - start > timeout:
                break
            time.sleep(0.02)
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
                # A waiter may be looking at the file at this instant. Left
                # behind, it would hold everyone up until it went stale.
                for _ in range(50):
                    try:
                        lock_path.unlink()
                        break
                    except FileNotFoundError:
                        break
                    except PermissionError:
                        time.sleep(0.01)

    def append_audit(self, event: str, detail: dict | None = None) -> str:
        """Append one tamper-evident record and return its digest.

        Each entry carries the digest of the one before it, so removing or
        editing any line invalidates every line after it. An attacker with
        write access can still delete the whole file -- nothing on an
        unencrypted disk prevents that -- but they cannot quietly remove a
        single failed-login record, which is the realistic case.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        with self._locked():
            prev = "0" * 64
            if self.audit.exists():
                lines = [l for l in self.audit.read_text(encoding="utf-8").splitlines() if l.strip()]
                if lines:
                    try:
                        prev = json.loads(lines[-1])["digest"]
                    except (json.JSONDecodeError, KeyError):
                        prev = "BROKEN"
            record = {
                "ts": int(time.time()),
                "event": event,
                "detail": detail or {},
                "prev": prev,
            }
            body = json.dumps(record, sort_keys=True)
            record["digest"] = hashlib.sha256((prev + body).encode()).hexdigest()
            with self.audit.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
            return record["digest"]

    def verify_audit(self) -> tuple[bool, str]:
        if not self.audit.exists():
            return True, "no audit log yet"
        prev = "0" * 64
        for i, line in enumerate(self.audit.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                return False, f"line {i} is not valid JSON"
            if rec.get("prev") != prev:
                return False, f"chain breaks at line {i}: an entry was removed or edited"
            digest = rec.pop("digest", "")
            body = json.dumps(rec, sort_keys=True)
            if hashlib.sha256((prev + body).encode()).hexdigest() != digest:
                return False, f"line {i} has been modified"
            prev = digest
        return True, "chain intact"

    def audit_entries(self, limit: int = 20) -> list[dict]:
        if not self.audit.exists():
            return []
        lines = [l for l in self.audit.read_text(encoding="utf-8").splitlines() if l.strip()]
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    # ----------------------------------------------------------------
    # login
    # ----------------------------------------------------------------

    def login(self, username: str, password: str) -> AuthResult:
        wait = self.wait_remaining()
        if wait > 0:
            self.append_audit("login_throttled", {"username": username,
                                                  "wait_s": wait})
            return AuthResult(
                False,
                f"locked out for another {wait}s after repeated failures",
                wait)

        if self._verify(username, password):
            self._write_state({"failures": 0, "last_failure": 0})
            token = secrets.token_hex(16)
            self.session.write_text(json.dumps({
                "token": token, "user": username,
                "expires": int(time.time()) + SESSION_SECONDS}), encoding="utf-8")
            try:
                os.chmod(self.session, 0o600)
            except OSError:
                pass
            self.append_audit("login_ok", {"username": username})
            return AuthResult(True, f"signed in for {SESSION_SECONDS // 60} minutes")

        st = self._read_state()
        failures = int(st.get("failures", 0)) + 1
        self._write_state({"failures": failures, "last_failure": time.time()})
        nxt = _BACKOFF[min(failures, len(_BACKOFF) - 1)]
        self.append_audit("login_failed",
                          {"username": username, "consecutive": failures})
        # No data is destroyed here, by design. See the module docstring.
        msg = "incorrect username or password"
        if nxt:
            msg += f"; next attempt in {nxt}s"
        return AuthResult(False, msg, nxt)

    def logout(self) -> None:
        self.session.unlink(missing_ok=True)
        self.append_audit("logout", {})

    def signed_in(self) -> bool:
        if not self.session.exists():
            return False
        try:
            doc = json.loads(self.session.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if int(doc.get("expires", 0)) < time.time():
            self.session.unlink(missing_ok=True)
            return False
        return True

    def require_session(self) -> None:
        if not self.signed_in():
            raise PermissionError(
                "not signed in. Run: nemo admin login")
