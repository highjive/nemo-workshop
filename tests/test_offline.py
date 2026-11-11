"""Offline use: readiness, preparation, datasheets, queued reviews, help."""
from __future__ import annotations

import http.server, os, re, socketserver, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

ROOT = Path(__file__).resolve().parent.parent


def make_pdf(pages: list[str]) -> bytes:
    """A small, valid PDF with one text line per page (empty string = a page
    with no text layer, like a scan)."""
    objs, kids = [], []
    font_id = 3
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(None)                                  # pages, filled later
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for text in pages:
        esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = (f"BT /F1 11 Tf 72 720 Td ({esc}) Tj ET" if text else "").encode()
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_id = len(objs)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                    % (font_id, content_id))
        kids.append(len(objs))
    objs[1] = (b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids)
               + b"] /Count %d >>" % len(kids))
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self._env = mock.patch.dict(os.environ, {
            "HOME": str(self.home), "USERPROFILE": str(self.home), "NEMO_HOME": str(self.home / ".nemo"),
            "PLATFORMIO_CORE_DIR": str(self.home / ".platformio")})
        self._env.start()

    def tearDown(self):
        self._env.stop(); self.tmp.cleanup()


# ====================================================================
class TestModelSources(unittest.TestCase):
    """One reference list; every installer's copy must agree with it."""

    def test_installer_copies_agree(self):
        # Only NemoIso.tar.gz ships nemodoc/fetch-models.sh; only NemoWin.zip
        # ships NemoDoc.ps1. A distribution is checked against only the
        # installer scripts it actually carries -- read() returning None
        # (file absent from this distribution) must not reach re.findall,
        # which raises on None rather than silently skipping.
        from nemo.offline import MODEL_SOURCES
        patterns = {
            "NemoDoc.ps1": r'name = "([^"]+)";\s*repo = "([^"]+)";\s*file = "([^"]+)"',
            "nemodoc": r'"([\w.\-]+)\|([\w./\-]+)\|([\w.\-]+)"',
            "fetch-models.sh": r'"([\w.\-]+)\|([\w./\-]+)\|([\w.\-]+)"',
        }
        checked_any = False
        for where, pattern in patterns.items():
            text = self._read(where)
            if text is None:
                continue
            checked_any = True
            rows = re.findall(pattern, text)
            self.assertTrue(rows, f"{where} was found but no model lines matched")
            for name, repo, file in rows:
                if name in MODEL_SOURCES:
                    self.assertEqual(MODEL_SOURCES[name], (repo, file), f"{where}: {name}")
        # At least one installer script must be present and checked -- this
        # test exists to catch a source list going stale, and a distribution
        # that ships neither installer script is not one it can run in.
        self.assertTrue(checked_any, "no installer script found to check "
                        "against MODEL_SOURCES in this distribution")

    def test_qwen3_1_7b_points_at_a_repo_that_actually_has_a_q4_k_m_file(self):
        # D100: the official Qwen/Qwen3-1.7B-GGUF repo ships only a Q8_0
        # quant (confirmed on its own model card: "Quantization: q8_0", and
        # its file listing has no Q4_K_M at all), unlike its 4B and 8B
        # siblings, which do carry Q4_K_M and are why those two never
        # failed. Requesting Qwen3-1.7B-Q4_K_M.gguf from the Qwen org 404s
        # -- confirmed on every single NemoDoc pass in five days of the
        # operator's own log, never once succeeding. unsloth/Qwen3-1.7B-GGUF
        # carries the exact filename at the expected ~1.1 GB (verified:
        # sha256 ba491cf470c3cadc624e4c8d6c9a27c998809e8ba8eb938d1689ae87e0
        # 24b6b7, 1.11 GB, commit cc27747, checked directly against Hugging
        # Face on 2026-09-29 -- not downloaded here, since that is real
        # network traffic a unit test should not depend on).
        from nemo.offline import MODEL_SOURCES
        repo, file = MODEL_SOURCES["qwen3-1.7b"]
        self.assertEqual(file, "Qwen3-1.7B-Q4_K_M.gguf")
        self.assertNotEqual(repo, "Qwen/Qwen3-1.7B-GGUF",
                            "this repo has never once served this file -- see D100")
        self.assertEqual(repo, "unsloth/Qwen3-1.7B-GGUF")

    def test_every_mode_model_has_a_source(self):
        # D68: Deep mode's model had no download source anywhere.
        from nemo.config import DEFAULTS
        from nemo.offline import MODEL_SOURCES
        import yaml
        configs = [DEFAULTS]
        for c in (ROOT / "config.yaml",):
            if c.exists():
                configs.append(yaml.safe_load(c.read_text()))
        for cfg in configs:
            for key in ("modes", "modes_windows"):
                for mode, spec in (cfg.get(key) or {}).items():
                    self.assertIn(spec["model"], MODEL_SOURCES, f"{key}.{mode}")

    def _read(self, name):
        for base in (ROOT, ROOT / "install" / "windows", ROOT / "install" / "linux",
                     ROOT / "manual"):
            if (base / name).exists():
                return (base / name).read_text()
        return None


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    body = b""
    drop_after = None            # simulate a broken connection once

    def log_message(self, *a):
        pass

    def do_GET(self):
        data, start = self.body, 0
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            self.send_response(206)
        else:
            self.send_response(200)
        chunk = data[start:]
        if type(self).drop_after is not None and not rng:
            chunk = chunk[:type(self).drop_after]
            type(self).drop_after = None
            self.send_header("Content-Length", str(len(data) - start))
            self.end_headers()
            self.wfile.write(chunk); self.wfile.flush()
            self.connection.close()
            return
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)


