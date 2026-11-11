"""The Timekeeper: how long the model takes, from the server's own figures
(Library, built 2026-10-21; docs/design-rules.md 4f: "read them, do not guess").

llama-server writes three lines per request into ~/.nemo/<mode>.log:

  ... slot print_timing: id  0 | task 3 | prompt eval time = 52730.00 ms /   157 tokens (...)
  ... slot print_timing: id  0 | task 3 |        eval time =   609.51 ms /     2 tokens (...)
  ... slot print_timing: id  0 | task 3 |       total time = 53339.51 ms /   159 tokens

(the form on the AH531, 2026-10-21). Reading the question is "prompt eval",
writing the answer is "eval". Nothing else is measured or estimated here.
The logs start again each time a mode is loaded, so this is the latest
session of each mode.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_LINE = re.compile(r"task\s+(\d+)\s*\|\s*(prompt eval|eval|total) time\s*=\s*([\d.]+) ms\s*/\s*(\d+) tokens")


@dataclass
class Request:
    task: int
    read_ms: float = 0.0
    read_tokens: int = 0
    write_ms: float = 0.0
    write_tokens: int = 0
    total_ms: float = 0.0


@dataclass
class ModeTimes:
    mode: str
    requests: list[Request] = field(default_factory=list)

    def _rate(self, tokens: str, ms: str) -> float | None:
        t = sum(getattr(r, tokens) for r in self.requests)
        m = sum(getattr(r, ms) for r in self.requests)
        return t / (m / 1000) if m else None

    @property
    def reading(self) -> float | None:
        """Tokens read a second, over every request."""
        return self._rate("read_tokens", "read_ms")

    @property
    def writing(self) -> float | None:
        """Tokens written a second, over every request."""
        return self._rate("write_tokens", "write_ms")

    @property
    def total_s(self) -> float:
        return sum(r.total_ms for r in self.requests) / 1000


def read_log(path: Path) -> list[Request]:
    found: dict[int, Request] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for m in _LINE.finditer(text):
        task, what, ms, tokens = int(m[1]), m[2], float(m[3]), int(m[4])
        r = found.setdefault(task, Request(task))
        if what == "prompt eval":
            r.read_ms, r.read_tokens = ms, tokens
        elif what == "eval":
            r.write_ms, r.write_tokens = ms, tokens
        else:
            r.total_ms = ms
    return list(found.values())


def times(home: Path | None = None) -> list[ModeTimes]:
    """Each mode with a log, and its requests."""
    from . import modes
    home = Path(home) if home else modes.STATE.parent
    out = []
    for log in sorted(home.glob("*.log")):
        reqs = read_log(log)
        if reqs:
            out.append(ModeTimes(log.stem, reqs))
    return out


def modes_of(department: str) -> set[str]:
    """The model modes a department's steps use (nemo/steps.py); a story,
    the Library's, uses talk."""
    from . import steps
    from .staff import STAFF
    used = {s.mode for s in steps.STEPS
            if s.uses_model and STAFF[s.owner].department == department}
    return used | ({"talk"} if department == "library" else set())


def describe(found: list[ModeTimes]) -> str:
    if not found:
        return "No model timings yet: the model logs have none (a mode must be loaded and asked)."
    lines = []
    for t in found:
        rd = f"{t.reading:.2f}" if t.reading else "-"
        wr = f"{t.writing:.2f}" if t.writing else "-"
        lines.append(f"{t.mode:<8} {len(t.requests):>3} request(s), {t.total_s:>7.0f} s in all; "
                     f"reads {rd} tokens/s, writes {wr} tokens/s")
    return "\n".join(lines) + "\n(The server's own figures, from its latest session of each mode.)"


# --------------------------------------------------------------------
#  Jobs that ask no model (Art Studio and Print Shop, owner 2026-10-22)
# --------------------------------------------------------------------
# A model build or a slice asks the model nothing, so the server's logs
# hold nothing about it. The job itself says how long it took: each run is
# one line of ~/.nemo/job-times.jsonl, measured by the clock, not guessed.

def _jobs_path() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "job-times.jsonl"


# ------------------------------------------------------------ builds
# Speed between builds (2026-11-08, after Claude Code Game Studios'
# performance-analyst: "compare performance across builds to detect
# regressions"). Each timing says which Nemo ran it and where, so a build is
# only ever compared with the build before it ON THE SAME MACHINE: the desktop
# slices in a second what the AH531 takes a minute over (mistake 3).
_BUILD: list[str] = []


