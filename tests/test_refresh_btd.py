"""scripts/terrain/refresh_btd.py (2026-11-21): the staged exterior's BTDs take a fresh build's texture layers, their
heights kept exactly; the rebuild reruns the staging's own build command with the blend options last."""
import os
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import btd  # noqa: E402
import refresh_btd as R  # noqa: E402


def make(heights_seed, weight_val, table=(0x10, 0x20)):
    rng = np.random.default_rng(heights_seed)
    h = rng.integers(0, 65535, (128, 128), dtype=np.uint16)
    w = np.full((128, 128), weight_val, np.uint16)
    q = np.zeros((2, 2, 8), np.uint8)
    q[..., 0], q[..., 1] = 2, 1
    return btd.write(btd.Btd(6, -10.0, 50.0, list(table), h, w, q))


class SpliceTest(unittest.TestCase):
    def test_heights_kept_textures_taken(self):
        old, new = make(1, 0), make(2, 7)
        data, why = R.splice_one(old, new)
        self.assertIsNone(why)
        got, o, n = btd.read(data), btd.read(old), btd.read(new)
        np.testing.assert_array_equal(got.heights_raw, o.heights_raw)
        self.assertEqual((got.hmin, got.hmax), (o.hmin, o.hmax))
        np.testing.assert_array_equal(got.weights, n.weights)
        np.testing.assert_array_equal(got.quad_map, n.quad_map)
        _d, why = R.splice_one(old, make(2, 7, table=(0x10, 0x30)))
        self.assertIn("LTEX table differs", why)

    def test_splice_folders_and_rebuild_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            st, fr = os.path.join(tmp, "staging"), os.path.join(tmp, "fresh")
            for root, data in ((st, make(1, 0)), (fr, make(2, 7))):
                for rel in (("Data", "Terrain", "W.btd"), ("Data", "meshes", "Terrain", "W.btd")):
                    p = os.path.join(root, *rel)
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "wb") as fh:
                        fh.write(data)
            only = os.path.join(st, "Data", "Terrain", "Other.btd")
            with open(only, "wb") as fh:
                fh.write(make(3, 0))
            from types import SimpleNamespace
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(R.cmd_splice(SimpleNamespace(staging=st, fresh=fr, dry_run=False)), 0)
            self.assertIn("spliced 2 of 3 BTDs", out.getvalue())
            got = btd.read(open(os.path.join(st, "Data", "Terrain", "W.btd"), "rb").read())
            self.assertEqual(int(got.weights.max()), 7)
            np.testing.assert_array_equal(got.heights_raw, btd.read(make(1, 0)).heights_raw)
            with open(os.path.join(st, "build_command.txt"), "w") as fh:
                fh.write('C:\\Python\\python.exe C:\\repo\\scripts\\terrain\\make_skyrim_overlay.py build --skyrim '
                         '"C:\\Games\\Sky Data\\Skyrim.esm" --out C:\\Modding\\staging\\skyrim_all --ltex-blend solid\n')
            args = R.build_args(st, "C:\\fresh", "noise", 3.5)
            self.assertEqual(args[:3], ["build", "--skyrim", "C:\\Games\\Sky Data\\Skyrim.esm"])
            self.assertEqual(args[-6:], ["--out", "C:\\fresh", "--ltex-blend", "noise", "--ltex-warp", "3.5"])


if __name__ == "__main__":
    unittest.main()
