"""The Doctors: diagnose what has gone wrong, and advise (owner, 2026-10-21).

The owner's words: "within department can diagnose and suggest to errors
only with user agreement". Nothing here changes anything: it diagnoses and
advises. A finding with a `remedy` can be treated by the Nurse
(nemo/nurse.py, phase 2), and only on the owner's yes, one at a time, with a
copy kept to undo it.

The rules, from the agreed layout:
  - Diagnosing only reads: files, records, the machine check.
  - What is not known is said to be not known. A symptom no rule here
    explains is shown in the evidence's own words, never given a meaning.
  - No language model: the model may be the patient, and the rules are code,
    so the same machine always gets the same diagnosis.
  - Nothing touches the safety limits, signing, lockdown or keys.

The GP asks each specialist in turn; one that fails is recorded as such and
the others still run. The Records Clerk writes every visit to
~/.nemo/clinic/cases.jsonl.
"""
from __future__ import annotations

import datetime as _dt
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

NEEDS = "needs attention"
LOOK = "worth a look"

# Fragments of router.explain_failure's sentences, as a failed model step
# saves them in its notes. tests/test_clinic.py ties each to what
# explain_failure really says, so a change there fails here first.
MODEL_NOTES = {
    "The model had not finished after": (
        "a model step ran past the time limit",
        "The model was still writing when the limit passed: on this laptop a long "
        "reply can take that long.",
        "Raise engine.timeout_s in config.yaml, or use a smaller mode for that step.",
        "raise_timeout"),
    "The language model server refused the request": (
        "the model server refused a step's question",
        "The model was loaded, but would not take the question; the server's reason "
        "is in the step's notes.",
        "Read the server's reason in the step's notes; this one is not known to the "
        "Doctors yet. Keep the case notes for a report.", ""),
    "The language model stopped answering part way through": (
        "the model stopped answering during a step",
        "The model server went away or stopped responding mid-reply.",
        "Check a model is loaded (the Model box at the top, or 'nemo mode'); load it again and re-run "
        "the step.", ""),
    "The model call could not be made": (
        "a step could not ask the model",
        "No model server could be reached when the step asked.",
        "Load a model first (the Model box at the top, or 'nemo mode talk'), then re-run the step.",
        ""),
    # 2026-11-04: a refused connection is no model at all, not one that stopped.
    "No language model is loaded": (
        "a step asked a model and none was loaded",
        "Nothing answered at the model's address: no mode had been started.",
        "Load the mode the step needs (the Model box at the top, or 'nemo mode design'), "
        "then re-run the step.", ""),
}


@dataclass
class Finding:
    specialist: str          # a staff.STAFF key, "doctors.<role>"
    severity: str            # NEEDS or LOOK
    what: str                # the symptom, as seen
    diagnosis: str           # what it means, or that it is not known
    advice: str              # the remedy, in words
    evidence: str = ""
    remedy: str = ""         # a nurse.REMEDIES key the Nurse can apply on a yes, or ""


@dataclass
class Case:
    at: float
    findings: list[Finding] = field(default_factory=list)
    seen_by: list[str] = field(default_factory=list)       # specialists that ran
    failed: list[str] = field(default_factory=list)        # specialists that could not

    @property
    def healthy(self) -> bool:
        return not self.findings and not self.failed


# ------------------------------------------------------------ specialists
def machine(cfg) -> list[Finding]:
    """The machine check (nemo/doctor.py), its warnings and failures."""
    from . import doctor
    out = []
    for f in doctor.run():
        if f.status in (doctor.FAIL, doctor.WARN):
            out.append(Finding("doctors.machine", NEEDS if f.status == doctor.FAIL else LOOK,
                               f.title, f.detail,
                               "Check this machine shows the whole report and what to do."))
    return out


# Where NVIDIA cards commonly begin to slow themselves to cool down: a rule
# of thumb, NOT this card's datasheet figure (none was looked up).
GPU_HOT_C = 83


