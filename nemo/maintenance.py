"""Maintenance operations for a clone: halt, resume, reset, diagnose.

The requirement: if a clone misbehaves, the master must be able to stop it
and restore it to a working state for diagnosis, without the clone having to
be wiped and reinstalled. Its projects and history must survive.

Every operation except diagnose is a document signed with the master key,
and every one carries three properties that are not optional:

  Target    bound to one clone's ID. Without this a single halt document is
            a universal kill switch for every clone that exists, and one
            leaked copy disables all of them.

  Expiry    valid for hours, not forever. A halt issued for a fault last
            spring must not still work next year.

  Nonce     usable exactly once per clone. The same document presented
            twice is refused, so a captured document cannot be replayed to
            halt a clone again after it has been fixed and resumed.

A note on what halt is and is not. It is a cooperative stop: an unmodified
clone honours it. A clone whose owner has edited the code can ignore it --
the same limit documented for every control in this package. For THIS
purpose that limit barely matters. Maintenance mode exists to diagnose a
malfunctioning clone, where the clone is not an adversary; cooperation is
exactly the right model, and the clone wants to be fixed.

Nothing here deletes user data. Halt freezes. Reset restores configuration.
Projects, the audit log and the local credential are never touched.
"""

from __future__ import annotations

import json
import platform
import re
import secrets
import shutil
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .signing import SigningError, sign_bytes, verify_bytes

DOC_VERSION = 2            # bumped: target_nonce (revoke) joined the signed payload
ACTIONS = ("halt", "resume", "reset", "revoke")
WILDCARD = "*"

# Hard ceiling on how long a document may live, regardless of what the
# signer asked for. A document that outlives the fault it was issued for is
# a liability, not a convenience.
MAX_VALIDITY_S = 7 * 24 * 3600

# Commands still permitted while halted. Everything needed to diagnose and
# recover; nothing that runs the design pipeline.
HALT_ALLOWED = {"admin", "lock", "doctor", "maint", "master", "status",
                "parts"}


# ====================================================================
#  Clone identity
# ====================================================================

def clone_id(store: Path) -> str:
    """This install's stable identity, created on first use.

    Excluded from clone images (see master.CLONE_EXCLUDE), so each clone
    generates its own on first boot. A shared ID would make target binding
    meaningless: a document for one clone would halt all of them.
    """
    path = Path(store) / "clone.id"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = str(uuid.uuid4())
    path.write_text(value + "\n", encoding="utf-8")
    return value


# ====================================================================
#  Operation documents
# ====================================================================

