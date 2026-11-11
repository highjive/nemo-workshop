"""Running a design's steps: the one loop (2026-10-20).

For each step, in order: is a model needed and loaded; the Inspector's
check before it starts (review.before); the Researcher, when the Inspector
stopped it for something that can be looked up; the step itself, by its
owner; the result saved and recorded in the work log. A failed step stops
the run unless asked to keep going.

`nemo run` is a thin wrapper round run_steps, and the window runs
`nemo run --json` in a separate process (D17: so it cannot drift from the
command line, and a stuck step can be stopped). The loop lived inside
cli.cmd_run, tangled with argparse; here it can be called and tested on
its own. What a step is (order, owner, model, mode) is nemo/steps.py.
"""
from __future__ import annotations

from typing import Callable

from . import modes, review, staff, steps
from .pipeline import StageResult
from .results import save_result
from .router import ModelCallFailed

# run_steps' return codes, as `nemo run` exits with them.
OK, FAILED, NEEDS_MODEL = 0, 1, 3


def plan(project, start: str | None = None, only: str | None = None) -> list[str]:
    """The steps a run will take: from `start` (else the first not done) to
    the end, or `only` the one. ValueError for a step that does not exist."""
    first = start or only or project.next_stage() or "brief"
    if first not in steps.ORDER:
        raise ValueError(f"unknown step {first!r}; known: {', '.join(steps.ORDER)}")
    return [first] if only else steps.ORDER[steps.ORDER.index(first):]


def needs_model(stage: str, project) -> bool:
    """Will this step ask the model anything? A step that will not must not
    wait for one to load (owner, 2026-10-18: a design with no parts was told
    to load a model for a schematic it does not have). With No parts needed
    there is nothing to draw, wire or program; and the enclosure asks only
    where the brief has a constraint about where a part goes (D172)."""
    if stage not in steps.MODEL_STEPS:
        return False
    try:
        brief = project.load_brief()
    except Exception:                                        # noqa: BLE001
        return True
    return steps.asks_model(stage, brief)


def run_step(stage: str, project, pipe, done: list, say: Callable[[str], None]) -> StageResult:
    """One step, with the Inspector before it and the Researcher where the
    Inspector's stop is something that can be looked up. Records the
    handoffs in the work log; does not save the result."""
    # The Inspector checks the handoff before the step starts (redesign,
    # 2026-10-17): what would make it fail, or build the wrong thing,
    # stops it here, with the reason and its fixes.
    who = staff.owner(stage)
    stops, rnotes = review.before(stage, project, pipe.lib)
    review.record(project.root, stage, "reviewed",
                  stops=[r.name for r in stops], notes=len(rnotes))
    wants = review.researchable(stops)
    if wants:
        # The Storekeeper first: a thing on the shelves by name is not
        # looked up online (owner, 2026-10-21); it is said, as a maybe.
        from . import storeroom
        from .config import Config
        try:
            root = Config.load().path("paths.storeroom")
            shelf = {(k, t): storeroom.on_shelf_named(root, t) for k, t in wants}
        except Exception:                                       # noqa: BLE001
            shelf = {}
        for (k, t), items in shelf.items():
            if items:
                say(f"Storekeeper: '{t}' may be on the shelves: "
                    + "; ".join(f"{i.name} ({i.quantity}" + (f", {i.where}" if i.where else "")
                                + ")" for i in items)
                    + ". Not looked up online; link it to a library part to use it.")
        wants = [w for w in wants if not shelf.get(w)]
    if wants:
        from . import research
        say(f"Researcher: looking online for {len(wants)} thing(s) the brief needs.")
        kept = research.look_up(project.root, wants, project.load_brief().mcu)
        found = sum(len(kept.get(f"{k}:{t}", {}).get("finds", [])) for k, t in wants)
        why = next((kept.get(f"{k}:{t}", {}).get("why") for k, t in wants
                    if kept.get(f"{k}:{t}", {}).get("why")), "")
        review.record(project.root, stage, "researched", by="Researcher",
                      found=found, why=why)
        say(f"Researcher: {found} part(s) found." + (f" ({why})" if why else ""))
    if stops:
        return StageResult(stage, False, results=stops, notes=[
            f"The Inspector stopped this step before the {who.label} began:"]
            + rnotes, go_back_to="brief")
    for n in rnotes:
        say(f"[note] {n}")
    if stage == "parts":
        # The Writer hands the brief to the Designer as an assignment
        # (owner, 2026-10-21): what to make, with what, how to know it works,
        # and what is still unclear.
        from . import writer
        path, wnotes = writer.write_assignment(project, pipe.lib, getattr(pipe, "cfg", None))
        review.record(project.root, stage, "assignment", by="Writer", notes=len(wnotes))
        say(f"Writer: the assignment is {path.name}.")
        for n in wnotes:
            say(f"Writer: {n}")
    review.record(project.root, stage, "started", by=who.title)
    fn = getattr(pipe, f"stage_{stage}")
    from . import archivist
    archivist.begin()
    from . import timekeeper
    with timekeeper.Timer(who.department, f"step {stage}") as clock:
        try:
            result = fn(done) if stage == "pack" else fn()
        except ModelCallFailed as exc:
            # D125: a failed step, saved and shown like any other, saying why.
            result = StageResult(stage, False, notes=[str(exc)])
        clock.ok = bool(result.ok)
    result.notes = list(rnotes) + list(result.notes)
    # The Archivist keeps a passed step's answers for an identical request
    # later, and never a failed one's (nemo/archivist.py).
    if result.ok:
        kept = archivist.keep(stage)
        if kept:
            review.record(project.root, stage, "archived", by="Archivist", answers=kept)
    else:
        archivist.drop()
    review.record(project.root, stage, "passed" if result.ok else "failed", by=who.title)
    return result


def run_steps(project, pipe, router, order: list[str], *, keep_going: bool = False,
              say: Callable[[str], None] = print,
              event: Callable[..., None] = lambda **kw: None) -> int:
    """Run `order`; OK, FAILED (a step failed) or NEEDS_MODEL (a step needs
    the language model and none is loaded: it is named in the event)."""
    done: list[StageResult] = []
    for stage in order:
        if stage == "brief":
            continue                      # written by 'nemo new' or 'nemo draft'
        # Only steps that call the model need one loaded. An earlier revision
        # refused to run anything without a model, including the parts and
        # packing steps, which never use it.
        if needs_model(stage, project) and not router.local_up():
            want = modes.suggest(stage)
            event(stage=stage, state="needs_model", mode=want)
            say(f"The {stage} step needs the language model, and none is "
                f"loaded. Load one with: nemo mode {want}")
            return NEEDS_MODEL
        want = modes.suggest(stage)
        st = modes.current()
        if stage in steps.MODEL_STEPS and st.running and st.name != want:
            say(f"[note] the {stage} step suits {want} mode; {st.name} is loaded.")

        event(stage=stage, state="running")
        say(f"--- {stage} ---")
        result = run_step(stage, project, pipe, done, say)
        done.append(result)
        rec = save_result(project.root, result)
        say(result.render())
        say("")
        event(stage=stage, state="done", result=rec)
        if not result.ok and not keep_going:
            return FAILED
    return OK