def gpu(cfg, status=None) -> list[Finding]:
    """The graphics card (owner, 2026-11-04): heat, and whether the design
    mode and a painting fit in what is free on it now. Nothing to say on a
    machine without an NVIDIA card (the laptop)."""
    from . import artist, machine, modes
    s = status if status is not None else machine.gpu_status()
    if not s:
        return []
    out = []
    name = s.get("name") or "the card"
    temp = s.get("temperature.gpu")
    if temp is not None and temp >= GPU_HOT_C:
        out.append(Finding("doctors.gpu", LOOK, f"{name} is at {temp:.0f} C",
                           f"At {GPU_HOT_C} C or more NVIDIA cards commonly slow themselves to cool "
                           "down (a rule of thumb, not this card's datasheet).",
                           "Give the case air: clear the vents, check the card's fan turns. Nemo's "
                           "models run slower while it is this hot.",
                           evidence=f"nvidia-smi temperature.gpu {temp:.0f}"))
    free = s.get("memory.free")
    if free is not None and not modes.current().running:
        try:
            spec = cfg.data.get("modes_desktop", {}).get("design", {})
            need = int(spec.get("vram_mb", 0)) + modes.VRAM_MARGIN_MIB
        except (AttributeError, TypeError, ValueError):
            need = 0
        if need and free < need:
            paint = (f" A painting ({artist.GPU_VRAM_MB} MiB) will not fit either."
                     if free < artist.GPU_VRAM_MB else "")
            out.append(Finding("doctors.gpu", LOOK, f"Only {free:.0f} MiB free on {name}",
                               f"Design mode needs about {need} MiB there and no model of Nemo's is "
                               "loaded, so another program is holding the rest." + paint,
                               "Close games, video editors or other programs using the card; "
                               "talk, build and tiny modes need less.",
                               evidence=f"nvidia-smi memory.free {free:.0f}, used {s.get('memory.used')}"))
        elif free < artist.GPU_VRAM_MB:              # no desktop design mode to measure against
            out.append(Finding("doctors.gpu", LOOK, f"Too little free on {name} to paint",
                               f"A painting needs about {artist.GPU_VRAM_MB} MiB; {free:.0f} is free.",
                               "Close what is using the card before asking the Artist."))
    return out


def _step_modes() -> list[str]:
    from . import steps
    return sorted({s.mode for s in steps.STEPS if s.uses_model})


def model(cfg) -> list[Finding]:
    from . import modes
    from .platform_probe import IS_WINDOWS, mem_available_mb, mem_total_mb
    out = []
    st = modes.current()
    if st.name and not st.running:
        out.append(Finding(
            "doctors.model", LOOK,
            f"Nemo's record says the {st.name} model is loaded, but its process "
            f"({st.pid}) has ended.",
            "The model server stopped or crashed without Nemo stopping it.",
            f"Load it again (the Model box at the top, or 'nemo mode {st.name}'); that "
            "replaces the old record.",
            str(modes.STATE), remedy="clear_record"))
    total, have = mem_total_mb(), mem_available_mb()
    for name in _step_modes():
        try:
            spec = cfg.mode(name)
        except Exception as exc:                                # noqa: BLE001
            out.append(Finding("doctors.model", NEEDS, f"The {name} mode is not set up.",
                               str(exc), f"Put the {name} mode back in config.yaml."))
            continue
        try:
            modes.model_path(cfg, spec["model"])
        except FileNotFoundError as exc:
            out.append(Finding("doctors.model", NEEDS,
                               f"The {name} mode's model, {spec['model']}, is not on disk.",
                               "Steps that use this mode cannot load a model.", str(exc)))
        need, _, _ = modes.memory_need(spec)
        if total and total < need:
            out.append(Finding("doctors.model", NEEDS,
                               f"The {name} mode needs about {need} MB; this machine has "
                               f"{total} MB in all.",
                               "It cannot load here, whatever is closed.",
                               f"Use a smaller model for {name} in config.yaml."))
        # As start() decides: with no model loaded and none stopped just now
        # (whose memory is still coming back, D191), short is refused.
        elif have and have < need and not st.running and not modes._stopped_recently():
            out.append(Finding("doctors.model", LOOK,
                               f"The {name} mode needs about {need} MB; {have} MB is free now.",
                               "It would be refused if loaded now.",
                               "Close what you can (a browser, KiCad) before loading it."
                               + (" trim.ps1 in the NemoWin folder frees more."
                                  if IS_WINDOWS else "")))
    out += _server_words()
    return out


