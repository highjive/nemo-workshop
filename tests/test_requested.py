"""What the owner's request asked for, decided by code after the model drafts
the brief (owner, 2026-11-05: "run test of blunderbuss through nemo llm then
fix"). The drafts below are qwen3-8b's own, from that run.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import requested, review, steps
from nemo.project import Brief, Project

REQUEST = ("A replica blunderbuss gun with a mechanical trigger and cocking mechanism that "
           "simulates the firing action, full size like a real one, to 3D print.")
# qwen3-8b's first draft of it, 2026-11-05 (blunderbuss-run1).
DRAFT = dict(
    name="blunderbuss_gun",
    function=("The blunderbuss gun is a 3D-printed replica that simulates the firing action of "
              "a real blunderbuss. It features a mechanical trigger and cocking mechanism to "
              "provide a realistic experience. The device includes sound effects and visual cues "
              "to enhance the simulation."),
    done_when=("The mechanical trigger and cocking mechanism operate smoothly, and the sound and "
               "visual effects are activated correctly upon triggering."))


class TestWhatWasNotAskedFor(unittest.TestCase):
    def test_the_models_added_features_are_found_and_taken_out(self):
        b = Brief(**DRAFT)
        self.assertEqual([t for t, _ in requested.invented(REQUEST, b)], ["a speaker", "lights"])
        said = requested.strip_invented(REQUEST, b)
        self.assertNotIn("sound", b.function.lower())
        self.assertNotIn("visual", b.function.lower())
        self.assertIn("mechanical trigger and cocking mechanism", b.function)
        self.assertEqual(b.done_when, "The mechanical trigger and cocking mechanism operate smoothly.")
        self.assertIn("a speaker and lights", said[0])

    def test_the_parts_for_them_go_too(self):
        b = Brief(**DRAFT, parts=["rp2040_pico", "speaker_8ohm_20mm", "dfplayer_mini", "ws2812b_ring8"],
                  mcu="rp2040_pico")
        said = requested.strip_invented(REQUEST, b)
        self.assertEqual(b.parts, ["rp2040_pico", "dfplayer_mini"])     # the board, and what no lost feature names
        self.assertIn("speaker_8ohm_20mm", said[0])

    def test_what_the_request_did_ask_for_stays(self):
        b = Brief(**DRAFT)
        asked = REQUEST + " It plays a firing sound and its muzzle lights up."
        self.assertEqual(requested.invented(asked, b), [])
        self.assertEqual(requested.strip_invented(asked, b), [])
        self.assertIn("sound effects", b.function)

    def test_a_test_of_done_naming_only_them_becomes_a_question(self):
        b = Brief(name="x", function="A replica blunderbuss.", done_when="The sound plays.")
        requested.strip_invented("a replica blunderbuss", b)
        self.assertEqual(b.done_when, "")
        self.assertTrue(any("How will you know it works" in q for q in b.open_questions))


class TestAMechanicalProp(unittest.TestCase):
    def test_a_printed_replica_with_nothing_electrical(self):
        b = Brief(**DRAFT)
        requested.strip_invented(REQUEST, b)
        self.assertTrue(requested.mechanical(REQUEST, b))

    def test_not_when_anything_electrical_is_named(self):
        for extra in (" with a light in the barrel", " powered by USB", " with a servo trigger",
                      " that plays a bang"):
            b = Brief(name="x", function="A replica blunderbuss" + extra)
            self.assertFalse(requested.mechanical(REQUEST + extra, b), extra)

    def test_not_for_a_device(self):
        b = Brief(name="x", function="A weather station for the garden.")
        self.assertFalse(requested.mechanical("a weather station", b))


class TestTheRealSize(unittest.TestCase):
    def test_read_from_the_request_with_its_unit_and_way(self):
        self.assertEqual(requested.size_from("a sword 90 cm long"), [900.0, 0.0, 0.0])
        self.assertEqual(requested.size_from("a lighthouse 30cm tall and 12 cm wide"),
                         [0.0, 120.0, 300.0])
        self.assertEqual(requested.size_from("a musket 5 ft long"), [1524.0, 0.0, 0.0])
        self.assertEqual(requested.size_from('a pistol 14" long'), [355.6, 0.0, 0.0])

    def test_a_bare_number_or_none_is_not_taken(self):
        for words in ("full size like a real one", "about 80 long", "a 1780 blunderbuss",
                      "80 cm"):
            self.assertIsNone(requested.size_from(words), words)

    def test_asked_for_where_nemo_can_build_it(self):
        b = Brief(name="x", function="A replica blunderbuss gun.")
        self.assertEqual(requested.shape_notes(REQUEST, b), [])
        self.assertTrue(any("real size" in q and "barrel" in q for q in b.open_questions))
        b = Brief(name="x", function="A replica blunderbuss gun.")
        said = requested.shape_notes(REQUEST + " It is 86 cm long.", b)
        self.assertEqual(b.shape_size_mm, [860.0, 0.0, 0.0])
        self.assertIn("from your request", said[0])
        b = Brief(name="x", function="A replica of a garden gnome.")
        requested.shape_notes("a replica of a garden gnome", b)
        self.assertEqual(b.open_questions, [])                     # Nemo cannot build it anyway


PLANT = ("A soil moisture alarm for a house plant: it beeps and lights a red LED when the soil "
         "is dry. Runs from a USB phone charger. Small enough to sit in the pot.")
# qwen3-8b's first draft of it, 2026-11-06 (plant-alarm run 1): a thermometer,
# a relay and a LiPo charger nobody asked for, and the board left out of the parts.
PLANT_PARTS = ["ds18b20", "relay_5v_1ch", "speaker_8ohm_20mm", "red_led", "resistor_220ohm",
               "soil_moisture_sensor", "tp4056_protected"]


class TestPartsNobodyAskedFor(unittest.TestCase):
    def draft(self):
        return Brief(name="soil_moisture_alarm", mcu="esp32_devkit_v1", parts=list(PLANT_PARTS),
                     function="The soil moisture alarm triggers a beep and a red LED when the "
                              "soil is dry.")

    def test_the_models_extra_parts_go_and_it_says_so(self):
        b = self.draft()
        said = requested.unasked_parts(PLANT, b)
        self.assertEqual(b.parts, ["speaker_8ohm_20mm", "red_led", "resistor_220ohm",
                                   "soil_moisture_sensor"])
        self.assertIn("no reason for ds18b20, relay_5v_1ch, tp4056_protected", said[0])
        self.assertIn("if they are needed", said[0])

    def test_what_the_request_names_stays(self):
        b = self.draft()
        asked = PLANT + " It has a rechargeable battery, shows the temperature and switches a pump."
        self.assertEqual(requested.unasked_parts(asked, b), [])
        self.assertEqual(b.parts, PLANT_PARTS)

    def test_the_owners_choices_and_the_board_stay(self):
        b = self.draft(); b.parts.append("esp32_devkit_v1")
        requested.unasked_parts(PLANT, b, chosen=["relay_5v_1ch"])
        self.assertIn("relay_5v_1ch", b.parts)
        self.assertIn("esp32_devkit_v1", b.parts)

    def test_the_board_is_put_among_the_parts(self):
        b = self.draft()
        requested.board_in_parts(b, {"esp32_devkit_v1": object()})
        self.assertEqual(b.parts[0], "esp32_devkit_v1")
        b = Brief(name="x", mcu="made_up_board", parts=["bme280"])
        requested.board_in_parts(b, {"esp32_devkit_v1": object()})
        self.assertEqual(b.parts, ["bme280"])                       # not one the library has


class TestTheInspectorsWords(unittest.TestCase):
    def test_the_shape_is_not_quoted_as_linking_words(self):
        # 2026-11-05: "a 3D-printed replica that simulates the firing action of a
        # real blunderbuss" was quoted as the shape "replica that simulates the".
        b = Brief(name="x", function=DRAFT["function"])
        self.assertEqual(review.shape_asked(b), "blunderbuss")

    def test_a_kind_nemo_can_build_named_as_a_prop_is_shaped(self):
        for words, said in (("a full-size prop sword for a play", "sword"),
                            ("A replica Blunderbust gun", "replica blunderbust gun")):
            self.assertEqual(review.shape_asked(Brief(name="x", function=words)), said)
        for words in ("a box that holds my house keys", "replicate the readings to a display",
                      "a weather station"):
            self.assertIsNone(review.shape_asked(Brief(name="x", function=words)), words)


class TestAPropHasNoCase(unittest.TestCase):
    def prop(self, **kw):
        b = dict(name="x", function="A replica blunderbuss gun.", done_when="it cocks",
                 no_power=True, no_parts=True)
        b.update(kw)
        return Brief(**b)

    def test_its_real_size_is_asked_for_not_an_inside_size(self):
        # 2026-11-05: the brief of a printed prop asked for an enclosure's inside size.
        self.assertEqual(self.prop().complete, (False, ["shape_size_mm"]))
        self.assertEqual(self.prop(shape_size_mm=[857, 0, 0]).complete, (True, []))
        self.assertEqual(Brief(name="x", function="a weather station", done_when="it reads",
                               power="USB", parts=["bme280"]).complete[1], ["envelope_mm"])

    def test_the_enclosure_has_nothing_to_do_and_is_not_stopped(self):
        # 2026-11-05: it stopped as "a shape Nemo cannot make", on every run.
        b = self.prop(shape_size_mm=[857, 74, 188])
        self.assertIn("no case to make", steps.not_needed("enclosure", b))
        self.assertFalse(steps.asks_model("enclosure", b))
        with tempfile.TemporaryDirectory() as t:
            p = Project(Path(t) / "p"); p.create(b)
            stops, notes = review.before("enclosure", p, mock.Mock(get=lambda r: None, parts={}))
        self.assertNotIn("review_shape_unsupported", [s.name for s in stops])
        self.assertIsNone(steps.not_needed("enclosure", self.prop(no_parts=False, parts=["sg90_servo"])))


ROBOT = ("A small robot car: two small DC motors driven by a DRV8833, a VL53L0X distance "
         "sensor so it stops before it hits a wall, an ESP32-C3 board, powered by a 1000 mAh "
         "LiPo cell with a charger.")


class TestTheRobotCar(unittest.TestCase):
    """The robot car through qwen3-8b, 2026-11-08: three drafts of one request."""

    @classmethod
    def setUpClass(cls):
        from nemo.parts import PartsLibrary
        cls.known = PartsLibrary.load().parts

    def test_a_near_miss_reference_is_the_librarys_part(self):
        # Drafts 1-3: "esp32c3_devkitc_1", close to esp32c3_devkit AND to
        # esp32s3_devkitc_1 (and esp32_devkit_v1): the request says ESP32-C3.
        b = Brief(name="car", mcu="esp32c3_devkitc_1",
                  parts=["drv8833", "vl53l0x", "esp32c3_devkitc_1"])
        said = requested.library_refs(b, self.known, ROBOT)
        self.assertEqual((b.mcu, b.parts[2]), ("esp32c3_devkit", "esp32c3_devkit"))
        self.assertEqual(len(said), 1)
        self.assertIn("the model wrote esp32c3_devkitc_1", said[0])
        # Not said which: left for the Inspector, never guessed.
        b = Brief(name="car", mcu="esp32c3_devkitc_1", parts=["esp32c3_devkitc_1"])
        self.assertEqual(requested.library_refs(b, self.known, "a robot car"), [])
        self.assertEqual(b.mcu, "esp32c3_devkitc_1")
        b = Brief(name="car", mcu="esp32_devkit", parts=[])
        requested.library_refs(b, self.known, "an ESP32 board")
        self.assertEqual(b.mcu, "esp32_devkit_v1")

    def test_the_cell_and_charger_the_request_names(self):
        # Draft 1: the cell, no charger, "What type of charger is required?".
        b = Brief(name="car", mcu="esp32c3_devkit", parts=["esp32c3_devkit", "lipo_1000"],
                  open_questions=["What type of charger is required for the 1000 mAh LiPo?",
                                  "How fast should it go?"])
        said = requested.asked_charger(ROBOT, b, self.known)
        self.assertIn("tp4056_protected", b.parts)
        self.assertEqual(b.open_questions, ["How fast should it go?"])
        self.assertIn("That answers", said[0])
        # Draft 2: the charger, no cell.
        b = Brief(name="car", mcu="esp32c3_devkit", parts=["esp32c3_devkit", "tp4056_protected"])
        self.assertIn("lipo_1000", requested.asked_cell(ROBOT, b, self.known)[0])
        self.assertIn("lipo_1000", b.parts)
        # Neither when the request does not ask.
        b = Brief(name="car", mcu="esp32c3_devkit", parts=["esp32c3_devkit", "lipo_1000"])
        self.assertEqual(requested.asked_charger("a robot car on a LiPo", b, self.known), [])
        self.assertEqual(requested.asked_cell("a robot car", b, self.known), [])

    def test_what_the_request_says_a_part_is_for_reaches_the_brief(self):
        # D270, 2026-11-11, Gemma 4 E4B: the request said "two small DC motors driven
        # by a DRV8833"; the draft never said "motor" and the Inspector stopped.
        req = ("A small robot car: two small DC motors driven by a DRV8833, a VL53L0X "
               "distance sensor so it stops before it hits a wall, an ESP32-C3 board.")
        b = Brief(name="robot", function="This robot car stops before colliding with a wall.",
                  parts=["esp32c3_devkit", "drv8833", "vl53l0x"], mcu="esp32c3_devkit",
                  constraints=["Must use the specified components."])
        explained = lambda: review._said(review.PURPOSE["drv8833"], review._text(b))
        self.assertFalse(explained())
        said = requested.purposes_from_request(req, b)
        self.assertIn("Your request: two small DC motors driven by a DRV8833", b.constraints)
        self.assertIn("drv8833", said[0])
        self.assertTrue(explained())                                     # what the Inspector reads
        self.assertEqual(requested.purposes_from_request(req, b), [])      # said once

    def test_a_draft_with_no_box_gets_one_that_holds_its_parts(self):
        # 2026-11-11, Gemma 4 E4B: both drafts gave no envelope_mm and the brief stopped
        # as incomplete, though the box can be sized from the parts.
        from nemo.enclosure import layout_fault
        b = Brief(name="car", mcu="esp32c3_devkit", parts=["esp32c3_devkit", "drv8833", "vl53l0x"])
        said = requested.envelope_fits(ROBOT, b, self.known)
        self.assertEqual(len(b.envelope_mm), 3)
        self.assertIsNone(layout_fault([self.known[r] for r in b.parts], b.envelope_mm))
        self.assertIn("the model gave none", said[0])
        b = Brief(name="car", parts=["esp32c3_devkit"])
        self.assertEqual(requested.envelope_fits("a box 90 mm long and 50 mm wide", b, self.known), [])
        self.assertEqual(b.envelope_mm, [])                        # a size asked for: not Nemo's

    def test_the_writer_knows_its_parts_model_names(self):
        from nemo import writer
        words = writer.known_words(Brief(name="car"), mock.Mock(parts=self.known))
        self.assertIn("C3", words)                       # "ESP32-C3" was "Co?"
        self.assertIn("ESP32", words)
        self.assertIn("oled", words)                     # Gemma 4 wrote "oled": "old?" (2026-11-11)
        self.assertIn("bme280", words)
        self.assertNotIn("mini", words)                  # a plain name stays as written


class TestTheBriefStep(unittest.TestCase):
    """The step itself, given the model's real first draft."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()

    def tearDown(self):
        self._env.stop(); self.t.cleanup()

    def draft(self, owner_ticked=False):
        import yaml
        from nemo.config import Config
        from nemo.parts import PartsLibrary
        from nemo.pipeline import Pipeline
        cfg = Config.load(Path("/nonexistent"))
        p = Project(cfg.path("paths.projects") / "b")
        p.create(Brief(name="b", function=REQUEST, no_power=owner_ticked))
        reply = "```yaml\n" + yaml.safe_dump(DRAFT, sort_keys=False) + "```"
        pipe = Pipeline(p, cfg, mock.Mock(), PartsLibrary.load())
        with mock.patch.object(pipe, "_ask", return_value=(reply, False)):
            r = pipe.stage_brief(REQUEST)
        return r, p.load_brief()

    def test_invented_features_out_a_prop_ticked_and_its_size_asked(self):
        r, b = self.draft()
        self.assertNotIn("sound", b.function.lower())
        self.assertTrue(b.no_power and b.no_parts)
        self.assertEqual(b.parts, [])
        self.assertEqual(b.complete[1], ["shape_size_mm"])
        self.assertTrue(any("real size" in q for q in b.open_questions))
        text = " ".join(r.notes)
        self.assertIn("did not ask for a speaker and lights", text)
        self.assertIn("No power and No parts are ticked", text)

    def test_a_device_draft_loses_its_unasked_parts_and_gains_its_board(self):
        import yaml
        from nemo.config import Config
        from nemo.parts import PartsLibrary
        from nemo.pipeline import Pipeline
        cfg = Config.load(Path("/nonexistent"))
        p = Project(cfg.path("paths.projects") / "plant")
        p.create(Brief(name="plant", function=PLANT))
        p.brief_path.unlink()                                      # a first draft
        draft = dict(name="soil_moisture_alarm", function="It beeps and lights a red LED "
                     "when the soil is dry.", power="USB 5 V 1 A", supply_ma=1000,
                     envelope_mm=[50, 30, 20], parts=list(PLANT_PARTS), mcu="esp32_devkit_v1",
                     done_when="It beeps when the soil is dry.")
        reply = "```yaml\n" + yaml.safe_dump(draft, sort_keys=False) + "```"
        pipe = Pipeline(p, cfg, mock.Mock(), PartsLibrary.load())
        with mock.patch.object(pipe, "_ask", return_value=(reply, False)):
            r = pipe.stage_brief(PLANT)
        b = p.load_brief()
        self.assertEqual(b.parts[0], "esp32_devkit_v1")
        for ref in ("ds18b20", "relay_5v_1ch", "tp4056_protected"):
            self.assertNotIn(ref, b.parts)
        self.assertIn("no reason for ds18b20", " ".join(r.notes))

    def test_the_owners_own_ticks_are_not_overruled(self):
        r, b = self.draft(owner_ticked=True)
        self.assertNotIn("No power and No parts are ticked", " ".join(r.notes))


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheBriefTab(unittest.TestCase):
    """D225, 2026-11-05: the Brief tab had no field for a shaped object's real
    size or its own figures, and Save brief rebuilt the brief without them: a
    save from the window erased both."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        from nemo.config import Config
        root = Config.load().path("paths.projects") / "gun"
        Project(root).create(Brief(name="gun", function="A replica blunderbuss gun.",
                                   no_power=True, no_parts=True, shape_size_mm=[857.0, 74.0, 188.0],
                                   shape_facts={"barrel_mm": 444.0, "muzzle_bore_mm": 35.0}))
        self.app = A.NemoApp(); self.app.update()
        self.app.refresh_projects(select="gun"); self.app.update()

    def tearDown(self):
        self.app.destroy(); self._env.stop(); self.t.cleanup()

    def test_a_save_keeps_the_real_size_and_its_figures(self):
        b = self.app._form_brief()
        self.assertEqual(b.shape_size_mm, [857.0, 74.0, 188.0])
        self.assertEqual(b.shape_facts, {"barrel_mm": 444.0, "muzzle_bore_mm": 35.0})
        self.assertEqual(self.app._get("shape_size_mm"), "857 x 74 x 188")
        self.assertEqual(self.app._get("shape_facts"), "barrel 444, muzzle bore 35")

    def test_they_can_be_given_in_the_window(self):
        self.app._put("shape_size_mm", "900 x 0 x 0")
        self.app._put("shape_facts", "barrel 500")
        b = self.app._form_brief()
        self.assertEqual((b.shape_size_mm, b.shape_facts), ([900.0, 0.0, 0.0], {"barrel_mm": 500.0}))


class TestTheFiguresBox(unittest.TestCase):
    def test_read_and_written_alike_and_nothing_guessed(self):
        from nemo.gui import controller as C
        facts = C.parse_facts("barrel 444, muzzle bore 35")
        self.assertEqual(facts, {"barrel_mm": 444.0, "muzzle_bore_mm": 35.0})
        self.assertEqual(C.parse_facts(C.format_facts(facts)), facts)
        self.assertEqual(C.parse_facts("barrel, bore about"), {})


if __name__ == "__main__":
    unittest.main()
