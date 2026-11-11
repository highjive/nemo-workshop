"""Tier 0 checks that shell out to real engineering tools.

Every runner degrades to SKIP with a useful message when its tool is absent,
so the pipeline stays usable on a machine where you have not installed
everything yet. A SKIP is never silently treated as a PASS.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .deterministic import FAIL, PASS, SKIP, Result


def _run(cmd: list[str], cwd: Path | None = None,
         timeout: int = 600, env: dict | None = None) -> tuple[int, str, str]:
    try:
        # errors="replace": a tool that prints one byte the console code
        # page cannot decode must not turn a check into a traceback.
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           errors="replace", timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except OSError as exc:
        return 127, "", str(exc)


def _kicad() -> str | None:
    from ..platform_probe import find_tool
    return find_tool("kicad-cli", os.environ.get("NEMO_KICAD_CLI"))


def kicad_version(kicad: str | None = None) -> tuple[int, ...]:
    """(major, minor, patch) of kicad-cli, or () if it cannot be read."""
    kicad = kicad or _kicad()
    if not kicad:
        return ()
    rc, so, _ = _run([kicad, "version"], timeout=30)
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", so or "")
    return tuple(int(x) for x in m.groups() if x) if (rc == 0 and m) else ()


# Command-line ERC and DRC arrived in KiCad 8. KiCad 7 -- which is what
# Ubuntu 24.04 LTS ships -- has only 'sch export', and an earlier revision
# of the ERC check reported PASS against it: the command failed, no report
# was written, and zero violations in a report that did not exist was read
# as a clean schematic.
KICAD_MIN_FOR_RULES = (8, 0)


def _missing(tool: str, why: str, how: str) -> Result:
    return Result(tool, SKIP, f"{tool} not installed -- {why}", [how])


# --------------------------------------------------------------------
# KiCad
# --------------------------------------------------------------------

def _skidl_env() -> tuple[dict | None, Path | None]:
    """The environment a SKiDL script needs, and the symbols folder found.

    D118, from the first real run (SKiDL 2.3.0, KiCad 10.0.6, Windows 11):
    SKiDL finds KiCad's symbol libraries only through KICAD<n>_SYMBOL_DIR.
    Nothing sets that. The KiCad installer does not, and neither did Nemo,
    so the first Part() in any script failed with "Can't open file: Device".

    Which <n> SKiDL reads is fixed by the SKiDL release, not by the KiCad
    that is installed (2.3.0 reads KICAD10 whatever is on the machine), so
    every variant is pointed at the one installation there is. A value the
    user has already set is left alone.
    """
    kicad = _kicad()
    if not kicad:
        return None, None
    symbols = Path(kicad).resolve().parent.parent / "share" / "kicad" / "symbols"
    if not symbols.is_dir():
        return None, None
    env = dict(os.environ)
    for name in ["KICAD_SYMBOL_DIR"] + [f"KICAD{n}_SYMBOL_DIR" for n in range(6, 13)]:
        env.setdefault(name, str(symbols))
    return env, symbols


def generate_schematic(script: Path, dest: Path, timeout: int = 600) -> Result:
    """Run a model-written SKiDL script and get its schematic to `dest`.

    D104: nothing ever executed this script. The stage that writes it said,
    in its own comment, "SKiDL generates the netlist" -- but generating
    only happens by running the script, and nothing did, so erc() always
    found no schematic and SKIPped, which counts as passing. Every
    electrical stage, for every project, has been reporting a checked
    design that was never actually checked.

    SKiDL's own defaults are not trustworthy enough to assume: with no
    arguments, generate_netlist() names its output after the invoking
    script (schematic.py -> schematic.net, not whatever the caller wants),
    and generate_schematic() has real, version-dependent history of both
    file-naming changes and outright crashes on ordinary circuits. Rather
    than hardcode assumptions about a library not available to verify
    against here, this runs the script as its own process (so a runaway
    or malformed model output cannot hang the pipeline, only this one
    check, and only up to `timeout`), then looks at what the script's own
    directory actually holds afterward and moves whichever .kicad_sch
    appeared into place -- correct regardless of the installed SKiDL
    version's exact naming behaviour.
    """
    if not script.exists():
        return Result("schematic", FAIL, f"no script at {script}")
    workdir = script.parent
    before = set(workdir.glob("*.kicad_sch"))
    env, symbols = _skidl_env()
    rc, out, err = _run([sys.executable, str(script)], cwd=workdir,
                        timeout=timeout, env=env)
    if rc == 124:
        return Result("schematic", FAIL,
                      f"the SKiDL script did not finish within {timeout}s",
                      ["a runaway or pathologically slow script -- no "
                       "schematic was produced"])
    if rc != 0:
        tail = (err or out).strip().splitlines()[-8:]
        if symbols is None and "Can't open file" in (err or out):
            tail.append("KiCad's symbol libraries were not found beside "
                        "kicad-cli, so SKiDL could not load a part. Set "
                        "KICAD<version>_SYMBOL_DIR to KiCad's symbols folder.")
        return Result("schematic", FAIL,
                      f"the SKiDL script exited with an error (code {rc})",
                      tail or ["no output was captured"])
    after = set(workdir.glob("*.kicad_sch"))
    made = sorted(after - before or after, key=lambda p: p.stat().st_mtime)
    if not made:
        return Result("schematic", FAIL,
                      "the script ran without error but produced no "
                      ".kicad_sch file",
                      ["check that the script actually calls "
                       "generate_schematic()"])
    produced = made[-1]
    if produced != dest:
        dest.parent.mkdir(parents=True, exist_ok=True)
        produced.replace(dest)
    return Result("schematic", PASS, f"generated {dest.name}")


def generate_enclosure(script: Path, dest: Path, timeout: int = 900) -> Result:
    """Run a model-written CadQuery script and check it left a mesh at `dest`.

    D131: nothing ever executed this script either. D104 found that the
    schematic script was written and never run; the enclosure step had the
    same hole and kept it. On the real laptop the step wrote housing.py,
    found no housing.stl, skipped all three of its checks for want of a
    mesh, and recorded the step as passed. CadQuery was not even installed.

    Run as its own process, in the script's own folder, so a runaway
    script costs this one check and no more.

      no CadQuery       SKIP, saying so: a missing tool is not the model's
                        fault and not a pass
      the script fails  FAIL, with the end of its output
      runs, no mesh     FAIL
    """
    if not script.exists():
        return Result("enclosure_script", FAIL, f"no script at {script}")
    dest.unlink(missing_ok=True)       # a mesh from an earlier run proves nothing
    rc, out, err = _run([sys.executable, str(script)], cwd=script.parent, timeout=timeout)
    text = (err or "") + (out or "")
    if rc == 124:
        return Result("enclosure_script", FAIL,
                      f"the enclosure script did not finish within {timeout}s")
    if rc != 0:
        if re.search(r"No module named ['\"](cadquery|OCP)", text):
            return Result("enclosure_script", SKIP,
                          "CadQuery is not installed, so the enclosure script "
                          "was written but could not be run",
                          ["There is no enclosure mesh. Install it with: "
                           "pip install cadquery  (a large download)"])
        tail = text.strip().splitlines()[-8:]
        return Result("enclosure_script", FAIL,
                      f"the enclosure script exited with an error (code {rc})",
                      tail or ["no output was captured"])
    if not dest.exists():
        made = sorted(p.name for p in script.parent.glob("*.stl"))
        return Result("enclosure_script", FAIL,
                      f"the script ran without error but wrote no {dest.name}",
                      [f"it wrote {', '.join(made)}" if made else
                       "check that it ends by exporting housing.stl"])
    return Result("enclosure_script", PASS, f"generated {dest.name}")


def erc(schematic: Path) -> Result:
    """Electrical rules check. Unconnected pins, power conflicts."""
    kicad = _kicad()
    if not kicad:
        return _missing("erc", "schematic is unchecked",
                        "install KiCad, or set NEMO_KICAD_CLI to kicad-cli")
    if not schematic.exists():
        return Result("erc", SKIP, f"no schematic at {schematic}")

    ver = kicad_version(kicad)
    if ver and ver < KICAD_MIN_FOR_RULES:
        return Result("erc", SKIP,
                      f"KiCad {'.'.join(map(str, ver))} has no command-line "
                      "ERC; the schematic is unchecked",
                      ["install KiCad 8 or later (the KiCad PPA on Ubuntu, "
                       "or Debian 13's own package)"])

    out = schematic.parent / "erc-report.json"
    # A report left by an earlier run must not be mistaken for this one.
    out.unlink(missing_ok=True)
    rc, so, se = _run([kicad, "sch", "erc",
                       "--format", "json", "--output", str(out),
                       "--severity-error", "--severity-warning",
                       "--exit-code-violations", str(schematic)])
    if rc == 127:
        return Result("erc", SKIP, se)

    # The verdict comes from the report, never from its absence. No report
    # means ERC did not run, whatever the exit code says.
    if not out.exists():
        tail = [ln for ln in (se or so).splitlines() if ln.strip()][-2:]
        return Result("erc", FAIL, "ERC did not run; no report was written",
                      tail or [f"kicad-cli exited {rc}"])

    violations = []
    try:
        doc = json.loads(out.read_text(encoding="utf-8", errors="replace"))
        for sheet in doc.get("sheets", []):
            for v in sheet.get("violations", []):
                violations.append(f"[{v.get('severity', '?')}] "
                                  f"{v.get('description', '')}")
    except (json.JSONDecodeError, OSError) as exc:
        return Result("erc", FAIL, "ERC report could not be read", [str(exc)])

    errors = [v for v in violations if v.startswith("[error")]
    if errors:
        return Result("erc", FAIL, f"{len(errors)} error(s)", violations[:20])
    if violations:
        return Result("erc", PASS, f"{len(violations)} warning(s)",
                      violations[:20])
    return Result("erc", PASS, "clean")


def drc(board: Path) -> Result:
    """Design rules check. Only relevant once there is a PCB."""
    if not board.exists():
        return Result("drc", SKIP, "no PCB in this project (harness only)")
    kicad = _kicad()
    if not kicad:
        return _missing("drc", "board is unchecked",
                        "install KiCad, or set NEMO_KICAD_CLI to kicad-cli")

    ver = kicad_version(kicad)
    if ver and ver < KICAD_MIN_FOR_RULES:
        return Result("drc", SKIP,
                      f"KiCad {'.'.join(map(str, ver))} has no command-line "
                      "DRC; the board is unchecked",
                      ["install KiCad 8 or later"])
    out = board.parent / "drc-report.json"
    out.unlink(missing_ok=True)
    rc, so, se = _run([kicad, "pcb", "drc",
                       "--format", "json", "--output", str(out),
                       "--severity-error", "--exit-code-violations",
                       str(board)])
    if rc == 127:
        return Result("drc", SKIP, se)
    if not out.exists():
        tail = [ln for ln in (se or so).splitlines() if ln.strip()][-2:]
        return Result("drc", FAIL, "DRC did not run; no report was written",
                      tail or [f"kicad-cli exited {rc}"])
    try:
        doc = json.loads(out.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError) as exc:
        return Result("drc", FAIL, "DRC report could not be read", [str(exc)])
    found = [f"[{v.get('severity', '?')}] {v.get('description', '')}"
             for v in doc.get("violations", [])]
    found += [f"[unconnected] {v.get('description', '')}"
              for v in doc.get("unconnected_items", [])]
    if found:
        return Result("drc", FAIL, f"{len(found)} violation(s)", found[:20])
    return Result("drc", PASS, "clean")


def netlist_nets(schematic: Path) -> set[str]:
    """Export the netlist and return the set of net names."""
    kicad = _kicad()
    if not schematic.exists() or not kicad:
        return set()
    out = schematic.parent / "netlist.net"
    rc, _, _ = _run([kicad, "sch", "export", "netlist",
                     "--output", str(out), str(schematic)])
    if rc != 0 or not out.exists():
        return set()
    return parse_net_names(out.read_text(encoding="utf-8", errors="replace"))


def netlist_groups(schematic: Path) -> tuple[list[tuple[str, set]] | None, str]:
    """The schematic's nets as (name, {(component value, pin number)}),
    from KiCad's XML netlist. Nets with one pin on them (a pin marked not
    connected) are left out. (None, why) if it could not be read.

    Read on the AH531 from KiCad 10.0.6 (2026-10-20): <comp ref="J1"> with
    <value>, and <net name=...> holding <node ref= pin=> with pin NUMBERS;
    a PWR_FLAG does not appear as a node.
    """
    import xml.etree.ElementTree as ET
    kicad = _kicad()
    if not kicad:
        return None, "kicad-cli is not installed"
    if not schematic.exists():
        return None, f"no schematic at {schematic}"
    out = schematic.parent / "netlist.xml"
    out.unlink(missing_ok=True)
    rc, so, se = _run([kicad, "sch", "export", "netlist", "--format", "kicadxml",
                       "--output", str(out), str(schematic)])
    if rc != 0 or not out.exists():
        tail = [ln for ln in (se or so or "").splitlines() if ln.strip()][-1:]
        return None, "kicad-cli could not export the netlist" + (f": {tail[0]}" if tail else "")
    try:
        root = ET.parse(out).getroot()
    except (ET.ParseError, OSError) as exc:
        return None, f"the netlist could not be read: {exc}"
    value = {c.get("ref"): (c.findtext("value") or "").strip()
             for c in root.iter("comp")}
    groups = []
    for net in root.iter("net"):
        ends = {(value.get(n.get("ref"), n.get("ref")), str(n.get("pin")))
                for n in net.iter("node")}
        if len(ends) > 1:
            groups.append((net.get("name", ""), ends))
    return groups, ""


# A net's own name is the (name ...) that directly follows its (code ...).
# Component and library names never follow a code, so they do not match.
_NET_NAME = re.compile(r'\(net\s*\(code\s+"?\d+"?\)\s*\(name\s+"((?:[^"\\]|\\.)*)"')


def parse_net_names(netlist: str) -> set[str]:
    """Net names from a KiCad netlist, whichever way it is laid out.

    D124: the reader assumed one net per line, `(net (code "1") (name "X")`,
    which is how KiCad wrote it up to version 9. KiCad 10 puts `(net`,
    `(code "1")` and `(name "X")` on three lines. Run on the real laptop
    against KiCad 10.0.6 it returned no nets at all for a schematic that
    has 52, and an empty set is also what "could not export" returns, so
    nothing distinguished the two.
    """
    return {m.group(1) for m in _NET_NAME.finditer(netlist)}


# --------------------------------------------------------------------
# Firmware
# --------------------------------------------------------------------

def compile_firmware(project: Path, env: str | None = None) -> Result:
    """The firmware either builds or it does not.

    This is the single most valuable check in the stack: it turns firmware
    generation from a guess into a loop with a real error signal.
    """
    if not (project / "platformio.ini").exists():
        return Result("compile", SKIP, "no platformio.ini")
    from ..platform_probe import find_tool
    pio = find_tool("pio")
    if not pio:
        return _missing("compile", "firmware is unverified",
                        "pip install platformio")

    cmd = [pio, "run"]
    if env:
        cmd += ["-e", env]
    rc, so, se = _run(cmd, cwd=project, timeout=1800)
    log = project / "build.log"
    log.write_text(so + "\n" + se, encoding="utf-8")

    if rc == 0:
        size = [ln for ln in so.splitlines()
                if "Flash:" in ln or "RAM:" in ln]
        return Result("compile", PASS, "builds clean", size)

    errors = [ln.strip() for ln in (so + se).splitlines()
              if "error:" in ln.lower()]
    if build_tools_failed(errors):
        return Result("compile", FAIL, TOOLS_FAILED,
                      errors[:6] + [
                          "This is the compiler failing to start, not a fault in "
                          "the code, so the code was not sent back to the model.",
                          "On Windows 'CreateProcess: No such file or directory' "
                          "usually means the build command grew too long: keep "
                          "PlatformIO's folder and the project on short paths.",
                          f"Full output: {log}"])
    return Result("compile", FAIL, f"build failed (rc={rc})",
                  errors[:15] or [f"see {log}"])


TOOLS_FAILED = "the build tools could not run"
# A diagnostic about the code names a file and a line. A compiler driver
# that could not start its own back end names only itself.
_SOURCE_DIAGNOSTIC = re.compile(r"[\w./\\-]+\.\w+:\d+(:\d+)?: (fatal )?error", re.I)
_DRIVER_FAILURE = re.compile(
    r"^\S*(gcc|g\+\+|cc1plus|cc1|ld|ar|as)(\.exe)?: (fatal )?error: "
    r"(CreateProcess|cannot execute|error trying to exec|spawn|vfork)", re.I)


def build_tools_failed(error_lines: list[str]) -> bool:
    """Did the build fail because the tools could not run, rather than
    because of the code?

    D126, from the first real firmware build on the AH531: every compile
    ended `xtensa-esp32-elf-g++: error: CreateProcess: No such file or
    directory`. That line was handed to the model as an error to fix, three
    times, forty minutes in all, and the gate then blamed the electrical
    step. Run through a shorter path the same toolchain compiled, and
    reported a real mistake in the generated code.

    Only when there is a driver failure and not one diagnostic that names
    a source line. Anything else is treated as a fault in the code, as
    before.
    """
    if any(_SOURCE_DIAGNOSTIC.search(ln) for ln in error_lines):
        return False
    if any("undefined reference" in ln or "multiple definition" in ln
           for ln in error_lines):
        return False
    return any(_DRIVER_FAILURE.search(ln) for ln in error_lines)


# --------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------

def solid(stl: Path) -> Result:
    """Is the mesh a closed, manifold, printable solid?"""
    if not stl.exists():
        return Result("solid", SKIP, f"no mesh at {stl}")
    try:
        import trimesh
    except ImportError:
        return _missing("solid", "geometry is unchecked",
                        "pip install trimesh")

    try:
        mesh = trimesh.load_mesh(str(stl))
    except Exception as exc:                       # noqa: BLE001
        return Result("solid", FAIL, f"mesh will not load: {exc}")

    items = [f"{len(mesh.faces)} faces, "
             f"volume {mesh.volume / 1000:.1f} cm3"]
    problems = []
    if not mesh.is_watertight:
        problems.append("not watertight -- the slicer will produce garbage")
    if not mesh.is_winding_consistent:
        problems.append("inconsistent face winding")
    # body_count needs scipy. It is informational, so a missing library
    # must degrade this line, not crash the enclosure stage -- which is what
    # happened the first time this ran against a real install.
    try:
        if mesh.body_count > 1:
            items.append(f"{mesh.body_count} separate bodies "
                         "(fine if intentional)")
    except ImportError:
        items.append("body count unavailable (pip install scipy)")
    if problems:
        return Result("solid", FAIL, "mesh is not a valid solid",
                      problems + items)
    return Result("solid", PASS, "watertight and manifold", items)


def thickness(stl: Path, min_wall_mm: float) -> Result:
    """Approximate minimum wall check by ray casting from the surface.

    Not a substitute for the slicer, but it catches the common failure:
    a model that looks right and has 0.4 mm walls somewhere.
    """
    if not stl.exists():
        return Result("thickness", SKIP, f"no mesh at {stl}")
    try:
        import numpy as np
        import trimesh
    except ImportError:
        return _missing("thickness", "wall thickness is unchecked",
                        "pip install trimesh numpy rtree")
    import importlib.util
    if importlib.util.find_spec("rtree") is None:
        # Without this, every measurement raised inside the try below and
        # the check reported SKIP on every real install: the wall-thickness
        # gate never checked a single wall.
        return _missing("thickness", "wall thickness is unchecked",
                        "pip install rtree")

    try:
        mesh = trimesh.load_mesh(str(stl))
        if not mesh.is_watertight:
            return Result("thickness", SKIP,
                          "mesh is not watertight; fix solid first")
        n = min(2000, len(mesh.faces))
        origins = mesh.triangles_center[:n]
        normals = -mesh.face_normals[:n]
        # Rays start just inside the surface so they do not hit the face they
        # leave from. That offset is added back below: an earlier revision
        # did not, so every measurement was short by it and a wall built to
        # exactly the minimum always failed.
        offset = 1e-4
        origins = origins + normals * offset
        hits, ray_idx, _ = mesh.ray.intersects_location(
            origins, normals, multiple_hits=False)
        if len(hits) == 0:
            return Result("thickness", SKIP, "no ray intersections measured")
        dists = np.linalg.norm(hits - origins[ray_idx], axis=1) + offset
        thin = float(dists.min())
        items = [f"thinnest measured section {thin:.2f} mm "
                 f"over {len(dists)} samples"]
        # 10 microns of tolerance: far below what an FDM nozzle can resolve,
        # far above floating-point noise in the mesh.
        if thin < min_wall_mm - 0.01:
            return Result("thickness", FAIL,
                          f"{thin:.2f} mm is below the {min_wall_mm} mm "
                          "minimum", items)
        return Result("thickness", PASS, f"min {thin:.2f} mm", items)
    except Exception as exc:                       # noqa: BLE001
        return Result("thickness", SKIP, f"could not measure: {exc}")


def wireviz(yaml_path: Path) -> Result:
    """Render the harness. WireViz validates its own schema on the way."""
    if not yaml_path.exists():
        return Result("wireviz", SKIP, f"no harness at {yaml_path}")
    from ..platform_probe import find_tool
    wv = find_tool("wireviz")
    if not wv:
        return _missing("wireviz", "harness not rendered",
                        "pip install wireviz  (needs graphviz: apt install "
                        "graphviz)")
    # WireViz runs Graphviz's 'dot' by name, so it must be on the PATH of
    # WireViz's own process. Graphviz's Windows installer does not add it,
    # and finding it ourselves is not enough: the check reported dot as fine
    # while every harness render failed with ExecutableNotFound.
    dot = find_tool("dot")
    if not dot:
        return _missing("wireviz", "harness not rendered",
                        "install Graphviz (graphviz.org, or apt install graphviz)")
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(dot) + os.pathsep + env.get("PATH", "")
    rc, so, se = _run([wv, str(yaml_path)], cwd=yaml_path.parent, env=env)
    if rc != 0:
        # The reason is the LAST line of a Python traceback, not the first.
        # Reporting the head showed "Traceback (most recent call last)" and
        # nothing useful.
        lines = [ln for ln in (se or so).splitlines() if ln.strip()]
        return Result("wireviz", FAIL, "harness did not render",
                      lines[-3:] if lines else ["no output"])
    made = sorted(p.name for p in yaml_path.parent.glob(yaml_path.stem + ".*")
                  if p.name.endswith((".svg", ".png", ".html", ".bom.tsv")))
    return Result("wireviz", PASS, "rendered", made)
