"""The Archivist: keeps the model's answers that passed, to reuse
(Library, built 2026-10-21; owner chose it to save the model work).

How it decides, so that nothing is reused that should not be:
  - Every answer the local model gives is noted as pending, with the exact
    request it answered: the model loaded, every message, the temperature,
    the length and the schema (router._call_local).
  - Only when the step it was given for PASSES are its pending answers kept
    (workflow.run_step); a failed step's are dropped. Stories are never
    kept: a story asked again should be a new story.
  - It is reused only for the identical request to the identical model.
    The step's checks still judge it, exactly as if the model had written it.
A reused answer costs nothing; asked again, the model at temperature 0.2
might not answer the same (docs/design-rules.md 4e), so reuse also makes a repeat run
repeat. `nemo archive clear` empties it; engine.archive: false turns it off.

Kept in ~/.nemo/archive/<sha256>.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

_pending: list[tuple[str, dict]] = []


def _home() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "archive"


def key(payload: dict, loaded: str | None) -> str:
    """The request exactly, and which model file answered it."""
    raw = json.dumps({"loaded": loaded, "payload": payload}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def on(cfg) -> bool:
    # NEMO_ARCHIVE=off: the test sandbox, where one test's passed step must
    # not answer another's request.
    if os.environ.get("NEMO_ARCHIVE") == "off":
        return False
    return bool(cfg.get("engine.archive", True))


def recall(k: str) -> str | None:
    """A kept answer to exactly this request, or None."""
    p = _home() / f"{k}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))["reply"]
    except (OSError, ValueError, KeyError):
        return None


def note(k: str, reply: str, task: str | None) -> None:
    """An answer the model just gave: kept only if its step passes."""
    _pending.append((k, {"reply": reply, "task": task}))


def begin() -> None:
    """A step starts: what earlier work left pending is not this step's."""
    _pending.clear()


def keep(step: str) -> int:
    """The step passed: keep its answers. Returns how many."""
    kept = 0
    home = _home()
    for k, rec in _pending:
        home.mkdir(parents=True, exist_ok=True)
        (home / f"{k}.json").write_text(
            json.dumps({**rec, "step": step, "at": int(time.time())}), encoding="utf-8")
        kept += 1
    _pending.clear()
    return kept


def drop() -> None:
    """The step failed: its answers are not kept."""
    _pending.clear()


def clear() -> int:
    """Forget every kept answer. Returns how many there were."""
    home = _home()
    gone = 0
    for p in home.glob("*.json") if home.is_dir() else []:
        p.unlink()
        gone += 1
    return gone


def count() -> int:
    home = _home()
    return len(list(home.glob("*.json"))) if home.is_dir() else 0
