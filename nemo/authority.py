"""The single place the effective safety parameters are assembled.

This module exists because of a defect found in review: the admin policy and
the master's signed floor were each implemented and individually tested, but
nothing ever connected them to the pipeline they were meant to govern. The
pipeline constructed a default Policy() and used the compiled floor, so no
admin setting and no signed document had any effect on any design. Worse,
'nemo admin set' validated against the compiled default rather than the
installed signed floor, so a local administrator could loosen past a limit
the master had set.

Everything that needs the effective parameters now calls resolve(). There is
deliberately no other path, so the two consumers cannot drift apart again.

Order of assembly, which is also the order of authority:

    1. HARD_FLOOR                    nobody
    2. signed floor, if verified     master; replaces FLOOR, then clamped by 1
       otherwise FLOOR               the compiled default
    3. local policy, bound to 2      local admin; tighten only
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .safety import FLOOR, Policy, active_floor


def store_dir() -> Path:
    return Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo")) / "admin"


@dataclass
class Authority:
    """Everything a caller needs to know about who set what."""

    policy: Policy
    floor: dict
    source: str                        # "signed floor serial N" | "compiled default"
    serial: int = 0
    overridden: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    @property
    def effective(self) -> dict:
        return self.policy.effective()

    def describe(self) -> str:
        lines = [f"floor source : {self.source}"]
        if self.overridden:
            lines.append("hard floor overrode the signed document on:")
            lines += [f"  - {x}" for x in self.overridden]
        if self.rejected:
            lines.append("local policy entries rejected (they tried to loosen):")
            lines += [f"  - {x}" for x in self.rejected]
        return "\n".join(lines)


def resolve(store: Path | None = None) -> Authority:
    """Assemble the effective parameters from every tier."""
    store = Path(store) if store else store_dir()

    # Imported here so a build without the cryptography package still runs
    # with the compiled default rather than failing to import at all.
    signed_values, serial = None, 0
    try:
        from .master import load_installed_floor
        signed_values, serial = load_installed_floor(store)
    except ImportError:
        pass

    floor, overridden = active_floor(signed_values)
    source = (f"signed floor, serial {serial}" if signed_values
              else "compiled default")

    policy = Policy.load(store / "policy.yaml").against(floor)
    return Authority(policy=policy, floor=floor, source=source,
                     serial=serial, overridden=overridden,
                     rejected=policy.validate())


