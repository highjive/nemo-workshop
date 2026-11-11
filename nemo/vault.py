"""The Storeroom's vault (owner, 2026-10-23): his personal letters and
recordings, encrypted with his passphrase, for him alone, and for Nemo as
his companion only if he allows it.

Each file is kept as <storeroom>/vault/<id>.nv: a random 12-byte nonce and
AES-256-GCM of a small JSON header (name, kind, added) and the file. The key
comes from his passphrase by scrypt (n=2**15, r=8, p=1) with a random salt in
vault.json, which also holds a sealed check so a wrong passphrase is told
apart from a damaged file. The passphrase and key are never written; the key
lives only in the Vault object while it is open.

Plain copies: opening a file writes it to a temporary folder so a player or
editor can read it; lock() deletes that folder. Until then it is on disk in
plain form, said, not hidden. A backup carries the vault as it is (sealed
files and vault.json only). LIMITS: a forgotten passphrase cannot be got
round, by design; the employees, the model and the Researcher are never
given the vault; the companion reads letters only when he has allowed it in
vault.json AND the vault is open now.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

CHECK = b"nemo-vault-v1"
LETTERS = {".txt", ".md", ".rtf", ".doc", ".docx", ".odt", ".pdf"}
RECORDINGS = {".wav", ".mp3", ".m4a", ".ogg", ".opus", ".flac", ".aac", ".wma",
              ".mp4", ".mov", ".webm", ".mkv"}


class VaultError(RuntimeError):
    """Said to him as it is: wrong passphrase, damaged file, no such item."""


@dataclass
class Item:
    id: str
    name: str
    kind: str          # "letter" or "recording" or "file"
    added: str
    bytes: int


def folder(root: Path) -> Path:
    return Path(root).expanduser() / "vault"


def _key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _seal(key: bytes, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def _open(key: bytes, blob: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], None)
    except (InvalidTag, ValueError):
        raise VaultError("this file does not open with this passphrase, or it is damaged") from None


def exists(root: Path) -> bool:
    return (folder(root) / "vault.json").is_file()


def _settings(root: Path) -> dict:
    try:
        return json.loads((folder(root) / "vault.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise VaultError("there is no vault here yet, or its vault.json is unreadable") from None


def create(root: Path, passphrase: str) -> "Vault":
    if len(passphrase) < 8:
        raise VaultError("a passphrase needs at least 8 characters")
    if exists(root):
        raise VaultError("there is a vault here already")
    salt = secrets.token_bytes(16)
    key = _key(passphrase, salt)
    folder(root).mkdir(parents=True, exist_ok=True)
    (folder(root) / "vault.json").write_text(json.dumps({
        "salt": salt.hex(), "check": _seal(key, CHECK).hex(), "companion": False}), encoding="utf-8")
    return Vault(root, key)


def unlock(root: Path, passphrase: str) -> "Vault":
    s = _settings(root)
    key = _key(passphrase, bytes.fromhex(s["salt"]))
    try:
        ok = _open(key, bytes.fromhex(s["check"])) == CHECK
    except VaultError:
        ok = False
    if not ok:
        raise VaultError("that is not the vault's passphrase")
    return Vault(root, key)


def companion_allowed(root: Path) -> bool:
    try:
        return bool(_settings(root).get("companion"))
    except VaultError:
        return False


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    return "letter" if ext in LETTERS else "recording" if ext in RECORDINGS else "file"


class Vault:
    """An open vault. Forget it (lock()) when done: the key goes with it."""

    def __init__(self, root: Path, key: bytes):
        self.root, self._key, self._plain = Path(root), key, None

    @property
    def dir(self) -> Path:
        return folder(self.root)

    def _need(self):
        if self._key is None:
            raise VaultError("the vault is locked")

    def add_bytes(self, name: str, data: bytes) -> Item:
        self._need()
        item = Item(secrets.token_hex(8), Path(name).name, kind_of(name),
                    dt.datetime.now().strftime("%Y-%m-%d %H:%M"), len(data))
        head = json.dumps(item.__dict__).encode("utf-8")
        blob = _seal(self._key, len(head).to_bytes(4, "big") + head + data)
        path = self.dir / f"{item.id}.nv"
        part = path.with_suffix(".part")
        part.write_bytes(blob)
        os.replace(part, path)
        if self.read(item.id) != data:                    # read back before anyone relies on it
            path.unlink(missing_ok=True)
            raise VaultError(f"{name} did not read back; nothing was kept")
        return item

    def add_file(self, src: Path, remove_original: bool = False) -> Item:
        """Seal a file in; the original is removed only when asked, and only
        after the sealed copy has read back the same."""
        src = Path(src)
        item = self.add_bytes(src.name, src.read_bytes())
        if remove_original:
            src.unlink()
        return item

    def _unseal(self, path: Path) -> tuple[Item, bytes]:
        self._need()
        raw = _open(self._key, path.read_bytes())
        n = int.from_bytes(raw[:4], "big")
        return Item(**json.loads(raw[4:4 + n].decode("utf-8"))), raw[4 + n:]

    def items(self) -> list[Item]:
        out = []
        for p in sorted(self.dir.glob("*.nv")):
            try:
                out.append(self._unseal(p)[0])
            except (VaultError, ValueError, KeyError):
                out.append(Item(p.stem, "(does not open)", "damaged", "", p.stat().st_size))
        return sorted(out, key=lambda i: i.added, reverse=True)

    def read(self, item_id: str) -> bytes:
        path = self.dir / f"{item_id}.nv"
        if not path.is_file():
            raise VaultError("no such item in the vault")
        return self._unseal(path)[1]

    def open_copy(self, item_id: str) -> Path:
        """A plain copy to play or read, in a temporary folder lock() deletes."""
        item, data = self._unseal(self.dir / f"{item_id}.nv")
        if self._plain is None:
            self._plain = Path(tempfile.mkdtemp(prefix="nemo-vault-"))
        out = self._plain / item.name
        out.write_bytes(data)
        return out

    def remove(self, item_id: str):
        self._need()
        path = self.dir / f"{item_id}.nv"
        self._unseal(path)                                 # only what this passphrase opens
        path.unlink()

    def allow_companion(self, allowed: bool):
        """His choice alone: needs the vault open, so his passphrase."""
        self._need()
        s = _settings(self.root)
        s["companion"] = bool(allowed)
        (self.dir / "vault.json").write_text(json.dumps(s), encoding="utf-8")

    def letters_for_companion(self, limit: int = 2000) -> list[tuple[str, str]]:
        """(name, text) of plain-text letters, for the companion, only if he
        allowed it; [] otherwise. Text is cut at `limit` characters each."""
        if not companion_allowed(self.root):
            return []
        out = []
        for item in self.items():
            if item.kind == "letter" and Path(item.name).suffix.lower() in (".txt", ".md"):
                out.append((item.name, self.read(item.id).decode("utf-8", "replace")[:limit]))
        return out

    def lock(self):
        self._key = None
        if self._plain is not None:
            shutil.rmtree(self._plain, ignore_errors=True)
            self._plain = None