class TestDownloads(Env):
    def _serve(self, body, drop_after=None):
        handler = type("H", (_RangeHandler,), {"body": body, "drop_after": drop_after})
        srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def test_valid_model_downloads(self):
        from nemo import offline
        base = self._serve(b"GGUF" + b"x" * 300_000)
        with mock.patch.object(offline, "HF_BASE", base):
            ok, _ = offline.download_model("gemma3-1b", progress=lambda m: None)
        self.assertTrue(ok)
        self.assertTrue(offline.is_gguf(offline.model_file("gemma3-1b")))

    def test_interrupted_download_resumes(self):
        from nemo import offline
        body = b"GGUF" + bytes(range(256)) * 2000
        base = self._serve(body, drop_after=100_000)
        with mock.patch.object(offline, "HF_BASE", base):
            ok1, _ = offline.download_model("gemma3-1b", progress=lambda m: None)
            ok2, _ = offline.download_model("gemma3-1b", progress=lambda m: None)
        self.assertTrue(ok2)
        self.assertEqual(offline.model_file("gemma3-1b").read_bytes(), body,
                         "resumed file must match the original byte for byte")

    def test_a_short_download_is_not_taken_for_the_model(self):
        # D211: qwen3-8b came down as 3,935,445,225 of 5,027,783,488 bytes
        # (2026-11-04). The stream ended without an error, the file started
        # with GGUF, and Nemo said "Ready to work offline". The earlier test
        # above never looked at the first, cut-short call.
        from nemo import offline
        body = b"GGUF" + bytes(range(256)) * 2000
        base = self._serve(body, drop_after=100_000)
        with mock.patch.object(offline, "HF_BASE", base):
            ok, why = offline.download_model("gemma3-1b", progress=lambda m: None)
            self.assertFalse(ok)
            self.assertIn("resume", why)
            self.assertIsNone(offline.model_file("gemma3-1b"))      # not where Nemo looks
            part = offline.models_dir() / "gemma3-1b.gguf.part"
            self.assertEqual(part.stat().st_size, 100_000)         # kept, to resume from
            ok2, _ = offline.download_model("gemma3-1b", progress=lambda m: None)
        self.assertTrue(ok2)
        self.assertEqual(offline.model_file("gemma3-1b").read_bytes(), body)

    def test_error_page_is_not_saved_as_a_model(self):
        from nemo import offline
        base = self._serve(b"<html>rate limited</html>")
        with mock.patch.object(offline, "HF_BASE", base):
            ok, why = offline.download_model("gemma3-1b", progress=lambda m: None)
        self.assertFalse(ok)
        self.assertIsNone(offline.model_file("gemma3-1b"))