@dataclass
class OperationDocument:
    action: str
    target: str
    nonce: str
    issued_at: int
    expires_at: int
    note: str = ""
    target_nonce: str = ""        # revoke only: the nonce being revoked
    signature: str = ""

    def payload(self) -> bytes:
        return json.dumps({
            "version": DOC_VERSION, "action": self.action,
            "target": self.target, "nonce": self.nonce,
            "issued_at": self.issued_at, "expires_at": self.expires_at,
            "note": self.note, "target_nonce": self.target_nonce,
        }, sort_keys=True, separators=(",", ":")).encode()

    def to_json(self) -> str:
        return json.dumps({
            "version": DOC_VERSION, "action": self.action,
            "target": self.target, "nonce": self.nonce,
            "issued_at": self.issued_at, "expires_at": self.expires_at,
            "note": self.note, "target_nonce": self.target_nonce,
            "signature": self.signature,
        }, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "OperationDocument":
        try:
            d = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SigningError(f"not a valid operation document: {exc}") from exc
        if d.get("version") != DOC_VERSION:
            raise SigningError(f"unsupported document version {d.get('version')}")
        need = ("action", "target", "nonce", "issued_at", "expires_at",
                "signature")
        missing = [k for k in need if k not in d]
        if missing:
            raise SigningError(f"document is missing: {', '.join(missing)}")
        return cls(action=d["action"], target=d["target"], nonce=d["nonce"],
                   issued_at=int(d["issued_at"]),
                   expires_at=int(d["expires_at"]), note=d.get("note", ""),
                   target_nonce=d.get("target_nonce", ""),
                   signature=d["signature"])


def sign_operation(private_key: Path, action: str, target: str,
                   hours: float = 24, note: str = "",
                   target_nonce: str = "") -> OperationDocument:
    """Issue an operation. Author-side only."""
    if action not in ACTIONS:
        raise SigningError(f"unknown action {action!r}; one of {ACTIONS}")
    if not target:
        raise SigningError("a target clone ID is required. Use '*' only if "
                           "you genuinely mean every clone.")
    if action == "revoke" and not target_nonce:
        raise SigningError("a revoke document must name the nonce it revokes")
    now = int(time.time())
    lifetime = min(int(hours * 3600), MAX_VALIDITY_S)
    doc = OperationDocument(action=action, target=target,
                            nonce=secrets.token_hex(16), issued_at=now,
                            expires_at=now + lifetime, note=note,
                            target_nonce=target_nonce)
    doc.signature = sign_bytes(private_key, doc.payload())
    return doc


# ====================================================================
#  State
# ====================================================================

@dataclass
class MaintState:
    halted: bool = False
    reason: str = ""
    since: int = 0
    by_nonce: str = ""
    history: list = field(default_factory=list)


class Maintenance:
    def __init__(self, store: Path, public_key_hex: str):
        self.store = Path(store)
        self.pub = public_key_hex
        self.state_path = self.store / "maint.state"
        self.used_path = self.store / "maint.used"

    # --- persistence ------------------------------------------------

    def read(self) -> MaintState:
        if not self.state_path.exists():
            return MaintState()
        try:
            d = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # An unreadable state file after a halt must not silently
            # resume the clone. Fail towards halted.
            return MaintState(True, "maintenance state unreadable")
        return MaintState(d.get("halted", False), d.get("reason", ""),
                          d.get("since", 0), d.get("by_nonce", ""),
                          d.get("history", []))

    def _write(self, st: MaintState) -> None:
        self.store.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "halted": st.halted, "reason": st.reason, "since": st.since,
            "by_nonce": st.by_nonce, "history": st.history[-50:]}, indent=2), encoding="utf-8")

    def _used(self) -> set[str]:
        if not self.used_path.exists():
            return set()
        return {ln.strip() for ln in self.used_path.read_text(encoding="utf-8").splitlines()
                if ln.strip()}

    def _mark_used(self, nonce: str) -> None:
        self.store.mkdir(parents=True, exist_ok=True)
        with self.used_path.open("a", encoding="utf-8") as fh:
            fh.write(nonce + "\n")

    # --- verification -----------------------------------------------

    def verify(self, doc: OperationDocument, now: int | None = None) -> None:
        """Every check an operation must pass. Raises on the first failure."""
        if not self.pub:
            raise SigningError("this build has no master public key embedded")

        verify_bytes(doc.payload(), doc.signature, self.pub)

        if doc.action not in ACTIONS:
            raise SigningError(f"unknown action {doc.action!r}")

        mine = clone_id(self.store)
        if doc.target not in (mine, WILDCARD):
            raise SigningError(
                f"this document targets clone {doc.target[:8]}..., but this "
                f"is clone {mine[:8]}... It was issued for a different "
                "machine and will not act on this one.")

        now = int(time.time()) if now is None else now
        if doc.issued_at > now + 300:
            skew_h = (doc.issued_at - now) / 3600
            raise SigningError(
                f"document is dated {skew_h:.1f}h in the future relative to "
                "this machine's clock. Check THIS machine first: a laptop of "
                "this age very likely has a dead CMOS coin cell, which resets "
                "the clock on every power loss. Connect to a network so NTP "
                "can correct it, or set it by hand, then retry.")
        if now > doc.expires_at:
            hrs = (now - doc.expires_at) / 3600
            raise SigningError(
                f"document expired {hrs:.1f}h ago by this machine's clock. "
                "If it was issued recently, this machine's clock is probably "
                "wrong rather than the document being old. Otherwise, issue "
                "a new one.")
        if doc.expires_at - doc.issued_at > MAX_VALIDITY_S:
            raise SigningError("document validity exceeds the permitted "
                               "maximum and was not issued by this tooling")

        if doc.nonce in self._used():
            raise SigningError(
                "this document has already been used on this clone. A "
                "captured document cannot be replayed; issue a new one.")

        if doc.action == "revoke" and not doc.target_nonce:
            raise SigningError("a revoke document must name the nonce it "
                               "revokes")

    # --- operations -------------------------------------------------

    def apply(self, doc: OperationDocument, now: int | None = None,
              audit=None) -> str:
        self.verify(doc, now)
        fn = {"halt": self._halt, "resume": self._resume,
              "reset": self._reset, "revoke": self._revoke}[doc.action]
        message = fn(doc)
        # Marked only after the action succeeds. Marking first meant a
        # failure part-way through -- a full disk during reset, say --
        # consumed the document and it could not be retried. All three
        # actions are idempotent, so a retry after a crash is safe.
        self._mark_used(doc.nonce)
        if audit is not None:
            audit.append_audit(f"maint_{doc.action}", {
                "nonce": doc.nonce[:12], "target": doc.target[:8],
                "note": doc.note})
        return message

    def _halt(self, doc: OperationDocument) -> str:
        st = self.read()
        st.halted = True
        st.reason = doc.note or "halted by master for diagnosis"
        st.since = int(time.time())
        st.by_nonce = doc.nonce[:12]
        st.history.append({"action": "halt", "at": st.since,
                           "note": doc.note})
        self._write(st)
        return ("halted. The design pipeline will not run until a signed "
                "resume is applied. Projects, history and credentials are "
                "untouched. Run 'nemo maint diagnose' to collect a report.")

    def _resume(self, doc: OperationDocument) -> str:
        st = self.read()
        was = st.halted
        st.halted = False
        st.reason = ""
        st.history.append({"action": "resume", "at": int(time.time()),
                           "note": doc.note})
        self._write(st)
        return "resumed" if was else "was not halted; nothing to resume"

    def _revoke(self, doc: OperationDocument) -> str:
        """O6: there was previously no way to neutralise a document known
        or suspected to be compromised before its validity window ran out
        on its own, up to seven days. This does not reach a clone over a
        network -- nothing here does, by design -- it gives the author a
        document, delivered the same way any other maintenance document
        already is, that marks a specific other document's nonce used the
        moment it is applied, so a copy of that document presented later
        is refused exactly like any other replay.
        """
        already = doc.target_nonce in self._used()
        if not already:
            self._mark_used(doc.target_nonce)
        st = self.read()
        st.history.append({"action": "revoke", "at": int(time.time()),
                           "note": doc.note, "target_nonce": doc.target_nonce[:16]})
        self._write(st)
        if already:
            return (f"nonce {doc.target_nonce[:12]}... was already used on "
                    "this clone before this revoke arrived -- the document "
                    "it belonged to already ran, or was already revoked. "
                    "Nothing to prevent now.")
        return (f"nonce {doc.target_nonce[:12]}... is now marked used. Any "
                "document carrying that nonce will be refused as already "
                "used if presented to this clone, including the first time.")

    def _reset(self, doc: OperationDocument) -> str:
        """Restore configuration to a known-good state. Never user data.

        Cleared: local policy (reverts to the signed or default floor),
        lock state, running mode, maintenance halt.
        Kept: projects, audit log, local credential, signed floor, models.
        The audit log is kept deliberately -- it is the evidence the
        diagnosis needs, and clearing it would destroy the record of the
        fault being investigated.
        """
        cleared = []
        for name in ("policy.yaml", "lock.state", "boot.baseline"):
            p = self.store / name
            if p.exists():
                backup = self.store / f"{name}.pre-reset-{int(time.time())}"
                shutil.copy2(p, backup)
                p.unlink()
                cleared.append(name)
        pid = self.store.parent / "mode.pid"
        if pid.exists():
            pid.unlink(); cleared.append("mode.pid")

        st = self.read()
        st.halted = False
        st.reason = ""
        st.history.append({"action": "reset", "at": int(time.time()),
                           "note": doc.note, "cleared": cleared})
        self._write(st)
        what = ", ".join(cleared) if cleared else "nothing needed clearing"
        return (f"reset. Cleared: {what}. Copies kept as *.pre-reset-* "
                "beside each file. Projects, audit log and credentials were "
                "not touched. Re-arm the boot baseline with "
                "'sudo nemo lock baseline' if it was cleared.")

    # --- gate -------------------------------------------------------

    def gate(self, command: str) -> None:
        st = self.read()
        if not st.halted or command in HALT_ALLOWED:
            return
        raise PermissionError(
            "HALTED for maintenance"
            + (f": {st.reason}" if st.reason else "")
            + ".\n  The design pipeline is disabled until a signed resume is "
              "applied.\n  Nothing has been deleted.\n"
              "  Collect a report for diagnosis: nemo maint diagnose")


