"""Platform probing for Windows and Linux.

Nemo was written for a Debian install on a Fujitsu Lifebook AH531. This
module exists because that assumption turned out to be wrong: the machine
runs Windows 11, on a CPU Microsoft never supported, via a bypass install.

That works -- Sandy Bridge has SSE4.2 and POPCNT, which is what 24H2 and
later actually require to boot -- but it changes three numbers that matter:
memory overhead, graphics capability, and which models are usable.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")

# Constants for kernel32!IsProcessorFeaturePresent.
_PF = {
    "sse4_2": 38,
    "avx": 39,
    "avx2": 40,
    "avx512f": 41,
}


def _proc(path: str) -> str:
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    except OSError:
        return ""


def _powershell(script: str, timeout: int = 20) -> str:
    """Run a PowerShell one-liner. Returns '' on any failure."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             script],
            capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# --------------------------------------------------------------------
# CPU
# --------------------------------------------------------------------

def cpu_flags() -> set[str]:
    if not IS_WINDOWS:
        m = re.search(r"^flags\s*:\s*(.+)$", _proc("/proc/cpuinfo"), re.M)
        return set(m.group(1).split()) if m else set()

    # Windows has no /proc. IsProcessorFeaturePresent is the documented way
    # to ask, and it is what actually matters for llama.cpp.
    found = set()
    try:
        k32 = ctypes.windll.kernel32           # type: ignore[attr-defined]
        for name, code in _PF.items():
            if k32.IsProcessorFeaturePresent(code):
                found.add(name)
    except (AttributeError, OSError):
        pass
    return found


def cpu_model() -> str:
    if not IS_WINDOWS:
        m = re.search(r"^model name\s*:\s*(.+)$", _proc("/proc/cpuinfo"), re.M)
        return m.group(1).strip() if m else "unknown"
    name = _powershell("(Get-CimInstance Win32_Processor).Name")
    return name or "unknown"


def cpu_threads() -> int:
    if not IS_WINDOWS:
        return len([ln for ln in _proc("/proc/cpuinfo").splitlines()
                    if ln.startswith("processor")]) or 1
    out = _powershell(
        "(Get-CimInstance Win32_Processor | "
        "Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum")
    try:
        return int(out)
    except ValueError:
        import os
        return os.cpu_count() or 1


