"""Which employee has a problem, and how to fix it (owner, 2026-11-04: "if
issue in a stage that employee give a notification and solutions to fix").

For the open project: each step whose last run failed, or passed with a
check it could not make (a SKIP), is its OWNER's issue (steps.py says who
owns which step). The issue carries the checks that went wrong and the
fixes Nemo already suggests for them (fixes.suggest_fixes), the same
fixes the Workshop's list offers, so the two cannot disagree. Nothing is
decided here that the Workshop did not already decide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FAILED, UNCHECKED, DOUBTED = "failed", "could not be checked", "is doubted by the other model"


@dataclass
class Issue:
    stage: str
    step: str                       # the step's own name, "Schematic"
    owner: str                      # a staff.STAFF key
    state: str                      # FAILED or UNCHECKED
    problems: list[str] = field(default_factory=list)
    fixes: list = field(default_factory=list)          # fixes.Fix

    def headline(self) -> str:
        return f"'{self.step}' {self.state}"


def _problems(rec: dict) -> list[str]:
    out = []
    for c in rec.get("checks", []):
        if c.get("status") in ("FAIL", "SKIP"):
            word = "failed" if c.get("status") == "FAIL" else "not checked"
            out.append(f"{c.get('name')} {word}: {c.get('detail') or ''}".rstrip(": "))
    return out


def for_project(project_root: Path, brief, library, min_wall_mm: float = 1.2) -> dict[str, list[Issue]]:
    """{employee key: its issues} for one project, in step order."""
    from .fixes import suggest_fixes
    from .results import load_results, load_safety
    from .steps import STEPS
    results = load_results(project_root)
    out: dict[str, list[Issue]] = {}
    for s in STEPS:
        rec = results.get(s.key)
        if not rec:
            continue
        skipped = any(c.get("status") == "SKIP" for c in rec.get("checks", []))
        if rec.get("ok") and not skipped:
            continue
        state = FAILED if not rec.get("ok") else UNCHECKED
        try:
            fixes = suggest_fixes(brief, library, s.key, rec, load_safety(project_root),
                                  min_wall_mm, project_root)
        except Exception:                                   # noqa: BLE001  a fix that fails to form
            fixes = []                                      # leaves the problem said, not hidden
        out.setdefault(s.owner, []).append(Issue(s.key, s.name, s.owner, state, _problems(rec), fixes))
    # The Second Opinion's doubts about the wiring (nemo/second.py): its own to raise.
    from . import second
    doubted = second.doubts(project_root)
    if doubted:
        out.setdefault("workshop.second", []).append(Issue(
            "electrical", "the wiring", "workshop.second", DOUBTED,
            [f"{o.part} {o.part_pin} on {o.mcu_pin}: {o.reason}" for o in doubted], []))
    return out


def for_department(all_issues: dict[str, list[Issue]], department: str) -> dict[str, list[Issue]]:
    return {k: v for k, v in all_issues.items() if k.split(".", 1)[0] == department}


def count_by_department(all_issues: dict[str, list[Issue]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in all_issues.items():
        d = k.split(".", 1)[0]
        out[d] = out.get(d, 0) + len(v)
    return out
