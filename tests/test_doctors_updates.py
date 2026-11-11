"""The Doctors' round of every department and their look for newer tools (owner,
2026-11-11: "sort with doctor in nemo so updates to all departments can be done";
he chose both, downloads only on his yes)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import clinic, toolkit, toolupdates as T
from nemo.config import Config

ROOT = Path(__file__).resolve().parent.parent


def rel(tag, pre=False, draft=False):
    return {"tag_name": tag, "prerelease": pre, "draft": draft,
            "html_url": f"https://example.invalid/{tag}"}


class TestReadingVersions(unittest.TestCase):
    def test_each_kind_of_tag_orders_by_its_numbers(self):
        self.assertTrue(T.is_newer(r"b(\d+)", "b11175", "b12282"))
        self.assertTrue(T.is_newer(r"master-(\d+)-", "master-929-3f8527a", "master-1088-32d516c"))
        self.assertTrue(T.is_newer(T.SEMVER, "v2.12.0", "v3.1.0"))
        self.assertTrue(T.is_newer(T.SEMVER, "2.4.2", "v2.5.0"))       # a 'v' or none
        self.assertFalse(T.is_newer(T.SEMVER, "4.7.2-stable", "4.7.2-stable"))
        self.assertFalse(T.is_newer(T.SEMVER, "9.0.2", "9.0"))
        # Tagged another way: said, never judged.
        self.assertIsNone(T.is_newer(r"b(\d+)", "b11175", "v0.9.0"))

    def test_a_build_numbered_tool_counts_its_prerelease_builds(self):
        # 2026-11-11: llama.cpp's "latest" was v0.9.0; its builds are pre-releases.
        pages = {"releases?per_page=40": [rel("b12282", pre=True), rel("b12277", pre=True),
                                          rel("v0.9.0")],
                 "releases/latest": rel("v0.9.0")}
        get = lambda url: next(v for k, v in pages.items() if url.endswith(k))
        self.assertEqual(T.latest("github:o/r", r"b(\d+)", get)[0::2], ("b12282", "v0.9.0"))

    def test_a_numbered_version_never_counts_a_beta(self):
        pages = {"releases?per_page=40": [rel("4.8-beta2", pre=True), rel("4.7.2-stable"),
                                          rel("4.9-draft", draft=True)]}
        get = lambda url: next(v for k, v in pages.items() if url.endswith(k))
        self.assertEqual(T.latest("github:o/r", T.SEMVER, get)[0], "4.7.2-stable")

    def test_one_feed_that_cannot_be_read_is_said_and_the_rest_still_look(self):
        def get(url):
            if "bad" in url:
                raise OSError("timed out")
            return [rel("v2.0.0")] if "per_page" in url else rel("v2.0.0")
        tools = (T.Tool("a", "Tool A", "library", "github:x/bad", T.SEMVER, lambda: "1.0.0"),
                 T.Tool("b", "Tool B", "library", "github:x/good", T.SEMVER, lambda: "1.0.0"))
        a, b = T.look(tools, get)
        self.assertIn("could not look", a.line())
        self.assertIsNone(a.newer)
        self.assertTrue(b.newer)
        self.assertEqual(b.line(), "Tool B: v2.0.0 is out; Nemo has 1.0.0")


class TestNemosOwnVersions(unittest.TestCase):
    def test_every_pinned_tool_reads_its_version_from_the_pins(self):
        for t in T.TOOLS:
            if t.key in ("godot", "rea"):          # found on the machine, not pinned
                continue
            ours = t.ours()
            self.assertIsNotNone(T.numbers(t.pattern, ours), (t.key, ours))

    def test_the_new_version_names_are_nemodocs_own(self):
        from nemo import gaming, speech
        doc = (ROOT / "NemoDoc.ps1").read_text(encoding="utf-8")
        self.assertIn(f"whisper.cpp/releases/download/{speech.WHISPER_TAG}/", doc)
        self.assertIn(f"libretro.com/stable/{gaming.RETROARCH_VERSION}/windows", doc)

    def test_the_godot_found_is_read_without_its_file_suffix(self):
        with mock.patch("nemo.gamestudio.godot",
                        return_value=Path("C:/Godot/Godot_v4.7.2-stable_win64_console.exe")):
            self.assertEqual(T._godot(), "4.7.2-stable")

    def test_every_tool_serves_a_real_department(self):
        from nemo.staff import DEPARTMENTS
        for t in T.TOOLS:
            self.assertIn(t.department, DEPARTMENTS, t.key)


class TestTheDoctorsSayIt(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load(Path("/nonexistent"))

    def test_the_kept_look_is_said_and_only_what_is_newer(self):
        looks = [T.Look("harper", "Harper", "library", "v2.12.0", "v3.1.0", True, "https://h"),
                 T.Look("ffmpeg", "FFmpeg", "film", "9.0.2", "9.0.2", False),
                 T.Look("whisper", "whisper", "library", "b5454", "v1.9.5", None)]
        found = clinic.updates(self.cfg, kept=(1794400000.0, looks))
        self.assertEqual([f.what for f in found], ["Harper: v3.1.0 is out (Nemo has v2.12.0)."])
        self.assertEqual(found[0].severity, clinic.LOOK)
        self.assertEqual(found[0].remedy, "")              # never taken by the Nurse
        self.assertIn("your yes", found[0].advice)

    def test_an_ordinary_visit_never_goes_on_the_network(self):
        with mock.patch.object(T, "_get", side_effect=AssertionError("network")):
            self.assertEqual(clinic.updates(self.cfg), [])  # never looked: nothing said

    def test_the_kept_look_round_trips(self):
        looks = [T.Look("orca", "OrcaSlicer", "printshop", "2.4.2", "v2.5.0", True, "u")]
        T.save(looks, now=5.0)
        self.assertEqual(T.last(), (5.0, looks))
        self.addCleanup(T.path().unlink)

    def test_the_round_names_each_department_once_with_what_is_missing(self):
        rows = [toolkit.Row("printshop.slicer", "OrcaSlicer", False, "not installed"),
                toolkit.Row("film.editor", "ffmpeg", True, "found"),
                toolkit.Row("library.researcher", "Wikipedia", False, "cannot be reached now"),
                toolkit.Row("computer_lab.foreman", "its job", False, "not built yet")]
        found = clinic.departments(self.cfg, rows)
        self.assertEqual(len(found), 1)
        self.assertIn("The Print Shop is missing 1 thing", found[0].what)
        self.assertIn("OrcaSlicer: not installed", found[0].evidence)
        self.assertIn("nemo staff printshop", found[0].advice)

    def test_the_round_is_one_of_the_doctors_and_looks_only(self):
        fns = [fn for _, fn in clinic.SPECIALISTS]
        self.assertIn(clinic.departments, fns)
        self.assertIn(clinic.updates, fns)
        case = clinic.examine(self.cfg, (("doctors.gp", clinic.records),
                                         ("doctors.gp", lambda c: [])))
        self.assertEqual(case.seen_by, ["doctors.gp"])     # named once

    def test_the_command_offers_the_look(self):
        from nemo import cli
        src = (ROOT / "nemo" / "cli.py").read_text(encoding="utf-8")
        self.assertRegex(src, r'choices=\[[^\]]*"updates"')
        self.assertTrue(re.search(r'args\.action == "updates"', src))
        self.assertTrue(hasattr(cli, "cmd_clinic"))


if __name__ == "__main__":
    unittest.main()
