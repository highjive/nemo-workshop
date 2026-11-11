"""D162: a thing the brief names and no part is, is asked about.

The fourth real design (AH531, 2026-10-07): "A bin lid that a small servo
opens when a hand comes near, with a relay that switches a 5 V fan while
the lid is open." Parts: a board, a distance sensor, a servo, a relay.
All steps passed twice. The fan was in no parts list, no power budget and
on no cable, and nothing said so.
"""
from __future__ import annotations

import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import named
from nemo.parts import PartsLibrary
from nemo.project import Brief
from test_gates_real import WeatherCase
from test_pipeline import PipelineCase, StubRouter

LIB = PartsLibrary.load()
REAL = ("A bin lid that a small servo opens when a hand comes near, with a relay that "
        "switches a 5 V fan while the lid is open.")
LID = ("esp32_devkit_v1", "vl53l0x", "sg90_servo", "relay_5v_1ch")
ASK = ("the brief names a fan and no part in the list is one. Its current is not in the power "
       "budget and it is on no cable. Add it to the parts, or give its peak current under "
       "extra_loads in brief.yaml, or confirm the brief means something else")


def absent(function, refs, **kw):
    b = Brief(name="x", function=function, power="USB 5 V 2 A", supply_ma=2000, rails=[5.0, 3.3],
              envelope_mm=[100, 60, 40], parts=list(refs), mcu="esp32", **kw)
    return named.named_but_absent(b, [LIB.get(r) for r in refs])


class TestWhatIsNamedAndMissing(unittest.TestCase):
    def test_the_real_briefs_fan(self):
        self.assertEqual(absent(REAL, LID), ["a fan"])
        self.assertEqual(named.question(["a fan"]), ASK)

    def test_the_servo_and_the_relay_it_also_names_are_parts_and_are_not_asked_about(self):
        self.assertNotIn("servo", " ".join(named.LOADS))
        self.assertEqual(absent("A servo and a relay.", LID), [])

    def test_a_motor_driver_is_not_a_motor(self):
        self.assertEqual(absent("A cart with two motors.", ("esp32_devkit_v1", "drv8833")),
                         ["a motor"])

    def test_things_that_are_in_the_parts_are_not_asked_about(self):
        self.assertEqual(absent("Plays a tune through a speaker and shows it on a display, "
                                "with a ring of lights.",
                                ("esp32_devkit_v1", "dfplayer_mini", "speaker_8ohm_20mm",
                                 "ssd1306_oled_096", "ws2812b_ring8")), [])

    def test_the_same_brief_without_them_asks_about_each_in_one_sentence(self):
        got = absent("Plays a tune through a speaker and shows it on a display, with a ring "
                     "of lights.", ("esp32_devkit_v1", "dfplayer_mini"))
        self.assertEqual(got, ["a speaker", "lights", "a display"])
        self.assertEqual(named.question(got),
                         "the brief names a speaker, lights and a display and no part in the "
                         "list is any of them. Their current is not in the power budget and "
                         "they are on no cable. Add them to the parts, or give their peak "
                         "current under extra_loads in brief.yaml, or confirm the brief means "
                         "something else")

    def test_done_when_and_constraints_are_read_and_the_name_is_not(self):
        self.assertEqual(absent("A box.", LID, done_when="The pump runs for a minute."),
                         ["a pump"])
        self.assertEqual(absent("A box.", LID, constraints=["The heater must cut out at 60 C."]),
                         ["a heater"])
        b = Brief(name="desk-fan", function="A box.", power="USB", supply_ma=500, rails=[5.0],
                  envelope_mm=[50, 50, 50], parts=list(LID), mcu="esp32")
        self.assertEqual(named.named_but_absent(b, [LIB.get(r) for r in LID]), [])

    def test_whole_words_only(self):
        for text in ("An infant's night light.", "It is controlled by a dial.",
                     "A fanfare when the door opens.", "Pumped-up kicks.", "A motorway sign."):
            self.assertEqual(absent(text, LID), [], text)

    def test_any_case_and_plurals(self):
        self.assertEqual(absent("Two FANS and three LEDs.", LID), ["a fan", "lights"])

    def test_nothing_named_nothing_asked(self):
        self.assertEqual(absent("Shows temperature and humidity.",
                                ("esp32_devkit_v1", "bme280", "ssd1306_oled_096")), [])
        self.assertEqual(named.question([]), "")

    def test_other_names_for_the_same_thing(self):
        for text, thing in (("A relay that switches a blower.", "a fan"),
                            ("Two ventilators in the roof.", "a fan"),
                            ("A gearmotor turns the drum.", "a motor"),
                            ("A heating pad under the tray.", "a heater"),
                            ("An electromagnet holds the door.", "a solenoid"),
                            ("A siren when it trips.", "a buzzer"),
                            ("A bulb that comes on at dusk.", "lights"),
                            ("A light strip under the shelf.", "lights")):
            self.assertEqual(absent(text, LID), [thing], text)

    def test_a_thing_the_brief_says_it_does_not_want_is_not_asked_about(self):
        for text in ("No fan is needed.", "It runs without a fan.", "A fan is not needed.",
                     "Fans are not required.", "It has no cooling fan.", "It needs no pump.",
                     "The lid does not need a motor.", "A quiet box: no fans, no buzzer.",
                     "A speaker isn't wanted here.", "It doesn't use a display."):
            self.assertEqual(absent(text, LID), [], text)

    def test_wanted_in_one_place_and_refused_in_another_is_asked_about(self):
        self.assertEqual(absent("A fan cools the box. No fan is needed in winter.", LID),
                         ["a fan"])

    def test_a_refusal_does_not_reach_past_its_own_clause(self):
        self.assertEqual(absent("It has no display, but a fan and a pump.", LID),
                         ["a fan", "a pump"])
        self.assertEqual(absent("No one wants a fan that rattles.", LID), ["a fan"])

    def test_what_it_still_does_not_see_is_known(self):
        self.assertEqual(absent("A relay that switches an extractor.", LID), [])
        self.assertEqual(absent("Leave the fan out.", LID), ["a fan"])


