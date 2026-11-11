"""Hardware and toolchain diagnostics.

Written for one machine: a Fujitsu Lifebook AH531 running Windows 11 on a
bypass install. That configuration has five failure modes that all present
as "Nemo is slow" and are actually configuration:

  1. llama.cpp built for AVX2, which Sandy Bridge does not have
  2. no graphics driver at all, so KiCad and FreeCAD get no OpenGL
  3. Windows 11 eating 3+ GB before anything useful loads
  4. a single memory stick, halving bandwidth on a memory-bound workload
  5. a thermally throttled CPU in a fourteen-year-old chassis

This module finds all five and says so plainly.

On another machine (2026-11-04: a desktop with an RTX 3050) the laptop's
facts are not stated as if they were this machine's: what is said about
Sandy Bridge, its graphics and its temperature is said only on a CPU
without AVX2, and the machine profile and GPU are reported
(nemo/machine.py).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .platform_probe import (IS_WINDOWS, basic_display_adapter, cpu_flags,
                             cpu_model, cpu_threads, display_adapter,
                             mem_available_mb, mem_total_mb, memory_sticks,
                             mesa_installed, os_label, windows_build)

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"

MODERN_ISA = ("avx2", "fma", "avx512f")

# Where KiCad and FreeCAD usually land on Windows, for the Mesa check.
WIN_APP_DIRS = [
    Path(r"C:\Program Files\KiCad\9.0\bin"),
    Path(r"C:\Program Files\KiCad\bin"),
    Path(r"C:\Program Files\FreeCAD 1.0\bin"),
    Path(r"C:\Nemo\tools\kicad\bin"),
]


@dataclass
class Finding:
    status: str
    title: str
    detail: str

    def line(self) -> str:
        mark = {OK: "[ ok ]", WARN: "[warn]",
                FAIL: "[FAIL]", INFO: "[    ]"}[self.status]
        return f"{mark} {self.title}\n       {self.detail}"


def llama_binary_runs(binary: str = "llama-server") -> tuple[bool, str]:
    """Does the installed binary actually start on this CPU?

    This replaces an earlier byte-scanning heuristic that searched the
    executable for the string "AVX2". That heuristic was wrong in the worst
    possible direction: llama.cpp prints a feature table reading
    "AVX = 1 | AVX2 = 0 | ...", so a correctly-built AVX-only binary
    contains the literal string AVX2 and was reported as a mismatch. The
    doctor would then tell the user to rebuild a binary that was already
    right.

    Executing it is the only honest test. A build compiled for an
    unavailable instruction set dies with SIGILL, which is exactly the
    signal we want and cannot be inferred from the file's contents.
    """
    path = shutil.which(binary) or shutil.which(binary + ".exe")
    if not path:
        return False, "not installed"
    try:
        proc = subprocess.run([path, "--version"], capture_output=True,
                              text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False, "did not respond to --version within 30s"
    except OSError as exc:
        return False, str(exc)

    # SIGILL surfaces as -4 on POSIX and 0xC000001D on Windows.
    if proc.returncode in (-4, 132, -1073741795, 3221225501):
        return False, ("illegal instruction -- this binary was built for "
                       "an instruction set this CPU does not have")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, (tail[-1] if tail else f"exited {proc.returncode}")
    return True, (proc.stdout or proc.stderr or "").strip().splitlines()[0] \
        if (proc.stdout or proc.stderr).strip() else "starts cleanly"


TOOLS = [
    ("kicad-cli", "schematic rules and netlist export", True),
    ("pio", "firmware compile gate", True),
    ("git", "per-stage commits so a bad run is one reset away", True),
    ("dot", "graphviz, required by WireViz", True),
    ("freecad", "optional: hand edits and still renders", False),
]


def run() -> list[Finding]:
    f: list[Finding] = []
    flags = cpu_flags()

    f.append(Finding(INFO, "System",
                     f"{os_label()} on {cpu_model()} ({cpu_threads()} threads)"))
    # The laptop's own facts (Sandy Bridge, its graphics, its fan) are said
    # only on a CPU like it: one without AVX2. They were said everywhere.
    old_cpu = bool(flags) and "avx2" not in flags

    from .machine import gpus, profile
    from .config import Config as _ProfileCfg
    kind, why = profile(_ProfileCfg.load())
    f.append(Finding(INFO, f"Machine profile: {kind}",
                     why + (". Modes run on the GPU (config modes_desktop)."
                            if kind == "desktop" else
                            ". Modes run on the CPU (config modes / modes_windows).")))

    # --- Windows 11 on unsupported silicon ----------------------------
    if IS_WINDOWS:
        ver, build = windows_build()
        if "sse4_2" in flags:
            f.append(Finding(
                OK, "Windows 11 boot requirements",
                f"SSE4.2 and POPCNT present, so {ver or '24H2'} and later "
                "will keep booting. That requirement only excludes "
                "pre-Nehalem chips" + (", and this is Sandy Bridge." if old_cpu else ".")))
        elif flags:
            f.append(Finding(
                FAIL, "No SSE4.2",
                "Windows 11 24H2 and later will not boot without it, and it "
                "cannot be bypassed. You are stuck on 23H2."))
        if old_cpu:
            f.append(Finding(
                WARN, "Unsupported configuration",
                "Windows 11 on a 2nd-gen Core CPU is a bypass install. It runs, "
                "but feature updates need the bypass reapplying each time, and "
                "no vendor ships drivers for this hardware any more. Keep a "
                "full disk image before every feature update."))

    # --- the AVX2 trap ------------------------------------------------
    has_avx2 = "avx2" in flags
    # The same location 'nemo mode' uses. The doctor used to search PATH
    # only, and on Windows the engine lives in C:\\Nemo\\engine, off PATH --
    # so it reported llama.cpp missing while models launched from it.
    from .config import Config
    from .platform_probe import find_tool
    configured = Config.load().get("paths.llama_server", "llama-server")
    engine = (configured if Path(str(configured)).is_file()
              else find_tool("llama-server") or configured)
    runs, detail = llama_binary_runs(engine)
    if detail == "not installed":
        f.append(Finding(WARN, "llama.cpp", "not installed yet"))
    elif not runs:
        f.append(Finding(
            FAIL, "llama.cpp will not start", detail + ". " +
            ("Use the unified CPU build (llama-*-bin-win-cpu-x64.zip) and "
             "keep every DLL from the zip beside llama-server.exe. It picks "
             "the right code path for this CPU at runtime."
             if IS_WINDOWS else
             "Rebuild with build-llama.sh, which selects the instruction "
             "set from /proc/cpuinfo.")))
    else:
        f.append(Finding(OK, "llama.cpp runs on this CPU", detail[:70]))

    if has_avx2:
        f.append(Finding(OK, "AVX2", "present; stock llama.cpp builds work"))
    elif "avx" in flags:
        f.append(Finding(
            OK, "AVX-only build",
            "No AVX2 on this CPU and none in the binary. Correct here."))
    elif "sse4_2" in flags:
        # Sandy Bridge Celeron and Pentium have AVX fused off entirely,
        # along with Turbo and hyper-threading. An AVX build faults on them
        # exactly as an AVX2 build faults on a Core i5.
        f.append(Finding(
            INFO, "No AVX: a Sandy Bridge Pentium or Celeron",
            "Intel switched AVX, Turbo Boost and hyper-threading off on these "
            "parts. " + ("Nothing to do: the llama.cpp package NemoDoc installs "
                         "includes an SSE4.2 backend and chooses it on its own."
                         if IS_WINDOWS else
                         "nemodoc builds llama.cpp without AVX for this CPU.")
            + " Expect about half the speed of a Core i5 of the same "
              "generation; Talk mode is the practical everyday choice."))
    else:
        f.append(Finding(INFO, "Instruction sets",
                         "Could not determine. Verify with CPU-Z before "
                         "blaming performance on the hardware."))

    # --- graphics, which on Windows 11 is the real problem -------------
    if IS_WINDOWS:
        name, drv = display_adapter()
        if basic_display_adapter():
            mesa_where = [d for d in WIN_APP_DIRS
                          if d.exists() and mesa_installed(d)]
            if mesa_where:
                f.append(Finding(
                    OK, "Software OpenGL in place",
                    f"Windows is using {name}, so there is no hardware "
                    "OpenGL -- but Mesa is installed beside " +
                    ", ".join(d.name for d in mesa_where) +
                    ". KiCad and FreeCAD will render on the CPU. Slow, but "
                    "it works."))
            else:
                f.append(Finding(
                    FAIL, "No OpenGL at all",
                    f"Windows fell back to {name}. Intel never shipped a "
                    "Windows 11 driver for HD Graphics 3000, and there is "
                    "no way to get one. KiCad's accelerated canvas and "
                    "FreeCAD's 3D view will not work. Fix: run "
                    "install/windows/setup-mesa.ps1 to drop Mesa's software "
                    "opengl32.dll beside each application."))
        elif name and "intel" in name.lower() and old_cpu:
            f.append(Finding(
                WARN, "Graphics",
                f"{name} (driver {drv}). If this is an inf-modded Intel "
                "driver it caps at OpenGL 3.1, which KiCad accepts and "
                "FreeCAD mostly accepts. Watch for viewport corruption."))
        elif name:
            f.append(Finding(OK, "Graphics", f"{name} (driver {drv})"))
    elif old_cpu:
        f.append(Finding(
            INFO, "Graphics",
            "On Linux, Mesa's Crocus driver gives HD 3000 a real OpenGL 3.3 "
            "context -- better than anything available on Windows."))

    cards = gpus()
    if cards:
        from .machine import cuda_engine
        card = max(cards, key=lambda g: g.total_mib)
        engine_gpu = cuda_engine()
        f.append(Finding(
            OK if kind == "desktop" else INFO, "GPU compute",
            f"{card.name}, {card.total_mib} MiB. " +
            ("The models run on it, every layer offloaded, with the CUDA engine at "
             f"{engine_gpu}." if kind == "desktop" else
             ("Not used: " + why + ".") if engine_gpu or "CUDA" not in why else
             "Not used yet: " + why + ".")))
    else:
        f.append(Finding(
            INFO, "GPU compute",
            ("Not used, on any OS. Sandy Bridge graphics is Gen6: no Vulkan, no "
             "OpenVINO GPU plugin, no DirectML. A GeForce GT 525M, if fitted, is "
             "Fermi and unsupported by every current framework.")
            if old_cpu else
            "No NVIDIA GPU found, so the models run on the CPU."))

    # --- memory -------------------------------------------------------
    total, avail = mem_total_mb(), mem_available_mb()
    overhead = total - avail
    f.append(Finding(INFO, "Memory",
                     f"{total} MB total, {avail} MB available "
                     f"({overhead} MB in use right now)"))

    if total and total < 5000:
        f.append(Finding(
            FAIL, "Not enough memory to work with",
            f"{total} MB installed. "
            + ("Windows alone wants around 3.2 GB, "
               if IS_WINDOWS else
               "Even a trimmed desktop wants around 1.2 GB, ")
            + f"leaving roughly {max(0, avail)} MB -- not enough for a 1B "
            "model and KiCad together. A matched pair of 4 GB DDR3-1333 "
            "SO-DIMMs costs about 20 euro and is not an optimisation here, "
            "it is the difference between the project working and not."))
    elif total and total > 12000 and kind == "desktop":
        f.append(Finding(
            OK, f"{round(total / 1024)} GB installed",
            "The model is on the GPU, so it holds under 1 GB of this; KiCad, "
            "FreeCAD and a browser have the rest."))
    elif total and total > 12000:
        # The 15000 branch below this one could never be reached (it was
        # tested second); one finding for both, as the advice was the same.
        f.append(Finding(
            OK, f"{round(total / 1024)} GB installed",
            "Enough to hold a model, KiCad, FreeCAD and a browser at once, "
            "so mode switching is optional rather than mandatory. Use "
            "'nemo mode roomy' for a 16k context. Extra memory buys context, "
            "not speed: tokens come out as fast as memory bandwidth allows."))
    elif total and total < 7000:
        f.append(Finding(
            WARN, "Under 8 GB",
            f"{total} MB installed. Use 'nemo mode tiny' (a 1B model); the "
            "design and build modes will not load. Filling both slots with "
            "4 GB sticks fixes this and doubles memory bandwidth at the "
            "same time."))

    from .modes import current as _current_mode
    from .platform_probe import process_rss_mb
    st = _current_mode()
    model_mb = process_rss_mb(st.pid) if st.running else 0
    if model_mb:
        f.append(Finding(INFO, f"Nemo's model ({st.name} mode)",
                         f"{model_mb} MB of the memory in use is Nemo's own "
                         f"{st.model} model. 'nemo mode off', or Off in the "
                         "window, gives it back."))
    others = overhead - model_mb
    # The laptop's worry: on 8 GB, what Windows holds is what the model
    # cannot have. With 12 GB or more it is not worth a warning.
    if IS_WINDOWS and total and total <= 12000 and others > 2800:
        f.append(Finding(
            WARN, "Memory used by Windows and open programs",
            f"{others} MB is in use by Windows and whatever else is open"
            + (f", not counting Nemo's {model_mb} MB model" if model_mb else "")
            + ". Open programs count -- a browser alone can take a gigabyte "
            "or more; Task Manager, sorted by Memory, shows what. A trimmed XFCE "
            "install idles around 1200 MB. If you stay on Windows, trim.ps1 "
            "in the NemoWin folder disables Search indexing, Widgets and "
            "startup apps."))

    # zram (owner, 2026-11-04): NemoIso makes compressed swap in RAM at boot,
    # its only swap. Said, so a booted stick shows whether it is working.
    if not IS_WINDOWS:
        from .platform_probe import zram_swap_mb
        zram = zram_swap_mb()
        if zram:
            f.append(Finding(OK, "zram swap",
                             f"{zram} MB of compressed swap in RAM: pages the system would "
                             "drop are kept compressed instead."))
        elif total and total <= 12000:
            f.append(Finding(INFO, "No zram swap",
                             "No compressed swap in RAM. NemoIso sets it up at boot "
                             "(zram-tools); an image built before 2026-11-04 has none."))

    sticks = memory_sticks()
    if not sticks:
        f.append(Finding(
            INFO, "Memory channels",
            "Could not read the DIMM layout. Confirm two populated slots by "
            "hand -- single channel roughly halves token throughput."))
    elif len(sticks) == 1:
        f.append(Finding(
            WARN, "Single channel",
            f"Only one DIMM populated ({sticks[0]}). A matched second stick "
            "is the cheapest speedup available on this machine, and it is "
            "roughly a 2x difference."))
    else:
        f.append(Finding(OK, "Dual channel",
                         f"{len(sticks)} DIMMs: {', '.join(sticks)}"))

    # --- thermals (Linux only; Windows needs vendor WMI that is absent) -
    if not IS_WINDOWS:
        temps = []
        for t in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
            try:
                temps.append(int(t.read_text(encoding="utf-8", errors="replace").strip()) / 1000)
            except (OSError, ValueError):
                pass
        if temps:
            hottest = max(temps)
            status = WARN if hottest > 80 else OK
            f.append(Finding(
                status, "Temperature", f"{hottest:.0f} C at idle. " +
                ("Clean the fan and repaste before blaming the software."
                 if status == WARN else "Healthy at idle.")))
    elif old_cpu:
        f.append(Finding(
            INFO, "Temperature",
            "Not readable without vendor WMI, which Fujitsu no longer "
            "ships for this model. Use HWiNFO64 to watch it under load: a "
            "fourteen-year-old laptop with a dusty fan can lose half its "
            "speed to throttling."))
    else:
        f.append(Finding(
            INFO, "Temperature",
            "Not read on Windows. HWiNFO64 shows it under load."))

    # --- parts library -----------------------------------------------
    from .config import Config as _Cfg
    from .parts import BUNDLED, PartsLibrary
    _extra = _Cfg.load().get("paths.parts")
    _lib = PartsLibrary.load(*([Path(str(_extra)).expanduser()] if _extra else []))
    n = len(_lib)
    for _err in _lib.errors:
        f.append(Finding(WARN, "A part could not be loaded",
                         f"{_err}. That part is skipped until it is fixed."))
    if n == 0:
        f.append(Finding(
            FAIL, "Parts library is empty",
            f"Nothing found at {BUNDLED}. The installation is incomplete; "
            "every design will fail at stage 2. Reinstall from the "
            "distribution folder."))
    else:
        f.append(Finding(OK, "Parts library", f"{n} parts"))

    # --- toolchain ----------------------------------------------------
    from .platform_probe import find_tool
    for name, why, required in TOOLS:
        hit = find_tool(name)
        if hit and name == "kicad-cli":
            from .checks.runners import KICAD_MIN_FOR_RULES, kicad_version
            ver = kicad_version(hit)
            if ver and ver < KICAD_MIN_FOR_RULES:
                f.append(Finding(
                    FAIL, f"KiCad {'.'.join(map(str, ver))} is too old",
                    "Electrical and board rule checks need KiCad 8 or later; "
                    "this version has no command-line ERC or DRC. Every "
                    "schematic would go unchecked. Ubuntu 24.04 ships 7.0 -- "
                    "use the KiCad PPA, or Debian 13's own package."))
                continue
        if hit:
            on_path = shutil.which(name) or shutil.which(name + ".exe")
            note = why if on_path else f"{why} -- found at {hit}, not on PATH"
            f.append(Finding(OK, name, note))
        else:
            # D206: an optional tool is a fact, not a fault. FreeCAD is on
            # no image, and the Doctors listed it as worth a look.
            f.append(Finding(FAIL if required else INFO, f"{name} missing",
                             f"needed for: {why}.{missing_hint(name, IS_WINDOWS)}"))
    return f


def missing_hint(name: str, windows: bool) -> str:
    """What to do about a tool that is not there, on the system it is read
    on. '' where there is nothing useful to add."""
    if name == "kicad-cli" and windows:
        return (" KiCad installs to a folder named for its version "
                "(C:\\Program Files\\KiCad\\10.0\\bin) and does "
                "not add itself to PATH. If it is installed somewhere "
                "unusual, set NEMO_KICAD_CLI to the full path.")
    if name == "kicad-cli":
        # D173: the Windows advice was given on Linux too, where it was
        # read on the first NemoIso image to boot.
        return (" On Debian: sudo apt install kicad. If it is installed "
                "somewhere unusual, set NEMO_KICAD_CLI to the full path.")
    if name == "pio" and not windows:
        return (" It is PlatformIO: /opt/nemo/venv/bin/pip install platformio, "
                "with a network.")
    return ""


def report() -> tuple[str, int]:
    findings = run()
    text = "\n".join(x.line() for x in findings)
    fails = sum(1 for x in findings if x.status == FAIL)
    return text, fails
