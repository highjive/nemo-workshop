"""The employees and the Reviewer (owner's redesign, 2026-10-17: "more
errors caught before failures").

The case that started it: on the AH531 the model drafted an "RFID audio
player" whose parts were a DFPlayer, an ESP32, a servo and a speaker: no
RFID reader, and a servo nothing asked for. Every gate would have passed it.
"""
from __future__ import annotations

import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import review, staff
from nemo.fixes import apply_fix, suggest_fixes
from nemo.parts import PartsLibrary
from nemo.project import Brief, Project
from nemo.results import save_result

LIB = PartsLibrary.load()

# Invented brief in the shape of the real one.
PLAYER = Brief(name="tag player", function="An RFID audio player reads tags and plays "
               "pre-recorded audio files through a speaker.", power="USB 5 V 1 A",
               supply_ma=1000, rails=[3.3, 5.0], envelope_mm=[150, 80, 50],
               parts=["dfplayer_mini", "esp32_devkit_v1", "sg90_servo", "speaker_8ohm_20mm"],
               mcu="esp32_devkit_v1", done_when="A tag plays its track.")


def project(brief: Brief) -> Project:
    return Project(Path(tempfile.mkdtemp()) / "p").create(brief)


def keys(stops):
    return [r.name for r in stops]


class TestTheStaff(unittest.TestCase):
    def test_the_workshop_team(self):
        # The Artist joined on 2026-10-20 (concepts, covers); the Writer on
        # 2026-10-21 (the brief, story chapters, spelling); the same day the
        # staff became four departments and the Reviewer the Inspector.
        self.assertEqual([e.title for e in staff.team("workshop")],
                         ["Researcher", "Writer", "Designer", "Inspector", "Clerk",
                          "Datasheet Reader", "Second Opinion", "PCB Designer",
                          "Woodworker", "Foreman", "Timekeeper"])

    def test_every_step_has_one_owner(self):
        from nemo.project import STAGES
        for s in STAGES:
            owners = [e for e in staff.STAFF.values() if s in e.steps]
            self.assertEqual(len(owners), 1, s)
        self.assertEqual(staff.owner("firmware").title, "Coder")
        self.assertEqual(staff.owner("pack").title, "Writer")


class TestTheRealBrief(unittest.TestCase):
    def test_a_missing_rfid_reader_stops_the_parts_step(self):
        stops, notes = review.before("parts", project(PLAYER), LIB)
        self.assertIn("review_missing_rfid", keys(stops))
        # D184: a part nothing asks for stops the step too (it was a note).
        loose = [r for r in stops if r.name == "review_unexplained_parts"]
        self.assertTrue(loose and "sg90_servo" in loose[0].detail)
        self.assertNotIn("review_missing_sound_files", keys(stops))  # the DFPlayer is there

    def test_its_fixes_add_the_reader_or_accept(self):
        p = project(PLAYER)
        stops, _ = review.before("parts", p, LIB)
        rec = {"checks": [{"name": r.name, "status": r.status, "detail": r.detail,
                           "items": r.items} for r in stops]}
        fixes = {f.key: f for f in suggest_fixes(PLAYER, LIB, "parts", rec)}
        b = apply_fix(PLAYER, fixes["review_add_rc522"])
        self.assertIn("rc522", b.parts)
        p.save_brief(b)
        self.assertNotIn("review_missing_rfid", keys(review.before("parts", p, LIB)[0]))
        p2 = project(PLAYER)
        p2.save_brief(apply_fix(PLAYER, fixes["review_accept_missing_rfid"]))
        stops2, notes2 = review.before("parts", p2, LIB)
        self.assertNotIn("review_missing_rfid", keys(stops2))
        self.assertTrue(any("not needed" in n for n in notes2))

    def test_negation_is_respected(self):
        b = Brief(**{**PLAYER.__dict__, "function": "A speaker box that plays audio files "
                     "with no RFID reader."})
        b.parts = ["dfplayer_mini", "esp32_devkit_v1", "speaker_8ohm_20mm"]
        self.assertNotIn("review_missing_rfid", keys(review.before("parts", project(b), LIB)[0]))