def _server_words() -> list[Finding]:
    """The last error lines in the most recent model log, in its own words:
    the Doctors know no meaning for them yet, so they give none."""
    from . import modes
    logs = [modes.STATE.parent / f"{m}.log" for m in _step_modes()]
    logs = [p for p in logs if p.is_file()]
    if not logs:
        return []
    last = max(logs, key=lambda p: p.stat().st_mtime)
    try:
        lines = last.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
    except OSError:
        return []
    errors = [l.strip() for l in lines if "error" in l.lower()]
    if not errors:
        return []
    return [Finding("doctors.model", LOOK,
                    f"The model server's last log ({last.name}) has error lines.",
                    "Not known: the Doctors have no rule for these words yet.",
                    "Keep the case notes; if a step is failing, they say what the server saw.",
                    "\n".join(errors[-5:]))]


def design(cfg) -> list[Finding]:
    """Failed steps in each project, and where their fixes are. A model
    failure saved in a step's notes goes to the Model Specialist's words."""
    from .results import load_results
    from .steps import ORDER
    out = []
    root = cfg.path("paths.projects")
    if not root.is_dir():
        return out
    for proj in sorted(p for p in root.iterdir() if p.is_dir()):
        results = load_results(proj)
        for step in ORDER:
            rec = results.get(step)
            if not rec or rec.get("ok"):
                continue
            notes = [n for n in rec.get("notes", []) if isinstance(n, str)]
            said = next(((frag, n) for n in notes for frag in MODEL_NOTES if n.startswith(frag)),
                        None)
            if said:
                what, why, advice, remedy = MODEL_NOTES[said[0]]
                out.append(Finding("doctors.model", NEEDS, f"{proj.name}, {step}: {what}.",
                                   why, advice, said[1], remedy))
                continue
            failed = [c["name"] for c in rec.get("checks", []) if c.get("status") == "FAIL"]
            if failed == ["concept_choice"]:
                # Waiting for the owner, not broken (2026-11-06: two concepts
                # drawn and waiting were called "the concept step failed").
                out.append(Finding("doctors.design", LOOK,
                                   f"{proj.name}: its concepts are waiting for your choice.",
                                   "Nothing is wrong: Nemo drew two and goes on once you "
                                   "choose one.",
                                   f"Choose a concept on the Build tab, or 'nemo --project "
                                   f"{proj.name} concept choose A'.",
                                   "\n".join(notes[:3])))
                continue
            if any(n.startswith("review_") for n in failed):
                why = "The Inspector stopped it before it began; its reasons are with the step."
            elif failed:
                why = "Its checks failed: " + ", ".join(failed) + "."
            else:
                why = "Not known: it failed with no failed check and no model note."
            out.append(Finding("doctors.design", NEEDS, f"{proj.name}: the {step} step failed.",
                               why, f"See its fixes in the window, or 'nemo --project "
                                    f"{proj.name} fix --stage {step}'.",
                               "\n".join(notes[:3])))
    return out


def stick(cfg) -> list[Finding]:
    from . import storage
    if not storage.has_stick():
        return []                       # not a live stick: the work is on a disk
    said = storage.status() or ""
    if "nothing is kept" in said:
        return [Finding("doctors.stick", NEEDS, "Work is not being kept on the stick.",
                        "nemo-sync says: " + said,
                        "Until this is put right, copy work off before shutting down "
                        "(Storeroom, Back up Nemo, to another drive).")]
    return []


def records(cfg) -> list[Finding]:
    """The GP's own look at the owner's records: the Storeroom and backups."""
    from . import backup, storeroom
    out = []
    try:
        storeroom.load(cfg.path("paths.storeroom"))
    except storeroom.StoreroomError as exc:
        out.append(Finding("doctors.gp", NEEDS, "The Storeroom's catalogue cannot be read.",
                           str(exc), "Open stock.yaml and put right what it names, or move "
                                     "it aside and start a new one.",
                           remedy="set_aside_stock"))
    projects = cfg.path("paths.projects")
    has_work = projects.is_dir() and any(p.is_dir() for p in projects.iterdir())
    if has_work and not backup.listing():
        out.append(Finding("doctors.gp", LOOK, "No backup has been made.",
                           f"There is work in {projects} and no backup in "
                           f"{backup.default_folder()}.",
                           "Storeroom, Back up Nemo (a backup in another folder is not "
                           "seen here).", remedy="backup"))
    # The Timekeeper's record (2026-11-08): a job this machine now does
    # SLOWER-times slower than in the build before. Said, never treated: the
    # cause is not known from times alone.
    from . import timekeeper
    for c in timekeeper.changes():
        if c.machine == timekeeper.machine() and c.ratio >= timekeeper.SLOWER:
            out.append(Finding("doctors.gp", LOOK, f"'{c.what}' is slower in this build.",
                               "Measured by the clock; what in the build did it is not known.",
                               "nemo times --measure measures again; if it holds, the change "
                               "in this build is the place to look.", evidence=c.line()))
    return out


