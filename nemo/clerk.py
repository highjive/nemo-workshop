"""The Workshop's Clerk: what the owner chose from lists is decided, and the
model is asked only for the rest (owner, 2026-10-21).

The Brief tab offers lists: the microcontroller, the parts from the
library, a power supply from Suggest power, and the supply's rating and the
inside size. Before the Clerk, "Draft it with Nemo" rebuilt the brief from
the model's reply, which put back a board and parts of its own choosing
(both model families draft parts lists badly: extra parts, two boards) and
wrote again what the owner had already said.

Now, before the draft:
  decided()   what the owner has chosen, from the brief as saved;
  note()      tells the model those are decided and to leave them out, so
              it writes fewer tokens (docs/design-rules.md 4f); it goes in the user's
              message, which varies, not the system prompt, which the
              server keeps read (4c);
  keep()      after the reply, puts the owner's choices back by code,
              whatever the model wrote.
"""
from __future__ import annotations

# The fields a list in the Brief tab fills.
FIELDS = ("mcu", "parts", "power", "supply_ma", "envelope_mm")


def decided(brief) -> dict:
    """The owner's choices from the lists, from the saved brief: only the
    fields that hold something."""
    if brief is None:
        return {}
    out = {}
    for k in FIELDS:
        v = getattr(brief, k, None)
        if v:                                   # "", 0.0, [] are not chosen
            out[k] = list(v) if isinstance(v, list) else v
    if getattr(brief, "no_parts", False):
        out.pop("mcu", None); out.pop("parts", None)
    if getattr(brief, "no_power", False):
        out.pop("power", None); out.pop("supply_ma", None)
    return out


def note(chosen: dict) -> str:
    """For the end of the user's message; empty when nothing is decided."""
    if not chosen:
        return ""
    lines = [f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}"
             for k, v in chosen.items()]
    return ("\n\nAlready decided by the owner; leave these fields out of your reply:\n"
            + "\n".join(lines))


def keep(data: dict, chosen: dict) -> list[str]:
    """Put the owner's choices into the model's reply. Returns the fields
    the model had changed, to say so."""
    changed = [k for k, v in chosen.items() if data.get(k) not in (None, "", [], v)]
    data.update({k: (list(v) if isinstance(v, list) else v) for k, v in chosen.items()})
    return changed
