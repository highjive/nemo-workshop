"""Nemo command line.

  nemo doctor                    check the machine before blaming the software
  nemo mode <design|build|talk>  load the right model for the work
  nemo new <name> "<brief>"      start a project
  nemo run [--from <stage>]      run the pipeline
  nemo check                     rerun tier 0 on an existing project
  nemo parts [ref]               inspect the library
  nemo status                    what is built and what is not
"""

from __future__ import annotations

import argparse
import json
import getpass
import os
import sys
from datetime import datetime
from pathlib import Path

from . import checks, doctor, modes
from .admin import AdminStore
from .authority import resolve
from .lockdown import Lockdown, measure
from .maintenance import Maintenance, OperationDocument, clone_id, diagnose
from .master import MASTER_PUBLIC_KEY, _is_removable, _on_local_console
from .signing import SigningError, public_key_fingerprint

from .config import Config
from .parts import PartsLibrary
from .pipeline import Pipeline, StageResult
from .project import STAGES, Brief, Project
from . import review, workflow
from .router import ModelCallFailed, Router


def _library(cfg: Config) -> PartsLibrary:
    extra = cfg.get("paths.parts")
    return PartsLibrary.load(*( [Path(extra).expanduser()] if extra else [] ))


def _project(cfg: Config, name: str | None) -> Project:
    root = cfg.path("paths.projects")
    if name:
        return Project(root / name)
    cwd = Path.cwd()
    if (cwd / "brief.yaml").exists():
        return Project(cwd)
    raise SystemExit("no project here. cd into one, or pass --project NAME")


# --------------------------------------------------------------------

def cmd_doctor(args, cfg: Config) -> int:
    text, fails = doctor.report()
    print(text)
    print()
    if fails:
        print(f"{fails} blocking problem(s). Fix these before running the "
              "pipeline -- they will present as 'Nemo is slow' otherwise.")
    else:
        print("Nothing blocking.")
    return 1 if fails else 0


def cmd_mode(args, cfg: Config) -> int:
    if args.name in ("off", "stop"):
        print("stopped" if modes.stop() else "nothing was running")
        return 0
    if args.name is None:
        st = modes.current()
        print(f"{st.name} ({st.model}, pid {st.pid})" if st.running
              else "no mode loaded")
        return 0
    try:
        ok, msg = modes.start(cfg, args.name, force=args.force)
    except KeyError as exc:
        # D120: an unknown mode name ended in a traceback. Config.mode()
        # already writes the message, known names included.
        print(f"{exc.args[0]}\nWith no name, `nemo mode` shows what is loaded; "
              "`nemo mode off` stops it.")
        return 1
    print(msg)
    return 0 if ok else 1


def cmd_new(args, cfg: Config) -> int:
    root = cfg.path("paths.projects") / args.name
    if root.exists() and (root / "brief.yaml").exists():
        raise SystemExit(f"{root} already has a brief")
    project = Project(root)
    cfg_router = Router(cfg)
    lib = _library(cfg)

    if not cfg_router.local_up():
        print("Local model is not responding. Start one with:\n"
              f"  nemo mode {modes.suggest('brief')}\n"
              "Creating a blank brief for you to fill in by hand instead.")
        project.create(Brief(name=args.name, function=args.brief))
        print(f"wrote {project.brief_path}")
        return 0

    project.create(Brief(name=args.name, function=args.brief))
    pipe = Pipeline(project, cfg, cfg_router, lib, resolve().policy)
    try:
        result = pipe.stage_brief(args.brief)
    except ModelCallFailed as exc:
        result = StageResult("brief", False, notes=[str(exc)])
    print(result.render())
    return 0 if result.ok else 1


def _event(args, **payload) -> None:
    """One machine-readable progress line, for the desktop interface."""
    if getattr(args, "json", False):
        print("@@NEMO " + json.dumps(payload), flush=True)


# The step loop is nemo/workflow.py; this name is kept for what imports it.
needs_model = workflow.needs_model


def cmd_run(args, cfg: Config) -> int:
    project = _project(cfg, args.project)
    router = Router(cfg)
    auth = resolve()
    print(f"safety parameters: {auth.source}", flush=True)
    pipe = Pipeline(project, cfg, router, _library(cfg), auth.policy)
    try:
        order = workflow.plan(project, args.start, args.only)
    except ValueError as exc:
        raise SystemExit(str(exc))
    return workflow.run_steps(project, pipe, router, order, keep_going=args.keep_going,
                              say=lambda m: print(m, flush=True),
                              event=lambda **kw: _event(args, **kw))


def _send_finished(cfg: Config, department: str, folder) -> None:
    """A department's finished piece, onto the Storeroom's Finished shelf (nemo/finished.py)."""
    from . import finished
    try:
        p = finished.send(cfg, department, Path(folder))
    except OSError:
        p = None
    if p is not None:
        print(f"Sent to the Storeroom's Finished shelf: {p.title} ({p.parts} parts).", flush=True)


def _store_finished(cfg: Config, name: str) -> int:
    """The Storeroom's Finished shelf (nemo/finished.py): every department's
    finished work, or every part of one piece."""
    from . import finished
    pieces = finished.gather(cfg)
    if not name:
        for dept, items in finished.by_department(pieces).items():
            print(f"{finished.department_name(dept)} ({len(items)})")
            for x in items:
                print(f"  {x.title:<44} {x.finished}  {x.parts} parts")
        if not pieces:
            print("Nothing finished yet: a department's finished work comes here by itself.")
        return 0
    want = name.lower()
    hit = next((x for x in pieces if want in (x.title.lower(), x.path.name.lower())), None) \
        or next((x for x in pieces if want in x.title.lower()), None)
    if hit is None:
        print(f"Nothing finished is called {name!r}. See: nemo store finished")
        return 1
    print(f"{hit.title} ({finished.department_name(hit.department)}), finished {hit.finished}")
    print(f"In {hit.folder}")
    group = None
    for g, f in finished.parts(hit):
        if g != group:
            group = g
            print(f"  {g or '(the top folder)'}/")
        print(f"    {f.name}")
    return 0


def cmd_credits(args, cfg: Config) -> int:
    """Who made what Nemo is built from (nemo/credits.py), written into the Storeroom."""
    from . import credits
    where = credits.write(cfg)
    print(f"Nemo: who made it ({len(credits.everyone(cfg))} credits). Created by {credits.CREATOR}.")
    print(f"Credits: {where.as_uri()}")
    return 0


def cmd_story(args, cfg: Config) -> int:
    """Stories, written by the employees (redesign, 2026-10-17)."""
    from . import stories
    from .gui import prompt_logic as L
    root = cfg.path("paths.stories")
    if args.action == "list":
        for st in L.list_stories(root):
            done = "written" if "story.md" in st["files"] else "asked for"
            print(f"{st['name']:32} {done:10} {st['asked']}")
        return 0
    if args.action == "new":
        if not args.text:
            raise SystemExit('usage: nemo story new "<what the story is>"')
        print(L.file_story(root, " ".join(args.text)).name)
        return 0
    # write, cover
    if not args.text:
        raise SystemExit(f"usage: nemo story {args.action} <story>   (see: nemo story list)")
    folder = root / args.text[0]
    if not (folder / "request.md").is_file():
        raise SystemExit(f"No story called {args.text[0]!r} (see: nemo story list)")
    from . import books
    if args.action == "book":
        return 0 if books.bind_and_say(folder, say=lambda m: print(m, flush=True)) else 1
    if args.action == "cover":
        from . import artist
        _event(args, stage="cover", state="running")
        try:
            artist.draw_cover(folder, cfg, say=lambda m: print(m, flush=True))
            stories.record(folder, "Artist", "cover")
            rc = 0
            if (folder / "book.pdf").is_file():          # bound before the cover: again, with it
                books.bind_and_say(folder, say=lambda m: print(m, flush=True))
        except artist.ArtistError as exc:
            print(exc, flush=True)
            rc = 1
        _event(args, stage="cover", state="done")
        return rc
    router = Router(cfg)
    if not router.local_up():
        want = modes.suggest("story")
        _event(args, stage="story", state="needs_model", mode=want)
        print(f"Writing a story needs the language model. Load one with: nemo mode {want}",
              flush=True)
        return 3
    _event(args, stage="story", state="running")
    ok = stories.write_story(folder, router, say=lambda m: print(m, flush=True))
    if (folder / "story.md").is_file():
        books.bind_and_say(folder, say=lambda m: print(m, flush=True))   # WordCraft, if installed
        _send_finished(cfg, "library", folder)
    _event(args, stage="story", state="done")
    return 0 if ok else 1


def cmd_draft(args, cfg: Config) -> int:
    """Have the model turn a description into a brief for an existing project."""
    from .results import save_result
    project = _project(cfg, args.project)
    router = Router(cfg)
    if not router.local_up():
        print("Drafting a brief needs the language model. Load one with: "
              f"nemo mode {modes.suggest('brief')}", flush=True)
        return 3
    pipe = Pipeline(project, cfg, router, _library(cfg), resolve().policy)
    _event(args, stage="brief", state="running")
    try:
        result = pipe.stage_brief(args.description)
    except ModelCallFailed as exc:
        result = StageResult("brief", False, notes=[str(exc)])
    rec = save_result(project.root, result)
    print(result.render(), flush=True)
    _event(args, stage="brief", state="done", result=rec)
    return 0 if result.ok else 1


def cmd_power(args, cfg: Config) -> int:
    """Suggest power supplies for the project's parts."""
    from .fixes import power_plan
    project = _project(cfg, args.project)
    brief = project.load_brief()
    lib = _library(cfg)
    parts = [p for p in (lib.get(r) for r in brief.parts) if p]
    plan = power_plan(parts, lib, brief.power)
    print(f"Peak draw {plan.peak_ma:.0f} mA; with the safety margin the supply "
          f"must give at least {plan.need_ma} mA.\n")
    for o in plan.options:
        print(f"  {o.verdict:<13} {o.supply.label}")
        print(f"                {o.why}")
    return 0


def cmd_fix(args, cfg: Config) -> int:
    """List suggested fixes for a step, or apply one by number."""
    from .gui.controller import apply_fix_to_project, fixes_for
    from .results import load_results
    project = _project(cfg, args.project)
    stage = args.stage or next((s for s, r in load_results(project.root).items()
                                if not r.get("ok")), None)
    if not stage:
        print("No failed step to fix.")
        return 0
    fixes = fixes_for(project, stage, _library(cfg), cfg)
    if not fixes:
        print(f"No suggestions for the {stage} step.")
        return 0
    if args.number is None:
        for i, f in enumerate(fixes, 1):
            tag = "" if f.kind == "change" else "  (advice)"
            print(f"  {i}. {f.title}{tag}\n     {f.why}")
            for ch in f.changes:
                print(f"       - {ch}")
        print(f"\nApply one with: nemo fix --stage {stage} <number>")
        return 0
    if not 1 <= args.number <= len(fixes):
        raise SystemExit(f"choose 1 to {len(fixes)}")
    f = fixes[args.number - 1]
    if f.kind != "change":
        raise SystemExit("That suggestion is advice; there is nothing to apply.")
    apply_fix_to_project(project, f)
    print(f"Applied: {f.title}. Run it again with: nemo run --only {f.rerun or stage}")
    return 0


def cmd_footprint(args, cfg: Config) -> int:
    """Each part's footprint or why not; or a header read off the owner's module."""
    from . import footprints, pcb
    lib = _library(cfg)
    if args.action == "header":
        if len(args.items) < 2:
            print("Give the part and its header's pins as printed, left to right: "
                  "nemo footprint header bme280 VIN GND SCL SDA  (- for a pin Nemo does not use)")
            return 2
        part = lib.get(args.items[0])
        if part is None:
            print(f"No part called {args.items[0]}. See: nemo parts")
            return 1
        try:
            out = footprints.header(part, args.items[1:], cfg.path("paths.parts"))
        except ValueError as exc:
            print(f"Not written: {exc}")
            return 1
        print(f"written: {out}\n  {footprints.socket_for(len(args.items) - 1)}, pads in the order you read.")
        return 0
    try:
        root = pcb.tools().footprints
    except pcb.PcbError:
        root = None
    have = 0
    for ref, fp, why in footprints.status(lib, root):
        have += bool(fp and not why)
        print(f"  {'ok  ' if fp and not why else 'NEED'} {ref:28} {fp or '-':55} {why}")
    print(f"{have} of {len(list(lib))} parts can go on a board.")
    return 0


