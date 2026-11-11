"""Home (owner, 2026-10-22): the devices on the network, and the permission
he gives each. The network is stood in for; the Gatekeeper is turned on.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import backup, cast, home, review, staff

ARP = {"192.168.50.1": "aa-bb-cc-00-00-01", "192.168.50.13": "7c-2e-bd-00-00-0d", "192.168.50.40": "24-0a-c4-00-00-28"}
SSDP = {"192.168.50.1": ["Linux UPnP/1.0 router"], "192.168.50.13": ["Linux/3.8 UPnP/1.0"]}
MDNS = {"192.168.50.13": {"names": ["Family Room TV", "Chromecast-1702"], "kinds": ["Chromecast or Google speaker"]},
        "192.168.50.40": {"names": ["lamp"], "kinds": ["Nemo-built board"]},
        "192.168.50.77": {"names": ["Kitchen printer"], "kinds": ["printer"]}}


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, {**_sandbox.home_env(self.root), "NEMO_HOME_GATE": "on"})
        self._env.start()
        self._cfg_home = mock.patch("nemo.config.CONFIG_HOME", self.root / ".nemo")
        self._cfg_home.start()
        # No real name lookups for the made-up addresses here (each could wait seconds).
        self.real_host_names = home.host_names
        self._names = mock.patch.object(home, "host_names", side_effect=lambda ips, timeout=4.0: [""] * len(ips))
        self._names.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def tearDown(self):
        self._names.stop(); self._cfg_home.stop(); self._env.stop()
        self.t.cleanup()

    def look(self):
        return home.remember(home.survey(0, arp=lambda: ARP, ssdp_=lambda s: SSDP, mdns_=lambda s: MDNS))


class TestTheSurveyor(AHome):
    def test_one_device_per_address_from_three_sources(self):
        found = {d.ip: d for d in self.look()}
        self.assertEqual(sorted(found), ["192.168.50.1", "192.168.50.13", "192.168.50.40", "192.168.50.77"])
        tv = found["192.168.50.13"]
        self.assertEqual(tv.key, "mac:7c-2e-bd-00-00-0d")
        self.assertEqual(tv.label, "Family Room TV")
        self.assertEqual(tv.found_by, ["ARP", "SSDP", "mDNS"])
        self.assertIn("Chromecast or Google speaker", tv.kinds)
        self.assertEqual(found["192.168.50.77"].key, "name:Kitchen printer")     # no MAC: by its name
        self.assertTrue(all(d.permission == "see" for d in found.values()))  # nothing allowed yet

    def test_one_device_at_two_addresses_is_one_device(self):
        # The AH531, 2026-10-28: a Samsung TV listed twice, by its IPv4 address
        # (ARP, so a MAC) and its IPv6 link-local one (mDNS only, no MAC).
        arp = dict(ARP, **{"192.168.50.134": "b0-f2-f6-00-00-92"})
        mdns = dict(MDNS, **{"192.168.50.134": {"names": ['32" HD'], "kinds": ["AirPlay screen or speaker"]},
                             "fe80::b2f2:f6ff:fe00:92": {"names": ['32" HD'], "kinds": ["Spotify speaker"]}})
        found = home.survey(0, arp=lambda: arp, ssdp_=lambda s: SSDP, mdns_=lambda s: mdns)
        tvs = [d for d in found if '32" HD' in d.names]
        self.assertEqual(len(tvs), 1)
        self.assertEqual((tvs[0].ip, tvs[0].key), ("192.168.50.134", "mac:b0-f2-f6-00-00-92"))
        self.assertEqual(tvs[0].kinds, ["AirPlay screen or speaker", "Spotify speaker"])

    def test_the_old_twin_goes_and_keeps_its_permission(self):
        home.remember([home.Device('name:32" HD', "fe80::1", "", ['32" HD'])])
        home.allow('32" HD', "use")
        home.remember([home.Device("mac:b0-f2", "192.168.50.134", "b0-f2", ['32" HD'])])
        kept = home.known()
        self.assertEqual([d.key for d in kept], ["mac:b0-f2"])
        self.assertEqual(kept[0].permission, "use")

    def test_a_device_not_found_this_time_is_remembered_not_present(self):
        with mock.patch.object(home.time, "strftime", return_value="2026-10-20 10:00"):
            home.remember([home.Device("ip:10.1.1.9", "10.1.1.9")])
        with mock.patch.object(home.time, "strftime", return_value="2026-10-28 09:00"):
            self.look()
        last = home.last_survey()
        self.assertEqual(last, "2026-10-28 09:00")
        old = home.find("10.1.1.9")
        self.assertFalse(home.present(old, last))
        self.assertTrue(home.present(home.find("Family Room TV"), last))

    def test_what_kind_of_device_from_what_is_already_known(self):
        D = home.Device
        self.assertEqual(home.device_type(D("k", kinds=["Chromecast or Google speaker"]))[0],
                         "Google Cast device (TV stick or speaker)")
        self.assertEqual(home.device_type(D("k", kinds=["AirPlay screen or speaker", "Samsung-Linux/4.1"]))[0],
                         "Samsung smart TV")
        self.assertEqual(home.device_type(D("k", host="DESKTOP-4FJ2K"))[0],
                         "Windows PC (a name Windows gives itself)")
        self.assertEqual(home.device_type(D("k", host="android-3f2a"))[0], "Android phone or tablet")
        self.assertEqual(home.device_type(D("k", host="MyDesktop"), {"MyDesktop": "your new PC"}),
                         ("MyDesktop: your new PC", "its network name"))
        # The AH531's network, 2026-10-28: a made-up hardware address, nothing announced.
        kind, why = home.device_type(D("k", mac="ae-00-00-00-00-84"))
        self.assertIn("phone, tablet or laptop", kind)
        self.assertEqual(why, "its hardware address")
        self.assertFalse(home.private_mac("04-cf-4b-00-00-05"))          # a maker's address
        self.assertEqual(home.device_type(D("k", mac="04-cf-4b-00-00-05")),
                         ("", "it announces nothing and has no network name"))

    def test_the_owner_picks_a_platform_and_sees_what_nemo_can_do(self):
        self.look()
        tv = home.find("Family Room TV")
        self.assertIn("(if it is Google Cast", home.can_do(tv))          # suggested, not assumed
        d = home.set_platform("Family Room TV", "google_cast")
        self.assertEqual(home.can_do(d), "cast videos, pictures and music (Theatre, Music Room)")
        self.assertEqual(home.device_type(home.find("Family Room TV")), (home.PLATFORMS["google_cast"][0],
                                                                  "you said so"))
        self.assertIn("platform google_cast", home.changes()[-1]["to"])  # logged like a permission
        self.assertEqual(home.find("Family Room TV").permission, "see")            # Use is still separate
        with self.assertRaises(home.HomeError):
            home.set_platform("Family Room TV", "toaster")
        for key, (label, what, built) in home.PLATFORMS.items():
            self.assertEqual(built, not what.startswith(("not built", "nothing")), key)

    def test_network_names_come_from_the_records_not_the_device(self):
        names = {"192.168.50.64": ("MyDesktop.lan", [], []), "192.168.50.9": ("192.168.50.9", [], [])}

        def lookup(ip):
            if ip in names:
                return names[ip]
            raise OSError("not found")
        with mock.patch.object(home.socket, "gethostbyaddr", side_effect=lookup):
            self.assertEqual(self.real_host_names(["192.168.50.64", "192.168.50.9", "192.168.50.2"]),
                             ["MyDesktop", "", ""])

    def test_the_arp_table_is_read_without_broadcasts(self):
        text = ("Interface: 192.168.50.5 --- 0x7\n  Internet Address      Physical Address      Type\n"
                "  192.168.50.1              aa-bb-cc-00-00-01     dynamic\n"
                "  192.168.50.255            ff-ff-ff-ff-ff-ff     static\n"
                "  224.0.0.22            01-00-5e-00-00-16     static\n")
        with mock.patch.object(home.sys, "platform", "win32"), \
             mock.patch.object(home, "lan_address", return_value="192.168.50.5"), \
             mock.patch.object(home.subprocess, "run", return_value=mock.Mock(stdout=text)):
            self.assertEqual(home.arp_table(), {"192.168.50.1": "aa-bb-cc-00-00-01"})

    def test_only_the_home_networks_interface(self):
        # 2026-11-06: WSL's virtual network (172.24.80.1) was read as the home's,
        # and its 172.24.89.58 listed as a device.
        text = ("Interface: 10.114.91.64 --- 0x3\n"
                "  10.114.91.13          7c-2e-bd-00-00-0d     dynamic\n"
                "Interface: 172.24.80.1 --- 0x33\n"
                "  172.24.89.58          00-15-5d-c6-05-7b     dynamic\n")
        self.assertEqual(home.windows_arp(text, "10.114.91.64"),
                         [("10.114.91.13", "7c-2e-bd-00-00-0d")])
        self.assertEqual(len(home.windows_arp(text, "")), 2)          # not known: all
        linux = ("IP address       HW type     Flags       HW address            Mask     Device\n"
                 "192.168.50.113     0x1         0x2         7c:2e:bd:00:00:0d     *        wlan0\n"
                 "172.17.0.2       0x1         0x2         02:42:ac:11:00:02     *        docker0\n")
        self.assertEqual(home.linux_arp(linux, "wlan0"), [("192.168.50.113", "7c-2e-bd-00-00-0d")])

    def test_this_computer_is_not_one_of_the_devices(self):
        # 2026-11-06: it was listed as "Spotify Desktop Launcher", at its IPv4
        # and then its IPv6 address.
        mdns = dict(MDNS, **{"192.168.50.64": {"names": ["Spotify Desktop Launcher"], "kinds": []},
                             "fe80::1:2": {"names": ["Spotify Desktop Launcher"], "kinds": []}})
        found = home.survey(0, arp=lambda: ARP, ssdp_=lambda s: SSDP, mdns_=lambda s: mdns,
                            own=lambda: {"192.168.50.64", "fe80::1:2"})
        self.assertNotIn("Spotify Desktop Launcher", [n for d in found for n in d.names])

    def test_an_announced_id_is_not_a_name(self):
        d = home.Device("mac:b0", "192.168.50.134", "b0", ["0123456789abcdef0123456789abcdef01234567"])
        self.assertEqual(d.label, "192.168.50.134")
        d.names.append("Lounge TV")
        self.assertEqual(d.label, "Lounge TV")


class TestTheGatekeeper(AHome):
    def test_only_the_owner_s_choice_and_every_change_logged(self):
        self.look()
        self.assertEqual(home.allow("Family Room TV", "use").permission, "use")
        home.allow("192.168.50.1", "hidden")
        self.assertEqual([(c["name"], c["from"], c["to"]) for c in home.changes()],
                         [("Family Room TV", "see", "use"), ("192.168.50.1", "see", "hidden")])
        again = {d.ip: d for d in self.look()}                     # a new look keeps the choices
        self.assertEqual(again["192.168.50.13"].permission, "use")
        with self.assertRaises(home.HomeError):
            home.allow("Family Room TV", "everything")
        with self.assertRaises(home.HomeError):
            home.allow("Nobody", "use")

    def test_casting_asks_first(self):
        device = mock.Mock()
        device.cast_info.host, device.cast_info.friendly_name = "192.168.50.13", "Family Room TV"
        song = self.root / "a.mp3"; song.write_bytes(b"x")
        with self.assertRaises(cast.CastError) as e:
            cast.Session(device, song)
        self.assertIn("not in Home yet", str(e.exception))
        self.look()
        with self.assertRaises(cast.CastError) as e:
            cast.Queue(device, [song])
        self.assertIn("set to See in Home", str(e.exception))
        device.wait.assert_not_called()                            # nothing sent before the yes
        home.allow("Family Room TV", "use")
        self.assertEqual(home.may_use("192.168.50.13", "Family Room TV"), (True, ""))

    def test_the_sandbox_switch(self):
        with mock.patch.dict(os.environ, {"NEMO_HOME_GATE": "off"}):
            self.assertEqual(home.may_use("1.2.3.4", "anything"), (True, ""))

    def test_backups_keep_the_permissions(self):
        self.look(); home.allow("Family Room TV", "use")
        made = backup.make(self.cfg, self.root / "backups")     # settings from the patched home
        names = zipfile.ZipFile(made.path).namelist()
        self.assertIn("settings/home.json", names)
        self.assertIn("settings/home-permissions.jsonl", names)


class TestTheKeeperAndWriter(AHome):
    def flashed(self, name):
        p = self.cfg.path("paths.projects") / name
        p.mkdir(parents=True)
        review.record(p, "firmware", "flashed", by="Flasher", ok=True)

    def test_boards_flashed_seen_and_read(self):
        self.flashed("lamp"); self.flashed("clock")
        self.look()
        found = {b.project: b for b in home.boards(self.cfg)}
        self.assertIn("does not announce itself yet", found["clock"].note)
        self.assertIn("set it to Use", found["lamp"].note)
        home.allow("lamp", "use")
        got = {b.project: b for b in home.boards(self.cfg, fetch=lambda url: b'{"ok": true, "temp": 21.5}')}
        self.assertEqual(got["lamp"].status, {"ok": True, "temp": 21.5})
        self.assertIn("http://192.168.50.40/status", got["lamp"].note)

    def test_the_list_leaves_hidden_devices_out(self):
        self.look(); home.allow("192.168.50.1", "hidden"); home.allow("Family Room TV", "use")
        text = home.write_list(self.cfg).read_text(encoding="utf-8")
        den = next(l for l in text.splitlines() if l.startswith("| Family Room TV |"))
        self.assertIn("Chromecast or Google speaker", den)
        self.assertTrue(den.endswith("| 192.168.50.13 | use it |"), den)
        self.assertNotIn("192.168.50.1 ", text)

    def test_the_team(self):
        self.assertEqual([e.title for e in staff.team("home")],
                         ["Surveyor", "Gatekeeper", "Device Keeper", "Writer"])


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_look_and_allow(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        app = A.NemoApp(); app.update()
        try:
            app.cfg = self.cfg
            w = A.HomeRoom(app); app.update()
            real = home.survey
            with mock.patch.object(home, "survey", side_effect=lambda: real(
                    0, arp=lambda: ARP, ssdp_=lambda s: SSDP, mdns_=lambda s: MDNS)):
                w.look()
                for _ in range(40):
                    app.update(); app.after(100)
                    if w._job is None:
                        break
            self.assertIn("4 device(s)", w.note.cget("text"))
            w.tree.selection_set("mac:7c-2e-bd-00-00-0d")
            w.set("use")
            self.assertEqual(w.tree.item("mac:7c-2e-bd-00-00-0d", "values")[0], "use")
            w.platform.set(home.PLATFORMS["google_cast"][0])
            w.set_platform()                                           # the platform, picked in the window
            self.assertEqual(w.tree.item("mac:7c-2e-bd-00-00-0d", "values")[4],
                             "cast videos, pictures and music (Theatre, Music Room)")
            w.tree.selection_set("mac:aa-bb-cc-00-00-01")
            w.set("hidden")
            self.assertFalse(w.tree.exists("mac:aa-bb-cc-00-00-01"))
            w.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
