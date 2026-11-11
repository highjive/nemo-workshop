"""D146: props, airsoft and toy bows go to a human sign-off under stated
conditions, instead of passing or being blocked by wording alone.

Security-critical: most of this file is about what must NOT get through,
and what no policy file or signed document can change.

Before: the scope guard was a word filter. "A toy sword with lights"
passed and "a replica weapon with lights" was blocked; "airsoft" and
"crossbow" were on no list, so a brief for either passed with no
condition at all unless it also said "weapon".
"""
from __future__ import annotations

import math, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import safety
from nemo.parts import PartsLibrary
from nemo.project import Brief
from nemo.safety import FLOOR, HARD_FLOOR, Policy, active_floor, blocking, review, signoffs

LIB = PartsLibrary.load()
LIGHTS = ["esp32_devkit_v1", "ws2812b_ring8", "dfplayer_mini", "speaker_8ohm_20mm"]
MOTOR = ["esp32_devkit_v1", "drv8833"]


def run(function, parts=LIGHTS, policy=None, **kw):
    b = Brief(name=kw.pop("name", "thing"), function=function, power="USB 5 V 2 A",
              supply_ma=4000, rails=[5.0, 3.3], envelope_mm=[200, 60, 40],
              parts=list(parts), mcu="esp32", **kw)
    return review(b, [LIB.get(r) for r in parts], policy)


def blocked(findings):
    return [f for f in blocking(findings) if f.rule == "forbidden_domains"]


def sign(findings, rule):
    return [f for f in signoffs(findings) if f.rule == rule]


def prop_signoff(findings):
    return sign(findings, "weapon_prop_requires_human_signoff")


def launcher_signoff(findings):
    return sign(findings, "launcher_requires_human_signoff")


# ---------------------------------------------------------------- props
class TestADeclaredPropGoesToASignOff(unittest.TestCase):
    def test_a_replica_with_lights_and_sound_is_not_blocked_and_needs_a_person(self):
        f = run("A replica weapon for a costume: lights along the blade and a hum.")
        self.assertEqual(blocked(f), [])
        self.assertEqual(len(prop_signoff(f)), 1)
        text = prop_signoff(f)[0].detail
        self.assertIn("a person must confirm that it cannot launch, fire or shock anything", text)
        self.assertIn("the law on realistic imitations", text)

    def test_each_of_the_declaring_words_does_it(self):
        for word in ("prop", "replica", "toy", "cosplay", "costume"):
            f = run(f"A {word} firearm that lights up and plays a sound.")
            self.assertEqual(blocked(f), [], word)
            self.assertEqual(len(prop_signoff(f)), 1, word)

    def test_plurals_and_the_name_and_constraints_count(self):
        f = run("Lights and sound.", name="toy weapons", constraints=["Must be light."])
        self.assertEqual(blocked(f), [])
        self.assertEqual(len(prop_signoff(f)), 1)

    def test_undeclared_it_is_blocked_as_it_always_was(self):
        f = run("A weapon with lights along the blade.")
        self.assertEqual(len(blocked(f)), 1)
        self.assertEqual(prop_signoff(f), [])