def cmd_pcb(args, cfg: Config) -> int:
    """The PCB Designer (nemo/pcb.py) on the open project: board, check, Gerbers."""
    from . import pcb, schematic
    project = _project(cfg, args.project)
    try:
        doc = json.loads(project.connections.read_text(encoding="utf-8"))
    except OSError:
        print("No connections yet: run the electrical step first.")
        return 2
    lib = _library(cfg)
    parts = [p for p in (lib.get(r) for r in project.load_brief().parts) if p]
    try:
        board = pcb.make(parts, schematic.nets(doc, parts), project.root / "pcb")
    except pcb.PcbError as exc:
        print(f"Not made: {exc}")
        return 2
    print(f"board: {board.pcb} ({board.size_mm[0]:.1f} x {board.size_mm[1]:.1f} mm, {board.tracks} tracks)")
    print(f"routed: {'all' if board.routed else f'{board.unrouted} connection(s) left unrouted'}")
    for e in board.drc_errors:
        print(f"  KiCad's check: {e}")
    if board.outside:
        print(f"  off the board: {', '.join(board.outside)}")
    print(f"Gerbers and drill: {board.pcb.parent / 'gerbers'} ({len(board.gerbers)} files)")
    return 0 if board.ok else 1


def cmd_second(args, cfg: Config) -> int:
    """The Second Opinion (nemo/second.py) on the open project's wiring."""
    from . import modes, second
    # A model's reason can hold a character the Windows console cannot show
    # (the 4B wrote one in Chinese, 2026-11-04): shown as ?, never a crash.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    project = _project(cfg, args.project)
    try:
        doc = json.loads(project.connections.read_text(encoding="utf-8"))
    except OSError:
        print("No wiring to look at yet: run the electrical step first.")
        return 2
    lib = _library(cfg)
    parts = [p for p in (lib.get(r) for r in project.load_brief().parts) if p]
    mode = args.mode
    # The mode already up is used as it is, and left up; a different one is
    # put back after (2026-11-08: it restarted a talk mode already running,
    # then stopped it, leaving no model loaded).
    before = modes.current()
    before = before.name if before.running else None
    if before != mode:
        ok, msg = modes.start(cfg, mode)
        print(msg, flush=True)
        if not ok:
            return 2
    model = cfg.mode(mode)["model"]
    try:
        opinions = second.review(doc, parts, cfg.get("engine.local", "http://127.0.0.1:8080/v1"))
    finally:
        if before is None:
            modes.stop()
        elif before != mode:
            ok, msg = modes.start(cfg, before)
            print(f"Put back as it was: {msg}", flush=True)
    second.save(project.root, opinions, model)
    for o in opinions:
        print(f"  {o.verdict:9} {o.part} {o.part_pin} -> {o.mcu_pin}: {o.reason}")
    wrong = [o for o in opinions if o.verdict == "wrong"]
    print(f"{len(opinions)} connection(s) looked at by {model}: {len(wrong)} doubted.")
    return 1 if wrong else 0


def cmd_eval(args, cfg: Config) -> int:
    """SHIP or DON'T SHIP a model for Nemo's jobs (nemo/shipcheck.py)."""
    from . import modes, shipcheck as S
    default = Path(__file__).parent / "data" / "evals" / "nemo-tasks.jsonl"
    if args.write_tasks:
        out = S.write_tasks(S.make_tasks(_library(cfg)), Path(args.write_tasks))
        print(f"wrote {out} (Soup's task format: prompt, expected, category, scoring)")
        return 0
    path = Path(args.tasks) if args.tasks else default
    tasks = S.read_tasks(path)
    print(f"{len(tasks)} tasks from {path}; {args.base} against {args.candidate}.", flush=True)
    runs = []
    try:
        for mode in (args.base, args.candidate):
            print(f"Loading {mode} ({cfg.mode(mode)['model']}) and asking...", flush=True)
            runs.append(S.run_mode(cfg, mode, tasks, say=lambda m: print(m, flush=True)))
    except RuntimeError as exc:
        print(f"Not run: {exc}")
        return 2
    finally:
        modes.stop()
    result, why = S.verdict(*runs)
    proof = S.evidence(path, *runs, result, why)
    print()
    for line in why:
        print("  " + line)
    print(f"\n{result}  ({runs[1].model} as Nemo's {args.candidate} model, against {runs[0].model})")
    print(f"evidence: {proof}")
    return 0 if result == "SHIP" else 1


def cmd_offline(args, cfg: Config) -> int:
    from .offline import prepare, readiness, summary
    lib = _library(cfg)
    if args.action == "prepare":
        print("Preparing to work offline. Keep the connection up until this "
              "finishes.", flush=True)
        for what, ok, why in prepare(cfg, lib, lambda m: print(m, flush=True),
                                     include_optional=args.all):
            print(f"  {'done' if ok else 'FAILED'}: {what} -- {why}", flush=True)
    items = readiness(cfg, lib)
    for i in items:
        print(f"  [{ {'ready': 'ready', 'partial': 'part', 'missing': 'NEED'}[i.status]:>5}] "
              f"{i.name}: {i.detail}")
    print("\n" + summary(items))
    return 0 if all(i.status != "missing" for i in items) else 1


def cmd_datasheet(args, cfg: Config) -> int:
    from .datasheets import Library
    with Library() as lib:
        return _datasheet(args, cfg, lib)


def _datasheet(args, cfg: Config, lib) -> int:
    if args.action == "draft":
        # The Datasheet Reader (nemo/reader.py): a draft part, every figure with its proof.
        from . import modes, reader
        if not args.items:
            print("Say which datasheet: nemo datasheet draft <file.pdf> [--part <ref>]")
            return 2
        lib.index()
        name = Path(args.items[0]).name
        pages = reader.pages_of(lib, name)
        if not pages:
            print(f"No text for {name} in the datasheet library (add it first, and it must "
                  "not be a scan).")
            return 2
        st = modes.current()
        if not (st.running and st.name == "design"):
            ok, msg = modes.start(cfg, "design")
            print(msg, flush=True)
            if not ok:
                return 2
        print(f"Reading {name}: {len(pages)} page(s)...", flush=True)
        d = reader.draft(name, pages, reader.ask(cfg.get("engine.local", "http://127.0.0.1:8080/v1"),
                                                 pages), args.part)
        out = reader.write(d, cfg.path("paths.parts"))
        print(f"kept {len(d.kept)} with their proof, dropped {len(d.dropped)}:")
        for f in d.kept:
            print(f"  ok    {f.what}: {f.value}  (p.{f.page})")
        for f in d.dropped:
            print(f"  NOT   {f.what}: {f.why}")
        print(f"draft: {out}\nCheck it against the datasheet, then move it up into "
              f"{cfg.path('paths.parts')} to use it.")
        return 0
    if args.action == "add":
        added = lib.add(args.items)
        print(f"added {len(added)}: {', '.join(added) or 'nothing (PDF files only)'}")
        parts = _library(cfg)
        for f in added:
            sug = lib.suggest_parts(f, parts)
            if sug:
                print(f"  {f} looks like it is for: {', '.join(sug)}. Confirm with: "
                      f"nemo datasheet link \"{f}\" {sug[0]}")
    elif args.action == "index":
        print(lib.index())
    elif args.action in ("link", "unlink"):
        # D155: the help offers --part, and "link --part <part> <file>" ended
        # in a traceback (IndexError) on the real laptop. Either form is
        # taken; anything else is told what to type.
        items = list(args.items)
        if len(items) == 1 and args.part:
            items.append(args.part)
        if len(items) != 2:
            print(f"Give the file and the part: nemo datasheet {args.action} "
                  "\"<file.pdf>\" <part>")
            return 2
        # Also D155: a file never added, or a part the library does not
        # have, was answered "linked".
        files = [sh.file for sh in lib.sheets()]
        if items[0] not in files:
            print(f"No datasheet called {items[0]} has been added. "
                  + ("Added so far: " + ", ".join(files) if files else "None has been yet."))
            return 1
        if _library(cfg).get(items[1]) is None:
            print(f"No part called {items[1]} in the parts library. See: nemo parts")
            return 1
        getattr(lib, args.action)(items[0], items[1])
        print("linked" if args.action == "link" else "unlinked")
    elif args.action == "search":
        hits = lib.search(" ".join(args.items), ref=args.part)
        for h in hits:
            print(f"  {h.file}, page {h.page}: {h.snippet}")
        if not hits:
            print("  nothing found" + (f" in datasheets linked to {args.part}" if args.part else ""))
    else:
        for sh in lib.sheets():
            parts = f" -> {', '.join(sh.parts)}" if sh.parts else " (not linked to a part)"
            note = f" [{sh.detail}]" if sh.detail else ""
            print(f"  {sh.file}: {sh.pages} pages{parts}{note}")
    return 0


def cmd_review(args, cfg: Config) -> int:
    from .reviews import pending, send_all
    items = pending()
    if args.action == "send":
        router = Router(cfg)
        if not router.online():
            print(f"Still offline; {len(items)} review(s) kept for later.")
            return 1
        for rid, ok, what in send_all(router):
            print(f"  {'sent' if ok else 'kept'}: {rid} {what}")
        return 0
    for it in items:
        ctx = it.get("context") or {}
        print(f"  {it['id']}: {ctx.get('stage', it['task'])} step of "
              f"{Path(ctx.get('project', '?')).name}")
    print(f"{len(items)} waiting." + (" Send with: nemo review send" if items else ""))
    return 0


def cmd_render(args, cfg: Config) -> int:
    """Pictures of the actual enclosure, drawn from its STL."""
    from .render import DEFAULT_VIEWS, RenderError, render_stl
    env = None
    if args.stl:
        stl = Path(args.stl)
        out = Path(args.out) if args.out else stl.parent / "renders"
    else:
        proj = _project(cfg, args.project)
        stl = proj.housing_stl
        out = Path(args.out) if args.out else proj.root / "renders"
        try:
            env = proj.load_brief().envelope_mm
        except FileNotFoundError as exc:          # no such project: say so, no traceback
            print(exc)
            return 1
    views = [v.strip() for v in args.views.split(",")] if args.views else DEFAULT_VIEWS
    try:
        res = render_stl(stl, out, views, args.size, envelope_mm=env)
    except RenderError as exc:
        print(exc)
        return 1
    print(res.report)
    for f in res.files:
        print(f)
    return 0


def cmd_concept(args, cfg: Config) -> int:
    """The Artist's two concepts of the enclosure, and the owner's choice."""
    from . import concept
    proj = _project(cfg, args.project)
    try:
        brief = proj.load_brief()
    except FileNotFoundError as exc:
        print(exc)
        return 1
    if args.action == "redraw":
        where = concept.set_aside(proj.root)
        review.record(proj.root, "concept", "set aside for a redraw", by="owner")
        print((f"The concepts and any choice are set aside in {where}." if where
               else "There were no concepts to set aside.")
              + " The Artist draws new ones on: nemo run --only concept")
        return 0
    lib = _library(cfg)
    parts = [p for p in (lib.get(r) for r in brief.parts) if p]
    sig = concept.current_signature(brief, parts)
    drawn = concept.load(proj.root, sig)
    if not drawn:
        print("No concepts for these parts and this size yet. Run: nemo run --only concept")
        return 1
    if args.action == "show":
        d = concept.folder(proj.root)
        for c in drawn:
            print(f"{c.key}: {c.title}. " + " ".join(c.said))
            for f in (concept.picture(proj.root, c), d / f"{c.key}-plan.svg"):
                if f.exists():
                    print(f"    {f}")
        pick = concept.chosen(proj.root, sig)
        print("Chosen: " + (concept.describe(pick) if pick else "not yet (nemo concept choose A)"))
        return 0
    if not args.key:
        raise SystemExit("usage: nemo concept choose A|B [--corners square|rounded] "
                         "[--notch left|front] [--changes \"...\"]")
    try:
        pick = concept.choose(proj.root, args.key.upper(), sig, args.corners, args.notch,
                              args.changes or "")
    except ValueError as exc:
        print(exc)
        return 1
    review.record(proj.root, "concept", "chosen", by="owner", concept=pick.concept,
                  changes=bool(pick.notes))
    print("Chosen: " + concept.describe(pick))
    # The concept step is run again at once, as the window does: told only to
    # run it, its saved "waiting for your choice" stayed after the enclosure
    # and firmware were built, and the Doctors reported it (2026-11-08).
    argv = (["--config", args.config] if getattr(args, "config", None) else []) + \
           (["--project", args.project] if args.project else []) + ["run", "--only", "concept"]
    return main(argv)


def cmd_gui(args, cfg: Config) -> int:
    try:
        from .gui.app import main as gui_main
    except ImportError as exc:
        raise SystemExit(
            f"The desktop interface needs Tk, which is missing ({exc}).\n"
            "  Debian/Ubuntu: sudo apt install python3-tk\n"
            "  Windows: reinstall Python with the 'tcl/tk' option ticked.")
    return gui_main(prompt=getattr(args, "prompt", False))


def cmd_check(args, cfg: Config) -> int:
    project = _project(cfg, args.project)
    brief = project.load_brief()
    lib = _library(cfg)
    parts = [p for p in (lib.get(r) for r in brief.parts) if p]
    hw = cfg.get("hardware", {})

    results = [
        checks.current_sum(parts, brief.supply_ma),
        checks.supply_rails(parts, brief.rails),
        checks.fits_envelope(parts, brief.envelope_mm),
        checks.erc(project.schematic),
        checks.drc(project.board),
        checks.wireviz(project.harness),
        checks.solid(project.housing_stl),
        checks.thickness(project.housing_stl,
                         float(hw.get("min_wall_mm", 1.2))),
        checks.compile_firmware(project.firmware),
    ]
    from .safety import blocking, review as safety_review
    auth = resolve()
    found = safety_review(brief, parts, auth.policy)
    blocks = blocking(found)
    results.append(checks.Result(
        "safety", checks.FAIL if blocks else checks.PASS,
        f"{auth.source}; {len(blocks)} blocking", [f.render() for f in found]))
    text, fails, _ = checks.summarise(results)
    print(text)
    return 1 if fails else 0