# Needs the round leaves out: a look at a web site is the network's state, not a
# fault of Nemo's (the Researcher says it when asked), and a job not built is the
# roster's, not a missing tool (2026-11-11).
_ROUND_SKIPS = ("Wikipedia", "Mouser", "its job")


def departments(cfg, rows=None) -> list[Finding]:
    """The GP's round of every department (owner, 2026-11-11: "updates to all
    departments"): each employee's tools (toolkit.NEEDS, the same looks as
    `nemo staff`), one finding per department with something missing. Looks only."""
    from . import staff, toolkit
    if rows is None:
        rows = toolkit.check(cfg)
    missing: dict[str, list[str]] = {}
    for r in rows:
        if r.ok or r.need in _ROUND_SKIPS:
            continue
        emp = staff.STAFF.get(r.employee)
        if emp is None or not emp.working:
            continue
        missing.setdefault(emp.department, []).append(f"{emp.label}: {r.need}: {r.detail}")
    out = []
    for key, lines in missing.items():
        name = staff.DEPARTMENTS[key].name if key in staff.DEPARTMENTS else key
        n = len(lines)
        out.append(Finding("doctors.gp", LOOK,
                           f"The {name} is missing {n} thing{'s' if n > 1 else ''} its people need.",
                           "Each line is the employee, what it needs, and what was found. "
                           "Only that employee's job is held up; the rest of the department works.",
                           f"NemoDoc installs Nemo's tools (run it again); 'nemo staff {key}' "
                           "shows the department's whole list.",
                           evidence="\n".join(lines)))
    return out


def updates(cfg, kept=None) -> list[Finding]:
    """Newer versions of the departments' tools, from the last look
    (`nemo clinic updates`; nemo/toolupdates.py). Reads the kept look only: an
    ordinary visit never goes on the network. Said, never taken."""
    from . import toolupdates
    kept = toolupdates.last() if kept is None else kept
    if not kept:
        return []
    at, looks = kept
    when = _dt.datetime.fromtimestamp(at).strftime("%Y-%m-%d")
    return [Finding("doctors.gp", LOOK, f"{x.label}: {x.latest} is out (Nemo has {x.ours}).",
                    f"Found by the look for newer tools on {when}. Nemo's pins, hashes and the way "
                    "it drives the tool were checked with the version it has, not this one.",
                    "Not taken on its own. Say if you want it: the new version is fetched on your "
                    "yes, its hash pinned, and the department's tests run with it.",
                    evidence=x.url)
            for x in looks if x.newer]


SPECIALISTS = (("doctors.machine", machine), ("doctors.gpu", gpu), ("doctors.model", model),
               ("doctors.design", design), ("doctors.stick", stick),
               ("doctors.gp", records), ("doctors.gp", departments), ("doctors.gp", updates))


# ------------------------------------------------------------------- the GP
def examine(cfg, who=None) -> Case:
    """Every specialist looks; nothing is changed. A specialist that fails
    is named, and the rest still look."""
    case = Case(time.time())
    for key, fn in (SPECIALISTS if who is None else who):
        try:
            case.findings += fn(cfg)
            if key not in case.seen_by:
                case.seen_by.append(key)
        except Exception as exc:                                # noqa: BLE001
            case.failed.append(f"{key}: {type(exc).__name__}: {exc}")
    order = {NEEDS: 0, LOOK: 1}
    case.findings.sort(key=lambda f: order.get(f.severity, 2))
    return case


# ---------------------------------------------------------- the case notes
def notes_path() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "clinic" / "cases.jsonl"


def record(case: Case) -> Path:
    """The Records Clerk: one line per visit. Phase 1 applies nothing, so
    every visit's `applied` is empty, and says so."""
    path = notes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"at": int(case.at), "findings": [asdict(f) for f in case.findings],
            "seen_by": case.seen_by, "failed": case.failed, "applied": []}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return path


