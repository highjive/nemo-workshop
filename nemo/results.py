"""Per-project record of what each step last produced.

Kept in <project>/.nemo/ so the interface can show a project's state after a
restart without re-running anything, and so the command line and the
interface read the same record rather than keeping two.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .steps import MODEL_STEPS

# Steps that call the language model (nemo/steps.py). The others -- parts,
# concept and pack -- are arithmetic, geometry and file assembly, and must
# run with no model loaded.
MODEL_STAGES = MODEL_STEPS


def _dir(project_root: Path) -> Path:
    d = Path(project_root) / ".nemo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def result_to_dict(sr) -> dict:
    return {
        "stage": sr.stage,
        "ok": bool(sr.ok),
        "when": int(time.time()),
        "degraded": bool(getattr(sr, "degraded", False)),
        "go_back_to": sr.go_back_to,
        "artifacts": [str(a) for a in sr.artifacts],
        "notes": list(sr.notes),
        "checks": [{"name": r.name, "status": r.status, "detail": r.detail,
                    "items": list(r.items)} for r in sr.results],
    }


def save_result(project_root: Path, sr) -> dict:
    path = _dir(project_root) / "results.json"
    data = load_results(project_root)
    rec = result_to_dict(sr)
    data[sr.stage] = rec
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return rec


def load_results(project_root: Path) -> dict:
    path = Path(project_root) / ".nemo" / "results.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_safety(project_root: Path, findings) -> None:
    # Written whole, then put in place: a power cut mid-write (a FAT32 stick)
    # leaves the old record, not half of a new one.
    path = _dir(project_root) / "safety.json"
    tmp = path.with_name("safety.json.tmp")
    tmp.write_text(json.dumps(
        [{"severity": f.severity, "rule": f.rule, "detail": f.detail}
         for f in findings], indent=2), encoding="utf-8")
    tmp.replace(path)


# Said in place of the findings when the record cannot be read. A damaged
# record is never read as "no findings": that let a pack go out with no
# safety sign-offs listed (2026-11-08). It FAILS CLOSED: one sign-off that
# the pack lists even when ticked (pipeline.stage_pack), until the safety
# check runs again and writes a readable record.
UNREADABLE = {"severity": "signoff", "rule": "record_unreadable",
              "detail": "this project's safety record (.nemo/safety.json) could not be read; "
                        "run the safety check again before trusting the design"}


def load_safety(project_root: Path) -> list[dict]:
    path = Path(project_root) / ".nemo" / "safety.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [dict(UNREADABLE)]
    if not isinstance(data, list) or not all(
            isinstance(f, dict) and {"severity", "rule", "detail"} <= set(f) for f in data):
        return [dict(UNREADABLE)]
    return data