def cmd_part(args, cfg: Config) -> int:
    """Add or remove a part in your own parts file (never the bundled one)."""
    from .parts import (PartsLibrary, delete_user_part, save_part,
                        user_parts_path, validate_part)
    root = cfg.path("paths.parts")
    if args.action == "remove":
        if delete_user_part(root, args.ref):
            print(f"Removed {args.ref!r} from {user_parts_path(root)}.")
            return 0
        print(f"{args.ref!r} is not in your own parts file. Only parts you "
              "added yourself can be removed this way -- the bundled "
              "library is never changed.")
        return 1

    def flist(s):
        return [float(x) for x in s.split(",")] if s else []

    data = {
        "ref": args.ref, "name": args.name, "category": args.category,
        "supply_v": flist(args.supply_v), "logic_v": args.logic_v,
        "current_ma": args.current_ma, "peak_ma": args.peak_ma,
        "size_mm": flist(args.size_mm), "mount": args.mount or "",
        "interfaces": [x.strip() for x in (args.interfaces or "").split(",")
                       if x.strip()],
        "datasheet": args.datasheet, "notes": args.notes or "",
    }
    existing = set(_library(cfg).parts.keys())
    problems = validate_part(data, existing_refs=existing,
                             allow_overwrite=args.overwrite)
    if problems:
        for p in problems:
            print(f"  - {p}")
        if any("already in the library" in p for p in problems):
            print("\nAdd --overwrite to replace it.")
        return 1
    path = save_part(root, data)
    print(f"Saved {args.ref!r} to {path}.")
    total = len(PartsLibrary.load(root))
    print(f"Library now has {total} parts.")
    return 0


def cmd_parts(args, cfg: Config) -> int:
    lib = _library(cfg)
    if args.ref:
        part = lib.get(args.ref)
        if not part:
            raise SystemExit(f"{args.ref!r} is not in the library")
        print(f"{part.ref}: {part.name}")
        print(f"  category   {part.category}")
        print(f"  supply     {part.supply_v} V, logic {part.logic_v} V")
        print(f"  current    {part.current_ma} mA typ, {part.peak_ma} mA peak")
        print(f"  size       {part.size_mm} mm, mount {part.mount}")
        print(f"  interfaces {', '.join(part.interfaces) or '-'}")
        if part.pins:
            print("  pins       " + ", ".join(p.name for p in part.pins))
        if part.notes:
            print("\n  " + part.notes.strip().replace("\n", "\n  "))
        return 0
    for p in sorted(lib, key=lambda x: (x.category, x.ref)):
        print(f"{p.ref:<28} {p.category:<10} {p.name}")
    print(f"\n{len(lib)} parts")
    return 0


def _store_drives(args, root) -> int:
    """Space, drives, moving a drive's files onto the shelves, the vault
    (nemo/drives.py, nemo/vault.py; owner, 2026-10-23)."""
    from . import drives
    if args.action == "space":
        use, free, total = drives.space(root)
        for k, v in use.items():
            print(f"{k:<10} {drives.human(v)}")
        print(f"free: {drives.human(free)} of {drives.human(total)}")
        return 0
    if args.action == "drives":
        found = drives.drives()
        for d in found:
            print(f"{d.name}: {drives.human(d.free)} free of {drives.human(d.total)}")
            groups, cut = drives.survey(d.path)
            for g in groups:
                print(f"    {g.ext:<8} {len(g.files):>6} file(s) {drives.human(g.bytes):>10}  "
                      + (f"-> {g.shelf}" if g.shelf else "no shelf: stays"))
            if cut:
                print("    (stopped looking at 20000 files)")
        if not found:
            print("No external drive is plugged in.")
        return 0
    if args.action == "move":
        if not args.name or not args.ext:
            print("Say which drive and which kinds: nemo store move F: --ext .jpg --ext .mp4")
            return 2
        groups, _ = drives.survey(Path(args.name))
        chosen = [g for g in groups if g.ext in {e.lower() for e in args.ext} and g.shelf]
        n = sum(len(g.files) for g in chosen)
        if not args.yes:
            print(f"{n} file(s), {drives.human(sum(g.bytes for g in chosen))}, would move onto "
                  "the shelves (copied, checked by hash, then removed from the drive). Add --yes.")
            return 0
        done = drives.move(chosen, root)
        print(f"Moved {len(done.moved)} file(s).")
        for f, why in done.kept:
            print(f"Kept on the drive: {f} ({why})")
        return 0 if not done.kept else 1
    from getpass import getpass
    from . import vault
    try:
        v = vault.unlock(root, getpass("The vault's passphrase: "))
        try:
            if args.name:
                item = v.add_file(Path(args.name))
                print(f"Sealed in: {item.name} ({item.kind}). The original is still where it was.")
            for it in v.items():
                print(f"{it.added:<17} {it.kind:<10} {it.name}")
        finally:
            v.lock()
    except vault.VaultError as exc:
        print(f"Vault: {exc}.")
        return 1
    return 0


def _which(what: str, usage: str, listing: str) -> int:
    """A command that needs a name was given none: say so, not "None"
    (2026-11-06)."""
    print(f"Which {what}? {usage}; {listing} shows them.")
    return 1


def cmd_store(args, cfg: Config) -> int:
    """The Storeroom: the parts you have to hand (nemo/storeroom.py)."""
    from . import storeroom
    root = cfg.path("paths.storeroom")
    if args.action in ("add", "take", "remove", "link") and not args.name:
        return _which("part", f"nemo store {args.action} \"<part>\"", "'nemo store list'")
    if args.action in ("space", "drives", "move", "vault"):
        return _store_drives(args, root)
    if args.action == "finished":
        return _store_finished(cfg, args.name)
    try:
        if args.action == "add":
            i = storeroom.add(root, args.name, args.qty, part=args.part or "",
                              where=args.where or "", notes=args.notes or "",
                              library=_library(cfg))
            print(f"{i.name}: {i.quantity} on hand"
                  + (f", in {i.where}" if i.where else "")
                  + (f" (library part {i.part})" if i.part else " (not linked to a library part)"))
            return 0
        if args.action == "suggest":
            lib = _library(cfg)
            items = ([storeroom.find(storeroom.load(root), args.name)] if args.name
                     else storeroom.unlinked(root))
            if args.name and items[0] is None:
                raise storeroom.StoreroomError(f"there is no {args.name!r} in the Storeroom")
            try:
                from .datasheets import Library as Sheets
                sheets = Sheets()
            except Exception:                                   # noqa: BLE001
                sheets = None
            for i in items:
                found = storeroom.suggest(i.name, lib, sheets=sheets)
                print(f"{i.name}" + (" (linked: " + i.part + ")" if i.part else ""))
                for s in found:
                    print(f"    {s.ref:<26} {s.name}  [{s.why}]")
                if not found:
                    print("    nothing in the library is like it")
            if not items:
                print("Every item is linked to a library part.")
            else:
                print('\nLink one with: nemo store link "<item>" --part <ref>')
            return 0
        if args.action == "link":
            if not args.part:
                raise storeroom.StoreroomError("say which library part: --part <ref>")
            i = storeroom.link(root, args.name, args.part, _library(cfg))
            print(f"{i.name} is now linked to {i.part}.")
            return 0
        if args.action == "take":
            i = storeroom.take(root, args.name, args.qty)
            print(f"{i.name}: {i.quantity} left")
            return 0
        if args.action == "remove":
            if storeroom.remove(root, args.name):
                print(f"Removed {args.name!r} from the Storeroom.")
                return 0
            print(f"There is no {args.name!r} in the Storeroom.")
            return 1
        items = storeroom.load(root)
    except storeroom.StoreroomError as exc:
        print(f"Storeroom: {exc}.")
        return 1
    for i in items:
        print(f"{i.quantity:>5}  {i.name:<30} {i.part or '-':<22} {i.where}")
    print(f"\n{len(items)} item(s) in {storeroom.stock_path(root)}")
    return 0


def cmd_backup(args, cfg: Config) -> int:
    """Back up the owner's work by hand, list backups, or check one."""
    from . import backup
    if args.action == "check":
        if not args.file:
            raise SystemExit("name the backup to check: nemo backup check <file.zip>")
        faults = backup.verify(Path(args.file))
        for f in faults:
            print(f"  - {f}")
        print("The backup is whole: every file is as it was saved." if not faults
              else f"The backup is NOT whole: {len(faults)} fault(s).")
        return 1 if faults else 0
    if args.action == "list":
        found = backup.listing(args.to)
        for p in found:
            print(f"{p.stat().st_size / 1e6:>8.1f} MB  {p}")
        print(f"\n{len(found)} backup(s) in {Path(args.to or backup.default_folder()).expanduser()}")
        return 0
    try:
        made = backup.make(cfg, args.to)
    except backup.BackupError as exc:
        print(f"Backup: {exc}.")
        return 1
    print(f"Backed up {made.files} file(s), {made.bytes / 1e6:.1f} MB, to {made.path}")
    if made.left_out:
        print("Not there, so not in it: " + ", ".join(made.left_out))
    print("Not in any backup: the program and models (reinstall them), the Researcher's "
          "key, the admin and safety store, and the Storeroom's videos and games.")
    return 0


def _owner_says_yes(args, question: str) -> bool:
    """The owner's yes: --yes on the command, or typed at the prompt. With
    neither (no terminal to ask at), the answer is no."""
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        print("No terminal to ask at: add --yes to say yes.")
        return False
    return input(f"{question} Type yes to go ahead: ").strip().lower() == "yes"


def cmd_clinic(args, cfg: Config) -> int:
    """The Doctors: diagnose and advise, show the case notes, or have the
    Nurse treat one finding (or undo a treatment) on the owner's yes."""
    from . import clinic, nurse
    if args.action == "updates":
        # The one visit that goes on the network: each department's tools against
        # their makers' latest releases (nemo/toolupdates.py). Looks only.
        from . import toolupdates
        print("Looking for newer versions of the departments' tools...")
        looks = toolupdates.look()
        for x in looks:
            print("  " + x.line())
        toolupdates.save(looks)
        newer = [x for x in looks if x.newer]
        print(f"\n{len(newer)} newer, kept in {toolupdates.path()}; nothing was downloaded."
              + (" The Doctors list them on every visit until the next look." if newer else ""))
        return 0
    if args.action == "notes":
        visits = clinic.past(args.last)
        for v in visits:
            when = datetime.fromtimestamp(v.get("at", 0)).strftime("%d %b %Y %H:%M")
            fs = v.get("findings", [])
            print(f"{when}  {len(fs)} finding(s)"
                  + (": " + "; ".join(f["what"] for f in fs[:3]) if fs else ""))
        print(f"\n{len(visits)} visit(s) in {clinic.notes_path()}")
        return 0
    if args.action == "report":
        path = clinic.report(cfg)
        print(f"The Doctors' Writer wrote {path}. Read it before you send it.")
        return 0
    if args.action == "treatments":
        done = nurse.treatments()[:args.last]
        for t in done:
            when = datetime.fromtimestamp(t["at"]).strftime("%d %b %Y %H:%M")
            print(f"{when}  {t['id']}  {t['title']}" + ("  (undone)" if t["undone"] else ""))
        print(f"\n{len(done)} treatment(s)")
        return 0
    if args.action == "undo":
        open_ones = [t for t in nurse.treatments() if not t["undone"]]
        rec = next((t for t in open_ones if t["id"] == args.which), None) if args.which             else (open_ones[0] if open_ones else None)
        if rec is None:
            print("There is no such treatment to undo." if args.which
                  else "There is no treatment to undo.")
            return 1
        print(f"Undo '{rec['title']}' ({rec['id']}): every file it changed is put back.")
        if not _owner_says_yes(args, "Undo it?"):
            print("Not undone.")
            return 1
        try:
            nurse.undo(rec["id"], agreed=True)
        except nurse.NurseError as exc:
            print(f"Nurse: {exc}.")
            return 1
        print("Undone: the files are as they were before it.")
        return 0
    case = clinic.examine(cfg)
    clinic.record(case)
    if args.action == "treat":
        try:
            f = case.findings[int(args.which) - 1]
        except (TypeError, ValueError, IndexError):
            print(clinic.describe(case))
            print(f"\nChoose a finding by its number, 1 to {len(case.findings)}.")
            return 1
        p = nurse.plan(cfg, f)
        if p is None:
            print(f"There is no remedy the Nurse can apply for: {f.what}\nAdvice: {f.advice}")
            return 1
        print(nurse.describe(p))
        if not _owner_says_yes(args, "Do it?"):
            print("Not applied. Nothing has changed.")
            return 1
        try:
            rec = nurse.treat(cfg, f, p.token, p.stamp)
        except nurse.NurseError as exc:
            print(f"Nurse: {exc}.")
            return 1
        print(f"Done ({rec['id']}). To undo it: nemo clinic undo {rec['id']}")
        return 0
    print(clinic.describe(case))
    return 0 if not any(f.severity == clinic.NEEDS for f in case.findings) else 1


