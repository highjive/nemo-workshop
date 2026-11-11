"""What is inside a video file, and whether a Chromecast will play it
(the Theatre, owner 2026-10-22: "codec check").

Read from the file itself, with no other program: an MP4's boxes (each
track's sample entry, and for H.264 and H.265 its profile and level), or a
WebM or Matroska file's codec names. Nothing is converted.

What each Chromecast plays is Google's own list (developers.google.com/cast/
docs/media, read 2026-10-22):

  Chromecast 1st, 2nd gen   H.264 High up to level 4.1; VP8
  Chromecast 3rd gen        H.264 High up to level 4.2; VP8
  Chromecast Ultra          H.264 up to 4.2; VP8; H.265 Main/Main10 up to 5.1; VP9
  Chromecast with Google TV H.264 up to 5.1; H.265 up to 5.1; VP9
  Google TV Streamer        H.264 up to 5.2; H.265 up to 5.1; VP9; AV1 up to 5.1

The page lists AAC, MP3, Opus, Vorbis, FLAC and WAV for sound, and AC-3,
E-AC-3 and the like under passthrough: sent on to a TV or amplifier that
decodes them, so they may play silent. A Chromecast that only calls
itself "Chromecast" may be any of the first three, so the oldest's limits
are used for it.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

# The H.264 level each model plays up to, and which other codecs it has.
DEVICES = {
    "Chromecast": (41, {"vp8"}),
    "Chromecast Ultra": (42, {"vp8", "hevc", "vp9"}),
    "Chromecast with Google TV": (51, {"vp8", "hevc", "vp9"}),
    "Google TV Streamer": (52, {"vp8", "hevc", "vp9", "av1"}),
}
SOUND_OK = {"aac", "mp3", "opus", "vorbis", "flac", "pcm"}
SOUND_PASSTHROUGH = {"ac3", "eac3"}
NAMES = {"h264": "H.264", "hevc": "H.265 (HEVC)", "vp8": "VP8", "vp9": "VP9", "av1": "AV1",
         "aac": "AAC", "mp3": "MP3", "opus": "Opus", "vorbis": "Vorbis", "flac": "FLAC",
         "pcm": "WAV (PCM)", "ac3": "AC-3 (Dolby Digital)", "eac3": "E-AC-3 (Dolby Digital Plus)"}

_MP4_VIDEO = {b"avc1": "h264", b"avc3": "h264", b"hvc1": "hevc", b"hev1": "hevc",
              b"vp08": "vp8", b"vp09": "vp9", b"av01": "av1"}
_MP4_SOUND = {b"mp4a": "aac", b".mp3": "mp3", b"Opus": "opus", b"fLaC": "flac",
              b"ac-3": "ac3", b"ec-3": "eac3", b"lpcm": "pcm", b"sowt": "pcm"}
_MKV = {b"V_MPEG4/ISO/AVC": "h264", b"V_MPEGH/ISO/HEVC": "hevc", b"V_VP8": "vp8",
        b"V_VP9": "vp9", b"V_AV1": "av1", b"A_AAC": "aac", b"A_MPEG/L3": "mp3",
        b"A_OPUS": "opus", b"A_VORBIS": "vorbis", b"A_FLAC": "flac", b"A_PCM": "pcm",
        b"A_EAC3": "eac3", b"A_AC3": "ac3"}
_H264_PROFILES = {66: "Baseline", 77: "Main", 88: "Extended", 100: "High", 110: "High 10",
                  122: "High 4:2:2", 244: "High 4:4:4"}


class MediaError(ValueError):
    pass


@dataclass
class Media:
    container: str
    video: str = ""                 # a key of NAMES, or "" when there is none
    profile: str = ""
    level: int | None = None        # H.264/H.265 level x10: 41 is level 4.1
    size: tuple[int, int] | None = None
    sound: list[str] = field(default_factory=list)


# --------------------------------------------------------------------
#  MP4
# --------------------------------------------------------------------

def _boxes(f, start: int, end: int):
    """(type, body start, body end) for each box from start to end."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            return
        size, kind = struct.unpack(">I4s", head)
        body = pos + 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            body = pos + 16
        elif size == 0:
            size = end - pos
        if size < 8 or pos + size > end:
            return
        yield kind, body, pos + size
        pos += size


def _child(f, start: int, end: int, kind: bytes):
    return next(((b, e) for k, b, e in _boxes(f, start, end) if k == kind), None)


def _mp4(path: Path) -> Media:
    m = Media("MOV" if path.suffix.lower() == ".mov" else "MP4")    # the same boxes
    with open(path, "rb") as f:
        total = path.stat().st_size
        moov = _child(f, 0, total, b"moov")
        if moov is None:
            raise MediaError(f"{path.name}: no 'moov' box, so not a readable MP4")
        for kind, tb, te in _boxes(f, *moov):
            if kind != b"trak":
                continue
            mdia = _child(f, tb, te, b"mdia")
            if not mdia:
                continue
            hdlr = _child(f, *mdia, b"hdlr")
            handler = b""
            if hdlr:
                f.seek(hdlr[0] + 8)            # after version, flags and pre_defined
                handler = f.read(4)
            path_ = mdia
            for k in (b"minf", b"stbl", b"stsd"):
                path_ = _child(f, *path_, k) if path_ else None
            if not path_:
                continue
            # stsd: version/flags (4), count (4), then the first sample entry
            entry = next(_boxes(f, path_[0] + 8, path_[1]), None)
            if entry is None:
                continue
            fourcc, eb, ee = entry
            if handler == b"vide" and not m.video:
                m.video = _MP4_VIDEO.get(fourcc, fourcc.decode("latin-1").strip())
                f.seek(eb + 24)
                w, h = struct.unpack(">HH", f.read(4))
                m.size = (w, h)
                # the codec's own box follows the 78-byte visual sample entry
                for k, cb, ce in _boxes(f, eb + 78, ee):
                    f.seek(cb)
                    data = f.read(min(ce - cb, 16))
                    if k == b"avcC" and len(data) >= 4:
                        m.profile = _H264_PROFILES.get(data[1], f"profile {data[1]}")
                        m.level = data[3]
                    elif k == b"hvcC" and len(data) >= 13:
                        m.profile = {1: "Main", 2: "Main 10"}.get(data[1] & 0x1F,
                                                                 f"profile {data[1] & 0x1F}")
                        m.level = round(data[12] / 3)          # general_level_idc is 30 x level
            elif handler == b"soun":
                m.sound.append(_MP4_SOUND.get(fourcc, fourcc.decode("latin-1").strip()))
    return m


