"""The Film Studio (owner, 2026-10-22): films from stories, clips joined,
slideshows. The last classes run the real ffmpeg where it is installed,
with a stand-in voice (a tone written to the WAV), so nothing is spoken.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import backup, filmstudio as F, mediainfo, staff

PARA = ("The lamp sat on the highest shelf of the workshop, listening for footsteps. "
        "Nobody had lit it for years, but it waited all the same. ") * 3


def tone(path: Path, seconds: float = 1.0) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(i / 8)))
                               for i in range(int(22050 * seconds))))
    return path


def fake_voice(text, wav=None, wait=False, whole=False):
    tone(Path(wav), 1.0)
    return True, ""


class AHome(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.home))
        self._env.start()
        from nemo.config import Config
        self.cfg = Config.load(Path("/nonexistent"))

    def tearDown(self):
        self._env.stop()
        self.t.cleanup()

    def story(self, name="the-lamp", chapters=3, paras=3) -> Path:
        d = self.cfg.path("paths.stories") / name
        (d / "chapters").mkdir(parents=True)
        (d / "story.md").write_text("# The Lamp That Waited\n", encoding="utf-8")
        for c in range(1, chapters + 1):
            (d / "chapters" / f"{c:02d}.md").write_text(
                f"# {c}. Part {c}\n\n" + "\n\n".join(PARA for _ in range(paras)), encoding="utf-8")
        return d

    def picture(self, name="p.png", colour=(200, 120, 40)) -> Path:
        from PIL import Image
        p = self.home / name
        Image.new("RGB", (320, 240), colour).save(p)
        return p


class TestTheDirector(AHome):
    def test_scenes_of_a_few_paragraphs_with_no_headings(self):
        plan = F.plan_story(self.story())
        self.assertEqual(plan.title, "The Lamp That Waited")
        self.assertTrue(2 <= len(plan.scenes) <= F.MAX_SCENES)
        for s in plan.scenes:
            self.assertNotIn("Chapter", s.text[:12])
            self.assertTrue(s.prompt.startswith("storybook cover illustration"))
            self.assertIn("The lamp sat on the highest shelf", s.prompt)
        joined = " ".join(" ".join(s.text.split()) for s in plan.scenes)
        self.assertEqual(joined.count("The lamp sat"), 3 * 3 * 3)      # nothing dropped

    def test_a_scene_is_painted_from_its_story_and_someone_in_it(self):
        # 2026-11-06: scenes were painted from "He climbed the spiral staircase"
        # and "a pair of bright eyes blinked open": no cat, no lighthouse.
        p = F._prompt("He climbed the stairs. The lamp room was dark, but Whiskers knew the "
                      "way. He pressed the switch.", "The Brave Cat", {"Whiskers"})
        self.assertIn('from the story "The Brave Cat"', p)
        self.assertTrue(p.endswith("The lamp room was dark, but Whiskers knew the way."))
        p = F._prompt("He climbed the stairs. It was dark.", "The Brave Cat", {"Whiskers"})
        self.assertTrue(p.endswith("He climbed the stairs."))      # none named: the first
        plan = F.plan_story(self.story())
        self.assertIn('from the story "The Lamp That Waited"', plan.scenes[0].prompt)

    def test_a_long_story_is_held_to_twelve_scenes(self):
        plan = F.plan_story(self.story(chapters=10, paras=6))
        self.assertEqual(len(plan.scenes), F.MAX_SCENES)

    def test_a_changed_plan_is_kept(self):
        plan = F.plan_story(self.story())
        plan.scenes = plan.scenes[:1]
        plan.scenes[0].text = "Changed by hand."
        F.save_plan(self.cfg, plan)
        again = F.plan_for(self.cfg, self.cfg.path("paths.stories") / "the-lamp")
        self.assertEqual([s.text for s in again.scenes], ["Changed by hand."])

    def test_nothing_to_film(self):
        d = self.cfg.path("paths.stories") / "empty"
        d.mkdir(parents=True)
        with self.assertRaises(F.FilmError):
            F.plan_story(d)
        self.assertEqual(F.stories(self.cfg), [])


class TestTheWriter(AHome):
    def test_subtitles_are_timed_by_share(self):
        srt = F.subtitles([("One. Two two.", 4.0, 3.0)], self.home / "x.srt").read_text(encoding="utf-8")
        self.assertIn("1\n00:00:04,000 --> 00:00:05,000\nOne.", srt)
        self.assertIn("2\n00:00:05,000 --> 00:00:07,000\nTwo two.", srt)

    def test_a_card(self):
        from PIL import Image
        p = F.card([("Title", 60), ("line", 30)], self.home / "c.png")
        with Image.open(p) as im:
            self.assertEqual(im.size, (F.WIDTH, F.HEIGHT))

    def test_a_clip_and_its_cut(self):
        self.assertEqual(F.clip_spec("holiday.mp4@5-20"), ("holiday.mp4", 5.0, 20.0))
        self.assertEqual(F.clip_spec("a.mp4@-9"), ("a.mp4", None, 9.0))
        self.assertEqual(F.clip_spec("a.mp4"), ("a.mp4", None, None))
        with self.assertRaises(F.FilmError):
            F.clip_spec("a.mp4@soon")


class TestTheFilmWithStandIns(AHome):
    def test_pictures_painted_given_or_the_cover(self):
        story = self.story(chapters=1, paras=2)
        plan = F.plan_story(story)
        plan.scenes = plan.scenes[:1] + [F.Scene("Second.", "p2")]
        given = self.picture()
        plan.scenes[1].picture = str(given)
        runs = []
        with mock.patch.object(F, "_run", side_effect=lambda cfg, a, **k: runs.append(a)), \
             mock.patch("nemo.voice.speak", side_effect=fake_voice), \
             mock.patch("nemo.artist.paint", side_effect=lambda out, *a, **k: self.picture(str(out))) as paint:
            made = F.make_film(self.cfg, plan, paint=True)
        self.assertEqual(paint.call_count, 1)                    # the given one is not painted
        pictures = [a[a.index("-i") + 1] for a in runs if "-loop" in a]
        self.assertEqual(Path(pictures[2]), given)
        self.assertTrue(pictures[0].endswith("title.png") and pictures[-1].endswith("credits.png"))
        self.assertEqual(made.film, self.cfg.path("paths.storeroom") / "videos" / "The Lamp That Waited.mp4")
        self.assertIn("1 picture(s) painted", made.notes[0])
        self.assertTrue(made.subtitles.is_file())

    def test_no_painting_uses_the_cover(self):
        story = self.story(chapters=1, paras=1)
        cover = self.picture("cover.png")
        shutil.copy(cover, story / "cover.png")
        runs = []
        with mock.patch.object(F, "_run", side_effect=lambda cfg, a, **k: runs.append(a)), \
             mock.patch("nemo.voice.speak", side_effect=fake_voice), \
             mock.patch("nemo.artist.paint") as paint:
            F.make_film(self.cfg, F.plan_story(story), paint=False)
        paint.assert_not_called()
        self.assertIn(str(story / "cover.png"), [a[a.index("-i") + 1] for a in runs if "-loop" in a])

    def test_no_ffmpeg_says_so(self):
        with mock.patch.object(F, "ffmpeg", return_value=None):
            with self.assertRaises(F.FilmError) as e:
                F._run(self.cfg, ["-version"])
        self.assertIn("not installed", str(e.exception))


class TestTheDepartment(AHome):
    def test_the_team_and_its_tools(self):
        self.assertEqual([e.title for e in staff.team("film")],
                         ["Director", "Storyboard Artist", "Narrator", "Editor", "Writer"])
        self.assertTrue(all(e.working for e in staff.team("film")))

    def test_backups_leave_the_working_files_out(self):
        self.assertTrue(backup._left_out(("film-studio", "x", "scene01.wav")))

    def test_nemodoc_fetches_what_filmstudio_pins(self):
        text = (Path(__file__).resolve().parent.parent / "NemoDoc.ps1").read_text(encoding="utf-8")
        name, size, sha = F.SOURCE
        self.assertIn(f'file = "{name}"; sha256 = "{sha}"; bytes = {size}', text)
        self.assertIn("[switch]$SkipFilm", text)
        image = (Path(__file__).resolve().parent.parent / "install" / "live-build"
                 / "build-iso.sh").read_text(encoding="utf-8")
        self.assertIn(" ffmpeg", image)


@unittest.skipUnless(_sandbox.has_display(), "no display")
class TestTheWindow(AHome):
    def test_plan_then_make(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        self.story(chapters=1, paras=2)
        app = A.NemoApp(); app.update()
        try:
            app.cfg = self.cfg
            w = A.FilmStudio(app); app.update()
            self.assertEqual(w.story.get(), "the-lamp")
            self.assertIsNotNone(w.show_plan())
            self.assertIn("Scene 1:", w.out.get("1.0", "end"))
            made = F.Made(self.home / "x.mp4", 9.0, None, ["1 scene(s)"])
            with mock.patch.object(F, "make_film", return_value=made) as mk:
                w.make()
                for _ in range(40):
                    app.update(); app.after(100)
                    if w._job is None and str(w.btn_make.cget("state")) == "normal":
                        break
            self.assertFalse(mk.call_args.kwargs["paint"])          # unticked: no painting
            self.assertIn("x.mp4 on the videos shelf", w.note.cget("text"))
            w.destroy()
        finally:
            app.destroy()


def probe(path: Path) -> dict:
    exe = F.ffmpeg()
    out = subprocess.run([str(exe.with_name("ffprobe" + exe.suffix)), "-v", "error", "-show_entries",
                          "stream=codec_type,duration,nb_frames", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


@unittest.skipUnless(F.ffmpeg(), "ffmpeg not installed here")
class TestARealFilm(AHome):
    def test_a_story_film_has_thirty_frames_a_second_and_casts(self):
        story = self.story(chapters=1, paras=1)
        plan = F.plan_story(story)
        plan.scenes[0].picture = str(self.picture())
        with mock.patch("nemo.voice.speak", side_effect=fake_voice):
            made = F.make_film(self.cfg, plan, paint=False)
        s = probe(made.film)
        video, sound = float(s["video"]["duration"]), float(s["audio"]["duration"])
        # 2026-10-22: without -framerate the first real film had 26 frames a
        # second and its picture ended 0.9 s before its sound.
        self.assertAlmostEqual(int(s["video"]["nb_frames"]) / video, F.FPS, delta=0.5)
        self.assertLess(abs(video - sound), 0.2)
        self.assertAlmostEqual(video, F.TITLE_SECONDS + 1.6 + F.CREDITS_SECONDS, delta=0.3)
        ok, lines = mediainfo.verdict(mediainfo.probe(made.film))
        self.assertTrue(ok, lines)

    def test_a_slideshow_with_music_then_clips_joined(self):
        song = tone(self.home / "song.wav", 3.0)                 # shorter than the pictures
        show = F.slideshow(self.cfg, "Pictures", [self.picture("a.png"), self.picture("b.png", (20, 90, 160))],
                           [song], seconds=2.0)
        s = probe(show.film)
        self.assertAlmostEqual(float(s["video"]["duration"]), 4.0, delta=0.2)
        self.assertAlmostEqual(float(s["audio"]["duration"]), 4.0, delta=0.2)   # silence after the song
        joined = F.join_clips(self.cfg, "Joined", [(show.film, 1.0, 3.0), (show.film, None, None)])
        self.assertAlmostEqual(float(probe(joined.film)["video"]["duration"]), 6.0, delta=0.3)
        self.assertTrue(mediainfo.verdict(mediainfo.probe(joined.film))[0])

    def test_a_clip_with_no_sound_gets_silence(self):
        show = F.slideshow(self.cfg, "Silent", [self.picture()], None, seconds=1.0)
        self.assertTrue(F.has_sound(self.cfg, show.film))          # silence is a sound track
        joined = F.join_clips(self.cfg, "J", [(show.film, None, None)])
        self.assertIn("audio", probe(joined.film))


if __name__ == "__main__":
    unittest.main()
