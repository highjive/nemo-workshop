"""Mixing, mastering, animation, hand editing and rebuilding (owner, 2026-11-19: "grab and add
to nemo"; nemo/crafts.py, nemo/mixing.py)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import asks, crafts, mixing

try:
    import numpy as np
    import soundfile as sf
except ImportError:                                  # pragma: no cover
    np = None

ROOT = Path(__file__).resolve().parent.parent


def tone(path: Path, hz: float, amp: float, seconds=3.0, rate=44100, stereo=False):
    t = np.arange(int(rate * seconds)) / rate
    x = (amp * np.sin(2 * np.pi * hz * t)).astype("float32")
    sf.write(str(path), np.stack([x, x], 1) if stereo else x, rate)
    return path


class TestPinned(unittest.TestCase):
    def test_nemodoc_fetches_exactly_what_nemo_pins(self):
        text = (ROOT / "NemoDoc.ps1").read_text(encoding="utf-8")
        for key, p in crafts.PROGRAMS.items():
            self.assertIn(p.sha256, text, key)
            self.assertIn(p.url, text, key)
            self.assertIn(f"bytes = {p.bytes}", text, key)
            self.assertTrue(p.url.endswith("/" + p.file), key)
            self.assertIn(f"/v{p.version}/", p.url, key)
            self.assertRegex(p.sha256, r"^[0-9a-f]{64}$")

    def test_the_doctors_look_for_newer_ones(self):
        from nemo import toolupdates
        keys = {t.key for t in toolupdates.TOOLS}
        self.assertTrue(set(crafts.PROGRAMS) <= keys)

    def test_every_new_employee_has_its_tools(self):
        from nemo import staff, toolkit
        for key in ("music.mixer", "music.mastering", "film.animator", "film.finisher",
                    "computer_lab.rebuilder"):
            self.assertIn(key, staff.STAFF)
            self.assertTrue(toolkit.NEEDS[key], key)

    def test_the_stick_carries_exactly_what_nemo_pins(self):
        # Owner, 2026-11-19: "use rea to make them available on the stick".
        text = (ROOT / "install" / "live-build" / "build-iso.sh").read_text(encoding="utf-8")
        for key, (file, size, sha) in crafts.LINUX.items():
            version = crafts.PROGRAMS[key].version
            self.assertEqual(file, f"{key}-{version}-linux-x86_64.tar.gz")
            self.assertIn(f'"{key} {version} {sha}"', text, key)
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
        self.assertIn('"matchering==2.0.6"', text)
        self.assertNotIn("opentoonz", crafts.LINUX)          # no Linux release to carry

    def test_on_linux_each_is_found_in_its_folder(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(crafts.sys, "platform", "linux"), \
                mock.patch.object(crafts, "LINUX_DIR", Path(d)):
            (Path(d) / "filmcraft" / "bin").mkdir(parents=True)
            (Path(d) / "filmcraft" / "bin" / "filmcraft-cli").write_bytes(b"")
            (Path(d) / "filmcraft" / "bin" / "filmcraft").write_bytes(b"")
            self.assertEqual(crafts.find("filmcraft"), Path(d) / "filmcraft" / "bin" / "filmcraft-cli")
            self.assertEqual(crafts.find("filmcraft", cli=False).name, "filmcraft")
            self.assertIsNone(crafts.find("soundcraft"))
            self.assertIn("build-iso.sh", crafts.not_installed("soundcraft"))
            self.assertIn("no Linux build", crafts.not_installed("opentoonz"))

    def test_nemo_never_signs_in_or_sets_craft_anything_up(self):
        src = (ROOT / "nemo" / "crafts.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        for word in ('"setup"', '"rebuild"', '"ai"', "--allow-run", "--deep"):
            self.assertNotIn(word, code)


@unittest.skipIf(np is None, "needs numpy and soundfile")
class TestMixEngineer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def test_changes_are_read_from_the_words(self):
        stems, said = mixing.changes(["song", "bass.wav", "vocals=+3", "gtr=-2,left", "keys=0,0.25"])
        self.assertEqual(stems, ["song", "bass.wav"])
        self.assertEqual(said, {"vocals": (3.0, None), "gtr": (-2.0, -0.6), "keys": (0.0, 0.25)})
        with self.assertRaises(mixing.MixError):
            mixing.changes(["x=1,2"])

    def test_each_stem_is_brought_to_the_same_level(self):
        a = tone(self.d / "bass.wav", 110, 0.5)
        b = tone(self.d / "lead.wav", 440, 0.05)
        stems = mixing.plan([a, b], {"lead": (2.0, None)})
        loud = [s.rms_db + s.gain_db - s.change_db for s in stems]
        self.assertAlmostEqual(loud[0], mixing.LEVEL_DB, delta=0.05)
        self.assertAlmostEqual(loud[1], mixing.LEVEL_DB, delta=0.05)
        self.assertEqual(stems[1].change_db, 2.0)
        with self.assertRaises(mixing.MixError) as e:
            mixing.plan([a, b], {"drums": (1.0, None)})
        self.assertIn("bass, lead", str(e.exception))
        silent = self.d / "quiet.wav"
        sf.write(str(silent), np.zeros(4410, dtype="float32"), 44100)
        with self.assertRaises(mixing.MixError):
            mixing.plan([silent], {})

    def test_a_stereo_stem_is_balanced_not_moved_whole(self):
        # 2026-11-19: SoundCraft's pan with no channel index put BOTH channels of a stereo
        # stem at 0.5; the stem was gone from the left. Each channel is panned now.
        self.assertEqual(mixing.pan_commands(5, 2, 0.5),
                         [("mix.pan", {"tracks": [5], "pan": 0.0, "index": 0}),
                          ("mix.pan", {"tracks": [5], "pan": 1.0, "index": 1})])
        self.assertEqual(mixing.pan_commands(5, 2, -1.0)[1][1]["pan"], -1.0)
        self.assertEqual(mixing.pan_commands(2, 1, -0.3), [("mix.pan", {"tracks": [2], "pan": -0.3})])
        self.assertEqual(mixing.pan_commands(2, 2, 0.0), [])

    def test_a_loud_bounce_comes_down_once(self):
        a = tone(self.d / "bass.wav", 110, 0.5)
        b = tone(self.d / "lead.wav", 440, 0.5, stereo=True)
        calls = []

        def fake(key, argv, cfg=None, timeout=0):
            calls.append(argv)
            if any(x.startswith("file.import_audio=") for x in argv):
                return ('file.import_audio: {"imported":[{"channels":1,"track":2},'
                        '{"channels":2,"track":5}]}\n')
            peak = 2.0 if len(calls) == 2 else -1.5
            return json.dumps({"lufs": -9.0, "peak_db": peak, "true_peak_db": peak}) + "\n"
        with mock.patch.object(crafts, "run_cli", side_effect=fake), \
                mock.patch("nemo.music.shelf", return_value=self.d / "music"):
            m = mixing.mix(None, "My Song", [a, b], {"lead": (0.0, 0.5)}, say=lambda s: None)
        self.assertEqual(len(calls), 3)                     # import, bounce, bounce again
        self.assertEqual(m.trimmed_db, 3.5)                 # 2.0 - (-1.0) + 0.5
        self.assertIn("--in-place", calls[1])
        vols = [json.loads(x.split("=", 1)[1]) for x in calls[2] if x.startswith("mix.volume=")]
        self.assertEqual([v["tracks"] for v in vols], [[2], [5]])
        self.assertAlmostEqual(vols[0]["db"], m.stems[0].gain_db - 3.5, places=2)
        self.assertEqual(m.out.name, "My Song.wav")
        kept = json.loads((m.out.parent / "My Song.json").read_text(encoding="utf-8"))
        self.assertEqual(kept["trimmed_db"], 3.5)

    @unittest.skipUnless(crafts.find("soundcraft"), "SoundCraft is not installed")
    def test_a_real_mix_in_soundcraft(self):
        a = tone(self.d / "bass.wav", 110, 0.5)
        b = tone(self.d / "lead.wav", 440, 0.3, stereo=True)
        with mock.patch("nemo.music.shelf", return_value=self.d / "music"):
            m = mixing.mix(None, "tones", [a, b], {"lead": (0.0, 0.5)}, say=lambda s: None)
        x, rate = sf.read(str(m.out))
        self.assertEqual((x.shape[1], rate), (2, 48000))
        self.assertLess(m.peak_db, mixing.PEAK_DB)
        left, right = np.sqrt((x ** 2).mean(0))
        self.assertGreater(left, 0.1 * 10 ** (mixing.LEVEL_DB / 20))  # the lead is on the left too
        self.assertGreater(right, left)
        self.assertTrue(m.session.is_file())

    @unittest.skipUnless(mixing.__name__ and __import__("importlib").util.find_spec("matchering"),
                         "Matchering is not installed")
    def test_a_track_is_mastered_like_the_reference(self):
        rng = np.random.default_rng(3)
        t = np.arange(44100 * 12) / 44100
        quiet = (0.05 * np.sin(2 * np.pi * 220 * t) + 0.02 * rng.standard_normal(len(t)))
        loud = np.clip(0.5 * np.sin(2 * np.pi * 330 * t) + 0.2 * rng.standard_normal(len(t)), -.95, .95)
        sf.write(str(self.d / "song.wav"), np.stack([quiet, quiet], 1).astype("float32"), 44100)
        sf.write(str(self.d / "ref.wav"), np.stack([loud, loud], 1).astype("float32"), 44100)
        out = mixing.master(None, self.d / "song.wav", self.d / "ref.wav", say=lambda s: None)
        y, _ = sf.read(str(out))
        self.assertGreater(20 * np.log10(np.sqrt((y ** 2).mean())),
                           20 * np.log10(np.sqrt((quiet ** 2).mean())) + 10)
        self.assertLess(np.abs(y).max(), 1.0)
        with self.assertRaises(mixing.MixError):
            mixing.master(None, self.d / "song.wav", self.d / "none.wav")


class TestStemsAreNotTracks(unittest.TestCase):
    def test_the_stems_folder_is_left_out_of_the_tracks(self):
        from nemo import music
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "stems" / "song").mkdir(parents=True)
            (root / "stems" / "song" / "bass.wav").write_bytes(b"RIFF")
            (root / "Band").mkdir()
            (root / "Band" / "01 Tune.wav").write_bytes(b"RIFF")
            with mock.patch.object(music, "shelf", return_value=root), \
                    mock.patch.object(music, "_tag_cache", return_value=root / "cache.json"):
                found = music.tracks(None)
        self.assertEqual([t.title for t in found], ["Tune"])


class TestFinishingEditor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        (self.d / "work").mkdir(); (self.d / "shelf").mkdir()
        for n in ("00-title", "01-scene", "02-scene", "99-credits"):
            (self.d / "work" / f"{n}.mp4").write_bytes(b"\0")
        (self.d / "work" / "title.png").write_bytes(b"\0")
        (self.d / "shelf" / "A Fox.mp4").write_bytes(b"\0")
        (self.d / "shelf" / "A Fox.srt").write_text("1\n", encoding="utf-8")
        for target, kw in (("nemo.filmstudio.studio",
                            {"side_effect": lambda cfg, n: self.d / ("work" if n == "A Fox" else n)}),
                           ("nemo.filmstudio.videos_shelf", {"return_value": self.d / "shelf"})):
            m = mock.patch(target, **kw); m.start(); self.addCleanup(m.stop)

    def test_the_pieces_in_order_with_the_subtitles(self):
        pieces, srt = crafts.film_pieces(None, "A Fox")
        self.assertEqual([p.stem for p in pieces], ["00-title", "01-scene", "02-scene", "99-credits"])
        self.assertEqual(srt.name, "A Fox.srt")
        cmds = crafts.filmcraft_script(pieces, "A Fox", self.d / "x.fcproj", srt)
        self.assertEqual([c["id"] for c in cmds],
                         ["file.newProject", "file.import", "file.newSequence",
                          "clip.automateToSequence", "file.saveAs", "captions.import", "file.save"])
        self.assertEqual(cmds[3]["params"]["items"], [1, 2, 3, 4])
        self.assertFalse(cmds[3]["params"]["videoTransition"])
        self.assertEqual((cmds[2]["params"]["width"], cmds[2]["params"]["fps"]), (1280, 30))
        with self.assertRaises(crafts.CraftError):
            crafts.film_pieces(None, "no such film")

    def test_subtitles_it_cannot_read_lose_only_themselves(self):
        # 2026-11-19, FilmCraft: "not a caption file" stopped the whole run before the save.
        said = []
        project = self.d / "work" / "A Fox.fcproj"

        def fake(key, argv, cfg=None, timeout=0):
            project.write_text("{}", encoding="utf-8")
            raise crafts.CraftError(
                'FilmCraft stopped (exit 1): {"id":"file.newProject","ok":true}\n'
                '{"id":"file.import","ok":true}\n{"id":"file.newSequence","ok":true}\n'
                '{"id":"clip.automateToSequence","ok":true}\n{"id":"file.saveAs","ok":true}\n'
                '{"id":"captions.import","ok":false,"error":"not a caption file"}\n')
        with mock.patch.object(crafts, "run_cli", side_effect=fake):
            got = crafts.hand_edit(None, "A Fox", open_it=False, say=said.append)
        self.assertEqual(got, project)
        self.assertIn("not a caption file", said[-1])
        self.assertNotIn("and the subtitles", said[0])

    def test_a_failed_command_is_said(self):
        out = ('{"id":"file.newProject","ok":true}\n'
               '{"id":"file.import","ok":false,"error":"cannot read 01-scene.mp4"}\n')
        with mock.patch.object(crafts, "run_cli", return_value=out):
            with self.assertRaises(crafts.CraftError) as e:
                crafts.hand_edit(None, "A Fox", open_it=False, say=lambda s: None)
        self.assertIn("cannot read 01-scene.mp4", str(e.exception))

    @unittest.skipUnless(crafts.find("filmcraft"), "FilmCraft is not installed")
    def test_a_real_project_from_real_clips(self):
        from nemo import filmstudio as F
        ff = F.ffmpeg()
        if ff is None:
            self.skipTest("no ffmpeg")
        import subprocess
        for p in (self.d / "work").glob("*.mp4"):
            p.unlink()
        (self.d / "shelf" / "A Fox.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nA fox.\n\n2\n00:00:01,000 --> 00:00:02,000\n"
            "The end.\n", encoding="utf-8")
        said = []
        for n, src in (("00-title", "testsrc"), ("01-scene", "smptebars")):
            subprocess.run([str(ff), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            f"{src}=size=320x180:rate=30", "-f", "lavfi", "-i", "sine=f=440",
                            "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            str(self.d / "work" / f"{n}.mp4")], check=True)
        project = crafts.hand_edit(None, "A Fox", open_it=False, say=said.append)
        self.assertTrue(project.is_file())
        self.assertIn("and the subtitles", said[0])
        kept = json.loads(project.read_text(encoding="utf-8"))
        text = json.dumps(kept)
        self.assertIn("00-title", text)
        self.assertIn("01-scene", text)


class TestAnimator(unittest.TestCase):
    def test_only_a_scene_is_rendered(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "walk.png"
            p.write_bytes(b"\0")
            with self.assertRaises(crafts.CraftError) as e:
                crafts.render_scene(None, p)
            self.assertIn(".tnz", str(e.exception))

    def test_frames_become_a_video(self):
        from nemo import filmstudio as F
        ff = F.ffmpeg()
        if ff is None or np is None:
            self.skipTest("needs ffmpeg and numpy")
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            scene = d / "walk.tnz"
            scene.write_text("<tnz/>", encoding="utf-8")

            def fake(key, args, cfg=None, timeout=0):
                out = Path(args[args.index("-o") + 1])
                for i in range(1, 7):
                    Image.new("RGB", (63, 41), (i * 40, 0, 0)).save(
                        out.with_name(f"frame.{i:04d}.png"))
                return ""
            with mock.patch.object(crafts, "run_cli", side_effect=fake), \
                    mock.patch.object(F, "studio", return_value=d / "work"), \
                    mock.patch.object(F, "videos_shelf", return_value=d / "videos"):
                out = crafts.render_scene(None, scene, fps=12, say=lambda s: None)
            self.assertEqual(out, d / "videos" / "walk.mp4")
            self.assertGreater(out.stat().st_size, 0)


class TestTheBoxes(unittest.TestCase):
    def test_the_words(self):
        cases = [
            ("music", "master my song like the reference song",
             ["music", "master", "song", "reference song"]),
            ("music", "master demo mix to sound like Big Hit", ["music", "master", "demo mix", "Big Hit"]),
            ("music", "mix band demo", ["music", "mix", "band demo", "band demo"]),
            ("film", "edit A Fox by hand", ["film", "edit", "A Fox"]),
            ("film", "cut the film A Fox", ["film", "edit", "A Fox"]),
            ("film", "animate", ["film", "animate"]),
            ("film", "render scene walk cycle", ["film", "animate", "walk cycle"]),
            ("film", "make a film of a-fox", ["film", "make", "a-fox"]),
            ("computer_lab", "open craft anything", ["rebuild"]),
            ("computer_lab", "is craft anything set up", ["rebuild", "doctor"]),
        ]
        for key, text, argv in cases:
            r = asks.answer(key, text, {})
            self.assertEqual((r.kind, r.argv), (asks.RUN, argv), text)
        r = asks.answer("music", "master it", {})
        self.assertEqual(r.kind, asks.SAY)
        self.assertIn("never fetches", r.say)

    def test_every_command_parses(self):
        from nemo import cli

        class Parsed(Exception):
            pass
        for argv in (["music", "mix", "song", "a.wav", "b.wav", "a=+1"], ["music", "master", "a", "b"],
                     ["film", "edit", "A Fox", "--no-open"], ["film", "animate", "walk", "--fps", "12"],
                     ["rebuild"], ["rebuild", "doctor"]):
            with mock.patch.object(cli.Config, "load", side_effect=Parsed), mock.patch("sys.stderr"):
                with self.assertRaises(Parsed, msg=argv):
                    cli.main(argv)


if __name__ == "__main__":
    unittest.main()
