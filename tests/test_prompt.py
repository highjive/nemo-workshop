"""The redesign's first part (owner's request, 2026-10-17): Nemo opens at
boot in a prompt window (an orb, a box to type in), the Story button lists
the stories created, and created work is kept on the USB stick."""
from __future__ import annotations

import os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import storage
from nemo.gui import prompt_logic as L

ROOT = Path(__file__).resolve().parent.parent
SYNC = ROOT / "install" / "linux" / "nemo-sync"
BUILD = ROOT / "install" / "live-build" / "build-iso.sh"
NEMODOC = ROOT / "install" / "linux" / "nemodoc"


def read(p: Path) -> str:
    if not p.exists():
        raise unittest.SkipTest(f"{p.name} is not in this layout")
    return p.read_text(encoding="utf-8")


class TestWhatARequestIs(unittest.TestCase):
    def test_stories(self):
        for r in ("Write me a short story about a lighthouse keeper",
                  "A bedtime story for a seven year old",
                  "Plan a novel in twelve chapters"):
            self.assertEqual(L.kind_of(r), "story", r)

    def test_things_to_build(self):
        for r in ("A lamp that turns on when someone walks past",
                  "An RFID audio player in a box",
                  "A story box that plays a track when a tag is placed on it"):
            self.assertEqual(L.kind_of(r), "design", r)

    def test_a_word_inside_another_is_not_a_story(self):
        self.assertEqual(L.kind_of("A storyboard stand for my desk"), "design")


class TestNames(unittest.TestCase):
    def test_from_the_requests_own_words(self):
        self.assertEqual(L.name_for("I would like to build a garden moisture alarm"),
                         "garden moisture alarm")
        self.assertEqual(L.name_for("Write me a short story about a lighthouse keeper"),
                         "lighthouse keeper")

    def test_unique(self):
        self.assertEqual(L.name_for("a door bell", {"door-bell"}), "door bell 2")

    def test_never_empty_and_always_a_valid_project_name(self):
        from nemo.gui import controller as C
        for r in ("!!!", "a the and", "x" * 200, "Lámpara de mesa"):
            self.assertIsNone(C.validate_name(L.name_for(r)), r)