def cmd_times(args, cfg: Config) -> int:
    """The Timekeeper: the model's own timings, by mode."""
    from . import timekeeper
    found = timekeeper.times()
    if args.department:
        found = [t for t in found if t.mode in timekeeper.modes_of(args.department)]
    if found or not args.department or timekeeper.modes_of(args.department):
        print(timekeeper.describe(found))
    if getattr(args, "measure", False):
        print("Timekeeper: the same jobs, each run "
              f"{timekeeper.MIN_RUNS} times (nothing is kept but the times).")
        for name, got in timekeeper.measure(cfg).items():
            print(f"  {name}: " + (got if isinstance(got, str) else
                                   ", ".join(f"{s:.1f} s" for s in got)))
    if getattr(args, "measure", False) or getattr(args, "builds", False):
        print("\nBetween builds:\n" + timekeeper.describe_changes(
            timekeeper.changes(everything=getattr(args, "builds", False))))
        return 0
    jobs = timekeeper.job_times(args.department)
    if jobs or args.department in ("art_studio", "printshop"):
        print("\nJobs:\n" + timekeeper.describe_jobs(jobs))
    return 0


def cmd_lookup(args, cfg: Config) -> int:
    """The Library's Researcher: look words up on Wikipedia."""
    from . import facts
    words = " ".join(args.words)
    try:
        found = facts.look_up(words)
    except facts.LookupError_ as exc:
        print(f"Researcher: {exc}.")
        return 1
    for f in found:
        print(f"{f.title}\n  {f.summary}\n  {f.url}\n")
    if not found:
        print("Researcher: Wikipedia has nothing for that.")
    if args.story:
        folder = cfg.path("paths.stories") / args.story
        if not folder.is_dir():
            print(f"There is no story {args.story!r}.")
            return 1
        print(f"Kept in {facts.keep(folder, words, found)}.")
    return 0


def cmd_archive(args, cfg: Config) -> int:
    """The Archivist: how many answers are kept, or forget them all."""
    from . import archivist
    if args.action == "clear":
        print(f"The Archivist forgot {archivist.clear()} answer(s).")
        return 0
    print(f"The Archivist keeps {archivist.count()} answer(s) from steps that passed"
          + ("" if archivist.on(cfg) else " (and is turned off: engine.archive)") + ".")
    return 0


def cmd_queue(args, cfg: Config) -> int:
    """The Foreman: queue long jobs and run them, loading each model as few times as it can."""
    from . import foreman, steps
    if args.action == "add":
        if not args.name:
            raise SystemExit("name the project: nemo queue add <project> [steps]")
        wanted = args.steps or [s for s in steps.ORDER if s != "brief"]
        bad = [s for s in wanted if s not in steps.ORDER]
        if bad:
            raise SystemExit(f"no step called {', '.join(bad)}; they are {', '.join(steps.ORDER)}")
        foreman.add([foreman.step_job(args.name, s) for s in wanted])
    elif args.action == "story":
        foreman.add([foreman.Job("story", args.name, "write", "talk",
                                 ["story", "write", args.name])])
    elif args.action == "cover":
        foreman.add([foreman.Job("cover", args.name, "cover", None,
                                 ["story", "cover", args.name])])
    elif args.action == "model":
        if not args.name:
            raise SystemExit("name the list of shapes: nemo queue model <spec.json>")
        from . import modelkit
        try:
            doc = json.loads(Path(args.name).read_text(encoding="utf-8"))
            foreman.add([foreman.model_job(doc)])
        except (OSError, ValueError) as exc:
            raise SystemExit(f"Foreman: not queued: {exc}.")
    elif args.action == "print":
        if not args.name:
            raise SystemExit("name the model: nemo queue print <model>")
        foreman.add([foreman.slice_job(args.name)])
    elif args.action == "clear":
        foreman.save([])
        print("The queue is empty.")
        return 0
    elif args.action == "run":
        done = foreman.run(cfg)
        return 0 if done and all(ok for _, ok in done) else 1
    jobs = foreman.order(foreman.load())
    if args.department:
        jobs = [j for j in jobs if foreman.department(j) == args.department]
    for n, j in enumerate(jobs, 1):
        print(f"{n:>3}. {j.label:<36} {j.mode or 'no model'}")
    print(f"\n{len(jobs)} job(s); in this order the model is loaded "
          f"{foreman.loads(jobs)} time(s), against {foreman.loads(foreman.load())} as queued.")
    return 0


def cmd_model(args, cfg: Config) -> int:
    """The Art Studio: 3D printable models from a kit of shapes (nemo/modelkit.py)."""
    from . import modelkit
    if args.action == "shapes":
        for k, keys in modelkit.SHAPES.items():
            print(f"{k:<12} {', '.join(keys)}, at [x, y, z], rotate [rx, ry, rz], op add|cut")
        return 0
    if args.action == "kinds":
        from . import artstudio
        for k in artstudio.KINDS.values():
            choices = artstudio.last(k.key)
            print(f"{k.key:<8} {k.title}: {k.about}\n         "
                  + ", ".join(f"{f.key}={choices[f.key]!r}" if isinstance(choices[f.key], str)
                              else f"{f.key}={choices[f.key]:g}" for f in k.fields))
        return 0
    if args.action == "card":
        from . import artstudio
        if not args.spec:
            raise SystemExit("name the model: nemo model card <name>")
        try:
            out = modelkit.folder(cfg, args.spec)
            if args.title is not None or args.line is not None:
                artstudio.write_about(out, args.title, args.line)
            print(artstudio.card(out))
        except (OSError, ValueError) as exc:
            print(f"Writer: {exc}.")
            return 1
        return 0
    if args.action == "make":
        from . import artstudio
        if not args.spec or not args.choices:
            raise SystemExit("nemo model make <kind> <name> [key=value ...]; see nemo model kinds")
        name, pairs = args.choices[0], args.choices[1:]
        bad = [p for p in pairs if "=" not in p]
        if bad:
            raise SystemExit(f"choices are key=value, not {', '.join(bad)}")
        try:
            values = dict(artstudio.last(args.spec), **dict(p.split("=", 1) for p in pairs))
            doc = artstudio.request(name, args.spec, values,
                                    float(cfg.get("hardware.min_wall_mm", 1.2)))
            out, results = modelkit.build(cfg, doc)
        except (OSError, ValueError, KeyError) as exc:
            print(f"Clerk: {exc}.")
            return 1
        for r in results:
            print(f"[{r.status:>4}] {r.name}: {r.detail}")
        print(f"\nIn {out}")
        _send_finished(cfg, "art_studio", out)
        return 0 if all(r.status != "FAIL" for r in results) else 1
    if args.action == "split":
        from . import joints
        if not args.spec:
            raise SystemExit("name the model: nemo model split <name>")
        try:
            out, results, plan = joints.split(cfg, args.spec)
        except (OSError, ValueError) as exc:          # joints.SplitError is a ValueError
            print(f"Designer: {exc}.")
            return 1
        for r in results:
            print(f"[{r.status:>4}] {r.name}: {r.detail}")
            for item in r.items:
                print(f"         {item}")
        print(f"\nIn {out / 'pieces'} (ASSEMBLY.txt says how they go together)")
        return 0 if all(r.status != "FAIL" for r in results) else 1
    if args.action == "list":
        found = modelkit.models(cfg)
        for m in found:
            print(f"{'passed' if m['passed'] else 'FAILED'}  {m['name']:<30} {m['folder']}")
        print(f"\n{len(found)} model(s) in {cfg.path('paths.models')}")
        return 0
    if not args.spec:
        raise SystemExit("name the list of shapes: nemo model build <spec.json>")
    try:
        doc = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        out, results = modelkit.build(cfg, doc)
    except (OSError, ValueError) as exc:
        print(f"Designer: {exc}.")
        return 1
    for r in results:
        print(f"[{r.status:>4}] {r.name}: {r.detail}")
    print(f"\nIn {out}")
    return 0 if all(r.status != "FAIL" for r in results) else 1


def cmd_guide(args, cfg: Config) -> int:
    """The Computer Lab's Writer: the project's firmware guide."""
    from . import labwriter
    project = _project(cfg, args.project)
    try:
        print(labwriter.guide(project, _library(cfg)))
    except (OSError, labwriter.GuideError) as exc:
        print(f"Writer: {exc}.")
        return 1
    print(f"(Written to {project.firmware / 'GUIDE.md'})")
    return 0


def cmd_test(args, cfg: Config) -> int:
    """The Tester: compile the project's firmware now, and read the build."""
    from . import tester
    project = _project(cfg, args.project)
    results = tester.test(project)
    for r in results:
        print(f"[{r.status:>4}] {r.name}: {r.detail}")
        for i in r.items[:8]:
            print(f"         {i}")
    return 0 if all(r.status != "FAIL" for r in results) else 1


def cmd_ahead(args, cfg: Config) -> int:
    """The Technician: which model the next step needs, and whether it fits."""
    from . import technician
    p = technician.plan(cfg, _project(cfg, args.project))
    print(f"Technician: {p.why}.")
    if p.mode and args.load:
        ok, msg = modes.start(cfg, p.mode)
        print(msg)
        return 0 if ok else 1
    return 0


def cmd_staff(args, cfg: Config) -> int:
    """Each employee's tools on this machine (nemo/toolkit.py)."""
    from . import toolkit
    from .staff import DEPARTMENTS, STAFF
    if args.department and args.department not in DEPARTMENTS:
        print(f"No department {args.department!r}; they are {', '.join(DEPARTMENTS)}.")
        return 1
    rows = toolkit.check(cfg, args.department)
    for r in rows:
        print(f"{'ready  ' if r.ok else 'MISSING'}  {STAFF[r.employee].label:<34} "
              f"{r.need:<22} {r.detail}")
    missing = sum(not r.ok for r in rows)
    print(f"\n{len(rows) - missing} ready, {missing} missing.")
    return 1 if missing else 0


def cmd_theatre(args, cfg: Config) -> int:
    """The Theatre: videos, photos, casting, and Chrome for websites."""
    from . import cast, storeroom, theatre
    if args.action == "stream":
        try:
            which = theatre.stream(args.name or "")
        except RuntimeError as exc:
            print(f"Streamer: {exc}.")
            return 1
        print(f"Streamer: opened {which}. To cast a website, use its menu, Cast.")
        return 0
    if args.action == "devices":
        try:
            found = cast.find()
        except cast.CastError as exc:
            print(f"Theatre: {exc}.")
            return 1
        for d in found:
            print(f"{d.cast_info.friendly_name}  ({d.cast_info.model_name}, {d.cast_info.host})")
        print(f"\n{len(found)} Chromecast(s) found on this network.")
        return 0 if found else 1
    storeroom.make_shelves(cfg.path("paths.storeroom"))
    items = theatre.videos(cfg) + theatre.photos(cfg)
    if args.action == "list":
        for i in items:
            print(f"{i.kind:<6} {i.name:<40} {i.source:<12}"
                  + ("" if i.castable else "  (not castable)"))
        print(f"\n{len(items)} item(s). Videos go in "
              f"{storeroom.shelf(cfg.path('paths.storeroom'), 'videos')}, pictures in "
              f"{storeroom.shelf(cfg.path('paths.storeroom'), 'pictures')}.")
        return 0
    if not args.name:
        # 2026-11-06: "nemo theatre check" said "There is no None in the Theatre".
        print(f"Which one? nemo theatre {args.action} \"<name>\"; 'nemo theatre list' "
              "shows what there is.")
        return 1
    item = theatre.find(items, args.name)
    if item is None:
        print(f"There is no {args.name!r} in the Theatre; 'nemo theatre list' shows what is.")
        return 1
    if args.action == "play":
        print(f"Playing {item.name} with {theatre.play_here(item)}.")
        return 0
    if args.action == "check":
        ok, lines = theatre.check(item)
        print("\n".join(lines) or f"{item.name} is a picture: every Chromecast shows it.")
        return 0 if ok is not False else 1
    try:
        found = cast.find()
        device = next((d for d in found if not args.to
                       or d.cast_info.friendly_name.lower() == args.to.lower()), None)
        if device is None:
            print("No Chromecast found" + (f" called {args.to!r}" if args.to else "")
                  + ". It must be on the same network, and switched on.")
            return 1
        ok, lines = theatre.check(item, device.cast_info.model_name)
        for line in lines:
            print(f"Projectionist: {line}")
        if ok is False:
            print("Projectionist: casting it anyway; if the Chromecast cannot play it, "
                  "it is let go by itself.")
        session = cast.Session(device, item.path, on_end=lambda s: print(
            "The Chromecast is let go" + (f" ({s.ended.lower()})" if s.ended else "")
            + ". Press Enter.", flush=True))
    except cast.CastError as exc:
        print(f"Theatre: {exc}.")
        return 1
    print(f"Casting {item.name} to {device.cast_info.friendly_name}. "
          "Press Enter to stop.")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    session.stop()
    print("Stopped.")
    return 0


