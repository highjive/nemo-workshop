"""Tests for the safety floor and the admin layer.

The property under test throughout: a policy may tighten, never loosen.
"""
from __future__ import annotations

import sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.admin import AdminStore
from nemo.parts import Part, PartsLibrary
from nemo.project import Brief
from nemo.safety import FLOOR, Policy, blocking, review, signoffs


class TestFloorCannotBeLoosened(unittest.TestCase):
    def test_protection_cannot_be_switched_off(self):
        p = Policy({"lipo_requires_protection_circuit": False})
        self.assertTrue(p.validate())
        self.assertTrue(p.effective()["lipo_requires_protection_circuit"])

    def test_human_signoff_cannot_be_removed(self):
        for key in ("human_signoff_before_print",
                    "human_signoff_before_order",
                    "human_signoff_before_battery_connect"):
            p = Policy({key: False})
            self.assertTrue(p.validate(), key)
            self.assertTrue(p.effective()[key], key)

    def test_voltage_ceiling_cannot_be_raised(self):
        p = Policy({"max_design_voltage_v": 400.0})
        self.assertTrue(p.validate())
        self.assertEqual(p.effective()["max_design_voltage_v"],
                         FLOOR["max_design_voltage_v"])

    def test_voltage_ceiling_can_be_lowered(self):
        p = Policy({"max_design_voltage_v": 12.0})
        self.assertEqual(p.validate(), [])
        self.assertEqual(p.effective()["max_design_voltage_v"], 12.0)

    def test_headroom_can_be_increased_not_decreased(self):
        self.assertEqual(Policy({"supply_headroom_fraction": 0.30}).validate(), [])
        self.assertEqual(Policy({"supply_headroom_fraction": 0.30})
                         .effective()["supply_headroom_fraction"], 0.30)
        loose = Policy({"supply_headroom_fraction": 0.01})
        self.assertTrue(loose.validate())
        self.assertEqual(loose.effective()["supply_headroom_fraction"],
                         FLOOR["supply_headroom_fraction"])

    def test_forbidden_domains_can_grow_not_shrink(self):
        p = Policy({"forbidden_domains": ["weapons"]})
        self.assertTrue(p.validate())            # removed the rest
        self.assertTrue(set(FLOOR["forbidden_domains"])
                        <= set(p.effective()["forbidden_domains"]))
        p2 = Policy({"forbidden_domains": FLOOR["forbidden_domains"] + ["drones"]})
        self.assertEqual(p2.validate(), [])
        self.assertIn("drones", p2.effective()["forbidden_domains"])

    def test_corrupt_policy_still_fails_safe(self):
        # effective() must hold the line even if validate() was never called
        evil = Policy({k: False for k in FLOOR if isinstance(FLOOR[k], bool)})
        eff = evil.effective()
        for k, v in FLOOR.items():
            if isinstance(v, bool) and v:
                self.assertTrue(eff[k], f"{k} was switched off")

    def test_unknown_keys_pass_through(self):
        p = Policy({"my_own_extra_rule": True})
        self.assertEqual(p.validate(), [])
        self.assertTrue(p.effective()["my_own_extra_rule"])


def mk(ref, **kw):
    base = dict(name=ref, category="misc"); base.update(kw)
    return Part(ref=ref, **base)


class TestReview(unittest.TestCase):
    def setUp(self):
        self.lib = PartsLibrary.load()
        self.brief = Brief(name="t", function="a card player",
                           supply_ma=1000, rails=[5.0, 3.3])

    def test_clean_design_passes(self):
        parts = [self.lib.require("esp32_devkit_v1"),
                 self.lib.require("rc522")]
        self.assertEqual(blocking(review(self.brief, parts)), [])

    def test_over_supply_blocks(self):
        parts = [mk("hog", peak_ma=1500)]
        self.assertTrue(blocking(review(self.brief, parts)))

    def test_high_voltage_blocks(self):
        b = Brief(name="t", function="x", supply_ma=1000, rails=[230.0])
        f = review(b, [])
        self.assertTrue(blocking(f))
        self.assertTrue(any("qualified person" in x.detail for x in f))

    def test_lipo_without_protection_blocks(self):
        parts = [self.lib.require("eemb_lipo_500")]
        f = review(self.brief, parts)
        self.assertTrue(any(x.rule == "lipo_requires_protection_circuit"
                            for x in blocking(f)))

    def test_lipo_with_protection_allowed_but_needs_signoff(self):
        parts = [self.lib.require("eemb_lipo_500"),
                 self.lib.require("tp4056_protected")]
        f = review(self.brief, parts)
        self.assertEqual(blocking(f), [])
        self.assertTrue(signoffs(f))     # swell clearance still needs a human

    def test_forbidden_domain_blocks(self):
        b = Brief(name="x", function="a projectile launcher for the garden",
                  supply_ma=1000, rails=[5.0])
        self.assertTrue(blocking(review(b, [])))

    def test_tightened_policy_blocks_what_floor_allows(self):
        parts = [mk("modest", peak_ma=600)]
        self.assertEqual(blocking(review(self.brief, parts)), [])
        strict = Policy({"supply_headroom_fraction": 0.50})
        self.assertTrue(blocking(review(self.brief, parts, strict)))


