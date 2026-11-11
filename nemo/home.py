"""Home: the devices on your home network, and what Nemo may do with each
(owner, 2026-10-22: "other devices on network and nemo permissions to access
them", and "your Nemo-built devices").

  Surveyor      who is on the network, from what devices announce of
                themselves (mDNS/Bonjour, and SSDP/UPnP: a question to the
                whole network, as finding a Chromecast already sends) and
                the list of addresses Windows or Linux already holds (the
                ARP table). It never connects to a device, opens its pages,
                tries its ports or logs in.
  Gatekeeper    a permission for each device, set only by you:
                  hidden  not listed
                  see     listed, nothing else (the default)
                  use     Nemo may talk to it through its own documented
                          local interface: cast to a Chromecast, read a
                          Nemo-built board's status
                Every change is written to a log. Casting (the Theatre, the
                Music Room) asks the Gatekeeper first.
  Device Keeper the boards you built and flashed (the Test Bench's work log),
                and any that announce themselves as Nemo's (_nemo._tcp);
                with "use", it reads their status page. Nemo's bring-up
                firmware does not announce itself yet, so a board is shown
                as flashed but not seen.
  Writer        a list of your home's devices (home-devices.md).

Nothing asks the model. Passwords for other devices are never asked for or
kept. NEMO_HOME_GATE=off (the test sandbox only) lets casting through.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PERMISSIONS = ("hidden", "see", "use")
DEFAULT = "see"
# What a service type says a device is, in plain words.
KINDS = {"_googlecast._tcp": "Chromecast or Google speaker",
         "_googlezone._tcp": "Google speaker group", "_ipp._tcp": "printer",
         "_printer._tcp": "printer", "_pdl-datastream._tcp": "printer",
         "_airplay._tcp": "AirPlay screen or speaker", "_raop._tcp": "AirPlay speaker",
         "_spotify-connect._tcp": "Spotify speaker", "_hap._tcp": "smart-home accessory",
         "_smb._tcp": "shared folders", "_workstation._tcp": "computer",
         "_device-info._tcp": "computer", "_http._tcp": "has a web page",
         "_nemo._tcp": "Nemo-built board", "_esphomelib._tcp": "ESPHome board",
         "_androidtvremote2._tcp": "Android TV", "_sonos._tcp": "Sonos speaker"}
SSDP_ADDR = ("239.255.255.250", 1900)


class HomeError(RuntimeError):
    pass


@dataclass
class Device:
    key: str                         # mac:aa-bb-.. , or name:.. , or ip:..
    ip: str = ""
    mac: str = ""
    names: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    found_by: list[str] = field(default_factory=list)
    permission: str = DEFAULT
    seen: str = ""                   # when a survey last found it, YYYY-MM-DD HH:MM
    host: str = ""                   # its name in the network's own records (reverse DNS)
    platform: str = ""               # the owner's choice from PLATFORMS, "" when not chosen

    @property
    def label(self) -> str:
        # Not an id announced as a name (2026-11-06: a speaker was listed as
        # "0123456789abcdef0123456789abcdef01234567", its Spotify id).
        names = [n for n in self.names if not re.fullmatch(r"[0-9a-fA-F-]{16,}", n)]
        return names[0] if names else (self.host or self.ip or self.key)


# ---------------------------------------------------------------- the Surveyor
def lan_address() -> str:
    """This machine's address on the home network: the one its default
    route leaves by. A UDP socket's connect sends nothing; "" if none."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))            # TEST-NET-1: never reached
            return s.getsockname()[0]
    except OSError:
        return ""


def lan_device() -> str:
    """Linux: the interface the default route leaves by, or ""."""
    try:
        for line in Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split()
            if len(f) > 2 and f[1] == "00000000":
                return f[0]
    except OSError:
        pass
    return ""


