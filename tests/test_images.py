"""Image tools: panel prompts from the bible, and renders of the real STL."""
from __future__ import annotations

import io, json, os, struct, sys, tempfile, unittest, zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import


try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:                                   # pragma: no cover
    HAVE_NUMPY = False

STYLE = "Ink and watercolour, muted palette"


def tmp() -> Path:
    return Path(tempfile.mkdtemp())


# ====================================================================


# ====================================================================
def decode_png(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "signature"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        crc = struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0]
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, f"bad CRC in {tag}"
        if tag == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
            assert body[8:] == b"\x08\x02\x00\x00\x00"
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    assert len(raw) == h * (1 + w * 3), "scanline data has the wrong length"
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(h, 1 + w * 3)
    assert (rows[:, 0] == 0).all()
    return rows[:, 1:].reshape(h, w, 3)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed (optional cad extra)")
class TestRender(unittest.TestCase):
    def setUp(self):
        from nemo import render
        self.R = render
        self.d = tmp()
        render.box_stl(self.d / "box.stl", 40, 20, 10)
        self.tris = render.read_stl(self.d / "box.stl")

    def drawn(self, view):
        im = self.R.render_view(self.tris, view, 480)
        m = np.abs(im.astype(int) - np.array(self.R.BACKGROUND)).sum(2) > 12
        ys, xs = np.nonzero(m)
        return xs.max() - xs.min() + 1, ys.max() - ys.min() + 1

    def test_orthographic_views_have_the_true_proportions(self):
        # Independent of shading: a 40 x 20 x 10 box.
        for view, want in (("top", 2.0), ("front", 4.0), ("right", 2.0)):
            w, h = self.drawn(view)
            self.assertAlmostEqual(w / h, want, delta=want * 0.02, msg=view)

    def test_ascii_and_binary_stl_read_the_same(self):
        self.R.box_stl(self.d / "a.stl", 40, 20, 10, binary=False)
        self.assertTrue(np.allclose(self.R.read_stl(self.d / "a.stl"), self.tris))

    def test_the_same_file_always_gives_the_same_bytes(self):
        a = self.R.render_stl(self.d / "box.stl", self.d / "a", size=200)
        b = self.R.render_stl(self.d / "box.stl", self.d / "b", size=200)
        for fa, fb in zip(a.files, b.files):
            self.assertEqual(fa.read_bytes(), fb.read_bytes(), fa.name)

    def test_outputs_are_valid_pngs_of_the_stated_size(self):
        r = self.R.render_stl(self.d / "box.stl", self.d / "o", size=200)
        by = {f.name: decode_png(f.read_bytes()) for f in r.files}
        self.assertEqual(by["enclosure-iso.png"].shape, (200, 200, 3))
        self.assertEqual(by["enclosure-sheet.png"].shape, (400, 400, 3))

    def test_views_differ_from_each_other(self):
        ims = {v: self.R.render_view(self.tris, v, 120) for v in ("iso", "top", "front")}
        self.assertFalse(np.array_equal(ims["iso"], ims["top"]))
        self.assertFalse(np.array_equal(ims["top"], ims["front"]))

    def _tray(self):
        W, D, H, w = 60, 40, 20, 2
        q = lambda a, b, c, d: [(a, b, c), (a, c, d)]
        t = []
        t += q((0, 0, 0), (W, 0, 0), (W, D, 0), (0, D, 0))
        t += q((0, 0, 0), (W, 0, 0), (W, 0, H), (0, 0, H)); t += q((0, D, 0), (W, D, 0), (W, D, H), (0, D, H))
        t += q((0, 0, 0), (0, D, 0), (0, D, H), (0, 0, H)); t += q((W, 0, 0), (W, D, 0), (W, D, H), (W, 0, H))
        t += q((w, w, w), (W - w, w, w), (W - w, D - w, w), (w, D - w, w))
        t += q((w, w, w), (W - w, w, w), (W - w, w, H), (w, w, H)); t += q((w, D - w, w), (W - w, D - w, w), (W - w, D - w, H), (w, D - w, H))
        t += q((w, w, w), (w, D - w, w), (w, D - w, H), (w, w, H)); t += q((W - w, w, w), (W - w, D - w, w), (W - w, D - w, H), (W - w, w, H))
        t += q((0, 0, H), (W, 0, H), (W - w, w, H), (w, w, H)); t += q((0, D, H), (W, D, H), (W - w, D - w, H), (w, D - w, H))
        t += q((0, 0, H), (0, D, H), (w, D - w, H), (w, w, H)); t += q((W, 0, H), (W, D, H), (W - w, D - w, H), (W - w, w, H))
        return np.array(t, dtype=float)

    def test_a_well_formed_tray_has_no_stray_slivers(self):
        # A rim quad with its corners in the wrong order (a bow-tie) once left a
        # jagged spike in a test render. The renderer draws what the file holds,
        # so the fixture itself must be sound: the right and left rims must match.
        im = self.R.render_view(self._tray(), "top", 400).astype(int)
        h, w, _ = im.shape
        left, right = im[:, : w // 2], im[:, w // 2:][:, ::-1]
        self.assertLess(np.abs(left - right).mean(), 0.05)     # exact for a sound mesh; the bow-tie scored 0.42

    def test_an_open_tray_looks_hollow_from_above(self):
        # The floor and the rim face the same way, so brightness alone cannot
        # tell them apart; depth must. A first version drew a solid rectangle.
        im = self.R.render_view(self._tray(), "top", 400).astype(int)
        h, w, _ = im.shape
        centre = im[h // 2, w // 2].sum()
        rim = im[h // 2, int(w * 0.075):int(w * 0.075) + 2].sum()   # the 2 mm rim, left edge
        self.assertGreater(rim - centre, 40)

    def test_the_tray_is_hollow_and_solid_isnt_in_the_iso_view(self):
        tray = self.R.render_view(self._tray(), "iso", 300)
        self.assertGreater(len(np.unique(tray.reshape(-1, 3), axis=0)), 8)

    def test_flipped_normals_are_not_drawn_black(self):
        flipped = self.tris[:, ::-1, :]
        im = self.R.render_view(flipped, "iso", 200)
        covered = np.abs(im.astype(int) - np.array(self.R.BACKGROUND)).sum(2) > 12
        self.assertGreater(im[covered].mean(), 60)

    def test_degenerate_triangles_do_not_break_it(self):
        t = np.concatenate([self.tris, np.zeros((3, 3, 3))])
        self.assertEqual(self.R.render_view(t, "iso", 100).shape, (100, 100, 3))

    def test_report_gives_the_extent_and_the_envelope_verdict(self):
        ok = self.R.render_stl(self.d / "box.stl", self.d / "ok", size=100, envelope_mm=[50, 30, 15])
        self.assertIn("40.0 x 20.0 x 10.0 mm", ok.report); self.assertIn("yes", ok.report)
        no = self.R.render_stl(self.d / "box.stl", self.d / "no", size=100, envelope_mm=[45, 30, 8])
        self.assertIn("NO, over by", no.report)
        self.assertTrue((self.d / "no" / "enclosure-render.txt").exists())

    def test_errors_are_sentences(self):
        R = self.R
        with self.assertRaisesRegex(R.RenderError, "does not exist"):
            R.render_stl(self.d / "nope.stl", self.d / "x")
        (self.d / "junk.stl").write_bytes(b"not an stl " * 20)
        with self.assertRaisesRegex(R.RenderError, "not a readable STL"):
            R.read_stl(self.d / "junk.stl")
        (self.d / "short.stl").write_bytes(b"x" * 10)
        with self.assertRaisesRegex(R.RenderError, "too short"):
            R.read_stl(self.d / "short.stl")
        with self.assertRaisesRegex(R.RenderError, "Unknown view"):
            R.render_view(self.tris, "sideways")
        (self.d / "empty.stl").write_bytes(b"\0" * 80 + struct.pack("<I", 0))
        with self.assertRaises(R.RenderError):
            R.render_stl(self.d / "empty.stl", self.d / "x")

    def test_a_truncated_binary_stl_is_refused_not_misread(self):
        data = (self.d / "box.stl").read_bytes()[:-30]
        (self.d / "cut.stl").write_bytes(data)
        with self.assertRaises(self.R.RenderError):
            self.R.read_stl(self.d / "cut.stl")


class TestRenderWithoutNumpy(unittest.TestCase):
    def test_a_missing_numpy_is_an_install_hint_not_a_traceback(self):
        from nemo import render
        real = __import__

        def fake(name, *a, **k):
            if name == "numpy":
                raise ImportError("no numpy")
            return real(name, *a, **k)
        with mock.patch("builtins.__import__", fake):
            with self.assertRaisesRegex(render.RenderError, "pip install numpy"):
                render.read_stl(Path("x.stl"))


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class TestRenderCommand(unittest.TestCase):
    def run_cli(self, *a):
        from nemo import cli
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(list(a))
        return rc, out.getvalue()

    def test_render_a_stl_and_the_failures(self):
        from nemo.render import box_stl
        d = tmp()
        box_stl(d / "h.stl", 82, 52, 31)
        rc, out = self.run_cli("render", "--stl", str(d / "h.stl"), "--views", "iso,top", "--size", "120")
        self.assertEqual(rc, 0); self.assertIn("82.0 x 52.0 x 31.0", out)
        self.assertTrue((d / "renders" / "enclosure-sheet.png").exists())
        rc, out = self.run_cli("render", "--stl", str(d / "none.stl"))
        self.assertEqual(rc, 1); self.assertIn("does not exist", out)
        rc, out = self.run_cli("render", "--stl", str(d / "h.stl"), "--views", "bogus")
        self.assertEqual(rc, 1); self.assertIn("Unknown view", out)

    def test_render_a_project_uses_its_brief_envelope(self):
        from nemo.gui import controller as C
        from nemo.project import Brief
        from nemo.render import box_stl
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home, "NEMO_HOME": home + "/.nemo"}):
            p = C.create_project("Box")
            p.save_brief(Brief(name="Box", envelope_mm=[60, 40, 20]))
            p.housing_stl.parent.mkdir(parents=True, exist_ok=True)
            box_stl(p.housing_stl, 82, 52, 31)
            rc, out = self.run_cli("--project", p.root.name, "render", "--size", "100")
            self.assertEqual(rc, 0); self.assertIn("NO, over by", out)
            rc, out = self.run_cli("--project", "does-not-exist", "render")
            self.assertEqual(rc, 1)

    def test_renders_show_up_in_the_files_tab_list(self):
        from nemo.gui import controller as C
        from nemo.render import box_stl
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home, "NEMO_HOME": home + "/.nemo"}):
            p = C.create_project("Box2")
            box_stl(p.housing_stl.parent.mkdir(parents=True, exist_ok=True) or p.housing_stl, 10, 10, 5)
            self.run_cli("--project", p.root.name, "render", "--size", "80")
            names = [f.name for g, f in C.project_files(p)]
            self.assertIn("enclosure-sheet.png", names); self.assertIn("enclosure-render.txt", names)


