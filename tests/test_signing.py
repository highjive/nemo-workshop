"""Tests for master authority by signature, and its limits."""
from __future__ import annotations

import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.safety import FLOOR, HARD_FLOOR, Policy, active_floor
from nemo.signing import (FloorDocument, SigningError, generate_master_key,
                          public_key_fingerprint, sign_floor, verify_floor)


class TestSigning(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.priv, self.pub = generate_master_key(
            self.tmp / "master.key", self.tmp / "master.pub")
        self.pubhex = self.pub.read_text().strip()

    def test_roundtrip(self):
        doc = sign_floor(self.priv, {"max_design_voltage_v": 24.0}, 2, "test")
        self.assertEqual(verify_floor(doc, self.pubhex)["max_design_voltage_v"],
                         24.0)

    def test_survives_serialisation(self):
        doc = sign_floor(self.priv, {"a": 1, "b": [3, 2]}, 5)
        again = FloorDocument.from_json(doc.to_json())
        self.assertEqual(verify_floor(again, self.pubhex), {"a": 1, "b": [3, 2]})

    def test_altered_values_fail(self):
        doc = sign_floor(self.priv, {"max_design_voltage_v": 24.0}, 2)
        doc.values["max_design_voltage_v"] = 600.0
        with self.assertRaises(SigningError):
            verify_floor(doc, self.pubhex)

    def test_altered_note_fails(self):
        doc = sign_floor(self.priv, {"x": 1}, 2, "original")
        doc.note = "tampered"
        with self.assertRaises(SigningError):
            verify_floor(doc, self.pubhex)

    def test_a_different_key_cannot_forge(self):
        other, _ = generate_master_key(self.tmp / "o.key", self.tmp / "o.pub")
        doc = sign_floor(other, {"x": 1}, 2)
        with self.assertRaises(SigningError):
            verify_floor(doc, self.pubhex)

    def test_replay_of_an_older_document_is_refused(self):
        # The document was legitimately signed once. It must not be usable
        # to roll a deployed floor back to a more permissive revision.
        old = sign_floor(self.priv, {"max_design_voltage_v": 48.0}, 1)
        with self.assertRaises(SigningError) as ctx:
            verify_floor(old, self.pubhex, minimum_serial=7)
        self.assertIn("Replay refused", str(ctx.exception))

    def test_same_serial_is_accepted_for_reinstall(self):
        doc = sign_floor(self.priv, {"x": 1}, 7)
        self.assertEqual(verify_floor(doc, self.pubhex, minimum_serial=7),
                         {"x": 1})

    def test_private_key_is_not_derivable_from_public(self):
        self.assertEqual(len(self.pubhex), 64)
        self.assertNotIn(self.priv.read_bytes().hex(), self.pubhex)

    def test_fingerprint_is_stable_and_short(self):
        fp = public_key_fingerprint(self.pubhex)
        self.assertEqual(fp, public_key_fingerprint(self.pubhex.upper()))
        self.assertLessEqual(len(fp), 20)

    def test_malformed_document_is_rejected_clearly(self):
        with self.assertRaises(SigningError):
            FloorDocument.from_json("{}")
        with self.assertRaises(SigningError):
            FloorDocument.from_json("not json at all")


class TestHardFloorBoundsMasterAuthority(unittest.TestCase):
    """The author is not exempt. An authority with no ceiling is a single
    point of failure."""

    def test_signed_floor_cannot_remove_the_human_gate(self):
        hostile = dict(FLOOR)
        for k in ("human_signoff_before_print", "human_signoff_before_order",
                  "human_signoff_before_battery_connect",
                  "tier0_checks_mandatory",
                  "lipo_requires_protection_circuit"):
            hostile[k] = False
        eff, overridden = active_floor(hostile)
        for k in HARD_FLOOR:
            if isinstance(HARD_FLOOR[k], bool):
                self.assertTrue(eff[k], f"{k} was removed by a signed floor")
        self.assertTrue(overridden)

    def test_signed_floor_cannot_raise_the_voltage_ceiling(self):
        eff, _ = active_floor({**FLOOR, "max_design_voltage_v": 1000.0})
        self.assertEqual(eff["max_design_voltage_v"],
                         HARD_FLOOR["max_design_voltage_v"])

    def test_signed_floor_can_lower_the_voltage_ceiling(self):
        eff, _ = active_floor({**FLOOR, "max_design_voltage_v": 12.0})
        self.assertEqual(eff["max_design_voltage_v"], 12.0)

    def test_signed_floor_cannot_empty_forbidden_domains(self):
        eff, _ = active_floor({**FLOOR, "forbidden_domains": []})
        for entry in HARD_FLOOR["forbidden_domains"]:
            self.assertIn(entry, eff["forbidden_domains"])

    def test_overrides_are_reported_not_silent(self):
        _, overridden = active_floor({**FLOOR, "max_design_voltage_v": 999.0})
        self.assertTrue(any("capped" in x for x in overridden))

    def test_signed_floor_can_genuinely_loosen_below_hard(self):
        # The legitimate use: relax a non-hard parameter in the field.
        eff, _ = active_floor({**FLOOR, "supply_headroom_fraction": 0.02})
        self.assertEqual(eff["supply_headroom_fraction"], 0.02)

    def test_local_policy_still_only_tightens_against_a_signed_floor(self):
        signed, _ = active_floor({**FLOOR, "max_design_voltage_v": 24.0})
        p = Policy({"max_design_voltage_v": 36.0}).against(signed)
        self.assertTrue(p.validate())
        self.assertEqual(p.effective()["max_design_voltage_v"], 24.0)
        p2 = Policy({"max_design_voltage_v": 12.0}).against(signed)
        self.assertEqual(p2.validate(), [])
        self.assertEqual(p2.effective()["max_design_voltage_v"], 12.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestCloneHygiene(unittest.TestCase):
    def setUp(self):
        from nemo.master import clone_manifest
        self.clone_manifest = clone_manifest
        self.home = Path(tempfile.mkdtemp())
        (self.home / "admin").mkdir()
        for rel in ("admin/admin.cred", "admin/audit.log",
                    "admin/boot.baseline", "admin/floor.signed.json",
                    "admin/policy.yaml"):
            (self.home / rel).write_text("x")

    def test_credential_is_never_cloned(self):
        drop, keep = self.clone_manifest(self.home)
        names = [p.name for p in drop]
        self.assertIn("admin.cred", names)
        self.assertNotIn("admin.cred", [p.name for p in keep])

    def test_audit_log_is_not_cloned(self):
        drop, _ = self.clone_manifest(self.home)
        self.assertIn("audit.log", [p.name for p in drop])

    def test_boot_baseline_is_not_cloned(self):
        # Hardware differs; carrying it would lock every clone on first boot.
        drop, _ = self.clone_manifest(self.home)
        self.assertIn("boot.baseline", [p.name for p in drop])

    def test_signed_floor_is_cloned(self):
        _, keep = self.clone_manifest(self.home)
        self.assertIn("floor.signed.json", [p.name for p in keep])