class TestWhatStaysBlocked(unittest.TestCase):
    def test_every_functional_term_is_blocked_even_when_called_a_toy(self):
        for term in ("explosive", "detonator", "projectile launcher", "gauss gun", "coil gun",
                     "rail gun", "taser", "stun gun", "munition"):
            f = run(f"A toy {term} replica prop for cosplay with lights.")
            self.assertEqual(len(blocked(f)), 1, term)
            self.assertEqual(prop_signoff(f) + launcher_signoff(f), [], term)
            self.assertIn(term, blocked(f)[0].detail)

    def test_only_two_words_are_exempt_and_they_are_the_general_ones(self):
        self.assertEqual(safety.PROP_EXEMPT, frozenset({"weapon", "firearm"}))
        self.assertTrue(safety.PROP_EXEMPT <= set(HARD_FLOOR["forbidden_domains"]))

    def test_a_prop_that_also_names_a_functional_term_is_blocked_on_that(self):
        f = run("A replica weapon prop with a built-in taser effect.")
        self.assertEqual(len(blocked(f)), 1)
        self.assertEqual(prop_signoff(f), [])

    def test_the_unrelated_domains_are_untouched(self):
        for term in ("defibrillator", "infusion pump", "flight controller", "mains wiring"):
            self.assertEqual(len(blocked(run(f"A toy {term} prop."))), 1, term)

    def test_something_thrown_or_loaded_defeats_the_declaration_and_says_so(self):
        for word in ("projectile", "pellets", "darts", "BBs", "ammunition", "ammo",
                     "cartridge", "live rounds"):
            f = run(f"A toy weapon that fires {word} and lights up.")
            self.assertEqual(len(blocked(f)), 1, word)
            self.assertEqual(prop_signoff(f), [], word)
            self.assertIn("It is not let through as a prop", blocked(f)[0].detail)

    def test_a_purpose_named_only_in_done_when_is_read(self):
        f = run("A handheld thing with lights.", done_when="The weapon lights up.")
        self.assertEqual(len(blocked(f)), 1)
        f = run("A toy weapon with lights.", done_when="It shoots a dart across the room.")
        self.assertEqual(len(blocked(f)), 1)


class TestThePartsAreCheckedNotJustTheWords(unittest.TestCase):
    def test_a_servo_a_relay_or_a_motor_driver_defeats_a_prop_naming_the_part(self):
        for ref in ("sg90_servo", "relay_5v_1ch", "drv8833"):
            f = run("A replica weapon prop with lights.", parts=["esp32_devkit_v1", ref])
            self.assertEqual(len(blocked(f)), 1, ref)
            self.assertIn(ref, blocked(f)[0].detail)
            self.assertIn("can move or switch something", blocked(f)[0].detail)

    def test_which_parts_in_the_library_count_as_moving(self):
        self.assertEqual(sorted(safety.moving_parts(LIB.parts.values())),
                         ["drv8833", "relay_5v_1ch", "sg90_servo"])

    def test_those_same_parts_are_fine_in_a_project_that_is_not_a_prop(self):
        f = run("A desk fan controller.", parts=["esp32_devkit_v1", "relay_5v_1ch"])
        self.assertEqual(blocked(f), [])


# -------------------------------------------------------------- airsoft
class TestTheAirsoftLimitThatShips(unittest.TestCase):
    def test_it_is_the_figure_the_owner_gave(self):
        # 0.7 J, given by the owner on 2026-10-07. Not checked against a statute.
        self.assertEqual(safety.AIRSOFT_MAX_JOULES, 0.7)
        at = run("An electric airsoft trigger controller, muzzle energy 0.7 J.", parts=MOTOR)
        self.assertEqual(blocked(at), [])
        self.assertEqual(len(launcher_signoff(at)), 1)
        over = run("An electric airsoft trigger controller, muzzle energy 0.71 J.", parts=MOTOR)
        self.assertIn("0.71 J is over the 0.7 J set for airsoft", blocked(over)[0].detail)
        self.assertEqual(launcher_signoff(over), [])

    def test_with_no_limit_set_every_airsoft_brief_is_blocked_and_told_why(self):
        with mock.patch.object(safety, "AIRSOFT_MAX_JOULES", None):
            f = run("An electric airsoft trigger controller, muzzle energy 0.5 J.", parts=MOTOR)
        self.assertEqual(len(blocked(f)), 1)
        self.assertIn("no airsoft energy limit is set in safety.py (AIRSOFT_MAX_JOULES)",
                      blocked(f)[0].detail)
        self.assertEqual(launcher_signoff(f), [])

    def test_it_used_to_pass_with_no_condition_at_all(self):
        # Neither word of this brief was on any list before D146.
        words = set(FLOOR["forbidden_domains"])
        self.assertFalse(words & {"airsoft", "crossbow", "bow"})


