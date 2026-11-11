"""The Artist's story covers (owner's request, 2026-10-20): painted by a local
image model, stable-diffusion.cpp with SD-Turbo, from the story's own title
and request. These tests use a stand-in engine; the real one was timed on
the AH531 (see nemo/artist.py)."""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import artist, staff

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


class FakeEngine:
    """sd-cli: writes the -o file and says what it did."""

    def __init__(self, ok=True):
        self.ok, self.cmd = ok, None

    def __call__(self, cmd, **kw):
        self.cmd = cmd
        if self.ok:
            Path(cmd[cmd.index("-o") + 1]).write_bytes(PNG)
        proc = mock.Mock()
        proc.stdout = io.StringIO("[INFO ] image.cpp:899  - sampling completed, taking 333.52s\n"
                                  "[INFO ] image.cpp:1050 - generate_image completed in 400.0s\n")
        proc.wait.return_value = 0 if self.ok else 1
        return proc


class Case(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.t, True)
        self.home = self.t / "artist"
        (self.home / "sd").mkdir(parents=True)
        exe = "sd-cli.exe" if sys.platform.startswith("win") else "sd-cli"
        (self.home / "sd" / exe).write_text("")
        (self.home / "sd_turbo-f16-q8_0.gguf").write_text("")
        self.cfg = mock.Mock(get=lambda k, d=None: str(self.home) if k == "paths.artist" else d)
        self.story = self.t / "lighthouse"
        self.story.mkdir()
        (self.story / "request.md").write_text("# Asked\n\nWrite me a short story about a "
                                               "lighthouse keeper.\n", encoding="utf-8")
        (self.story / "story.md").write_text("# The Keeper of the Light\n\nOnce...\n",
                                             encoding="utf-8")

    def draw(self, engine=None, mb=4000):
        engine = engine or FakeEngine()
        out = artist.draw_cover(self.story, self.cfg, say=lambda m: None,
                                available_mb=lambda: mb, popen=engine)
        return out, engine


class TestPainting(Case):
    def test_a_cover_is_painted_from_the_title_and_request(self):
        out, eng = self.draw()
        self.assertEqual(out, self.story / "cover.png")
        self.assertEqual(out.read_bytes()[:8], PNG[:8])
        prompt = eng.cmd[eng.cmd.index("-p") + 1]
        self.assertIn("The Keeper of the Light", prompt)
        self.assertIn("lighthouse keeper", prompt)
        self.assertNotIn("Write me", prompt)
        self.assertEqual(eng.cmd[eng.cmd.index("--steps") + 1], "1")
        self.assertTrue((self.story / "cover-prompt.txt").is_file())

    def test_the_tiny_decoder_is_used_where_present(self):
        _, eng = self.draw()
        self.assertNotIn("--taesd", eng.cmd)
        (self.home / "taesd.safetensors").write_text("")
        _, eng = self.draw()
        self.assertEqual(Path(eng.cmd[eng.cmd.index("--taesd") + 1]).name, "taesd.safetensors")

    def test_not_enough_memory_is_said_and_nothing_runs(self):
        eng = FakeEngine()
        with self.assertRaises(artist.ArtistError) as cm:
            self.draw(eng, mb=1500)
        self.assertIn("Unload the language model", str(cm.exception))
        self.assertIsNone(eng.cmd)

    def test_no_picture_is_an_error_and_leaves_no_file(self):
        with self.assertRaises(artist.ArtistError):
            self.draw(FakeEngine(ok=False))
        self.assertFalse((self.story / "cover.png").exists())
        self.assertFalse((self.story / "cover.partial.png").exists())

    def test_no_engine_says_where_it_looked(self):
        shutil.rmtree(self.home / "sd")
        with self.assertRaises(artist.ArtistError) as cm:
            self.draw()
        self.assertIn(str(self.home), str(cm.exception))

    def test_files_saved_with_a_byte_order_mark_are_read(self):
        # Found painting a real cover (2026-10-20): files saved by PowerShell
        # (or Notepad) start with a BOM; the title was lost and "# Asked"
        # went into the prompt.
        (self.story / "request.md").write_text("﻿# Asked\n\nA story about a lighthouse.\n",
                                               encoding="utf-8")
        (self.story / "story.md").write_text("﻿# The Keeper\n\nOnce...\n", encoding="utf-8")
        title, request = artist.title_and_request(self.story)
        self.assertEqual(title, "The Keeper")
        self.assertNotIn("Asked", request)

    def test_the_asking_goes_and_the_subject_stays(self):
        p = artist.cover_prompt("The Backwards Clock",
                                "A short story about a clockmaker's apprentice who finds a "
                                "clock that runs backwards, in three chapters.")
        self.assertIn("The Backwards Clock. a clockmaker's apprentice who finds a clock", p)
        subject = p.split(": ", 1)[1]                  # after the style ("storybook ...")
        for gone in ("short", "story", "chapters", "A about"):
            self.assertNotIn(gone, subject)
        p = artist.cover_prompt("", "Please write me a bedtime story of a sleepy owl")
        self.assertTrue(p.endswith(": a sleepy owl"), p)

    def test_the_prompt_fits_the_text_encoder(self):
        p = artist.cover_prompt("T", "word " * 200)
        self.assertLessEqual(len(p.split()), 60)


