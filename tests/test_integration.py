"""Integration tests: do the tiers actually reach the thing they govern?

Every component in the authority chain was unit-tested before this file
existed, and all of those tests passed -- while the pipeline ignored the
admin policy and the signed floor entirely. Unit tests prove parts work.
These prove the parts are connected. Each test here corresponds to a defect
found in review.
"""
from __future__ import annotations

import os, re, shutil, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import master
from nemo.authority import resolve
from nemo.maintenance import (Maintenance, clone_id, diagnose, redact,
                              sign_operation)
from nemo.project import Brief
from nemo.safety import FLOOR, Policy, blocking, review


# Where PowerShell is. These tests were written in a sandbox with pwsh 7 in
# /tmp, and skipped on the very machine NemoDoc is for (D181): Windows 11
# ships Windows PowerShell 5.1 as powershell.exe, and NemoDoc runs under it.
def _windows_powershell():
    if sys.platform != "win32":
        return None
    return shutil.which("powershell") or shutil.which("powershell.exe")


def _powershell():
    for p in (shutil.which("pwsh"), "/tmp/pwsh/pwsh", _windows_powershell()):
        if p and Path(p).exists():
            return p
    return None


def _parse_with(ps, path):
    script = ("$e=$null;$t=$null;"
              "[System.Management.Automation.Language.Parser]::ParseFile"
              f"('{path}',[ref]$t,[ref]$e)|Out-Null;"
              "if($e.Count -eq 0){exit 0}else{$e|%{Write-Output $_.Message};exit 1}")
    return subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=120)
from nemo.signing import SigningError, generate_master_key, sign_floor


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = self.tmp / "admin"
        self.store.mkdir()
        self.priv, pub = generate_master_key(self.tmp / "k", self.tmp / "p")
        self.pub = pub.read_text().strip()
        self._key = mock.patch.object(master, "MASTER_PUBLIC_KEY", self.pub)
        self._key.start()

    def tearDown(self):
        self._key.stop()

    def install_signed(self, values, serial=1):
        doc = sign_floor(self.priv, values, serial)
        (self.store / "floor.signed.json").write_text(doc.to_json())


class TestAuthorityReachesThePipeline(Env):
    """Defect: pipeline constructed Policy() and ignored every tier."""

    def test_signed_floor_is_what_resolve_returns(self):
        self.install_signed({**FLOOR, "max_design_voltage_v": 24.0})
        auth = resolve(self.store)
        self.assertIn("signed floor", auth.source)
        self.assertEqual(auth.effective["max_design_voltage_v"], 24.0)

    def test_signed_floor_actually_blocks_a_design(self):
        brief = Brief(name="t", function="x", supply_ma=1000, rails=[36.0])
        # Under the compiled 48 V default this passes...
        self.assertEqual(blocking(review(brief, [], resolve(self.store).policy)), [])
        # ...and under a signed 24 V floor it must block.
        self.install_signed({**FLOOR, "max_design_voltage_v": 24.0})
        self.assertTrue(blocking(review(brief, [], resolve(self.store).policy)))

    def test_local_policy_actually_blocks_a_design(self):
        Policy({"max_design_voltage_v": 12.0}).save(self.store / "policy.yaml")
        brief = Brief(name="t", function="x", supply_ma=1000, rails=[24.0])
        self.assertTrue(blocking(review(brief, [], resolve(self.store).policy)))

    def test_cli_passes_resolved_policy_to_pipeline(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "cli.py").read_text()
        for call in [l for l in src.splitlines() if "Pipeline(" in l and "=" in l]:
            self.assertTrue("policy" in call or "resolve" in call,
                            f"pipeline built without a policy: {call.strip()}")


class TestLocalCannotExceedMaster(Env):
    """Defect: 'admin set' validated against the compiled default."""

    def test_local_loosening_past_signed_floor_is_rejected(self):
        self.install_signed({**FLOOR, "max_design_voltage_v": 24.0})
        policy = resolve(self.store).policy
        policy.values["max_design_voltage_v"] = 36.0
        self.assertTrue(policy.validate())
        self.assertEqual(policy.effective()["max_design_voltage_v"], 24.0)

    def test_local_tightening_below_signed_floor_is_accepted(self):
        self.install_signed({**FLOOR, "max_design_voltage_v": 24.0})
        policy = resolve(self.store).policy
        policy.values["max_design_voltage_v"] = 12.0
        self.assertEqual(policy.validate(), [])
        self.assertEqual(policy.effective()["max_design_voltage_v"], 12.0)


class TestTamperedSignedFloorFallsBackSafely(Env):
    def test_edited_signed_floor_is_ignored_not_trusted(self):
        self.install_signed({**FLOOR, "max_design_voltage_v": 24.0})
        f = self.store / "floor.signed.json"
        f.write_text(f.read_text().replace("24.0", "48.0"))
        auth = resolve(self.store)
        self.assertEqual(auth.source, "compiled default")


class TestPolicyFileHygiene(Env):
    """Defect: Policy.save wrote the whole bound floor into policy.yaml."""

    def test_saved_policy_contains_only_local_values(self):
        self.install_signed({**FLOOR, "max_design_voltage_v": 24.0})
        policy = resolve(self.store).policy
        policy.values["supply_headroom_fraction"] = 0.3
        policy.save(self.store / "policy.yaml")
        import yaml
        saved = yaml.safe_load((self.store / "policy.yaml").read_text())
        self.assertEqual(set(saved), {"values", "note", "version"})
        self.assertEqual(saved["values"], {"supply_headroom_fraction": 0.3})


