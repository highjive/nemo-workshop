"""Credits: everyone whose work Nemo is built from (owner, 2026-11-11: "Any
parts or code used in creating Nemo has a link at end of nemodoc run to
storehouse where shows all programmers and creators of programs used to
create it"; "My creative title in list will be only known as Highjive").

Nothing here is made up. Who made each thing comes from where it says so
itself:
  - the tools Nemo fetches and pins: the project their pinned source names
    (toolupdates.TOOLS, models from offline.MODEL_SOURCES), and a short table
    of the system programs the image installs, as each project names itself;
  - every Python package in Nemo's environment: its own published metadata
    (Author, Author-email names, Maintainer, licence), read at the time;
  - the homebrew games: their makers and licences as recorded when fetched
    (<storeroom>/games/HOMEBREW.txt).
E-mail addresses are never shown. Where a package names no one, it says so.

write() puts the page in the Storeroom (<storeroom>/credits/index.html, and
credits.txt beside it); NemoDoc writes it at the end of every run and gives
its link.
"""
from __future__ import annotations

import html
import importlib.metadata as _md
import re
from dataclasses import dataclass
from pathlib import Path

CREATOR = "Highjive"           # the owner's creative title, and the only name of his shown

# Nemo itself.
NEMO = [("Nemo", "the whole of it: the departments, their staff and every check",
         f"Created by {CREATOR}", "", ""),
        ("Claude (Anthropic)", "programming Nemo with " + CREATOR, "Anthropic", "", "https://www.anthropic.com")]

# Programs the image or NemoDoc installs that no pin list names, as each
# project names its own makers. (name, what Nemo uses it for, by, licence, link)
SYSTEM = [
    ("Python", "the language Nemo is written in", "the Python Software Foundation and contributors",
     "PSF-2.0", "https://www.python.org"),
    ("Tcl/Tk (tkinter)", "Nemo's windows", "the Tcl Core Team and contributors", "TCL (BSD-style)",
     "https://www.tcl-lang.org"),
    ("Debian", "NemoIso's operating system", "the Debian Project", "various (DFSG-free)",
     "https://www.debian.org"),
    ("KiCad", "schematics and circuit boards", "the KiCad developers", "GPL-3.0-or-later",
     "https://www.kicad.org"),
    ("Graphviz", "the wiring diagrams", "the Graphviz authors", "EPL-1.0", "https://graphviz.org"),
    ("PlatformIO", "building and flashing firmware", "PlatformIO Labs and contributors",
     "Apache-2.0", "https://platformio.org"),
    ("FreeCAD", "opening 3D models on NemoIso", "the FreeCAD contributors", "LGPL-2.0-or-later",
     "https://www.freecad.org"),
    ("Vosk", "hearing speech on the laptop", "Alpha Cephei", "Apache-2.0", "https://alphacephei.com/vosk"),
    ("eSpeak NG", "Nemo's voice on NemoIso", "the eSpeak NG contributors", "GPL-3.0-or-later",
     "https://github.com/espeak-ng/espeak-ng"),
    ("Ghidra", "the Reverse Engineer's decompiler", "the National Security Agency (NSA)",
     "Apache-2.0", "https://ghidra-sre.org"),
    ("Eclipse Temurin (Java)", "running Ghidra and Freerouting", "Eclipse Adoptium",
     "GPL-2.0 with Classpath Exception", "https://adoptium.net"),
    ("Node.js", "running REA", "the OpenJS Foundation and Node.js contributors", "MIT",
     "https://nodejs.org"),
    ("Firefox ESR", "opening web pages and drawings on NemoIso", "Mozilla", "MPL-2.0",
     "https://www.mozilla.org/firefox"),
    ("VLC", "the Theatre's player on NemoIso", "VideoLAN", "GPL-2.0-or-later", "https://www.videolan.org"),
]

# A model's family, by the start of Nemo's own name for it: who made the model.
MODEL_MAKERS = (("qwen", "the Qwen team (Alibaba Cloud)"), ("gemma", "Google"))


@dataclass(frozen=True)
class Credit:
    name: str
    used_for: str
    by: str
    licence: str = ""
    link: str = ""
    group: str = ""


_EMAIL = re.compile(r"\s*<[^>]*>|\S+@\S+")


def _people(text: str | None) -> str:
    """Names only: e-mail addresses taken out."""
    if not text:
        return ""
    names = [_EMAIL.sub("", part).strip(" ,\"'") for part in re.split(r",(?![^<]*>)", text)]
    return ", ".join(n for n in names if n)


