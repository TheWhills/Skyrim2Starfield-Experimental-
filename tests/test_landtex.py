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
        self.assertTrue((qmap[:, :, 4] > 0).all())                     # 4 overlays, base in byte 4
        self.assertTrue((qmap[:, :, 5:] == 0).all())
        dec = landtex.decode_quadrants(qmap, words, table)
        got = np.stack([dec.get(t, np.zeros((128, 128))) for t in table])
        kept = got.sum(axis=0)
        np.testing.assert_allclose(kept, 1.0, atol=1e-9)
        err = np.abs(got - w)
        self.assertLess(float(err.mean()), 0.08)                       # 3-bit alphas, 2 of 7 textures dropped
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

    def test_noise_blend_turns_straight_fades_into_patches(self):
        """2026-11-21 (owner: ground textures meeting "like squares"): a smooth Skyrim fade cut at one half is a straight
        border; cut against coherent noise it wanders through the fade, the layer covering about its weight."""
        table = [landtex.PLAIN_GROUND, 0x20]
        rows, cols = 128, 256
        fade = np.clip((np.arange(cols) - 64) / 128.0, 0, 1).astype(np.float32)   # 0 .. 1 over 100 m
        w = np.zeros((2, rows, cols), np.float32)
        w[1] = fade[None, :]
        w[0] = 1.0 - w[1]
        xs, ys = np.arange(cols) * 0.78125 + 1000.0, np.arange(rows) * 0.78125 - 500.0

        def crossings(words, qmap):
            dec = landtex.decode_quadrants(qmap, words, table)[0x20]
            return dec, [int(np.argmax(r > 0.5)) for r in dec]
        sq, sw, _ = landtex.encode_quadrants(w, table, table, blend="solid")
        _d, solid_x = crossings(sw, sq)
        self.assertEqual(len(set(solid_x)), 1)                                  # solid: one straight border
        nq, nw, _ = landtex.encode_quadrants(w, table, table, blend="noise", coords=(xs, ys))
        self.assertTrue(set(np.unique(nw & 7).tolist()) <= {0, 7})              # still only on / off per sample
        dec, noise_x = crossings(nw, nq)
        self.assertGreater(np.std(noise_x), 5.0)                                # the border wanders
        cover = dec.mean(axis=0)
        for c in (96, 128, 160):                                                # about its weight through the fade
            self.assertAlmostEqual(float(cover[c - 8:c + 8].mean()), float(fade[c - 8:c + 8].mean()), delta=0.2)
        # no seam at the quadrant border (column 128), where the stack flips (base and overlay swap): the coverage
        # just either side differs no more than anywhere else in the fade
        step = np.abs(np.diff(cover[100:156]))
        self.assertLessEqual(float(abs(cover[128] - cover[127])), float(np.sort(step)[-2]) + 1e-6)
        self.assertEqual(float(dec[:, :60].max()), 0.0)                          # none where Skyrim has none
        self.assertEqual(float(dec[:, 200:].min()), 1.0)                         # all where Skyrim has all
        # the threshold belongs to the world position: two halves encoded apart match the whole
        lq, lw, _ = landtex.encode_quadrants(w[:, :, :128], table, table, blend="noise", coords=(xs[:128], ys))
        rq, rw, _ = landtex.encode_quadrants(w[:, :, 128:], table, table, blend="noise", coords=(xs[128:], ys))
        np.testing.assert_array_equal(np.concatenate([lw, rw], axis=1), nw)
        n1 = landtex.blend_noise(xs, ys, 0x20)
        np.testing.assert_array_equal(n1, landtex.blend_noise(xs, ys, 0x20))
        self.assertFalse(np.array_equal(n1, landtex.blend_noise(xs, ys, 0x21)))   # each texture its own pattern
        self.assertTrue(0.3 < float(n1.mean()) < 0.7)
        self.assertTrue(0.1 < float((n1 < 0.25).mean()) < 0.4)                   # spread toward uniform

    def test_cell_edges_stitched_consistently(self):
        """2026-11-21 (owner's grey-blue strips; ground_at: Skyrim 1 % rock, the build drew rock): two cells share their
        edge column; a texture the second cell does not have must not keep the first cell's value there, or two
        textures are both full on the edge line (a vertex-wide straight strip along the cell edge)."""
        rock, grass = np.ones((33, 33), np.float32), np.ones((33, 33), np.float32)
        cells = {(0, 0): {1: rock}, (1, 0): {2: grass}}
        r = landtex.merged_grid(cells, 1, 0, 1, 0, 0, 0.0)
        g = landtex.merged_grid(cells, 2, 0, 1, 0, 0, 0.0)
        np.testing.assert_allclose(r + g, 1.0)                                # every vertex sums to one
        self.assertEqual((float(r[5, 32]), float(g[5, 32])), (0.0, 1.0))      # the edge belongs to the cell written last
        self.assertEqual(float(r[5, 31]), 1.0)                                 # the first cell's interior untouched
        old_r = landtex.merged_grid(cells, 1, 0, 1, 0, 0, 0.0, consistent_edges=False)
        self.assertEqual(float(old_r[5, 32] + g[5, 32]), 2.0)                  # the old stitching: both full
        empty = landtex.merged_grid({(0, 0): {1: rock}}, 1, 0, 1, 0, 0, 0.0)   # a cell with no data: the fill
        self.assertEqual(float(empty[5, 40]), 0.0)

    def test_aligned_slots_keep_edges_consistent(self):
        """2026-11-22 (the snow band on a quadrant's first rows): neighbouring quadrants keep shared textures at the same
        byte, fill unused bytes with the neighbour's, and near an edge a sample only uses a byte equal to the
        neighbour's there, so blending the two quadrants' bytes there (as the engine appears to) changes nothing."""
        n = 10
        kept = {(0, 0): [3, 7, 1], (0, 1): [7, 5, 3, 2, 9], (1, 0): [1, 3], (1, 1): [5, 7, 4]}
        plan = landtex.plan_slots(kept)
        for q, ts in kept.items():
            self.assertEqual(len(plan[q]), landtex.SLOTS)
            self.assertTrue(set(ts) <= set(plan[q]))                       # every texture has a position
        a, b, c = plan[(0, 0)], plan[(0, 1)], plan[(1, 0)]
        self.assertEqual(b.index(7), a.index(7))                           # shared with the west neighbour
        self.assertEqual(b.index(3), a.index(3))
        self.assertEqual(c.index(1), a.index(1))                           # shared with the south neighbour
        self.assertEqual(c.index(3), a.index(3))
        # two quadrants side by side (west: textures 3 / 7 / 1, east: 7 / 5 / 3 / 2 / 9), every texture everywhere
        ids = [0x100 + i for i in range(n)]
        rng = np.random.default_rng(3)
        w = rng.random((n, 64, 128)).astype(np.float32)
        xs, ys = np.arange(128) * 0.78125, np.arange(64) * 0.78125
        rowplan = [plan[(0, 0)], plan[(0, 1)]]
        side = {"w": (0, -1), "e": (0, 1), "s": (-1, 0), "n": (1, 0)}
        q, words = landtex.encode_band_aligned(w, ids, rowplan, lambda qc, sd: plan.get((0 + side[sd][0], qc + side[sd][1])),
                                               (xs, ys), n)
        self.assertEqual([landtex.entry_for(int(x), n) for x in q[0][:5]], rowplan[0])
        self.assertTrue(set(np.unique(words & 0x7FFF).tolist()) <= {0, 7, 7 << 3, 7 << 6, 7 << 9})   # one layer each

        def active(word, slots):
            g = [k for k in range(4) if (int(word) >> (3 * k)) & 7]
            return g[0] if g else 4
        # the engine's apparent edge blend: within the edge band, the active byte mixes with the neighbour's
        for r in range(64):
            for cc in (60, 61, 62, 63, 64, 65, 66, 67):
                me, nb = (0, 1) if cc < 64 else (1, 0)
                k = active(words[r, cc], rowplan[me])
                self.assertEqual(rowplan[me][k], rowplan[nb][k],
                                 f"row {r} col {cc}: byte {k} differs across the edge")
        # away from the edges each quadrant draws its own most weighted textures as before
        mid = [rowplan[0][active(words[r, cc], rowplan[0])] for r in range(10, 54) for cc in range(10, 54)]
        self.assertTrue(set(mid) <= set(kept[(0, 0)]) | set(rowplan[0]))

    def test_slots_shared_across_owner_quadrants(self):
        """2026-11-22 (owner's grey patch at -1846.08, 849.67): quadrant (88, 35) held ReachDirt at byte 0, the one south
        of it at byte 4, so only MossyRocks (byte 3 in both) was allowed in the 3 m edge strip and covered it. With one
        position per texture, every texture on both sides of an edge has the same byte."""
        dirt, rnr, rocks, mossy, mud, grass, rb, dirt02, moss = 27, 14, 30, 38, 40, 44, 50, 49, 34
        kept = {(1, 0): [dirt, mud, grass, rocks, moss], (1, 1): [dirt, rnr, rocks, mossy, mud],
                (1, 2): [dirt, rnr, rocks, mossy, moss], (0, 0): [grass, moss, rocks, mossy, dirt],
                (0, 1): [grass, rb, dirt02, mossy, dirt], (0, 2): [grass, moss, rocks, mossy, dirt],
                (2, 1): [dirt, rnr, rocks, moss, 46]}
        # weights as the owner's quadrants: ReachDirt dominant where Skyrim paints it, MossyRocks a few per cent
        w = {q: {t: (60.0 if t == dirt else 20.0 if t == grass else 8.0) for t in ts} for q, ts in kept.items()}
        plan = landtex.plan_slots(kept, w)
        shared_ok = total = 0
        for (q1, q2) in [((1, 1), (0, 1)), ((1, 1), (1, 0)), ((1, 1), (1, 2)), ((1, 1), (2, 1)), ((0, 0), (0, 1))]:
            shared = set(kept[q1]) & set(kept[q2])
            for t in shared:
                total += 1
                shared_ok += plan[q1].index(t) == plan[q2].index(t)
            heavy = max(shared, key=lambda t: min(w[q1][t], w[q2][t]))
            self.assertEqual(plan[q1].index(heavy), plan[q2].index(heavy), f"{q1} {q2}: {heavy}")
        # ten textures meet in these seven quadrants: more than five positions can keep apart, so not every
        # minor texture lines up, but most do and the one that mattered at the owner's strip (ReachDirt) does
        self.assertGreaterEqual(shared_ok / total, 0.8)
        self.assertEqual(plan[(1, 1)].index(dirt), plan[(0, 1)].index(dirt))
        for q, ts in kept.items():
            self.assertTrue(set(ts) <= set(plan[q]))

    def test_smooth_keeps_skyrims_mix(self):
        """2026-11-22 (vanilla hand-made worlds use partial alphas): "smooth" writes Skyrim's mix as alphas at the planned
        positions; decoding gives the mix back within one alpha step, on both sides of an edge."""
        n = 6
        ids = [0x100 + i for i in range(n)]
        kept = {(0, 0): [1, 2, 3], (0, 1): [1, 2, 4]}
        plan = landtex.plan_slots(kept)
        w = np.zeros((n, 64, 128), np.float32)
        frac = np.linspace(0.0, 1.0, 128, dtype=np.float32)
        w[1] = 0.6 * frac[None, :]
        w[2] = 0.6 * (1 - frac[None, :])
        w[3][:, :64] = 0.4
        w[4][:, 64:] = 0.4
        xs, ys = np.arange(128) * 0.78125, np.arange(64) * 0.78125
        side = {"w": (0, -1), "e": (0, 1), "s": (-1, 0), "n": (1, 0)}
        q, words = landtex.encode_band_aligned(w, ids, [plan[(0, 0)], plan[(0, 1)]],
                                               lambda qc, sd: plan.get((side[sd][0], qc + side[sd][1])), (xs, ys), n,
                                               partial=True)
        qm = np.zeros((1, 2, 8), np.uint8)
        qm[0] = q
        dec = landtex.decode_quadrants(qm, words, ids)
        alphas = set()
        for g in range(5):
            alphas |= set(np.unique((words >> (3 * g)) & 7).tolist())
        self.assertTrue(alphas - {0, 7})                                       # partial alphas written
        for t in (1, 2):
            got = dec[ids[t]][:, 8:56].mean(axis=0)                            # away from the edge band
            want = w[t][:, 8:56].mean(axis=0)
            self.assertLess(float(np.abs(got - want).max()), 1.0 / 7 + 0.02)
        self.assertLess(abs(float(dec[ids[3]][:, 8:56].mean()) - 0.4), 0.08)

    def test_warp_bends_sharp_borders(self):
        """A sharp Skyrim border (one vertex step) read at the warped positions wanders by up to WARP_M, the same for
        every texture (weights still sum to 1) and the same at the same world position."""
        from fo4sf import terrain_grid as tg
        U, sp = tg.UNITS_PER_METRE, 128.0
        g = np.zeros((40, 60))
        g[:, 30:] = 1.0
        xs, ys = np.arange(128) * 0.78125 + 10.0, np.arange(128) * 0.78125 + 5.0
        plain = tg.resample_bilinear(g, 0, 0, sp, xs * U, ys * U)
        dx, dy = landtex.warp_offsets(xs, ys)
        self.assertLessEqual(float(np.abs(dx).max()), landtex.WARP_M)
        warped = landtex.sample_warped(g, 0, 0, sp, xs * U, ys * U, dx * U, dy * U)
        inv = landtex.sample_warped(1.0 - g, 0, 0, sp, xs * U, ys * U, dx * U, dy * U)
        np.testing.assert_allclose(warped + inv, 1.0, atol=1e-9)
        straight = {int(np.argmax(r >= 0.5)) for r in plain}
        bent = [int(np.argmax(r >= 0.5)) for r in warped]
        self.assertEqual(len(straight), 1)
        self.assertGreater(max(bent) - min(bent), 3)                         # metres of wander, not a straight line
        self.assertLessEqual(max(bent) - min(bent), 2 * landtex.WARP_M / 0.78125 + 4)
        # 20:58 (the grey strip): ragged in place, not slid sideways: on average the border stays where Skyrim's is
        self.assertLess(abs(float(np.mean(bent)) - next(iter(straight))), 1.5)
        dx2, _ = landtex.warp_offsets(xs[64:], ys)
        np.testing.assert_array_equal(dx2, dx[:, 64:])                     # a function of the world position
        np.testing.assert_allclose(landtex.sample_warped(g, 0, 0, sp, xs * U, ys * U, 0 * dx, 0 * dy), plain)

    def test_single_texture_quadrant_matches_vanilla_form(self):
        w = np.zeros((1, 64, 64), np.float32)
        w[0] = 1.0
        qmap, words, _ = landtex.encode_quadrants(w, [landtex.PLAIN_GROUND], [landtex.PLAIN_GROUND])
        self.assertEqual(list(qmap[0, 0]), [1, 0, 0, 0, 0, 0, 0, 0])
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