def cmd_music(args, cfg: Config) -> int:
    """The Music Room: list, play here, cast a list, keep playlists."""
    from . import cast, music, storeroom
    storeroom.make_shelves(cfg.path("paths.storeroom"))
    found = music.tracks(cfg)
    if args.action == "list":
        for t in found:
            print(f"{t.artist or '-':<24} {t.album or '-':<24} {t.title}")
        for p in music.playlists(cfg):
            print(f"playlist: {p.stem}")
        print(f"\n{len(found)} track(s) in {music.shelf(cfg)}")
        return 0
    chosen = []
    for n in args.names:
        pl = next((p for p in music.playlists(cfg) if p.stem.lower() == n.lower()), None)
        chosen += music.load_playlist(cfg, pl) if pl else music.find(found, n)
    if args.action == "save":
        lost = [n for n in args.names[1:] if not music.find(found, n)]
        if lost:
            print(f"Writer: nothing on the music shelf called {', '.join(map(repr, lost))}; "
                  "'nemo music' lists it.")
            return 1
        try:
            p = music.save_playlist(cfg, args.names[0] if args.names else "",
                                    [t for n in args.names[1:] for t in music.find(found, n)])
        except ValueError as exc:
            print(f"Writer: {exc}.")
            return 1
        print(f"Writer: saved {p}")
        return 0
    if not chosen:
        print("Nothing on the music shelf by that name; 'nemo music' lists it.")
        return 1
    if args.action == "play":
        print(f"Player: {len(chosen)} track(s) with {music.play_here(chosen)}.")
        return 0
    try:
        device = next((d for d in cast.find() if not args.to
                       or d.cast_info.friendly_name.lower() == args.to.lower()), None)
        if device is None:
            print("No Chromecast found" + (f" called {args.to!r}" if args.to else "") + ".")
            return 1
        q = cast.Queue(device, [t.path for t in chosen],
                       on_change=lambda q: print(
                           "DJ: the Chromecast is let go." if q.released else
                           f"DJ: playing {q.current.stem} ({q.index + 1} of {len(q.paths)})",
                           flush=True))
    except cast.CastError as exc:
        print(f"DJ: {exc}.")
        return 1
    print("Press Enter to stop.")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    q.stop()
    return 0


def cmd_audio(args, cfg: Config) -> int:
    """The Audio department: narrate a story, ready an SD card, list the shelf."""
    from . import audio, storeroom
    storeroom.make_shelves(cfg.path("paths.storeroom"))
    if args.action == "narrate":
        if not args.name:
            return _which("story", "nemo audio narrate <story>", "'nemo story list'")
        folder = cfg.path("paths.stories") / args.name
        if not folder.is_dir():
            print(f"Narrator: no story called {args.name!r}; 'nemo story list' shows them.")
            return 1
        try:
            book = audio.narrate(cfg, folder)
        except (ValueError, RuntimeError) as exc:
            print(f"Narrator: {exc}.")
            return 1
        print(f"Narrator: the audiobook is in {book}")
        return 0
    if args.action == "card":
        try:
            out, problems = audio.ready_sd_card(cfg, args.name or "", [Path(f) for f in args.files])
        except ValueError as exc:
            print(f"Sound Engineer: {exc}.")
            return 1
        for p in problems:
            print(f"  note: {p}")
        print(f"Sound Engineer: ready in {out} (see index.txt)")
        return 0
    for it in audio.listening(cfg):
        at = audio.place(cfg, it.path)
        print(f"{it.kind:<10} {it.title}" + (f"  (reached {int(at // 60)}:{int(at % 60):02d})" if at else ""))
    return 0


def cmd_science(args, cfg: Config) -> int:
    """Science: units, maths, physics, statistics, spreadsheets, worked out."""
    import sys
    from . import science as S
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")      # a unit sign the console lacks
    a, items = args.action, args.items
    try:
        if a == "formulas":
            for k, (what, eq, units) in S.FORMULAS.items():
                print(f"{k:<10} {what}: {eq}   ({', '.join(units)})")
            return 0
        if a == "read":
            for name, rows in S.read_sheet(Path(items[0])).items():
                print(f"== {name}")
                for r in rows:
                    print("  " + " | ".join("" if v is None else str(v) for v in r))
            return 0
        if a == "convert":
            if len(items) != 2:
                raise S.ScienceError('nemo science convert "10 inch" mm')
            ans = S.convert(items[0], items[1])
        elif a == "formula":
            given = dict(i.split("=", 1) for i in items[1:] if "=" in i)
            ans = S.formula(items[0] if items else "", given)
        elif a == "stats":
            nums = [float(x) for x in items]
            ans = S.stats(nums, cfg.path("paths.storeroom") / "science" /
                          f"chart {datetime.now().strftime('%Y-%m-%d %H%M%S')}.png")
            if args.sheet:
                S.write_sheet(Path(args.sheet), "Readings", ["Reading", "Value"],
                              [[n, v] for n, v in enumerate(nums, 1)])
                print(f"Bookkeeper: {args.sheet}")
        else:
            ans = S.maths(" ".join(items), a)
    except (S.ScienceError, ValueError, IndexError) as exc:
        print(f"Science: {exc}.")
        return 1
    for n, s in enumerate(ans.steps, 1):
        print(f"  {n}. {s}")
    print(f"Answer: {ans.result}")
    print(f"Writer: {S.keep(cfg, ans)}")
    return 0


def cmd_comms(args, cfg: Config) -> int:
    """Communications: the web, letters, email, social media. Nothing is sent."""
    from . import comms
    a = args
    try:
        if a.action == "bookmarks":
            for b in comms.bookmarks(cfg):
                print(f"{b.kind:<7} {b.name:<24} {b.url}")
            return 0
        if a.action == "bookmark":
            b = comms.add_bookmark(cfg, a.name or "", a.url or "", a.kind)
            print(f"Browser: kept {b.name} ({b.url}).")
            return 0
        if a.action == "open":
            print(f"Browser: opened in {comms.open_web(a.name or '', cfg)}.")
            return 0
        if a.action == "contacts":
            for c in comms.contacts(cfg):
                print(f"{c.name:<24} {c.email}")
            return 0
        if a.action == "contact":
            c = comms.add_contact(cfg, a.name or "", a.email or "", (a.address or "").replace("|", "\n"))
            print(f"Postman: kept {c.name}.")
            return 0
        if a.action == "drafts":
            for p in comms.drafts(cfg):
                print(p.name)
            return 0
        body = a.body or ""
        if a.action == "letter":
            body = comms.letter(cfg, a.name or "", body, a.sender or "")
        d = comms.save_draft(cfg, comms.Draft(
            {"email": "email", "letter": "letter", "post": "post"}[a.action],
            a.name or "", a.subject or "", body))
        print(body if a.action == "letter" else "")
        for s in d.spelling:
            print(f"Writer: {s}")
        print(f"Writer: kept as {d.path}")
        if a.action == "email" and a.send:
            print("Postman: " + comms.send_by_mail_program(cfg, d) + ".")
        return 0
    except comms.CommsError as exc:
        print(f"Communications: {exc}.")
        return 1


def cmd_update(args, cfg: Config) -> int:
    """A newer Nemo from the Windows disk, once NemoIso has booted (nemo/update.py)."""
    from . import update
    if args.stop:
        update.stop_using()
        print("The image's own Nemo starts next time.")
        return 0
    found = update.available(args.zip)
    if found is None:
        commit, _ = update.image()
        print("No newer Nemo found" + (f" (this image is {commit[:7]})." if commit else ".")
              + " NemoIso looks for C:\\Nemo\\dist\\NemoWin.zip on the Windows disk.")
        return 0
    print(update.describe(found))
    if not args.yes:
        print("To use it: nemo update --yes (then start Nemo again).")
        return 0
    try:
        dest = update.apply(found)
    except RuntimeError as exc:
        print(f"Not updated: {exc}.")
        return 1
    print(f"Ready in {dest}. Start Nemo again to use it.")
    return 0


def cmd_wood(args, cfg: Config) -> int:
    """The Workshop's Woodworker: a plan for flooring or skirting (nemo/woodworker.py)."""
    from . import woodworker
    board = None
    if args.board:
        w = args.board.lower().replace(" ", "").split("x")
        board = (int(w[0]), int(w[1]))
    try:
        p = woodworker.plan(args.job, pack_m2=args.pack, board_mm=board, doors=args.doors)
    except woodworker.WoodworkerError as exc:
        print(f"Woodworker: {exc}.")
        return 2
    print(p.text())
    if p.room_mm and p.board_mm:
        # The floor drawn by CADCraft (nemo/drawings.py), to scale, when it is installed.
        from . import drawings
        import re as _re
        slug = _re.sub(r"[^a-z0-9]+", "-", p.job.lower()).strip("-")
        where = cfg.path("paths.projects") / "woodworker" / slug
        try:
            made = drawings.floor_drawing(p, where)
        except drawings.DrawingError as exc:
            print(f"\nNo floor drawing: {exc}.")
            return 0
        if made is None:
            print("\n" + drawings.NOT_INSTALLED)
        elif made.ok:
            print(f"\nDrawn to scale on {made.paper}: {made.files[1]} (and .dxf, .png beside it).")
            _send_finished(cfg, "workshop", where)
        else:
            print("\nThe floor drawing does not read back as drawn, so it is not offered: "
                  + "; ".join(made.faults[:3]))
    return 0


def cmd_home(args, cfg: Config) -> int:
    """Home: the devices on the network, and what Nemo may do with each."""
    from . import home
    try:
        if args.action == "survey":
            found = home.remember(home.survey())
            print(f"Surveyor: {len(found)} device(s) on this network.")
            args.action = "list"
        if args.action == "list":
            shown = [d for d in home.known() if d.permission != "hidden" or args.all]
            last = home.last_survey()
            here = [d for d in shown if home.present(d, last)]
            gone = [d for d in shown if not home.present(d, last)]
            for d in sorted(here, key=lambda d: d.label.lower()):
                kind, why = home.device_type(d)
                print(f"{d.permission:<7} {d.label:<24} {d.ip:<16} "
                      + (f"{kind}  [{why}]" if kind else f"type not known: {why}")
                      + f"\n{'':<7} Nemo can: {home.can_do(d)}")
            if gone:
                print("\nNot found by the latest survey (remembered):")
                for d in sorted(gone, key=lambda d: d.label.lower()):
                    print(f"{d.permission:<7} {d.label:<32} {d.ip:<16} last seen {d.seen or 'unknown'}")
            hidden = len(home.known()) - len(shown)
            print(f"\n{len(here)} device(s) found" + (f", {len(gone)} remembered" if gone else "")
                  + (f", {hidden} hidden (--all shows them)" if hidden else "")
                  + ". Set one with: nemo home allow \"<device>\" hidden|see|use")
            return 0
        if args.action == "allow":
            if not args.name or args.permission not in home.PERMISSIONS:
                raise home.HomeError("say which device and hidden, see or use: "
                                     "nemo home allow \"Family Room TV\" use")
            d = home.allow(args.name, args.permission)
            print(f"Gatekeeper: {d.label} is now {d.permission}. The change is logged.")
            return 0
        if args.action == "platform":
            if not args.name:
                for key, (label, what, built) in home.PLATFORMS.items():
                    print(f"{key:<12} {label}\n{'':<12} Nemo can: {what}")
                print('\nChoose one: nemo home platform "<device>" <platform>')
                return 0
            d = home.set_platform(args.name, args.permission or "")
            print(f"Home: {d.label} is {home.PLATFORMS[d.platform][0] if d.platform else 'not chosen'}. "
                  f"Nemo can: {home.can_do(d)}. The change is logged.")
            return 0
        if args.action == "changes":
            for c in home.changes():
                print(f"{c['at']}  {c['name']}: {c['from']} -> {c['to']} (by {c['by']})")
            return 0
        if args.action == "boards":
            found = home.boards(cfg)
            for b in found:
                print(f"{b.project:<24} flashed {b.flashed}; {b.note}"
                      + (f"\n    {b.status}" if b.status else ""))
            if not found:
                print("Device Keeper: no board has been flashed from the Test Bench yet.")
            return 0
        print(f"Writer: {home.write_list(cfg)}")
        return 0
    except home.HomeError as exc:
        print(f"Home: {exc}.")
        return 1