class TestFirmwareToolchain(Env):
    def _fake_pio(self, rc):
        d = self.home / "bin"; d.mkdir(exist_ok=True)
        if sys.platform.startswith("win"):        # a batch file stands in on Windows
            f = d / "pio.cmd"
            f.write_text("@echo off\r\necho building\r\n"
                         'mkdir "%PLATFORMIO_CORE_DIR%\\platforms\\espressif32" 2>nul\r\n'
                         f"exit /b {rc}\r\n", encoding="utf-8")
            return str(f)
        f = d / "pio"
        f.write_text(f"#!/bin/sh\necho building\n"
                     f"mkdir -p \"$PLATFORMIO_CORE_DIR/platforms/espressif32\"\nexit {rc}\n")
        f.chmod(0o755)
        return str(f)

    def test_successful_build_marks_board_ready(self):
        from nemo import offline
        with mock.patch("nemo.platform_probe.find_tool", return_value=self._fake_pio(0)):
            ok, _ = offline.prepare_board("esp32dev", progress=lambda m: None)
        self.assertTrue(ok)
        self.assertTrue(offline.board_ready("esp32dev")[0])
        self.assertIn("setup()", (self.home / ".nemo" / "offline-warmup" /
                                  "esp32dev" / "src" / "main.cpp").read_text())

    def test_failed_build_is_not_ready(self):
        from nemo import offline
        with mock.patch("nemo.platform_probe.find_tool", return_value=self._fake_pio(1)):
            ok, why = offline.prepare_board("esp32dev", progress=lambda m: None)
        self.assertFalse(ok)
        self.assertFalse(offline.board_ready("esp32dev")[0])

    def test_removed_platform_is_no_longer_ready(self):
        from nemo import offline
        offline.save_state({"boards": {"esp32dev": {"ok": True, "when": 1}}})
        ok, why = offline.board_ready("esp32dev")
        self.assertFalse(ok)
        self.assertIn("removed", why)

    def test_boards_come_from_the_library(self):
        # D69: two more MCU boards joined the library (rp2040_pico,
        # esp32c3_devkit), each needing its own firmware toolchain readiness.
        from nemo import offline
        from nemo.parts import PartsLibrary
        self.assertEqual(set(offline.boards(PartsLibrary.load())),
                         {"esp32dev", "esp32-s3-devkitc-1", "pico",
                          "esp32-c3-devkitm-1"})


class TestReadiness(Env):
    def test_fake_model_file_is_not_ready(self):
        from nemo import offline
        from nemo.config import Config
        d = self.home / ".nemo" / "models"; d.mkdir(parents=True)
        (d / "qwen3-1.7b.gguf").write_bytes(b"<html>")
        items = {i.name: i for i in offline.readiness(Config.load(), [])}
        talk = next(v for k, v in items.items() if k.startswith("Talk"))
        self.assertEqual(talk.status, "missing")
        self.assertIn("not a valid model", talk.detail)


# ====================================================================
class TestReviewQueue(Env):
    def _router(self, reviewer="openrouter/x"):
        from nemo.config import Config, LOCAL_THEN_REVIEW
        from nemo.router import Reply, Router
        cfg = Config.load(Path("/nonexistent"))
        cfg.data["engine"]["review"] = reviewer
        cfg.data["routing"]["cad_script"] = LOCAL_THEN_REVIEW
        r = Router(cfg)
        r._call_local = lambda *a: Reply("draft text", "local", "m")
        def offline_(*a):
            raise OSError("no network")
        r.review = offline_
        r.context = {"project": str(self.home / "proj"), "stage": "enclosure"}
        return r

    def test_offline_review_is_queued_not_lost(self):
        from nemo.reviews import pending
        out = self._router().ask("cad_script", "sys", "user")
        self.assertTrue(out.degraded)
        self.assertTrue(out.queued)
        self.assertEqual(len(pending()), 1)
        self.assertEqual(pending()[0]["context"]["stage"], "enclosure")

    def test_nothing_queued_without_a_reviewer(self):
        from nemo.reviews import pending
        self._router(reviewer=None).ask("cad_script", "sys", "user")
        self.assertEqual(pending(), [])

    def test_sending_files_advice_and_clears_the_queue(self):
        from nemo.reviews import pending, reviews_for, send_all
        from nemo.router import Reply
        (self.home / "proj").mkdir()
        self._router().ask("cad_script", "sys", "user")
        online = mock.Mock(); online.review.return_value = Reply("Walls too thin.", "remote", "rev")
        results = send_all(online)
        self.assertTrue(results[0][1])
        self.assertEqual(pending(), [])
        notes = reviews_for(self.home / "proj", "enclosure")
        self.assertEqual(len(notes), 1)
        text = notes[0].read_text()
        self.assertIn("Walls too thin.", text)
        self.assertIn("Nothing in the project was changed", text)

    def test_failed_send_keeps_the_item(self):
        from nemo.reviews import pending, send_all
        self._router().ask("cad_script", "sys", "user")
        broken = mock.Mock(); broken.review.side_effect = OSError("still offline")
        send_all(broken)
        self.assertEqual(len(pending()), 1)