def build() -> str:
    """This Nemo's commit, 12 characters: the update it runs from, else the
    image's /opt/nemo/COMMIT, else the git checkout it is in; "" if none says."""
    if _BUILD:
        return _BUILD[0]
    found = ""
    try:
        from . import update
        used = update.running()
        found = used.name[:12] if used is not None else update.image()[0][:12]
    except Exception:                                           # noqa: BLE001
        found = ""
    if not found:
        import subprocess
        try:
            here = str(Path(__file__).resolve().parent.parent)
            r = subprocess.run(["git", "-C", here, "rev-parse", "--short=12", "HEAD"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=10)
            found = r.stdout.strip() if r.returncode == 0 else ""
            if found:
                # Uncommitted edits are their own build: timed apart from the commit.
                d = subprocess.run(["git", "-C", here, "status", "--porcelain",
                                    "--untracked-files=no", "--", "nemo"], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=10)
                if d.stdout.strip():
                    found += "+edits"
        except (OSError, Exception):                            # noqa: BLE001
            found = ""
    _BUILD.append(found)
    return found


def machine() -> str:
    """This computer, as its own name and system say (no hardware probe)."""
    import platform
    import sys
    return f"{platform.node() or 'unnamed'} ({sys.platform})"


def record(department: str, what: str, seconds: float, ok: bool) -> None:
    """One job's time. Never fails the job it times."""
    import json
    import time
    try:
        p = _jobs_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "department": department,
                                "what": what, "seconds": round(seconds, 1), "ok": ok,
                                "build": build(), "machine": machine()}) + "\n")
    except OSError:
        pass


class Timer:
    """`with Timer(department, what) as t:` records the time on the way out;
    t.ok = False before leaving says it failed; an exception says so too."""

    def __init__(self, department: str, what: str):
        self.department, self.what, self.ok = department, what, True

    def __enter__(self):
        import time
        self.began = time.time()
        return self

    def __exit__(self, kind, *_):
        import time
        record(self.department, self.what, time.time() - self.began, self.ok and kind is None)
        return False


@dataclass
class JobTimes:
    department: str
    what: str
    seconds: list[float] = field(default_factory=list)
    failed: int = 0

    @property
    def mean(self) -> float:
        return sum(self.seconds) / len(self.seconds) if self.seconds else 0.0


def job_times(department: str | None = None) -> list[JobTimes]:
    """Each kind of job's times, from the record; failed runs are counted,
    not averaged, as a failure can stop early."""
    import json
    found: dict[tuple, JobTimes] = {}
    try:
        lines = _jobs_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if department and d.get("department") != department:
            continue
        t = found.setdefault((d["department"], d["what"]), JobTimes(d["department"], d["what"]))
        if d.get("ok"):
            t.seconds.append(float(d["seconds"]))
        else:
            t.failed += 1
    return list(found.values())


SLOWER = 1.3        # a build this much slower (median to median) is said
FASTER = 1 / 1.3
MIN_RUNS = 3        # runs of each build before two are compared


@dataclass
class Change:
    machine: str
    department: str
    what: str
    before: str            # build
    after: str
    before_s: float        # median seconds
    after_s: float
    runs: tuple[int, int]

    @property
    def ratio(self) -> float:
        return self.after_s / self.before_s if self.before_s else 1.0

    def line(self) -> str:
        how = "slower" if self.ratio > 1 else "faster"
        return (f"{self.what} ({self.department}): {self.after_s:.1f} s in {self.after or 'this build'}"
                f" against {self.before_s:.1f} s in {self.before}, {self.ratio:.2f}x, {how} "
                f"(medians of {self.runs[1]} and {self.runs[0]} runs, on {self.machine})")


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def changes(lines: list[str] | None = None, everything: bool = False) -> list[Change]:
    """For each job on each machine, the latest build against the build that
    ran it before, where each has MIN_RUNS passed runs. Only the slower and
    the faster are returned (everything=True: all compared). Records from
    before builds were kept say no build and are never compared. A change is
    a measurement, not a cause: what in the build did it is not known here."""
    import json
    if lines is None:
        try:
            lines = _jobs_path().read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    runs: dict[tuple, dict[str, list[float]]] = {}
    order: dict[tuple, list[str]] = {}
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        b = d.get("build")
        if not b or not d.get("ok") or not d.get("machine"):
            continue
        key = (d["machine"], d.get("department", ""), d.get("what", ""))
        runs.setdefault(key, {}).setdefault(b, []).append(float(d.get("seconds", 0)))
        seen = order.setdefault(key, [])
        if b in seen:
            seen.remove(b)
        seen.append(b)                          # the build last seen running it is the latest
    out = []
    for key, builds in order.items():
        enough = [b for b in builds if len(runs[key][b]) >= MIN_RUNS]
        if len(enough) < 2:
            continue
        before, after = enough[-2], enough[-1]
        c = Change(*key, before, after, _median(runs[key][before]), _median(runs[key][after]),
                   (len(runs[key][before]), len(runs[key][after])))
        if everything or c.ratio >= SLOWER or c.ratio <= FASTER:
            out.append(c)
    return sorted(out, key=lambda c: -c.ratio)


