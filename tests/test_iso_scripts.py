"""What the NemoIso build puts in an image, and what nemodoc does with it.

These read the scripts; they do not build or boot anything. Building and
booting are recorded in docs/real-hardware-results.md.

2026-10-14, for retesting on the AH531 over a phone's hotspot: the images
had NetworkManager and nothing it needs to join a wifi network, and the
models were to come over the network although they are on the Windows
disk of the same laptop already.
"""
from __future__ import annotations

import re, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "install" / "live-build" / "build-iso.sh"
NEMODOC = ROOT / "install" / "linux" / "nemodoc"


def read(p: Path) -> str:
    if not p.exists():
        raise unittest.SkipTest(f"{p.name} is not in this layout")
    return p.read_text(encoding="utf-8")


class TestWifi(unittest.TestCase):
    def setUp(self):
        self.s = read(BUILD)

    def test_what_joining_a_wifi_network_needs_is_installed(self):
        for pkg in ("wpasupplicant", "wireless-regdb", "network-manager",
                    "network-manager-gnome"):
            self.assertIn(pkg, self.s, pkg)

    def test_the_ah531s_own_cards_have_their_firmware(self):
        # Intel Centrino Wireless-N 1030 (iwlwifi) and Realtek RTL8168 (r8169),
        # as Windows lists them on that laptop.
        self.assertIn("firmware-iwlwifi", self.s)
        self.assertIn("firmware-realtek", self.s)
        self.assertIn("8086:008a", self.s)

    def test_firmware_comes_from_the_section_debian_keeps_it_in(self):
        self.assertIn("non-free-firmware", self.s)

    def test_the_windows_disk_can_be_read(self):
        self.assertIn("ntfs-3g", self.s)


class TestBootEntries(unittest.TestCase):
    def setUp(self):
        self.s = read(BUILD)

    def test_a_persistent_entry_on_both_kinds_of_boot(self):
        self.assertIn("LABEL persist", self.s)
        self.assertIn('menuentry "Nemo (live, keeping changes on the stick)"', self.s)
        self.assertEqual(len(re.findall(r"\$LIVE persistence quiet", self.s)), 2)

    def test_the_plain_entry_is_still_the_default(self):
        self.assertIn("DEFAULT nemo", self.s)
        self.assertLess(self.s.index("LABEL nemo"), self.s.index("LABEL persist"))


class TestTheCheckOnTheDesktop(unittest.TestCase):
    def test_a_menu_item_runs_the_check_in_a_window_that_stays_open(self):
        s = read(BUILD)
        self.assertIn("nemo-check.desktop", s)
        self.assertIn("--hold", s)
        self.assertIn("/opt/nemo/app/nemodoc --check-only", s)


class TestModelsFromTheWindowsDisk(unittest.TestCase):
    def setUp(self):
        self.s = read(NEMODOC)
        self.fn = self.s[self.s.index("windows_models()"):self.s.index("link_models()")]

    def test_only_ever_read_only(self):
        # Every mount of a partition; not umount, not the mountpoint test.
        mounts = re.findall(r"(?<![\w-])mount [^\n]*", self.fn)
        self.assertTrue(mounts)
        for m in mounts:
            self.assertIn("-o ro", m, m)

    def test_it_looks_where_nemowin_keeps_them(self):
        # One finder for models and the Artist's files (D194).
        self.assertIn("windows_models() { windows_folder Nemo/models '*.gguf'; }", self.fn)
        self.assertIn('ls "$dir"/$want/$files', self.fn)

    def test_a_partition_with_none_is_unmounted_again(self):
        self.assertIn('as_root umount "$dir"', self.fn)

    def test_the_models_are_linked_not_copied(self):
        link = self.s[self.s.index("link_models()"):self.s.index("t_network()")]
        self.assertIn("ln -s", link)
        self.assertNotRegex(link, r"\bcp\b")

    def test_check_only_mounts_nothing(self):
        block = self.s[self.s.index('if t_models; then ok "Language models"'):]
        self.assertIn('[ "$CHECK_ONLY" -eq 0 ] && found="$(windows_models)"', block)

    def test_the_disk_is_tried_before_the_network(self):
        block = self.s[self.s.index('if t_models; then ok "Language models"'):]
        self.assertLess(block.index("windows_models"), block.index("step models"))


class TestTheNetworkLine(unittest.TestCase):
    def test_it_is_reported_and_says_how_to_join_a_hotspot(self):
        s = read(NEMODOC)
        self.assertIn("nmcli -t -f STATE general", s)
        self.assertIn("hotspot", s)
        self.assertIn("USB tethering", s)


if __name__ == "__main__":
    unittest.main()


class TestTheEngineIsOnThePath(unittest.TestCase):
    """D176: llama-server went into /opt/nemo/bin and nowhere on the PATH,
    so loading a model on the first real run could not find it."""

    def test_llama_server_is_linked_where_nemo_and_nemodoc_are(self):
        b = read(BUILD)
        self.assertIn('ln -sf /opt/nemo/bin/llama-server "$ROOT/usr/local/bin/llama-server"', b)


class TestTheDesktopUserCanJoinANetwork(unittest.TestCase):
    """D179: "Not authorized to control networking" on the AH531. Recommends
    are off in the image, and polkitd and libpam-systemd are Recommends."""

    def test_the_permission_machinery_is_installed(self):
        b = read(BUILD)
        self.assertRegex(b, r"apt-get install[^\n]*\bpolkitd\b")
        self.assertRegex(b, r"apt-get install[^\n]*\blibpam-systemd\b")

    def test_the_live_user_is_allowed_to_manage_networks(self):
        b = read(BUILD)
        self.assertIn("/etc/polkit-1/rules.d/50-nemo-network.rules", b)
        self.assertIn('action.id.indexOf("org.freedesktop.NetworkManager.") == 0', b)
        self.assertIn('subject.isInGroup("sudo")', b)


class TestTheDesktopCanShutDown(unittest.TestCase):
    """D180: Shut Down did nothing on the AH531. XFCE asks systemd-logind,
    which asks polkit, and the image had no polkitd (the cause of D179)."""

    def test_the_live_user_may_power_off_and_restart(self):
        b = read(BUILD)
        self.assertRegex(b, r"apt-get install[^\n]*\bpolkitd\b")
        self.assertIn("/etc/polkit-1/rules.d/50-nemo-power.rules", b)
        for action in ("org.freedesktop.login1.power-off", "org.freedesktop.login1.reboot"):
            self.assertIn(f'action.id.indexOf("{action}") == 0', b)



class TestTheImageCanOpenThings(unittest.TestCase):
    """A browser (owner's request, 2026-10-19), and D190: the image had no
    xdg-open, which everything Nemo opens goes through."""

    def test_a_browser_and_xdg_open_are_installed_and_checked(self):
        b = read(BUILD)
        self.assertRegex(b, r"apt-get install[^\n]*\bfirefox-esr\b")
        self.assertRegex(b, r"apt-get install[^\n]*\bxdg-utils\b")
        self.assertIn("for tool in kicad-cli dot pio firefox-esr xdg-open freecad node rea java; do", b)

    def test_nemo_opens_things_with_xdg_open_on_linux(self):
        from nemo.gui import controller as C
        import inspect
        self.assertIn("xdg-open", inspect.getsource(C.open_path))
