import math
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import nif, sfmesh, skyrimlod, skyrimsea as sea  # noqa: E402


class DistantSea(unittest.TestCase):
    def test_layout_covers_the_overlay(self):
        t, k, x0 = sea.tile_layout(-36, 36)
        self.assertEqual((k, x0), (10, -3600.0))
        self.assertAlmostEqual(t * k, 7300.0)
        ps = sea.pieces(-36, 36, 20000)
        self.assertEqual(len(ps), 100 + 40 + 4)
        for _kind, (x, y), _rz in ps:                   # every reference sits inside the overlay's cells
            self.assertTrue(-36 <= math.floor(x / 100) <= 36 and -36 <= math.floor(y / 100) <= 36)

    def test_quads_face_up_and_tile_uvs(self):
        pos, uv, tris = sea.quads(0, 730, 0, 730, 5.0, 365)
        self.assertEqual((len(pos), len(tris)), (16, 8))
        for a, b, c in tris:                            # counter-clockwise seen from above: +z cross product
            (ax, ay, _), (bx, by, _), (cx, cy, _) = pos[a], pos[b], pos[c]
            self.assertGreater((bx - ax) * (cy - ay) - (by - ay) * (cx - ax), 0)
        self.assertTrue(all(float(u).is_integer() and float(v).is_integer() for u, v in uv))
        self.assertLessEqual(max(max(u, v) for u, v in uv), 30)

    def test_add_writes_models_and_refs_and_rerun_replaces(self):
        objects = {"bases": [{"edid": "SKY_Rock", "model": "skyrim\\rock.nif"}],
                   "refs": [{"src": "x", "base": 0, "cell": [0, 0], "pos": [1, 2, 3], "rot": [0, 0, 0], "scale": 1}]}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sea, "write_material", return_value="materials\\skyrim\\distantsea\\sea.mat"):
            st = sea.add(objects, d, -36, 36, -15.0, "cr.zip", "texconv.exe")
            self.assertEqual(st["pieces"], 144)
            self.assertAlmostEqual(st["z"], -15.3)
            self.assertEqual(len(objects["bases"]), 4)
            corner = objects["bases"][3]
            self.assertGreater(corner["bounds"][1][0] - corner["bounds"][0][0], 19000)
            shapes, _r = skyrimlod.load_model(d, corner["model"])          # the lod step can read it back
            self.assertEqual(len(shapes), 1)
            f = nif.parse(open(os.path.join(d, "meshes", *corner["model"].split("\\")), "rb").read())
            self.assertEqual(f.type_of(2), "BSGeometry")
            sea.add(objects, d, -36, 36, -15.0, "cr.zip", "texconv.exe")   # rerun: replaced, not doubled
            self.assertEqual((len(objects["bases"]), len(objects["refs"])), (4, 145))
            self.assertEqual(sea.remove(objects), 3)
            self.assertEqual(objects["refs"], [{"src": "x", "base": 0, "cell": [0, 0], "pos": [1, 2, 3],
                                                "rot": [0, 0, 0], "scale": 1}])

    def test_wave_normals_tile(self):
        r, g = sea.wave_normals(64)
        self.assertEqual(r.shape, (64, 64))
        self.assertLess(abs(int(r[0, 0]) - int(r[0, -1])), 40)           # continuous across the wrap


if __name__ == "__main__":
    unittest.main()
