"""The Foreman: a queue of long jobs, run in an order that loads each model
as few times as it can (Library, built 2026-10-21; owner chose it to save
the model work).

Loading a model here takes minutes and only one fits in memory, so three
jobs that need Design, Talk and Design again cost three loads where two
would do. The Foreman runs the queue in the order that switches least,
without ever running a project's step before the steps queued ahead of it
in the same project: those build on each other. Jobs that need no model
run whichever model is loaded. Start it before bed: `nemo queue run`.

A job that fails stops the rest of its own project or story, and the
others go on. Each job is the same `nemo` command the window runs, in its
own process. The queue is ~/.nemo/queue.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Job:
    kind: str            # "step", "story", "cover", "model" or "slice"
    owner: str           # the project or story it belongs to
    what: str            # the step's key, or "write" / "cover"
    mode: str | None     # the model mode it needs, or None
    argv: list[str]      # the nemo command, after "nemo"

    @property
    def label(self) -> str:
        return f"{self.owner}: {self.what}"


# Whose a job is, by its kind: a design step is the Workshop's (its owner
# in nemo/steps.py says which department), a story or a cover the Library's,
# a model build the Art Studio's and a slice the Print Shop's (2026-10-22).
# A model and its slice share an owner, the model's name, so a slice queued
# after its build never runs before it.
def department(job: Job) -> str:
    if job.kind == "step":
        from . import steps
        from .staff import STAFF
        return STAFF[steps.get(job.what).owner].department
    return {"model": "art_studio", "slice": "printshop"}.get(job.kind, "library")


def model_job(doc: dict) -> Job:
    """A model build for the queue: its list of shapes kept beside the queue
    until it runs, as the build reads it from a file."""
    from . import modelkit
    name = modelkit.slug(modelkit.validate(doc).name)
    spec = queue_path().parent / "queued-models" / f"{name}.json"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return Job("model", name, "build", None, ["model", "build", str(spec)])


def slice_job(name: str) -> Job:
    return Job("slice", name, "slice", None, ["print", "slice", name])


def queue_path() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "queue.json"


def load() -> list[Job]:
    try:
        return [Job(**d) for d in json.loads(queue_path().read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return []


def save(jobs: list[Job]) -> None:
    p = queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([asdict(j) for j in jobs], indent=1), encoding="utf-8")


def step_job(project: str, step: str) -> Job:
    from . import steps
    s = steps.get(step)
    return Job("step", project, step, s.mode if s.uses_model else None,
               ["--project", project, "run", "--only", step])


def add(jobs_to_add: list[Job]) -> list[Job]:
    jobs = load() + [j for j in jobs_to_add if j not in load()]
    save(jobs)
    return jobs


def order(jobs: list[Job], loaded: str | None = None) -> list[Job]:
    """The queue in the order that switches model least. A job may go only
    when every job queued before it for the same owner has gone."""
    left, out, current = list(jobs), [], loaded
    while left:
        ready = [j for j in left
                 if not any(k.owner == j.owner for k in left[:left.index(j)])]
        pick = (next((j for j in ready if j.mode is None or j.mode == current), None)
                or ready[0])
        out.append(pick)
        left.remove(pick)
        if pick.mode:
            current = pick.mode
    return out


def loads(jobs: list[Job], loaded: str | None = None) -> int:
    """How many times a model would be loaded, running them in this order."""
    n, current = 0, loaded
    for j in jobs:
        if j.mode and j.mode != current:
            n, current = n + 1, j.mode
    return n


def run(cfg, say=print, start_mode=None, run_job=None) -> list[tuple[Job, bool]]:
    """Run the whole queue in the Foreman's order. Returns (job, passed)."""
    from . import modes
    start_mode = start_mode or (lambda name: modes.start(cfg, name))
    run_job = run_job or (lambda j: subprocess.run(
        [sys.executable, "-m", "nemo.cli", *j.argv]).returncode == 0)
    current = modes.current().name if modes.current().running else None
    plan = order(load(), current)
    say(f"Foreman: {len(plan)} job(s); the model is loaded {loads(plan, current)} time(s).")
    done, failed_owners = [], set()
    for j in plan:
        if j.owner in failed_owners:
            say(f"Foreman: skipped {j.label}: an earlier job of {j.owner} failed.")
            done.append((j, False))
            continue
        if j.mode and j.mode != current:
            say(f"Foreman: loading the {j.mode} model.")
            ok, msg = start_mode(j.mode)
            if not ok:
                say(f"Foreman: the {j.mode} model did not load ({msg}); stopping here.")
                break
            current = j.mode
        say(f"Foreman: {j.label}")
        t = time.time()
        ok = run_job(j)
        say(f"Foreman: {j.label} {'passed' if ok else 'FAILED'} ({time.time() - t:.0f} s).")
        done.append((j, ok))
        if not ok:
            failed_owners.add(j.owner)
    finished = {id(j) for j, _ in done}
    save([j for j in plan if id(j) not in finished])       # what is left, if it stopped
    return done