@mock.patch.object(safety, "AIRSOFT_MAX_JOULES", 1.0)
class TestAirsoftWithALimitSet(unittest.TestCase):
    """The figure 1.0 is this test's own, not a statement of any law."""

    OK = "An electric airsoft trigger controller, muzzle energy 0.9 J."

    def test_within_the_limit_and_no_gas_it_goes_to_a_sign_off(self):
        f = run(self.OK, parts=MOTOR)
        self.assertEqual(blocked(f), [])
        self.assertEqual(len(launcher_signoff(f)), 1)
        text = launcher_signoff(f)[0].detail
        self.assertIn("a person must measure the energy of what it fires", text)
        self.assertIn("has checked nothing but the figures the brief states", text)

    def test_a_motor_driver_is_allowed_here_as_it_is_not_for_a_prop(self):
        self.assertEqual(blocked(run(self.OK, parts=MOTOR)), [])

    def test_over_the_limit_is_blocked_with_both_figures(self):
        f = run("An electric airsoft controller, muzzle energy 1.2 J.", parts=MOTOR)
        self.assertEqual(len(blocked(f)), 1)
        self.assertIn("1.2 J is over the 1 J set for airsoft", blocked(f)[0].detail)

    def test_exactly_at_the_limit_passes(self):
        self.assertEqual(blocked(run("An airsoft controller, 1.0 joules.", parts=MOTOR)), [])

    def test_no_energy_stated_is_blocked(self):
        f = run("An electric airsoft trigger controller.", parts=MOTOR)
        self.assertEqual(len(blocked(f)), 1)
        self.assertIn("does not state the energy of what it fires", blocked(f)[0].detail)

    def test_gas_by_any_of_its_names_is_blocked_whatever_the_energy(self):
        for gas in ("gas", "green gas", "CO2", "HPA", "propane", "compressed air",
                    "pneumatic", "an air tank", "pre-charged"):
            f = run(f"An airsoft pistol using {gas}, muzzle energy 0.5 J.", parts=MOTOR)
            self.assertEqual(len(blocked(f)), 1, gas)
            self.assertIn("nothing propelled by gas is allowed", blocked(f)[0].detail)
            self.assertEqual(launcher_signoff(f), [], gas)

    def test_the_word_gasket_is_not_gas(self):
        f = run("An airsoft controller with a sealed gasket, 0.9 J.", parts=MOTOR)
        self.assertEqual(blocked(f), [])

    def test_calling_it_a_replica_firearm_or_naming_bbs_does_not_block_it(self):
        f = run("An airsoft replica firearm controller for 6 mm BBs, 0.9 J.", parts=MOTOR)
        self.assertEqual(blocked(f), [])
        self.assertEqual(len(launcher_signoff(f)), 1)

    def test_but_every_functional_term_still_does(self):
        for term in ("taser", "coil gun", "explosive", "rail gun", "detonator"):
            f = run(f"An airsoft {term} controller, 0.9 J.", parts=MOTOR)
            self.assertEqual(len(blocked(f)), 1, term)
            self.assertIn(term, blocked(f)[0].detail)


