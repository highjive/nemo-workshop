"""Tests for maintenance mode. The properties that make it safe to have."""
from __future__ import annotations

import json, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.admin import AdminStore
from nemo.maintenance import (HALT_ALLOWED, MAX_VALIDITY_S, WILDCARD,
                              Maintenance, OperationDocument, clone_id,
                              diagnose, sign_operation)
from nemo.signing import SigningError, generate_master_key


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.priv, pub = generate_master_key(self.tmp / "k", self.tmp / "p")
        self.pub = pub.read_text().strip()
        self.home = self.tmp / "home"
        self.store = self.home / "admin"
        self.store.mkdir(parents=True)
        self.m = Maintenance(self.store, self.pub)
        self.me = clone_id(self.store)

    def op(self, action, target=None, hours=24, note=""):
        return sign_operation(self.priv, action, target or self.me, hours, note)


class TestTargetBinding(Base):
    def test_document_for_this_clone_is_accepted(self):
        self.m.apply(self.op("halt"))
        self.assertTrue(self.m.read().halted)

    def test_document_for_another_clone_is_refused(self):
        other = "00000000-0000-0000-0000-000000000000"
        with self.assertRaises(SigningError) as ctx:
            self.m.apply(self.op("halt", target=other))
        self.assertIn("different machine", str(ctx.exception))
        self.assertFalse(self.m.read().halted)

    def test_wildcard_is_explicit_and_works(self):
        self.m.apply(self.op("halt", target=WILDCARD))
        self.assertTrue(self.m.read().halted)

    def test_empty_target_is_refused_at_signing(self):
        with self.assertRaises(SigningError):
            sign_operation(self.priv, "halt", "")

    def test_clone_id_is_stable(self):
        self.assertEqual(clone_id(self.store), self.me)

    def test_separate_installs_get_separate_ids(self):
        other = self.tmp / "other"; other.mkdir()
        self.assertNotEqual(clone_id(other), self.me)


class TestExpiryAndReplay(Base):
    def test_expired_document_is_refused(self):
        doc = self.op("halt", hours=1)
        with self.assertRaises(SigningError) as ctx:
            self.m.apply(doc, now=doc.expires_at + 60)
        self.assertIn("expired", str(ctx.exception))

    def test_validity_is_capped_at_signing(self):
        doc = self.op("halt", hours=10_000)
        self.assertLessEqual(doc.expires_at - doc.issued_at, MAX_VALIDITY_S)

    def test_same_document_cannot_be_used_twice(self):
        doc = self.op("halt")
        self.m.apply(doc)
        self.m.apply(self.op("resume"))
        with self.assertRaises(SigningError) as ctx:
            self.m.apply(doc)                  # replay the old halt
        self.assertIn("already been used", str(ctx.exception))
        self.assertFalse(self.m.read().halted)

    def test_future_dated_document_is_refused(self):
        doc = self.op("halt")
        with self.assertRaises(SigningError):
            self.m.apply(doc, now=doc.issued_at - 3600)

    def test_tampered_action_is_refused(self):
        doc = self.op("resume")
        doc.action = "halt"                    # swap the action
        with self.assertRaises(SigningError):
            self.m.apply(doc)

    def test_tampered_target_is_refused(self):
        doc = self.op("halt", target="00000000-0000-0000-0000-000000000000")
        doc.target = self.me                   # retarget at this clone
        with self.assertRaises(SigningError):
            self.m.apply(doc)

    def test_foreign_key_cannot_issue_operations(self):
        forged, _ = generate_master_key(self.tmp / "f", self.tmp / "fp")
        doc = sign_operation(forged, "halt", self.me)
        with self.assertRaises(SigningError):
            self.m.apply(doc)

    def test_survives_serialisation(self):
        doc = self.op("halt")
        self.m.apply(OperationDocument.from_json(doc.to_json()))
        self.assertTrue(self.m.read().halted)


