"""Synthetic-fixture tests for Skyrim grass (src/fo4sf/skyrimgrass.py, make_skyrim_objects.py grass). No game data."""
import contextlib
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import nif, skyrimgrass, textures  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402


def gras_data(density=100, min_slope=0, max_slope=90, from_water=0, pos_range=0.0, height_range=0.0, flags=0):
    return struct.pack("<BBBBHHIffffB3x", density, min_slope, max_slope, 0, from_water, 0, 0, pos_range,
                       height_range, 0.0, 0.0, flags)


def plugin(path):
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800))])
    ltex = [rec(b"LTEX", 0x10, [(b"EDID", b"LGrass\0"), (b"GNAM", struct.pack("<I", 0x20)),
                                (b"GNAM", struct.pack("<I", 0x21))]),
            rec(b"LTEX", 0x11, [(b"EDID", b"LDirt\0")])]
    gras = [rec(b"GRAS", 0x20, [(b"EDID", b"FieldGrass01\0"), (b"MODL", b"Landscape\\Grass\\Grass01.nif\0"),
                                (b"DATA", gras_data(60, 0, 40, 0, 32.0, 0.5, 2))]),
            rec(b"GRAS", 0x21, [(b"EDID", b"NoModel\0"), (b"DATA", gras_data())])]
    with open(path, "wb") as f:
        f.write(tes4 + grup(b"LTEX", 0, ltex) + grup(b"GRAS", 0, gras))
    return path


class ReadTests(unittest.TestCase):
    def test_ltex_grass_and_gras_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            lg, gr = skyrimgrass.read_grass(plugin(os.path.join(tmp, "Skyrim.esm")))
        self.assertEqual(lg, {0x10: [0x20, 0x21]})
        self.assertEqual(set(gr), {0x20})                       # a GRAS without a model is left out
        g = gr[0x20]
        self.assertEqual((g["edid"], g["model"], g["density"], g["max_slope"]),
                         ("FieldGrass01", "Landscape\\Grass\\Grass01.nif", 60, 40))
        self.assertAlmostEqual(g["position_range"], 32.0)
        self.assertEqual(g["flags"], 2)
        with self.assertRaises(ValueError):
            skyrimgrass.parse_gras_data(b"\0" * 8)


class ScatterTests(unittest.TestCase):
    LG = {1: [5]}

    def gras(self, **k):
        return {5: dict(skyrimgrass.parse_gras_data(gras_data(**k)), model="g.nif", edid="G")}

    def test_full_density_fills_the_grid(self):
        w = {1: np.ones((33, 33))}
        got = skyrimgrass.scatter(w, np.zeros((33, 33)), self.LG, self.gras(), 512.0, np.random.default_rng(0))
        self.assertEqual(len(got), 64)                          # 4096 / 512 = 8 x 8 candidates, all kept
        self.assertTrue(all(0 <= x <= 4096 and 0 <= y <= 4096 and z == 0.0 for _g, x, y, z, _r, _s in got))

    def test_density_texture_water_and_slope(self):
        rng = np.random.default_rng(1)
        flat = np.zeros((33, 33))
        self.assertEqual(skyrimgrass.scatter({1: np.ones((33, 33))}, flat, self.LG, self.gras(density=0), 512.0, rng), [])
        self.assertEqual(skyrimgrass.scatter({2: np.ones((33, 33))}, flat, self.LG, self.gras(), 512.0, rng), [])
        self.assertEqual(skyrimgrass.scatter({1: np.ones((33, 33))}, flat, self.LG, self.gras(), 512.0, rng,
                                             water=100.0), [])  # under the cell's water
        steep = np.tile(np.arange(33) * 128.0, (33, 1))         # 45 degrees
        self.assertEqual(skyrimgrass.scatter({1: np.ones((33, 33))}, steep, self.LG, self.gras(max_slope=30), 512.0,
                                             rng), [])
        self.assertEqual(len(skyrimgrass.scatter({1: np.ones((33, 33))}, steep, self.LG, self.gras(max_slope=60),
                                                 512.0, rng)), 64)

    def test_half_painted_texture_grows_on_its_half(self):
        w1 = np.zeros((33, 33)); w1[:, :16] = 1.0             # west half
        w = {1: w1, 2: 1.0 - w1}
        got = skyrimgrass.scatter(w, np.zeros((33, 33)), self.LG, self.gras(), 256.0, np.random.default_rng(2))
        self.assertTrue(got)
        self.assertLess(max(x for _g, x, _y, _z, _r, _s in got), 2200)