# --------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _winmem() -> tuple[int, int]:
    stat = _MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore
            ctypes.byref(stat))
    except (AttributeError, OSError):
        return 0, 0
    return (stat.ullTotalPhys // (1024 * 1024),
            stat.ullAvailPhys // (1024 * 1024))


def mem_total_mb() -> int:
    if IS_WINDOWS:
        return _winmem()[0]
    m = re.search(r"^MemTotal:\s+(\d+) kB", _proc("/proc/meminfo"), re.M)
    return int(m.group(1)) // 1024 if m else 0


def mem_available_mb() -> int:
    if IS_WINDOWS:
        return _winmem()[1]
    m = re.search(r"^MemAvailable:\s+(\d+) kB", _proc("/proc/meminfo"), re.M)
    return int(m.group(1)) // 1024 if m else 0


def zram_swap_mb(swaps: str | None = None) -> int:
    """Total size of the zram swap devices in /proc/swaps, in MB (0 where
    there are none, or on Windows). NemoIso sets one up at boot (zram-tools,
    build-iso.sh)."""
    if swaps is None:
        if IS_WINDOWS:
            return 0
        swaps = _proc("/proc/swaps")
    total_kb = 0
    for line in swaps.splitlines()[1:]:
        f = line.split()
        if len(f) >= 3 and f[0].startswith("/dev/zram") and f[2].isdigit():
            total_kb += int(f[2])
    return total_kb // 1024


def memory_sticks() -> list[str]:
    if IS_WINDOWS:
        out = _powershell(
            "Get-CimInstance Win32_PhysicalMemory | "
            "ForEach-Object { \"$($_.Capacity/1GB) GB @ $($_.Speed) MHz\" }")
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    import shutil
    if not shutil.which("dmidecode"):
        return []
    try:
        out = subprocess.run(["dmidecode", "-t", "memory"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    sticks = []
    for block in out.stdout.split("Memory Device"):
        size = re.search(r"^\s*Size:\s*(.+)$", block, re.M)
        speed = re.search(r"^\s*Speed:\s*(.+)$", block, re.M)
        if size and "No Module" not in size.group(1):
            s = size.group(1).strip()
            sticks.append(f"{s} @ {speed.group(1).strip()}" if speed else s)
    return sticks


# --------------------------------------------------------------------
# Windows specifics
# --------------------------------------------------------------------

def windows_build() -> tuple[str, str]:
    """(display version e.g. '24H2', build number). Empty on Linux."""
    if not IS_WINDOWS:
        return "", ""
    out = _powershell(
        "$k='HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'; "
        "$p=Get-ItemProperty $k; "
        "\"$($p.DisplayVersion)|$($p.CurrentBuildNumber).$($p.UBR)\"")
    if "|" in out:
        ver, build = out.split("|", 1)
        return ver.strip(), build.strip()
    return "", ""


def display_adapter() -> tuple[str, str]:
    """(adapter name, driver version). This is the load-bearing check."""
    if not IS_WINDOWS:
        return "", ""
    out = _powershell(
        "Get-CimInstance Win32_VideoController | "
        "ForEach-Object { \"$($_.Name)|$($_.DriverVersion)\" }")
    first = out.splitlines()[0] if out.splitlines() else ""
    if "|" in first:
        name, drv = first.split("|", 1)
        return name.strip(), drv.strip()
    return first.strip(), ""


def basic_display_adapter() -> bool:
    """True when Windows fell back to the software display driver.

    On Windows 11 there is no Intel driver for HD Graphics 3000, so this is
    the expected state on an AH531 -- and it means no hardware OpenGL at all.
    """
    name, _ = display_adapter()
    return "basic display" in name.lower() or "basic render" in name.lower()


def mesa_installed(app_dir: Path) -> bool:
    """Is a Mesa software-OpenGL DLL sitting next to the application?

    Dropping mesa's opengl32.dll beside kicad.exe or freecad.exe is the only
    way to get a usable OpenGL context on this machine under Windows 11.
    """
    return (app_dir / "opengl32.dll").exists()


def os_label() -> str:
    if not IS_WINDOWS:
        return "Linux"
    ver, build = windows_build()
    return f"Windows 11 {ver} (build {build})" if ver else "Windows"


# ====================================================================
#  Locating external tools
# ====================================================================

# Where installers put things that they do not add to PATH. KiCad's Windows
# installer is the case that prompted this: it never touches PATH, and it
# installs into a folder named for its major version -- so a search for
# "9.0" silently misses 10.0, which is the current release.
_TOOL_GLOBS = {
    "kicad-cli": [
        r"C:\Program Files\KiCad\*\bin\kicad-cli.exe",
        r"C:\Program Files (x86)\KiCad\*\bin\kicad-cli.exe",
        "{LOCALAPPDATA}\\Programs\\KiCad\\*\\bin\\kicad-cli.exe",
        "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    ],
    "dot": [
        "/usr/bin/dot", "/usr/local/bin/dot",
        r"C:\Program Files\Graphviz\bin\dot.exe",
        r"C:\Program Files (x86)\Graphviz\bin\dot.exe",
    ],
    # D210: FreeCAD's installer never adds it to PATH. Its folders are named
    # "FreeCAD <version>" (all-users or per-user install).
    "freecad": [
        r"C:\Program Files\FreeCAD *\bin\freecad.exe",
        "{LOCALAPPDATA}\\Programs\\FreeCAD *\\bin\\freecad.exe",
        "/Applications/FreeCAD.app/Contents/MacOS/FreeCAD",
    ],
    # The CUDA build, apart from the CPU one (nemo/machine.py).
    "llama-server-cuda": [
        r"C:\Nemo\engine-cuda\llama-server.exe",
        "/opt/nemo/bin-cuda/llama-server",
        "{HOME}/.nemo/bin-cuda/llama-server",
    ],
    "llama-server": [
        r"C:\Nemo\engine\llama-server.exe",
        "/opt/nemo/bin/llama-server",
        "{HOME}/.nemo/bin/llama-server",
    ],
}


_VERSION_DIR = re.compile(r"[\\/](?:(?:KiCad|Graphviz)[\\/]|FreeCAD )(\d+(?:\.\d+)*)[\\/]",
                          re.IGNORECASE)


def _version_key(path: str) -> tuple:
    """Version from the folder directly under the product directory.

    Orders 10.0 after 9.0, which a string sort does not. An earlier revision
    took every digit in the whole path, so "Program Files (x86)" sorted as
    version 86 and a user named Someone2011 as version 2011 -- either of
    which beat a real 10.0 install. Only the version folder counts.
    """
    m = _VERSION_DIR.search(path)
    if not m:
        return (0,)
    return tuple(int(n) for n in m.group(1).split("."))


def find_tool(name: str, override: str | None = None) -> str | None:
    """Find an executable, including ones installers leave off PATH.

    Order: explicit override, PATH, then known install locations -- newest
    version first when several are installed side by side.
    """
    import glob
    import os
    import shutil

    if override:
        o = os.path.expanduser(override)
        if os.path.isfile(o):
            return o

    for candidate in (name, name + ".exe"):
        hit = shutil.which(candidate)
        if hit:
            return hit

    # Tools pip installed into Nemo's own environment -- PlatformIO and
    # WireViz -- live beside the interpreter, and that folder is on nobody's
    # PATH on the ISO. Without this the firmware and wiring gates skipped
    # on every run there while both tools sat installed next door.
    import sys
    here = os.path.dirname(os.path.abspath(sys.executable))
    for candidate in (name, name + ".exe"):
        c = os.path.join(here, candidate)
        if os.path.isfile(c):
            return c

    env = {"LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
           "HOME": os.path.expanduser("~")}
    found: list[str] = []
    for pattern in _TOOL_GLOBS.get(name, []):
        try:
            pattern = pattern.format(**env)
        except (KeyError, IndexError):
            continue
        if pattern.startswith("\\") or not pattern.strip():
            continue
        found.extend(g for g in glob.glob(pattern) if os.path.isfile(g))
    if not found:
        return None
    return sorted(found, key=_version_key)[-1]


def pid_alive(pid: int | None) -> bool:
    """Whether a process with this id exists right now. Sends it nothing.

    D113: this used to be os.kill(pid, 0) everywhere. That is the POSIX
    probe. On Windows 0 is CTRL_C_EVENT: the call succeeds for a process
    that has already exited, and it delivers a Ctrl+C to the console.
    """
    if not pid:
        return False
    if not IS_WINDOWS:
        try:
            os.kill(int(pid), 0)
            return True
        except PermissionError:
            return True               # it exists; it is just not ours
        except OSError:
            return False
    try:
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        # PROCESS_QUERY_LIMITED_INFORMATION
        h = k32.OpenProcess(0x1000, False, int(pid))
        if not h:
            # 5 = access denied: there is such a process, we may not open it.
            return ctypes.get_last_error() == 5      # type: ignore[attr-defined]
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == 259                 # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except (AttributeError, OSError, ValueError):
        return False


def process_rss_mb(pid: int) -> int:
    """Resident memory of one process, in MB. 0 if it cannot be read.

    Used to separate Nemo's own model from everything else, so the doctor
    does not blame Windows for memory Nemo itself is holding.
    """
    if not pid:
        return 0
    if not IS_WINDOWS:
        m = re.search(r"^VmRSS:\s+(\d+) kB", _proc(f"/proc/{pid}/status"), re.M)
        return int(m.group(1)) // 1024 if m else 0
    try:
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.windll.kernel32                      # type: ignore[attr-defined]
        h = k32.OpenProcess(0x1000 | 0x0010, False, int(pid))
        if not h:
            return 0
        try:
            c = PMC(); c.cb = ctypes.sizeof(PMC)
            if not k32.K32GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
                return 0
            return int(c.WorkingSetSize) // (1024 * 1024)
        finally:
            k32.CloseHandle(h)
    except (AttributeError, OSError):
        return 0