def update_esm(path):
    """An Update.esm over skyrim_esm: cell (0, 0)'s LAND repainted with a new LTEX of its own (0x01000800,
    'LUpdGrass') over the whole of quadrant 0, and LTundra01 given grass (GRAS 0x01000900)."""
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800)), (b"MAST", b"Skyrim.esm\0"),
                            (b"DATA", bytes(8))])
    ltex = grup(b"LTEX", 0, [rec(b"LTEX", 0x01000800, [(b"EDID", b"LUpdGrass\0"), (b"TNAM", struct.pack("<I", 0x0B01)),
                                                       (b"GNAM", struct.pack("<I", 0x01000900))]),
                             rec(b"LTEX", GRASS, [(b"EDID", b"LTundra01\0"), (b"TNAM", struct.pack("<I", 0x0B01)),
                                                  (b"GNAM", struct.pack("<I", 0x01000900))])])
    gras = grup(b"GRAS", 0, [rec(b"GRAS", 0x01000900, [(b"EDID", b"UpdGrass01\0"), (b"MODL", b"g\\upd.nif\0"),
                                                       (b"DATA", bytes([40, 0, 30, 0]) + bytes(28))])])
    cid = None
    x0, x1, y0, y1 = EXTENT
    fid = 0x1000
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            if (x, y) == (0, 0):
                cid = fid
            fid += 2
    lay = [btxt(DIRT, 0)] + atxt(0x01000800, 0, 0, {(r, c): 1.0 for r in range(17) for c in range(17)})
    cell = rec(b"CELL", cid, [(b"XCLC", struct.pack("<iiI", 0, 0, 0))])
    land = rec(b"LAND", 0x01000A00, [(b"DATA", b"\0" * 4)] + lay)
    items = [grup(b"\0\0\0\0", 4, [grup(b"\0\0\0\0", 5, [cell, grup(cid, 6, [grup(cid, 9, [land])])])])]
    wrld = rec(b"WRLD", 0x3C, [(b"EDID", b"Tamriel\0")])
    with open(path, "wb") as f:
        f.write(tes4 + ltex + gras + grup(b"WRLD", 0, [wrld, grup(0x3C, 1, items)]))
    return path


