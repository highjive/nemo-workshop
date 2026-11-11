"""Second opinions requested while offline, kept until they can be sent.

When a step drafts locally and asks the online reviewer to check the draft,
but there is no connection, the step carries on with the local draft. Before
this module the review request was simply dropped. Now it is written to a
queue and sent when a connection returns; the answer is filed with the
project as a note for a person to read. It never replaces a file the step
already wrote: a review is a suggestion, like every other suggestion here.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def queue_dir() -> Path:
    return Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo")) / "review-queue"


def enqueue(task: str, system: str, user: str, draft: str,
            context: dict | None = None) -> str:
    q = queue_dir(); q.mkdir(parents=True, exist_ok=True)
    rid = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    (q / f"{rid}.json").write_text(json.dumps({
        "id": rid, "task": task, "system": system, "user": user,
        "draft": draft, "context": context or {}, "queued": int(time.time())},
        indent=2), encoding="utf-8")
    return rid


def pending() -> list[dict]:
    q = queue_dir()
    out = []
    for f in sorted(q.glob("*.json")) if q.exists() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8", errors="replace")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def reviews_for(project_root: Path, stage: str) -> list[Path]:
    d = Path(project_root) / ".nemo" / "reviews"
    return sorted(d.glob(f"{stage}-*.md")) if d.exists() else []


def send_all(router) -> list[tuple[str, bool, str]]:
    """Send every queued review. Failures stay queued for next time."""
    results = []
    for item in pending():
        ctx = item.get("context") or {}
        try:
            reply = router.review(item["task"], item["system"], item["user"],
                                  item["draft"])
        except Exception as exc:                            # noqa: BLE001
            results.append((item["id"], False, str(exc)))
            continue
        project, stage = ctx.get("project"), ctx.get("stage", item["task"])
        if project and Path(project).exists():
            d = Path(project) / ".nemo" / "reviews"
            d.mkdir(parents=True, exist_ok=True)
            when = time.strftime("%d %b %Y %H:%M", time.localtime(item["queued"]))
            (d / f"{stage}-{item['id']}.md").write_text(
                f"# Second opinion on the {stage} step\n\n"
                f"Requested {when} while offline; answered by {reply.model}.\n"
                "This is advice. Nothing in the project was changed.\n\n"
                + reply.text + "\n", encoding="utf-8")
        (queue_dir() / f"{item['id']}.json").unlink(missing_ok=True)
        results.append((item["id"], True, stage))
    return results
