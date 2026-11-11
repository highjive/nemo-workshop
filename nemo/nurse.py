"""The Nurse: applies a remedy the owner said yes to (Doctors phase 2,
owner, 2026-10-21: "the Nurse applies one remedy at a time only after my
yes, keeps a copy to undo it, starting with the safe remedies").

How a treatment goes:
  1. plan()  The remedy is worked out afresh from how things are NOW, and
             says in words what it will change and which files. A finding
             that no longer holds gets no plan.
  2. yes     treat() takes the plan's token, which only the plan shown can
             give: a yes to one plan cannot apply another, and nothing is
             applied without one. One finding, one remedy, one call.
  3. copy    Every file the plan names is copied (or noted as absent) under
             ~/.nemo/clinic/treatments/<id>/ before anything changes.
  4. apply   If the remedy fails part way, the copies are put back at once.
  5. undo    Puts every file back as it was, with the owner's yes, unless a
             file has changed since: then it stops and names it, rather than
             overwrite later work.

The Nurse may touch only the files on its list (ALLOWED): the model's
running record, the owner's settings file, the Storeroom's folder and the
backups folder. Never the keys, the admin or safety store, signing or
lockdown: a plan naming any other file is refused before a copy is made.

The remedies (phase 2, the safe ones):
  clear_record     a record of a loaded model whose process has ended
  set_aside_stock  a Storeroom catalogue that cannot be read: renamed aside
  backup           no backup: make one, in the backups folder
  raise_timeout    a model step ran past its limit: engine.timeout_s doubled
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path


class NurseError(RuntimeError):
    """The remedy was not applied, or not undone; the message says why."""


@dataclass
class Plan:
    remedy: str
    title: str
    finding: str                    # the finding's `what`
    steps: list[str]                # what will change, in words
    touches: list[str]              # every file that may change
    data: dict = field(default_factory=dict)
    stamp: str = ""                 # the time it was planned for, in names it makes

    @property
    def token(self) -> str:
        """Only this plan gives this token: the yes is to exactly what was shown.
        Planned again with the same stamp, an unchanged situation gives the
        same token; a changed one does not."""
        raw = json.dumps([self.remedy, self.steps, self.touches, self.data, self.stamp],
                         sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


# ------------------------------------------------------------ the rules
def allowed(cfg) -> tuple[list[Path], list[Path]]:
    """(files, folders) the Nurse may change, and nothing else."""
    from . import backup, modes
    from .config import CONFIG_PATH
    return [modes.STATE, CONFIG_PATH], [cfg.path("paths.storeroom"), backup.default_folder()]


def _may_touch(cfg, path: Path) -> bool:
    p = Path(path).expanduser().resolve()
    files, folders = allowed(cfg)
    if any(p == Path(f).expanduser().resolve() for f in files):
        return True
    for d in folders:
        try:
            p.relative_to(Path(d).expanduser().resolve())
            return True
        except ValueError:
            pass
    return False


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _home() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "clinic" / "treatments"


# ------------------------------------------------------------ the remedies
def _plan_clear_record(cfg, finding, stamp: str) -> Plan | None:
    from . import modes
    st = modes.current()
    if not st.name or st.running:
        return None
    return Plan("clear_record", "Clear the record of a model that has stopped", finding.what,
                [f"Remove Nemo's record that the {st.name} model is loaded "
                 f"(process {st.pid}, which has ended). No model is stopped or started."],
                [str(modes.STATE)], {"pid": st.pid})


def _apply_clear_record(cfg, plan: Plan) -> None:
    from . import modes
    st = modes.current()
    if st.running:
        raise NurseError("the model is running now; its record is right, so it is left")
    modes.STATE.unlink(missing_ok=True)


def _plan_set_aside(cfg, finding, stamp: str) -> Plan | None:
    from . import storeroom
    root = cfg.path("paths.storeroom")
    try:
        storeroom.load(root)
        return None                                   # it reads again: nothing to do
    except storeroom.StoreroomError:
        pass
    stock = storeroom.stock_path(root)
    aside = stock.with_name(f"{stock.name}.unreadable-{stamp.replace(':', '')}")
    return Plan("set_aside_stock", "Set the unreadable catalogue aside", finding.what,
                [f"Rename {stock.name} to {aside.name}, in the same folder, so the "
                 "Storeroom starts a new catalogue. Nothing in it is deleted; open it "
                 "to copy back what you need."],
                [str(stock), str(aside)])


def _apply_set_aside(cfg, plan: Plan) -> None:
    stock, aside = (Path(p) for p in plan.touches)
    os.replace(stock, aside)


def _plan_backup(cfg, finding, stamp: str) -> Plan | None:
    from . import backup
    if backup.listing():
        return None
    now = _dt.datetime.fromisoformat(stamp)
    zipped = backup.default_folder() / f"nemo-backup-{now:%Y-%m-%d_%H%M%S}.zip"
    return Plan("backup", "Make a backup", finding.what,
                [f"Write {zipped.name} into {zipped.parent}: your projects, stories, "
                 "Storeroom, added parts and datasheets, and settings. Nothing else changes."],
                [str(zipped)])


def _apply_backup(cfg, plan: Plan) -> None:
    from . import backup
    made = backup.make(cfg, backup.default_folder(),
                       now=_dt.datetime.fromisoformat(plan.stamp))
    if str(made.path) != plan.touches[0]:
        raise NurseError(f"the backup was written as {made.path}, not where planned")


_TIMEOUT = re.compile(r"^(\s+timeout_s:\s*)(\d+)(\s*(#.*)?)$")
TIMEOUT_CAP_S = 7200            # two hours: past it, a smaller mode is the remedy


def _timeout_line(text: str) -> int | None:
    """The index of the one engine.timeout_s line, or None if there is not
    exactly one inside `engine:`. Only that line is ever changed."""
    lines, section, found = text.splitlines(), None, []
    for i, line in enumerate(lines):
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            section = line.split(":")[0].strip()
        if section == "engine" and _TIMEOUT.match(line):
            found.append(i)
    return found[0] if len(found) == 1 else None


def _plan_raise_timeout(cfg, finding, stamp: str) -> Plan | None:
    from .config import CONFIG_PATH
    now = int(cfg.get("engine.timeout_s", 900))
    if now >= TIMEOUT_CAP_S:
        return None
    new = min(now * 2, TIMEOUT_CAP_S)
    if CONFIG_PATH.is_file():
        if _timeout_line(CONFIG_PATH.read_text(encoding="utf-8")) is None:
            return None                     # not one plain line: the owner changes it by hand
        how = f"Change the timeout_s line in {CONFIG_PATH.name} from {now} to {new}."
    else:
        how = f"Write {CONFIG_PATH} holding only engine.timeout_s: {new}."
    return Plan("raise_timeout", "Give the model longer", finding.what,
                [how, f"Model steps may then run for {new} s ({new // 60} minutes) before "
                      "they are stopped. Nothing else in the settings changes."],
                [str(CONFIG_PATH)], {"from": now, "to": new})


def _apply_raise_timeout(cfg, plan: Plan) -> None:
    from .config import CONFIG_PATH
    new = plan.data["to"]
    if not CONFIG_PATH.is_file():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(f"engine:\n  timeout_s: {new}\n", encoding="utf-8")
        return
    text = CONFIG_PATH.read_text(encoding="utf-8")
    i = _timeout_line(text)
    if i is None:
        raise NurseError("the settings file changed: there is no longer one timeout_s line")
    lines = text.splitlines(keepends=True)
    end = lines[i][len(lines[i].rstrip("\r\n")):]
    m = _TIMEOUT.match(lines[i].rstrip("\r\n"))
    lines[i] = f"{m.group(1)}{new}{m.group(3)}{end}"
    CONFIG_PATH.write_text("".join(lines), encoding="utf-8")


REMEDIES = {
    "clear_record": (_plan_clear_record, _apply_clear_record),
    "set_aside_stock": (_plan_set_aside, _apply_set_aside),
    "backup": (_plan_backup, _apply_backup),
    "raise_timeout": (_plan_raise_timeout, _apply_raise_timeout),
}


# ------------------------------------------------------------ the Nurse
def plan(cfg, finding, stamp: str | None = None) -> Plan | None:
    """The remedy for this finding as things are now, or None. `stamp` is
    the time names it makes are given; treat() passes the shown plan's."""
    if not getattr(finding, "remedy", "") or finding.remedy not in REMEDIES:
        return None
    stamp = stamp or _dt.datetime.now().isoformat(timespec="seconds")
    p = REMEDIES[finding.remedy][0](cfg, finding, stamp)
    if p is not None:
        p.stamp = stamp
    return p