def cmd_film(args, cfg: Config) -> int:
    """The Film Studio: films from stories, clips joined, slideshows."""
    from . import filmstudio as F
    from . import music, theatre
    try:
        if args.action == "list":
            for d in F.stories(cfg):
                print(f"story  {d.name}")
            for v in theatre.videos(cfg):
                print(f"video  {v.name}")
            return 0
        if args.action in ("plan", "make") and not args.name:
            return _which("story", f"nemo film {args.action} <story>", "`nemo film list`")
        if args.action in ("plan", "make"):
            story = next((d for d in F.stories(cfg) if d.name.lower() == (args.name or "").lower()),
                         None)
            if story is None:
                print(f"Film Studio: no story called {args.name!r}; `nemo film list` shows them.")
                return 1
            plan = F.plan_for(cfg, story)
            if args.picture:
                for s in plan.scenes:
                    s.picture = str(Path(args.picture).expanduser())
            if args.action == "plan":
                path = F.save_plan(cfg, plan)
                for n, s in enumerate(plan.scenes, 1):
                    print(f"Scene {n}: {' '.join(s.text.split()[:16])}...\n    picture: "
                          f"{s.picture or 'painted from: ' + s.prompt}")
                print(f"\n{len(plan.scenes)} scene(s). Change the plan in {path}, then: "
                      f"nemo film make {story.name}")
                return 0
            made = F.make_film(cfg, plan, paint=not args.quick)
        elif args.action == "join":
            clips = []
            found = theatre.videos(cfg)
            for spec in args.items:
                name, start, end = F.clip_spec(spec)
                item = theatre.find(found, name)
                clips.append((item.path if item else Path(name), start, end))
            made = F.join_clips(cfg, args.name or "joined", clips)
        else:                                                    # slideshow
            photos = theatre.photos(cfg)
            pics = [(theatre.find(photos, n).path if theatre.find(photos, n) else Path(n))
                    for n in args.items]
            tracks = [t.path for n in (args.music or []) for t in music.find(music.tracks(cfg), n)]
            made = F.slideshow(cfg, args.name or "slideshow", pics, tracks, args.seconds)
    except (F.FilmError, OSError, RuntimeError) as exc:
        print(f"Film Studio: {exc}.")
        return 1
    for n in made.notes:
        print(n)
    print(f"Film: {made.film}" + (f"\nSubtitles: {made.subtitles}" if made.subtitles else ""))
    print("The Theatre lists it with the videos.")
    return 0


def cmd_studio(args, cfg: Config) -> int:
    """The Game Studio (nemo/gamestudio.py): games in Godot from your idea."""
    from . import gamestudio as G
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    if args.action == "kinds":
        print("Built by code: " + ", ".join(G.KINDS) + ". Any other idea: the model writes "
              "it (Game mode, loaded for it), and the Tester checks it.")
        return 0
    if args.action == "list":
        found = G.games(cfg)
        for g in found:
            print(f"{g['title']:<32} {g['kind']:<11} {g['folder']}")
        print(f"\n{len(found)} game(s) in {G.folder(cfg)}.")
        return 0
    words = " ".join(args.words).strip()
    if args.action == "new":
        if not words:
            print("Game Studio: say your idea: nemo studio new \"a platformer where ...\"")
            return 1
        from . import modes
        want = G.model_mode(cfg) if G.kind_of(words) is None else None
        if want and modes.current().name != want:
            ok, said = modes.start(cfg, want)
            print(f"Game Studio: {said}", flush=True)
        router = Router(cfg) if modes.current().running else None
        try:
            made = G.make(cfg, words, router, say=lambda m: print(m, flush=True))
        except G.StudioError as exc:
            print(f"Game Studio: {exc}.")
            return 1
        print(f"\n{made.spec.title}: {made.where}"
              + ("" if made.check.ok else "\nThe Tester found faults: see README.md."))
        if made.check.ok:
            print(f"Play it: nemo studio play \"{made.spec.title}\"")
            _send_finished(cfg, "studio", made.where)
        return 0 if made.check.ok else 1
    where = G.find(cfg, words)
    if where is None:
        print(f"Game Studio: no game called {words!r}; `nemo studio list` shows them." if words
              else "Game Studio: which game? `nemo studio list` shows them.")
        return 1
    if args.action == "check":
        c = G.test(where, cfg)
        print(("Tester: passed" if c.ok else "Tester: FAILED") + f" in {c.seconds} s.")
        for line in c.lines:
            print(f"  {line}")
        return 0 if c.ok else 1
    ok, why = G.available(cfg)
    if not ok:
        print(f"Game Studio: {why}.")
        return 1
    G.play(cfg, where)
    print(f"Playing {where.name}: Left and Right to move, Space or Up to jump; close the window "
          "to stop.")
    return 0


def cmd_print(args, cfg: Config) -> int:
    """The Print Shop: the models it can slice, and a slice for the Kobra 3."""
    from . import printshop
    found = printshop.models(cfg)
    if args.action == "list" or not args.name:
        for m in found:
            print(f"{m.name:<30} {m.where:<11} {m.stl}")
        print(f"\n{len(found)} model(s)." + ("" if found else
              " Make one in the Art Studio (nemo model) or a Workshop enclosure."))
        return 0
    m = next((m for m in found if m.name == args.name), None)
    if m is None:
        print(f"Print Shop: no model named {args.name!r}; `nemo print list` shows them.")
        return 1
    exe = printshop.orca(cfg)
    c = printshop.choices(exe) if exe else {"process": [], "filament": []}
    pick = {}
    for kind, given, default in (("process", args.quality, printshop.QUALITY),
                                 ("filament", args.filament, printshop.FILAMENT)):
        names = [n for n in c[kind] if given and n.lower().startswith(given.lower())]
        if given and not names:
            print(f"Print Shop: no {kind} starting {given!r}; there are:")
            for n in c[kind]:
                print(f"  {n.split(' @')[0]}")
            return 1
        pick[kind] = names[0] if names else default
    job = printshop.slice_model(cfg, m, pick["process"], pick["filament"])
    for n in job.notes:
        print(f"note: {n}")
    if not job.ok:
        print("Not sliced.")
        return 1
    print(job.card.read_text(encoding="utf-8"))
    print(f"G-code: {job.gcode}  (sliced in {job.seconds:g} s)")
    return 0


def cmd_bench(args, cfg: Config) -> int:
    """The Test Bench: the board's ports, flash the firmware, listen to it."""
    from . import bench
    if args.action == "ports":
        found = bench.ports()
        for p in found:
            print(f"{p.device:<10} {p.description}" + (f"  ({p.hint})" if p.hint else "")
                  + ("  (a Bluetooth link, not a board)" if p.bluetooth else ""))
        print(f"\n{len(found)} serial port(s)."
              + ("" if bench.board_port(found) else " No board: is it plugged in?"))
        return 0
    project = _project(cfg, args.project)
    if args.action == "flash":
        found = bench.ports()
        if not args.port and found and not bench.board_port(found):
            print("Flasher: the only serial ports are Bluetooth links; plug the board in, "
                  "or name its port with --port.")
            return 1
        run = bench.flash(project, args.port)
    else:
        found = bench.board_port(bench.ports())
        port = args.port or (found.device if found else None)
        if not port:
            print("Serial Monitor: no board's serial port (Bluetooth links are not boards); "
                  "plug the board in, or name one with --port.")
            return 1
        run = bench.listen(project, port, args.seconds, args.baud)
    for line in run.lines[-25:]:
        print(f"  {line}")
    for n in run.notes:
        print(f"note: {n}")
    print(("Done." if run.ok else "Not done.") + (f" Log: {run.log}" if run.log else ""))
    return 0 if run.ok else 1


def cmd_games(args, cfg: Config) -> int:
    """Gaming: the games shelf, and each console's emulator."""
    from . import gaming
    gaming.make_shelves(cfg)
    found = gaming.games(cfg)
    if args.action == "emulators":
        for c in gaming.CONSOLES:
            why = gaming.why_not(c, cfg)
            print(f"{c.name + ' Emulator':<28} {'ready' if not why else why}")
        return 0
    if args.action == "list":
        for g in found:
            wrong = gaming.shelf_check(g)
            print(f"{g.console.name:<18} {g.name}" + (f"\n    Attendant: {wrong}." if wrong else ""))
        print(f"\n{len(found)} game(s). Put your own game files in "
              f"{gaming.shelf(cfg, gaming.CONSOLES[0]).parent}\\<console>.")
        return 0
    if not args.name:
        return _which("game", f"nemo games {args.action} \"<game>\"", "'nemo games list'")
    game = gaming.find(found, args.name)
    if game is None:
        print(f"There is no game {args.name!r} on the shelves; 'nemo games list' shows them.")
        return 1
    wrong = gaming.shelf_check(game)
    if wrong:
        print(f"Attendant: {wrong}.")
    try:
        gaming.play(game, cfg, fullscreen=not args.window)
    except RuntimeError as exc:
        print(f"{game.console.name} Emulator: {exc}.")
        return 1
    print(f"The {game.console.name} Emulator is playing {game.name}. Esc quits it.")
    return 0


def _store(cfg: Config) -> AdminStore:
    return AdminStore(Path(os.environ.get("NEMO_HOME",
                                          Path.home() / ".nemo")) / "admin")


def cmd_admin(args, cfg: Config) -> int:
    store = _store(cfg)

    if args.action == "init":
        if store.has_password() and not args.force:
            raise SystemExit("a credential already exists; pass --force to replace it")
        user = args.username or input("admin username: ").strip()
        pw = getpass.getpass("password: ")
        if pw != getpass.getpass("repeat: "):
            raise SystemExit("passwords did not match")
        store.set_password(user, pw)
        print(f"admin credential set for {user!r}")
        print("Stored as a salted scrypt hash. It cannot be read back.")
        return 0

    if args.action == "login":
        if not store.has_password():
            raise SystemExit("no admin credential yet. Run: nemo admin init")
        user = args.username or input("username: ").strip()
        res = store.login(user, getpass.getpass("password: "))
        print(res.message)
        return 0 if res.ok else 1

    if args.action == "logout":
        store.logout(); print("signed out"); return 0

    if args.action == "show":
        auth = resolve(store.root)
        policy = auth.policy
        eff = auth.effective
        print(auth.describe() + "\n")
        print("Effective safety parameters")
        print("  (F) = fixed floor, cannot be loosened by any policy\n")
        for key in sorted(eff):
            fixed = "F" if key in auth.floor and eff[key] == auth.floor.get(key) else " "
            print(f"  [{fixed}] {key:<42} {eff[key]}")
        problems = policy.validate()
        if problems:
            print("\nRejected from the policy file (they tried to loosen the floor):")
            for x in problems:
                print(f"  ! {x}")
        return 0

    # everything below changes state, so it needs a session
    try:
        store.require_session()
    except PermissionError as exc:
        raise SystemExit(str(exc))

    if args.action == "set":
        if not args.key:
            raise SystemExit("usage: nemo admin set KEY VALUE")
        # Bound to the active floor, so a local admin cannot loosen past a
        # limit the master has set. Previously validated against the
        # compiled default, which let 36 V through under a 24 V signed floor.
        policy = resolve(store.root).policy
        raw = args.value
        for cast in (int, float):
            try:
                raw = cast(args.value); break
            except (TypeError, ValueError):
                continue
        else:
            if str(args.value).lower() in ("true", "false"):
                raw = str(args.value).lower() == "true"
        before = policy.effective().get(args.key)
        policy.values[args.key] = raw
        problems = policy.validate()
        if problems:
            print("Refused:")
            for x in problems:
                print(f"  ! {x}")
            store.append_audit("policy_refused",
                               {"key": args.key, "value": str(raw),
                                "reason": problems})
            return 1
        policy.version += 1
        policy.save(store.policy)
        after = policy.effective().get(args.key)
        store.append_audit("policy_set", {"key": args.key,
                                          "from": str(before), "to": str(after),
                                          "version": policy.version})
        print(f"{args.key}: {before} -> {after}  (policy v{policy.version})")
        return 0

    if args.action == "unset":
        policy = resolve(store.root).policy
        if args.key not in policy.values:
            raise SystemExit(f"{args.key!r} is not set in the policy")
        del policy.values[args.key]
        policy.version += 1
        policy.save(store.policy)
        store.append_audit("policy_unset", {"key": args.key})
        print(f"{args.key} removed; the floor value applies again")
        return 0

    if args.action == "history":
        ok, msg = store.verify_audit()
        print(f"audit chain: {msg}\n")
        for rec in store.audit_entries(args.limit):
            when = datetime.fromtimestamp(rec["ts"]).strftime("%Y-%m-%d %H:%M")
            print(f"  {when}  {rec['event']:<18} {rec.get('detail', {})}")
        return 0 if ok else 1

    if args.action == "verify":
        ok, msg = store.verify_audit()
        print(msg)
        return 0 if ok else 1

    return 0


def _lock(cfg: Config) -> Lockdown:
    return Lockdown(Path(os.environ.get("NEMO_HOME",
                                        Path.home() / ".nemo")) / "admin")


def _root_is_encrypted() -> bool:
    from .lockdown import root_is_encrypted
    return root_is_encrypted()