# ====================================================================
#  Diagnosis -- open to anyone, because it only reads, and never secrets
# ====================================================================

# Never included in a diagnostic bundle, whoever requests it.
NEVER_BUNDLE = {"admin.cred", "admin.session", "maint.used", ".env"}

# Keys belong in the environment, but people paste them into config files
# anyway. Anything shaped like one is redacted from every text file in the
# bundle, because the bundle is sent to someone else.
_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),              # OpenAI-style
    re.compile(r"sk-or-[A-Za-z0-9_\-]{16,}"),           # OpenRouter
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),          # Anthropic
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),             # Google
    re.compile(r"nvapi-[A-Za-z0-9_\-]{16,}"),           # NVIDIA
    re.compile(r"hf_[A-Za-z0-9]{20,}"),                 # Hugging Face --
        # the model downloader's own provider; a gated model needs one.
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)"
               r"['\"]?[^\s'\"]{8,}"),
    re.compile(r"(?i)(bearer)(\s+)[A-Za-z0-9_\-\.]{16,}"),
        # O9: a pasted curl command or raw HTTP request carries the key
        # after "Bearer ", not after "key=" or "token:" -- the one existing
        # catch-all pattern never matched that shape at all. The secret
        # itself is deliberately left out of the capture groups, matching
        # the api-key pattern's own convention, so the substitution below
        # (group 1 + group 2 + "[REDACTED]") cannot keep it in the output.
]