def windows_arp(text: str, lan: str) -> list[tuple[str, str]]:
    """(ip, mac) from `arp -a`, from the home network's interface only when
    it is known: WSL's and Hyper-V's virtual networks have their own
    (2026-11-06: WSL's 172.24.89.58 was listed as a device on the network)."""
    pairs, keep = [], True
    for line in text.splitlines():
        m = re.match(r"^Interface:\s+(\d+\.\d+\.\d+\.\d+)", line.strip())
        if m:
            keep = not lan or m[1] == lan
            continue
        m = re.match(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+dynamic", line)
        if m and keep:
            pairs.append((m[1], m[2]))
    return pairs


def linux_arp(text: str, device: str) -> list[tuple[str, str]]:
    """(ip, mac) from /proc/net/arp, on the default route's interface only
    when it is known (not docker0, virbr0 and the like)."""
    return [(a, m.replace(":", "-")) for a, m, dev in
            re.findall(r"^(\d+\.\d+\.\d+\.\d+)\s+\S+\s+0x2\s+([0-9a-f:]{17})\s+\S+\s+(\S+)",
                       text, re.M)
            if not device or dev == device]


def arp_table() -> dict[str, str]:
    """ip -> mac, from the list the system already holds, on the home
    network's interface. Broadcast and multicast entries are left out."""
    out: dict[str, str] = {}
    try:
        if sys.platform.startswith("win"):
            text = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=20,
                                  errors="replace").stdout
            pairs = windows_arp(text, lan_address())
        else:
            text = Path("/proc/net/arp").read_text(encoding="utf-8")
            pairs = linux_arp(text, lan_device())
    except (OSError, subprocess.SubprocessError):
        return {}
    for ip, mac in pairs:
        mac = mac.lower()
        if mac not in ("ff-ff-ff-ff-ff-ff",) and not mac.startswith("01-00-5e"):
            out[ip] = mac
    return out


def ssdp(seconds: float = 3.0) -> dict[str, list[str]]:
    """ip -> what its SSDP answers say it is (their SERVER line). The
    LOCATION each gives is not opened."""
    found: dict[str, list[str]] = {}
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
           "MX: 2\r\nST: ssdp:all\r\n\r\n").encode()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(0.5)
        s.sendto(msg, SSDP_ADDR)
    except OSError:
        return {}
    end = time.time() + seconds
    try:
        while time.time() < end:
            try:
                data, (ip, _) = s.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(rb"^SERVER:\s*(.+?)\r?$", data, re.I | re.M)
            words = m[1].decode("utf-8", "replace").strip() if m else "answers UPnP"
            if words not in found.setdefault(ip, []):
                found[ip].append(words)
    except OSError:
        pass
    finally:
        s.close()
    return found


def mdns(seconds: float = 3.0) -> dict[str, dict]:
    """ip -> {"names": [...], "kinds": [...], "port": {type: port}} from
    what devices announce over mDNS: the service types on the network
    first, then who offers each."""
    try:
        from zeroconf import Zeroconf, ZeroconfServiceTypes
    except ImportError:
        return {}
    found: dict[str, dict] = {}
    zc = Zeroconf()
    try:
        types = ZeroconfServiceTypes.find(zc=zc, timeout=seconds)
        for t in types:
            short = t.replace(".local.", "")
            for name in _browse(zc, t, seconds / 2):
                info = zc.get_service_info(t, name, timeout=1500)
                if not info:
                    continue
                label = name.replace("." + t, "").strip()
                # A device's own friendly name, where its announcement gives
                # one: a Chromecast calls itself "Chromecast-<id>" and puts
                # "Family Room TV" in its "fn" text field (seen on the AH531's network).
                props = info.properties or {}
                friendly = next((props[k].decode("utf-8", "replace").strip() for k in (b"fn", b"n")
                                 if isinstance(props.get(k), bytes) and props[k].strip()), "")
                for ip in info.parsed_addresses():
                    d = found.setdefault(ip, {"names": [], "kinds": [], "port": {}})
                    if friendly and friendly not in d["names"]:
                        d["names"].insert(0, friendly)
                    if label and label not in d["names"]:
                        d["names"].append(label)
                    kind = KINDS.get(short, short)
                    if kind not in d["kinds"]:
                        d["kinds"].append(kind)
                    d["port"][short] = info.port
    except OSError:
        pass
    finally:
        zc.close()
    return found