class LoadOrderTests(unittest.TestCase):
    def test_update_esm_overrides_land_ltex_and_grass(self):
        from fo4sf import skyrimgrass
        with tempfile.TemporaryDirectory() as tmp:
            esm = skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            only, _l = landtex.read_world_textures(esm, official=False)
            update_esm(os.path.join(tmp, "Update.esm"))
            self.assertEqual([os.path.basename(p) for p in landtex.official_plugins(esm)], ["Skyrim.esm", "Update.esm"])
            cells, ltex = landtex.read_world_textures(esm)
            lg, gras = skyrimgrass.read_grass(esm)
            lg0, _g0 = skyrimgrass.read_grass(esm, official=False)
        self.assertIn(GRASS, only[(0, 0)])
        self.assertAlmostEqual(cells[(0, 0)][0x01000800][5, 5], 1.0)            # Update's own LTEX, load index 1
        self.assertNotIn(GRASS, cells[(0, 0)])                                  # the whole LAND is replaced
        for k in only[(1, 1)]:                                                  # other cells: Skyrim.esm's
            np.testing.assert_allclose(cells[(1, 1)][k], only[(1, 1)][k])
        self.assertEqual(ltex[0x01000800]["edid"], "LUpdGrass")
        self.assertEqual(lg[GRASS], [0x01000900])                               # override gives LTundra01 grass
        self.assertNotIn(GRASS, lg0)
        self.assertEqual(gras[0x01000900]["edid"], "UpdGrass01")
        self.assertEqual(gras[0x01000900]["density"], 40)

    def test_fid_remapper(self):
        paths = ["Skyrim.esm", "Update.esm", "HearthFires.esm"]
        r = landtex.fid_remapper(paths, 2, ["Skyrim.esm", "Update.esm"])     # HearthFires: own index 2 -> 2
        self.assertEqual(r(0x00012345), 0x00012345)
        self.assertEqual(r(0x02000801), 0x02000801)
        r = landtex.fid_remapper(["Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm"], 3,
                                 ["Skyrim.esm", "Update.esm"])
        self.assertEqual(r(0x02000801), 0x03000801)                             # own records -> load index 3
        self.assertEqual(r(0x01000005), 0x01000005)
        self.assertEqual(r(0), 0)


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

    def test_recompute_installed_terrain_textures(self):
        """2026-11-21 (owner's skyrim_all has no build_command.txt): refresh_btd.py recompute re-encodes the staged BTDs'
        textures from Skyrim.esm with the staging's own mapping, after a spot check that the old way reproduces them;
        heights stay byte for byte. With other inputs (a changed mapping) the check fails and nothing is written."""
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "terrain"))
        import refresh_btd as R
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            esm = skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            sfd = os.path.join(tmp, "SF")
            os.makedirs(sfd)
            starfield_esm(os.path.join(sfd, "Starfield.esm"))
            out = os.path.join(tmp, "out")
            with mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                    contextlib.redirect_stdout(io.StringIO()):
                sk.main(["build", "--skyrim", esm, "--sf-data", sfd, "--out", out, "--mask-writer", "builtin",
                         "--arrival", "", "--land-textures", "--ltex-blend", "solid"])
            path = os.path.join(out, "Data", "Terrain", "SKY_Tamriel.btd")
            with open(path, "rb") as f:
                before = btd.read(f.read())
            args = SimpleNamespace(staging=out, skyrim=esm, sf_data=sfd, world="Tamriel", min_match=0.98,
                                   check_bands=24, check_blend="solid", blend="noise", warp=3.5,
                                   infer_bands=48, dry_run=False)
            mp = os.path.join(out, "ltex_mapping.json")
            with open(mp, encoding="utf-8") as f:
                good = f.read()
            bad = json.loads(good)
            for v in bad["skyrim"].values():                                      # not what the build used
                v["starfield"] = "LGrassMeadow01"
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(bad, f)
            with contextlib.redirect_stdout(io.StringIO()) as o1:
                self.assertEqual(R.cmd_recompute(args), 1)
            self.assertIn("nothing written", o1.getvalue())
            with open(path, "rb") as f:
                self.assertEqual(btd.read(f.read()).weights.tobytes(), before.weights.tobytes())
            with open(mp, "w", encoding="utf-8") as f:
                f.write(good)
            with contextlib.redirect_stdout(io.StringIO()) as o2:
                self.assertEqual(R.cmd_recompute(args), 0)
            self.assertRegex(o2.getvalue(), r"(99\.\d|100\.0)% of samples draw the same texture as the terrain as built")
            with open(os.path.join(out, R.BACKUP, "Data", "Terrain", "SKY_Tamriel.btd"), "rb") as f:
                self.assertEqual(btd.read(f.read()).weights.tobytes(), before.weights.tobytes())   # the build's kept
            with open(path, "rb") as f:
                after = btd.read(f.read())
            # the owner's October staging has no ltex_mapping.json: learnt off the installed terrain instead
            with open(path, "wb") as f:
                f.write(btd.write(before))
            os.remove(mp)
            import shutil
            shutil.rmtree(os.path.join(out, R.BACKUP))
            args.infer_bands = 48
            with contextlib.redirect_stdout(io.StringIO()) as o3:
                self.assertEqual(R.cmd_recompute(args), 0)
            self.assertIn("read off the terrain", o3.getvalue())
            self.assertRegex(o3.getvalue(), r"(99\.\d|100\.0)% of samples draw the same texture as the terrain as built")
            with open(path, "rb") as f:
                inferred = btd.read(f.read())
            np.testing.assert_array_equal(inferred.weights, after.weights)             # the same as with the mapping
            # run again on terrain that is already blended: the check and the learning read the backup (as built)
            with contextlib.redirect_stdout(io.StringIO()) as o4:
                self.assertEqual(R.cmd_recompute(args), 0)
            self.assertRegex(o4.getvalue(), r"(99\.\d|100\.0)% of samples draw the same texture as the terrain as built")
            with open(path, "rb") as f:
                np.testing.assert_array_equal(btd.read(f.read()).weights, after.weights)
            # 2026-11-23: Update.esm repaints cell (0, 0): learnt and checked against Skyrim.esm (the build's input),
            # painted as the game loads it
            update_esm(os.path.join(tmp, "Update.esm"))
            with contextlib.redirect_stdout(io.StringIO()) as o5:
                self.assertEqual(R.cmd_recompute(args), 0)
            self.assertIn("Update.esm / DLC repaint 1 cells", o5.getvalue())
            self.assertRegex(o5.getvalue(), r"(99\.\d|100\.0)% of samples draw the same texture as the terrain as built")
            with open(path, "rb") as f:
                upd = btd.read(f.read())
            self.assertFalse(np.array_equal(upd.weights, after.weights))
            np.testing.assert_array_equal(upd.heights_raw, before.heights_raw)
        np.testing.assert_array_equal(after.heights_raw, before.heights_raw)
        self.assertEqual((after.hmin, after.hmax, after.ltex), (before.hmin, before.hmax, before.ltex))
        self.assertFalse(np.array_equal(after.weights, before.weights))                # the noise blend went in
        self.assertTrue(set(np.unique(after.weights & 7).tolist()) <= {0, 7})

    def test_ground_at_map(self):
        """2026-11-21: ground_at.py --map prints what Skyrim paints and what the BTD draws around a spot, with the
        quadrant edges and each nearby quadrant's five textures (to tell a dropped texture from a wrong one)."""
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "terrain"))
        import ground_at
        with tempfile.TemporaryDirectory() as tmp:
            esm = skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            sfd = os.path.join(tmp, "SF")
            os.makedirs(sfd)
            starfield_esm(os.path.join(sfd, "Starfield.esm"))
            out = os.path.join(tmp, "out")
            with mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                    contextlib.redirect_stdout(io.StringIO()):
                sk.main(["build", "--skyrim", esm, "--sf-data", sfd, "--out", out, "--mask-writer", "builtin",
                         "--arrival", "", "--land-textures"])
            with contextlib.redirect_stdout(io.StringIO()) as o:
                ground_at.main(["--skyrim", esm, "--terrain", out, "--pos", "-14.3", "-14.3", "--map", "8"])
        text = o.getvalue()
        self.assertIn("left: what Skyrim paints most, right: what the build draws", text)
        lines = text.splitlines()
        k = next(i for i, ln in enumerate(lines) if ln.startswith("maps "))
        rows = lines[k + 1:k + 18]
        self.assertTrue(all(len(r.split()) in (2, 3) for r in rows))          # two maps side by side per row
        self.assertIn("legend:", lines[k + 18])
        self.assertIn(" <", rows[8])                                         # the spot's row is marked
        self.assertIn("legend:", text)
        self.assertIn("quadrant (+0, +0) from the spot's: its five", text)

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