class TestALoadTheBriefGivesAFigureFor(unittest.TestCase):
    FAN = [{"name": "5 V fan", "ma": 200}]

    def test_it_settles_the_question(self):
        self.assertEqual(absent(REAL, LID, extra_loads=self.FAN), [])

    def test_only_for_the_thing_it_names(self):
        self.assertEqual(absent("A fan and a pump.", LID, extra_loads=self.FAN), ["a pump"])
        self.assertEqual(absent(REAL, LID, extra_loads=[{"name": "fanfare horn", "ma": 50}]),
                         ["a fan"])

    def test_another_name_for_the_thing_settles_it_too(self):
        self.assertEqual(absent(REAL, LID, extra_loads=[{"name": "blower", "ma": 150}]), [])

    def test_entries_that_cannot_be_used_are_named_and_settle_nothing(self):
        b = Brief(name="x", function=REAL, parts=list(LID), extra_loads=[
            {"name": "fan"}, {"name": "fan", "ma": 0}, {"name": "fan", "ma": True},
            {"name": "", "ma": 5}, "fan", {"name": "fan", "ma": "200"}])
        good, bad = named.extra_loads(b)
        self.assertEqual(good, [])
        self.assertEqual(bad, ["extra load 'fan' has no current in mA above zero"] * 3
                         + ["extra load 4 has no name", "extra load 5 has no name",
                            "extra load 'fan' has no current in mA above zero"])
        self.assertEqual(named.named_but_absent(b, [LIB.get(r) for r in LID]), ["a fan"])

    def test_it_is_counted_against_the_supply_and_marked_as_the_briefs(self):
        from nemo.checks.deterministic import current_sum
        parts = [LIB.get(r) for r in LID]
        without = current_sum(parts, 2000)
        with_fan = current_sum(parts, 2000, extra=[("5 V fan", 200.0)])
        self.assertEqual(without.detail, "990 mA of 2000 mA")
        self.assertEqual(with_fan.detail, "1190 mA of 2000 mA")
        self.assertIn("5 V fan: 200 mA (the brief's own figure, not the library's)",
                      with_fan.items)

    def test_and_can_fail_the_budget_that_passed_without_it(self):
        from nemo.checks.deterministic import current_sum
        r = current_sum([LIB.get(r) for r in LID], 2000, extra=[("heater", 600.0)])
        self.assertEqual(r.status, "FAIL")
        self.assertIn("1590 mA", r.detail)

    def test_a_brief_saved_before_this_loads_and_has_none(self):
        self.assertEqual(Brief(name="x").extra_loads, [])


class LidCase(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="hand-lid", function=REAL, power="USB 5 V 2 A", supply_ma=2000,
            rails=[5.0, 3.3], envelope_mm=[150, 100, 50], parts=list(LID), mcu="esp32",
            done_when="The lid opens."))


class TestTheStepsSayIt(LidCase):
    def test_the_parts_step_says_it_and_still_passes(self):
        sr = self.pipe(StubRouter()).stage_parts()
        self.assertTrue(sr.ok, sr.render())
        self.assertEqual(sr.notes, ["The" + ASK[3:] + "."])

    def test_the_power_budget_says_what_it_leaves_out(self):
        self.pipe(StubRouter()).stage_parts()
        text = self.project.power_path.read_text(encoding="utf-8")
        self.assertIn("**Peak total: 990 mA**", text)
        self.assertIn(f"**Not in this budget:** {ASK}.", text)

    def test_the_guide_asks(self):
        self.pipe(StubRouter()).stage_pack([])
        text = self.project.build_md.read_text(encoding="utf-8")
        self.assertIn(f"- [parts] {ASK}", text[text.index("## Open questions"):])


