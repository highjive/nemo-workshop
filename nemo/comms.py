"""Communications: the web, letters, email and social media, with nothing
sent, posted or logged into by Nemo (owner, 2026-10-22: "web browser, email,
social media" and "letters and messages").

  Browser  opens the web in your own browser (Chrome, as the Theatre's
           Streamer does), and keeps your bookmarks
  Postman  keeps an address book; opens your mail program with a draft
           filled in (a mailto: link, handled on this computer), or copies
           the draft and opens your webmail, so the text never goes into a
           web address. You press Send.
  Social   your social sites, as bookmarks; a post is drafted here and
           copied for you to paste. Nemo never logs in or posts.
  Writer   letters, emails and posts, from your own words: spell-checked
           (Harper, British spelling, as the Library's Writer), a letter laid
           out with the date, greeting and sign-off. The model is not asked.

Everything is kept in <storeroom>/comms: bookmarks.json, contacts.json and
drafts/, which backups keep. No password is asked for or kept.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path

KINDS = ("web", "mail", "social")
MAILTO_LIMIT = 1800          # a mailto: link longer than this is cut by some mail programs


class CommsError(ValueError):
    pass


def home(cfg) -> Path:
    return cfg.path("paths.storeroom") / "comms"


def _read(path: Path, default):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, type(default)) else default
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- the Browser
@dataclass
class Bookmark:
    name: str
    url: str
    kind: str = "web"                 # web, mail (a webmail inbox) or social


def _url(url: str) -> str:
    url = url.strip()
    if not url:
        raise CommsError("give the web address")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if not parts.netloc or " " in parts.netloc or "." not in parts.netloc:
        raise CommsError(f"{url!r} is not a web address")
    return url


def bookmarks(cfg) -> list[Bookmark]:
    return [Bookmark(**b) for b in _read(home(cfg) / "bookmarks.json", [])
            if isinstance(b, dict) and b.get("name") and b.get("url")]


def add_bookmark(cfg, name: str, url: str, kind: str = "web") -> Bookmark:
    if kind not in KINDS:
        raise CommsError(f"a bookmark is {', '.join(KINDS)}, not {kind!r}")
    if not name.strip():
        raise CommsError("give the bookmark a name")
    b = Bookmark(name.strip(), _url(url), kind)
    kept = [x for x in bookmarks(cfg) if x.name.lower() != b.name.lower()] + [b]
    _write(home(cfg) / "bookmarks.json", [asdict(x) for x in kept])
    return b


def remove_bookmark(cfg, name: str) -> bool:
    kept = bookmarks(cfg)
    left = [b for b in kept if b.name.lower() != name.strip().lower()]
    _write(home(cfg) / "bookmarks.json", [asdict(x) for x in left])
    return len(left) < len(kept)


def open_web(target: str, cfg=None, opener=None) -> str:
    """The Browser: a bookmark by name, or a web address, in Chrome."""
    from . import theatre
    b = next((b for b in bookmarks(cfg) if b.name.lower() == target.strip().lower()),
             None) if cfg is not None else None
    url = b.url if b else _url(target)
    return (opener or theatre.stream)(url)


# ---------------------------------------------------------------- the Postman
@dataclass
class Contact:
    name: str
    email: str = ""
    address: str = ""                 # for a letter: the lines of a postal address
    notes: str = ""


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def contacts(cfg) -> list[Contact]:
    return [Contact(**c) for c in _read(home(cfg) / "contacts.json", [])
            if isinstance(c, dict) and c.get("name")]


def add_contact(cfg, name: str, email: str = "", address: str = "", notes: str = "") -> Contact:
    if not name.strip():
        raise CommsError("give the contact a name")
    if email and not _EMAIL.match(email.strip()):
        raise CommsError(f"{email!r} is not an email address")
    c = Contact(name.strip(), email.strip(), address.strip(), notes.strip())
    kept = [x for x in contacts(cfg) if x.name.lower() != c.name.lower()] + [c]
    _write(home(cfg) / "contacts.json", [asdict(x) for x in sorted(kept, key=lambda x: x.name.lower())])
    return c


def find_contact(cfg, name: str) -> Contact | None:
    n = name.strip().lower()
    if not n:                     # an empty name matched any contact with no email address
        return None
    return next((c for c in contacts(cfg) if n in (c.name.lower(), c.email.lower())), None)


@dataclass
class Draft:
    kind: str                         # email, letter or post
    to: str = ""                      # a contact's name, an address, or a site
    subject: str = ""
    body: str = ""
    spelling: list[str] = field(default_factory=list)
    path: Path | None = None


def mailto(to: str, subject: str, body: str) -> str:
    """A mailto: link for this computer's own mail program."""
    q = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{urllib.parse.quote(to, safe='@')}?{q}"


def open_link(link: str, starter=None) -> None:
    """Hand a link to this computer (mailto: goes to the mail program)."""
    if starter is not None:
        starter(link)
    elif sys.platform.startswith("win"):
        import os
        os.startfile(link)                                     # noqa: S606 (the owner's own link)
    else:
        subprocess.Popen(["xdg-open", link])


