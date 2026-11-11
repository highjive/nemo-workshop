"""The prompt cache kept on disk (nemo/slotcache.py, modes.start, router).

Measured on the AH531 (qwen3-1.7b, 227-token prompt, after a restart):
78.3 s read cold, 9.5 s with the saved cache restored first."""

import json
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import modes, slotcache


class FakeServer:
    """Enough of llama-server: /v1/chat/completions and /slots/0?action=...
    It writes a file on save, as the real one does, into `folder`."""

    def __init__(self, folder: Path, fail_restore=False):
        self.calls, self.folder, self.fail_restore = [], folder, fail_restore
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.calls.append((self.path, body))
                if "action=save" in self.path:
                    (outer.folder / body["filename"]).write_bytes(b"kv")
                if "action=restore" in self.path and outer.fail_restore:
                    self.send_response(400); self.end_headers(); return
                out = json.dumps({"choices": [{"message": {"content": "x"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def paths(self):
        return [p for p, _ in self.calls]

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


class TestPrepare(unittest.TestCase):
    def setUp(self):
        slotcache._warm.clear()
        self.folder = Path(tempfile.mkdtemp())
        self.srv = FakeServer(self.folder)
        self.addCleanup(self.srv.close)
        self.payload = {"model": "m", "messages": [], "max_tokens": 300,
                        "chat_template_kwargs": {"enable_thinking": False},
                        "response_format": {"type": "json_schema"}}

    def prepare(self, pid=1, system="You choose pins."):
        return slotcache.prepare(self.srv.base, pid, self.folder, system,
                                 self.payload, 30)

    def test_first_time_the_system_prompt_alone_is_read_then_saved(self):
        self.assertEqual(self.prepare(), "saved")
        (p1, prime), (p2, save) = self.srv.calls
        self.assertEqual(p1, "/v1/chat/completions")
        self.assertEqual(prime["messages"][0], {"role": "system", "content": "You choose pins."})
        self.assertEqual(prime["messages"][1]["content"], "")
        self.assertEqual(prime["max_tokens"], 1)
        # The template options are kept (they shape the prompt); the
        # schema is not (a one-token reply cannot satisfy it).
        self.assertEqual(prime["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("response_format", prime)
        self.assertEqual(p2, "/slots/0?action=save")
        self.assertTrue((self.folder / save["filename"]).is_file())

    def test_the_same_prompt_again_on_the_same_server_asks_nothing(self):
        self.prepare()
        n = len(self.srv.calls)
        self.assertEqual(self.prepare(), "warm")
        self.assertEqual(len(self.srv.calls), n)

    def test_after_a_restart_the_file_is_restored_not_read_again(self):
        self.prepare(pid=1)
        self.srv.calls.clear()
        self.assertEqual(self.prepare(pid=2), "restored")
        self.assertEqual(self.srv.paths(), ["/slots/0?action=restore"])

    def test_a_different_system_prompt_gets_its_own_file(self):
        self.prepare(system="one")
        self.assertEqual(self.prepare(system="two"), "saved")
        self.assertEqual(len(list(self.folder.glob("*.bin"))), 2)

    def test_a_file_the_server_refuses_is_dropped_and_made_again(self):
        self.prepare(pid=1)
        self.srv.fail_restore = True
        self.srv.calls.clear()
        self.assertEqual(self.prepare(pid=2), "saved")
        self.assertEqual(self.srv.paths(), ["/slots/0?action=restore",
                                            "/v1/chat/completions", "/slots/0?action=save"])

    def test_no_server_is_quiet(self):
        out = slotcache.prepare("http://127.0.0.1:9/v1", 1, self.folder, "s", {}, 2)
        self.assertTrue(out.startswith("off:"), out)

    def test_a_folder_in_ram_is_not_used(self):
        with mock.patch.object(slotcache, "in_ram", return_value=True):
            self.assertTrue(self.prepare().startswith("off:"))
        self.assertEqual(self.srv.calls, [])


class TestOnALiveStick(TestPrepare):
    """The folder is staging in RAM; the stick keeps the files (nemo-sync
    moves them there and never back)."""

    def setUp(self):
        super().setUp()
        self.stick = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.stick, True)

    def prepare(self, pid=1, system="You choose pins."):
        return slotcache.prepare(self.srv.base, pid, self.folder, system,
                                 self.payload, 30, stick=self.stick)

    def test_a_file_on_the_stick_is_borrowed_restored_and_dropped(self):
        name = slotcache.key("You choose pins.") + ".bin"
        (self.stick / name).write_bytes(b"kv")
        restored = []
        orig = slotcache._post

        def watch(url, body, timeout):
            if "action=restore" in url:
                restored.append((self.folder / body["filename"]).is_file())
            return orig(url, body, timeout)
        with mock.patch.object(slotcache, "_post", side_effect=watch):
            self.assertEqual(self.prepare(), "restored")
        self.assertEqual(restored, [True])                    # there for the server
        self.assertFalse((self.folder / name).exists())       # gone from RAM after
        self.assertTrue((self.stick / name).exists())         # the stick keeps it

    def test_a_new_prompt_is_saved_to_staging_and_left_for_nemo_sync(self):
        self.assertEqual(self.prepare(), "saved")
        self.assertEqual(len(list(self.folder.glob("*.bin"))), 1)

    def test_a_folder_in_ram_is_not_used(self):
        # Inherited name, opposite answer: on a stick the RAM folder only
        # stages, so it is used.
        with mock.patch.object(slotcache, "in_ram", return_value=True):
            self.assertEqual(self.prepare(), "saved")

    def test_nothing_more_is_saved_while_staging_is_full(self):
        (self.folder / "waiting.bin").write_bytes(b"x" * 2**20)
        with mock.patch.object(slotcache, "STAGING_MB", 1):
            note = self.prepare()
        self.assertTrue(note.startswith("read (not saved"), note)
        self.assertNotIn("/slots/0?action=save", self.srv.paths())
        self.assertTrue((self.folder / "waiting.bin").exists())   # not pruned here

    def test_staging_is_not_pruned_by_nemo(self):
        old = self.folder / "old.bin"; old.write_bytes(b"x" * 2**20)
        with mock.patch.object(slotcache, "MAX_MB", 0):
            self.prepare()
        self.assertTrue(old.exists())


class TestPrune(unittest.TestCase):
    def test_oldest_go_first(self):
        import os
        d = Path(tempfile.mkdtemp())
        for i in range(4):
            f = d / f"{i}.bin"; f.write_bytes(b"x" * 2**20)
            os.utime(f, (i, i))
        slotcache.prune(d, max_mb=2)
        self.assertEqual(sorted(p.name for p in d.glob("*.bin")), ["2.bin", "3.bin"])


class TestInRam(unittest.TestCase):
    LIVE = ("tmpfs /run/live/overlay tmpfs rw 0 0\n"
            "overlay / overlay rw,lowerdir=/run/live/rootfs/fs,upperdir=/run/live/overlay/rw,workdir=/run/live/overlay/work 0 0\n")
    PERSIST = ("/dev/sdb3 /run/live/persistence/sdb3 ext4 rw 0 0\n"
               "overlay / overlay rw,lowerdir=/run/live/rootfs/fs,upperdir=/run/live/persistence/sdb3/rw,workdir=/x 0 0\n")

    def test_a_live_system_without_persistence_is_ram(self):
        self.assertTrue(slotcache.in_ram(Path("/home/user/.nemo/slots"), self.LIVE))

    def test_a_live_system_with_persistence_is_not(self):
        self.assertFalse(slotcache.in_ram(Path("/home/user/.nemo/slots"), self.PERSIST))

    def test_tmpfs_and_a_plain_disk(self):
        m = "/dev/sda1 / ext4 rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n"
        self.assertTrue(slotcache.in_ram(Path("/tmp/x"), m))
        self.assertFalse(slotcache.in_ram(Path("/home/x"), m))


class TestModeStart(unittest.TestCase):
    """modes.start runs one slot and names the cache folder to the server."""

    def start(self, prompt_cache=True, ram=False, stick=False):
        from nemo.config import Config
        cfg = Config.load(Path("/nonexistent"))
        cfg.data["modes_windows"]["talk"] = cfg.data["modes"]["talk"] = \
            {"model": "m", "ram_mb": 1, "ctx": 2048}
        cfg.data["engine"]["prompt_cache"] = prompt_cache
        state = Path(tempfile.mkdtemp()) / "mode.pid"
        popen = mock.Mock(return_value=mock.Mock(pid=4242, poll=lambda: None))
        with mock.patch.object(modes, "STATE", state), \
             mock.patch.object(modes, "mem_available_mb", return_value=8000), \
             mock.patch.object(modes, "engine_path", return_value="llama-server"), \
             mock.patch.object(modes, "llama_binary_runs", return_value=(True, "")), \
             mock.patch.object(modes, "model_path", return_value=Path("qwen3-1.7b.gguf")), \
             mock.patch.object(modes, "stop"), \
             mock.patch.object(slotcache, "in_ram", return_value=ram), \
             mock.patch("nemo.storage.has_stick", return_value=stick), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="", stderr="")), \
             mock.patch("subprocess.Popen", popen), \
             mock.patch.object(modes, "_wait_ready", return_value=True):
            ok, msg = modes.start(cfg, "talk")
        self.assertTrue(ok, msg)
        return popen.call_args[0][0], state.parent

    def test_on_a_live_stick_the_folder_stages_and_the_stick_keeps(self):
        cmd, home = self.start(ram=True, stick=True)
        folder = Path(cmd[cmd.index("--slot-save-path") + 1])
        pid, recorded, stick = slotcache.read_state(home)
        self.assertEqual((pid, recorded), (4242, folder))
        self.assertEqual(stick, slotcache.STICK_SLOTS / folder.name)

    def test_one_slot(self):
        cmd, _ = self.start()
        self.assertEqual(cmd[cmd.index("-np") + 1], "1")

    def test_the_ram_prompt_cache_is_capped(self):
        # llama-server's own default is 8192 MB, which nothing counted.
        # Measured on the AH531: 18 MB more per new system prompt, and with
        # a 40 MB cap private memory stopped growing after two.
        cmd, _ = self.start()
        self.assertEqual(cmd[cmd.index("--cache-ram") + 1], "256")

    def test_the_cache_folder_is_named_and_recorded(self):
        cmd, home = self.start()
        folder = Path(cmd[cmd.index("--slot-save-path") + 1])
        self.assertEqual(folder.parent, home / "slots")
        self.assertIn("qwen3-1.7b", folder.name); self.assertTrue(folder.name.endswith("-c2048"))
        self.assertTrue(folder.is_dir())
        self.assertEqual(slotcache.read_state(home), (4242, folder, None))

    def test_off_in_config_or_in_ram_names_no_folder(self):
        for kw in ({"prompt_cache": False}, {"ram": True}):
            cmd, home = self.start(**kw)
            self.assertNotIn("--slot-save-path", cmd, kw)
            self.assertIsNone(slotcache.read_state(home), kw)

    def test_stop_forgets_the_folder(self):
        home = Path(tempfile.mkdtemp())
        slotcache.write_state(home, 1, home / "f")
        with mock.patch.object(modes, "STATE", home / "mode.pid"):
            modes.stop()
        self.assertIsNone(slotcache.read_state(home))


class TestRouterUsesIt(unittest.TestCase):
    def router(self):
        from nemo.config import Config
        from nemo.router import Router
        return Router(Config.load(Path("/nonexistent")))

    def test_a_server_nemo_did_not_start_is_left_alone(self):
        home = Path(tempfile.mkdtemp())
        slotcache.write_state(home, 111, home / "f")
        with mock.patch.object(modes, "STATE", home / "mode.pid"), \
             mock.patch.object(modes, "current",
                               return_value=modes.ModeStatus("talk", 222, "m")), \
             mock.patch("nemo.modes.pid_alive", return_value=True), \
             mock.patch.object(slotcache, "prepare") as prep:
            note = self.router()._warm_cache([{"role": "system", "content": "s"}], {})
        self.assertTrue(note.startswith("off:")); prep.assert_not_called()

    def test_it_is_asked_before_the_request_with_the_system_prompt(self):
        home = Path(tempfile.mkdtemp())
        slotcache.write_state(home, 222, home / "f")
        r = self.router()
        with mock.patch.object(modes, "STATE", home / "mode.pid"), \
             mock.patch.object(modes, "current",
                               return_value=modes.ModeStatus("talk", 222, "m")), \
             mock.patch("nemo.modes.pid_alive", return_value=True), \
             mock.patch.object(slotcache, "prepare", return_value="restored") as prep, \
             mock.patch("nemo.router._post",
                        return_value={"choices": [{"message": {"content": "ok"}}]}):
            reply = r._call_local([{"role": "system", "content": "SYS"},
                                   {"role": "user", "content": "u"}], 0.2, 10)
        self.assertEqual(reply.text, "ok")
        self.assertEqual(prep.call_args[0][1:4], (222, home / "f", "SYS"))
        self.assertIsNone(prep.call_args.kwargs["stick"])
        self.assertEqual(r.cache_note, "restored")

    def test_off_in_config(self):
        r = self.router(); r.cfg.data["engine"]["prompt_cache"] = False
        with mock.patch.object(slotcache, "prepare") as prep:
            self.assertTrue(r._warm_cache([{"role": "system", "content": "s"}], {}).startswith("off:"))
        prep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
