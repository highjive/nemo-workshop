"""The Storeroom's drives and space (owner, 2026-10-23): what each shelf
takes and what is free; external drives picked up when plugged in, their
files sorted by extension to the shelf each belongs on, and moved over only
when he says, each copy checked by hash before the original is removed.
A backup of Nemo is offered when a drive appears; it runs only on his yes.

Never touched: the system disk, the Windows disk NemoIso reads, the stick
NemoIso booted from (label NEMOISO or /run/live/medium). Nothing on a drive
is changed until a move he asked for; a file that is already on the shelf
(same name) is given a new name, never overwritten.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

BOOT_LABELS = {"NEMOISO"}
# Picture extensions beyond the Theatre's (phones' and cameras').
MORE_PICTURES = {".heic", ".tif", ".tiff"}


@dataclass
class Drive:
    path: Path
    label: str
    total: int
    free: int

    @property
    def name(self) -> str:
        return f"{self.label} ({self.path})" if self.label else str(self.path)


@dataclass
class Group:
    ext: str
    shelf: str                 # "" where no shelf takes it
    files: list[Path] = field(default_factory=list)
    bytes: int = 0


def _windows_drives() -> list[Path]:
    import ctypes
    k = ctypes.windll.kernel32
    system = os.environ.get("SystemDrive", "C:").upper()
    out = []
    mask = k.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        # 2 removable; 3 fixed only on a USB bus (a USB hard disk shows as
        # fixed; the AH531's own D: is a fixed SATA partition, and stays out)
        kind = k.GetDriveTypeW(root)
        if root[:2].upper() != system and (kind == 2 or (kind == 3 and _bus(root[:2]) == 7)):
            out.append(Path(root))
    return out


def _bus(letter: str) -> int:
    """The drive's bus type by IOCTL_STORAGE_QUERY_PROPERTY (7 = USB); -1 unknown."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.CreateFileW.restype = wintypes.HANDLE
    h = k.CreateFileW(f"\\\\.\\{letter}", 0, 3, None, 3, 0, None)
    if h in (None, wintypes.HANDLE(-1).value):
        return -1
    try:
        query = (ctypes.c_uint32 * 3)(0, 0, 0)            # StorageDeviceProperty, standard query
        out = ctypes.create_string_buffer(1024)
        got = wintypes.DWORD()
        if not k.DeviceIoControl(wintypes.HANDLE(h), 0x2D1400, query, 12, out, 1024,
                                 ctypes.byref(got), None):
            return -1
        return out.raw[28]                                 # STORAGE_DEVICE_DESCRIPTOR.BusType
    finally:
        k.CloseHandle(wintypes.HANDLE(h))


def _label(path: Path) -> str:
    if sys.platform == "win32":
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        if ctypes.windll.kernel32.GetVolumeInformationW(str(path), buf, 261, None, None, None, None, 0):
            return buf.value
        return ""
    return path.name


def _linux_drives() -> list[Path]:
    user = os.environ.get("USER", "")
    out = []
    for base in (Path("/media") / user, Path("/run/media") / user, Path("/media")):
        if base.is_dir():
            out += [p for p in sorted(base.iterdir()) if p.is_dir() and os.path.ismount(p)]
    skip = {Path("/run/live/medium")}
    return [p for p in dict.fromkeys(out) if p not in skip and _on_usb(p)]


def _on_usb(mount: Path) -> bool:
    """Whether a mount's device sits on a USB bus (an internal disk the
    desktop mounted under /media, such as the Windows disk, stays out)."""
    try:
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            dev, where = line.split()[:2]
            if Path(where.replace("\\040", " ")) == mount and dev.startswith("/dev/"):
                name = Path(os.path.realpath(dev)).name
                return "/usb" in os.path.realpath(f"/sys/class/block/{name}")
    except OSError:
        pass
    return False


def drives() -> list[Drive]:
    """External drives plugged in now, with their space; never the boot stick."""
    found = []
    try:
        paths = _windows_drives() if sys.platform == "win32" else _linux_drives()
    except OSError:
        return []
    for p in paths:
        try:
            label = _label(p)
            if label.upper() in BOOT_LABELS:
                continue
            use = shutil.disk_usage(p)
        except OSError:
            continue                                       # a card reader with no card
        found.append(Drive(p, label, use.total, use.free))
    return found


