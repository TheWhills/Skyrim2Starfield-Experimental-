"""Synthetic-fixture tests for ground textures: Skyrim LAND layers -> Starfield BTD layers. No game data."""
import contextlib
import io
import json
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
from fo4sf import btd, landtex  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402
from test_skyrimland import cell_vhgt  # noqa: E402

DIRT, GRASS, SNOW, ROAD = 0x0C01, 0x0C02, 0x0C03, 0x0C04
SF = {"LDirtFootprints01": 0x001235C2, "LGrassMeadow01": 0x00200001, "LSnowDeep01": 0x00200002,
      "LRockCliff01": 0x00200003, "LGravelPath01": 0x00200004, "LSandBeach01": 0x00200005}
EXTENT = (-6, 5, -4, 4)


def btxt(fid, quad):
    return (b"BTXT", struct.pack("<IBBh", fid, quad, 0, -1))


def atxt(fid, quad, layer, ops):
    """ops: {(row, col) in 17 x 17: opacity}"""
    return [(b"ATXT", struct.pack("<IBBH", fid, quad, 0, layer)),
            (b"VTXT", b"".join(struct.pack("<HHf", r * 17 + c, 0, v) for (r, c), v in sorted(ops.items())))]


def cell_textures(x, y):
    """West half dirt, east half grass; cell (-1, -1) quadrant NE (3) fully snow; cell (0, 0) SW quadrant: a road
    layer at 50 % everywhere."""
    base = DIRT if x < 0 else GRASS
    f = [btxt(base, q) for q in range(4)]
    if (x, y) == (-1, -1):
        f += atxt(SNOW, 3, 0, {(r, c): 1.0 for r in range(17) for c in range(17)})
    if (x, y) == (0, 0):
        f += atxt(ROAD, 0, 0, {(r, c): 0.5 for r in range(17) for c in range(17)})
    return f


def skyrim_esm(path):
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800))])
    txst = grup(b"TXST", 0, [rec(b"TXST", 0x0B00 + k, [(b"EDID", e.encode() + b"\0"), (b"TX00", d.encode() + b"\0")])
                             for k, (e, d) in enumerate([("TXDirt", "landscape\\dirt02.dds"),
                                                         ("TXGrass", "landscape\\grass\\tundra01.dds"),
                                                         ("TXSnow", "landscape\\snow01.dds"),
                                                         ("TXRoad", "landscape\\roads\\road01.dds")])])
    ltex = grup(b"LTEX", 0, [rec(b"LTEX", fid, [(b"EDID", e.encode() + b"\0"), (b"TNAM", struct.pack("<I", 0x0B00 + k))])
                             for k, (fid, e) in enumerate([(DIRT, "LDirt02"), (GRASS, "LTundra01"), (SNOW, "LSnow01"),
                                                           (ROAD, "LRoad01")])])
    items, sub, fid = [], [], 0x1000
    x0, x1, y0, y1 = EXTENT
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            vh, _ = cell_vhgt(x, y)
            sub.append(rec(b"CELL", fid, [(b"XCLC", struct.pack("<iiI", x, y, 0))]))
            land = rec(b"LAND", fid + 1, [(b"DATA", b"\0" * 4), (b"VHGT", vh)] + cell_textures(x, y), compress=True)
            sub.append(grup(fid, 6, [grup(fid, 9, [land])]))
            fid += 2
    items.append(grup(b"\0\0\0\0", 4, [grup(b"\0\0\0\0", 5, sub)]))
    wrld = rec(b"WRLD", 0x3C, [(b"EDID", b"Tamriel\0"), (b"DNAM", struct.pack("<ff", -2048.0, -14000.0))])
    with open(path, "wb") as f:
        f.write(tes4 + txst + ltex + grup(b"WRLD", 0, [wrld, grup(0x3C, 1, items)]))
    return path


def starfield_esm(path):
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
    ltex = grup(b"LTEX", 0, [rec(b"LTEX", fid, [(b"EDID", e.encode() + b"\0")]) for e, fid in SF.items()])
    with open(path, "wb") as f:
        f.write(tes4 + ltex)
    return path


