"""The team is introduced (owner, 2026-10-23, the first step of Nemo as the
OS: "companion first, employees introduced before going to the different
departments"). The first time he goes into a department Nemo, his companion,
introduces each employee in turn, its portrait lit: who it is and what it
does. Afterwards "Meet the team" does it again on request.

The words are the roster's own (staff.STAFF job, written in the third
person), cut to the first sentence and without code references, so an
introduction never claims more than the roster says. Who has been
introduced is kept in gui.json ("introduced").
"""
from __future__ import annotations

import re

from .staff import DEPARTMENTS, Employee, team

KEY = "introduced"
# A parenthesis naming code: (nemo/clerk.py), (clinic.report), (PCSX ReARMed) stays.
_CODE = re.compile(r"\s*\((?:[^()]*nemo/[^()]*|[a-z_]+(?:\.[a-z_]+)+(?:\(\))?|owner, [^()]*)\)")


def _first_sentence(text: str) -> str:
    text = _CODE.sub("", text).strip()
    return re.split(r"(?<=[.!?])\s+(?=[A-Z])", text, maxsplit=1)[0].rstrip(".")


def line(e: Employee) -> str:
    """What Nemo says of the employee: "This is the Researcher. It searches ..."."""
    job = _first_sentence(e.job)
    # "Searches ...", a verb, reads "It searches"; "Photos: ...", "REA: ..." do not.
    verb = re.match(r"[A-Z][a-z]+s\b(?!:)", job) and not job.startswith(("Its ", "His "))
    lead = job if job[1:2].isupper() else job[:1].lower() + job[1:]
    said = f"This is the {e.title}. It {lead}." if verb else f"This is the {e.title}: {lead}."
    if not e.working:
        said += " Its job is not built yet."
    return said


def lines(key: str) -> list[tuple[str, str]]:
    """(role, what Nemo says) for the department's team, in roster order."""
    return [(e.key.split(".", 1)[1], line(e)) for e in team(key)]


def welcome(key: str) -> str:
    return f"Here is the {DEPARTMENTS[key].name} team: {len(team(key))} of them."


def seen(settings: dict, key: str) -> bool:
    return key in settings.get(KEY, [])


def mark(settings: dict, key: str) -> dict:
    return dict(settings, **{KEY: list(dict.fromkeys(settings.get(KEY, []) + [key]))})
