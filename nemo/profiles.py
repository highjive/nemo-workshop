"""An employee's profile (owner, 2026-11-04: "improve employees profiles").

Everything on a profile is something Nemo already knows, gathered in one
place; nothing is written for effect:

  who        title, department, Nemo's own introduction (introductions.py)
  job        the roster's job text (staff.py)
  steps      the steps it owns, from THE table (steps.py), and whether each
             asks the language model, in which mode, and that mode's model
             on THIS machine (cfg.mode: the laptop's or the desktop's)
  tools      what it needs and whether each is ready (toolkit.py): the same
             looks the Tools check makes; nothing is installed or changed
  status     not built yet / needs something / ready, and busy right now
             (busy.py, the signal that lights its ring)

The tools are looked at only when asked (tools=True): one of them (the
Researcher's) asks a web site whether it can be reached.
"""
from __future__ import annotations

from dataclasses import dataclass, field

NOT_BUILT, NEEDS, READY = "not built yet", "needs something", "ready"


@dataclass
class StepLine:
    name: str
    uses_model: bool
    mode: str | None
    model: str | None


@dataclass
class ToolLine:
    need: str
    ok: bool
    detail: str


@dataclass
class Profile:
    key: str
    title: str
    department: str
    introduction: str
    job: str
    working: bool
    steps: list[StepLine] = field(default_factory=list)
    tools: list[ToolLine] | None = None          # None: not looked at
    busy: bool = False

    @property
    def status(self) -> str:
        if not self.working:
            return NOT_BUILT
        if self.tools is not None and any(not t.ok for t in self.tools):
            return NEEDS
        return READY

    @property
    def missing(self) -> list[ToolLine]:
        return [t for t in (self.tools or []) if not t.ok]


def profile(key: str, cfg=None, tools: bool = False, app=None) -> Profile:
    """The profile of the employee `key` ("<department>.<role>")."""
    from . import introductions
    from .staff import DEPARTMENTS, STAFF
    from .steps import STEPS
    e = STAFF[key]
    lines = []
    for s in STEPS:
        if s.owner != key:
            continue
        model = None
        if s.uses_model and cfg is not None:
            try:
                model = cfg.mode(s.mode)["model"]
            except KeyError:
                model = None
        lines.append(StepLine(s.name, s.uses_model, s.mode if s.uses_model else None, model))
    p = Profile(key, e.title, DEPARTMENTS[e.department].name, introductions.line(e), e.job,
                e.working, lines)
    if tools and cfg is not None:
        from . import toolkit
        p.tools = []
        for need in toolkit.NEEDS.get(key, ()):
            try:
                ok, detail = need.check(cfg)
            except Exception as exc:                     # noqa: BLE001  a look that fails is said
                ok, detail = False, f"could not be checked: {exc}"
            p.tools.append(ToolLine(need.name, bool(ok), str(detail)))
    if app is not None:
        from . import busy
        try:
            p.busy = bool(busy.signals(app, e.department).get(key.split(".", 1)[1]))
        except Exception:                                # noqa: BLE001
            p.busy = False
    return p
