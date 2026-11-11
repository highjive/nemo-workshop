"""The Datasheet Reader and the Second Opinion (owner, 2026-11-04)."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from _pdf import NT41, NT41_TRUTH, make_pdf
from nemo import issues, reader, second, skills
from nemo.datasheets import Library
from nemo.parts import PartsLibrary
from test_harness import good

APP = Path(__file__).resolve().parent.parent / "nemo" / "gui" / "app.py"

# What the 8B answered on the first real reading (2026-11-04), as it came:
# every quote wrapped in quotation marks, three pins' jobs wrong.
REPLY = {
    "name": {"value": "NT-41 Ambient Light Sensor Module", "quote": "\"NT-41 Ambient Light Sensor Module\"", "page": 1},
    "supply_v": [{"value": 3.3, "quote": "\"3.3 V\"", "page": 1}, {"value": 5, "quote": "\"5 V\"", "page": 1}],
    "current_ma": {"value": 0.8, "quote": "\"0.8 mA\"", "page": 1},
    "logic_v": {"value": 3.3, "quote": "\"3.3 V (I2C interface)\"", "page": 1},
    "pins": [{"name": "VCC", "function": "power", "quote": "\"VCC  power supply input\"", "page": 2},
             {"name": "GND", "function": "gnd", "quote": "\"GND  ground\"", "page": 2},
             {"name": "SDA", "function": "io", "quote": "\"SDA  I2C data line\"", "page": 2},
             {"name": "SCL", "function": "io", "quote": "\"SCL  I2C clock line\"", "page": 2},
             {"name": "INT", "function": "bus", "quote": "\"INT  interrupt output, active low\"", "page": 2}],
}


class TestTheDatasheetReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        (d / "sheets").mkdir()
        make_pdf(d / "sheets" / "nt41.pdf", NT41)
        with Library(d / "sheets", d / "ds.sqlite") as lib:
            lib.index()
            cls.pages = reader.pages_of(lib, "nt41.pdf")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_test_datasheet_has_a_text_layer(self):
        self.assertEqual(sorted(self.pages), [1, 2])
        self.assertIn("0.8 mA", self.pages[1])

    def test_the_real_reading_holds_up_and_matches_the_truth(self):
        d = reader.draft("nt41.pdf", self.pages, REPLY, "nt41")
        self.assertEqual(d.dropped, [])
        kept = {f.what: f.value for f in d.kept}
        self.assertEqual({float(f.value) for f in d.kept if f.what == "supply_v"}, NT41_TRUTH["supply_v"])
        self.assertEqual(float(kept["current_ma"]), NT41_TRUTH["current_ma"])
        self.assertEqual(float(kept["logic_v"]), NT41_TRUTH["logic_v"])
        pins = {f.value[0]: f.value[1] for f in d.kept if f.what.startswith("pin ")}
        self.assertEqual(pins, NT41_TRUTH["pins"])          # code decided the jobs, not the model

    def test_a_quote_not_on_its_page_is_dropped(self):
        bad = copy.deepcopy(REPLY)
        bad["current_ma"] = {"value": 0.8, "quote": "Typical supply current: 0.8 mA", "page": 2}
        f = next(f for f in reader.draft("nt41.pdf", self.pages, bad).found if f.what == "current_ma")
        self.assertFalse(f.ok)
        self.assertIn("not on page 2", f.why)

    def test_an_invented_figure_is_dropped(self):
        bad = copy.deepcopy(REPLY)
        bad["current_ma"] = {"value": 1.2, "quote": "Typical supply current: 0.8 mA", "page": 1}
        f = next(f for f in reader.draft("nt41.pdf", self.pages, bad).found if f.what == "current_ma")
        self.assertFalse(f.ok)
        self.assertIn("1.2 is not in those words", f.why)

    def test_nothing_quoted_is_not_found_not_guessed(self):
        bad = copy.deepcopy(REPLY)
        bad["logic_v"] = {"value": 1.8, "quote": "", "page": 1}
        f = next(f for f in reader.draft("nt41.pdf", self.pages, bad).found if f.what == "logic_v")
        self.assertFalse(f.ok)

    def test_a_bare_number_is_kept_but_flagged(self):
        f = next(f for f in reader.draft("nt41.pdf", self.pages, REPLY).found if f.what == "current_ma")
        self.assertTrue(f.ok)
        self.assertIn("short quote", f.why)

    def test_the_draft_shows_its_proof_and_is_never_read_as_a_part(self):
        d = reader.draft("nt41.pdf", self.pages, REPLY, "nt41")
        text = reader.to_yaml(d)
        self.assertIn("# p.2:", text)
        self.assertIn("the model said io; its description says bus", text)
        with tempfile.TemporaryDirectory() as parts:
            out = reader.write(d, Path(parts))
            self.assertEqual(out.parent.name, "drafts")
            lib = PartsLibrary.load(Path(parts))
            self.assertIsNone(lib.get("nt41"))
            moved = Path(parts) / "nt41.yaml"
            out.replace(moved)                                  # moved up by the owner...
            refused = PartsLibrary.load(Path(parts))
            self.assertIsNone(refused.get("nt41"))              # ...but not yet given a category
            self.assertIn("category", " ".join(refused.errors))
            moved.write_text(moved.read_text(encoding="utf-8").replace(
                "  # category: CHOOSE", "  category: sensor\n  # was: CHOOSE"), encoding="utf-8")
            self.assertIsNotNone(PartsLibrary.load(Path(parts)).get("nt41"))

    def test_the_categories_offered_are_the_librarys(self):
        self.assertEqual(set(reader.CATEGORIES), {p.category for p in PartsLibrary.load()})

    def test_a_long_datasheets_pin_table_is_read_not_cut_off(self):
        # 2026-11-08: the first PAGE_CHARS were given and the rest cut, so a
        # pin table on page 40 of a long datasheet was never read.
        filler = "Application note. Layout guidance for the board. " * 120
        pages = {n: filler for n in range(1, 61)}
        pages[1] = "NT-90 Pressure Sensor. Features: small. " + filler
        pages[40] = "Pin description. Pin 1 VCC supply voltage 3.3 V. Pin 2 GND. Pin 3 SDA."
        pages[44] = "Electrical characteristics. Supply current 1.2 mA typical."
        text = reader.prompt(pages)
        self.assertLessEqual(len(text), reader.PAGE_CHARS + 2000)
        self.assertIn("[page 1]", text)
        self.assertIn("Pin 1 VCC supply voltage 3.3 V", text)
        self.assertIn("Supply current 1.2 mA", text)
        self.assertIn("pages were left out", text)
        keep, left = reader.chosen_pages(pages)
        self.assertEqual(keep, sorted(keep))
        self.assertIn(40, keep)
        self.assertTrue(left)

    def test_a_short_datasheet_is_given_whole(self):
        keep, left = reader.chosen_pages(self.pages)
        self.assertEqual((keep, left), (sorted(self.pages), []))
        self.assertNotIn("left out", reader.prompt(self.pages))

    def test_pin_jobs_by_their_words(self):
        self.assertEqual(reader.function_from("VDD", "core supply"), "power")
        self.assertEqual(reader.function_from("MISO", "SPI data out"), "bus")
        self.assertEqual(reader.function_from("RST", "reset, active low"), "io")


class TestTheSecondOpinion(unittest.TestCase):
    def setUp(self):
        lib = PartsLibrary.load()
        self.doc = good()
        refs = sorted({w for c in self.doc["cables"] for w in (c["from"], c["to"])})
        self.parts = [lib.get(r) for r in refs if lib.get(r)]

    def test_one_connection_at_a_time_with_a_way_out(self):
        asked = []

        def post(payload):
            asked.append(payload)
            return {"verdict": "fine", "reason": "ok"}
        ops = second.review(self.doc, self.parts, "", post)
        self.assertEqual(len(asked), len(ops))
        self.assertEqual(asked[0]["response_format"]["json_schema"]["schema"]["properties"]["verdict"]["enum"],
                         ["fine", "wrong", "not sure"])
        self.assertEqual(asked[0]["temperature"], 0)

    def test_a_shared_bus_is_said_to_be_shared_by_design(self):
        texts = []
        second.review(self.doc, self.parts, "", lambda p: (texts.append(p["messages"][0]["content"]),
                                                          {"verdict": "fine", "reason": ""})[1])
        self.assertTrue(any("bus line: parts on one bus share it by design" in t for t in texts))

    def test_an_answer_outside_the_three_is_not_sure(self):
        ops = second.review(self.doc, self.parts, "", lambda p: {"verdict": "maybe", "reason": ""})
        self.assertTrue(all(o.verdict == "not sure" for o in ops))

    def test_its_doubts_are_its_own_issue_and_change_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ops = [second.Opinion("BME280", "SDA", "GPIO21", "wrong", "clash"),
                   second.Opinion("BME280", "SCL", "GPIO22", "fine", "")]
            second.save(root, ops, "qwen3-4b")
            self.assertEqual([o.part_pin for o in second.doubts(root)], ["SDA"])
            got = issues.for_project(root, None, PartsLibrary.load())
        i = got["workshop.second"][0]
        self.assertEqual(i.state, issues.DOUBTED)
        self.assertEqual(i.fixes, [])
        self.assertIn("clash", i.problems[0])


class TestTheSecondOpinionLeavesTheModelAsItWas(unittest.TestCase):
    """2026-11-08: `nemo second` restarted a talk mode already running, then
    stopped it, leaving no model loaded."""

    def run_it(self, running):
        import io
        import json
        import os
        from contextlib import redirect_stdout
        from unittest import mock
        from nemo import cli, modes
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        env = mock.patch.dict(os.environ, _sandbox.home_env(d.name)); env.start()
        self.addCleanup(env.stop)
        project = mock.Mock(connections=Path(d.name) / "c.json", root=Path(d.name))
        project.connections.write_text(json.dumps({"connections": []}), encoding="utf-8")
        project.load_brief.return_value = mock.Mock(parts=[])
        status = modes.ModeStatus(running, 4321 if running else None, "m")
        calls = []
        with mock.patch.object(cli, "_project", return_value=project), \
             mock.patch.object(cli, "_library", return_value=mock.Mock(get=lambda r: None)), \
             mock.patch.object(modes, "current", return_value=status), \
             mock.patch.object(modes.ModeStatus, "running", property(lambda s: s.pid is not None)), \
             mock.patch.object(modes, "start", side_effect=lambda c, n, **k: (calls.append(
                 ("start", n)) or (True, f"mode {n} up"))), \
             mock.patch.object(modes, "stop", side_effect=lambda: calls.append(("stop",))), \
             mock.patch.object(second, "review", return_value=[]), \
             mock.patch.object(second, "save"), redirect_stdout(io.StringIO()):
            cli.main(["second"])
        return calls

    def test_a_mode_already_up_is_used_and_left_up(self):
        self.assertEqual(self.run_it("talk"), [])

    def test_with_none_up_it_starts_and_stops_its_own(self):
        self.assertEqual(self.run_it(None), [("start", "talk"), ("stop",)])

    def test_another_mode_is_put_back(self):
        self.assertEqual(self.run_it("design"), [("start", "talk"), ("start", "design")])


class TestTheirSkills(unittest.TestCase):
    def test_the_readers_dialog_button_exists(self):
        src = APP.read_text(encoding="utf-8")
        for key, offers in skills.DIALOG_SKILLS.items():
            for _, target in offers:
                cls, _, button = target.partition(":")
                body = src[src.index(f"\nclass {cls}("):]
                body = body[:body.find("\nclass ", 1)]
                if button:
                    self.assertIn(f'text="{button}"', body, key)

    def test_the_second_opinion_works_on_the_open_project(self):
        s = next(s for s in skills.skills_for("workshop.second") if s.kind == skills.JOB)
        self.assertIn(s.target, skills.PROJECT_JOBS)


if __name__ == "__main__":
    unittest.main()