def python_packages() -> list[Credit]:
    out, seen = [], set()
    for d in _md.distributions():
        m = d.metadata
        name = m.get("Name") or ""
        if not name or name.lower() in seen or name.lower() == "nemo":
            continue
        seen.add(name.lower())
        by = (_people(m.get("Author")) or _people(m.get("Author-email"))
              or _people(m.get("Maintainer")) or _people(m.get("Maintainer-email")))
        lic = m.get("License-Expression") or (m.get("License") or "").splitlines()[0:1]
        lic = lic if isinstance(lic, str) else (lic[0] if lic else "")
        if not lic:
            lic = next((c.split("::")[-1].strip() for c in (m.get_all("Classifier") or [])
                        if c.startswith("License ::")), "")
        link = m.get("Home-page") or ""
        if not link:
            link = next((u.split(",", 1)[1].strip() for u in (m.get_all("Project-URL") or [])
                         if "," in u), "")
        out.append(Credit(f"{name} {d.version}", "a Python package Nemo uses",
                          by or "(its package names no maker)", lic[:60], link, "Python packages"))
    return sorted(out, key=lambda c: c.name.lower())


def tools() -> list[Credit]:
    from .toolupdates import TOOLS
    out = []
    for t in TOOLS:
        kind, _, where = t.feed.partition(":")
        if kind == "github":
            owner = where.split("/")[0]
            by, link = f"{owner} and the project's contributors", f"https://github.com/{where}"
        else:
            by, link = f"the {where} package's authors (npm)", f"https://www.npmjs.com/package/{where}"
        out.append(Credit(t.label.split(" (")[0], t.label.split(" (", 1)[1].rstrip(")")
                          if " (" in t.label else "", by, "", link, "Tools Nemo fetches and pins"))
    return out


def models() -> list[Credit]:
    from .offline import MODEL_SOURCES
    out = []
    for name, (repo, _file) in sorted(MODEL_SOURCES.items()):
        maker = next((who for start, who in MODEL_MAKERS if name.startswith(start)), "")
        packed = repo.split("/")[0]
        by = (f"{maker}; the GGUF file by {packed}" if maker else f"the GGUF file by {packed}")
        out.append(Credit(name, "a language model Nemo runs", by, "see its model page",
                          f"https://huggingface.co/{repo}", "Language models"))
    return out


def games(storeroom: Path) -> list[Credit]:
    f = Path(storeroom) / "games" / "HOMEBREW.txt"
    out = []
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return out
    for m in re.finditer(r"^(\S[^:\n]*): (.+)\n\s+by ([^;\n]+); licence ([^\n]+)\n\s+from (\S+)",
                         text, re.M):
        system, title, by, lic, url = (x.strip() for x in m.groups())
        out.append(Credit(title, f"a homebrew game to test the {system} emulator", by, lic, url,
                          "Homebrew games"))
    return out


def everyone(cfg) -> list[Credit]:
    out = [Credit(*row, group="Nemo") for row in NEMO]
    out += tools()
    out += [Credit(*row, group="Programs on NemoIso and Windows") for row in SYSTEM]
    out += models()
    out += python_packages()
    out += games(cfg.path("paths.storeroom"))
    return out


def page(credits: list[Credit]) -> str:
    e = html.escape
    groups: dict[str, list[Credit]] = {}
    for c in credits:
        groups.setdefault(c.group, []).append(c)
    rows = []
    for g, items in groups.items():
        rows.append(f"<h2>{e(g)}</h2><table><tr><th>What</th><th>Made by</th><th>What Nemo uses it for"
                    "</th><th>Licence</th></tr>")
        for c in items:
            name = (f'<a href="{e(c.link)}">{e(c.name)}</a>' if c.link else e(c.name))
            rows.append(f"<tr><td>{name}</td><td>{e(c.by)}</td><td>{e(c.used_for)}</td>"
                        f"<td>{e(c.licence)}</td></tr>")
        rows.append("</table>")
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><title>Nemo: credits</title>"
            "<style>body{font-family:sans-serif;margin:2em;background:#f6efe0;color:#2b1e13}"
            "table{border-collapse:collapse;width:100%;margin-bottom:1.5em}"
            "td,th{border-bottom:1px solid #c49a52;padding:4px 8px;text-align:left;vertical-align:top}"
            "th{background:#e8d7b0}</style></head><body>"
            f"<h1>Nemo: who made it</h1><p>Nemo was created by {e(CREATOR)}. It is built from the work "
            f"of everyone below: {len(credits)} programs, packages, models and games, each as its "
            "own makers name themselves.</p>" + "".join(rows) + "</body></html>\n")


def text(credits: list[Credit]) -> str:
    out = [f"Nemo: who made it. Created by {CREATOR}.", ""]
    group = None
    for c in credits:
        if c.group != group:
            group = c.group
            out += ["", group.upper()]
        out.append(f"  {c.name}: {c.by}" + (f" ({c.licence})" if c.licence else ""))
    return "\n".join(out) + "\n"


def folder(cfg) -> Path:
    return cfg.path("paths.storeroom") / "credits"


def write(cfg) -> Path:
    """Write the credits page into the Storeroom; returns index.html."""
    credits = everyone(cfg)
    d = folder(cfg)
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(page(credits), encoding="utf-8")
    (d / "credits.txt").write_text(text(credits), encoding="utf-8")
    return d / "index.html"
