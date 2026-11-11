"""The steps of a design, in one table (2026-10-20).

Every fact about a step lives here: its order, who owns it, whether it asks
the language model and in which mode, what it builds on, when it has
nothing to do, the file that shows it ran, and its name in the window.
project.STAGES, review.ORDER, results.MODEL_STAGES, the staff's steps,
modes.suggest, cli.needs_model, Pipeline._not_needed and the window's step
names were each a copy of part of this; when the Concept step was added,
each had to be found and changed by hand (docs/design-rules.md, mistake 3: two parts
of the system deciding from different lists). They are now read from here.

A leaf module: it imports nothing from Nemo, so anything may import it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Step:
    key: str
    owner: str                      # a staff.STAFF key, "<department>.<role>"
    mode: str                       # the llama-server mode it suits
    uses_model: bool                # asks the language model, when it has work
    builds_on: tuple[str, ...]      # steps that must have passed first (the Inspector)
    output: Callable                # project -> the file that shows it ran
    name: str                       # in the window
    help: str


STEPS: tuple[Step, ...] = (
    Step("brief", "workshop.writer", "talk", True, (), lambda p: p.brief_path,
         "Describe it", "What the thing is, what powers it, how big it can be."),
    Step("parts", "workshop.designer", "talk", False, (), lambda p: p.bom_path,
         "Parts and power", "Checks the parts exist, fit, and that the supply can feed them."),
    Step("electrical", "workshop.designer", "design", True, ("parts",), lambda p: p.schematic,
         "Schematic", "Draws the schematic and runs KiCad's electrical checks."),
    Step("wiring", "workshop.designer", "design", True, ("electrical",), lambda p: p.harness,
         "Wiring harness", "Draws the harness and checks every wire lands on a real pin."),
    Step("concept", "art_studio.artist", "talk", False, ("parts",),
         lambda p: p.root / "concept" / "choice.json",
         "Concept", "Draws two ways the case could look; you choose one, and any changes."),
    Step("enclosure", "workshop.designer", "design", True, ("parts",), lambda p: p.housing_stl,
         "Enclosure", "Models a printable case and checks its walls."),
    Step("firmware", "computer_lab.coder", "build", True, ("electrical",),
         lambda p: p.firmware / "platformio.ini",
         "Firmware", "Writes the code and compiles it until it builds."),
    Step("pack", "workshop.writer", "talk", False, (), lambda p: p.build_md,
         "Build guide", "Gathers everything into one build guide with open questions."),
)

BY_KEY: dict[str, Step] = {s.key: s for s in STEPS}
ORDER: list[str] = [s.key for s in STEPS]
MODEL_STEPS: frozenset[str] = frozenset(s.key for s in STEPS if s.uses_model)

# With No parts needed there is nothing to draw, wire or program.
_NOTHING_WITHOUT_PARTS = {"electrical": "draw", "wiring": "wire", "firmware": "program"}


def get(key: str) -> Step:
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError(f"no step called {key!r}; the steps are {', '.join(ORDER)}") from None


def not_needed(key: str, brief) -> str | None:
    """Why this step has nothing to do for this brief, or None. Such a step
    passes, saying so; it is not failed (owner, 2026-10-18)."""
    if getattr(brief, "no_parts", False) and not brief.parts and key in _NOTHING_WITHOUT_PARTS:
        return f"No parts are needed, so there is nothing to {_NOTHING_WITHOUT_PARTS[key]}."
    # A printed object with no parts has no case: the Art Studio's Designer
    # builds the object itself from the concept chosen (the blunderbuss through
    # Nemo, 2026-11-05: this step stopped it as "a shape Nemo cannot make").
    if key == "enclosure":
        from .review import built_by_code
        if built_by_code(brief):
            return ("No parts are needed and it is a shaped object: there is no case to make. "
                    "The Art Studio's Designer builds the object from the concept you chose.")
    return None


def asks_model(key: str, brief) -> bool:
    """Will this step ask the model anything for this brief? One that will
    not must not wait for a model to load. The enclosure asks only where
    there are parts to place (D172)."""
    if not get(key).uses_model or not_needed(key, brief):
        return False
    if key == "enclosure" and not brief.parts:
        return False
    return True