class TestOnTheDesktopsGpu(Case):
    """Owner, 2026-11-04: repaint every picture with this system's GPU, at
    full-screen size, from the laptop's paintings (from the NemoIso stick)."""

    def setUp(self):
        super().setUp()
        exe = "sd-cli.exe" if sys.platform.startswith("win") else "sd-cli"
        (self.home / "sd-cuda").mkdir()
        (self.home / "sd-cuda" / exe).write_text("")
        (self.home / "taesd.safetensors").write_text("")
        from PIL import Image
        self.ref = self.t / "library.png"
        Image.new("RGB", (512, 512), (120, 80, 40)).save(self.ref)

    def paint(self, machine="desktop", vram=6000, **kw):
        eng = FakeEngine()
        with mock.patch.dict("os.environ", {"NEMO_MACHINE": machine}):
            out = artist.paint(self.t / "scene.png", "a library", self.cfg, say=lambda m: None,
                               available_mb=lambda: 4000, popen=eng, vram_free=lambda: vram, **kw)
        return out, eng

    def test_the_desktop_paints_on_the_gpu_with_the_full_decoder(self):
        _, eng = self.paint()
        self.assertEqual(Path(eng.cmd[0]).parent.name, "sd-cuda")
        self.assertNotIn("--taesd", eng.cmd)

    def test_the_laptop_never_uses_the_gpu_build_even_beside_it(self):
        _, eng = self.paint(machine="laptop")
        self.assertEqual(Path(eng.cmd[0]).parent.name, "sd")
        self.assertIn("--taesd", eng.cmd)

    def test_a_full_screen_scene_is_painted_from_the_earlier_one(self):
        out, eng = self.paint(size=(1344, 576), reference=self.ref, strength=0.4, steps=3)
        cmd = eng.cmd
        self.assertEqual((cmd[cmd.index("-W") + 1], cmd[cmd.index("-H") + 1]), ("1344", "576"))
        self.assertEqual(cmd[cmd.index("--strength") + 1], "0.40")
        self.assertEqual(cmd[cmd.index("--steps") + 1], "3")
        fitted = Path(cmd[cmd.index("-i") + 1])
        self.assertNotEqual(fitted, self.ref)                 # a fitted copy, never the original
        self.assertFalse(fitted.exists())                     # and it is cleared away after
        self.assertTrue(self.ref.is_file())

    def test_too_little_free_on_the_card_is_said_and_nothing_runs(self):
        eng = FakeEngine()
        with mock.patch.dict("os.environ", {"NEMO_MACHINE": "desktop"}), \
             self.assertRaises(artist.ArtistError) as cm:
            artist.paint(self.t / "scene.png", "a library", self.cfg, say=lambda m: None,
                         available_mb=lambda: 4000, popen=eng, vram_free=lambda: 900)
        self.assertIn("Unload the language model", str(cm.exception))
        self.assertIsNone(eng.cmd)

    def test_nemodoc_fetches_the_same_gpu_build(self):
        import re
        root = Path(__file__).resolve().parent.parent
        for base in (root, root / "install" / "windows"):
            if (base / "NemoDoc.ps1").exists():
                text = (base / "NemoDoc.ps1").read_text(encoding="utf-8")
                break
        else:
            self.skipTest("NemoDoc.ps1 not in this layout")
        block = text[text.index("$SdCudaFiles = @("):text.index("$SdCudaFiles = @(") + 600]
        pinned = set(re.findall(r'file = "([^"]+)"; sha256 = "([0-9a-f]{64})"; bytes = (\d+)', block))
        self.assertEqual(pinned, {(f, h, str(b)) for f, b, h in artist.SD_CUDA})


class TestTheArtistIsStaff(unittest.TestCase):
    def test_it_draws_concepts_and_covers(self):
        # Two departments, two Artists (2026-10-21): concepts in the Art
        # Studio, story covers in the Library.
        self.assertEqual(staff.STAFF["art_studio.artist"].steps, ("concept",))
        self.assertIn("cover", staff.STAFF["library.artist"].job)
        self.assertEqual(staff.STAFF["library.artist"].steps, ())


if __name__ == "__main__":
    unittest.main()