@unittest.skipUnless(HAVE_NUMPY and _sandbox.has_display(), "needs numpy and a display")
class TestHousingDialog(unittest.TestCase):
    def test_view_the_housing_opens_a_dialog_with_the_image(self):
        from nemo.gui import controller as C
        from nemo.render import box_stl
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home, "NEMO_HOME": home + "/.nemo"}):
            p = C.create_project("Box3")
            p.housing_stl.parent.mkdir(parents=True, exist_ok=True)
            box_stl(p.housing_stl, 60, 40, 20)
            from nemo.gui.app import NemoApp, RenderDialog
            app = NemoApp(); app.update()
            try:
                app.refresh_projects(select=p.root.name); app.update()
                app.view_housing(); app.update()
                import time
                end = time.time() + 15
                dlgs = []
                while time.time() < end and not dlgs:          # drawn in a worker thread
                    app.update(); time.sleep(0.05)
                    dlgs = [w for w in app.winfo_children() if isinstance(w, RenderDialog)]
                self.assertEqual(len(dlgs), 1)
                self.assertGreater(dlgs[0].img.width(), 300)
                # It must fit a 1366x768 screen with room for a taskbar: the
                # first version was 844 px tall and its buttons fell off it.
                dlgs[0].update_idletasks()
                self.assertLessEqual(dlgs[0].winfo_reqheight(), 700)
                self.assertLessEqual(dlgs[0].winfo_reqwidth(), 1000)
            finally:
                app.destroy()

    def test_the_window_stays_alive_while_a_slow_render_runs(self):
        # A detailed housing takes tens of seconds on the target. Drawing it
        # on the UI thread froze the window for all of that.
        import time
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home, "NEMO_HOME": home + "/.nemo"}):
            from nemo.gui import controller as C
            from nemo.render import box_stl
            p = C.create_project("Slow")
            p.housing_stl.parent.mkdir(parents=True, exist_ok=True)
            box_stl(p.housing_stl, 20, 20, 10)

            from nemo.render import render_stl as real     # before patching: not the patched name

            def slow(stl, out, *a, **k):
                time.sleep(1.2)
                return real(stl, out, size=80)
            from nemo.gui.app import NemoApp
            app = NemoApp(); app.update()
            try:
                app.refresh_projects(select=p.root.name); app.update()
                ticks = []
                with mock.patch("nemo.render.render_stl", slow):
                    app.view_housing()
                    self.assertTrue(app._rendering)
                    t0 = time.time()
                    while time.time() - t0 < 0.9:
                        app.after(50, lambda: ticks.append(1)); app.update(); time.sleep(0.03)
                    still_running = app._rendering
                    end = time.time() + 10
                    while app._rendering and time.time() < end:
                        app.update(); time.sleep(0.05)
                self.assertTrue(still_running, "the render should still be running")
                self.assertGreater(len(ticks), 5, "UI events were not processed during the render")
                self.assertFalse(app._rendering)
            finally:
                app.destroy()

    def test_no_stl_is_explained_not_crashed(self):
        from nemo.gui import controller as C
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home, "NEMO_HOME": home + "/.nemo"}):
            p = C.create_project("Box4")
            from nemo.gui.app import NemoApp, RenderDialog
            app = NemoApp(); app.update()
            try:
                app.refresh_projects(select=p.root.name); app.update()
                app.view_housing()
                import time
                end = time.time() + 1.0
                while time.time() < end:
                    app.update(); time.sleep(0.05)
                self.assertFalse([w for w in app.winfo_children() if isinstance(w, RenderDialog)])
                self.assertFalse(app._rendering)
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