def _matroska(path: Path) -> Media:
    """WebM or Matroska: the codec names, from the start of the file where
    the track list is. Their profile and level are not read."""
    with open(path, "rb") as f:
        head = f.read(4 * 1024 * 1024)
    if not head.startswith(b"\x1a\x45\xdf\xa3"):
        raise MediaError(f"{path.name} is not a WebM or Matroska file")
    m = Media("WebM" if b"webm" in head[:64] else "Matroska")
    # CodecID is element 0x86; a one-byte size (0x80 | length) follows it.
    for hit in re.finditer(rb"\x86([\x83-\x98])(?=[AV]_)", head):
        cid = head[hit.end():hit.end() + (hit[1][0] & 0x7F)]
        code = _MKV.get(cid) or next((v for k, v in _MKV.items() if cid.startswith(k + b"/")), None)
        if code is None:
            continue
        if code in ("h264", "hevc", "vp8", "vp9", "av1"):
            m.video = m.video or code
        else:
            m.sound.append(code)
    return m


def probe(path: Path) -> Media:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".mp4", ".m4v", ".mov"):
        return _mp4(path)
    if suffix in (".webm", ".mkv"):
        return _matroska(path)
    raise MediaError(f"{path.name}: Nemo reads MP4, M4V, MOV, WebM and MKV files")


# --------------------------------------------------------------------
#  Will it play?
# --------------------------------------------------------------------

def _device(model: str | None) -> str | None:
    if not model:
        return None
    m = model.lower()
    if "streamer" in m:
        return "Google TV Streamer"
    if "google tv" in m:
        return "Chromecast with Google TV"
    if "ultra" in m:
        return "Chromecast Ultra"
    if m.startswith("chromecast"):
        return "Chromecast"
    return None


def _plays(m: Media, device: str) -> bool | None:
    top, has = DEVICES[device]
    if m.video == "h264":
        if m.level is None:
            return None                                        # a level not read: not sure
        if device == "Chromecast" and m.level == 42:
            return None                                        # a 3rd gen plays it, a 1st does not
        return m.level <= top
    return m.video in has or not m.video


def verdict(m: Media, model: str | None = None) -> tuple[bool | None, list[str]]:
    """(True: it plays, False: it will not, None: not sure) and the reasons,
    for this Chromecast model, or for any when the model is not known."""
    lines = []
    what = NAMES.get(m.video, m.video or "no video")
    if m.profile or m.level:
        what += f" {m.profile}".rstrip() + (f", level {m.level / 10:g}" if m.level else "")
    if m.size:
        what += f", {m.size[0]} x {m.size[1]}"
    lines.append(f"{m.container}: {what}; sound: "
                 + (", ".join(NAMES.get(s, s) for s in m.sound) or "none"))
    known_video = not m.video or m.video in NAMES
    if not known_video:
        return False, lines + [f"No Chromecast plays its video ({m.video})."]
    device = _device(model)
    ok: bool | None
    if m.video == "h264" and m.level is None:
        lines.append("Its H.264 level is not read from this kind of file: up to level 4.1 "
                     "plays on every Chromecast, higher only on newer ones.")
    if device:
        ok = _plays(m, device)
        if ok is not None:
            lines.append(f"{'Plays' if ok else 'Will not play'} on a {device}"
                         + (f" ({model})" if model != device else "") + ".")
    else:
        said = [_plays(m, d) for d in DEVICES]
        fits = [d for d, yes in zip(DEVICES, said) if yes]
        ok = (None if None in said else True if len(fits) == len(DEVICES)
              else None if fits else False)
        if None not in said:
            lines.append("Plays on every Chromecast." if ok else
                         f"Plays only on: {', '.join(fits)}." if fits else "No Chromecast plays it.")
    if m.container == "Matroska" or m.container == "MOV":
        lines.append(f"Nemo casts MP4, M4V and WebM files only, and converts nothing: "
                     f"a {m.container} file plays here, not on the Chromecast.")
        ok = False
    odd = [s for s in m.sound if s not in SOUND_OK]
    if any(s in SOUND_PASSTHROUGH for s in odd):
        lines.append("Its sound is " + ", ".join(NAMES[s] for s in odd if s in NAMES)
                     + ": a Chromecast passes that on to the TV or amplifier, so it may be silent.")
        ok = None if ok else ok
    elif odd:
        lines.append(f"Its sound ({', '.join(odd)}) is not on Google's list: it may be silent.")
        ok = None if ok else ok
    return ok, lines