def redact(text: str) -> tuple[str, int]:
    count = 0
    for pat in _KEY_PATTERNS:
        def _sub(m):
            nonlocal count
            count += 1
            if m.lastindex and m.lastindex >= 2:
                return m.group(1) + m.group(2) + "[REDACTED]"
            return "[REDACTED]"
        text = pat.sub(_sub, text)
    return text, count


def diagnose(home: Path, out_dir: Path, extras: dict | None = None) -> Path:
    """Collect everything needed to diagnose a clone into one zip.

    Deliberately excludes the credential hash, live session tokens, the
    used-nonce list, API keys, and project contents. A diagnostic bundle is
    something you email to someone; it must be safe to email.
    """
    home = Path(home)
    store = home / "admin"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bundle = out_dir / f"nemo-diagnose-{stamp}.zip"

    report = {
        "generated": stamp,
        "clone_id": clone_id(store),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
    }
    if extras:
        report.update(extras)

    redacted_total = 0

    def add(z, f: Path, arcname: str) -> None:
        nonlocal redacted_total
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            z.write(f, arcname)
            return
        clean, n = redact(text)
        redacted_total += n
        z.writestr(arcname, clean)

    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.json", json.dumps(report, indent=2, default=str))
        if store.exists():
            for f in sorted(store.iterdir()):
                if not f.is_file() or f.name in NEVER_BUNDLE:
                    continue
                if f.stat().st_size > 5 * 1024 * 1024:
                    z.writestr(f"state/{f.name}.SKIPPED",
                               f"{f.stat().st_size} bytes, over limit")
                    continue
                add(z, f, f"state/{f.name}")
        for name in ("config.yaml", "nemodoc.log", "mode.pid"):
            f = home / name
            if f.exists() and f.is_file():
                add(z, f, name)
        for log in sorted(home.glob("*.log")):
            if log.name != "nemodoc.log":
                add(z, log, f"logs/{log.name}")
        z.writestr("EXCLUDED.txt",
                   "Deliberately not included:\n" +
                   "\n".join(f"  {n}" for n in sorted(NEVER_BUNDLE)) +
                   "\n  project contents\n  API keys (environment only)\n"
                   f"\nKey-shaped strings redacted from included files: "
                   f"{redacted_total}\n")
    return bundle