def past(n: int = 20) -> list[dict]:
    """The last `n` visits, newest first."""
    path = notes_path()
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "findings" in d:                 # treatments are the Nurse's (nurse.treatments)
            out.append(d)
    return out[::-1][:n]


def report(cfg, out_dir: Path | None = None) -> Path:
    """The Doctors' Writer: a case report the owner can send (phase 3).

    What it holds: this machine (system, processor, memory), the last
    visit's findings, the latest treatments, and which employees lack a
    tool. What it never holds: briefs, stories, keys or the owner's files.
    Project names are replaced by "project 1", "project 2"... (some are the
    owner's private names), and his home folder by "~". Nothing is sent: the
    file is for the owner to read first and send himself."""
    import datetime as dt
    from . import __version__, nurse, toolkit
    from .platform_probe import cpu_model, mem_total_mb, os_label
    from .staff import STAFF
    projects = cfg.path("paths.projects")
    names = sorted((p.name for p in projects.iterdir() if p.is_dir()), key=len, reverse=True) \
        if projects.is_dir() else []
    home = str(Path.home())

    def clean(text: str) -> str:
        text = str(text).replace(home, "~").replace(home.replace("\\", "/"), "~")
        for n, name in enumerate(sorted(names), 1):
            text = text.replace(name, f"project {n}")
        return text

    visit = next(iter(past(1)), None)
    lines = [f"# Nemo case report, {dt.datetime.now():%d %b %Y %H:%M}", "",
             f"Nemo {__version__}; {os_label()}; {cpu_model()}; {mem_total_mb()} MB of memory.", ""]
    lines.append("## The last visit")
    if visit is None:
        lines.append("No visit yet: see the Doctors first.")
    else:
        lines.append(f"{dt.datetime.fromtimestamp(visit['at']):%d %b %Y %H:%M}")
        for f in visit.get("findings", []) or [{"severity": "", "what": "nothing found"}]:
            lines.append(f"- [{f.get('severity', '')}] {clean(f.get('what', '')).rstrip('.')}: "
                         f"{clean(f.get('diagnosis', ''))}")
            for e in str(f.get("evidence", "")).splitlines()[:5]:
                lines.append(f"    {clean(e)}")
        for x in visit.get("failed", []):
            lines.append(f"- could not look: {clean(x)}")
    lines += ["", "## Treatments, newest first"]
    done = nurse.treatments()[:10]
    lines += [f"- {dt.datetime.fromtimestamp(t['at']):%d %b %H:%M} {t['title']}"
              + (" (undone)" if t["undone"] else "") for t in done] or ["None."]
    lines += ["", "## Employees missing a tool"]
    try:
        missing = [r for r in toolkit.check(cfg) if not r.ok]
    except Exception as exc:                                    # noqa: BLE001
        missing, lines = [], lines + [f"The tools check failed: {exc}"]
    lines += [f"- {STAFF[r.employee].label}: {r.need}: {clean(r.detail)}" for r in missing] or ["None."]
    lines += ["", "(Written by Nemo's Doctors. It holds no briefs, stories, keys or files of "
                  "yours; project names are replaced. Read it before you send it.)", ""]
    out_dir = Path(out_dir) if out_dir else notes_path().parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"case-report-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def describe(case: Case) -> str:
    """The case in plain words, for the terminal and the window."""
    from .staff import STAFF
    when = _dt.datetime.fromtimestamp(case.at).strftime("%d %b %Y %H:%M")
    lines = [f"The Doctors, {when}."]
    if case.healthy:
        lines.append("Nothing found that needs attention.")
    for n, f in enumerate(case.findings, 1):
        title = STAFF[f.specialist].title if f.specialist in STAFF else f.specialist
        lines += ["", f"{n}. [{f.severity}] {f.what}", f"  {title}: {f.diagnosis}",
                  f"  Advice: {f.advice}"]
        if f.evidence:
            lines += ["  Seen: " + l for l in f.evidence.splitlines()]
        if f.remedy:
            lines.append(f"  The Nurse can do this for you, if you say yes: nemo clinic treat {n}")
    for x in case.failed:
        lines += ["", f"[could not look] {x}"]
    lines += ["", "Looking changed nothing. A remedy is applied only when you say yes, "
                  "one at a time."]
    return "\n".join(lines)