class TestHaltPreservesEverything(Base):
    def setUp(self):
        super().setUp()
        self.project = self.home / "projects" / "chest"
        self.project.mkdir(parents=True)
        (self.project / "housing.py").write_text("the user's work\n")
        self.admin = AdminStore(self.store)
        self.admin.set_password("test-admin", "testing-only-123")

    def test_halt_blocks_the_pipeline(self):
        self.m.apply(self.op("halt"))
        for cmd in ("run", "new", "check", "mode"):
            with self.assertRaises(PermissionError, msg=cmd):
                self.m.gate(cmd)

    def test_halt_leaves_diagnosis_reachable(self):
        self.m.apply(self.op("halt"))
        for cmd in sorted(HALT_ALLOWED):
            self.m.gate(cmd)

    def test_halt_deletes_nothing(self):
        before = sorted(p.name for p in self.store.iterdir())
        self.m.apply(self.op("halt"))
        after = sorted(p.name for p in self.store.iterdir())
        self.assertTrue(set(before) <= set(after))
        self.assertEqual((self.project / "housing.py").read_text(),
                         "the user's work\n")
        self.assertTrue(self.admin.cred.exists())

    def test_resume_restores_operation(self):
        self.m.apply(self.op("halt"))
        self.m.apply(self.op("resume"))
        self.m.gate("run")

    def test_halt_is_audited(self):
        self.m.apply(self.op("halt", note="fault 7"), audit=self.admin)
        events = [e["event"] for e in self.admin.audit_entries()]
        self.assertIn("maint_halt", events)
        self.assertTrue(self.admin.verify_audit()[0])

    def test_corrupt_state_fails_towards_halted(self):
        self.m.apply(self.op("halt"))
        self.m.state_path.write_text("{garbage")
        self.assertTrue(self.m.read().halted)


class TestReset(Base):
    def setUp(self):
        super().setUp()
        (self.store / "policy.yaml").write_text("values: {x: 1}\n")
        (self.store / "lock.state").write_text("{}")
        self.admin = AdminStore(self.store)
        self.admin.set_password("test-admin", "testing-only-123")
        self.admin.append_audit("something_happened", {})
        self.project = self.home / "projects" / "chest"
        self.project.mkdir(parents=True)
        (self.project / "firmware.cpp").write_text("keep me\n")

    def test_reset_clears_configuration(self):
        self.m.apply(self.op("reset"))
        self.assertFalse((self.store / "policy.yaml").exists())
        self.assertFalse((self.store / "lock.state").exists())

    def test_reset_keeps_a_copy_of_what_it_cleared(self):
        self.m.apply(self.op("reset"))
        self.assertTrue(list(self.store.glob("policy.yaml.pre-reset-*")))

    def test_reset_never_touches_user_data(self):
        self.m.apply(self.op("reset"))
        self.assertEqual((self.project / "firmware.cpp").read_text(), "keep me\n")
        self.assertTrue(self.admin.cred.exists())

    def test_reset_keeps_the_audit_log(self):
        # The evidence the diagnosis needs. Clearing it would destroy the
        # record of the very fault being investigated.
        self.m.apply(self.op("reset"), audit=self.admin)
        events = [e["event"] for e in self.admin.audit_entries(50)]
        self.assertIn("something_happened", events)
        self.assertTrue(self.admin.verify_audit()[0])

    def test_reset_lifts_a_halt(self):
        self.m.apply(self.op("halt"))
        self.m.apply(self.op("reset"))
        self.assertFalse(self.m.read().halted)


class TestDiagnose(Base):
    def setUp(self):
        super().setUp()
        self.admin = AdminStore(self.store)
        self.admin.set_password("test-admin", "testing-only-123")
        self.admin.login("test-admin", "testing-only-123")   # creates a session
        self.m.apply(self.op("halt", note="fault under investigation"))
        (self.home / "config.yaml").write_text("engine: {}\n")

    def test_bundle_is_created(self):
        b = diagnose(self.home, self.tmp / "out")
        self.assertTrue(b.exists())

    def test_bundle_never_contains_secrets(self):
        b = diagnose(self.home, self.tmp / "out")
        names = zipfile.ZipFile(b).namelist()
        for secret in ("admin.cred", "admin.session", "maint.used"):
            self.assertFalse(any(n.endswith(secret) for n in names),
                             f"{secret} leaked into the bundle")

    def test_bundle_contains_what_diagnosis_needs(self):
        names = zipfile.ZipFile(diagnose(self.home, self.tmp / "out")).namelist()
        for needed in ("report.json", "state/maint.state", "state/audit.log",
                       "config.yaml", "EXCLUDED.txt"):
            self.assertIn(needed, names)

    def test_bundle_says_what_it_left_out(self):
        z = zipfile.ZipFile(diagnose(self.home, self.tmp / "out"))
        self.assertIn(b"admin.cred", z.read("EXCLUDED.txt"))

    def test_report_identifies_the_clone(self):
        z = zipfile.ZipFile(diagnose(self.home, self.tmp / "out"))
        self.assertEqual(json.loads(z.read("report.json"))["clone_id"], self.me)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestCloneIdentity(unittest.TestCase):
    def test_clone_id_is_excluded_from_clones(self):
        from nemo.master import CLONE_EXCLUDE
        self.assertIn("admin/clone.id", CLONE_EXCLUDE)

    def test_halted_state_is_excluded_from_clones(self):
        from nemo.master import CLONE_EXCLUDE
        self.assertIn("admin/maint.state", CLONE_EXCLUDE)

    def test_a_shared_id_would_defeat_targeting(self):
        # Demonstrates WHY the exclusion matters: two installs with the same
        # ID both obey a document meant for one.
        tmp = Path(tempfile.mkdtemp())
        priv, pub = generate_master_key(tmp / "k", tmp / "p")
        pubhex = pub.read_text().strip()
        a, b = tmp / "a", tmp / "b"
        a.mkdir(); b.mkdir()
        shared = clone_id(a)
        (b / "clone.id").write_text(shared)            # the bug
        doc_for_a = sign_operation(priv, "halt", shared)
        Maintenance(b, pubhex).apply(doc_for_a)
        self.assertTrue(Maintenance(b, pubhex).read().halted,
                        "with a shared ID, B obeys a halt meant for A")


