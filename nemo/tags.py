"""The tags inside a music file: title, artist, album and track number
(the Music Room, owner 2026-10-22: "read tags").

Read with Nemo's own code, nothing downloaded or installed:
  MP3       ID3v2.2/2.3/2.4 text frames at the start, else the ID3v1 block
            at the end
  M4A/MP4   the iTunes-style list in moov/udta/meta/ilst
  FLAC      its VORBIS_COMMENT metadata block
  Ogg, Opus the Vorbis comment packet ("\\x03vorbis" or "OpusTags") on the
            first pages
WMA and WAV are not read. A tag that cannot be read is left out, never
guessed; the Music Room then uses the folders, as before.
"""
from __future__ import annotations

import struct
from pathlib import Path

WANTED = ("title", "artist", "album", "number")


def _text(raw: bytes, enc: int) -> str:
    try:
        if enc == 0:
            s = raw.decode("latin-1")
        elif enc == 1:
            s = raw.decode("utf-16")
        elif enc == 2:
            s = raw.decode("utf-16-be")
        else:
            s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return s.split("\0")[0].strip()


def _number(s: str) -> int:
    head = s.strip().split("/")[0]
    return int(head) if head.isdigit() else 0


# ---------------------------------------------------------------- MP3
_ID3 = {"TIT2": "title", "TPE1": "artist", "TALB": "album", "TRCK": "number",
        "TT2": "title", "TP1": "artist", "TAL": "album", "TRK": "number"}


def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _id3v2(data: bytes) -> dict:
    if data[:3] != b"ID3" or len(data) < 10:
        return {}
    major, flags = data[3], data[5]
    end = 10 + _syncsafe(data[6:10])
    if flags & 0x80 and major < 4:                         # the whole tag "unsynchronised"
        body = data[10:end].replace(bytes([0xFF, 0x00]), bytes([0xFF]))
        data, end = data[:10] + body, 10 + len(body)
    pos = 10
    if flags & 0x40 and major >= 3:                        # an extended header
        pos += (_syncsafe(data[10:14]) if major == 4 else struct.unpack(">I", data[10:14])[0] + 4)
    out: dict = {}
    while pos + (6 if major == 2 else 10) <= min(end, len(data)):
        if major == 2:
            fid, size, head = data[pos:pos + 3].decode("latin-1"), int.from_bytes(data[pos + 3:pos + 6], "big"), 6
        else:
            fid = data[pos:pos + 4].decode("latin-1")
            size = (_syncsafe(data[pos + 4:pos + 8]) if major == 4
                    else struct.unpack(">I", data[pos + 4:pos + 8])[0])
            head = 10
        if not fid.strip("\0") or size <= 0:
            break
        body = data[pos + head:pos + head + size]
        key = _ID3.get(fid)
        if key and body and key not in out:
            value = _text(body[1:], body[0])
            if value:
                out[key] = _number(value) if key == "number" else value
        pos += head + size
    return out


def _id3v1(tail: bytes) -> dict:
    if len(tail) < 128 or tail[-128:-125] != b"TAG":
        return {}
    t = tail[-128:]
    out = {k: t[a:b].split(b"\0")[0].decode("latin-1").strip()
           for k, (a, b) in (("title", (3, 33)), ("artist", (33, 63)), ("album", (63, 93)))}
    out = {k: v for k, v in out.items() if v}
    if t[125] == 0 and t[126]:                             # ID3v1.1 track number
        out["number"] = t[126]
    return out


# ---------------------------------------------------------------- Vorbis comments
_VORBIS = {"TITLE": "title", "ARTIST": "artist", "ALBUM": "album", "TRACKNUMBER": "number"}


def _comments(data: bytes, pos: int) -> dict:
    """A Vorbis comment block starting at pos (vendor, then KEY=value)."""
    out: dict = {}
    try:
        n = struct.unpack_from("<I", data, pos)[0]
        pos += 4 + n
        count = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        for _ in range(min(count, 500)):
            n = struct.unpack_from("<I", data, pos)[0]
            entry = data[pos + 4:pos + 4 + n].decode("utf-8", "replace")
            pos += 4 + n
            k, _, v = entry.partition("=")
            key = _VORBIS.get(k.upper())
            if key and v.strip() and key not in out:
                out[key] = _number(v) if key == "number" else v.strip()
    except struct.error:
        pass                                             # cut short: keep what was read
    return out


def _flac(data: bytes) -> dict:
    if data[:4] != b"fLaC":
        return {}
    pos = 4
    while pos + 4 <= len(data):
        head = data[pos]
        size = int.from_bytes(data[pos + 1:pos + 4], "big")
        if head & 0x7F == 4:
            return _comments(data, pos + 4)
        if head & 0x80:
            break
        pos += 4 + size
    return {}


def _ogg(data: bytes) -> dict:
    """The comment packet, with the Ogg page headers in between taken out:
    a long comment runs over pages."""
    if data[:4] != b"OggS":
        return {}
    body, pos = bytearray(), 0
    while pos + 27 <= len(data) and data[pos:pos + 4] == b"OggS":
        segs = data[pos + 26]
        table = data[pos + 27:pos + 27 + segs]
        start = pos + 27 + segs
        body += data[start:start + sum(table)]
        pos = start + sum(table)
    for mark in (b"\x03vorbis", b"OpusTags"):
        at = body.find(mark)
        if at >= 0:
            return _comments(bytes(body), at + len(mark))
    return {}


# ---------------------------------------------------------------- M4A
_ILST = {b"\xa9nam": "title", b"\xa9ART": "artist", b"\xa9alb": "album", b"trkn": "number"}


def _m4a(path: Path) -> dict:
    from .mediainfo import _boxes, _child
    out: dict = {}
    with open(path, "rb") as f:
        place = (0, path.stat().st_size)
        for kind in (b"moov", b"udta", b"meta"):
            place = _child(f, *place, kind) if place else None
        if not place:
            return {}
        ilst = _child(f, place[0] + 4, place[1], b"ilst")   # meta is a full box: 4 bytes more
        if not ilst:
            return {}
        for kind, b, e in _boxes(f, *ilst):
            key = _ILST.get(kind)
            data = _child(f, b, e, b"data") if key else None
            if not data:
                continue
            f.seek(data[0] + 8)                            # type and locale
            raw = f.read(data[1] - data[0] - 8)
            if key == "number":
                if len(raw) >= 4:
                    out[key] = int.from_bytes(raw[2:4], "big")
            else:
                value = raw.decode("utf-8", "replace").strip()
                if value:
                    out[key] = value
    return out


def read(path: Path) -> dict:
    """The tags found, a dict with some of title, artist, album, number."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix in (".m4a", ".mp4"):
            return _m4a(path)
        with open(path, "rb") as f:
            head = f.read(256 * 1024)
            if suffix == ".mp3":
                found = _id3v2(head)
                if len(found) < 3:
                    f.seek(max(0, path.stat().st_size - 128))
                    found = {**_id3v1(f.read(128)), **found}
                return found
        if suffix == ".flac":
            return _flac(head)
        if suffix in (".ogg", ".opus"):
            return _ogg(head)
    except (OSError, ValueError, struct.error):
        return {}
    return {}
