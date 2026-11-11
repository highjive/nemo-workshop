"""The Workshop's Researcher looks online for what the Inspector found missing.

Owner's request, 2026-10-18: "researcher should be able to find fixes from
internet to pass to reviewer for missing parts". When the Inspector (the
Reviewer until 2026-10-21) stops a step for a thing no part in the library
is, or a part name the library does not know, the Researcher searches Mouser's parts catalogue and keeps what it
found with the project. The Inspector then offers each find as a fix: a part
with its datasheet, to open.

Mouser, the owner's choice: DuckDuckGo was tried first and answered the
second query with a human check, which Nemo must not get round. Mouser's
Search API is meant for programs and needs a free key, which the owner
enters (Researcher key, in the window); it is read from the environment or
the key file, never from the config, the repository or the image.

What is sent: the missing thing and the board's name ("RFID reader module
ESP32"), never the brief. What comes back is a suggestion, not a part: no
figure found online goes into the parts library unread (docs/design-rules.md: never
invent a datasheet figure). Adding the part, from its datasheet, stays the
owner's job ("Add a part").

NOT VERIFIED: the reply's shape is Mouser's documented Search API v1
(SearchResults.Parts[], each with Manufacturer, ManufacturerPartNumber,
Description, DataSheetUrl, ProductDetailUrl). No call has been made with a
real key yet; the tests use that documented shape.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

API = "https://api.mouser.com/api/v1/search/keyword?apiKey="
MAX_FINDS = 5


@dataclass
class Find:
    title: str
    url: str
    snippet: str = ""
    datasheet: str = ""


# ---------------------------------------------------------------- the key
def key_file() -> Path:
    return Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo")) / "keys" / "mouser.key"


def key() -> str | None:
    """The Mouser key: the environment first, then the key file the window
    writes. Never the config file or the repository."""
    from .config import Config
    k = Config.api_key("mouser")
    if k:
        return k
    try:
        k = key_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return k or None


def key_looks_right(value: str) -> bool:
    """Mouser's API keys are GUIDs, 8-4-4-4-12 hex. The first one entered
    on the AH531 had 35 characters, and Mouser refused it ("Invalid unique
    identifier"); a key of the wrong shape is worth a warning on entry."""
    import re
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                             r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value.strip()))


def save_key(value: str) -> Path:
    p = key_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


# ------------------------------------------------------------- searching
def parse(reply: dict) -> tuple[list[Find], str]:
    """Finds from a Mouser keyword-search reply, or ([], its error)."""
    errors = reply.get("Errors") or []
    if errors:
        msg = "; ".join(str(e.get("Message", e)) if isinstance(e, dict) else str(e)
                        for e in errors)
        if "unique identifier" in msg.lower():
            msg += " (the Researcher key is not one Mouser knows: enter it again)"
        return [], f"Mouser said: {msg}"
    parts = ((reply.get("SearchResults") or {}).get("Parts")) or []
    out = []
    for p in parts:
        name = " ".join(x for x in (p.get("Manufacturer", ""),
                                    p.get("ManufacturerPartNumber", "")) if x)
        url = p.get("ProductDetailUrl") or p.get("DataSheetUrl") or ""
        if not (name and url):
            continue
        out.append(Find(name, url, p.get("Description", ""), p.get("DataSheetUrl", "")))
    return out, ""


def search(query: str, timeout: float = 20) -> tuple[list[Find], str]:
    """(finds, '') or ([], why not)."""
    k = key()
    if not k:
        return [], ("no Mouser key is set: give one under Researcher key, or search "
                    "by hand")
    body = json.dumps({"SearchByKeywordRequest": {
        "keyword": query, "records": MAX_FINDS, "startingRecord": 0,
        "searchOptions": "", "searchWithYourSignUpLanguage": ""}}).encode()
    req = urllib.request.Request(API + k, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            reply = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return [], f"Mouser refused the search (HTTP {exc.code})"
    except (OSError, ValueError) as exc:
        return [], f"the search could not be made ({exc})"
    finds, why = parse(reply)
    if why:
        return [], why
    if not finds:
        return [], "Mouser found no part for it"
    return finds, ""


# ------------------------------------------------------------ the job
def path(project_root: Path) -> Path:
    return Path(project_root) / ".nemo" / "research.json"


def load(project_root: Path) -> dict:
    try:
        return json.loads(path(project_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def query_for(key_: str, thing: str, board: str) -> str:
    """Words a parts catalogue matches: the thing without its article, and
    the board's family. Never the brief."""
    thing = thing.removeprefix("an ").removeprefix("a ")
    if key_ == "unknown_parts":
        return thing.replace("_", " ")
    family = next((f for f in ("ESP32", "RP2040", "Pico") if f.lower() in board.lower()), "")
    return f"{thing} module {family}".strip()


def look_up(project_root: Path, wants: list[tuple[str, str]], board: str = "",
            searcher=None) -> dict:
    """Search for each (key, thing) not found before; keep the finds with
    the project. A search that failed is tried again next time."""
    searcher = searcher or search
    kept = load(project_root)
    for key_, thing in wants:
        tag = f"{key_}:{thing}"
        if tag in kept and kept[tag].get("finds"):
            continue
        q = query_for(key_, thing, board)
        finds, why = searcher(q)
        kept[tag] = {"query": q, "at": int(time.time()), "why": why,
                     "finds": [asdict(f) for f in finds[:MAX_FINDS]]}
    p = path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(kept, indent=1), encoding="utf-8")
    return kept


def finds_for(project_root: Path, key_: str) -> list[tuple[str, dict]]:
    """(thing, record) for every search kept under this Inspector key."""
    return [(tag.split(":", 1)[1], rec) for tag, rec in load(project_root).items()
            if tag.split(":", 1)[0] == key_]
