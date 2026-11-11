"""Everything the desktop interface knows, with no Tk in it.

The window only draws what this module returns and calls what it offers, so
all of the behaviour can be tested without a display. Anything slow -- a
model step, loading a mode -- is not done here: it is run as the same
'nemo' command a person would type, in a separate process, so the interface
cannot drift from the command line (the lesson of D17) and a stuck step can
be stopped without taking the window down with it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..parts import PartsLibrary
from .. import steps as _steps
from ..project import STAGES, Brief, Project
from ..results import MODEL_STAGES, load_results, load_safety

# Plain names for each step, as a person would describe the work.
# The window's step names and help are in nemo/steps.py, with the rest of each step.
STEP_NAMES = {s.key: s.name for s in _steps.STEPS}
# What the Inspector stopped a step for (nemo/review.py), in the window.
REVIEW_NAMES = {
    "brief_incomplete": "the brief is not finished",
    "unknown_parts": "a part the library lacks",
    "no_board": "no board",
    "missing_rfid": "no RFID reader",
    "missing_microphone": "no microphone",
    "missing_distance": "no distance sensor",
    "missing_climate": "no temperature sensor",
    "missing_motion": "no motion sensor",
    "missing_sound_files": "nothing to play sound files",
    "missing_sound": "no speaker",
    "boards_many": "more than one board",
    "unexplained_parts": "parts nothing asks for",
    "shape_unsupported": "a shape Nemo cannot make",
    "no_supply": "no supply rating",
    "over_budget": "the supply is too small",
    "rails": "a part has no rail",
    "no_pins": "a part without pins",
    "no_envelope": "no inside size",
    "too_small": "the box is too small",
    "no_size": "a part without a size",
    "needs_parts": "parts step not passed",
    "needs_electrical": "schematic step not passed",
    "no_concept": "no concept chosen",
    "brief_spelling": "a spelling to check",
}

STEP_HELP = {s.key: s.help for s in _steps.STEPS}

CHECK_NAMES = {
    "current_sum": "Current against the supply",
    "supply_rails": "Voltage rails",
    "fits_envelope": "Fits in the enclosure",
    "safety": "Safety rules",
    "voltage_compat": "Logic voltages match",
    "schematic": "Schematic generated",
    "erc": "Electrical rules (KiCad)",
    "drc": "Board rules (KiCad)",
    "wireviz": "Harness drawing",
    "wire_gauge": "Wire thickness",
    "harness_pins": "Wires land on real pins",
    "harness_covers": "Every part is wired",
    "harness_electrical": "Every part has power and data",
    "harness_signals": "No wire does two jobs",
    "harness_levels": "Signal voltages suit both ends",
    "pin_current": "Current through each supply pin of the board",
    "keep_apart": "Parts that must be apart are",
    "harness_supply": "Every part gets a voltage it can take",
    "enclosure_script": "Enclosure script runs",
    "concepts": "Concepts drawn",
    "concept_pictures": "Pictures of each concept",
    "concept_choice": "Your choice",
    "designer_model": "The Designer's model of your choice",
    "fits_printer": "It fits the printer",
    "pieces_made": "Cut into pieces that fit, with pins",
    "solid": "Solid, printable shape",
    "thickness": "Wall thickness",
    "xref_cutouts": "Openings for panel parts",
    "compile": "Firmware compiles",
    "printability": "Prints without supports",
    "xref_nets": "Harness matches schematic",
}

_FINDING = re.compile(r"^(BLOCK|SIGN|note)\s+[\w]+:\s*(.*)$")


def check_name(name: str) -> str:
    if name.startswith("review_"):
        return "Inspector: " + REVIEW_NAMES.get(name[7:], name[7:].replace("_", " "))
    return CHECK_NAMES.get(name, name.replace("_", " ").capitalize())


def plain_item(item: str) -> str:
    """'note  enclosure_vent_required_above_ma: 560 mA exceeds ...' ->
    'Note: 560 mA exceeds ...' -- the rule id is for the log, not a person."""
    m = _FINDING.match(item.strip())
    if not m:
        return item
    label = {"BLOCK": "Blocked", "SIGN": "Needs your sign-off",
             "note": "Note"}[m.group(1)]
    return f"{label}: {m.group(2)}"


MODES = [
    ("off", "Off", 0),
    ("talk", "Talk (small, fast)", 2100),
    ("design", "Design (enclosures, schematics)", 3200),
    ("build", "Build (firmware)", 2100),
    ("tiny", "Tiny (low memory)", 900),
]

# Human gates: always present, whatever the design. The software cannot
# stop a print or an order; this is the record that a person checked.
GATES = [
    ("gate_print", "Checked the enclosure before printing it"),
    ("gate_order", "Checked the parts list before ordering"),
    ("gate_battery", "Checked the wiring before connecting a battery"),
]

_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,47}$")


def home() -> Path:
    return Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo"))


def config() -> Config:
    return Config.load()


# ====================================================================
#  Projects and briefs
# ====================================================================

def projects_root(cfg: Config | None = None) -> Path:
    return (cfg or config()).path("paths.projects")


def list_projects(cfg: Config | None = None) -> list[str]:
    root = projects_root(cfg)
    if not root.exists():
        return []
    found = [p.parent for p in root.glob("*/brief.yaml")]
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in found]


def display_name(folder: str, cfg: Config | None = None) -> str:
    """The name a person gave the project, not its folder name."""
    try:
        return open_project(folder, cfg).load_brief().name or folder
    except (OSError, TypeError, ValueError):
        return folder


def validate_name(name: str) -> str | None:
    """None if the name is usable, otherwise what is wrong with it."""
    name = name.strip()
    if not name:
        return "Give the project a name."
    if not _NAME_OK.match(name):
        return ("Use letters, numbers, spaces, hyphens or underscores, "
                "up to 48 characters.")
    return None


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-")


def create_project(name: str, cfg: Config | None = None) -> Project:
    problem = validate_name(name)
    if problem:
        raise ValueError(problem)
    root = projects_root(cfg) / slug(name)
    if (root / "brief.yaml").exists():
        raise ValueError(f"A project called '{name}' already exists.")
    return Project(root).create(Brief(name=name.strip()))


def open_project(name: str, cfg: Config | None = None) -> Project:
    return Project(projects_root(cfg) / name)


def brief_problems(brief: Brief) -> list[str]:
    """What still stops the brief being usable, in plain words."""
    labels = {"function": "what it does", "power": "the power source",
              "done_when": "how you'll know it works", "parts": "the parts",
              "envelope_mm": "the enclosure size"}
    ok, missing = brief.complete
    out = [labels.get(m, m) for m in missing]
    if not brief.supply_ma and not getattr(brief, "no_power", False):
        out.append("the supply rating in mA")
    return out


def parse_numbers(text: str) -> list[float]:
    """'140 x 100 x 70' or '5, 3.3' -> numbers. Ignores anything else."""
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text or "")]


_LOAD_LINE = re.compile(r"^(.*?)[\s,:;=]+(\d+(?:\.\d+)?)\s*(?:ma)?\s*$", re.I)


def parse_extra_loads(text: str) -> list[dict]:
    """The "Other loads" box, one per line, into the brief's extra_loads.

    'fan, 200' and '5 V fan 200 mA' are a name and a peak current: the
    last number on the line is the current, so a voltage in the name
    stays in the name. A line with no number at its end is kept with its
    name alone; the parts step then says it has no current and does not
    count it. Nothing typed is dropped silently (D162).
    """
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LOAD_LINE.match(line)
        name = m.group(1).strip(" ,:;=") if m else ""
        if m and name:
            ma = float(m.group(2))
            out.append({"name": name, "ma": int(ma) if ma.is_integer() else ma})
        else:
            out.append({"name": line})
    return out


def parse_facts(text: str) -> dict:
    """The Brief tab's "Its own figures": "barrel 444, muzzle bore 35" or one
    per line, into shape_facts {barrel_mm: 444.0, muzzle_bore_mm: 35.0}. A
    name without a number is left out: a figure is never guessed."""
    import re
    out = {}
    for item in re.split(r"[,;\n]+", text or ""):
        m = re.match(r"\s*([A-Za-z][A-Za-z _-]*?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm)?\s*$", item)
        if not m:
            continue
        key = re.sub(r"[\s-]+", "_", m.group(1).strip().lower())
        if not key.endswith("_mm"):
            key += "_mm"
        out[key] = float(m.group(2))
    return out


def format_facts(facts) -> str:
    return ", ".join(f"{k[:-3] if k.endswith('_mm') else k} {v:g}".replace("_", " ")
                     for k, v in (facts or {}).items() if isinstance(v, (int, float)))


def format_extra_loads(loads) -> str:
    """The brief's extra_loads as the box shows them. What the box cannot
    show (an entry that is not a name and a number) is shown as its name."""
    lines = []
    for item in loads or []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        ma = item.get("ma")
        usable = isinstance(ma, (int, float)) and not isinstance(ma, bool)
        lines.append(f"{str(item['name']).strip()}, {ma:g}" if usable
                     else str(item["name"]).strip())
    return "\n".join(lines)


# ====================================================================
#  Parts
# ====================================================================

def parts_catalog(cfg: Config | None = None) -> PartsLibrary:
    extra = (cfg or config()).get("paths.parts")
    return PartsLibrary.load(*([Path(extra).expanduser()] if extra else []))


# ====================================================================
#  Steps
# ====================================================================

@dataclass
class StepRow:
    stage: str
    number: int
    name: str
    help: str
    status: str          # passed | failed | unchecked | done | not run
    when: int = 0
    needs_model: bool = False
    record: dict | None = None


def step_rows(project: Project) -> list[StepRow]:
    results = load_results(project.root)
    have = project.status()
    rows = []
    for i, stage in enumerate(STAGES, 1):
        rec = results.get(stage)
        if rec:
            if not rec.get("ok"):
                status = "failed"
            elif any(c.get("status") == "SKIP" for c in rec.get("checks", [])):
                # Ran, but some checks could not: not the same as passing.
                status = "unchecked"
            else:
                status = "passed"
        elif have.get(stage):
            status = "done"
        else:
            status = "not run"
        rows.append(StepRow(stage, i, STEP_NAMES[stage], STEP_HELP[stage],
                            status, (rec or {}).get("when", 0),
                            stage in MODEL_STAGES, rec))
    return rows


def concept_state(project: Project, library):
    """(concepts, choice or None, signature, folder, box) for the project's
    current parts and envelope. concepts is [] where none are drawn for them."""
    from .. import concept, enclosure
    brief = project.load_brief()
    parts = [p for p in (library.get(r) for r in brief.parts) if p]
    sig = concept.current_signature(brief, parts)
    try:
        box = enclosure.box_for(brief.envelope_mm, Config.load().get("hardware", {}))
    except enclosure.EnclosureError:
        box = None
    return (concept.load(project.root, sig), concept.chosen(project.root, sig), sig,
            concept.folder(project.root), box, parts)


def choose_concept(project: Project, library, key: str, corners: str, notch_wall: str,
                   notes: str):
    from .. import concept, review
    sig = concept_state(project, library)[2]
    pick = concept.choose(project.root, key, sig, corners, notch_wall, notes)
    review.record(project.root, "concept", "chosen", by="owner", concept=pick.concept,
                  changes=bool(pick.notes))
    return pick


def concept_waiting(project: Project, library) -> bool:
    """Concepts are drawn for the current design and none is chosen."""
    try:
        drawn, pick = concept_state(project, library)[:2]
    except Exception:                                       # noqa: BLE001
        return False
    return bool(drawn) and pick is None


def next_step(project: Project) -> str | None:
    for row in step_rows(project):
        if row.status in ("not run", "failed"):
            return row.stage
    return None


# ====================================================================
#  Sign-offs
# ====================================================================

def signoff_items(project: Project) -> list[tuple[str, str]]:
    items = list(GATES)
    for f in load_safety(project.root):
        if f.get("severity") == "signoff":
            items.append((f"safety_{f['rule']}", f["detail"]))
    return items


def _signoff_path(project: Project) -> Path:
    return project.root / "signoffs.json"


def signoffs(project: Project) -> dict:
    return project.given_signoffs()


def set_signoff(project: Project, key: str, by: str, signed: bool) -> None:
    by = by.strip()
    if signed and not by:
        raise ValueError("Enter your name before signing.")
    data = signoffs(project)
    if signed:
        data[key] = {"by": by, "when": int(time.time())}
    else:
        data.pop(key, None)
    _signoff_path(project).write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Every signature and withdrawal goes into the tamper-evident log.
    try:
        from ..admin import AdminStore
        from ..authority import store_dir
        AdminStore(store_dir()).append_audit(
            "signoff" if signed else "signoff_withdrawn",
            {"project": project.root.name, "item": key, "by": by})
    except OSError:
        pass


# ====================================================================
#  Files
# ====================================================================

FILE_GROUPS = [("Build guide", ["BUILD.md", "pack.pdf", "assignment.md"]),
               ("Brief and parts", ["brief.yaml", "bom.csv", "power-budget.md"]),
               ("Schematic", ["electrical/*"]),
               ("Wiring", ["wiring/*"]),
               ("Concept", ["concept/*.svg", "concept/*-iso.png", "concept/*-painted.png", "concept/choice.json"]),
               ("Enclosure", ["enclosure/*", "enclosure/drawings/*", "renders/*.png", "renders/*.txt"]),
               ("Firmware", ["firmware/platformio.ini", "firmware/src/*"])]


def project_files(project: Project) -> list[tuple[str, Path]]:
    out = []
    for group, patterns in FILE_GROUPS:
        for pat in patterns:
            for f in sorted(project.root.glob(pat)):
                if f.is_file() and not f.name.startswith("."):
                    out.append((group, f))
    return out


def open_path(path: Path) -> None:
    path = Path(path)
    if sys.platform.startswith("win"):
        os.startfile(str(path))                     # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ====================================================================
#  Running 'nemo' commands
# ====================================================================

def python_for_children() -> str:
    """python.exe, not pythonw.exe, so child output can be read."""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        alt = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(alt):
            return alt
    return exe


def nemo_argv(*args: str) -> list[str]:
    return [python_for_children(), "-u", "-m", "nemo.cli", *args]


def parse_event(line: str) -> dict | None:
    if not line.startswith("@@NEMO "):
        return None
    try:
        return json.loads(line[len("@@NEMO "):])
    except json.JSONDecodeError:
        return None


# ====================================================================
#  Settings
# ====================================================================

def logo(size: int) -> Path:
    """Nemo's cog (owner, 2026-10-21): the eight departments as its teeth, N
    on the hub. Sizes shipped: 16, 32, 64, 120, 150 and 256 (the cog alone, on
    clear), and 512 and 1024 (the whole picture; the 1024 fills the prompt
    window). Redrawn 2026-10-22 with a tooth for every department."""
    return Path(__file__).resolve().parent.parent / "data" / "logo" / f"nemo-cog-{size}.png"


def logo_ico() -> Path:
    """Nemo's cog as a Windows icon (owner, 2026-10-29: "sort out Nemo icon"):
    16 to 256 px, the shipped small cogs used as they are."""
    return Path(__file__).resolve().parent.parent / "data" / "logo" / "nemo.ico"


def department_card(key: str) -> Path:
    """A department's card, laid on its painted scene (tools/draw_departments.py),
    for the prompt window's home scene (owner, 2026-10-22)."""
    return Path(__file__).resolve().parent.parent / "data" / "departments" / f"{key}.jpg"


