"""Casting to a Chromecast, for the Theatre (owner, 2026-10-21: "Nemo casts
itself").

A Chromecast plays a file by fetching it over the home network, so Nemo
lends it one file at a time from a small web server of its own:
  - it serves only the file being cast, at a path with a random token in it
    (/<token>/<name>), so nothing else on the computer can be fetched and
    nobody can guess the address; anything else gets 404;
  - it answers Range requests, which a Chromecast uses to seek;
  - it stops when the casting stops.
Finding the Chromecast and telling it what to play is pychromecast's job.

What a Chromecast plays, by file name (MEDIA): MP4/M4V and WebM video,
JPEG, PNG, GIF, WebP and BMP pictures. Nothing is converted: a file of
another kind is refused with the reason, as converting video on this
laptop's processor would be slow. MKV is left out: some Chromecasts play it
and some do not.

Cast for real once, at the owner's request (2026-10-21): a picture to his
Chromecast, taken in 0.8 s, after D198 (see find()). No video yet.
pychromecast's calls are as its version 14.0.10 has them.
Windows asks once whether Python may accept connections; on a Public
network it may refuse, and then the Chromecast cannot fetch the file.
"""
from __future__ import annotations

import mimetypes
import secrets
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MEDIA = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
         # Audio, for the Music Room (2026-10-21): what Google lists the
         # Default Media Receiver as playing.
         ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
         ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac",
         ".wav": "audio/wav"}


class CastError(RuntimeError):
    """It could not be cast; the message says why."""


def castable(path: Path) -> str | None:
    """The type a Chromecast is sent for this file, or None if it cannot play it."""
    return MEDIA.get(Path(path).suffix.lower())


