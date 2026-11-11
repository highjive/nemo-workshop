"""The Researcher (owner's request, 2026-10-18): looks up online, in
Mouser's catalogue, what the Reviewer stopped a step for, and hands the
finds to the Reviewer as fixes. Mouser's reply here is its documented
Search API v1 shape, invented parts in it; no call with a real key has been
made (NOT VERIFIED against the live service)."""
from __future__ import annotations

import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import research as R, review
from nemo.parts import PartsLibrary
from nemo.project import Brief, Project

LIB = PartsLibrary.load()
REPLY = {"Errors": [], "SearchResults": {"NumberOfResult": 2, "Parts": [
    {"Manufacturer": "Acme", "ManufacturerPartNumber": "RF-100", "Description": "RFID reader module",
     "DataSheetUrl": "https://example.com/rf100.pdf", "ProductDetailUrl": "https://example.com/rf100"},
    {"Manufacturer": "Acme", "ManufacturerPartNumber": "", "Description": "no part number",
     "DataSheetUrl": "", "ProductDetailUrl": "https://example.com/x"}]}}


class TestMouser(unittest.TestCase):
    def test_the_documented_reply_is_read(self):
        finds, why = R.parse(REPLY)
        self.assertEqual(why, "")
        self.assertEqual([f.title for f in finds], ["Acme RF-100", "Acme"])
        self.assertEqual(finds[0].datasheet, "https://example.com/rf100.pdf")

    def test_an_error_is_said(self):
        finds, why = R.parse({"Errors": [{"Message": "Invalid unique identifier."}]})
        self.assertEqual(finds, []); self.assertIn("Invalid unique identifier", why)

    def test_no_key_no_call(self):
        with mock.patch.object(R, "key", return_value=None), \
             mock.patch("urllib.request.urlopen") as call:
            finds, why = R.search("RFID reader module ESP32")
        call.assert_not_called()
        self.assertIn("no Mouser key", why)

    def test_the_key_goes_only_in_the_request_url_and_the_query_is_the_thing(self):
        sent = {}

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake(req, timeout=0):
            sent["url"], sent["body"] = req.full_url, json.loads(req.data)
            return Resp(json.dumps(REPLY).encode())
        with mock.patch.object(R, "key", return_value="K123"), \
             mock.patch("urllib.request.urlopen", fake):
            R.search("RFID reader module ESP32")
        self.assertTrue(sent["url"].startswith(R.API) and sent["url"].endswith("K123"))
        self.assertEqual(sent["body"]["SearchByKeywordRequest"]["keyword"], "RFID reader module ESP32")

    def test_queries_never_carry_the_brief(self):
        self.assertEqual(R.query_for("missing_rfid", "an RFID reader", "esp32_devkit_v1"),
                         "RFID reader module ESP32")
        self.assertEqual(R.query_for("unknown_parts", "pn532_breakout", ""), "pn532 breakout")


class TestTheKey(unittest.TestCase):
    def test_saved_to_the_key_file_and_read_back_the_environment_first(self):
        with tempfile.TemporaryDirectory() as t, \
             mock.patch.dict(os.environ, {"NEMO_HOME": t}, clear=False):
            os.environ.pop("NEMO_MOUSER_KEY", None); os.environ.pop("MOUSER_API_KEY", None)
            self.assertIsNone(R.key())
            R.save_key("  ABC  ")
            self.assertEqual(R.key(), "ABC")
            with mock.patch.dict(os.environ, {"NEMO_MOUSER_KEY": "ENV"}):
                self.assertEqual(R.key(), "ENV")

    def test_the_stick_keeps_it(self):
        s = (Path(__file__).resolve().parent.parent / "install" / "linux" / "nemo-sync")
        if not s.exists():
            self.skipTest("nemo-sync is not in this layout")
        t = s.read_text(encoding="utf-8")
        self.assertIn('FOLDERS="nemo-projects nemo-stories nemo-storeroom nemo-models .nemo/keys .nemo/art .nemo/engines"', t)
        self.assertIn('chmod 600 "$HOME_DIR/$f"/*', t)


def project(b):
    return Project(Path(tempfile.mkdtemp()) / "p").create(b)


PLAYER = Brief(name="p", function="An RFID player that plays audio files through a speaker.",
               power="USB 5 V 1 A", supply_ma=1000, envelope_mm=[150, 80, 50],
               parts=["esp32_devkit_v1", "dfplayer_mini", "speaker_8ohm_20mm"],
               mcu="esp32_devkit_v1", done_when="It plays.")


class TestTheReviewerOffersTheFinds(unittest.TestCase):
    def test_what_to_look_up(self):
        p = project(Brief(**{**PLAYER.__dict__, "parts": PLAYER.parts + ["flux_capacitor"]}))
        stops, _ = review.before("parts", p, LIB)
        wants = review.researchable(stops)
        self.assertIn(("missing_rfid", "an RFID reader"), wants)
        self.assertIn(("unknown_parts", "flux_capacitor"), wants)

    def test_finds_become_fixes_that_open_a_page(self):
        p = project(PLAYER)
        R.look_up(p.root, [("missing_rfid", "an RFID reader")], "esp32_devkit_v1",
                  searcher=lambda q: R.parse(REPLY))
        fixes = review.fixes("missing_rfid", PLAYER, LIB, p.root)
        online = [f for f in fixes if f.title.startswith("Found online")]
        self.assertEqual(online[0].url, "https://example.com/rf100.pdf")   # the datasheet first
        self.assertEqual(online[0].kind, "info")
        self.assertIn("Add a part", online[0].why)
        self.assertTrue(any(f.key == "review_add_rc522" for f in fixes))  # the library's own still

    def test_nothing_found_is_said_and_tried_again_next_time(self):
        p = project(PLAYER)
        calls = []

        def none(q):
            calls.append(q); return [], "no Mouser key is set"
        R.look_up(p.root, [("missing_rfid", "an RFID reader")], searcher=none)
        R.look_up(p.root, [("missing_rfid", "an RFID reader")], searcher=none)
        self.assertEqual(len(calls), 2)
        f = review.fixes("missing_rfid", PLAYER, LIB, p.root)
        self.assertTrue(any("nothing found" in x.title and "no Mouser key" in x.why for x in f))

    def test_a_find_is_not_searched_twice(self):
        p = project(PLAYER)
        calls = []

        def one(q):
            calls.append(q); return R.parse(REPLY)
        R.look_up(p.root, [("missing_rfid", "an RFID reader")], searcher=one)
        R.look_up(p.root, [("missing_rfid", "an RFID reader")], searcher=one)
        self.assertEqual(len(calls), 1)


class TestRunAsksTheResearcher(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()

    def tearDown(self):
        self._env.stop(); self.t.cleanup()

    def test_after_a_stop_for_a_missing_thing(self):
        from nemo import cli
        from nemo.config import Config
        root = Config.load().path("paths.projects") / "player"
        Project(root).create(PLAYER)
        with mock.patch.object(R, "search", return_value=R.parse(REPLY)) as s, \
             redirect_stdout(io.StringIO()) as out:
            cli.main(["--project", "player", "run", "--only", "parts"])
        s.assert_called_once()
        self.assertIn("Researcher: 2 part(s) found", out.getvalue())
        self.assertEqual(review.work_log(root)[-1]["event"], "researched")