class IndexRuleTests(unittest.TestCase):
    def test_head_is_starfield_default(self):
        self.assertEqual(landtex.INDEX_RULE, "head")
        for rule in landtex.INDEX_RULES:
            for i in range(5):
                self.assertEqual(landtex.entry_for(landtex.byte_for(i, 5, rule), 5, rule), i)
        self.assertEqual(landtex.byte_for(0, 5, "head"), 1)
        self.assertEqual(landtex.byte_for(0, 5, "tail"), 5)
        with self.assertRaises(ValueError):
            landtex.byte_for(0, 5, "middle")

    def test_encode_writes_head_bytes(self):
        table = [0x100, 0x200, 0x300]
        w = np.zeros((3, 64, 64), np.float32)
        w[0] = 1.0                                   # the whole quadrant is table entry 0
        qmap, _words, _ = landtex.encode_quadrants(w, table, table, blend="solid")
        self.assertEqual([int(b) for b in qmap[0, 0]], [1, 0, 0, 0, 0, 0, 0, 0])    # vanilla's single-texture form
        qmap, _words, _ = landtex.encode_quadrants(w, table, table, blend="solid", index_rule="tail")
        self.assertEqual(int(qmap[0, 0, 0]), 3)

    def test_base_follows_overlays_within_bytes_0_to_4(self):
        table = list(range(0x100, 0x100 + 7))
        w = np.ones((7, 64, 64), np.float32) * np.arange(7, 0, -1)[:, None, None]
        qmap, _words, st = landtex.encode_quadrants(w, table, table, blend="solid")
        b = [int(x) for x in qmap[0, 0]]
        self.assertEqual(b[5:], [0, 0, 0])
        self.assertEqual(b[4], 1)                    # base = the most weight = table entry 0 (head: byte 1)
        self.assertGreater(st["weight_beyond_six_layers"], 0)