def _browse(zc, service_type: str, seconds: float) -> list[str]:
    from zeroconf import ServiceBrowser
    names: list[str] = []

    class Listener:
        def add_service(self, z, t, name):
            if name not in names:
                names.append(name)

        def update_service(self, z, t, name):
            pass

        def remove_service(self, z, t, name):
            pass

    b = ServiceBrowser(zc, service_type, Listener())
    time.sleep(seconds)
    b.cancel()
    return names


def own_addresses() -> set[str]:
    """This computer's own addresses: it is not one of the home's devices
    (2026-11-06: it was listed as "Spotify Desktop Launcher", its own mDNS
    announcement)."""
    found = {lan_address()} - {""}
    try:
        # IPv4 and IPv6 (it announced itself again at its fe80:: address).
        found |= {str(a[4][0]).split("%")[0]
                  for a in socket.getaddrinfo(socket.gethostname(), None)}
    except OSError:
        pass
    return found


def survey(seconds: float = 3.0, arp=arp_table, ssdp_=ssdp, mdns_=mdns,
           own=own_addresses) -> list[Device]:
    """Everything the three sources say, one device per address, this
    computer left out."""
    table, upnp, bonjour = arp(), ssdp_(seconds), mdns_(seconds)
    mine = own()
    out: dict[str, Device] = {}
    for ip in sorted((set(table) | set(upnp) | set(bonjour)) - mine,
                     key=lambda a: tuple(int(x) for x in a.split(".")) if a.count(".") == 3 else (999,)):
        mac = table.get(ip, "")
        b = bonjour.get(ip, {})
        names = list(b.get("names", []))
        key = f"mac:{mac}" if mac else (f"name:{names[0]}" if names else f"ip:{ip}")
        d = out.setdefault(key, Device(key, ip, mac))
        d.names += [n for n in names if n not in d.names]
        d.kinds += [k for k in b.get("kinds", []) if k not in d.kinds]
        d.kinds += [w for w in upnp.get(ip, []) if w not in d.kinds]
        d.found_by = [s for s, here in (("ARP", ip in table), ("SSDP", ip in upnp),
                                        ("mDNS", ip in bonjour)) if here]
    found = _merge_by_name(out)
    for d, name in zip(found, host_names([d.ip for d in found])):
        d.host = name
    return found


def host_names(ips: list[str], timeout: float = 4.0) -> list[str]:
    """Each address's name in the network's own records (reverse DNS, asked
    of this computer's resolver, usually the router), "" where it has none.
    The device itself is not contacted. Asked together, so ten addresses
    take one wait, not ten."""
    from concurrent.futures import ThreadPoolExecutor, wait

    def one(ip):
        try:
            name = socket.gethostbyaddr(ip)[0]
        except (OSError, UnicodeError):
            return ""
        return "" if name == ip else name.split(".")[0]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one, ip) for ip in ips]
        wait(futures, timeout=timeout)
        return [f.result() if f.done() else "" for f in futures]


def _merge_by_name(out: dict[str, Device]) -> list[Device]:
    """One device seen at two addresses is one device: an entry with no MAC
    (an IPv6 link-local address announcing itself by mDNS) that has a name a
    MAC-keyed device also has joins that device, which keeps its IPv4 address.
    The AH531, 2026-10-28: a Samsung TV was listed twice, once per address."""
    by_name = {n: d for d in out.values() if d.mac for n in d.names}
    for key in [k for k, d in out.items() if not d.mac]:
        d = out[key]
        home = next((by_name[n] for n in d.names if n in by_name), None)
        if home is None:
            continue
        home.kinds += [k for k in d.kinds if k not in home.kinds]
        home.found_by += [f for f in d.found_by if f not in home.found_by]
        del out[key]
    return list(out.values())


# ---------------------------------------------------------------- the Gatekeeper
def _store() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "home.json"


def _log() -> Path:
    from .config import CONFIG_HOME
    return CONFIG_HOME / "home-permissions.jsonl"


