"""Mode switching.

8 GB will not hold a model, KiCad, FreeCAD and a browser at once. So Nemo
runs one mode at a time and refuses to start a model that will not fit in
the memory actually available right now -- because the alternative is the
OOM killer taking KiCad down mid-edit, or twenty minutes of swap thrashing
on a SATA drive.

  design  Qwen3-4B            enclosure and schematic work
  build   Qwen2.5-Coder-3B    firmware and the compile loop
  talk    Qwen3-1.7B          conversation, routing, quick formatting
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import slotcache, storage
from .config import Config
from .doctor import llama_binary_runs
from .platform_probe import (IS_WINDOWS, cpu_flags, find_tool,
                             mem_available_mb, mem_total_mb, pid_alive,
                             process_rss_mb)

STATE = Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo")) / "mode.pid"


@dataclass
class ModeStatus:
    name: str | None
    pid: int | None
    model: str | None

    @property
    def running(self) -> bool:
        # D113: not os.kill(pid, 0). On Windows that is a Ctrl+C to the
        # console, and it succeeds for a process that has already exited.
        return pid_alive(self.pid)


def current() -> ModeStatus:
    if not STATE.exists():
        return ModeStatus(None, None, None)
    try:
        name, pid, model = STATE.read_text(encoding="utf-8", errors="replace").strip().split("\n")
        return ModeStatus(name, int(pid), model)
    except (ValueError, OSError):
        return ModeStatus(None, None, None)


def stop() -> bool:
    slotcache.clear_state(STATE.parent)
    st = current()
    if not st.running:
        STATE.unlink(missing_ok=True)
        return False
    _signal(st.pid, signal.SIGTERM)
    for _ in range(50):
        if not st.running:
            break
        time.sleep(0.1)
    else:
        # Windows has no SIGKILL; SIGTERM there is already TerminateProcess.
        _signal(st.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    STATE.unlink(missing_ok=True)
    try:
        # D191: when, so a start soon after waits for the memory to return.
        STATE.with_name(STOPPED_NAME).write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
    return True


def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except OSError:
        pass          # it went away between the check and the signal


def model_path(cfg: Config, model: str) -> Path:
    root = Path(os.environ.get("NEMO_HOME",
                               Path.home() / ".nemo")) / "models"
    for pattern in (f"{model}*.gguf", f"*{model}*.gguf"):
        found = sorted(root.glob(pattern))
        if found:
            return found[0]
    raise FileNotFoundError(
        f"no GGUF for {model!r} under {root}. Download it there, or change "
        "the model name in config under modes.")


def engine_path(cfg: Config) -> str | None:
    """The llama-server to run: the configured file if it exists, else
    the same search the doctor makes (PATH, then where the installers put
    it). D176: this used the configured name as it stood, "llama-server",
    which on NemoIso is in /opt/nemo/bin, on nobody's PATH. nemodoc and
    the doctor looked there and said it was installed; loading a model
    looked only on the PATH and could not, on the first real run."""
    configured = str(cfg.get("paths.llama_server", "llama-server"))
    if Path(configured).is_file():
        return configured
    return find_tool("llama-server")


def gpu_engine_path(cfg: Config) -> str | None:
    """The CUDA llama-server for a desktop mode (nemo/machine.py)."""
    configured = cfg.get("paths.llama_server_gpu")
    if configured and Path(str(configured)).is_file():
        return str(configured)
    from .machine import cuda_engine
    return cuda_engine()


# What a GPU mode asks to be free on the card beyond its own figure: the
# desktop itself draws on the same memory (602-666 MiB was in use before
# any model on the RTX 3050, 2026-11-04) and can grow while a mode runs.
VRAM_MARGIN_MIB = 300


def _too_little_vram(name: str, need: int, have: int) -> str:
    return (f"mode {name!r} needs about {need} MiB free on the GPU but only {have} MiB "
            "is. A game or another program using the card holds the rest: close it, "
            "use a smaller mode (talk, build, tiny), or pass --force to try anyway.")


def memory_need(spec: dict) -> tuple[int, int, int]:
    """(need, model, tools) in MB for a mode: what start() asks to be free.
    The Doctors read it too (nemo/clinic.py), so the two cannot judge
    memory by different figures (docs/design-rules.md, mistake 3)."""
    want_mb = int(spec.get("ram_mb", 2500))
    tools_mb = int(spec.get("tools_mb", 0))
    return want_mb + tools_mb + 300, want_mb, tools_mb


def start(cfg: Config, name: str, force: bool = False) -> tuple[bool, str]:
    spec = cfg.mode(name)
    model = spec["model"]
    need, want_mb, tools_mb = memory_need(spec)

    # Refuse before we thrash, not after. The tools reservation matters:
    # a model that fits on its own and leaves no room for KiCad is not a
    # working configuration, it is a configuration that fails in ten minutes.
    #
    # D191: counted as if nothing were given back. A mode already running
    # is stopped below, so its memory is coming back: switching from one
    # mode to another was refused for memory the old one was about to
    # free. And Windows gives a stopped server's memory back over a second
    # or two (measured on the AH531, 2026-10-19: 1995 MB available just
    # after a stop, 3958 MB two seconds later), so a start straight after
    # a stop was refused too.
    old = current()
    held = process_rss_mb(old.pid) if old.running else 0
    have = mem_available_mb()
    reclaim = False
    if have and have < need and not force:
        if held and have + held >= need:
            reclaim = True          # decided after stopping it, below
        elif not old.running and _stopped_recently():
            have = _wait_for_memory(need, MEMORY_RETURN_S)
    if have and have < need and not force and not reclaim:
        return False, _too_little(name, need, want_mb, tools_mb, have)

    # A desktop mode (nemo/machine.py): the model lives on the GPU, so the
    # card's free memory is what decides, checked like RAM above. A mode
    # already running is stopped below and gives its share back, so it is
    # checked again after that rather than refused now.
    gpu = bool(spec.get("gpu"))
    vram_need = int(spec.get("vram_mb", 0)) + VRAM_MARGIN_MIB if gpu else 0
    if gpu and not force and not old.running:
        from .machine import gpu_free_mib
        free = gpu_free_mib()
        if free is not None and free < vram_need:
            return False, _too_little_vram(name, vram_need, free)

    # Refuse before llama.cpp dies with an illegal instruction. Verified by
    # running it, which is the only test that distinguishes a binary built
    # for the wrong instruction set from one that is merely slow.
    binary = gpu_engine_path(cfg) if gpu else engine_path(cfg)
    if gpu and not binary:
        return False, ("this mode runs on the GPU and the CUDA llama-server is not "
                       "installed (C:\\Nemo\\engine-cuda). Run NemoDoc while online, or "
                       "set machine: laptop in config.yaml to use the CPU modes.")
    if not binary:
        return False, ("llama-server is not installed, or not where Nemo looks: "
                       "on the PATH, C:\\Nemo\\engine, /opt/nemo/bin or ~/.nemo/bin. "
                       "Run NemoDoc (Windows) or nemodoc (Linux) while online.")
    runs, why = llama_binary_runs(binary)
    if not runs:
        # Blame the instruction set only when that is what happened. The
        # hint used to follow every failure, including argument errors.
        hint = ("\n  This build uses an instruction set this CPU lacks."
                if "illegal instruction" in why else "")
        return False, f"llama-server will not start: {why}{hint}"

    try:
        gguf = model_path(cfg, model)
    except FileNotFoundError as exc:
        return False, str(exc)

    stop()
    if reclaim:
        # Stopped only now, after every other reason to refuse, so a start
        # that fails for another reason leaves the running mode alone.
        have = _wait_for_memory(need, MEMORY_RETURN_S)
        if have < need:
            return False, (f"mode {old.name!r} was stopped to make room, but only "
                           f"{have} MB came back.\n  " +
                           _too_little(name, need, want_mb, tools_mb, have))
    if gpu and not force and old.running:
        from .machine import gpu_free_mib
        end = time.time() + MEMORY_RETURN_S
        free = gpu_free_mib()
        while free is not None and free < vram_need and time.time() < end:
            time.sleep(0.5)
            free = gpu_free_mib()
        if free is not None and free < vram_need:
            return False, (f"mode {old.name!r} was stopped to make room on the GPU.\n  "
                           + _too_little_vram(name, vram_need, free))
    port = cfg.get("engine.local", "http://127.0.0.1:8080/v1")
    port = port.rsplit(":", 1)[-1].split("/")[0]

    # Only what Nemo actually needs. An earlier revision also passed:
    #   --mlock  removed upstream (now --load-mode). The first launch on the
    #            laptop died with "invalid argument: --mlock". Locking the
    #            model into RAM is wrong here anyway: on 8 GB it forces
    #            Windows to page out KiCad instead.
    #   -t N     set to the LOGICAL core count, overriding llama.cpp's own
    #            default of physical cores -- worse for bandwidth-bound
    #            inference on a hyper-threaded dual core.
    #   -np 1    one slot. The default ("auto") made four on the AH531
    #            (~/.nemo/talk.log); Nemo sends one request at a time, and
    #            the prompt cache below saves and restores slot 0.
    #   --slot-save-path  where the prompt cache is kept (nemo/slotcache.py).
    #   --cache-ram  llama-server keeps every prompt it has read in RAM, up
    #            to 8192 MB by default, and nothing in the budget above
    #            counted it. Measured on the AH531 (talk mode, 2026-10-20):
    #            18 MB more for each new 160-token system prompt. Capped
    #            within the 300 MB margin; the disk cache does the rest.
    args = ["-m", str(gguf), "-c", str(spec.get("ctx", 4096)), "--port", port,
            "-np", "1", "--cache-ram", str(int(cfg.get("engine.cache_ram_mb", 256)))]
    if gpu:
        #   -ngl 99  every layer on the GPU (its figures were measured so).
        #   --load-mode none  read the file in rather than map it: mapped,
        #            the 8B held 4.9 GB of RAM it never used (779 MB without).
        args += ["-ngl", "99", "--load-mode", "none"]
    slots = stick = None
    if cfg.get("engine.prompt_cache", True):
        slots = slotcache.folder_for(STATE.parent, gguf, spec.get("ctx", 4096))
        if slotcache.in_ram(slots.parent.parent):
            # A live stick keeps the files in NemoData (slotcache.STICK_SLOTS);
            # this folder only stages them. Anywhere else in RAM: no cache.
            if storage.has_stick():
                stick = slotcache.STICK_SLOTS / slots.name
            else:
                slots = None
        if slots is not None:
            args += ["--slot-save-path", str(slots)]

    # Confirm this build accepts every flag before launching, so a future
    # upstream rename is reported by name rather than as a crash.
    try:
        helptext = subprocess.run([binary, "--help"], capture_output=True,
                                  text=True, timeout=30)
        text = (helptext.stdout or "") + (helptext.stderr or "")
        unknown = [a for a in args if a.startswith("-") and a not in text]
        if text.strip() and unknown:
            return False, (f"this llama-server does not accept {', '.join(unknown)}. "
                           "It is probably a different version from the one "
                           "NemoDoc pins (b11175).")
    except (OSError, subprocess.SubprocessError):
        pass          # the launch below reports the real problem
    cmd = [binary] + args

    log = STATE.parent / f"{name}.log"
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if slots is not None:
        slots.mkdir(parents=True, exist_ok=True)
    logfile = log.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(cmd, stdout=logfile,
                                stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        # The child inherits its own copy of the descriptor; this process's
        # copy is only needed for the Popen() call itself.
        logfile.close()
    STATE.write_text(f"{name}\n{proc.pid}\n{model}\n", encoding="utf-8")
    if slots is not None:
        slotcache.write_state(STATE.parent, proc.pid, slots, stick)

    # D121: this used to sleep two seconds and report "up". The process
    # exists long before the model is loaded: measured on the AH531, the
    # server answered HTTP 503 for a further 2.6 s after "up" was printed,
    # and a story command sent in that gap was told no model was loaded.
    # So wait until it actually answers, or dies, or the limit passes.
    ready = _wait_ready(cfg.get("engine.local", "http://127.0.0.1:8080/v1"),
                        proc, READY_TIMEOUT_S)
    if proc.poll() is not None:
        STATE.unlink(missing_ok=True)
        slotcache.clear_state(STATE.parent)
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
        return False, ("llama-server exited immediately:\n  " +
                       "\n  ".join(tail))
    what = f"{gguf.name}, {spec.get('ctx')} ctx, pid {proc.pid}"
    if not ready:
        return True, (f"mode {name!r} started ({what}) but is still loading after "
                      f"{READY_TIMEOUT_S} s. It is not answering yet; give it a "
                      "little longer before using it.")
    return True, f"mode {name!r} up: {what}"


READY_TIMEOUT_S = 180

# How long a start waits for a stopped server's memory to come back, and
# how recently a stop must have been for a start to wait at all.
MEMORY_RETURN_S = 15
RECENT_STOP_S = 30
STOPPED_NAME = "mode.stopped"     # beside mode.pid


def _stopped_recently() -> bool:
    try:
        return time.time() - STATE.with_name(STOPPED_NAME).stat().st_mtime < RECENT_STOP_S
    except OSError:
        return False


def _wait_for_memory(need: int, timeout: float) -> int:
    """Available memory once it reaches `need`, or when `timeout` passes."""
    end = time.time() + timeout
    have = mem_available_mb()
    while have < need and time.time() < end:
        time.sleep(0.5)
        have = mem_available_mb()
    return have


def _too_little(name: str, need: int, want_mb: int, tools_mb: int, have: int) -> str:
    extra = ("\n  Windows is using around "
             f"{mem_total_mb() - have} MB of the {mem_total_mb()} MB "
             # D123: this named install/windows/trim.ps1, a folder that
             # exists only in the old source tree, not in what ships.
             "installed. trim.ps1 in the NemoWin folder recovers roughly "
             "800 MB to 1 GB of that."
             if IS_WINDOWS else "")
    return (f"mode {name!r} needs about {need} MB ({want_mb} for the model, "
            f"{tools_mb} reserved for the tools the steps run) but only {have} MB "
            f"is available.{extra}\n  Close what you can, use talk mode, or "
            "pass --force to try anyway (expect heavy swapping on a SATA "
            "drive).")


def _wait_ready(base: str, proc, timeout: float) -> bool:
    """True once the server answers, False if it exits or time runs out.

    A server that is still loading its model refuses the connection or
    answers 503; both mean "not yet".
    """
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(f"{base}/models", timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def suggest(task: str) -> str:
    """Which mode a given task wants.

    On a machine with under 8 GB installed there is only one answer: the
    larger modes will not load, so suggesting them wastes the user's time.
    """
    if mem_total_mb() and mem_total_mb() < 7000:
        return "tiny"
    from .steps import BY_KEY
    step = BY_KEY.get(task)
    mode = step.mode if step else "talk"          # a story, or anything else: talk
    # D102: NemoDoc's own launcher already downgrades design to talk with
    # no AVX -- a Sandy Bridge Celeron or Pentium -- but that check only
    # ran once, at startup. Every later in-app recommendation went through
    # this function instead, which had no such check, so on exactly that
    # hardware the CAD stages (electrical, wiring, enclosure) kept being
    # pointed at design: it needs more headroom than this CPU class ever
    # has free, "Load the model?" leads straight to "could not load the
    # model", and asking again reaches the identical suggestion and the
    # identical failure. From the outside that is indistinguishable from
    # the pipeline simply refusing to move past whichever stage asked.
    if mode == "design" and "avx" not in cpu_flags():
        return "talk"
    return mode