class TestAdmin(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.s = AdminStore(self.tmp)
        self.s.set_password("test-admin", "correct horse battery")

    def test_correct_login(self):
        self.assertTrue(self.s.login("test-admin", "correct horse battery").ok)
        self.assertTrue(self.s.signed_in())

    def test_wrong_password_fails(self):
        self.assertFalse(self.s.login("test-admin", "nope").ok)
        self.assertFalse(self.s.signed_in())

    def test_wrong_username_fails(self):
        self.assertFalse(self.s.login("someone", "correct horse battery").ok)

    def test_password_is_not_stored_in_clear(self):
        blob = self.s.cred.read_text()
        self.assertNotIn("correct horse battery", blob)
        self.assertIn("salt", blob)

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            self.s.set_password("test-admin", "short")

    def test_backoff_escalates(self):
        for _ in range(3):
            self.s.login("test-admin", "wrong")
        self.assertGreater(self.s.wait_remaining(), 0)

    def test_failures_do_not_destroy_anything(self):
        # The explicit anti-requirement: repeated failure must leave the
        # credential, the policy and the audit log entirely intact.
        (self.tmp / "policy.yaml").write_text("values: {}\n")
        for _ in range(12):
            self.s.login("test-admin", "wrong")
        self.assertTrue(self.s.cred.exists())
        self.assertTrue((self.tmp / "policy.yaml").exists())
        self.assertTrue(self.s.audit.exists())

    def test_successful_login_clears_backoff(self):
        self.s.login("test-admin", "wrong")
        self.s.login("test-admin", "wrong")
        self.s._write_state({"failures": 2, "last_failure": 0})   # age it out
        self.assertTrue(self.s.login("test-admin", "correct horse battery").ok)
        self.assertEqual(self.s.wait_remaining(), 0)

    def test_audit_chain_intact(self):
        self.s.login("test-admin", "wrong")
        self.s.login("test-admin", "correct horse battery")
        ok, msg = self.s.verify_audit()
        self.assertTrue(ok, msg)

    def test_audit_tampering_is_detected(self):
        for _ in range(3):
            self.s.login("test-admin", "wrong")
        lines = self.s.audit.read_text().splitlines()
        del lines[2]                       # remove one failed-login record
        self.s.audit.write_text("\n".join(lines) + "\n")
        ok, msg = self.s.verify_audit()
        self.assertFalse(ok)
        self.assertIn("removed or edited", msg)

    def test_session_expires(self):
        self.s.login("test-admin", "correct horse battery")
        import json
        d = json.loads(self.s.session.read_text())
        d["expires"] = int(time.time()) - 1
        self.s.session.write_text(json.dumps(d))
        self.assertFalse(self.s.signed_in())

    def test_require_session_raises_when_out(self):
        with self.assertRaises(PermissionError):
            self.s.require_session()


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestRegressions(unittest.TestCase):
    """Bugs found in review. Each of these shipped and each was wrong."""

    def setUp(self):
        self.brief = lambda t: Brief(name="t", function=t, supply_ma=1000,
                                     rails=[5.0])

    def test_ordinary_electronics_words_do_not_block(self):
        # Substring matching on words over four characters blocked these,
        # because "transmission" and "equipment" appear in the floor's
        # multi-word domain phrases.
        for text in ("a sensor logging data transmission rates over BLE",
                     "a bench test equipment controller",
                     "a transmission line impedance calculator",
                     "life logging equipment for hillwalking"):
            self.assertEqual(blocking(review(self.brief(text), [])), [],
                             f"wrongly blocked: {text}")

    def test_genuinely_forbidden_briefs_still_block(self):
        for text in ("a projectile launcher for the garden",
                     "a coil gun controller",
                     "a taser trigger board",
                     "an infusion pump driver",
                     "a flight controller for a fixed-wing aircraft"):
            self.assertTrue(blocking(review(self.brief(text), [])),
                            f"failed to block: {text}")

    def test_plural_forms_are_caught(self):
        self.assertTrue(blocking(review(self.brief("two coil guns"), [])))

    def test_substring_inside_a_word_does_not_match(self):
        # "weapon" must not fire on a word that merely contains it.
        self.assertEqual(
            blocking(review(self.brief("a weaponry museum audio guide"), [])),
            [], "matched inside a longer word")