def load() -> dict:
    try:
        d = json.loads(_store().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(devices: list[Device]) -> list[Device]:
    """Keep what was found (names, address, kinds) beside each device's
    permission, and give each found device its permission."""
    kept = load()
    for d in devices:
        if d.mac:
            # An entry kept by name before the merge above is this device: its
            # permission comes across (if this one has none yet) and it goes.
            for old in [k for k, v in kept.items() if k.startswith("name:")
                        and set(v.get("names", [])) & set(d.names)]:
                kept.setdefault(d.key, {"permission": kept[old].get("permission", DEFAULT)})
                del kept[old]
        k = kept.setdefault(d.key, {"permission": DEFAULT})
        k.update({"names": d.names, "ip": d.ip, "mac": d.mac, "kinds": d.kinds, "host": d.host,
                  "seen": time.strftime("%Y-%m-%d %H:%M")})
        d.permission = k.get("permission", DEFAULT)
        d.seen = k["seen"]
    _store().parent.mkdir(parents=True, exist_ok=True)
    _store().write_text(json.dumps(kept, indent=1), encoding="utf-8")
    return devices


def known() -> list[Device]:
    """Every device Nemo has seen, with its permission, hidden ones too."""
    return [Device(k, v.get("ip", ""), v.get("mac", ""), v.get("names", []), v.get("kinds", []),
                   [], v.get("permission", DEFAULT), v.get("seen", ""), v.get("host", ""),
                   v.get("platform", "")) for k, v in load().items()]


# ---------------------------------------------------------------- what kind of thing
# Owner, 2026-10-28: "a way of identifying what platform type a device on the
# network is". From what the survey already has, nothing more is asked of the
# device: what it announces, its network name, and its hardware address.
# Each guess says what it rests on; nothing is said where nothing is known.
_BY_KIND = (("Chromecast or Google speaker", "Google Cast device (TV stick or speaker)"),
            ("Samsung", "Samsung smart TV"), ("AirPlay", "Apple AirPlay device or AirPlay TV"),
            ("Spotify", "speaker or TV with Spotify"), ("printer", "printer"),
            ("Nemo board", "a board you built (Nemo)"))
_BY_NAME = ((r"^(desktop|laptop)-", "Windows PC (a name Windows gives itself)"),
            (r"^(android|galaxy|pixel|redmi|oneplus)", "Android phone or tablet"),
            (r"^(iphone|ipad)", "iPhone or iPad"), (r"(macbook|imac|mac-mini|\bmac\b)", "Mac"),
            (r"^raspberrypi", "Raspberry Pi"), (r"^(esp32|esp8266|esp_|espressif)", "ESP32 or ESP8266 board"),
            (r"(chromecast|google-home|nest)", "Google Cast device"), (r"(tv|bravia|lgwebos)", "smart TV"))


# The platform a device is, chosen by the owner (2026-10-28: "pick which
# platform ... making it usable network connection-wise"), and what Nemo can
# do with it over the network: built (and in which department), or not yet.
# Nothing here connects; the Gatekeeper's Use still decides whether Nemo may.
PLATFORMS = {
    "google_cast": ("Google Cast (Chromecast, Google TV, Nest speaker)",
                    "cast videos, pictures and music (Theatre, Music Room)", True),
    "nemo_board": ("A board you built with Nemo",
                   "read its status page (Home's Device Keeper)", True),
    "dlna_tv": ("Smart TV or speaker with DLNA/UPnP (Samsung, LG, Sony)",
                "not built yet: casting by DLNA", False),
    "airplay": ("Apple AirPlay (Apple TV, AirPlay TV or speaker)",
                "not built yet: casting by AirPlay", False),
    "windows_pc": ("Windows PC", "not built yet: sharing files with it", False),
    "mac": ("Mac", "not built yet: sharing files with it", False),
    "linux": ("Linux computer or Raspberry Pi", "not built yet: sharing files with it", False),
    "android": ("Android phone or tablet", "nothing yet: Nemo does not use phones", False),
    "ios": ("iPhone or iPad", "nothing yet: Nemo does not use phones", False),
    "printer": ("Network printer", "not built yet: printing to it", False),
    "router": ("Router or network box", "nothing: Nemo leaves it alone", False),
    "other": ("Something else", "nothing", False),
}
# A likely type (device_type) that points at a platform, to offer it first.
_SUGGEST = (("Google Cast", "google_cast"), ("Samsung smart TV", "dlna_tv"), ("smart TV", "dlna_tv"),
            ("AirPlay", "airplay"), ("Windows PC", "windows_pc"), ("Mac", "mac"),
            ("Raspberry Pi", "linux"), ("Android", "android"), ("iPhone", "ios"),
            ("printer", "printer"), ("board you built", "nemo_board"))


def suggest_platform(d: Device) -> str:
    """The platform the likely type points at, "" when it points nowhere."""
    kind = device_type(d)[0]
    return next((key for word, key in _SUGGEST if word.lower() in kind.lower()), "")


def can_do(d: Device) -> str:
    """What Nemo can do with the device over the network, by its platform:
    the owner's choice, else the suggestion (said as a suggestion)."""
    key = d.platform or suggest_platform(d)
    if not key:
        return "choose its platform to see what Nemo can do with it"
    _label, what, _built = PLATFORMS[key]
    return what if d.platform else f"{what} (if it is {PLATFORMS[key][0]}: choose to confirm)"


def set_platform(name_or_key: str, platform: str, by: str = "owner") -> Device:
    """The owner says which platform a device is; logged like a permission."""
    if platform not in PLATFORMS and platform != "":
        raise HomeError(f"a platform is one of {', '.join(PLATFORMS)}, not {platform!r}")
    d = find(name_or_key)
    if d is None:
        raise HomeError(f"no device {name_or_key!r} is known: look around first (nemo home survey)")
    kept = load()
    before = kept[d.key].get("platform", "")
    kept[d.key]["platform"] = platform
    _store().write_text(json.dumps(kept, indent=1), encoding="utf-8")
    with _log().open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "device": d.key, "name": d.label,
                            "from": f"platform {before or 'none'}", "to": f"platform {platform or 'none'}",
                            "by": by}) + "\n")
    d.platform = platform
    return d