# ------------------------------------------------------- bows, crossbows
class TestToyBowsAndCrossbows(unittest.TestCase):
    def test_a_toy_at_or_under_the_small_limit_goes_to_a_sign_off(self):
        for what in ("toy crossbow", "toy bow and arrow", "toy archery set"):
            f = run(f"A {what} that lights up, projectile energy 0.07 J.")
            self.assertEqual(blocked(f), [], what)
            self.assertEqual(len(launcher_signoff(f)), 1, what)

    def test_not_called_a_toy_it_is_blocked(self):
        f = run("A crossbow trigger release, 0.07 J.")
        self.assertEqual(len(blocked(f)), 1)
        self.assertIn("allowed only as a toy", blocked(f)[0].detail)

    def test_over_the_small_limit_it_needs_the_tip_to_be_judged(self):
        f = run("A toy crossbow, projectile energy 0.5 J.")
        self.assertEqual(len(blocked(f)), 1)
        self.assertIn("the diameter of the projectile's tip in mm is needed",
                      blocked(f)[0].detail)

    def test_with_a_broad_enough_tip_it_passes_and_a_narrow_one_does_not(self):
        wide = run("A toy crossbow, projectile energy 0.5 J, tip diameter 20 mm.")
        self.assertEqual(blocked(wide), [])
        narrow = run("A toy crossbow, projectile energy 0.5 J, tip diameter 10 mm.")
        self.assertEqual(len(blocked(narrow)), 1)
        self.assertIn("6,366 J/m2, over the 2,500 J/m2 allowed for a toy",
                      blocked(narrow)[0].detail)

    def test_the_arithmetic(self):
        self.assertEqual(round(0.5 / (math.pi * 0.010 ** 2)), 1592)      # 20 mm tip
        self.assertEqual(round(0.5 / (math.pi * 0.005 ** 2)), 6366)      # 10 mm tip
        self.assertEqual((safety.TOY_PROJECTILE_MAX_J, safety.TOY_PROJECTILE_MAX_J_PER_M2),
                         (0.08, 2500.0))

    def test_gas_is_blocked_here_too(self):
        f = run("A toy crossbow driven by compressed air, 0.05 J.")
        self.assertEqual(len(blocked(f)), 1)
        self.assertIn("nothing propelled by gas", blocked(f)[0].detail)

    def test_no_energy_stated_is_blocked(self):
        self.assertEqual(len(blocked(run("A toy crossbow that lights up."))), 1)

    def test_a_boats_bow_and_a_bow_tie_are_not_bows(self):
        for text in ("A bow thruster controller for a model boat.", "A light-up bow tie.",
                     "An elbow brace with a sensor.", "A rainbow lamp."):
            f = run(text)
            self.assertEqual(blocked(f) + launcher_signoff(f), [], text)

    def test_parsing_what_a_brief_states(self):
        self.assertEqual(safety._joules("muzzle energy 0.9 j, 6 mm"), 0.9)
        self.assertEqual(safety._joules("about 2 joules"), 2.0)
        self.assertIsNone(safety._joules("three jacks and 5 jumpers"))
        self.assertEqual(safety._tip_mm("tip diameter 20 mm"), 20.0)
        self.assertEqual(safety._tip_mm("a 25 mm foam tip"), 25.0)
        self.assertIsNone(safety._tip_mm("an arrow 300 mm long"))


