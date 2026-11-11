"""Master authority by signature, not by password.

The requirement was a master credential, held by the author, that ships
inside cloned images and permits the safety floor to be reset. A password
cannot do this, and the failure is not subtle.

A password that ships in an image is a secret on a disk the recipient owns.
They do not need to crack it: they overwrite the credential file with a hash
of a password they chose, and they are now master. Increasing the hash cost
changes nothing, because cracking was never the attack.

The primitive that does work is asymmetric. The author holds a private key
that never leaves their own machine. The image carries only the public key,
which is not a secret and leaks nothing. A floor change is a document signed
with the private key; Nemo verifies it against the embedded public key.
Nobody holding the image can forge one.

What this genuinely provides:

  * A floor change is provably from the author, on any unmodified install.
  * Nothing secret is distributed, so cloning the image is safe.
  * A signed document can be emailed, carried on a USB stick, or published
    -- it is useless to anyone trying to forge a different one.
  * Replay is bounded: documents carry a serial and Nemo refuses to accept
    one older than the floor it already holds.

What it does not provide, stated plainly because the distinction is the
whole point of the earlier hardening work:

  * It does not stop the holder of an image from editing the Python source,
    replacing the embedded public key with their own, or deleting the
    verification entirely. On hardware someone else controls, no software
    control survives a determined owner. This is the same result as the
    boot-media analysis in docs/hardening.md, and it is not fixable.

So signature verification protects the integrity of an installation that is
running the author's code. It is authenticity, not enforcement. Anyone who
claims software can enforce a policy on hardware they do not control is
describing DRM, which has never worked and does not work here either.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    HAVE_CRYPTO = True
except ImportError:                                   # pragma: no cover
    HAVE_CRYPTO = False

    class InvalidSignature(Exception):
        pass


DOC_VERSION = 1


class SigningError(RuntimeError):
    pass


def _require_crypto() -> None:
    if not HAVE_CRYPTO:
        raise SigningError(
            "the 'cryptography' package is required for signed floor "
            "documents.\n  Debian:  sudo apt install python3-cryptography\n"
            "  Windows: pip install cryptography")


# ====================================================================
#  Key generation -- runs on the author's machine, never on a target
# ====================================================================

def generate_master_key(private_path: Path,
                        public_path: Path) -> tuple[Path, Path]:
    """Create a master keypair.

    Run this once, on a machine you control, and keep the private key off
    every target install and out of every image. If it leaks, anyone can
    sign floor documents as you, and the only remedy is to reissue the
    public key in a new release.
    """
    _require_crypto()
    key = Ed25519PrivateKey.generate()
    private_path = Path(private_path)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(key.private_bytes_raw())
    try:
        private_path.chmod(0o600)
    except OSError:
        pass
    pub = key.public_key().public_bytes_raw()
    Path(public_path).write_text(pub.hex() + "\n", encoding="utf-8")
    return private_path, Path(public_path)


# ====================================================================
#  Documents
# ====================================================================

@dataclass
class FloorDocument:
    """A signed replacement for the default safety floor."""

    values: dict
    serial: int
    issued_at: int
    note: str = ""
    signature: str = ""

    def payload(self) -> bytes:
        """Exactly the bytes that are signed and verified.

        The signature is excluded, and keys are sorted, so the same
        document always produces the same bytes regardless of how it was
        serialised or transported.
        """
        return json.dumps({
            "version": DOC_VERSION,
            "values": self.values,
            "serial": self.serial,
            "issued_at": self.issued_at,
            "note": self.note,
        }, sort_keys=True, separators=(",", ":")).encode()

    def to_json(self) -> str:
        return json.dumps({
            "version": DOC_VERSION, "values": self.values,
            "serial": self.serial, "issued_at": self.issued_at,
            "note": self.note, "signature": self.signature,
        }, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "FloorDocument":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SigningError(f"not a valid document: {exc}") from exc
        if doc.get("version") != DOC_VERSION:
            raise SigningError(
                f"document version {doc.get('version')} is not supported by "
                f"this build (expects {DOC_VERSION})")
        missing = [k for k in ("values", "serial", "issued_at", "signature")
                   if k not in doc]
        if missing:
            raise SigningError(f"document is missing: {', '.join(missing)}")
        return cls(values=doc["values"], serial=int(doc["serial"]),
                   issued_at=int(doc["issued_at"]), note=doc.get("note", ""),
                   signature=doc["signature"])


def sign_floor(private_key_path: Path, values: dict, serial: int,
               note: str = "") -> FloorDocument:
    """Sign a floor document. Author-side only."""
    _require_crypto()
    raw = Path(private_key_path).read_bytes()
    if len(raw) != 32:
        raise SigningError(
            f"{private_key_path} is not a raw ed25519 private key "
            f"({len(raw)} bytes, expected 32)")
    key = Ed25519PrivateKey.from_private_bytes(raw)
    doc = FloorDocument(values=values, serial=int(serial),
                        issued_at=int(time.time()), note=note)
    doc.signature = key.sign(doc.payload()).hex()
    return doc


def verify_floor(doc: FloorDocument, public_key_hex: str,
                 minimum_serial: int = 0) -> dict:
    """Verify a document against the embedded public key.

    Raises on any failure. Returns the floor values on success.
    """
    _require_crypto()
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
    except ValueError as exc:
        raise SigningError(f"embedded public key is malformed: {exc}") from exc

    try:
        pub.verify(bytes.fromhex(doc.signature), doc.payload())
    except (InvalidSignature, ValueError) as exc:
        raise SigningError(
            "signature does not verify against this build's master key. "
            "Either the document was not signed by the holder of that key, "
            "or it was altered after signing."
        ) from exc

    # Refuse an older document than the one already in force, so a floor
    # cannot be rolled back to a permissive earlier revision by replaying a
    # document that was legitimately signed at the time.
    if doc.serial < minimum_serial:
        raise SigningError(
            f"document serial {doc.serial} is older than the floor already "
            f"in force (serial {minimum_serial}). Replay refused.")

    return dict(doc.values)


def sign_bytes(private_key_path: Path, payload: bytes) -> str:
    """Sign arbitrary bytes. Author-side only."""
    _require_crypto()
    raw = Path(private_key_path).read_bytes()
    if len(raw) != 32:
        raise SigningError(f"{private_key_path} is not a raw ed25519 key")
    return Ed25519PrivateKey.from_private_bytes(raw).sign(payload).hex()


def verify_bytes(payload: bytes, signature_hex: str,
                 public_key_hex: str) -> None:
    """Verify arbitrary bytes. Raises SigningError on failure."""
    _require_crypto()
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub.verify(bytes.fromhex(signature_hex), payload)
    except (InvalidSignature, ValueError) as exc:
        raise SigningError(
            "signature does not verify against this build's master key"
        ) from exc


def public_key_fingerprint(public_key_hex: str) -> str:
    """Short human-comparable form, for checking a build is yours."""
    h = public_key_hex.strip().lower()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))