def private_mac(mac: str) -> bool:
    """A locally administered hardware address (the 2 bit of the first byte):
    phones, tablets and some laptops make one up per network to stay
    anonymous, so it names no maker."""
    try:
        return bool(int(mac.replace(":", "-").split("-")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


def device_type(d: Device, owner_names: dict[str, str] | None = None) -> tuple[str, str]:
    """(what kind of device it likely is, what that rests on); ("", why not)
    when nothing says. owner_names: known computers' own names, such as
    {"MyDesktop": "your PC"}; a match is said plainly."""
    if d.platform in PLATFORMS:
        return PLATFORMS[d.platform][0], "you said so"
    text = " ".join(d.kinds)
    for word, kind in _BY_KIND:
        if word.lower() in text.lower():
            return kind, "what it announces"
    host = d.host or ""
    if owner_names and host.lower() in {k.lower() for k in owner_names}:
        mine = next(v for k, v in owner_names.items() if k.lower() == host.lower())
        return f"{host}: {mine}", "its network name"
    for pattern, kind in _BY_NAME:
        if host and re.search(pattern, host, re.I):
            return kind, f"its network name ({host})"
    if private_mac(d.mac):
        return ("phone, tablet or laptop (a private, made-up hardware address)",
                "its hardware address")
    if host:
        return f"a computer or device called {host}", "its network name"
    return "", "it announces nothing and has no network name"


def last_survey(devices: list[Device] | None = None) -> str:
    """When the latest survey ran: the newest 'seen' time kept."""
    return max((d.seen for d in (known() if devices is None else devices) if d.seen), default="")


def present(d: Device, last: str) -> bool:
    """Whether the latest survey found it; otherwise it is only remembered."""
    return bool(last) and d.seen == last


def find(name_or_key: str) -> Device | None:
    n = name_or_key.strip().lower()
    return next((d for d in known() if n in (d.key.lower(), d.ip, d.mac, d.label.lower())
                 or n in (x.lower() for x in d.names)), None)


def allow(name_or_key: str, permission: str, by: str = "owner") -> Device:
    """The owner sets a device's permission; the change is logged."""
    if permission not in PERMISSIONS:
        raise HomeError(f"a permission is one of {', '.join(PERMISSIONS)}, not {permission!r}")
    d = find(name_or_key)
    if d is None:
        raise HomeError(f"no device {name_or_key!r} is known: look around first (nemo home survey)")
    kept = load()
    before = kept[d.key].get("permission", DEFAULT)
    kept[d.key]["permission"] = permission
    _store().write_text(json.dumps(kept, indent=1), encoding="utf-8")
    with _log().open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "device": d.key,
                            "name": d.label, "from": before, "to": permission, "by": by}) + "\n")
    d.permission = permission
    return d