class TestOtherStops(unittest.TestCase):
    def b(self, **kw):
        good = Brief(name="x", function="A lamp whose LEDs glow.", power="USB 5 V 1 A",
                     supply_ma=1000, rails=[5.0, 3.3], envelope_mm=[100, 80, 40],
                     parts=["esp32_devkit_v1", "ws2812b_ring8"], mcu="esp32_devkit_v1",
                     done_when="It glows.")
        return Brief(**{**good.__dict__, **kw})

    def test_a_good_brief_passes(self):
        self.assertEqual(review.before("parts", project(self.b()), LIB)[0], [])

    def test_no_board(self):
        p = project(self.b(parts=["ws2812b_ring8"]))
        self.assertIn("review_no_board", keys(review.before("parts", p, LIB)[0]))

    def test_unknown_part(self):
        p = project(self.b(parts=["esp32_devkit_v1", "ws2812b_ring8", "flux_capacitor"]))
        self.assertIn("review_unknown_parts", keys(review.before("parts", p, LIB)[0]))

    def test_no_supply_stops_the_schematic_not_the_parts(self):
        p = project(self.b(supply_ma=0))
        self.assertNotIn("review_no_supply", keys(review.before("parts", p, LIB)[0]))
        save_result(p.root, type("R", (), {"stage": "parts", "ok": True, "results": [],
                                           "artifacts": [], "notes": [], "go_back_to": None,
                                           "degraded": False})())
        self.assertIn("review_no_supply", keys(review.before("electrical", p, LIB)[0]))

    def test_a_step_waits_for_the_one_it_builds_on(self):
        p = project(self.b())
        self.assertIn("review_needs_electrical", keys(review.before("firmware", p, LIB)[0]))

    def test_a_box_too_small_stops_the_enclosure(self):
        p = project(self.b(envelope_mm=[20, 20, 5]))
        self.assertIn("review_too_small", keys(review.before("enclosure", p, LIB)[0]))

    def test_each_stop_names_the_employee_to_fix_it(self):
        p = project(self.b(parts=["ws2812b_ring8", "flux_capacitor"]))
        for r in review.before("parts", p, LIB)[0]:
            self.assertTrue(any(i.startswith("For the ") for i in r.items), r.name)