class LayerTests(unittest.TestCase):
    def test_skyrim_layers_to_vertex_weights(self):
        lay = landtex.land_layers(b"".join(sig + struct.pack("<H", len(d)) + d for sig, d in
                                           [btxt(DIRT, 0), btxt(DIRT, 1), btxt(GRASS, 2), btxt(GRASS, 3)]
                                           + atxt(SNOW, 0, 0, {(0, 0): 1.0, (5, 5): 0.25})
                                           + atxt(ROAD, 0, 1, {(5, 5): 0.5})))
        w = landtex.cell_weights(lay)
        total = sum(w.values())
        np.testing.assert_allclose(total, 1.0, atol=1e-9)              # weights of every vertex sum to one
        self.assertAlmostEqual(w[SNOW][0, 0], 1.0)
        self.assertAlmostEqual(w[ROAD][5, 5], 0.5)                     # road layer 1 is above snow layer 0
        self.assertAlmostEqual(w[SNOW][5, 5], 0.25 * 0.5)
        self.assertAlmostEqual(w[DIRT][5, 5], 0.75 * 0.5)
        self.assertAlmostEqual(w[GRASS][20, 5], 1.0)                   # NW quadrant base
        self.assertAlmostEqual(w[DIRT][3, 25], 1.0)                    # SE quadrant base

    def test_encode_decode_round_trip(self):
        rng = np.random.default_rng(3)
        k = 7
        raw = rng.random((k, 128, 128)) ** 3
        raw[0] += 0.5                                                  # a dominant base
        w = raw / raw.sum(axis=0)
        table = [0x100 + i for i in range(k)]
        qmap, words, st = landtex.encode_quadrants(w.astype(np.float32), table, table)
        self.assertEqual(qmap.shape, (2, 2, 8))
        self.assertTrue((qmap[:, :, 5] > 0).all())                     # base in byte 5
        self.assertTrue((qmap[:, :, 6:] == 0).all())
        dec = landtex.decode_quadrants(qmap, words, table)
        got = np.stack([dec.get(t, np.zeros((128, 128))) for t in table])
        kept = got.sum(axis=0)
        np.testing.assert_allclose(kept, 1.0, atol=1e-9)
        err = np.abs(got - w)
        self.assertLess(float(err.mean()), 0.05)                       # 3-bit alphas, one texture beyond six dropped
        self.assertGreater(st["weight_beyond_six_layers"], 0.0)

    def test_solid_blend_drops_faint_layers_and_fills_strong_ones(self):
        table = [landtex.PLAIN_GROUND, 0x10, 0x20]
        w = np.zeros((3, 64, 64), np.float32)
        w[0] = 1.0                                         # base everywhere
        w[1, :, :32] = 0.3                                 # faint dusting on the west half (dither: specks)
        w[2, :, 32:] = 0.8                                 # a strong layer on the east half
        w[0] -= w[1] + w[2]
        qmap, words, _ = landtex.encode_quadrants(w, table, table, blend="solid")
        dec = landtex.decode_quadrants(qmap, words, table)
        self.assertEqual(float(dec.get(0x10, np.zeros((64, 64))).max()), 0.0)        # faint layer gone
        self.assertEqual(float(dec[0x20][:, 32:].min()), 1.0)                           # strong layer solid
        self.assertEqual(float(dec[landtex.PLAIN_GROUND][:, :32].min()), 1.0)          # base shows through
        dith, dwords, _ = landtex.encode_quadrants(w, table, table, blend="dither")
        self.assertTrue(any(0 < int(v) < 7 for v in np.unique(dwords & 7)) or
                        any(0 < int(v) < 7 for v in np.unique((dwords >> 3) & 7)))     # dither keeps partials
        with self.assertRaises(ValueError):
            landtex.encode_quadrants(w, table, table, blend="nope")

    def test_single_texture_quadrant_matches_vanilla_form(self):
        w = np.zeros((1, 64, 64), np.float32)
        w[0] = 1.0
        qmap, words, _ = landtex.encode_quadrants(w, [landtex.PLAIN_GROUND], [landtex.PLAIN_GROUND])
        self.assertEqual(list(qmap[0, 0]), [0, 0, 0, 0, 0, 1, 0, 0])
        self.assertEqual(int(words.max()), 0)

    def test_categories_and_mapping_overrides(self):
        self.assertEqual(landtex.category("LSnow01", ""), "snow")
        self.assertEqual(landtex.category("LTundra01", "landscape\\grass\\tundra01.dds"), "grass")
        self.assertEqual(landtex.category("LRoad01", ""), "road")
        self.assertEqual(landtex.category("LXyz", "landscape\\pinefloor\\needles.dds"), "forest")
        self.assertEqual(landtex.category("LMystery", ""), "dirt")
        sky = {DIRT: {"edid": "LDirt02", "diffuse": ""}, SNOW: {"edid": "LSnow01", "diffuse": ""},
               ROAD: {"edid": "LRoad01", "diffuse": ""}}
        m = landtex.build_mapping(sky, SF)
        self.assertEqual(m["skyrim"][SNOW]["starfield"], "LSnowDeep01")
        self.assertEqual(m["skyrim"][ROAD]["starfield"], "LGravelPath01")
        self.assertEqual(m["skyrim"][DIRT]["starfield"], "LDirtFootprints01")
        self.assertEqual(m["categories"]["ash"]["edid"], "LDirtFootprints01")     # nothing matches: plain ground
        m2 = landtex.build_mapping(sky, SF, {"categories": {"snow": "LRockCliff01"}, "skyrim": {"LRoad01": "LSandBeach01"}})
        self.assertEqual(m2["skyrim"][SNOW]["starfield"], "LRockCliff01")
        self.assertEqual(m2["skyrim"][ROAD]["starfield"], "LSandBeach01")
        with self.assertRaises(ValueError):
            landtex.build_mapping(sky, SF, {"categories": {"snow": "NoSuchTexture"}})

    def test_reads_world_textures(self):
        with tempfile.TemporaryDirectory() as tmp:
            cells, ltex = landtex.read_world_textures(skyrim_esm(os.path.join(tmp, "Skyrim.esm")))
        self.assertEqual(len(cells), 12 * 9)
        self.assertEqual(ltex[SNOW], {"edid": "LSnow01", "diffuse": "landscape\\snow01.dds", "normal": ""})
        self.assertAlmostEqual(cells[(-1, -1)][SNOW][30, 30], 1.0)
        self.assertAlmostEqual(cells[(0, 0)][ROAD][5, 5], 0.5)
        self.assertAlmostEqual(cells[(0, 0)][GRASS][5, 5], 0.5)