class TestRevoke(Base):
    """O6: a leaked or mis-issued document was previously usable for the
    whole of its validity window, up to seven days, with no way for the
    author to stop it early. Revoke does not reach a clone over a network
    -- nothing here does, by design -- it marks a specific other document's
    nonce used the moment the revoke itself is applied, through the exact
    same delivery mechanism (console, removable media) every other
    maintenance document already requires.
    """

    def test_a_revoked_document_is_refused_even_on_its_first_presentation(self):
        leaked = self.op("halt", note="sent to the wrong person")
        revoke = sign_operation(self.priv, "revoke", self.me, 1,
                                target_nonce=leaked.nonce)
        self.m.apply(revoke)
        with self.assertRaises(SigningError) as ctx:
            self.m.apply(leaked)
        self.assertIn("already been used", str(ctx.exception))
        self.assertFalse(self.m.read().halted)

    def test_revoking_an_already_applied_document_says_so_plainly(self):
        halt = self.op("halt")
        self.m.apply(halt)
        revoke = sign_operation(self.priv, "revoke", self.me, 1,
                                target_nonce=halt.nonce)
        msg = self.m.apply(revoke)
        self.assertIn("already used", msg)
        self.assertTrue(self.m.read().halted, "revoke does not undo an applied action")

    def test_an_unrelated_document_is_unaffected_by_a_revoke(self):
        leaked = self.op("halt")
        other = self.op("halt")
        revoke = sign_operation(self.priv, "revoke", self.me, 1,
                                target_nonce=leaked.nonce)
        self.m.apply(revoke)
        self.m.apply(other)                    # must still work
        self.assertTrue(self.m.read().halted)

    def test_revoke_with_no_target_nonce_is_refused_at_signing(self):
        with self.assertRaises(SigningError):
            sign_operation(self.priv, "revoke", self.me, 1)

    def test_a_hand_crafted_revoke_with_no_target_nonce_is_refused_at_verify(self):
        # Defense in depth: sign_operation already refuses to build this
        # document at all, so to prove verify() has its own, separate
        # check (in case a document is ever produced another way), build
        # and sign one directly rather than going through sign_operation.
        import time, secrets
        from nemo.signing import sign_bytes
        now = int(time.time())
        doc = OperationDocument(action="revoke", target=self.me,
                                nonce=secrets.token_hex(16), issued_at=now,
                                expires_at=now + 3600, target_nonce="")
        doc.signature = sign_bytes(self.priv, doc.payload())
        with self.assertRaises(SigningError) as ctx:
            self.m.apply(doc)
        self.assertIn("must name the nonce", str(ctx.exception))

    def test_target_nonce_is_part_of_the_signed_payload(self):
        # If it were not, an attacker could change which nonce gets
        # revoked without invalidating the signature.
        doc = sign_operation(self.priv, "revoke", self.me, 1, target_nonce="a" * 32)
        tampered = OperationDocument(action=doc.action, target=doc.target,
                                     nonce=doc.nonce, issued_at=doc.issued_at,
                                     expires_at=doc.expires_at, note=doc.note,
                                     target_nonce="b" * 32, signature=doc.signature)
        with self.assertRaises(SigningError):
            self.m.apply(tampered)

    def test_reset_does_not_undo_a_revoke(self):
        leaked = self.op("halt")
        revoke = sign_operation(self.priv, "revoke", self.me, 1,
                                target_nonce=leaked.nonce)
        self.m.apply(revoke)
        self.m.apply(self.op("reset"))
        with self.assertRaises(SigningError):
            self.m.apply(leaked)

    def test_old_format_documents_are_rejected_by_version_not_a_confusing_signature_error(self):
        # DOC_VERSION was bumped when target_nonce joined the signed
        # payload; an old-format document must fail with a clear version
        # message, not an opaque signature-mismatch one.
        import json
        doc = self.op("halt")
        old = json.loads(doc.to_json())
        old["version"] = 1
        del old["target_nonce"]
        with self.assertRaises(SigningError) as ctx:
            OperationDocument.from_json(json.dumps(old))
        self.assertIn("unsupported document version", str(ctx.exception))
