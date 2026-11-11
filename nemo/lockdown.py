"""Boot-chain measurement and lockdown.

What this module is for, stated precisely, because the distinction decides
whether it is useful or theatre.

Kon-Boot and its relatives boot from removable media and patch the running
kernel's authentication routine in memory. They do not touch the disk.
Against an unencrypted machine they work, and no software running on that
machine can stop them -- including this module, which would simply be
disabled by the same attacker who bypassed the login.

So this module does NOT claim to block that attack. Full-disk encryption
blocks it, because there is no authentication routine to patch when the
volume is ciphertext and the key is in the operator's head. See
docs/hardening.md.

What this module does is detect that the boot chain changed, on the next
legitimate boot, and refuse to operate until an administrator acknowledges
it. Its security rests on one structural property:

    The baseline lives INSIDE the encrypted volume.

An attacker who boots removable media never decrypts that volume, so they
cannot read the baseline, forge it, or update it after modifying the
bootloader. And an attacker who HAS decrypted it already possesses
everything and lockdown is irrelevant. The mechanism is therefore tamper
evidence for the owner, which is the achievable goal, and is presented as
nothing more than that.

The classic residual risk this addresses is the evil-maid bootloader
keylogger: an encrypted machine left unattended, its unencrypted /boot
replaced with something that captures the passphrase on your next entry.
Encryption alone does not detect that. Measuring /boot does.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

STATE_OK = "ok"
STATE_LOCKED = "locked"
STATE_UNSET = "no-baseline"

# Commands whose whole purpose is to resolve a lockdown, so they must stay
# reachable while locked. Everything else is refused.
ALWAYS_ALLOWED = {"admin", "lock", "doctor", "maint", "master"}


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()


def root_is_encrypted() -> bool:
    """Is the root filesystem itself on a LUKS volume?

    Walks root's own device chain. An earlier revision asked whether ANY
    block device was of type crypt, so an encrypted USB stick plugged into
    an unencrypted laptop made this return True -- and 'nemo lock baseline'
    would then arm on a disk an attacker can freely rewrite, defeating the
    refusal that exists to prevent exactly that.
    """
    source = _run(["findmnt", "-no", "SOURCE", "/"])
    if not source:
        return False
    # -s lists the device and its ancestors (inverse dependency order).
    chain = _run(["lsblk", "-sno", "TYPE", source])
    return "crypt" in chain.split()


@dataclass
class Measurement:
    """One observation of the boot chain."""

    values: dict[str, str] = field(default_factory=dict)
    taken_at: int = 0

    @property
    def digest(self) -> str:
        body = json.dumps(self.values, sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()

    UNREADABLE = "unreadable"

    def diff(self, other: "Measurement") -> list[str]:
        """Differences against a baseline.

        A field that was readable when the baseline was taken and is not
        readable now (or the reverse) is a privilege difference, not a
        tamper event, and is reported separately rather than triggering a
        lock. The alternative -- treating it as a change -- makes the
        mechanism fire whenever the same check runs as a different user.
        """
        out = []
        keys = set(self.values) | set(other.values)
        for k in sorted(keys):
            a, b = other.values.get(k), self.values.get(k)
            if a == b:
                continue
            if self.UNREADABLE in (a, b):
                continue
            if a is None:
                out.append(f"{k}: appeared ({b[:16]}...)")
            elif b is None:
                out.append(f"{k}: disappeared")
            else:
                out.append(f"{k}: changed ({a[:16]}... -> {b[:16]}...)")
        return out


def measure() -> Measurement:
    """Take a boot-chain measurement.

    Deliberately excludes things that change legitimately -- a plugged-in
    mouse, a mounted USB stick -- because a tamper alarm that cries wolf is
    an alarm that gets disabled. Only boot-relevant state is measured.
    """
    v: dict[str, str] = {}

    if IS_WINDOWS:
        # Without a TPM there is no measured boot to read, so this is a
        # weaker observation than the Linux path and is labelled as such.
        v["bcd"] = hashlib.sha256(
            _run(["bcdedit", "/enum", "all"]).encode()).hexdigest()
        v["secureboot"] = _run([
            "powershell", "-NoProfile", "-Command",
            "try{(Confirm-SecureBootUEFI).ToString()}catch{'unavailable'}"])
        v["firmware"] = _run([
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion"])
        v["disk_signature"] = _run([
            "powershell", "-NoProfile", "-Command",
            "(Get-Disk | Select-Object -First 1).Signature"])
        return Measurement(v, int(time.time()))

    # --- kernel and initramfs ---------------------------------------
    boot = Path("/boot")
    if boot.exists():
        for pattern in ("vmlinuz*", "initrd.img*", "grub/grub.cfg",
                        "grub/x86_64-efi/core.efi", "grub/i386-pc/core.img"):
            for f in sorted(boot.glob(pattern)):
                if f.is_file():
                    v[f"boot:{f.relative_to(boot)}"] = _hash_file(f)

    # --- EFI boot entries -------------------------------------------
    efi = _run(["efibootmgr", "-v"])
    if efi:
        v["efi:bootorder"] = hashlib.sha256(efi.encode()).hexdigest()
    else:
        # Legacy BIOS. Worth recording, because a machine that gains UEFI
        # entries between boots has had its firmware settings changed.
        v["efi:bootorder"] = "legacy-or-unavailable"

    # --- firmware ----------------------------------------------------
    # dmidecode needs root. Recording "unreadable" rather than omitting the
    # key matters: an omitted key looks like a removed component, so a
    # baseline taken by the boot service (root) and a check run by the
    # desktop user (not root) would differ on every single field and lock a
    # perfectly clean machine. A tamper alarm that fires on privilege level
    # is one that gets switched off within a week.
    for key, arg in (("bios:version", "bios-version"),
                     ("bios:date", "bios-release-date")):
        v[key] = _run(["dmidecode", "-s", arg]) or "unreadable"

    # --- fixed storage ----------------------------------------------
    # Internal disks only. A new internal disk, or a changed serial, means
    # the machine was opened.
    lsblk = _run(["lsblk", "-dno", "NAME,SIZE,SERIAL,TYPE"])
    fixed = [ln for ln in lsblk.splitlines()
             if ln.strip() and not ln.split()[0].startswith(("sr", "loop"))]
    v["disks"] = (hashlib.sha256("\n".join(sorted(fixed)).encode()).hexdigest()
                  if fixed else "unreadable")

    # --- whether the root filesystem is actually encrypted -----------
    # A machine that was encrypted and now is not has been reinstalled.
    v["luks"] = "yes" if root_is_encrypted() else "no"

    return Measurement(v, int(time.time()))


@dataclass
class LockState:
    state: str
    reason: str = ""
    changes: list[str] = field(default_factory=list)
    since: int = 0

    @property
    def locked(self) -> bool:
        return self.state == STATE_LOCKED


class Lockdown:
    """Baseline storage and the lock state machine.

    The baseline path must sit inside the encrypted volume. On the ISO
    distribution that is the installed root filesystem; the installer
    refuses to arm lockdown if LUKS is absent, because an unencrypted
    baseline is one the attacker can simply rewrite.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.baseline_path = self.root / "boot.baseline"
        self.state_path = self.root / "lock.state"

    # ----------------------------------------------------------------

    def armed(self) -> bool:
        return self.baseline_path.exists()

    def arm(self, m: Measurement | None = None) -> Measurement:
        m = m or measure()
        self.root.mkdir(parents=True, exist_ok=True)
        self.baseline_path.write_text(json.dumps(
            {"values": m.values, "taken_at": m.taken_at,
             "digest": m.digest}, indent=2, sort_keys=True), encoding="utf-8")
        self._write_state(LockState(STATE_OK, "baseline recorded",
                                    since=int(time.time())))
        return m

    def baseline(self) -> Measurement | None:
        if not self.baseline_path.exists():
            return None
        try:
            doc = json.loads(self.baseline_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return Measurement(doc.get("values", {}), doc.get("taken_at", 0))

    # ----------------------------------------------------------------

    def _write_state(self, st: LockState) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "state": st.state, "reason": st.reason,
            "changes": st.changes, "since": st.since}), encoding="utf-8")

    def read_state(self) -> LockState:
        if not self.armed():
            return LockState(STATE_UNSET, "no baseline recorded")
        if not self.state_path.exists():
            return LockState(STATE_OK, "no state recorded yet")
        try:
            doc = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # An unreadable state file is itself suspicious; fail closed.
            return LockState(STATE_LOCKED, "lock state unreadable")
        return LockState(doc.get("state", STATE_OK), doc.get("reason", ""),
                         doc.get("changes", []), doc.get("since", 0))

    # ----------------------------------------------------------------

    def check(self, m: Measurement | None = None) -> LockState:
        """Compare the current boot chain against the baseline.

        Called at boot by the bootcheck service. Locks on any difference.
        """
        base = self.baseline()
        if base is None:
            return LockState(STATE_UNSET, "no baseline recorded")

        current = m or measure()
        changes = current.diff(base)

        # Say so when a field could not be compared, so a check that is
        # quietly seeing less than the baseline did is visible rather than
        # passing silently.
        unreadable = sorted(k for k, val in current.values.items()
                            if val == Measurement.UNREADABLE
                            and base.values.get(k) != Measurement.UNREADABLE)
        if not changes:
            reason = "boot chain matches baseline"
            if unreadable:
                reason += (f"; {len(unreadable)} field(s) not readable at "
                           "this privilege level and therefore unchecked: "
                           + ", ".join(unreadable))
            st = LockState(STATE_OK, reason, since=int(time.time()))
            self._write_state(st)
            return st

        st = LockState(
            STATE_LOCKED,
            f"{len(changes)} change(s) in the boot chain since the baseline",
            changes, int(time.time()))
        self._write_state(st)
        return st

    def unlock(self, note: str = "",
               m: Measurement | None = None) -> LockState:
        """Clear the lock and re-baseline.

        Takes the measurement rather than re-measuring, so the state being
        accepted is exactly the state that triggered the lock. Re-measuring
        here would silently accept anything that changed in between, which
        is a small window but the wrong one to leave open in this
        particular function.

        Callers must have verified an admin session first; this class does
        not authenticate, so that the authentication and the state machine
        can be tested independently.
        """
        self.arm(m)
        st = LockState(STATE_OK, note or "unlocked by administrator",
                       since=int(time.time()))
        self._write_state(st)
        return st

    # ----------------------------------------------------------------

    def gate(self, command: str) -> None:
        """Refuse a command while locked.

        Honest about its own limits: this stops the assistant from
        operating on a machine whose boot chain changed. It does not stop
        anyone who already has a shell.
        """
        st = self.read_state()
        if not st.locked:
            return
        if command in ALWAYS_ALLOWED:
            return
        raise PermissionError(
            "LOCKED: the boot chain changed since the recorded baseline.\n"
            + "\n".join(f"  - {c}" for c in st.changes[:8])
            + "\n\nInvestigate before clearing this. If you did not change "
              "the bootloader, firmware settings or disks yourself, treat "
              "the machine as compromised: the realistic cause is a "
              "bootloader keylogger placed to capture your encryption "
              "passphrase.\n"
              "Clear with: nemo admin login && nemo lock unlock")