# ====================================================================
class TestHelp(unittest.TestCase):
    def test_markdown_segments(self):
        from nemo.help import segments
        seg = segments("# Title\ntext **bold** `code`\n- item\n| a | b |\n|---|---|\n| 1 | 2 |\n```\nx = 1\n```\n")
        styles = [s for _, s in seg]
        self.assertIn("h1", styles)
        self.assertIn("code", styles)
        joined = "".join(t for t, _ in seg)
        self.assertIn("text bold code", joined)
        self.assertIn("\u2022 item", joined)
        self.assertNotIn("|---|", joined)
        self.assertIn("x = 1", joined)


# ====================================================================
class TestDatasheets(Env):
    def setUp(self):
        super().setUp()
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")
        from nemo.datasheets import Library
        self.src = self.home / "incoming"; self.src.mkdir()
        (self.src / "MFRC522.pdf").write_bytes(make_pdf([
            "MFRC522 Standard performance MIFARE reader",
            "Absolute maximum ratings VDD 4.0 V",
            "Pin 1 SDA serial data"]))
        (self.src / "FN-M16P.pdf").write_bytes(make_pdf([
            "FN-M16P Embedded MP3 Audio Module", "Working Voltage DC3.3~5.0V"]))
        (self.src / "scan.pdf").write_bytes(make_pdf(["", ""]))
        self.lib = Library(root=self.home / "sheets")
        self.lib.add(sorted(self.src.glob("*.pdf")))

    def tearDown(self):
        self.lib.close(); super().tearDown()

    def test_search_cites_the_page(self):
        hits = self.lib.search("absolute maximum")
        self.assertEqual((hits[0].file, hits[0].page), ("MFRC522.pdf", 2))

    def test_scan_is_flagged_not_silent(self):
        st = {s.file: s for s in self.lib.sheets()}
        self.assertEqual(st["scan.pdf"].status, "no text")
        self.assertIn("scanned", st["scan.pdf"].detail)

    def test_search_operators_typed_by_accident_do_not_crash(self):
        for q in ('VDD: "4.0', "sleep-mode", "a AND OR NOT", "(("):
            self.lib.search(q)

    def test_linking_is_suggested_then_confirmed(self):
        from nemo.parts import PartsLibrary
        parts = PartsLibrary.load()
        self.assertIn("rc522", self.lib.suggest_parts("MFRC522.pdf", parts))
        # The DFPlayer's own sheet never says "DFPlayer" -- it is the FN-M16P.
        # It is suggested only because the library records that source for
        # the part (D67); a datasheet with no name in common gets no guess.
        self.assertEqual(self.lib.suggest_parts("FN-M16P.pdf", parts), ["dfplayer_mini"])
        (self.src / "mystery.pdf").write_bytes(make_pdf(["Some unrelated widget"]))
        self.lib.add([self.src / "mystery.pdf"])
        self.assertEqual(self.lib.suggest_parts("mystery.pdf", parts), [])
        # Suggested is not linked: nothing is linked until confirmed.
        self.assertEqual(self.lib.files_for("dfplayer_mini"), [])
        self.lib.link("FN-M16P.pdf", "dfplayer_mini")
        hits = self.lib.search("working voltage", ref="dfplayer_mini")
        self.assertEqual(hits[0].file, "FN-M16P.pdf")
        self.assertEqual(self.lib.search("absolute", ref="dfplayer_mini"), [])

    def test_reindex_is_incremental_and_forgets_removed_files(self):
        self.assertEqual(self.lib.index()["unchanged"], 3)
        (self.lib.root / "scan.pdf").unlink()
        self.assertEqual(self.lib.index()["removed"], 1)

    def test_fallback_search_without_full_text_index(self):
        self.lib.fts = False
        hits = self.lib.search("working voltage")
        self.assertEqual(hits[0].file, "FN-M16P.pdf")

    def test_model_numbers_are_tokens_generic_words_are_not(self):
        from nemo.datasheets import part_tokens
        from nemo.parts import PartsLibrary
        lib = PartsLibrary.load()
        self.assertIn("mfrc522", part_tokens(lib.get("rc522")))
        self.assertNotIn("mp3", part_tokens(lib.get("dfplayer_mini")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