class TestStoriesAreKeptAndListed(unittest.TestCase):
    def test_a_request_is_kept_and_found(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "nemo-stories"
            a = L.file_story(root, "A tale about a fox who keeps a lighthouse")
            time.sleep(0.05)
            b = L.file_story(root, "A tale about a fox who keeps a lighthouse")
            self.assertNotEqual(a, b)
            listed = L.list_stories(root)
            self.assertEqual([s["name"] for s in listed], [b.name, a.name])  # newest first
            self.assertEqual(listed[0]["asked"], "A tale about a fox who keeps a lighthouse")
            self.assertIn(L.REQUEST, listed[0]["files"])

    def test_no_folder_is_no_stories(self):
        self.assertEqual(L.list_stories(Path(tempfile.gettempdir()) / "no-such-nemo"), [])


class TestStorageOffTheStick(unittest.TestCase):
    def test_says_nothing_and_saves_nothing(self):
        with mock.patch.object(storage, "SYNC", Path("/no/such/nemo-sync")), \
             mock.patch("subprocess.run") as run:
            self.assertIsNone(storage.status())
            ok, msg = storage.save_now()
        self.assertTrue(ok)
        run.assert_not_called()

    def test_on_a_stick_it_asks_the_root_helper_without_a_password(self):
        done = subprocess.CompletedProcess([], 0, "nemo-sync: saved to the stick\n", "")
        with mock.patch.object(storage, "has_stick", return_value=True), \
             mock.patch("subprocess.run", return_value=done) as run:
            ok, msg = storage.save_now()
        self.assertTrue(ok); self.assertEqual(msg, "saved to the stick")
        argv = run.call_args[0][0]
        self.assertEqual(argv[:3], ["sudo", "-n", str(storage.SYNC)])
        self.assertEqual(argv[3], "save")


class TestTheImage(unittest.TestCase):
    def test_it_keeps_work_on_the_stick(self):
        b = read(BUILD)
        self.assertIn('install -m 0755 "$REPO/install/linux/nemo-sync" "$ROOT/usr/local/sbin/nemo-sync"', b)
        self.assertIn("%sudo ALL=(root) NOPASSWD: /usr/local/sbin/nemo-sync", b)
        self.assertIn("systemctl enable nemo-sync.timer nemo-sync-shutdown.service", b)
        self.assertIn("ExecStop=/usr/local/sbin/nemo-sync save nemo", b)
        self.assertRegex(b, r"apt-get install[^\n]*\brsync\b")

    def test_nemo_opens_at_the_prompt_window_at_boot(self):
        b = read(BUILD)
        self.assertIn("/etc/xdg/autostart/nemo.desktop", b)
        self.assertIn("Exec=/opt/nemo/app/nemodoc --prompt", b)
        d = read(NEMODOC)
        self.assertIn('exec "$VENV/bin/nemo" gui --prompt', d)
        self.assertIn('sudo -n "$SYNC" restore', d)

    def test_the_helper_writes_only_to_a_fat_boot_stick(self):
        s = read(SYNC)
        self.assertIn('MEDIUM="${NEMO_MEDIUM:-/run/live/medium}"', s)
        self.assertIn("vfat|exfat) ;;", s)
        self.assertIn("remount,ro", s)
        self.assertNotIn("--backup", s)          # a changed file is not copied every save

    def test_the_command_line_opens_at_the_prompt(self):
        from nemo import cli
        with mock.patch("nemo.gui.app.main", return_value=0) as main:
            cli.main(["gui", "--prompt"])
        main.assert_called_once_with(prompt=True)


def _wsl_debian() -> bool:
    """WSL's Debian with sh, rsync and python3, where the stick helper can run on Windows."""
    if not sys.platform.startswith("win") or not shutil.which("wsl.exe"):
        return False
    try:
        r = subprocess.run(["wsl.exe", "-d", "Debian", "--", "sh", "-c",
                            "command -v rsync && command -v python3"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


@unittest.skipUnless(_wsl_debian(), "needs Windows with WSL's Debian")
class TestTheHelperUnderWSL(unittest.TestCase):
    """The stick helper's real tests (below) need Linux; on Windows they run
    in WSL's Debian, so they are not only skipped here (2026-10-28)."""

    def test_the_helpers_real_tests_pass_in_debian(self):
        here = Path(__file__).resolve().parent
        unix = "/mnt/" + here.drive[0].lower() + here.as_posix()[2:]
        r = subprocess.run(["wsl.exe", "-d", "Debian", "--", "sh", "-c",
                            f"cd '{unix}' && python3 -m unittest test_prompt.TestTheHelperForReal"],
                           capture_output=True, text=True, timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out[-2000:])
        self.assertIn("Ran 5 tests", out)


@unittest.skipUnless(os.name == "posix" and shutil.which("rsync") and shutil.which("sh"),
                     "needs sh and rsync (Linux)")
class TestTheHelperForReal(unittest.TestCase):
    """nemo-sync itself, in plain folders (NEMO_SYNC_TEST skips the mounts)."""

    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self.home, self.medium = self.t / "home", self.t / "medium"
        (self.home / "nemo-projects" / "lamp").mkdir(parents=True)
        self.medium.mkdir()
        self.env = dict(os.environ, NEMO_SYNC_TEST="1", NEMO_SYNC_HOME=str(self.home),
                        NEMO_MEDIUM=str(self.medium), NEMO_SYNC_STATE=str(self.t / "run"))

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def sync(self, action, **env):
        return subprocess.run(["sh", str(SYNC), action, os.environ.get("USER", "root")],
                              env={**self.env, **env}, capture_output=True, text=True)

    def test_a_damaged_folder_stops_only_itself(self):
        """D207 (booted stick, 2026-10-31): the storeroom's rsync failed, so
        .nemo/art after it never came back, and nothing could be saved."""
        data = self.medium / "NemoData"
        for f in ("nemo-storeroom", ".nemo/art/departments", "nemo-projects/lamp"):
            (data / f).mkdir(parents=True)
        (data / ".nemo/art/departments/home.png").write_text("art", encoding="utf-8")
        (data / "nemo-storeroom/stock.yaml").write_text("mine", encoding="utf-8")
        (self.home / "nemo-storeroom").mkdir()
        bin_ = self.t / "bin"; bin_.mkdir()
        (bin_ / "rsync").write_text(
            '#!/bin/sh\ncase "$*" in *NemoData/nemo-storeroom/*) exit 23 ;; esac\n'
            f'exec {shutil.which("rsync")} "$@"\n', encoding="utf-8")
        (bin_ / "rsync").chmod(0o755)
        path = f"{bin_}{os.pathsep}{os.environ['PATH']}"
        r = self.sync("restore", PATH=path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("except: nemo-storeroom", r.stdout)
        self.assertTrue((self.home / ".nemo/art/departments/home.png").is_file())
        self.assertEqual(self.sync("save", PATH=path).returncode, 0)   # saving goes on
        self.assertEqual((data / "nemo-storeroom/stock.yaml").read_text(), "mine")
        self.assertFalse(list((data / ".removed").rglob("stock.yaml")))  # not taken for deleted

    def test_save_delete_restore(self):
        lamp = self.home / "nemo-projects" / "lamp"
        (lamp / "brief.yaml").write_text("v1", encoding="utf-8")
        (lamp / "notes.txt").write_text("old", encoding="utf-8")
        self.assertEqual(self.sync("restore").returncode, 0)
        self.assertEqual(self.sync("save").returncode, 0)
        (lamp / "notes.txt").unlink()
        time.sleep(2.2); (lamp / "brief.yaml").write_text("v2", encoding="utf-8")
        self.assertEqual(self.sync("save").returncode, 0)
        data = self.medium / "NemoData"
        self.assertEqual((data / "nemo-projects/lamp/brief.yaml").read_text(), "v2")
        self.assertFalse((data / "nemo-projects/lamp/notes.txt").exists())
        self.assertTrue(list((data / ".removed").rglob("notes.txt")))
        shutil.rmtree(self.home); self.home.mkdir()
        self.assertEqual(self.sync("restore").returncode, 0)
        self.assertEqual((self.home / "nemo-projects/lamp/brief.yaml").read_text(), "v2")

    def test_prompt_caches_move_to_the_stick_and_never_come_back(self):
        slots = self.home / ".nemo/slots/qwen3-1.7b-1107409472-c8192"
        slots.mkdir(parents=True)
        old, fresh = slots / "old.bin", slots / "fresh.bin"
        for f in (old, fresh):
            f.write_bytes(b"\0" * 3_000_000)
        t = time.time() - 60
        os.utime(old, (t, t))                 # finished a minute ago; fresh is not
        self.sync("restore")
        self.assertEqual(self.sync("save").returncode, 0)
        kept = self.medium / "NemoData/.nemo/slots" / slots.name
        self.assertEqual(sorted(p.name for p in kept.iterdir()), ["old.bin"])
        self.assertEqual(sorted(p.name for p in slots.iterdir()), ["fresh.bin"])
        shutil.rmtree(self.home); self.home.mkdir()
        self.sync("restore")
        self.assertFalse((self.home / ".nemo/slots").exists())

    def test_the_stick_keeps_the_newest_prompt_caches(self):
        slots = self.home / ".nemo/slots/m"
        slots.mkdir(parents=True)
        self.sync("restore")
        for n in ("a", "b", "c"):
            f = slots / f"{n}.bin"; f.write_bytes(b"\0" * 3_000_000)
            t = time.time() - 60; os.utime(f, (t, t))
            self.assertEqual(self.sync("save").returncode, 0)
            time.sleep(1.1)
        r = self.sync("save", SLOTS_MB="4")
        self.assertEqual(r.returncode, 0)
        kept = self.medium / "NemoData/.nemo/slots/m"
        self.assertEqual(sorted(p.name for p in kept.iterdir()), ["c.bin"])

    def test_no_save_before_the_boots_restore(self):
        (self.home / "nemo-projects/lamp/a.txt").write_text("a", encoding="utf-8")
        self.sync("restore"); self.sync("save")
        shutil.rmtree(self.home); self.home.mkdir()
        r = self.sync("save", NEMO_SYNC_STATE=str(self.t / "new-boot"))
        self.assertEqual(r.returncode, 4)
        self.assertTrue((self.medium / "NemoData/nemo-projects/lamp/a.txt").exists())


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"HOME": self.t.name, "USERPROFILE": self.t.name,
                                                 "NEMO_HOME": self.t.name + "/.nemo"})
        self._env.start()
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.A = A
        self.app = A.NemoApp(); self.app.withdraw(); self.app.update()

    def tearDown(self):
        self.app.destroy()
        # A window's background work (the Doctors' look at the machine writes
        # its case note) may still be writing in the home: wait for it, or the
        # folder is "not empty" when removed, 1 run in 3 (2026-10-29).
        import threading
        for th in threading.enumerate():
            if th is not threading.current_thread() and th.daemon:
                th.join(timeout=60)
        self._env.stop(); self.t.cleanup()

    def test_a_story_request_is_kept_and_listed(self):
        from nemo.gui.prompt import PromptWindow
        pw = PromptWindow(self.app); self.app.update()
        request = "Write me a short story about a lighthouse keeper"
        with mock.patch.object(self.app, "start_job") as job, \
             mock.patch("nemo.companion.reply", return_value="That sounds lovely."):
            # 2026-10-23: Nemo answers as itself and only suggests the Library;
            # naming it brings its card, carrying the request; Go there starts it.
            self.say(pw, request)
            self.assertIsNone(pw._card)
            job.assert_not_called()
            self.say(pw, "Library")
            self.assertEqual(pw._card_key, "library")
            pw.go(request, pw._card_key); self.app.update()
        self.assertIn("Story list", pw.status.cget("text"))
        argv, kind = job.call_args[0]
        self.assertEqual(kind, "story")
        self.assertEqual(argv[-4:], ["story", "write", "lighthouse-keeper", "--json"])
        w = self.A.StoryList(self.app); self.app.update()
        self.assertEqual(len(w.tree.get_children()), 1)
        w.destroy()
        # D273: the 1.5 s timer into the Library outlived the window ("invalid
        # command name ...leave_home") when it closed first.
        job_id = pw._leave_job
        with mock.patch.object(pw, "after_cancel", wraps=pw.after_cancel) as cancel:
            pw.destroy()
        cancel.assert_any_call(job_id)

    def test_the_glows_timer_dies_with_it(self):
        from nemo.gui.prompt import Glow
        o = Glow(self.app); self.app.update()
        with mock.patch.object(o, "after_cancel", wraps=o.after_cancel) as cancel:
            o.destroy()
        cancel.assert_called_once()

    def test_the_story_button_is_first_and_save_to_stick_only_on_a_stick(self):
        texts = []

        def walk(w):
            for c in w.winfo_children():
                try:
                    texts.append(c.cget("text"))
                except Exception:                  # noqa: BLE001
                    pass
                walk(c)
        walk(self.app)
        self.assertIn("Story", texts)
        self.assertNotIn("Save to stick", texts)     # this test machine is no stick

    def say(self, pw, text):
        """Type and send, and wait for Nemo's answer (a stand-in model)."""
        pw.box.insert("1.0", text)
        pw.send(); self.app.update()
        for _ in range(100):
            if getattr(pw, "_talk_job", None) is None:
                break
            self.app.update(); self.app.after(30)
        self.app.update()

    def test_nemo_answers_as_itself_and_only_suggests(self):
        # The owner's rule (2026-10-23): Nemo is his companion; it changes
        # department only when he names one or presses its card.
        from nemo.gui.prompt import PromptWindow
        pw = PromptWindow(self.app); self.app.update()
        with mock.patch("nemo.companion.reply", return_value="I can help with that.") as reply:
            self.say(pw, "3d print the stand on the kobra")
        self.assertEqual(reply.call_args[0][1], "3d print the stand on the kobra")
        self.assertIsNone(pw._card)                                        # no change of department
        self.assertIn("I can help with that.", pw.status.cget("text"))
        self.assertIn("The Print Shop could help", pw.status.cget("text"))
        self.assertEqual(pw.suggest_btn.cget("text"), "\u2192 Print Shop")
        pw.suggest_btn.invoke(); self.app.update()                         # pressing its card
        self.assertEqual(pw._card_key, "printshop")
        pw.hide_department()
        self.say(pw, "go to the science")
        self.assertEqual(pw._card_key, "science")                          # named: it changes
        pw.destroy()

    def test_a_crisis_gets_the_helplines_not_the_model(self):
        from nemo import companion
        router = mock.Mock()
        said = companion.reply(router, "I want to die")
        router.ask.assert_not_called()
        self.assertIn("116 123", said)
        self.assertIn("999 or 112", said)
        self.assertFalse(companion.crisis("this lamp is killing me with its bugs"))

    def test_the_home_scene_answers_with_a_department(self):
        from nemo.gui.prompt import PromptWindow
        pw = PromptWindow(self.app); self.app.update()
        pw.show_department("3d print the stand on the kobra", "printshop", ["kobra"]); self.app.update()
        self.assertEqual(pw._card_key, "printshop")
        self.assertEqual(pw.glow.itemcget(pw._panel, "state"), "hidden")   # the prompt steps aside
        self.assertIsNotNone(pw._card_img)                                 # the card is shown
        pw.show_department("3d print the stand", "music", []); self.app.update()
        self.assertEqual(pw._card_key, "music")                            # somewhere else
        with mock.patch.object(self.app, "open_department") as open_:
            pw.go("3d print the stand", "printshop")
        open_.assert_called_once_with("printshop")

    def test_back_shows_the_prompt_again(self):
        from nemo.gui.prompt import PromptWindow
        pw = PromptWindow(self.app); self.app.update()
        pw.show_department("my playlist", "music", ["playlist"]); self.app.update()
        pw.hide_department(); self.app.update()
        self.assertIsNone(pw._card)
        self.assertEqual(pw.glow.itemcget(pw._panel, "state"), "normal")
        pw.destroy()

    def test_each_department_opens_its_window(self):
        from nemo.staff import DEPARTMENTS
        for key in DEPARTMENTS:
            w = self.app.open_department(key)          # its pixel room (2026-10-23)
            self.assertIsNotNone(w, key)
            self.app.update(); w.destroy()
            real = self.app.real_window(key)           # its own working window
            if key in ("workshop", "computer_lab"):
                self.assertIsNone(real, key)               # they are this main window
            else:
                self.assertIsNotNone(real, key)
                self.app.update(); real.destroy()


class TestWhichDepartment(unittest.TestCase):
    """The home scene's choice, by words (prompt_logic.department_for)."""

    def test_requests_go_to_the_right_department(self):
        from nemo.gui.prompt_logic import department_for
        for request, key in (("write me a story about a lighthouse keeper", "library"),
                             ("a lamp with an esp32 and a light sensor", "workshop"),
                             ("3d print the stand on the kobra", "printshop"),
                             ("my playlist for the evening", "music"),
                             ("cast the holiday video to the tv", "theatre"),
                             ("something is broken, Nemo shows an error", "doctors"),
                             ("make a film of my story", "film"),
                             ("what is on my network", "home"),
                             ("A story box that plays a track when a tag is placed on it", "workshop"),
                             ("a nice plaque for the door", "art_studio"),
                             ("record a podcast", "audio"),
                             ("hello", "workshop")):
            self.assertEqual(department_for(request)[0], key, request)

    def test_every_department_has_its_words_and_card(self):
        from nemo.gui import controller as C
        from nemo.gui.prompt_logic import DEPARTMENT_WORDS
        from nemo.staff import DEPARTMENTS
        self.assertEqual(set(DEPARTMENT_WORDS), set(DEPARTMENTS))
        for key in DEPARTMENTS:
            self.assertTrue(C.department_card(key).is_file(), key)