def cmd_lock(args, cfg: Config) -> int:
    lock = _lock(cfg)
    store = _store(cfg)

    if args.action == "status":
        st = lock.read_state()
        print(f"state: {st.state}")
        if st.reason:
            print(f"  {st.reason}")
        for c in st.changes:
            print(f"  - {c}")
        base = lock.baseline()
        if base:
            print(f"\nmeasuring {len(base.values)} item(s):")
            for k in sorted(base.values):
                print(f"  {k}")
        else:
            print("\nNot armed. Run: sudo nemo lock baseline")
        return 1 if st.locked else 0

    if args.action == "baseline":
        # Refused on an unencrypted root, because a baseline the attacker
        # can rewrite makes the whole mechanism a formality.
        if not _root_is_encrypted() and not args.force:
            print("Refused: the root filesystem is not encrypted.")
            print()
            print("The baseline must live inside an encrypted volume. On an")
            print("unencrypted disk, anyone who boots a USB stick can read")
            print("it, modify your bootloader, and write a matching baseline")
            print("back -- so the check would always pass and detect nothing.")
            print()
            print("Encrypt the disk first. See docs/hardening.md.")
            print("To arm anyway, knowing it proves little: --force")
            return 1
        m = lock.arm()
        store.append_audit("lock_baseline", {"items": len(m.values),
                                             "digest": m.digest[:16]})
        print(f"baseline recorded: {len(m.values)} item(s)")
        for k in sorted(m.values):
            print(f"  {k}")
        if args.force:
            print("\nArmed WITHOUT encryption. This detects accidents, not "
                  "attackers.")
        return 0

    if args.action == "check":
        st = lock.check()
        if st.state == "no-baseline":
            print("not armed"); return 0
        if st.locked:
            print("LOCKED: " + st.reason)
            for c in st.changes:
                print(f"  - {c}")
            store.append_audit("lock_triggered", {"changes": st.changes})
            return 1
        print("boot chain matches baseline")
        return 0

    if args.action == "unlock":
        try:
            store.require_session()
        except PermissionError as exc:
            raise SystemExit(str(exc))
        st = lock.read_state()
        if not st.locked:
            print("not locked"); return 0
        print("Clearing this accepts the current boot chain as the new")
        print("baseline. Changes that triggered the lock:")
        for c in st.changes:
            print(f"  - {c}")
        if input("\nInvestigated and accepted? [y/N] ").strip().lower() != "y":
            print("left locked"); return 1
        lock.unlock(args.note or "cleared by administrator", measure())
        store.append_audit("lock_cleared", {"was": st.changes,
                                            "note": args.note or ""})
        print("unlocked and re-baselined")
        return 0

    return 0


def _home() -> Path:
    return Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo"))


def _maint() -> Maintenance:
    return Maintenance(_home() / "admin", MASTER_PUBLIC_KEY)


def cmd_maint(args, cfg: Config) -> int:
    m = _maint()
    store = _store(cfg)

    if args.action == "status":
        st = m.read()
        print(f"clone id    : {clone_id(_home() / 'admin')}")
        if MASTER_PUBLIC_KEY:
            print(f"master key  : {public_key_fingerprint(MASTER_PUBLIC_KEY)}")
        else:
            print("master key  : none embedded -- maintenance documents "
                  "cannot be verified on this build")
        print(f"state       : {'HALTED' if st.halted else 'running'}")
        if st.halted:
            print(f"  reason    : {st.reason}")
        for h in st.history[-5:]:
            when = datetime.fromtimestamp(h.get("at", 0)).strftime("%Y-%m-%d %H:%M")
            print(f"  {when}  {h.get('action'):<7} {h.get('note', '')}")
        print("\nGive the clone id to the master to receive an operation "
              "document for this machine.")
        return 1 if st.halted else 0

    if args.action == "diagnose":
        # Open to anyone: it only reads, and never includes secrets.
        doctor_text, _ = doctor.report()
        bundle = diagnose(_home(), Path(args.out or Path.cwd()),
                          {"doctor": doctor_text,
                           "audit_chain": store.verify_audit()[1]})
        print(f"wrote {bundle}")
        print("Safe to send: credentials, session tokens and API keys are "
              "excluded. See EXCLUDED.txt inside.")
        return 0

    if args.action == "apply":
        if not args.document:
            raise SystemExit("usage: nemo maint apply <document.json>")
        doc_path = Path(args.document)
        # Physical presence, as required: console and removable media.
        on_console, how = _on_local_console()
        if not on_console:
            raise SystemExit(f"refused: physical presence required ({how}).")
        removable, where = _is_removable(doc_path)
        if not removable and not args.allow_fixed:
            raise SystemExit(
                f"refused: the document must be on removable media ({where}). "
                "Copy it to a USB stick and run this from that path.")
        try:
            doc = OperationDocument.from_json(doc_path.read_text(encoding="utf-8", errors="replace"))
            print(f"action : {doc.action}")
            print(f"note   : {doc.note or '(none)'}")
            msg = m.apply(doc, audit=store)
        except SigningError as exc:
            store.append_audit("maint_refused", {"reason": str(exc)[:200]})
            raise SystemExit(f"refused: {exc}")
        print(msg)
        return 0

    return 0


def cmd_master(args, cfg: Config) -> int:
    """Signed floor documents. The command the documentation promised and
    an earlier revision never actually provided."""
    from .master import apply_floor
    store = _store(cfg)
    auth = resolve(store.root)

    if args.action == "status":
        if MASTER_PUBLIC_KEY:
            print(f"master key : {public_key_fingerprint(MASTER_PUBLIC_KEY)}")
        else:
            print("master key : none embedded -- signed floors cannot be "
                  "verified on this build")
        print(auth.describe())
        return 0

    if args.action == "apply":
        if not args.document:
            raise SystemExit("usage: nemo master apply <floor-N.signed.json>")
        try:
            values, notes = apply_floor(Path(args.document), store.root,
                                        minimum_serial=auth.serial,
                                        require_physical=True)
        except SigningError as exc:
            store.append_audit("floor_refused", {"reason": str(exc)[:200]})
            raise SystemExit(f"refused: {exc}")
        after = resolve(store.root)
        store.append_audit("floor_applied", {"serial": after.serial,
                                             "notes": notes})
        print(f"applied signed floor, serial {after.serial}")
        for n in notes:
            print(f"  {n}")
        if after.overridden:
            print("\nThe hard floor overrode part of this document:")
            for x in after.overridden:
                print(f"  - {x}")
        return 0
    return 0


def cmd_clone(args, cfg: Config) -> int:
    from .master import stage_clone
    tree = Path(__file__).resolve().parent.parent
    try:
        result = stage_clone(_home(), tree, Path(args.dest))
    except (FileExistsError, FileNotFoundError) as exc:
        raise SystemExit(str(exc))
    print(f"staged a clean clone at {result['dest']}")
    print("\ncarried:")
    for r in result["carried"] or ["(nothing yet)"]:
        print(f"  + {r}")
    print("dropped, as every clone must:")
    for r in result["dropped"] or ["(none present)"]:
        print(f"  - {r}")
    print("\nBuild the image on a faster machine, not this one:")
    print(f"  cd {result['dest']} && sudo packaging/build-iso.sh live")
    return 0


def cmd_status(args, cfg: Config) -> int:
    # Outside a project, say what exists rather than failing -- this is the
    # first command the launch window runs.
    if not args.project and not (Path.cwd() / "brief.yaml").exists():
        root = cfg.path("paths.projects")
        st = modes.current()
        print(f"mode     : {st.name + ' (' + str(st.model) + ')' if st.running else 'none loaded'}")
        found = sorted(p.parent.name for p in root.glob("*/brief.yaml")) if root.exists() else []
        print(f"projects : {', '.join(found) if found else 'none yet'}  ({root})")
        print('\nStart one:  nemo new <name> "<what it should do>"')
        return 0
    project = _project(cfg, args.project)
    state = project.status()
    for stage in STAGES:
        print(f"  [{'x' if state.get(stage) else ' '}] {stage}")
    nxt = project.next_stage()
    print(f"\nnext: {nxt}" if nxt else "\nall stages complete")
    return 0