class TestMasterCommandExists(unittest.TestCase):
    """Defect: documentation described 'nemo master apply'; it did not exist."""

    def test_master_subcommand_is_registered(self):
        from nemo import cli
        with self.assertRaises(SystemExit) as ctx:
            with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                cli.main(["master", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_every_documented_command_exists(self):
        from nemo import cli
        root = Path(__file__).resolve().parent.parent
        docs = list((root / "docs").glob("*.md"))
        docs += list((root / "readmes").glob("*.md"))
        import re
        promised = set()
        # Any 'nemo <word>' at all. An earlier pattern required a following
        # word, so 'nemo clone --iso' slipped past and a documented command
        # that did not exist went unreported.
        for d in docs:
            promised |= set(re.findall(r"(?:^|\s|`)nemo ([a-z]+)\b",
                                       d.read_text(), re.M))
        for sub in sorted(promised):
            with self.subTest(command=sub):
                with self.assertRaises(SystemExit) as ctx:
                    with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                        cli.main([sub, "--help"])
                self.assertEqual(ctx.exception.code, 0,
                                 f"docs promise 'nemo {sub}' but it is not a command")


class TestNonceOrdering(Env):
    """Defect: nonce burned before the action ran."""

    def test_failed_action_leaves_document_retryable(self):
        m = Maintenance(self.store, self.pub)
        doc = sign_operation(self.priv, "halt", clone_id(self.store))
        with mock.patch.object(m, "_halt", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                m.apply(doc)
        m.apply(doc)                        # must not say "already used"
        self.assertTrue(m.read().halted)


class TestClockGuidance(Env):
    """Defect: skew error blamed the signing machine, not the clone."""

    def test_future_dated_error_points_at_this_machine(self):
        m = Maintenance(self.store, self.pub)
        doc = sign_operation(self.priv, "halt", clone_id(self.store))
        with self.assertRaises(SigningError) as ctx:
            m.apply(doc, now=doc.issued_at - 10 * 365 * 86400)   # CMOS reset
        msg = str(ctx.exception)
        self.assertIn("THIS machine", msg)
        self.assertIn("CMOS", msg)


class TestRedaction(unittest.TestCase):
    """Defect: a key pasted into config.yaml would be emailed in the bundle."""

    def test_common_key_shapes_are_redacted(self):
        for key in ("sk-or-v1-abcdefghijklmnopqrstuvwxyz123456",
                    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
                    "AIzaSyAbcdefghijklmnopqrstuvwxyz0123456",
                    "nvapi-abcdefghijklmnopqrstuvwxyz"):
            out, n = redact(f"review_key: {key}\n")
            self.assertNotIn(key, out, key)
            self.assertGreater(n, 0)

    def test_labelled_secrets_keep_their_label(self):
        out, _ = redact("api_key = hunter2hunter2\n")
        self.assertIn("api_key", out)
        self.assertNotIn("hunter2hunter2", out)

    def test_huggingface_tokens_are_redacted(self):
        # O9: the model downloader's own provider; a gated model needs one.
        token = "hf_AbCdEfGhIjKlMnOpQrStUvWxYz0123456"
        out, n = redact(f"HF_TOKEN={token}\n")
        self.assertNotIn(token, out)
        self.assertGreater(n, 0)

    def test_bearer_tokens_in_a_pasted_curl_command_are_redacted(self):
        # O9: a raw HTTP request or curl command carries the key after
        # "Bearer ", a shape none of the label-based patterns matched.
        key = "sk-or-v1-" + "x" * 40
        out, n = redact(f'curl -H "Authorization: Bearer {key}" https://x\n')
        self.assertNotIn(key, out)
        self.assertIn("Bearer", out)          # the label survives, like the others
        self.assertGreater(n, 0)

    def test_bearer_pattern_does_not_leak_the_token_through_its_own_capture_groups(self):
        # The first version of this pattern captured the secret itself in
        # a group, and the substitution logic (group 1 + group 2 +
        # "[REDACTED]") kept whatever a capture group held -- it would
        # have reproduced the secret right next to the word REDACTED.
        key = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
        out, _ = redact(f"Bearer {key}")
        self.assertNotIn(key, out)
        self.assertEqual(out, "Bearer [REDACTED]")

    def test_bear_and_token_as_ordinary_words_are_not_touched(self):
        text = "The bear went over the mountain, token of nothing in particular here"
        out, n = redact(text)
        self.assertEqual(out, text)
        self.assertEqual(n, 0)

    def test_ordinary_config_survives(self):
        text = "engine:\n  local: http://127.0.0.1:8080/v1\n  timeout_s: 900\n"
        out, n = redact(text)
        self.assertEqual(out, text)
        self.assertEqual(n, 0)

    def test_bundle_redacts_a_pasted_key(self):
        home = Path(tempfile.mkdtemp())
        (home / "admin").mkdir()
        (home / "config.yaml").write_text("api_key: sk-or-v1-" + "x" * 40 + "\n")
        b = diagnose(home, home / "out")
        body = zipfile.ZipFile(b).read("config.yaml").decode()
        self.assertNotIn("x" * 40, body)
        self.assertIn("[REDACTED]", body)


class TestRootEncryptionCheck(unittest.TestCase):
    """Defect: any crypt device counted, so an encrypted USB stick on an
    unencrypted laptop let 'nemo lock baseline' arm."""

    def _probe(self, root_chain):
        from nemo import lockdown
        outs = {("findmnt", "-no", "SOURCE", "/"): "/dev/sda2",
                ("lsblk", "-sno", "TYPE", "/dev/sda2"): root_chain}
        with mock.patch.object(lockdown, "_run",
                               side_effect=lambda cmd, **k: outs.get(tuple(cmd), "")):
            return lockdown.root_is_encrypted()

    def test_plain_root_is_not_encrypted_even_with_crypt_usb_present(self):
        self.assertFalse(self._probe("part\ndisk"))

    def test_luks_root_is_encrypted(self):
        self.assertTrue(self._probe("crypt\npart\ndisk"))


class TestRemovableDetection(unittest.TestCase):
    """Defect: name-mangling rejected SD cards and NVMe."""

    def _probe(self, lsblk_out):
        def fake_run(cmd, **k):
            r = mock.Mock()
            r.stdout = "/dev/x\n" if cmd[0] == "findmnt" else lsblk_out
            return r
        with mock.patch.object(master.subprocess, "run", side_effect=fake_run):
            with mock.patch.object(master.sys, "platform", "linux"):
                return master._is_removable(Path("/media/stick/doc.json"))[0]

    # Real lsblk -P output. Note TRAN is EMPTY on the partition rows: an
    # earlier mock supplied three clean columns, matching the author's
    # assumption rather than the tool, and so passed while the real parser
    # misaligned every field. Mocks encode assumptions; these encode lsblk.

    def test_sd_card_in_builtin_reader(self):
        self.assertTrue(self._probe(
            'RM="0" TRAN="" NAME="mmcblk0p1"\nRM="0" TRAN="mmc" NAME="mmcblk0"\n'))

    def test_usb_stick_reporting_rm_zero(self):
        self.assertTrue(self._probe(
            'RM="0" TRAN="" NAME="sdb1"\nRM="0" TRAN="usb" NAME="sdb"\n'))

    def test_classic_removable_flag(self):
        self.assertTrue(self._probe(
            'RM="1" TRAN="" NAME="sdb1"\nRM="1" TRAN="usb" NAME="sdb"\n'))

    def test_internal_sata_disk_rejected(self):
        self.assertFalse(self._probe(
            'RM="0" TRAN="" NAME="sda2"\nRM="0" TRAN="sata" NAME="sda"\n'))

    def test_luks_root_on_internal_disk_rejected(self):
        self.assertFalse(self._probe(
            'RM="0" TRAN="" NAME="sda3_crypt"\nRM="0" TRAN="" NAME="sda3"\n'
            'RM="0" TRAN="sata" NAME="sda"\n'))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestClone(unittest.TestCase):
    def test_clone_drops_identity_and_credentials(self):
        home = Path(tempfile.mkdtemp())
        (home / "admin").mkdir()
        for f in ("admin.cred", "clone.id", "audit.log", "boot.baseline",
                  "maint.used", "policy.yaml", "floor.signed.json"):
            (home / "admin" / f).write_text("x")
        tree = Path(__file__).resolve().parent.parent
        dest = Path(tempfile.mkdtemp()) / "c"
        master.stage_clone(home, tree, dest)
        copied = {p.name for p in dest.rglob("*") if p.is_file()}
        for secret in ("admin.cred", "clone.id", "audit.log",
                       "boot.baseline", "maint.used"):
            self.assertNotIn(secret, copied, f"{secret} leaked into clone")
        self.assertIn("floor.signed.json", copied)
        self.assertIn("policy.yaml", copied)
        self.assertTrue((dest / "nemo" / "safety.py").exists())

    def test_clone_refuses_a_non_empty_destination(self):
        dest = Path(tempfile.mkdtemp()); (dest / "x").write_text("x")
        with self.assertRaises(FileExistsError):
            master.stage_clone(Path(tempfile.mkdtemp()),
                               Path(__file__).resolve().parent.parent, dest)


class TestFindTool(unittest.TestCase):
    """Defects D29/D30: KiCad was installed but reported missing."""

    def _find(self, files, on_path=None):
        from nemo import platform_probe as pp
        def fake_glob(pattern):
            import fnmatch
            return [f for f in files if fnmatch.fnmatch(f, pattern)]
        with mock.patch("glob.glob", side_effect=fake_glob), \
             mock.patch("os.path.isfile", side_effect=lambda f: f in files), \
             mock.patch("shutil.which", return_value=on_path), \
             mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\g\AppData\Local"}):
            return pp.find_tool("kicad-cli")

    def test_finds_kicad_10_which_the_old_list_missed(self):
        hit = self._find([r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"])
        self.assertIsNotNone(hit)
        self.assertIn("10.0", hit)

    def test_newest_version_wins_numerically_not_alphabetically(self):
        # String sort puts "9.0" after "10.0". Numeric sort must not.
        hit = self._find([r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
                          r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"])
        self.assertIn("10.0", hit)

    def test_per_user_install_is_found(self):
        hit = self._find([r"C:\Users\g\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"])
        self.assertIsNotNone(hit)

    def test_path_wins_when_present(self):
        self.assertEqual(self._find([], on_path="/usr/bin/kicad-cli"),
                         "/usr/bin/kicad-cli")

    def test_absent_is_none(self):
        self.assertIsNone(self._find([]))

    def test_override_is_honoured(self):
        from nemo import platform_probe as pp
        with mock.patch("os.path.isfile", return_value=True):
            self.assertEqual(pp.find_tool("kicad-cli", r"D:\Tools\kicad-cli.exe"),
                             r"D:\Tools\kicad-cli.exe")

    def test_runners_use_the_finder_not_bare_path(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "checks" /
               "runners.py").read_text()
        self.assertNotIn('_run(["kicad-cli"', src)
        self.assertNotIn('shutil.which("kicad-cli")', src)


class TestInstallPackageDoesNotSwallowFailure(unittest.TestCase):
    """D101: Install-Package discarded winget's exit code entirely
    ($null = winget install ...; return $true unconditionally whenever
    winget was merely present), so a real failure was indistinguishable
    from success at the point it happened. Two consequences, both real:
    the "see the summary below" detail for a failed install had nothing
    to show (this is what the operator's own log showed for KiCad, five
    times, with zero diagnostic content), and the $DirectUrl fallback a
    few lines below was never reached even when one existed -- true for
    the Python install, which has a real python.org fallback URL that
    was unreachable dead code whenever winget was present but failed.
    """

    root = Path(__file__).resolve().parent.parent

    def _path(self) -> Path:
        for base in (self.root, self.root / "install" / "windows"):
            if (base / "NemoDoc.ps1").exists():
                return base / "NemoDoc.ps1"
        self.skipTest("NemoDoc.ps1 not present in this layout")

    def _read(self):
        return self._path().read_text()

    def _block(self, s):
        i = s.index("function Install-Package {")
        j = s.index("function Expand-Zip {")
        return s[i:j]

    def test_the_exit_code_is_actually_checked(self):
        block = self._block(self._read())
        self.assertIn("$LASTEXITCODE -eq 0", block)
        self.assertNotIn("$null = winget install", block,
                         "winget's own output must not be discarded")

    def test_a_failure_is_logged_with_real_detail_not_just_swallowed(self):
        block = self._block(self._read())
        self.assertIn("Note \"WARN\"", block)
        self.assertIn("LASTEXITCODE", block)

    def test_the_fallback_url_path_is_still_reachable_on_failure(self):
        # The bug's second half: return $true right after the winget call
        # meant `if (-not $DirectUrl) { return $false }` and everything
        # after it could never run when winget existed. Confirm the
        # success path no longer returns before that point.
        s = self._read()
        block = self._block(s)
        i = block.index("if ($LASTEXITCODE -eq 0)")
        j = block.index("if (-not $DirectUrl)")
        self.assertLess(i, j, "the fallback check must still be reachable")

    def test_pythons_direct_url_fallback_is_wired_up(self):
        s = self._read()
        self.assertIn('Install-Package "Python.Python.3.12"', s)
        self.assertIn("python.org/ftp/python/3.12.8", s)

    def test_still_parses_as_valid_powershell(self):
        ps = _powershell()
        if ps is None:
            self.skipTest("no real PowerShell available to parse with")
        r = _parse_with(ps, self._path())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_still_has_no_powershell_7_only_syntax(self):
        # Real Windows machines ship PowerShell 5.1, not pwsh 7. Where 5.1
        # itself is here, its parser is the check: it rejects 7-only syntax.
        ps51 = _windows_powershell()
        if ps51 is not None:
            r = _parse_with(ps51, self._path())
            self.assertEqual(r.returncode, 0, "Windows PowerShell 5.1 cannot parse it: "
                             + r.stdout + r.stderr)
            return
        checker = Path("/tmp/ps51.ps1")
        if not checker.exists():
            self.skipTest("PS5.1-compat checker not available in this environment")
        pwsh = shutil.which("pwsh") or "/tmp/pwsh/pwsh"
        r = subprocess.run([pwsh, "-File", str(checker), str(self._path())],
                          capture_output=True, text=True)
        self.assertIn("no PowerShell-7-only syntax", r.stdout)


class TestModeSelectionChecksTheModelIsActuallyPresent(unittest.TestCase):
    """First real-hardware report: 4437 MB free, no AVX -- correctly picked
    talk mode -- but only gemma3-1b had actually downloaded (the model loop
    skips qwen3-4b/1.7b/coder on any machine under 7000 MB total, a
    threshold with no relationship to the free-memory brackets the mode
    picker uses). The pre-launch checks passed ("Everything checks out"),
    then the launch itself failed on a model that was never fetched, on
    exactly the kind of machine this whole project targets.
    """

    root = Path(__file__).resolve().parent.parent

    def _path(self) -> Path:
        for base in (self.root, self.root / "install" / "windows"):
            if (base / "NemoDoc.ps1").exists():
                return base / "NemoDoc.ps1"
        self.skipTest("NemoDoc.ps1 not present in this layout")

    def _read(self):
        return self._path().read_text()

    def test_mode_choice_checks_the_models_directory(self):
        s = self._read()
        # The fix must run Test-Path against $ModelDir before trusting the
        # free-memory-only choice made just above it.
        i = s.index("if (-not $Mode) {")
        j = s.index("& $NemoCmd mode $Mode")
        block = s[i:j]
        self.assertIn("Test-Path", block)
        self.assertIn("ModelDir", block)

    def test_the_mode_model_mapping_matches_the_real_config(self):
        # This table is necessarily a duplicate of nemo/config.py's DEFAULTS
        # (PowerShell has no way to import the Python config); if one is
        # edited without the other, this is what would catch it.
        import sys
        sys.path.insert(0, str(self.root))
        from nemo.config import DEFAULTS
        s = self._read()
        m = re.search(r'\$ModeModel\s*=\s*\[ordered\]@\{([^}]+)\}', s)
        self.assertIsNotNone(m, "no $ModeModel table found")
        pairs = dict(re.findall(r'(\w+)\s*=\s*"([\w.\-]+)"', m.group(1)))
        self.assertEqual(pairs.get("design"), DEFAULTS["modes"]["design"]["model"])
        self.assertEqual(pairs.get("talk"), DEFAULTS["modes"]["talk"]["model"])
        self.assertEqual(pairs.get("tiny"), DEFAULTS["modes_windows"]["tiny"]["model"])

    def test_a_missing_model_steps_down_rather_than_failing_at_launch(self):
        s = self._read()
        i = s.index("if (-not $Mode) {")
        j = s.index("& $NemoCmd mode $Mode")
        block = s[i:j]
        # It must actually change $Mode when stepping down, not just print
        # a message and proceed with the original (still-missing) choice.
        self.assertIn("$Mode = $chosen", block)
        # And it must give up cleanly, not fall through to the opaque
        # "no GGUF for ..." failure, when nothing at all is usable.
        self.assertIn("Read-Host", block)
        self.assertIn("exit 1", block)

    def test_no_downgrade_message_when_the_picked_mode_is_actually_there(self):
        # A capable machine with every model present must see no new
        # messaging at all -- this must be additive, not a behaviour change
        # for the common case.
        s = self._read()
        self.assertIn('if ($chosen -ne $Mode)', s)

    def test_still_parses_as_valid_powershell(self):
        ps = _powershell()
        if ps is None:
            self.skipTest("no real PowerShell available to parse with")
        r = _parse_with(ps, self._path())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_still_has_no_powershell_7_only_syntax(self):
        # Real Windows machines ship PowerShell 5.1, not pwsh 7. Where 5.1
        # itself is here, its parser is the check: it rejects 7-only syntax.
        ps51 = _windows_powershell()
        if ps51 is not None:
            r = _parse_with(ps51, self._path())
            self.assertEqual(r.returncode, 0, "Windows PowerShell 5.1 cannot parse it: "
                             + r.stdout + r.stderr)
            return
        checker = Path("/tmp/ps51.ps1")
        if not checker.exists():
            self.skipTest("PS5.1-compat checker not available in this environment")
        pwsh = shutil.which("pwsh") or "/tmp/pwsh/pwsh"
        r = subprocess.run([pwsh, "-File", str(checker), str(self._path())],
                          capture_output=True, text=True)
        self.assertIn("no PowerShell-7-only syntax", r.stdout)



class TestLlamaPinning(unittest.TestCase):
    """Defects D31/D32: stale asset name; ISO shipped a binary without its libs."""

    root = Path(__file__).resolve().parent.parent

    def _read(self, *names):
        for n in names:
            for base in (self.root, self.root / "install" / "linux",
                         self.root / "install" / "windows",
                         self.root / "install" / "live-build",
                         self.root / "packaging", self.root / "manual"):
                if (base / n).exists():
                    return (base / n).read_text()
        self.skipTest(f"{names} not present in this layout")

    def test_windows_uses_unified_cpu_build_not_avx_asset(self):
        s = self._read("NemoDoc.ps1")
        self.assertIn("bin-win-cpu-x64.zip", s)
        self.assertNotRegex(s, r'bin-win-\$IsaTag')

    def test_windows_download_is_hash_verified(self):
        s = self._read("NemoDoc.ps1")
        self.assertIn("Get-FileHash", s)
        self.assertRegex(s, r'LlamaSha256\s*=\s*"[0-9a-f]{64}"')

    def test_windows_does_not_depend_on_the_github_api(self):
        # 60 requests an hour per IP, unauthenticated. Shared NAT exhausts it.
        s = self._read("NemoDoc.ps1")
        self.assertNotIn("api.github.com", s)

    def test_linux_builds_are_pinned_and_static(self):
        for name in ("build-iso.sh", "build-llama.sh", "nemodoc"):
            s = self._read(name)
            self.assertIn("--branch", s, name)
            self.assertIn("BUILD_SHARED_LIBS=OFF", s, name)


class TestPackaging(unittest.TestCase):
    """Defects D35/D36: found by installing the archive, not the source."""

    root = Path(__file__).resolve().parent.parent

    def test_every_runtime_resource_lives_inside_the_package(self):
        # Anything located relative to a module file must resolve INSIDE the
        # package, or a pip install leaves it behind.
        from nemo.parts import BUNDLED
        from nemo.prompts import HERE
        pkg = (self.root / "nemo").resolve()
        for res in (BUNDLED, HERE):
            self.assertTrue(str(res.resolve()).startswith(str(pkg)),
                            f"{res} is outside the package")

    def test_bundled_library_is_not_empty(self):
        from nemo.parts import PartsLibrary
        self.assertGreater(len(PartsLibrary.load()), 0)

    def test_package_data_declares_the_library(self):
        s = (self.root / "pyproject.toml").read_text()
        self.assertIn("data/parts/*.yaml", s)

    def test_user_folder_extends_rather_than_replaces(self):
        from nemo.parts import PartsLibrary
        d = Path(tempfile.mkdtemp())
        (d / "mine.yaml").write_text("my_sensor:\n  name: X\n  category: sensor\n")
        base = len(PartsLibrary.load())
        both = PartsLibrary.load(d)
        self.assertEqual(len(both), base + 1)
        self.assertIsNotNone(both.get("rc522"))

    def test_user_entry_overrides_bundled_of_same_ref(self):
        from nemo.parts import PartsLibrary
        d = Path(tempfile.mkdtemp())
        (d / "fix.yaml").write_text(
            "rc522:\n  name: corrected\n  category: sensor\n  peak_ma: 120\n")
        self.assertEqual(PartsLibrary.load(d).get("rc522").peak_ma, 120)

    def test_clone_refuses_outside_a_distribution(self):
        site = Path(tempfile.mkdtemp())          # stands in for site-packages
        with self.assertRaises(FileNotFoundError):
            master.stage_clone(site, site, Path(tempfile.mkdtemp()) / "c")


class TestVersionSortOnRealisticPaths(unittest.TestCase):
    """D37: the D29 fix sorted on every digit in the path. The first unit
    tests passed because no fixture contained a stray number."""

    def key(self, p):
        from nemo.platform_probe import _version_key
        return _version_key(p)

    def test_x86_folder_is_not_version_86(self):
        new = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
        old = r"C:\Program Files (x86)\KiCad\6.0\bin\kicad-cli.exe"
        self.assertEqual(max([new, old], key=self.key), new)

    def test_digits_in_username_do_not_count(self):
        new = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
        usr = r"C:\Users\Someone2011\AppData\Local\Programs\KiCad\9.0\bin\kicad-cli.exe"
        self.assertEqual(max([new, usr], key=self.key), new)

    def test_point_releases_order_correctly(self):
        a = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
        b = r"C:\Program Files\KiCad\10.10\bin\kicad-cli.exe"
        self.assertEqual(max([a, b], key=self.key), b)

    def test_path_without_version_folder_sorts_lowest(self):
        self.assertEqual(self.key("/usr/bin/kicad-cli"), (0,))


class TestFreeCADOffThePath(unittest.TestCase):
    """D210: FreeCAD's installer never puts it on PATH and find_tool had no
    places to look for it, so the doctor said "freecad missing" on a machine
    with FreeCAD 0.20, 0.21 and 1.1 installed. Its folders carry the version
    in their name ("FreeCAD 1.1"), not in a folder below."""

    def test_it_is_found_where_its_installer_puts_it_newest_first(self):
        import glob as _glob
        from nemo import platform_probe as pp
        old = r"C:\Program Files\FreeCAD 0.21\bin\freecad.exe"
        older = r"C:\Program Files\FreeCAD 0.20\bin\freecad.exe"
        new = r"C:\Users\x\AppData\Local\Programs\FreeCAD 1.1\bin\freecad.exe"
        every = [old, older, new]

        def fake_glob(pattern):
            import fnmatch
            return [p for p in every if fnmatch.fnmatch(p.lower(), pattern.lower())]

        with mock.patch("shutil.which", return_value=None), \
             mock.patch("os.path.isfile", side_effect=lambda p: p in every), \
             mock.patch.object(_glob, "glob", side_effect=fake_glob), \
             mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}):
            self.assertEqual(pp.find_tool("freecad"), new)

    def test_freecad_point_releases_order_correctly(self):
        from nemo.platform_probe import _version_key
        a = r"C:\Program Files\FreeCAD 1.1\bin\freecad.exe"
        b = r"C:\Program Files\FreeCAD 0.21\bin\freecad.exe"
        self.assertEqual(max([a, b], key=_version_key), a)
        self.assertEqual(_version_key(a), (1, 1))


class TestRuleChecksNeverPassUnrun(unittest.TestCase):
    """D40/D41: against real KiCad 7, ERC reported PASS for a check that
    never ran, and a stale report could stand in for a fresh one."""

    def setUp(self):
        from nemo.checks import runners
        self.r = runners
        self.tmp = Path(tempfile.mkdtemp())
        self.sch = self.tmp / "p.kicad_sch"; self.sch.write_text("(kicad_sch)")
        self.pcb = self.tmp / "p.kicad_pcb"; self.pcb.write_text("(kicad_pcb)")

    def _patch(self, version, rc=1, err="Unknown subcommand", writes=None):
        def fake_run(cmd, **k):
            if writes is not None and "--output" in cmd:
                Path(cmd[cmd.index("--output") + 1]).write_text(writes)
            return rc, "", err
        return (mock.patch.object(self.r, "_kicad", return_value="/x/kicad-cli"),
                mock.patch.object(self.r, "kicad_version", return_value=version),
                mock.patch.object(self.r, "_run", side_effect=fake_run))

    def run_erc(self, *a, **k):
        p1, p2, p3 = self._patch(*a, **k)
        with p1, p2, p3:
            return self.r.erc(self.sch)

    def test_kicad_7_is_skipped_with_reason_not_passed(self):
        res = self.run_erc((7, 0, 11))
        self.assertEqual(res.status, "SKIP")
        self.assertIn("KiCad 8", " ".join(res.items))

    def test_no_report_is_a_failure_even_if_version_unknown(self):
        res = self.run_erc((), rc=1)
        self.assertEqual(res.status, "FAIL")
        self.assertIn("did not run", res.detail)

    def test_no_report_with_exit_zero_is_still_not_a_pass(self):
        # The exit code must not be trusted on its own.
        self.assertNotEqual(self.run_erc((9, 0), rc=0).status, "PASS")

    def test_stale_report_is_not_reused(self):
        (self.tmp / "erc-report.json").write_text(
            '{"sheets":[{"violations":[]}]}')        # an old, clean report
        self.assertNotEqual(self.run_erc((9, 0), rc=1).status, "PASS")

    def test_fresh_clean_report_passes(self):
        res = self.run_erc((9, 0), rc=0, writes='{"sheets":[{"violations":[]}]}')
        self.assertEqual(res.status, "PASS")

    def test_fresh_report_with_errors_fails(self):
        rep = '{"sheets":[{"violations":[{"severity":"error","description":"pin not connected"}]}]}'
        self.assertEqual(self.run_erc((9, 0), rc=5, writes=rep).status, "FAIL")

    def test_drc_follows_the_same_rule(self):
        p1, p2, p3 = self._patch((9, 0), rc=0)
        with p1, p2, p3:
            self.assertNotEqual(self.r.drc(self.pcb).status, "PASS")
        p1, p2, p3 = self._patch((7, 0))
        with p1, p2, p3:
            self.assertEqual(self.r.drc(self.pcb).status, "SKIP")


class TestHarnessAgainstRealWireVizFormat(unittest.TestCase):
    """D43-D45: found by running against real WireViz output."""

    HARNESS = """
connectors:
  ESP32: {pinlabels: [3V3, GND, GPIO4, GPIO18, GPIO19, GPIO23, GPIO22, GPIO26, GPIO27]}
  RC522: {pinlabels: [VCC, RST, GND, MISO, MOSI, SCK, SDA]}
  DFPLAYER: {pinlabels: [VCC, RX, TX, GND]}
cables:
  W_RFID: {wirecount: 7, gauge: 26 AWG}
  W_AUDIO: {wirecount: 3, gauge: 0.34 mm2}
connections:
  - - ESP32: [3V3, GPIO22, GND, GPIO19, GPIO23, GPIO18, GPIO4]
    - W_RFID: [1-7]
    - RC522: [VCC, RST, GND, MISO, MOSI, SCK, SDA]
  - - ESP32: [3V3, GND, GPIO27]
    - W_AUDIO: [1-3]
    - DFPLAYER: [VCC, GND, RX]
"""

    def setUp(self):
        from nemo.parts import PartsLibrary
        from nemo.pipeline import Pipeline
        self.P = Pipeline
        lib = PartsLibrary.load()
        self.parts = [lib.get(x) for x in ("esp32_devkit_v1", "rc522", "dfplayer_mini")]
        self.path = Path(tempfile.mkdtemp()) / "h.yaml"
        self.path.write_text(self.HARNESS)

    def test_gauge_notation_parses(self):
        from nemo.checks.deterministic import parse_awg
        self.assertEqual(parse_awg("26 AWG"), 26)
        self.assertEqual(parse_awg(22), 22)
        self.assertEqual(parse_awg("0.25 mm2"), 24)
        self.assertEqual(parse_awg(0.5, "mm2"), 20)
        self.assertIsNone(parse_awg("thick"))

    def test_current_is_derived_from_what_the_cable_joins(self):
        runs = {r["name"]: r for r in self.P._harness_runs(self.path, self.parts)}
        self.assertEqual(runs["W_RFID"]["current_ma"], 100)     # rc522 peak
        self.assertEqual(runs["W_AUDIO"]["current_ma"], 200)    # dfplayer peak
        self.assertFalse(runs["W_RFID"]["estimated"])

    def test_endpoints_are_pins_not_connector_names(self):
        nets = self.P._harness_nets(self.path)
        self.assertIn("RC522.MOSI", nets)
        self.assertNotIn("RC522", nets)
        self.assertNotIn("W_RFID", nets)

    def test_real_pins_verify(self):
        self.assertEqual(self.P.check_harness_pins(self.path, self.parts).status, "PASS")

    def test_nonexistent_pin_fails(self):
        self.path.write_text(self.HARNESS.replace("MOSI, SCK, SDA]\n  - -", "MOSQ, SCK, SDA]\n  - -"))
        r = self.P.check_harness_pins(self.path, self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertTrue(any("MOSQ" in i for i in r.items))

    def test_part_without_pin_list_is_unchecked_not_guessed(self):
        # The Waveshare board has no list (the C3 and the Pico have had one since D163).
        from nemo.parts import PartsLibrary
        lib = PartsLibrary.load()
        parts = [lib.get(x) for x in ("waveshare_esp32s3_lcd_128", "rc522", "dfplayer_mini")]
        r = self.P.check_harness_pins(self.path, parts)
        self.assertTrue(any("ESP32" in i and "unchecked" in i for i in r.items))

    def test_a_pin_the_board_does_not_offer_fails(self):
        self.path.write_text(self.HARNESS.replace("GND, GPIO27]\n", "GND, GPIO0]\n"))
        r = self.P.check_harness_pins(self.path, self.parts)
        self.assertEqual(r.status, "FAIL")
        self.assertTrue(any("GPIO0" in i for i in r.items))


class TestThicknessBoundary(unittest.TestCase):
    """D46: every measurement was short by the ray-start offset, so a wall
    built to exactly the minimum failed, with the message '1.20 mm is below
    the 1.2 mm minimum'. Needs trimesh and rtree; skipped without them."""

    def _shell(self, wall):
        import importlib.util
        if not (importlib.util.find_spec("trimesh") and importlib.util.find_spec("rtree")):
            self.skipTest("trimesh/rtree not installed")
        import trimesh
        a = trimesh.creation.box((60, 40, 30))
        b = trimesh.creation.box((60 - 2 * wall, 40 - 2 * wall, 30 - 2 * wall))
        b.invert()
        p = Path(tempfile.mkdtemp()) / "s.stl"
        trimesh.util.concatenate([a, b]).export(p)
        return p

    def test_wall_exactly_at_minimum_passes(self):
        from nemo.checks import thickness
        self.assertEqual(thickness(self._shell(1.2), 1.2).status, "PASS")

    def test_wall_measurably_below_minimum_fails(self):
        from nemo.checks import thickness
        self.assertEqual(thickness(self._shell(1.1), 1.2).status, "FAIL")

    def test_measurement_is_not_biased(self):
        from nemo.checks import thickness
        r = thickness(self._shell(2.0), 1.2)
        self.assertIn("2.00", r.detail)


class TestInstallCheckTestsTheInstall(unittest.TestCase):
    """D51/D52: NemoDoc tested 'import nemo' from the NemoWin folder, where
    the source folder satisfied it with nothing installed, so the 'nemo'
    command was never created. It also pointed at the download folder."""

    root = Path(__file__).resolve().parent.parent

    def _read(self, name):
        for base in (self.root, self.root / "install" / "windows",
                     self.root / "install" / "linux"):
            if (base / name).exists():
                return (base / name).read_text()
        self.skipTest(f"{name} not in this layout")

    def test_windows_check_is_isolated_from_the_working_directory(self):
        s = self._read("NemoDoc.ps1")
        fn = s[s.index("function Test-NemoInstalled"):s.index("Step \"Nemo package\"")]
        self.assertIn("-I -c", fn)
        self.assertIn("Push-Location $env:TEMP", fn)
        self.assertIn("Test-Path $NemoCmd", fn)

    def test_windows_installs_from_a_copy_not_the_download(self):
        s = self._read("NemoDoc.ps1")
        self.assertIn('$AppDir  = Join-Path $Prefix "app"', s)
        self.assertIn('-Value $AppDir', s)

    def test_windows_launch_does_not_rely_on_path_lookup(self):
        s = self._read("NemoDoc.ps1")
        self.assertIn("& '$NemoCmd' status", s)

    def test_linux_check_is_isolated_too(self):
        s = self._read("nemodoc")
        fn = s[s.index("t_nemo()"):s.index("f_nemo()")]
        self.assertIn("-I -c", fn)
        self.assertIn("cd /", fn)

    def test_python_would_have_been_fooled(self):
        # The mechanism itself, with a throwaway package no install can
        # contain. An earlier version of this test used 'nemo' and failed
        # whenever Nemo really was installed -- the environment-dependence
        # the test exists to guard against.
        import subprocess, uuid
        name = "probe_" + uuid.uuid4().hex[:12]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / name).mkdir()
            (Path(d) / name / "__init__.py").write_text("")
            plain = subprocess.run([sys.executable, "-c", f"import {name}"],
                                   cwd=d, capture_output=True)
            iso = subprocess.run([sys.executable, "-I", "-c", f"import {name}"],
                                 cwd=d, capture_output=True)
        self.assertEqual(plain.returncode, 0,
                         "without -I the working directory supplies the package")
        self.assertNotEqual(iso.returncode, 0,
                            "-I must hide the working directory")


class TestStatusOutsideAProject(unittest.TestCase):
    """D53: the first command in the launch window exited with an error."""

    def test_status_without_a_project_succeeds(self):
        from nemo import cli
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"NEMO_HOME": d}), \
             mock.patch("pathlib.Path.cwd", return_value=Path(d)), \
             mock.patch("sys.stdout"):
            self.assertEqual(cli.main(["status"]), 0)


class TestLlamaLaunch(unittest.TestCase):
    """D54/D55/D57: --mlock was removed upstream and killed the first launch;
    -t overrode llama.cpp's better default; every failure blamed the CPU."""

    src = (Path(__file__).resolve().parent.parent / "nemo" / "modes.py").read_text()

    def _launch_args(self):
        seg = self.src[self.src.index("args = ["):]
        return seg[:seg.index("]") + 1]

    def test_only_the_arguments_nemo_needs(self):
        a = self._launch_args()
        for flag in ('"-m"', '"-c"', '"--port"'):
            self.assertIn(flag, a)
        for gone in ('"--mlock"', '"-t"', '"--threads"', '"--no-mmap"'):
            self.assertNotIn(gone, a)

    def test_flags_are_checked_against_help_before_launch(self):
        self.assertIn('"--help"', self.src)
        self.assertIn("does not accept", self.src)

    def test_isa_hint_only_for_an_illegal_instruction(self):
        seg = self.src[self.src.index("runs, why = llama_binary_runs"):]
        seg = seg[:seg.index("return False, f\"llama-server will not start")]
        self.assertIn('"illegal instruction" in why', seg)


class TestToolsBesideTheInterpreter(unittest.TestCase):
    """D56: pio and wireviz live in Nemo's own environment, which is on
    nobody's PATH on the ISO, so the firmware and wiring gates always
    skipped."""

    def test_found_beside_sys_executable_without_path(self):
        from nemo import platform_probe as pp
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "python"; exe.write_text("")
            tool = Path(d) / "pio"; tool.write_text("")
            with mock.patch("shutil.which", return_value=None), \
                 mock.patch.object(sys, "executable", str(exe)):
                self.assertEqual(pp.find_tool("pio"), str(tool))

    def test_runners_do_not_use_bare_names(self):
        src = (Path(__file__).resolve().parent.parent / "nemo" / "checks" /
               "runners.py").read_text()
        for bad in ('["pio", "run"]', '_run(["wireviz"', 'shutil.which("pio")',
                    'shutil.which("wireviz")'):
            self.assertNotIn(bad, src)


class TestEveryPackageShips(unittest.TestCase):
    """D59: the hand-written package list omitted nemo.gui from pip installs."""

    def test_packages_are_discovered_not_listed(self):
        root = Path(__file__).resolve().parent.parent
        s = (root / "pyproject.toml").read_text()
        self.assertIn("[tool.setuptools.packages.find]", s)
        self.assertNotRegex(s, r"(?m)^packages\s*=\s*\[")

    def test_every_subpackage_matches_the_include_pattern(self):
        root = Path(__file__).resolve().parent.parent
        for init in (root / "nemo").rglob("__init__.py"):
            name = ".".join(init.parent.relative_to(root).parts)
            self.assertTrue(name.startswith("nemo"), name)


class TestFromTheLaptopsFirstReport(unittest.TestCase):
    """D61-D64: found in the first doctor report from the real machine."""

    def test_wireviz_gets_dot_on_its_path(self):
        # D62: dot found by Nemo but not by WireViz's own process.
        from nemo.checks import runners
        seen = {}
        def fake_run(cmd, cwd=None, timeout=600, env=None):
            seen["env"] = env
            return 1, "", "stop here"
        with tempfile.TemporaryDirectory() as d:
            y = Path(d) / "h.yaml"; y.write_text("connectors: {}\n")
            with mock.patch("nemo.platform_probe.find_tool",
                            side_effect=lambda n, *a: f"/opt/gv/bin/{n}"), \
                 mock.patch.object(runners, "_run", side_effect=fake_run):
                runners.wireviz(y)
        self.assertTrue(seen["env"]["PATH"].startswith("/opt/gv/bin" + os.pathsep))

    def test_doctor_uses_the_configured_engine(self):
        # D61: doctor searched PATH; the engine lives off PATH on Windows.
        src = (Path(__file__).resolve().parent.parent / "nemo" / "doctor.py").read_text()
        self.assertIn('get("paths.llama_server"', src)
        self.assertNotIn("runs, detail = llama_binary_runs()\n", src)

    def test_nemos_own_model_is_not_blamed_on_windows(self):
        # D63: all memory in use was attributed to Windows.
        from nemo.platform_probe import process_rss_mb
        self.assertGreater(process_rss_mb(os.getpid()), 0)
        src = (Path(__file__).resolve().parent.parent / "nemo" / "doctor.py").read_text()
        self.assertIn("others = overhead - model_mb", src)
        self.assertNotIn("is gone before Nemo starts", src)

    def test_no_avx_advice_matches_the_platform(self):
        # D64: told Windows users to compile an SSE-only build they do not need.
        src = (Path(__file__).resolve().parent.parent / "nemo" / "doctor.py").read_text()
        self.assertNotIn("You need an SSE-only", src)
        self.assertIn("chooses it on its own", src)

    def test_launch_mode_respects_a_cpu_without_avx(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("NemoDoc.ps1",):
            for base in (root, root / "install" / "windows"):
                if (base / name).exists():
                    self.assertIn('-not $HasAvx -and $Mode -eq "design"',
                                  (base / name).read_text())
