"""The Doctors' memory check (owner's yes, 2026-10-23: design B).

Now and then, when he asks ("memory check"), Nemo reads out five everyday
words; he talks about something else for a few minutes, then says "recall"
and the words he remembers. The score is out of 5, the same way every time,
kept as a private trend in ~/.nemo/memory-check.jsonl.

A personal record, NOT a medical test: it never diagnoses. If his scores fall
clearly over several weeks, it says so plainly and suggests mentioning it to
his GP; a single day says nothing, and it says that too.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

WORDS = ("apple", "chair", "river", "candle", "garden", "button", "window", "pencil", "bridge",
         "orange", "blanket", "ladder", "kettle", "forest", "hammer", "violin", "carpet",
         "pillow", "lemon", "anchor", "basket", "mirror", "rocket", "saddle", "tunnel", "wallet",
         "turtle", "trumpet", "cabbage", "lantern", "harbour", "feather", "biscuit", "compass",
         "parrot", "teapot", "marble", "jacket", "helmet", "meadow")
COUNT = 5
CLEAR_FALL = 1.5            # points out of 5, between the last four checks and the four before


def _path() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "memory-check.jsonl"


def _rows() -> list[dict]:
    try:
        return [json.loads(l) for l in _path().read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


def _write(row: dict) -> None:
    p = _path(); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def start(rng=random) -> list[str]:
    """Five words, none of them the last check's."""
    last = next((r["words"] for r in reversed(_rows()) if r.get("words")), [])
    words = rng.sample([w for w in WORDS if w not in last], COUNT)
    _write({"at": time.strftime("%Y-%m-%d %H:%M"), "words": words, "score": None})
    return words


def _stem(w: str) -> str:
    w = w.lower()
    return w[:-1] if w.endswith("s") and len(w) > 3 else w


def recall(said: str) -> tuple[int, list[str], str]:
    """Score what he remembered against the words waiting; (score, missed,
    a plain reading of the trend)."""
    rows = _rows()
    # Only the latest check can be waiting: an earlier one stayed open after it
    # was recalled, and could be scored twice (its test).
    waiting = rows[-1] if rows and rows[-1].get("words") and rows[-1].get("score") is None else None
    if waiting is None:
        raise ValueError("there is no memory check waiting: say memory check first")
    heard = {_stem(w) for w in re.findall(r"[A-Za-z]+", said)}
    got = [w for w in waiting["words"] if _stem(w) in heard]
    missed = [w for w in waiting["words"] if w not in got]
    _write({"at": time.strftime("%Y-%m-%d %H:%M"), "words": [], "score": len(got)})
    return len(got), missed, trend()


def trend() -> str:
    scores = [r["score"] for r in _rows() if r.get("score") is not None]
    if len(scores) < 8:
        return f"{len(scores)} check(s) so far: one day says nothing; a trend needs eight or more."
    recent, before = sum(scores[-4:]) / 4, sum(scores[-8:-4]) / 4
    if before - recent >= CLEAR_FALL:
        return (f"Your last four average {recent:.1f} of 5, against {before:.1f} before. That is a "
                "clear fall. It is not a diagnosis, but it is worth mentioning to your GP.")
    return f"Your last four average {recent:.1f} of 5, against {before:.1f} before: no clear change."