def changes() -> list[dict]:
    try:
        return [json.loads(l) for l in _log().read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


def may_use(ip: str = "", name: str = "") -> tuple[bool, str]:
    """Whether Nemo may talk to this device; the reason when not. Asked by
    casting before it connects."""
    if os.environ.get("NEMO_HOME_GATE") == "off":
        return True, ""
    d = next((d for d in known() if (ip and d.ip == ip) or (name and name in d.names)), None)
    label = name or ip
    if d is None:
        return False, (f"{label} is not in Home yet: open Home, look around, and set it to "
                       "Use (or: nemo home allow \"" + label + "\" use)")
    if d.permission != "use":
        return False, (f"{d.label} is set to {d.permission.capitalize()} in Home: set it to Use "
                       "there to let Nemo cast to it")
    return True, ""


# ---------------------------------------------------------------- the Device Keeper
@dataclass
class Board:
    project: str
    flashed: str = ""                # when the Test Bench last flashed it
    device: Device | None = None     # its device on the network, if it announces itself
    status: dict | None = None
    note: str = ""


def boards(cfg, devices: list[Device] | None = None, fetch=None) -> list[Board]:
    """The projects the Test Bench flashed, matched to boards that announce
    themselves as Nemo's (_nemo._tcp, named for their project)."""
    from . import review
    devices = devices if devices is not None else known()
    nemo_devs = [d for d in devices if "Nemo-built board" in d.kinds]
    out = []
    root = cfg.path("paths.projects")
    for proj in sorted(root.iterdir()) if root.is_dir() else []:
        runs = [e for e in review.work_log(proj) if e.get("event") == "flashed" and e.get("ok")]
        if not runs:
            continue
        b = Board(proj.name, time.strftime("%Y-%m-%d %H:%M", time.localtime(runs[-1].get("at", 0))))
        b.device = next((d for d in nemo_devs if proj.name.lower() in (n.lower() for n in d.names)), None)
        if b.device is None:
            b.note = ("flashed, not seen on the network: Nemo's bring-up firmware does not "
                      "announce itself yet")
        elif b.device.permission != "use":
            b.note = f"seen at {b.device.ip}; set it to Use to read its status"
        else:
            b.status, b.note = _status(b.device, fetch)
        out.append(b)
    return out


def _status(d: Device, fetch=None) -> tuple[dict | None, str]:
    """GET http://<ip>/status from a board allowed Use: JSON, or why not."""
    import urllib.request
    url = f"http://{d.ip}/status"
    try:
        raw = fetch(url) if fetch else urllib.request.urlopen(url, timeout=3).read()
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw), f"status read from {url}"
    except (OSError, ValueError) as exc:
        return None, f"its status page did not answer ({exc})"


# ---------------------------------------------------------------- the Writer
def write_list(cfg) -> Path:
    """The Writer: home-devices.md in the Storeroom, hidden devices left out."""
    devices = [d for d in known() if d.permission != "hidden"]
    lines = ["# Devices at home", "", f"Written by Nemo's Home Writer, {time.strftime('%Y-%m-%d %H:%M')}.",
             "", "| Device | Likely type | What it announces | Address | Nemo may |",
             "|---|---|---|---|---|"]
    for d in sorted(devices, key=lambda d: d.label.lower()):
        kind = device_type(d)[0] or "not known"
        lines.append(f"| {d.label} | {kind} | {', '.join(d.kinds) or '-'} | {d.ip or '-'} "
                     f"| {'use it' if d.permission == 'use' else 'only list it'} |")
    flashed = boards(cfg)
    if flashed:
        lines += ["", "## Boards you built", ""]
        lines += [f"- {b.project}: flashed {b.flashed}; {b.note}" for b in flashed]
    out = cfg.path("paths.storeroom") / "home-devices.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