def treat(cfg, finding, consent: str, stamp: str) -> dict:
    """Apply this finding's remedy, if `consent` is the token of the plan
    the owner was shown (planned at `stamp`). It is planned again first: if
    anything has changed since it was shown, the token differs and nothing
    is applied. Returns the treatment record."""
    p = plan(cfg, finding, stamp)
    if p is None:
        raise NurseError("there is nothing to treat: it no longer holds, or has no remedy here")
    if consent != p.token:
        raise NurseError("not applied: the yes was not to this plan (things may have "
                         "changed since it was shown; look again)")
    bad = [t for t in p.touches if not _may_touch(cfg, Path(t))]
    if bad:
        raise NurseError("not applied: the Nurse may not change " + ", ".join(bad))
    tid = f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{p.remedy}"
    folder = _home() / tid
    folder.mkdir(parents=True, exist_ok=False)
    files = []
    for n, t in enumerate(p.touches):
        src = Path(t)
        copy = None
        if src.is_file():
            copy = f"{n}.copy"
            shutil.copy2(src, folder / copy)
        files.append({"path": t, "copy": copy})
    try:
        REMEDIES[p.remedy][1](cfg, p)
    except Exception as exc:                                    # noqa: BLE001
        _put_back(files, folder)
        shutil.rmtree(folder, ignore_errors=True)
        raise NurseError(f"not applied, and everything put back as it was: {exc}") from None
    for f in files:
        f["after"] = _sha(Path(f["path"]))
    rec = {"id": tid, "at": int(time.time()), "remedy": p.remedy, "title": p.title,
           "finding": p.finding, "steps": p.steps, "files": files, "undone": False}
    (folder / "treatment.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    _note({"at": rec["at"], "treated": tid, "remedy": p.remedy, "finding": p.finding})
    return rec


def _put_back(files: list[dict], folder: Path) -> None:
    for f in files:
        dest = Path(f["path"])
        if f["copy"]:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / f["copy"], dest)
        else:
            dest.unlink(missing_ok=True)      # the treatment made it; it was not there before