class MergeTests(unittest.TestCase):
    def shape(self):
        return nif.Fo4Shape(b"G", (10.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 2.0, 0, -1, -1,
                            [(0, 0, 0), (1, 0, 0), (0, 0, 1)], [(0, 0), (1, 0), (0, 1)], [(0, 1, 0)] * 3,
                            [(1, 0, 0)] * 3, [(255, 255, 255, 255)] * 3, [(0, 1, 2)], False)

    def test_instances_are_transformed_and_chunked(self):
        inst = [(100.0, 0.0, 5.0, 0.0, 1.0), (0.0, 100.0, 5.0, math.pi / 2, 0.5), (0.0, 0.0, 5.0, 0.0, 1.0)]
        got = skyrimgrass.instance_shapes([self.shape()], inst, (0.0, 0.0, 5.0), 6)
        self.assertEqual(len(got), 2)                           # 3 vertices each, 6 per shape: 2 + 1 instances
        a = got[0][1]
        self.assertEqual(len(a.positions), 6)
        self.assertEqual(a.triangles, [(0, 1, 2), (3, 4, 5)])
        self.assertEqual(a.translation, (0.0, 0.0, 0.0))
        np.testing.assert_allclose(a.positions[1], (112.0, 0.0, 0.0))            # (1*2 + 10) + instance x 100
        np.testing.assert_allclose(a.positions[4], (0.0, 106.0, 0.0), atol=1e-9)  # yaw 90 deg, scale 0.5
        np.testing.assert_allclose(a.normals[3], (-1.0, 0.0, 0.0), atol=1e-9)
        self.assertEqual(len(got[1][1].positions), 3)

    def test_vertex_colour(self):
        vc = np.zeros((33, 33, 3), np.uint8)
        vc[:, 16:] = (255, 128, 0)                              # east half
        np.testing.assert_allclose(skyrimgrass.vertex_colour(vc, 4000.0, 100.0), (1.0, 128 / 255, 0.0))
        np.testing.assert_allclose(skyrimgrass.vertex_colour(vc, 0.0, 0.0), (0.0, 0.0, 0.0))

    def test_patch_stem(self):
        self.assertEqual(skyrimgrass.patch_stem(-3, 7, "Landscape\\Grass\\FieldGrass01.nif"), "cm3_7_fieldgrass01")


class CommandTests(unittest.TestCase):
    def test_grass_then_stage_adds_patches(self):
        import make_cw_overlays as cw
        import make_skyrim_objects as so
        import make_skyrim_overlay as sk
        import skyrim_fixtures as F
        import test_skyrim_objects as T
        lg = {0x77: [0x88]}
        gr = {0x88: dict(skyrimgrass.parse_gras_data(gras_data(100)), edid="Fern",
                         model="landscape\\plants\\fern01.nif")}
        with tempfile.TemporaryDirectory() as tmp, T.starfield_inputs(tmp) as sf, \
                mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([0, 0, 0, 0, 0, 0, 0, 1]))), \
                mock.patch.object(skyrimgrass, "read_grass", return_value=(lg, gr)), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            esm = T.write_esm(os.path.join(tmp, "Skyrim.esm"))
            data = F.skyrim_data(os.path.join(tmp, "Data"))
            terrain, work, out = (os.path.join(tmp, d) for d in ("terrain", "work", "out"))
            sk.main(["build", "--skyrim", esm, "--sf-data", tmp, "--out", terrain, "--mask-writer", "builtin",
                     "--arrival", ""])
            so.main(["export", "--skyrim", esm, "--work", work])
            so.main(["select", "--work", work, "--terrain", terrain])
            texconv = os.path.join(tmp, "texconv.exe")
            with open(texconv, "wb") as f:
                f.write(b"MZ")
            so.main(["convert", "--work", work, "--skyrim-data", data, "--content-resources", sf["content_resources"],
                     "--texconv", texconv, "--collision-template", sf["collision_template"]])
            from fo4sf import landtex
            weights = {(0, 0): {0x77: np.ones((33, 33))}}
            with mock.patch.object(landtex, "read_world_textures", return_value=(weights, {})):
                so.main(["grass", "--work", work, "--terrain", terrain, "--skyrim", esm, "--skyrim-data", data,
                         "--content-resources", sf["content_resources"], "--texconv", texconv, "--around", "0,0",
                         "--radius", "0", "--grass-spacing", "8"])
            g = json.load(open(os.path.join(work, "grass", "grass.json")))
            so.main(["stage", "--work", work, "--terrain", terrain, "--out", out])
            ok, rep = so.check(out)
            obj = json.load(open(os.path.join(out, "objects.json")))
        self.assertTrue(ok, [c for c in rep["checks"] if not c[1]])
        self.assertEqual(len(g["refs"]), 1, (g["failed"], log.getvalue()[-1500:]))   # one cell, one model: one patch
        self.assertGreater(g["instances"]["landscape\\plants\\fern01.nif"], 10)
        patch = obj["bases"][-1]
        self.assertTrue(patch["edid"].startswith("SKY_Grass_c0_0_fern01"))
        self.assertEqual(patch["collision"], "none")
        r = obj["refs"][-1]
        self.assertEqual(r["base"], len(obj["bases"]) - 1)
        self.assertAlmostEqual(r["pos"][0], 2048 / 70, places=3)   # the cell's centre
        self.assertIn("grass: 1 patches", log.getvalue())


if __name__ == "__main__":
    unittest.main()
