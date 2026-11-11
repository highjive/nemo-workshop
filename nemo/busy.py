"""Who is busy now: which of a department's workers has a job running, for
the glowing ring round its portrait in the department view (gui
IllustratedRoom). What was left of the pixel rooms (2026-10-23) once their
pictures went (owner, 2026-10-25); the rest was removed on 2026-10-29.

Only real signals light a ring: in the Library the Writer and Editor on a
story job, the Artist on a cover, the Foreman with a queue, the Timekeeper on
any job; elsewhere only the Timekeeper so far. A worker with no live signal
is said to have none (no_signal), never shown as busy.
"""
from __future__ import annotations


def signals(app, key: str = "library") -> dict[str, bool]:
    """Which workers are busy now, from what the app is doing."""
    job = getattr(app, "job", None)
    running = bool(job and getattr(job, "running", False))
    kind = getattr(job, "kind", "") if running else ""
    try:
        from . import foreman
        queued = bool(foreman.load())
    except Exception:                                           # noqa: BLE001
        queued = False
    if key != "library":
        return {"timekeeper": running}
    return {"writer": kind == "story", "editor": kind == "story",
            "artist": kind == "cover", "foreman": queued and running,
            "timekeeper": running}


NO_SIGNAL = ("researcher", "linguist", "archivist")


def no_signal(key: str) -> list[str]:
    """The workers of this department with no live signal yet: said, not pretended."""
    if key == "library":
        return list(NO_SIGNAL)
    from .staff import team
    return [e.key.split(".", 1)[1] for e in team(key) if not e.key.endswith(".timekeeper")]
