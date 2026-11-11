"""A Nemo project is a folder, a brief, and a git history.

Committing after every stage is not bookkeeping. On a machine where a single
generation takes minutes, being able to reset one stage instead of rerunning
the whole pipeline is the difference between usable and not.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import yaml

from . import steps as _steps

STAGES = _steps.ORDER                  # the one list: nemo/steps.py


def _split_sentence(text: str, name: str) -> list[str]:
    import re
    text = text.strip()
    if not text:
        return []
    if name in ("parts", "accepted"):
        return [t for t in re.split(r"[\s,;]+", text) if t]
    # Questions end at "?"; other lists at a line break or ";" (a comma is
    # inside a clause as often as between items, so it does not split).
    if name == "open_questions" and "?" in text:
        out = [q.strip(" ;,\n") + "?" for q in text.split("?") if q.strip(" ;,\n")]
        return out
    return [t.strip() for t in re.split(r"[\n;]+", text) if t.strip()]


def _as_list(value, name: str) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_sentence(value, name)
    value = list(value)
    # A sentence saved letter by letter: every item one character, and
    # enough of them that it cannot be a list of single-letter refs.
    if len(value) > 3 and all(isinstance(v, str) and len(v) <= 1 for v in value):
        joined = "".join(value)
        # The window's box put each letter on a line and dropped the blank
        # ones on the way back, so the spaces are gone; the commas are not.
        if " " not in joined and "," in joined and name != "open_questions":
            return [t for t in joined.split(",") if t]
        return _split_sentence(joined, name)
    return [str(v) if not isinstance(v, str) else v for v in value]


def _as_numbers(value) -> list[float]:
    import re
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", value)]
    out = []
    for v in value:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            pass
    return out


@dataclass
class Brief:
    name: str
    function: str = ""
    user: str = ""                       # who uses it, and how
    power: str = ""                      # "USB 5V 1A" | "500mAh LiPo"
    supply_ma: float = 0.0
    rails: list[float] = field(default_factory=lambda: [5.0, 3.3])
    envelope_mm: list[float] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)   # refs into the library
    mcu: str = ""
    done_when: str = ""
    constraints: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    # Things that draw current and are not in the parts library: each
    # {name: fan, ma: 200}, the owner's own peak figure. Counted in the
    # power budget and nowhere else (D162).
    extra_loads: list[dict] = field(default_factory=list)
    # Reviewer findings the owner has said are right (nemo/review.py):
    # e.g. missing_rfid when an RFID word in the brief is not a reader.
    accepted: list[str] = field(default_factory=list)
    # The owner's answer that the thing needs no power, or no parts at all
    # (owner's request, 2026-10-18): a holder, a case, a passive prop. The
    # brief then does not ask for them, and the steps that need them say
    # they are not needed instead of failing.
    no_power: bool = False
    no_parts: bool = False
    # A shaped object's real size, [long, wide, high] in mm, 0 where not known
    # (owner, 2026-11-04: the blunderbuss "at full size instead of shrinking").
    # Its concepts are drawn this size; one longer than the printer is built in
    # pieces with pins (nemo/joints.py). Not the inside size (envelope_mm).
    shape_size_mm: list[float] = field(default_factory=list)
    # A shaped object's own figures for its family (nemo/anatomy.py), from a
    # source the owner gives: e.g. a long gun's barrel_mm and muzzle_bore_mm.
    # Anything not given is estimated, and the concept says so.
    shape_facts: dict = field(default_factory=dict)

    def __post_init__(self):
        """Lists are lists. D182, the AH531 on 2026-10-18: the model gave
        constraints and open_questions as one sentence each, and everything
        that walked them as lists walked them letter by letter: the brief
        was saved one character per line, and every model prompt was sent
        one-letter constraints. A sentence is split into its parts here, and
        a list that is a sentence spelt out one character at a time, as the
        briefs saved then are, is joined and split properly."""
        for name in ("constraints", "open_questions", "parts", "accepted"):
            setattr(self, name, _as_list(getattr(self, name), name))
        for name in ("rails", "envelope_mm", "shape_size_mm"):
            setattr(self, name, _as_numbers(getattr(self, name)))

    @property
    def complete(self) -> tuple[bool, list[str]]:
        missing = [f for f in ("function", "power", "done_when")
                   if not getattr(self, f) and not (f == "power" and self.no_power)]
        if not self.parts and not self.no_parts:
            missing.append("parts")
        # A shaped object with no parts has no inside to size: its own real
        # size is what is missing (the blunderbuss, 2026-11-05: its brief asked
        # for an enclosure's inside size).
        from .review import shape_asked
        prop = self.no_parts and shape_asked(self)
        if prop:
            if not self.envelope_mm and not any(v > 0 for v in (self.shape_size_mm or [])):
                missing.append("shape_size_mm")
        elif not self.envelope_mm:
            missing.append("envelope_mm")
        return (not missing), missing


class Project:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    # --- layout -------------------------------------------------------

    @property
    def brief_path(self) -> Path:
        return self.root / "brief.yaml"

    @property
    def bom_path(self) -> Path:
        return self.root / "bom.csv"

    @property
    def power_path(self) -> Path:
        return self.root / "power-budget.md"

    @property
    def schematic(self) -> Path:
        return self.root / "electrical" / "project.kicad_sch"

    @property
    def board(self) -> Path:
        return self.root / "electrical" / "project.kicad_pcb"

    @property
    def harness(self) -> Path:
        return self.root / "wiring" / "harness.yaml"

    @property
    def connections(self) -> Path:
        """Which pin goes to which pin: the one thing the model decides
        about the circuit. The schematic and the harness are both written
        from it."""
        return self.root / "electrical" / "connections.json"

    @property
    def housing_script(self) -> Path:
        return self.root / "enclosure" / "housing.py"

    @property
    def housing_stl(self) -> Path:
        return self.root / "enclosure" / "housing.stl"

    @property
    def firmware(self) -> Path:
        return self.root / "firmware"

    @property
    def build_md(self) -> Path:
        return self.root / "BUILD.md"

    # --- lifecycle ----------------------------------------------------

    def create(self, brief: Brief) -> "Project":
        for sub in ("electrical", "wiring", "enclosure", "firmware",
                    "render", "datasheets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.save_brief(brief)
        (self.root / ".gitignore").write_text(
            "build.log\n.pio/\n__pycache__/\n*.pyc\n"
            "# never commit keys\n.env\n", encoding="utf-8")
        self.git_init()
        self.commit("brief", "project created")
        return self

    def save_brief(self, brief: Brief) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.brief_path.write_text(
            yaml.safe_dump(asdict(brief), sort_keys=False), encoding="utf-8")

    def load_brief(self) -> Brief:
        if not self.brief_path.exists():
            raise FileNotFoundError(
                f"no brief at {self.brief_path}; run 'nemo new' first")
        return Brief(**(yaml.safe_load(self.brief_path.read_text(encoding="utf-8", errors="replace")) or {}))

    # --- git ----------------------------------------------------------

    @staticmethod
    def _no_git() -> bool:
        """Git off for this process: missing, or NEMO_PROJECT_GIT=off. The
        test sandbox sets the second. Measured on the AH531, each git call
        takes 0.3 s to start, and creating and committing test projects was
        78 s of a 102 s test file; no test but the git ones reads history."""
        return os.environ.get("NEMO_PROJECT_GIT") == "off" or not shutil.which("git")

    def _git(self, *args: str) -> int:
        if self._no_git():
            return 127
        return subprocess.run(["git", *args], cwd=self.root,
                              capture_output=True, text=True).returncode

    def git_init(self) -> None:
        if not (self.root / ".git").exists():
            self._git("init", "-q")

    def commit(self, stage: str, note: str = "") -> bool:
        """Snapshot after a stage. Failure here is never fatal."""
        if self._git("add", "-A") != 0:
            return False
        msg = f"{stage}: {note}" if note else stage
        return self._git("-c", "user.name=nemo",
                         "-c", "user.email=nemo@localhost",
                         "commit", "-q", "-m", msg) == 0

    def rollback(self, stage: str) -> bool:
        """Undo back to the most recent commit for a stage.

        Resolves the commit explicitly rather than relying on git's ``:/text``
        search syntax, which matches the OLDEST commit whose message contains
        the text and which an earlier revision here malformed with a trailing
        colon. Rolling a project back to the first time a stage ever ran,
        rather than the last, is a quietly destructive difference.
        """
        if self._no_git():
            return False
        found = subprocess.run(
            ["git", "log", "-1", "--format=%H", f"--grep=^{stage}:"],
            cwd=self.root, capture_output=True, text=True)
        rev = found.stdout.strip()
        if found.returncode != 0 or not rev:
            return False
        return self._git("reset", "--hard", rev) == 0

    # --- state --------------------------------------------------------

    def status(self) -> dict[str, bool]:
        """Which steps are done: their output exists AND, if the step has a
        saved result, that result passed.

        D128: this was file existence alone. On the real laptop a wiring
        step and a firmware step that had both failed were shown as done,
        because each had written its file before its gate failed, and
        `nemo run` would have resumed after them.
        """
        from .results import load_results
        failed = {s for s, rec in load_results(self.root).items()
                  if isinstance(rec, dict) and rec.get("ok") is False}
        return {s: there and s not in failed
                for s, there in self._outputs().items()}

    def _outputs(self) -> dict[str, bool]:
        return {s.key: s.output(self).exists() for s in _steps.STEPS}

    def next_stage(self) -> str | None:
        done = self.status()
        return next((s for s in STAGES if not done.get(s)), None)

    def stamp(self) -> str:
        return date.today().isoformat()

    def given_signoffs(self) -> dict:
        """What has actually been signed off for this project, keyed the
        same way the GUI's Sign-off tab writes them (safety_<rule>). {}
        if none yet or the file is unreadable.

        The single place that should read signoffs.json: stage_pack() used
        to rebuild its "still open" list straight from the original safety
        findings, never once checking whether the user had since signed
        them, so nothing they did in the Sign-off tab could ever be
        reflected in the build guide.
        """
        p = self.root / "signoffs.json"
        try:
            return json.loads(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}