class OverlayTextureTests(unittest.TestCase):
    def test_overlay_build_with_land_textures(self):
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        with tempfile.TemporaryDirectory() as tmp:
            esm = skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            sfd = os.path.join(tmp, "SF")
            os.makedirs(sfd)
            starfield_esm(os.path.join(sfd, "Starfield.esm"))
            out = os.path.join(tmp, "out")
            with mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                    contextlib.redirect_stdout(io.StringIO()):
                sk.main(["build", "--skyrim", esm, "--sf-data", sfd, "--out", out, "--mask-writer", "builtin",
                         "--arrival", "", "--land-textures", "--ltex-blend", "dither"])
            with open(os.path.join(out, "Data", "Terrain", "SKY_Tamriel.btd"), "rb") as f:
                t = btd.read(f.read())
            with open(os.path.join(out, "ltex_mapping.json"), encoding="utf-8") as f:
                mapping = json.load(f)
            with open(os.path.join(out, "skyrim_source.json"), encoding="utf-8") as f:
                src = json.load(f)
        self.assertEqual(sorted(t.ltex), sorted([SF["LDirtFootprints01"], SF["LGrassMeadow01"], SF["LSnowDeep01"],
                                                 SF["LGravelPath01"]]))
        dec = landtex.decode_quadrants(t.quad_map, t.weights, t.ltex)
        n = t.ncx
        o = tg.grid_origin(n)

        def weight_at(fid, xu, yu):                                    # Skyrim units -> BTD sample
            c = int((xu / 70.0 - o) / tg.SF_STEP_M)
            r = int((yu / 70.0 - o) / tg.SF_STEP_M)
            return float(dec.get(fid, np.zeros((1, 1)))[r, c]) if fid in dec else 0.0
        self.assertGreater(weight_at(SF["LSnowDeep01"], -1000.0, -1000.0), 0.9)     # cell (-1,-1) NE quadrant: snow
        self.assertGreater(weight_at(SF["LDirtFootprints01"], -6000.0, -6000.0), 0.9)   # west: dirt
        self.assertGreater(weight_at(SF["LGrassMeadow01"], 3000.0, 6000.0), 0.9)    # east: grass
        road = weight_at(SF["LGravelPath01"], 700.0, 700.0)                          # cell (0,0) SW: 50 % road
        self.assertAlmostEqual(road, 0.5, delta=0.1)
        self.assertEqual(mapping["skyrim"][str(SNOW)]["category"], "snow")
        self.assertIn("LSnowDeep01", mapping["coverage"])
        self.assertEqual(src["land_textures"]["skyrim_ltex"], 4)
        self.assertNotIn("land textures (one plain ground LTEX; --land-textures)", src["not_included"])
        # LOD4 weights are every 16th sample of LOD0 (written by btd.write)
        self.assertEqual(t.weights.dtype, np.uint16)

    def test_without_option_btd_keeps_plain_ground(self):
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        with tempfile.TemporaryDirectory() as tmp:
            esm = skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            out = os.path.join(tmp, "out")
            with mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                    contextlib.redirect_stdout(io.StringIO()):
                sk.main(["build", "--skyrim", esm, "--sf-data", tmp, "--out", out, "--mask-writer", "builtin",
                         "--arrival", ""])
            with open(os.path.join(out, "Data", "Terrain", "SKY_Tamriel.btd"), "rb") as f:
                t = btd.read(f.read())
        self.assertEqual(t.ltex, [0x001235C2])
        self.assertEqual(int(t.weights.max()), 0)
        self.assertTrue((t.quad_map[:, :, 0] == 1).all())


if __name__ == "__main__":
    unittest.main()