# ------------------------------------------------------------ tampering
class TestNoDocumentCanWidenIt(unittest.TestCase):
    PROP = "A replica weapon prop with lights and sound."
    BOW = "A toy crossbow that lights up, projectile energy 0.07 J."

    def test_both_sign_offs_are_in_the_hard_floor(self):
        self.assertIs(HARD_FLOOR["weapon_prop_requires_human_signoff"], True)
        self.assertIs(HARD_FLOOR["launcher_requires_human_signoff"], True)

    def test_a_signed_floor_that_drops_them_has_them_forced_back(self):
        eff, overridden = active_floor({**FLOOR, "weapon_prop_requires_human_signoff": False,
                                        "launcher_requires_human_signoff": False})
        for key in ("weapon_prop_requires_human_signoff", "launcher_requires_human_signoff"):
            self.assertIs(eff[key], True)
            self.assertTrue(any(key in o for o in overridden), key)

    def test_a_policy_cannot_switch_them_off(self):
        p = Policy({"weapon_prop_requires_human_signoff": False,
                    "launcher_requires_human_signoff": False})
        self.assertEqual(len(p.validate()), 2)
        self.assertEqual(len(prop_signoff(run(self.PROP, policy=p))), 1)
        self.assertEqual(len(launcher_signoff(run(self.BOW, policy=p))), 1)

    def test_a_signed_floor_cannot_remove_the_words_to_avoid_the_question(self):
        eff, _ = active_floor({**FLOOR, "forbidden_domains": []})
        f = run("A weapon with lights.", policy=Policy().against(eff))
        self.assertEqual(len(blocked(f)), 1)

    def test_no_key_in_a_policy_or_a_signed_floor_widens_any_of_it(self):
        hostile = {"prop_exempt": ["taser", "explosive", "coil gun"], "PROP_EXEMPT": ["taser"],
                   "prop_words": ["with"], "prop_defeated_by": [], "gas_words": [],
                   "airsoft_max_joules": 100.0, "AIRSOFT_MAX_JOULES": 100.0,
                   "toy_projectile_max_j": 50.0, "toy_projectile_max_j_per_m2": 1e9}
        eff, _ = active_floor({**FLOOR, **hostile})
        for policy in (Policy(dict(hostile)), Policy().against(eff),
                       Policy(dict(hostile)).against(eff)):
            for text in ("A toy taser prop with lights.", "A toy weapon that fires darts.",
                         "An airsoft controller, 0.9 J.", "A toy crossbow, 5 J.",
                         "An airsoft pistol using green gas, 0.5 J."):
                self.assertEqual(len(blocked(run(text, parts=MOTOR if "airsoft" in text
                                                 else LIGHTS, policy=policy))), 1, text)

    def test_the_lists_and_limits_are_constants_that_cannot_be_added_to_in_place(self):
        self.assertIsInstance(safety.PROP_EXEMPT, frozenset)
        for name in ("PROP_WORDS", "PROP_DEFEATED_BY", "AIRSOFT_WORDS", "BOW_WORDS", "GAS_WORDS"):
            self.assertIsInstance(getattr(safety, name), tuple, name)

    def test_a_policy_or_a_signed_floor_can_close_either_again(self):
        p = Policy({"forbid_weapon_props": True, "forbid_launchers": True})
        self.assertEqual(p.validate(), [])                       # tightening: allowed
        f = run(self.PROP, policy=p)
        self.assertIn("switched off by this machine's policy", blocked(f)[0].detail)
        f = run(self.BOW, policy=p)
        self.assertIn("switched off by this machine's policy", blocked(f)[0].detail)
        eff, _ = active_floor({**FLOOR, "forbid_launchers": True})
        self.assertEqual(len(blocked(run(self.BOW, policy=Policy().against(eff)))), 1)

    def test_once_closed_by_the_floor_a_policy_cannot_open_it(self):
        eff, _ = active_floor({**FLOOR, "forbid_weapon_props": True, "forbid_launchers": True})
        p = Policy({"forbid_weapon_props": False, "forbid_launchers": False}).against(eff)
        self.assertIs(p.effective()["forbid_weapon_props"], True)
        self.assertIs(p.effective()["forbid_launchers"], True)
        self.assertEqual(len(blocked(run(self.PROP, policy=p))), 1)
        self.assertEqual(len(blocked(run(self.BOW, policy=p))), 1)


class TestOrdinaryBriefsAreAsBefore(unittest.TestCase):
    def test_a_toy_that_is_not_a_weapon_gets_no_sign_off(self):
        f = run("A toy robot that lights up.")
        self.assertEqual(blocked(f) + prop_signoff(f) + launcher_signoff(f), [])

    def test_the_word_inside_another_word_still_does_not_match(self):
        f = run("A prop for a play about a weaponsmith's apprentice, with lights.")
        self.assertEqual(blocked(f) + prop_signoff(f), [])

    def test_the_weather_station_of_the_real_runs_is_untouched(self):
        f = run("A small desk display that shows room temperature and humidity.",
                parts=["esp32_devkit_v1", "bme280", "ssd1306_oled_096"])
        self.assertEqual(blocking(f), [])
        self.assertEqual(signoffs(f), [])


if __name__ == "__main__":
    unittest.main()