# ------------------------------------------------------------ the one file
class _OneFile(BaseHTTPRequestHandler):
    path_on_disk: Path
    url_path: str

    def log_message(self, *args):            # quiet: no log of every request
        pass

    def do_HEAD(self):
        self._send(head=True)

    def do_GET(self):
        self._send(head=False)

    def _send(self, head: bool):
        if urllib.parse.unquote(self.path) != self.url_path:
            self.send_error(404)
            return
        size = self.path_on_disk.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            try:
                if a:
                    start, end = int(a), (int(b) if b else size - 1)
                else:
                    start, end = max(size - int(b), 0), size - 1
            except ValueError:
                self.send_error(416); return
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers(); return
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", castable(self.path_on_disk)
                         or mimetypes.guess_type(self.path_on_disk.name)[0]
                         or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Access-Control-Allow-Origin", "*")   # the Cast receiver asks
        self.end_headers()
        if head:
            return
        with self.path_on_disk.open("rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    block = f.read(min(1 << 16, left))
                    if not block:
                        break
                    self.wfile.write(block)
                    left -= len(block)
            except (ConnectionError, OSError):
                pass                           # the Chromecast hung up, as it does on a seek


class Lender:
    """A web server that lends one file, until stop()."""

    def __init__(self, path: Path, port: int = 0):
        self.path = Path(path)
        if not self.path.is_file():
            raise CastError(f"there is no file {self.path}")
        self.token = secrets.token_urlsafe(12)
        handler = type("Handler", (_OneFile,), {
            "path_on_disk": self.path, "url_path": f"/{self.token}/{self.path.name}"})
        self.server = ThreadingHTTPServer(("0.0.0.0", port), handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def url(self, host: str) -> str:
        return f"http://{host}:{self.port}/{self.token}/{urllib.parse.quote(self.path.name)}"

    def stop(self) -> None:
        """Stop lending. Safe to call again."""
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self.server.shutdown()
        self.server.server_close()


def address_towards(host: str) -> str:
    """This computer's address on the network that reaches `host`. Nothing
    is sent: a UDP socket only asks the system which way it would go."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 8009))
        return s.getsockname()[0]


# ------------------------------------------------------------ the Chromecast
def available() -> tuple[bool, str]:
    try:
        import pychromecast  # noqa: F401
    except ImportError:
        return False, "pychromecast is not installed (NemoDoc installs it)"
    return True, ""


def find(timeout: float = 8.0) -> list:
    """The Chromecasts on this network, by their names."""
    ok, why = available()
    if not ok:
        raise CastError(why)
    import pychromecast
    from pychromecast.models import CastInfo, HostServiceInfo
    found, browser = pychromecast.get_chromecasts(timeout=timeout)
    # Bound to its address, not to discovery: found by discovery, a
    # Chromecast connects through it, and with discovery stopped it never
    # connects (the first real cast, Family Room TV on the AH531, 2026-10-21: "Zeroconf
    # instance loop must be running", then a 10 s time-out).
    out = []
    for c in found:
        i = c.cast_info
        out.append(pychromecast.get_chromecast_from_cast_info(
            CastInfo({HostServiceInfo(i.host, i.port)}, i.uuid, i.model_name,
                     i.friendly_name, i.host, i.port, i.cast_type, i.manufacturer), None))
    pychromecast.discovery.stop_discovery(browser)
    return sorted(out, key=lambda c: c.cast_info.friendly_name)


# The app a Chromecast runs to play what Nemo sends it.
DEFAULT_RECEIVER = "CC1AD845"


class Session:
    """One file cast to one Chromecast: play, pause, resume, stop, and let it go.

    D199, the AH531 and Family Room TV, 2026-10-21: after Stop the Chromecast kept
    running the cast app (player IDLE, "CANCELLED") instead of going back to
    its own screen, and Nemo never disconnected; nothing let it go when a
    video ended either. Now the Chromecast is released, its cast app closed
    and Nemo disconnected, on Stop and when the video ends or fails. When
    someone else takes over the Chromecast ("INTERRUPTED"), Nemo stops lending
    and steps away without closing their app.
    """

    def __init__(self, device, path: Path, on_end=None, start_at: float = 0.0):
        mime = castable(path)
        if mime is None:
            raise CastError(f"a Chromecast does not play {Path(path).suffix or 'this'} files; "
                            f"it plays {', '.join(sorted(MEDIA))}")
        gatekeeper(device)
        self.device, self.lender = device, Lender(path)
        self.released, self.ended, self.on_end = False, None, on_end
        self._lock = threading.Lock()
        try:
            device.wait(timeout=10)
            here = address_towards(device.cast_info.host)
            self.media = device.media_controller
            self.media.play_media(self.lender.url(here), mime, title=Path(path).stem,
                                  stream_type="BUFFERED",
                                  current_time=start_at if start_at > 0 else None)
            self.media.block_until_active(timeout=15)
            self.media.register_status_listener(self)
        except Exception as exc:                                # noqa: BLE001
            self.lender.stop()
            raise CastError(f"the Chromecast did not take it: {exc}") from None

    # pychromecast calls this on every change of the media's state.
    def new_media_status(self, status) -> None:
        if self.released or status.player_state != "IDLE":
            return
        reason = status.idle_reason
        if reason in ("FINISHED", "ERROR", "INTERRUPTED"):
            self.ended = reason
            # Not from pychromecast's own thread, which the release talks through.
            threading.Thread(target=self.release, args=(reason != "INTERRUPTED",),
                             daemon=True).start()

    def load_media_failed(self, item, error_code) -> None:   # pychromecast asks for it
        pass

    def pause(self):
        self.media.pause()

    def resume(self):
        self.media.play()

    def position(self) -> float | None:
        """Seconds played, as the Chromecast last said; None if not known."""
        try:
            return float(self.media.status.adjusted_current_time
                         or self.media.status.current_time or 0)
        except (AttributeError, TypeError, ValueError):
            return None

    def stop(self):
        """The owner's Stop: stop playing, then let the Chromecast go."""
        self.stopped_at = None if self.released else self.position()
        try:
            if not self.released:
                self.media.stop()
        except Exception:                                       # noqa: BLE001
            pass
        self.release()

    def release(self, close_app: bool = True) -> None:
        """Close Nemo's cast app (never another's), disconnect, stop lending."""
        with self._lock:
            if self.released:
                return
            self.released = True
        try:
            if close_app and getattr(self.device.status, "app_id", None) == DEFAULT_RECEIVER:
                self.device.quit_app()
        except Exception:                                       # noqa: BLE001
            pass
        try:
            self.device.disconnect(timeout=5)
        except Exception:                                       # noqa: BLE001
            pass
        self.lender.stop()
        if self.on_end:
            try:
                self.on_end(self)
            except Exception:                                   # noqa: BLE001
                pass


def gatekeeper(device) -> None:
    """Home's Gatekeeper (owner, 2026-10-22): Nemo casts only to a device
    he has set to Use. Asked before anything is lent or sent."""
    from . import home
    info = getattr(device, "cast_info", None)
    ok, why = home.may_use(str(getattr(info, "host", "") or ""),
                           str(getattr(info, "friendly_name", "") or ""))
    if not ok:
        raise CastError(why)


class Queue:
    """The Music Room's DJ: several files cast one after another over one
    connection (owner, 2026-10-21). Each is lent only while it plays; when
    one finishes the next starts; after the last, or on stop(), the
    Chromecast is let go as Session.release does (D199), and someone else
    taking it over makes the queue step away without closing their app."""

    def __init__(self, device, paths: list[Path], on_change=None):
        self.paths = [Path(p) for p in paths if castable(p)]
        if not self.paths:
            raise CastError("nothing in the list is something a Chromecast plays")
        gatekeeper(device)
        self.device, self.on_change = device, on_change
        self.index, self.lender, self.released, self.ended = -1, None, False, None
        self._lock = threading.Lock()
        try:
            device.wait(timeout=10)
            self.here = address_towards(device.cast_info.host)
            self.media = device.media_controller
            self._play(0)
            self.media.register_status_listener(self)
        except CastError:
            raise
        except Exception as exc:                                # noqa: BLE001
            self._stop_lending()
            raise CastError(f"the Chromecast did not take it: {exc}") from None

    @property
    def current(self) -> Path | None:
        return self.paths[self.index] if 0 <= self.index < len(self.paths) else None

    def _stop_lending(self):
        if self.lender is not None:
            self.lender.stop()
            self.lender = None

    def _play(self, i: int):
        old = self.lender
        p = self.paths[i]
        self.lender = Lender(p)
        self.media.play_media(self.lender.url(self.here), castable(p), title=p.stem,
                              stream_type="BUFFERED")
        self.media.block_until_active(timeout=15)
        if old is not None:
            old.stop()                      # the last track is no longer lent
        self.index = i                      # D200: only once the last one is let go
        if self.on_change:
            self.on_change(self)

    def new_media_status(self, status) -> None:
        if self.released or status.player_state != "IDLE":
            return
        reason = status.idle_reason
        if reason == "FINISHED":
            threading.Thread(target=self.next, daemon=True).start()
        elif reason in ("ERROR", "INTERRUPTED"):
            self.ended = reason
            threading.Thread(target=self.release, args=(reason != "INTERRUPTED",),
                             daemon=True).start()

    def load_media_failed(self, item, error_code) -> None:
        pass

    def next(self):
        """The next track, or the end: then the Chromecast is let go."""
        with self._lock:
            if self.released:
                return
            last = self.index + 1 >= len(self.paths)
        if last:
            self.ended = "FINISHED"
            self.release()
        else:
            try:
                self._play(self.index + 1)
            except Exception:                                   # noqa: BLE001
                self.ended = "ERROR"
                self.release()

    def pause(self):
        self.media.pause()

    def resume(self):
        self.media.play()

    def stop(self):
        try:
            if not self.released:
                self.media.stop()
        except Exception:                                       # noqa: BLE001
            pass
        self.release()

    def release(self, close_app: bool = True) -> None:
        with self._lock:
            if self.released:
                return
            self.released = True
        try:
            if close_app and getattr(self.device.status, "app_id", None) == DEFAULT_RECEIVER:
                self.device.quit_app()
        except Exception:                                       # noqa: BLE001
            pass
        try:
            self.device.disconnect(timeout=5)
        except Exception:                                       # noqa: BLE001
            pass
        self._stop_lending()
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:                                   # noqa: BLE001
                pass