def send_by_mail_program(cfg, draft: Draft, starter=None) -> str:
    """The Postman: the mail program opens with the draft in it; the owner
    sends it. A body too long for a link is left for the owner to paste."""
    c = find_contact(cfg, draft.to)
    to = c.email if c and c.email else draft.to
    if not _EMAIL.match(to or ""):
        raise CommsError(f"{draft.to!r} has no email address; add one to the contact")
    link = mailto(to, draft.subject, draft.body)
    if len(link) > MAILTO_LIMIT:
        open_link(mailto(to, draft.subject, ""), starter)
        return "the mail program is open with the address and subject; paste the text (it is copied)"
    open_link(link, starter)
    return "the mail program is open with the draft in it: check it and press Send"


# ---------------------------------------------------------------- the Writer
def spell(text: str, cfg=None, known=()) -> list[str]:
    """Harper's words on the text, as lines; [] when all is well. Where
    Harper is not here, one line says the spelling was not checked. `known`:
    words that are right as written (the contact's own name and address:
    "Fenwick", "Tetbury" and "GL8" were called misspellings, 2026-11-08)."""
    from . import writer
    found = writer.check(text, list(known), cfg=cfg)
    if found is None:
        return ["the spelling was not checked: Harper is not installed"]
    # An initial ("A. Owner" under a letter) is not a misspelling (2026-11-06).
    return [f"\"{l.matched}\": {l.message}" + (f" (perhaps {', '.join(l.suggestions[:3])})"
                                                if l.suggestions else "") for l in found
            if not re.fullmatch(r"[A-Z]\.?", l.matched.strip())]


# Words that make a name a firm's or an office's, not a person's.
ORGANISATION = ("ltd", "limited", "plc", "llp", "inc", "co", "company", "centre", "center",
                "council", "shop", "store", "stores", "bank", "services", "hospital",
                "surgery", "school", "college", "university", "club", "society",
                "department", "office", "agency", "association", "trust", "group",
                "garage", "hotel", "restaurant", "cafe", "library", "museum", "church",
                "team", "support", "customer", "sales", "accounts", "enquiries", "hmrc",
                "dvla", "nhs", "the")


def organisation(name: str) -> bool:
    """A name that is a firm's or an office's, by its own words."""
    return any(w in ORGANISATION for w in re.findall(r"[a-z]+", name.lower()))


TITLES = ("mr", "mrs", "ms", "miss", "mx", "dr", "prof", "professor", "sir", "dame", "lady",
          "lord", "rev", "revd", "reverend", "captain", "capt")


def greeting(name: str) -> str:
    """Who "Dear ..." names, in British form: a title takes the surname
    ("Mrs Ada Fenwick": "Mrs Fenwick"; it began "Dear Mrs," 2026-11-08), a
    plain name its first name ("Ada Fenwick": "Ada")."""
    words = name.split()
    if not words:
        return ""
    if words[0].rstrip(".").lower() in TITLES:
        return f"{words[0]} {words[-1]}" if len(words) > 1 else words[0]
    return words[0]


def letter(cfg, to: str, body: str, sender: str = "", when: str | None = None) -> str:
    """A letter laid out: the date, the address if the contact has one, a
    greeting, the owner's words, and a sign-off."""
    c = find_contact(cfg, to)
    name = c.name if c else to.strip()
    lines = [when or time.strftime("%d %B %Y").lstrip("0"), ""]
    if c and c.address:
        lines += [name] + [l.strip() for l in c.address.splitlines() if l.strip()] + [""]
    # A firm or an office has no first name (2026-11-06: a letter to "Sample
    # Garden Centre" began "Dear Sample,").
    first = greeting(name) if name and not organisation(name) else ""
    lines += [f"Dear {first}," if first else "Dear Sir or Madam,", "", body.strip(), ""]
    # British usage: "Dear Sir or Madam" closes "Yours faithfully", a name "Yours sincerely".
    lines += ["Yours sincerely," if first else "Yours faithfully,", "", sender.strip()]
    return "\n".join(lines).rstrip() + "\n"


def save_draft(cfg, draft: Draft) -> Draft:
    """The Writer keeps every draft, spell-checked, in drafts/."""
    if not draft.body.strip():
        raise CommsError("the draft is empty")
    c = find_contact(cfg, draft.to) if draft.to else None
    own = re.findall(r"[A-Za-z0-9]+", f"{draft.to} {c.name} {c.address}" if c else draft.to or "")
    draft.spelling = spell(f"{draft.subject}\n\n{draft.body}", cfg, own)
    folder = home(cfg) / "drafts"
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", f"{draft.kind} {draft.to} {draft.subject}").strip()[:60]
    draft.path = folder / f"{time.strftime('%Y-%m-%d %H%M%S')} {stem or draft.kind}.md"
    head = [f"# {draft.kind.capitalize()}" + (f" to {draft.to}" if draft.to else "")]
    if draft.subject:
        head.append(f"Subject: {draft.subject}")
    draft.path.write_text("\n".join(head) + "\n\n" + draft.body.strip() + "\n", encoding="utf-8")
    return draft


def drafts(cfg) -> list[Path]:
    folder = home(cfg) / "drafts"
    return sorted(folder.glob("*.md"), reverse=True) if folder.is_dir() else []