class TestRunAsksTheReviewerFirst(unittest.TestCase):
    """`nemo run`, which the window's Run buttons use: a stop is a failed
    step with the Reviewer's checks, the step itself never runs, and the
    handoff is in the work log."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()

    def tearDown(self):
        self._env.stop(); self.t.cleanup()

    def test_stopped_before_the_designer_began(self):
        from nemo import cli
        from nemo.config import Config
        root = Config.load().path("paths.projects") / "tag-player"
        Project(root).create(PLAYER)
        with mock.patch("nemo.pipeline.Pipeline.stage_parts") as parts, \
             redirect_stdout(io.StringIO()) as out:
            rc = cli.main(["--project", "tag-player", "run", "--only", "parts"])
        self.assertEqual(rc, 1)
        parts.assert_not_called()
        self.assertIn("Inspector stopped this step", out.getvalue())
        rec = json.loads((root / ".nemo" / "results.json").read_text(encoding="utf-8"))
        self.assertIn("review_missing_rfid", [c["name"] for c in rec["parts"]["checks"]])
        log = review.work_log(root)
        reviewed = [e for e in log if e["event"] == "reviewed"]
        self.assertIn("review_missing_rfid", reviewed[-1]["stops"])
        self.assertEqual(log[-1]["event"], "researched")      # then the Researcher looked


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindowShowsTheStaff(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        from nemo.config import Config
        self.root = Config.load().path("paths.projects") / "tag-player"
        Project(self.root).create(PLAYER)
        review.record(self.root, "parts", "reviewed", stops=["review_missing_rfid"], notes=1)
        self.A = A
        self.app = A.NemoApp(); self.app.update()
        self.app.refresh_projects(select="tag-player"); self.app.update()

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def test_each_step_names_its_employee(self):
        texts = [self.app.traveller.itemcget(i, "text")
                 for i in self.app.traveller.find_all()
                 if self.app.traveller.type(i) == "text"]
        joined = " ".join(texts)
        for who in ("Workshop Designer", "Computer Lab Coder", "Workshop Writer"):
            self.assertIn(who, joined)

    def test_the_work_log_says_what_the_reviewer_stopped(self):
        w = self.A.WorkLog(self.app); self.app.update()
        body = [c for c in w.winfo_children() if isinstance(c, self.A.tk.Text)][0].get("1.0", "end")
        self.assertIn("Inspector: no RFID reader", body)
        w.destroy()



# ----------------------------------------------------------------- D184
class TestTheReviewerStopsWhatReallyFailed(unittest.TestCase):
    """D184, the AH531 on 2026-10-18: briefs with two boards, with "sound
    effects" and no speaker, and with five parts nothing asked for, went past
    the Reviewer as notes and failed later."""

    def brief(self, **kw):
        base = Brief(name="x", function="A lamp whose LEDs glow.", power="USB 5 V 1 A",
                     supply_ma=1000, rails=[5.0, 3.3], envelope_mm=[100, 80, 40],
                     parts=["esp32_devkit_v1", "ws2812b_ring8"], mcu="esp32_devkit_v1",
                     done_when="It glows.")
        return Brief(**{**base.__dict__, **kw})

    def stops(self, b):
        return {r.name: r for r in review.before("parts", project(b), LIB)[0]}

    def fix(self, b, key):
        rec = {"checks": [{"name": r.name, "status": r.status, "detail": r.detail,
                           "items": r.items} for r in self.stops(b).values()]}
        return {f.key: f for f in suggest_fixes(b, LIB, "parts", rec)}[key]

    def test_two_boards_stop_with_a_fix_for_each(self):
        b = self.brief(parts=["esp32_devkit_v1", "rp2040_pico", "ws2812b_ring8"])
        self.assertIn("review_boards_many", self.stops(b))
        kept = apply_fix(b, self.fix(b, "review_keep_rp2040_pico"))
        self.assertEqual(kept.parts, ["rp2040_pico", "ws2812b_ring8"])
        self.assertEqual(kept.mcu, "rp2040_pico")
        self.assertNotIn("review_boards_many", self.stops(kept))

    def test_sound_asked_for_with_no_speaker(self):
        b = self.brief(function="A replica lantern with light and sound effects.")
        self.assertIn("review_missing_sound", self.stops(b))
        b2 = apply_fix(b, self.fix(b, "review_add_speaker_8ohm_20mm"))
        self.assertNotIn("review_missing_sound", self.stops(b2))

    def test_parts_nothing_asks_for_are_removed_in_one_go(self):
        b = self.brief(parts=["esp32_devkit_v1", "ws2812b_ring8", "bme280", "sg90_servo"])
        self.assertIn("review_unexplained_parts", self.stops(b))
        clean = apply_fix(b, self.fix(b, "review_drop_unexplained"))
        self.assertEqual(clean.parts, ["esp32_devkit_v1", "ws2812b_ring8"])
        self.assertEqual(self.stops(clean), {})

    def test_or_kept_when_the_owner_says_they_are_needed(self):
        b = self.brief(parts=["esp32_devkit_v1", "ws2812b_ring8", "bme280"])
        ok = apply_fix(b, self.fix(b, "review_accept_unexplained_parts"))
        stops, notes = review.before("parts", project(ok), LIB)
        self.assertEqual(stops, [])
        self.assertTrue(any("you said they are needed" in n for n in notes))
