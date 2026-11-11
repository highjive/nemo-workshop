"""REA, the Computer Lab's Reverse Engineer (owner, 2026-10-21: "add Rea as
employee in computer lab"), and what its tools check looks for.
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

from nemo import staff, toolkit


class TestTheReverseEngineer(unittest.TestCase):
    def test_on_the_computer_lab_team(self):
        e = staff.STAFF["computer_lab.rea"]
        self.assertEqual((e.title, e.department, e.working),
                         ("Reverse Engineer", "computer_lab", True))
        self.assertIn("REA", e.job)
        self.assertIn("Reverse Engineer", [x.title for x in staff.team("computer_lab")])

    def test_its_four_tools_are_checked(self):
        self.assertEqual([n.name for n in toolkit.NEEDS["computer_lab.rea"]],
                         ["Node.js", "REA", "Ghidra", "Java 21"])


class TestFindingTheTools(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        # Nemo's own copy is looked for first; here it is not installed.
        self._home = mock.patch.object(toolkit, "REA_HOME", self.root / "no-rea")
        self._home.start()
        self._iso = mock.patch.object(toolkit, "REA_HOME_ISO", self.root / "no-rea-iso")
        self._iso.start()

    def tearDown(self):
        self._iso.stop()
        self._home.stop()
        self.t.cleanup()

    def test_nemo_s_own_copy_comes_first(self):
        own = self.root / "no-rea" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
        own.parent.mkdir(parents=True)
        own.write_text("", encoding="utf-8")
        cache = self.root / "npm-cache" / "_npx" / "abc" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
        cache.parent.mkdir(parents=True)
        cache.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root), "APPDATA": str(self.root / "none")}), \
             mock.patch("shutil.which", return_value=None):
            self.assertEqual(toolkit.rea_cli(), own)

    def test_rea_in_npx_s_cache(self):
        script = self.root / "npm-cache" / "_npx" / "abc" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
        script.parent.mkdir(parents=True)
        script.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root), "APPDATA": str(self.root / "none")}), \
             mock.patch("shutil.which", return_value=None):
            self.assertEqual(toolkit.rea_cli(), script)

    def test_no_rea_says_so(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root), "APPDATA": str(self.root)}), \
             mock.patch("shutil.which", return_value=None):
            self.assertIsNone(toolkit.rea_cli())
            self.assertEqual(toolkit._rea(None)[0], False)

    def test_ghidra_and_java_by_their_settings(self):
        g = self.root / "ghidra_12.1.4_PUBLIC"
        (g / "support").mkdir(parents=True)
        (g / "support" / "analyzeHeadless.bat").write_text("", encoding="utf-8")
        j = self.jdk("jdk-21", '"21.0.9"')
        with mock.patch.dict(os.environ, {"GHIDRA_INSTALL_DIR": str(g), "JAVA_HOME": str(j)}):
            self.assertEqual(toolkit._ghidra(None), (True, str(g)))
            self.assertEqual(toolkit._java(None), (True, str(j)))
        empty = self.root / "empty"; empty.mkdir()
        with mock.patch.dict(os.environ, {"GHIDRA_INSTALL_DIR": str(empty), "JAVA_HOME": str(empty)}), \
             mock.patch.object(toolkit, "_tool_dir", return_value=empty), \
             mock.patch("glob.glob", return_value=[]):    # not this machine's C:\Nemo\tools
            self.assertFalse(toolkit._ghidra(None)[0])
            self.assertFalse(toolkit._java(None)[0])

    def jdk(self, name: str, version: str | None) -> Path:
        j = self.root / name
        (j / "bin").mkdir(parents=True)
        (j / "bin" / "java.exe").write_text("", encoding="utf-8")
        if version is not None:
            (j / "release").write_text(f'JAVA_VERSION={version}\nOS_NAME="Windows"\n',
                                       encoding="utf-8")
        return j

    def test_a_java_8_is_not_taken_for_java_21(self):
        # D209: JAVA_HOME was an Adoptium JRE 8 and the tools check said
        # "Java 21 ready" with its path; Ghidra 12 needs 21.
        old = self.jdk("jre-8.0.352.8-hotspot", '"1.8.0_352"')
        with mock.patch.dict(os.environ, {"JAVA_HOME": str(old)}), \
             mock.patch("glob.glob", return_value=[]):
            ok, why = toolkit._java(None)
        self.assertFalse(ok)
        self.assertIn("1.8.0_352", why)

    def test_a_java_whose_version_cannot_be_read_is_not_ready(self):
        nameless = self.jdk("jdk-unknown", None)
        with mock.patch.dict(os.environ, {"JAVA_HOME": str(nameless)}), \
             mock.patch("glob.glob", return_value=[]):
            self.assertFalse(toolkit._java(None)[0])

    def test_nemo_s_own_jdk_is_found_past_an_old_java_home(self):
        old = self.jdk("jre-8", '"1.8.0_352"')
        new = self.jdk("jdk-21.0.9+10", '"21.0.9"')
        with mock.patch.dict(os.environ, {"JAVA_HOME": str(old)}), \
             mock.patch("glob.glob", side_effect=lambda p: [str(new)] if "jdk-" in p else []):
            self.assertEqual(toolkit._java(None), (True, str(new)))

    def test_the_image_s_copies(self):
        # NemoIso (owner 2026-11-03: "add to stick all needed for rea to work"):
        # REA in /opt/nemo/tools/rea, a Ghidra with no .bat files.
        iso = self.root / "no-rea-iso" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
        iso.parent.mkdir(parents=True)
        iso.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "", "APPDATA": ""}), \
             mock.patch("shutil.which", return_value=None):
            self.assertEqual(toolkit.rea_cli(), iso)
        g = self.root / "ghidra_12.1.4_PUBLIC"
        (g / "support").mkdir(parents=True)
        (g / "support" / "analyzeHeadless").write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"GHIDRA_INSTALL_DIR": str(g)}):
            self.assertEqual(toolkit._ghidra(None), (True, str(g)))

    def test_tool_dir_tries_each_place(self):
        j = self.root / "jvm" / "java-21-openjdk-amd64"
        j.mkdir(parents=True)
        with mock.patch.dict(os.environ, {"JAVA_HOME": ""}):
            self.assertEqual(toolkit._tool_dir("JAVA_HOME", str(self.root / "none-*"),
                                               str(self.root / "jvm" / "java-21-*")), j)


class TestInTheImage(unittest.TestCase):
    def test_build_iso_installs_them(self):
        s = (Path(__file__).resolve().parent.parent / "install" / "live-build"
             / "build-iso.sh").read_text(encoding="utf-8")
        for what in ("node-$NODE_V-linux-x64.tar.xz", "sha256sum -c", "rea-agents@6.7.0",
                     "openjdk-21-jdk-headless", "ghidra_12.1.4_PUBLIC",
                     "GHIDRA_INSTALL_DIR=/opt/nemo/tools/ghidra_12.1.4_PUBLIC",
                     "JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64"):
            self.assertIn(what, s)
        self.assertIn("node rea java", s)   # in the image's tools check


if __name__ == "__main__":
    unittest.main()