def new_since(before: list[Drive], now: list[Drive]) -> list[Drive]:
    seen = {d.path for d in before}
    return [d for d in now if d.path not in seen]


# ---------------------------------------------------------------- space
def _size(p: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def space(root: Path) -> tuple[dict[str, int], int, int]:
    """Bytes on each shelf (and the rest of the Storeroom), and the disk's
    free and total bytes."""
    from .storeroom import SHELVES
    root = Path(root).expanduser()
    out = {name: _size(root / name) for name in SHELVES}
    out["vault"] = _size(root / "vault")
    everything = _size(root) if root.is_dir() else 0
    out["other"] = max(0, everything - sum(out.values()))
    use = shutil.disk_usage(root if root.is_dir() else root.anchor or "/")
    return out, use.free, use.total


def human(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ---------------------------------------------------------------- sorting
def shelf_for(ext: str) -> str:
    """The shelf a file of this extension goes on, "" if none takes it."""
    from .gaming import CONSOLES
    from .music import AUDIO
    from .theatre import PHOTO, VIDEO
    ext = ext.lower()
    if ext in VIDEO:
        return "videos"
    if ext in PHOTO or ext in MORE_PICTURES:
        return "pictures"
    if ext in AUDIO:
        return "music"
    for c in CONSOLES:
        if ext in c.exts and ext != ".bin":                # .bin is too many things to guess
            return f"games/{c.key}"
    return ""


def survey(where: Path, limit: int = 20000) -> tuple[list[Group], bool]:
    """The files on a drive by extension, each with its shelf; and whether
    the look stopped at `limit` files. Hidden and system folders are skipped."""
    groups: dict[str, Group] = {}
    n, cut = 0, False
    for root, dirs, files in os.walk(where):
        dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d != "System Volume Information"]
        for f in files:
            if n >= limit:
                cut = True
                break
            p = Path(root) / f
            ext = p.suffix.lower() or "(none)"
            g = groups.setdefault(ext, Group(ext, shelf_for(ext) if ext != "(none)" else ""))
            g.files.append(p)
            try:
                g.bytes += p.stat().st_size
            except OSError:
                pass
            n += 1
        if cut:
            break
    return sorted(groups.values(), key=lambda g: (g.shelf == "", -g.bytes)), cut


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _free_name(dest: Path) -> Path:
    if not dest.exists():
        return dest
    for i in range(2, 10000):
        cand = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not cand.exists():
            return cand
    raise OSError(f"no free name for {dest.name}")


@dataclass
class Moved:
    moved: list[Path] = field(default_factory=list)
    kept: list[tuple[Path, str]] = field(default_factory=list)    # (file, why it stayed)


def move(groups: list[Group], root: Path, keep_originals: bool = False) -> Moved:
    """Move the groups' files onto their shelves: copy, check by sha256,
    then remove the original (unless keep_originals). Stops before starting
    if the shelves' disk lacks room for all of it."""
    root = Path(root).expanduser()
    todo = [(f, g.shelf) for g in groups if g.shelf for f in g.files]
    need = sum(f.stat().st_size for f, _ in todo if f.exists())
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    if need > free:
        raise OSError(f"not enough room: {human(need)} to move, {human(free)} free")
    done = Moved()
    for f, shelf in todo:
        dest = _free_name(root / shelf / f.name)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            if _sha(f) != _sha(dest):
                dest.unlink(missing_ok=True)
                done.kept.append((f, "the copy did not match; the original is kept"))
                continue
            if not keep_originals:
                f.unlink()
            done.moved.append(dest)
        except OSError as exc:
            done.kept.append((f, str(exc)))
    return done


def backup_fits(cfg, drive: Drive) -> tuple[int, bool]:
    """About how big a backup of Nemo would be (before compression), and
    whether the drive has room for it."""
    from . import backup
    total = 0
    for _name, src in backup.sources(cfg):
        if src.is_file():
            total += src.stat().st_size
        elif src.is_dir():
            total += _size(src)
    return total, total < drive.free