def describe_changes(found: list[Change]) -> str:
    if not found:
        return (f"No build is {SLOWER:.1f}x slower or faster than the one before it on this "
                f"record (each needs {MIN_RUNS} timed runs of a job on the same machine).")
    return "\n".join(c.line() for c in found) + (
        "\n(Measured by the clock. Which change in the build did it is not known: measure "
        "again before believing one slow run.)")


# The same jobs every time, so builds compare cleanly: what Nemo does by its
# own code with outside programs, no model (a model's speed is the engine's,
# read above from its own log). Each is skipped, and said, where its program
# is missing. Nothing is left behind: the model is built in a temporary folder.
MEASURE_TEXT = ("The old clockmaker opened the shop at seven, as he had done for forty years. "
                "Rain ran down the window and the bell above the door was quiet. ") * 12
MEASURE_MODEL = {"name": "Timekeeper measure", "shapes": [
    {"shape": "plate", "size": [40, 40], "thickness": 4},
    {"shape": "sphere", "radius": 10, "at": [0, 0, 12]}]}


def measure(cfg, repeats: int = MIN_RUNS, say=print) -> dict[str, list[float] | str]:
    """Run the fixed jobs `repeats` times, record each run (department
    "timekeeper", what "measure: <job>"), and return the seconds or why not."""
    import copy
    import tempfile
    import time
    from . import writer
    out: dict[str, list[float] | str] = {}

    def job(name, fn):
        secs = []
        for i in range(repeats):
            t0 = time.time()
            try:
                ok = fn()
            except Exception as exc:                            # noqa: BLE001
                out[name] = f"failed: {exc}"
                record("timekeeper", f"measure: {name}", time.time() - t0, False)
                return
            if ok is None:
                out[name] = "skipped: its program is not installed"
                return
            took = time.time() - t0
            record("timekeeper", f"measure: {name}", took, bool(ok))
            secs.append(round(took, 2))
            say(f"Timekeeper: {name}, run {i + 1} of {repeats}: {took:.1f} s")
        out[name] = secs

    job("spelling", lambda: None if writer.harper(cfg) is None
        else writer.check(MEASURE_TEXT, cfg=cfg) is not None)

    def model():
        from . import modelkit
        from .checks import FAIL
        with tempfile.TemporaryDirectory(prefix="nemo-measure-") as d:
            c = copy.deepcopy(cfg)
            c.data.setdefault("paths", {})["models"] = d
            _, results = modelkit.build(c, MEASURE_MODEL)
            if any("cadquery" in (r.detail or "").lower() and r.status != "PASS" for r in results):
                return None
            return not any(r.status == FAIL for r in results)
    job("model build", model)
    return out


def describe_jobs(found: list[JobTimes]) -> str:
    if not found:
        return "No job timings yet: none of these jobs has run since timing began."
    lines = []
    for t in found:
        if t.seconds:
            lines.append(f"{t.what:<14} {len(t.seconds):>3} run(s), {t.mean:>6.1f} s on average, "
                         f"{min(t.seconds):.1f} to {max(t.seconds):.1f} s"
                         + (f"; {t.failed} failed" if t.failed else ""))
        else:
            lines.append(f"{t.what:<14} no run finished; {t.failed} failed")
    return "\n".join(lines) + "\n(Measured by the clock, each run as it happened.)"
