"""The Computer Lab's Technician: loads the model the next step will need
while the owner is reading the last one (owner, 2026-10-21).

Loading a model here takes minutes; until now it began only when Run was
pressed. After a step passes in the window, the Technician looks at what
comes next and, if it needs a different model, starts loading it then.

It never loads one that would not fit: the figure is modes.memory_need, the
one modes.start itself refuses by (docs/design-rules.md, mistake 3), counting the
memory the loaded model would give back. It does nothing while another job
runs, when the next step needs no model or the one already loaded, and when
the owner has turned "Load ahead" off. Nothing here asks the model anything.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Plan:
    mode: str | None         # the mode to load, or None
    why: str                 # in words, either way


def next_step(project) -> str | None:
    """The first step, after the brief, that has not passed."""
    from . import steps
    from .results import load_results
    done = load_results(project.root)
    return next((s for s in steps.ORDER[1:] if not (done.get(s) or {}).get("ok")), None)


def fits(cfg, mode: str) -> tuple[bool, str]:
    from . import modes
    from .platform_probe import mem_available_mb, process_rss_mb
    need, _, _ = modes.memory_need(cfg.mode(mode))
    st = modes.current()
    back = process_rss_mb(st.pid) if st.running else 0       # given back when it stops
    have = (mem_available_mb() or 0) + (back or 0)
    if have < need:
        return False, f"the {mode} model needs about {need} MB and only {have} MB would be free"
    return True, ""


def plan(cfg, project) -> Plan:
    """What to load ahead for this project now, and why (or why not)."""
    from . import modes, steps
    step = next_step(project)
    if step is None:
        return Plan(None, "every step has passed")
    try:
        brief = project.load_brief()
    except Exception:                                           # noqa: BLE001
        return Plan(None, "the brief cannot be read")
    if not steps.asks_model(step, brief):
        return Plan(None, f"the next step, {step}, needs no model")
    mode = steps.get(step).mode
    st = modes.current()
    if st.running and st.name == mode:
        return Plan(None, f"the {mode} model, which {step} needs, is loaded already")
    ok, why = fits(cfg, mode)
    if not ok:
        return Plan(None, f"not loading ahead: {why}")
    return Plan(mode, f"loading the {mode} model for the next step, {step}")
