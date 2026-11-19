"""The Art Studio's relief: a printable panel raised from a picture (nemo/relief.py;
owner, 2026-11-18, after "a 3d sculpture of mona lisa")."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _sandbox; _sandbox.activate()   # D112: before any nemo import

try:
    import numpy as np
    from PIL import Image
except ImportError:                                  # pragma: no cover
    np = None

from nemo import asks, relief


class Cfg:
    def __init__(self, root: Path, min_wall=1.2):
        self.root, self.min_wall = Path(root), min_wall

    def get(self, key, default=None):
        return {"hardware.min_wall_mm": self.min_wall,
                "hardware.build_volume_mm": [250, 250, 260]}.get(key, default)

    def path(self, key):
        return self.root / {"paths.models": "models", "paths.storeroom": "storeroom"}[key]


def picture(path: Path, size=(40, 60), left=0, right=255):
    """A picture: its left half `left` grey, its right half `right` grey."""
    a = np.full((size[1], size[0]), left, dtype=np.uint8)
    a[:, size[0] // 2:] = right
    Image.fromarray(a).save(path)
    return path


@unittest.skipIf(np is None, "needs numpy and Pillow")
class TestRelief(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = Cfg(self.root)
        self.shelf = self.root / "storeroom" / "pictures"
        self.shelf.mkdir(parents=True)

    def test_a_picture_is_found_on_the_shelf_never_fetched(self):
        a = picture(self.shelf / "Mona Lisa.png")
        picture(self.shelf / "lighthouse at night.jpg")
        self.assertEqual(relief.find_picture(self.cfg, "mona lisa"), a)
        self.assertEqual(relief.find_picture(self.cfg, "Mona Lisa.png"), a)
        self.assertEqual(relief.find_picture(self.cfg, str(a)), a)          # a path
        with self.assertRaises(relief.ReliefError) as e:
            relief.find_picture(self.cfg, "girl with a pearl earring")
        self.assertIn("never downloads", str(e.exception))
        self.assertIn("Mona Lisa", str(e.exception))                        # what is there
        picture(self.shelf / "lighthouse by day.png")
        with self.assertRaises(relief.ReliefError) as e:
            relief.find_picture(self.cfg, "lighthouse")
        self.assertIn("2 pictures match", str(e.exception))

    def test_sizes_are_held_to_the_rules(self):
        pic = picture(self.root / "p.png")
        with self.assertRaises(relief.ReliefError):
            relief.plan(pic, mode="statue")
        with self.assertRaises(relief.ReliefError) as e:
            relief.plan(pic, base_mm=0.8, min_wall_mm=1.2)
        self.assertIn("least wall", str(e.exception))
        with self.assertRaises(relief.ReliefError):
            relief.plan(pic, width_mm=5)
        with self.assertRaises(relief.ReliefError) as e:
            relief.plan(pic, width_mm=400, pitch_mm=0.2)
        self.assertIn("too many", str(e.exception))
        p = relief.plan(pic, width_mm=60, pitch_mm=0.5)
        self.assertEqual((p.width_mm, p.cols), (60.0, 121))                 # exactly as asked
        self.assertAlmostEqual(p.height_mm, 90.0, delta=0.5)                # the picture's shape

    def test_light_stands_up_in_a_relief_and_is_thin_in_a_lithophane(self):
        pic = picture(self.root / "p.png", size=(80, 40), left=0, right=255)
        z = relief.heights(relief.plan(pic, width_mm=40, pitch_mm=0.5))
        mid = z.shape[0] // 2
        dark, light = z[mid, 12], z[mid, -12]
        self.assertAlmostEqual(dark, relief.BASE_MM, delta=0.05)
        self.assertAlmostEqual(light, relief.BASE_MM + relief.DEPTH_MM, delta=0.05)
        z = relief.heights(relief.plan(pic, mode="lithophane", width_mm=40, pitch_mm=0.5))
        self.assertGreater(z[mid, 12], z[mid, -12])                         # dark is thick
        self.assertAlmostEqual(z[mid, -12], relief.LITHO_THIN_MM, delta=0.05)
        self.assertTrue(np.allclose(z[0, :], z.max()))                      # the flat rim

    def test_the_mesh_is_one_closed_solid(self):
        pic = picture(self.root / "p.png", size=(30, 20))
        tris = relief.triangles(relief.heights(relief.plan(pic, width_mm=20, pitch_mm=1)), 1.0)
        # every edge is used exactly twice, once each way: closed and consistently wound
        edges = {}
        for t in np.round(tris.astype(float), 4):
            for a, b in ((0, 1), (1, 2), (2, 0)):
                k = (tuple(t[a]), tuple(t[b]))
                edges[k] = edges.get(k, 0) + 1
        self.assertTrue(all(n == 1 for n in edges.values()))
        self.assertTrue(all((b, a) in edges for a, b in edges))
        # signed volume > 0: the faces point outward
        v = np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6
        self.assertGreater(v, 0)

    def test_made_and_checked_as_any_model(self):
        picture(self.shelf / "Mona Lisa.png", size=(60, 90))
        out, results = relief.make(self.cfg, "Mona Lisa Relief", "mona lisa", width_mm=40,
                                   pitch_mm=1.0, say=lambda m: None)
        self.assertEqual(out.name, "mona-lisa-relief")
        self.assertTrue((out / "model.stl").is_file())
        status = {r.name: r.status for r in results}
        self.assertEqual(status["model_made"], "PASS")
        self.assertEqual(status["size_as_asked"], "PASS")
        self.assertEqual(status["fits_printer"], "PASS")
        self.assertIn(status["solid"], ("PASS", "SKIP"))                    # SKIP: no trimesh
        from nemo import modelkit, printshop
        listed = {m["name"]: m for m in modelkit.models(self.cfg)}
        self.assertEqual(listed["Mona Lisa Relief"]["kind"], "relief")
        with mock.patch.object(self.cfg, "path", side_effect=lambda k: self.root / (
                "models" if k == "paths.models" else "projects")):
            self.assertIn("mona-lisa-relief", [m.name for m in printshop.models(self.cfg)])

    def test_the_art_studio_takes_the_words(self):
        r = asks.answer("art_studio", "a relief of mona lisa 150 mm wide")
        self.assertEqual(r.argv, ["model", "relief", "mona lisa", "width=150"])
        r = asks.answer("art_studio", "make a lithophane of the lighthouse")
        self.assertEqual(r.argv, ["model", "relief", "lighthouse", "mode=lithophane"])
        r = asks.answer("art_studio", "make a 3d sculpture of mona lisa")
        self.assertEqual(r.kind, asks.SAY)
        self.assertIn("'a relief of mona lisa'", r.say)

    def test_the_command(self):
        from nemo import cli
        picture(self.shelf / "Mona Lisa.png", size=(60, 90))
        with mock.patch.object(cli.Config, "load", return_value=self.cfg), \
                mock.patch.object(cli, "_send_finished"):
            self.assertEqual(cli.main(["model", "relief", "mona lisa", "colour=red"]), 2)
            self.assertEqual(cli.main(["model", "relief", "nothing like it"]), 1)
            self.assertEqual(cli.main(["model", "relief", "mona lisa", "width=30", "pitch=1"]), 0)
        self.assertTrue((self.root / "models" / "mona-lisa-relief" / "model.stl").is_file())


if __name__ == "__main__":
    unittest.main()