def logo_part(name: str) -> Path:
    """One of the 1024 cog's glow masks, "halo" (round its edge) or "logos"
    (round each department's logo), for the prompt window's glow."""
    return Path(__file__).resolve().parent.parent / "data" / "logo" / f"nemo-cog-{name}-1024.png"


def load_settings() -> dict:
    p = home() / "gui.json"
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict) -> None:
    p = home() / "gui.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ====================================================================
#  Power suggestions and fixes (logic in nemo.fixes)
# ====================================================================

def power_plan_for(brief, library):
    from ..fixes import power_plan
    parts = [library.get(r) for r in brief.parts]
    return power_plan([p for p in parts if p], library, brief.power)


def fixes_for(project: Project, stage: str, library, cfg: Config | None = None):
    from ..fixes import suggest_fixes
    rec = load_results(project.root).get(stage)
    if not rec:
        return []
    ok_and_checked = rec.get("ok") and not any(
        c.get("status") == "SKIP" for c in rec.get("checks", []))
    if ok_and_checked:
        return []
    min_wall = float((cfg or config()).get("hardware.min_wall_mm", 1.2))
    return suggest_fixes(project.load_brief(), library, stage, rec,
                         load_safety(project.root), min_wall, project.root)


def apply_fix_to_project(project: Project, fix) -> None:
    """Apply one chosen fix to the brief, and record it in git."""
    from ..fixes import apply_fix
    brief = apply_fix(project.load_brief(), fix)
    project.save_brief(brief)
    project.commit("brief", f"applied suggested fix: {fix.title}")


# ====================================================================
#  Adding a part (logic in nemo.parts)
# ====================================================================

def known_categories() -> list[str]:
    from ..parts import KNOWN_CATEGORIES
    return list(KNOWN_CATEGORIES)


def check_new_part(data: dict, cfg: Config | None = None,
                   allow_overwrite: bool = False) -> list[str]:
    from ..parts import validate_part
    existing = set(parts_catalog(cfg).parts.keys())
    return validate_part(data, existing_refs=existing,
                         allow_overwrite=allow_overwrite)


def add_new_part(data: dict, cfg: Config | None = None,
                 allow_overwrite: bool = False):
    """Save a part to the user's own file. Raises ValueError with the
    problems if it is not valid -- callers should check_new_part() first
    to show them in the form, but this guards against a stale check too."""
    from ..parts import save_part, validate_part
    cfg = cfg or config()
    existing = set(parts_catalog(cfg).parts.keys())
    problems = validate_part(data, existing_refs=existing,
                             allow_overwrite=allow_overwrite)
    if problems:
        raise ValueError("\n".join(problems))
    save_part(cfg.path("paths.parts"), data)