# --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nemo", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--project", help="project name under paths.projects")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor")

    m = sub.add_parser("mode")
    m.add_argument("name", nargs="?",
                   help="design | build | talk | off")
    m.add_argument("--force", action="store_true",
                   help="start even if memory looks too tight")

    n = sub.add_parser("new")
    n.add_argument("name")
    n.add_argument("brief")

    r = sub.add_parser("run")
    r.add_argument("--from", dest="start", help="step to start at")
    r.add_argument("--only", help="run just this one step")
    r.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    r.add_argument("--keep-going", action="store_true",
                   help="continue past a failed gate (rarely a good idea)")

    sub.add_parser("check")

    p = sub.add_parser("parts")
    p.add_argument("ref", nargs="?")

    sub.add_parser("status")

    sub.add_parser("credits", help="who made what Nemo is built from, written into the Storeroom")
    so = sub.add_parser("story", help="stories written by Nemo's employees")
    so.add_argument("action", choices=["list", "new", "write", "cover", "book"])
    so.add_argument("text", nargs="*", help="new: what the story is; write, cover: its name")
    so.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    dr = sub.add_parser("draft", help="have the model draft a project's brief")
    dr.add_argument("description")
    dr.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    gu = sub.add_parser("gui", help="open the desktop interface")
    gu.add_argument("--prompt", action="store_true",
                    help="open at the prompt window, as at boot")

    sub.add_parser("power", help="suggest power supplies for the parts")

    sub.add_parser("pcb", help="a routed circuit board from the project's connections, checked, "
                               "with its Gerbers")
    fpp = sub.add_parser("footprint", help="parts' footprints, or a header read off your own module")
    fpp.add_argument("action", nargs="?", choices=["list", "header"], default="list")
    fpp.add_argument("items", nargs="*")

    so = sub.add_parser("second", help="the other model looks again at the design's wiring")
    so.add_argument("--mode", default="talk", help="the mode to ask (default talk: not the design's)")

    ev = sub.add_parser("eval", help="SHIP or DON'T SHIP a model for Nemo's jobs (Soup-style)")
    ev.add_argument("--base", default="talk", help="the mode to measure against (default talk)")
    ev.add_argument("--candidate", default="design", help="the mode being judged (default design)")
    ev.add_argument("--tasks", help="a Soup task file (JSONL); default Nemo's own")
    ev.add_argument("--write-tasks", metavar="FILE", help="write Nemo's tasks from the parts library")

    of = sub.add_parser("offline", help="what works offline; prepare for it")
    of.add_argument("action", nargs="?", choices=["status", "prepare"], default="status")
    of.add_argument("--all", action="store_true", help="include Deep mode's 5 GB model")

    ds = sub.add_parser("datasheet", help="the offline datasheet library")
    ds.add_argument("action", choices=["add", "search", "list", "link", "unlink", "index", "draft"])
    ds.add_argument("items", nargs="*")
    ds.add_argument("--part")

    rv = sub.add_parser("review", help="second opinions waiting to be sent")
    rv.add_argument("action", nargs="?", choices=["list", "send"], default="list")

    fx = sub.add_parser("fix", help="list or apply suggested fixes")
    fx.add_argument("number", nargs="?", type=int)
    fx.add_argument("--stage")

    rn = sub.add_parser("render", help="draw the enclosure STL: iso, top, front, right")
    rn.add_argument("--stl", help="a specific STL instead of the project's housing")
    rn.add_argument("--views", help="comma-separated: iso,top,bottom,front,right")
    rn.add_argument("--size", type=int, default=480, help="pixels per view")
    rn.add_argument("--out", help="folder for the PNGs (default: the project's renders/)")

    cn = sub.add_parser("concept", help="the Artist's two enclosure concepts; choose one")
    cn.add_argument("action", choices=["show", "choose", "redraw"])
    cn.add_argument("key", nargs="?", help="choose: A or B")
    cn.add_argument("--corners", choices=["square", "rounded"])
    cn.add_argument("--notch", choices=["left", "front"], help="the cable opening's wall")
    cn.add_argument("--changes", help="anything about where the parts go, for the Designer")

    pt = sub.add_parser("part", help="add or remove a part in your own library")
    pt.add_argument("action", choices=["add", "remove"])
    pt.add_argument("ref")
    pt.add_argument("--name")
    pt.add_argument("--category")
    pt.add_argument("--supply-v", help="comma-separated volts, e.g. 3.3,5.0")
    pt.add_argument("--logic-v", type=float)
    pt.add_argument("--current-ma", type=float, default=0.0)
    pt.add_argument("--peak-ma", type=float, default=0.0)
    pt.add_argument("--size-mm", help="comma-separated L,W,H in mm")
    pt.add_argument("--mount", choices=["holes", "slot", "panel", "loose"])
    pt.add_argument("--interfaces", help="comma-separated, e.g. spi,i2c")
    pt.add_argument("--datasheet",
                    help="where the figures came from -- required")
    pt.add_argument("--notes")
    pt.add_argument("--overwrite", action="store_true",
                    help="replace an existing part with this ref, "
                         "including a bundled one")

    st = sub.add_parser("store", help="the Storeroom: the parts you have to hand")
    st.add_argument("action", nargs="?", default="list",
                    choices=["list", "add", "take", "remove", "suggest", "link",
                             "space", "drives", "move", "vault", "finished"])
    st.add_argument("name", nargs="?", default="",
                    help="what the part is, e.g. 'ESP32 DevKit'")
    st.add_argument("--qty", type=int, default=1, help="how many to add or take")
    st.add_argument("--part", help="the parts-library ref it is, if not found by name")
    st.add_argument("--where", help="where it is kept, e.g. 'drawer 3'")
    st.add_argument("--notes")
    st.add_argument("--ext", action="append", help="move: a kind of file to move, e.g. .jpg")
    st.add_argument("--yes", action="store_true", help="move: do it")

    dc = sub.add_parser("clinic", help="the Doctors: diagnose what is wrong and advise")
    dc.add_argument("action", nargs="?", default="see",
                    choices=["see", "notes", "treat", "undo", "treatments", "report", "updates"])
    dc.add_argument("which", nargs="?",
                    help="treat: the finding's number; undo: a treatment id (default the last)")
    dc.add_argument("--last", type=int, default=20, help="how many past visits to list")
    dc.add_argument("--yes", action="store_true",
                    help="say yes to the remedy or undo shown, without being asked")

    sub.add_parser("test", help="the Tester: compile the project's firmware now")
    ah = sub.add_parser("ahead", help="the Technician: the model the next step needs")
    ah.add_argument("--load", action="store_true", help="load it now, if it fits")
    md = sub.add_parser("model", help="the Art Studio: 3D printable models from shapes")
    md.add_argument("action", nargs="?", default="list",
                    choices=["list", "build", "shapes", "kinds", "make", "card", "split"])
    md.add_argument("spec", nargs="?",
                    help="build: a JSON list of shapes; make: the kind; card, split: the model")
    md.add_argument("choices", nargs="*",
                    help="make: the model's name, then key=value choices (`nemo model kinds`)")
    md.add_argument("--title", help="card: the model's title (empty clears it)")
    md.add_argument("--line", help="card: a line about it (empty clears it)")
    tm = sub.add_parser("times", help="the Timekeeper: how fast the model reads and writes")
    tm.add_argument("--department", help="only the modes this department's steps use")
    tm.add_argument("--builds", action="store_true",
                    help="each job's time in this build against the build before, per machine")
    tm.add_argument("--measure", action="store_true",
                    help="run the same jobs 3 times and compare with the build before")
    lu = sub.add_parser("lookup", help="the Researcher: look words up on Wikipedia")
    lu.add_argument("words", nargs="+")
    lu.add_argument("--story", help="keep what is found with this story")
    ar = sub.add_parser("archive", help="the Archivist: answers kept for reuse")
    ar.add_argument("action", nargs="?", default="count", choices=["count", "clear"])
    qu = sub.add_parser("queue", help="the Foreman: queue long jobs and run them")
    qu.add_argument("action", nargs="?", default="list",
                    choices=["list", "add", "story", "cover", "model", "print", "run", "clear"])
    qu.add_argument("name", nargs="?",
                    help="the project or story; model: a JSON list of shapes; print: the model")
    qu.add_argument("steps", nargs="*", help="add: the steps (default: all but the brief)")
    qu.add_argument("--department", help="list: only this department's jobs")

    sf = sub.add_parser("staff", help="each employee's tools on this machine")
    sf.add_argument("department", nargs="?", help="one department, e.g. library")

    th = sub.add_parser("theatre", help="the Theatre: videos, photos, casting, websites")
    th.add_argument("action", nargs="?", default="list",
                    choices=["list", "play", "cast", "check", "devices", "stream"])
    th.add_argument("name", nargs="?", help="the video or photo; for stream, a web address")
    th.add_argument("--to", help="the Chromecast's name, when there is more than one")

    sub.add_parser("guide", help="the Computer Lab's Writer: the project's firmware guide")
    sc = sub.add_parser("science", help="Science: units, maths, physics, statistics, spreadsheets")
    sc.add_argument("action", choices=["convert", "solve", "simplify", "factor", "expand",
                                       "differentiate", "integrate", "evaluate", "formula",
                                       "formulas", "stats", "read"])
    sc.add_argument("items", nargs="*", help="the quantity and unit, the maths, the formula "
                    "and its values (V=? I=\"20 mA\"), the numbers, or the .xlsx")
    sc.add_argument("--sheet", help="stats: also write the numbers to this .xlsx")
    co = sub.add_parser("comms", help="Communications: the web, letters, email; nothing is sent")
    co.add_argument("action", nargs="?", default="bookmarks",
                    choices=["bookmarks", "bookmark", "open", "contacts", "contact",
                             "email", "letter", "post", "drafts"])
    co.add_argument("name", nargs="?", help="the bookmark, address, contact or site")
    co.add_argument("url", nargs="?", help="bookmark: its web address")
    co.add_argument("--kind", default="web", help="bookmark: web, mail or social")
    co.add_argument("--email", help="contact: the email address")
    co.add_argument("--address", help="contact: the postal address, lines split by |")
    co.add_argument("--subject")
    co.add_argument("--body", help="email/letter/post: your words")
    co.add_argument("--sender", help="letter: your name under it")
    co.add_argument("--send", action="store_true",
                    help="email: open your mail program with it (you press Send)")
    wd = sub.add_parser("wood", help="the Workshop's Woodworker: plan flooring or skirting")
    wd.add_argument("job", help="e.g. 'laminate flooring 4.2 x 3.6 m'")
    wd.add_argument("--pack", type=float, help="m2 one pack covers (from the packet)")
    wd.add_argument("--board", help="board length x width in mm, e.g. 1380x193")
    wd.add_argument("--doors", type=int, help="doorways (default: as the job says, else 1)")
    up = sub.add_parser("update", help="NemoIso: use a newer NemoWin.zip from the Windows disk")
    up.add_argument("--yes", action="store_true", help="unpack and use it")
    up.add_argument("--stop", action="store_true", help="go back to the image's own Nemo")
    up.add_argument("--zip", help="the zip to look at (default: what nemodoc found)")
    hm = sub.add_parser("home", help="Home: the devices on your network and Nemo's permissions")
    hm.add_argument("action", nargs="?", default="list",
                    choices=["survey", "list", "allow", "platform", "changes", "boards", "write"])
    hm.add_argument("name", nargs="?", help="allow/platform: the device, by name or address")
    hm.add_argument("permission", nargs="?",
                    help="allow: hidden, see or use; platform: one of the platforms "
                         "(nemo home platform lists them)")
    hm.add_argument("--all", action="store_true", help="list: hidden devices too")
    fm = sub.add_parser("film", help="the Film Studio: films from stories, clips, slideshows")
    fm.add_argument("action", nargs="?", default="list",
                    choices=["list", "plan", "make", "join", "slideshow"])
    fm.add_argument("name", nargs="?", help="plan/make: the story; join/slideshow: the film's name")
    fm.add_argument("items", nargs="*",
                    help="join: clips, each optionally cut as name@start-end; slideshow: pictures")
    fm.add_argument("--quick", action="store_true",
                    help="make: no painting (the story's cover, or a card with its first words)")
    fm.add_argument("--picture", help="plan/make: one picture for every scene")
    fm.add_argument("--music", nargs="*", help="slideshow: tracks, artists or albums")
    fm.add_argument("--seconds", type=float, default=5.0, help="slideshow: seconds a picture")
    gs = sub.add_parser("studio", help="the Game Studio: games in Godot from your idea")
    gs.add_argument("action", nargs="?", default="list",
                    choices=["list", "new", "play", "check", "kinds"])
    gs.add_argument("words", nargs="*", help="new: your idea; play, check: the game's name")
    pr = sub.add_parser("print", help="the Print Shop: slice a model for the Kobra 3")
    pr.add_argument("action", nargs="?", default="list", choices=["list", "slice"])
    pr.add_argument("name", nargs="?", help="slice: the model's name, as `nemo print list` shows it")
    pr.add_argument("--quality", help="e.g. 0.16mm (default: 0.20mm Standard)")
    pr.add_argument("--filament", help="e.g. 'Anycubic PETG' (default: Anycubic PLA)")
    be = sub.add_parser("bench", help="the Test Bench: flash the board and listen to it")
    be.add_argument("action", nargs="?", default="ports", choices=["ports", "flash", "listen"])
    be.add_argument("--port", help="the serial port, e.g. COM5 (default: the first found)")
    be.add_argument("--seconds", type=float, default=10.0, help="listen: how long")
    be.add_argument("--baud", type=int, help="listen: the speed (default: platformio.ini's, or 115200)")
    au = sub.add_parser("audio", help="Audio: audiobooks from stories, SD cards, the listening shelf")
    au.add_argument("action", nargs="?", default="list", choices=["list", "narrate", "card"])
    au.add_argument("name", nargs="?", help="narrate: the story; card: the card's name")
    au.add_argument("files", nargs="*", help="card: the sounds, in order")
    mu = sub.add_parser("music", help="the Music Room: play, cast, playlists")
    mu.add_argument("action", nargs="?", default="list", choices=["list", "play", "cast", "save"])
    mu.add_argument("names", nargs="*",
                    help="tracks, artists, albums or a playlist; save: the playlist's name first")
    mu.add_argument("--to", help="the Chromecast's name, when there is more than one")
    gm = sub.add_parser("games", help="Gaming: your retro games and their emulators")
    gm.add_argument("action", nargs="?", default="list", choices=["list", "play", "emulators"])
    gm.add_argument("name", nargs="?", help="the game to play")
    gm.add_argument("--window", action="store_true", help="play in a window, not full screen")

    bk = sub.add_parser("backup", help="back up your work by hand; list or check backups")
    bk.add_argument("action", nargs="?", default="make", choices=["make", "list", "check"])
    bk.add_argument("file", nargs="?", help="the backup to check")
    bk.add_argument("--to", help="the folder for backups (default ~/nemo-backups)")

    a = sub.add_parser("admin", help="safety parameters and admin access")
    a.add_argument("action", choices=["init", "login", "logout", "show",
                                      "set", "unset", "history", "verify"])
    a.add_argument("key", nargs="?")
    a.add_argument("value", nargs="?")
    a.add_argument("--username")
    a.add_argument("--force", action="store_true")
    a.add_argument("--limit", type=int, default=20)

    lk = sub.add_parser("lock", help="boot-chain tamper detection")
    lk.add_argument("action", choices=["status", "baseline", "check",
                                       "unlock"])
    lk.add_argument("--force", action="store_true",
                    help="arm without disk encryption (proves little)")
    lk.add_argument("--note", default="")

    cl = sub.add_parser("clone", help="stage a clean copy for a clone image")
    cl.add_argument("dest")

    ms = sub.add_parser("master", help="signed safety floor documents")
    ms.add_argument("action", choices=["status", "apply"])
    ms.add_argument("document", nargs="?")

    mt = sub.add_parser("maint", help="maintenance: halt, reset, diagnose")
    mt.add_argument("action", choices=["status", "apply", "diagnose"])
    mt.add_argument("document", nargs="?")
    mt.add_argument("--out", help="where to write the diagnostic bundle")
    mt.add_argument("--allow-fixed", action="store_true",
                    help=argparse.SUPPRESS)

    args = ap.parse_args(argv)
    cfg = Config.load(args.config)
    handler = {"doctor": cmd_doctor, "mode": cmd_mode, "new": cmd_new,
               "run": cmd_run, "check": cmd_check, "parts": cmd_parts,
               "status": cmd_status, "admin": cmd_admin,
               "lock": cmd_lock, "maint": cmd_maint,
               "master": cmd_master, "clone": cmd_clone,
               "draft": cmd_draft, "gui": cmd_gui,
               "power": cmd_power, "fix": cmd_fix, "offline": cmd_offline, "eval": cmd_eval, "second": cmd_second, "pcb": cmd_pcb, "footprint": cmd_footprint,
               "datasheet": cmd_datasheet, "review": cmd_review,
               "part": cmd_part, "store": cmd_store, "backup": cmd_backup,
               "clinic": cmd_clinic, "theatre": cmd_theatre, "games": cmd_games,
               "music": cmd_music, "audio": cmd_audio, "bench": cmd_bench,
               "print": cmd_print, "guide": cmd_guide, "film": cmd_film, "studio": cmd_studio,
               "home": cmd_home, "comms": cmd_comms, "update": cmd_update, "wood": cmd_wood,
               "science": cmd_science,
               "staff": cmd_staff, "times": cmd_times, "lookup": cmd_lookup,
               "archive": cmd_archive, "queue": cmd_queue, "model": cmd_model,
               "test": cmd_test, "ahead": cmd_ahead,
               "story": cmd_story, "credits": cmd_credits,
               "render": cmd_render, "concept": cmd_concept}[args.cmd]

    # Every command passes the lockdown gate first. Recovery commands are
    # exempt, or a locked machine could never be unlocked.
    try:
        _lock(cfg).gate(args.cmd)
        _maint().gate(args.cmd)
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        return handler(args, cfg)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except ModelCallFailed as exc:
        print(str(exc), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