class TestTheStepsWithTheFanGiven(PipelineCase):
    def setUp(self):
        super().setUp()
        self.project.create(Brief(
            name="hand-lid", function=REAL, power="USB 5 V 2 A", supply_ma=2000,
            rails=[5.0, 3.3], envelope_mm=[150, 100, 50], parts=list(LID), mcu="esp32",
            done_when="The lid opens.",
            extra_loads=[{"name": "5 V fan", "ma": 200}, {"name": "pump"}]))

    def test_it_survives_the_file(self):
        self.assertEqual(self.project.load_brief().extra_loads,
                         [{"name": "5 V fan", "ma": 200}, {"name": "pump"}])

    def test_the_parts_step_counts_it_and_names_the_entry_it_could_not_use(self):
        sr = self.pipe(StubRouter()).stage_parts()
        self.assertTrue(sr.ok, sr.render())
        self.assertIn("1190 mA of 2000 mA", sr.render())
        self.assertEqual(sr.notes, ["In the brief's extra_loads, extra load 'pump' has no "
                                    "current in mA above zero: it is not counted."])

    def test_the_power_budget_has_its_row_and_the_new_total(self):
        self.pipe(StubRouter()).stage_parts()
        text = self.project.power_path.read_text(encoding="utf-8")
        self.assertIn("| 5 V fan | the brief's own figure | - | 200 |", text)
        self.assertIn("**Peak total: 1190 mA**", text)
        self.assertNotIn("Not in this budget", text)

    def test_the_guide_stops_asking_whether_and_says_what_is_still_open(self):
        self.pipe(StubRouter()).stage_pack([])
        text = self.project.build_md.read_text(encoding="utf-8")
        asked = text[text.index("## Open questions"):]
        self.assertNotIn("the brief names a fan", asked)
        self.assertIn("- [parts] 5 V fan (200 mA, the brief's own figure) is counted in the "
                      "power budget and nowhere else: it is on no cable and in no enclosure, "
                      "and where it takes its current from is not checked", asked)
        self.assertIn("- [parts] in the brief's extra_loads, extra load 'pump' has no current "
                      "in mA above zero: it is not counted", asked)


class TestTheWindowsBoxForThem(unittest.TestCase):
    def setUp(self):
        from nemo.gui import controller
        self.C = controller

    def test_a_name_and_a_number_per_line(self):
        self.assertEqual(self.C.parse_extra_loads("fan, 200\npump: 350 mA\n\n  heater 1200mA  "),
                         [{"name": "fan", "ma": 200}, {"name": "pump", "ma": 350},
                          {"name": "heater", "ma": 1200}])

    def test_the_last_number_is_the_current_so_a_voltage_stays_in_the_name(self):
        self.assertEqual(self.C.parse_extra_loads("5 V fan, 200\n12 V pump 0.5"),
                         [{"name": "5 V fan", "ma": 200}, {"name": "12 V pump", "ma": 0.5}])

    def test_a_line_with_no_current_is_kept_by_name_and_not_dropped(self):
        got = self.C.parse_extra_loads("5 V fan\n200\nfan, lots")
        self.assertEqual(got, [{"name": "5 V fan"}, {"name": "200"}, {"name": "fan, lots"}])
        good, bad = named.extra_loads(Brief(name="x", extra_loads=got))
        self.assertEqual((good, len(bad)), ([], 3))

    def test_what_is_typed_comes_back_as_typed_and_settles_the_question(self):
        loads = self.C.parse_extra_loads("5 V fan, 200")
        self.assertEqual(self.C.format_extra_loads(loads), "5 V fan, 200")
        self.assertEqual(self.C.parse_extra_loads(self.C.format_extra_loads(loads)), loads)
        self.assertEqual(absent(REAL, LID, extra_loads=loads), [])

    def test_showing_entries_the_box_cannot_hold(self):
        self.assertEqual(self.C.format_extra_loads(
            [{"name": "fan"}, "junk", {"ma": 5}, {"name": "pump", "ma": True},
             {"name": "lamp", "ma": 12.5}]), "fan\npump\nlamp, 12.5")
        self.assertEqual(self.C.format_extra_loads(None), "")

    def test_the_form_has_the_box_and_reads_and_fills_it(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "gui" / "app.py").read_text(
            encoding="utf-8")
        self.assertIn('row(13, "Other loads", self.fields["extra_loads"])', src)
        self.assertIn('extra_loads=C.parse_extra_loads(self._get("extra_loads"))', src)
        self.assertIn('self._put("extra_loads", C.format_extra_loads(b.extra_loads))', src)


class TestAProjectThatNamesNothingMissing(WeatherCase):
    def test_has_no_such_line_anywhere(self):
        pipe = self.pipe(StubRouter())
        sr = pipe.stage_parts()
        pipe.stage_pack([])
        self.assertEqual(sr.notes, [])
        self.assertNotIn("Not in this budget", self.project.power_path.read_text(encoding="utf-8"))
        self.assertNotIn("the brief names", self.project.build_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