def treatments() -> list[dict]:
    """Every treatment, newest first."""
    home = _home()
    out = []
    for f in sorted(home.glob("*/treatment.json"), reverse=True) if home.is_dir() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def undo(tid: str | None = None, *, agreed: bool = False) -> dict:
    """Put back the files a treatment changed (the newest not yet undone,
    if no id is given). Needs the owner's yes, and stops, naming them, if
    any file has changed since the treatment."""
    open_ones = [t for t in treatments() if not t["undone"]]
    rec = next((t for t in open_ones if t["id"] == tid), None) if tid else \
        (open_ones[0] if open_ones else None)
    if rec is None:
        raise NurseError(f"there is no treatment {tid!r} to undo" if tid
                         else "there is no treatment to undo")
    if not agreed:
        raise NurseError("not undone: it needs your yes")
    changed = [f["path"] for f in rec["files"] if _sha(Path(f["path"])) != f.get("after")]
    if changed:
        raise NurseError("not undone: changed since the treatment, and putting it back "
                         "would lose that: " + ", ".join(changed))
    folder = _home() / rec["id"]
    _put_back(rec["files"], folder)
    rec["undone"] = True
    rec["undone_at"] = int(time.time())
    (folder / "treatment.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    _note({"at": rec["undone_at"], "undone": rec["id"], "remedy": rec["remedy"]})
    return rec


def _note(line: dict) -> None:
    """Into the Records Clerk's case notes, beside the visits."""
    from .clinic import notes_path
    path = notes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def describe(p: Plan) -> str:
    return "\n".join([f"{p.title}:"] + [f"  - {s}" for s in p.steps]
                     + ["  A copy of every file it changes is kept, so it can be undone."])
