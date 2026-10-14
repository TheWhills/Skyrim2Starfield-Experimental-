"""Synthetic tests for the Commonwealth overlay grid: src/fo4sf/overlay_grid.py (tiles, frames, seams, masks, planet
placement hypothesis) and scripts/terrain/make_cw_overlays.py (build from made-up FO4 heights, offline check).
No game data: every height here is a formula."""
import argparse
import contextlib
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
from fo4sf import btd, overlay  # noqa: E402
from fo4sf import overlay_grid as og  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402
import make_cw_overlays as mco  # noqa: E402
import overlay_records as orc  # noqa: E402


class Region(unittest.TestCase):
    def test_fo4_rect_to_sf_cells(self):
        # experiment 3: FO4 cells x -35..10, y -6..40 -> Starfield cells x -21..6, y -4..23 (28 x 28)
        self.assertEqual(og.sf_cells_of_fo4_rect(-35, 10, -6, 40), (-21, 6, -4, 23))
        # the whole LAND grid, 192 FO4 cells = 11,234.7 m -> 114 Starfield cells
        x0, x1, y0, y1 = og.sf_cells_of_fo4_rect(-96, 95, -96, 95)
        self.assertEqual((x0, x1), (-57, 56))
        self.assertEqual(x1 - x0 + 1, 114)

    def test_split_two_by_two(self):
        tiles = og.split(-21, 6, -4, 23, 14)
        self.assertEqual(len(tiles), 4)
        self.assertEqual([(t.ix, t.iy, t.cx0, t.cy0) for t in tiles],
                         [(0, 0, -21, -4), (1, 0, -7, -4), (0, 1, -21, 10), (1, 1, -7, 10)])
        self.assertEqual(og.grid_shape(tiles), (2, 2))
        self.assertEqual(tiles[0].tag, "00")
        self.assertEqual(tiles[3].cells_x, (-7, 6))

    def test_padding(self):
        # 114 cells in tiles of 14 -> 9 tiles = 126 cells; 'centre' puts 6 extra cells on each side
        tiles = og.split(-57, 56, -57, 56, 14)
        xs = sorted({t.cx0 for t in tiles})
        self.assertEqual(len(xs), 9)
        self.assertEqual(xs[0], -63)
        self.assertEqual(xs[-1] + 14 - 1, 62)
        sw = og.split(-57, 56, -57, 56, 14, pad="sw")
        self.assertEqual(min(t.cx0 for t in sw), -57)
        one = og.split(-21, 6, -4, 23, 28)            # one tile = option (a), one overlay
        self.assertEqual(len(one), 1)
        self.assertEqual(og.outer_edges(one[0], one), ("w", "e", "s", "n"))
        with self.assertRaises(ValueError):
            og.split(0, 9, 0, 9, 2)

    def test_origin_padding(self):
        # the playable core (Starfield cells x -20..18, y -23..18) as one 64-cell overlay whose frame is the CW frame
        one = og.split(-20, 18, -23, 18, 64, pad="origin")
        self.assertEqual(len(one), 1)
        self.assertEqual((one[0].cells_x, one[0].cells_y), ((-32, 31), (-32, 31)))
        self.assertEqual(one[0].origin_m, (0.0, 0.0))
        self.assertEqual(one[0].to_local(-989.0286, 1147.2), (-989.0286, 1147.2))
        # a grid: tile origins on multiples of 14 cells, one tile centred on the CW origin
        tiles = og.split(-21, 6, -4, 23, 14, pad="origin")
        self.assertTrue(all((t.cx0 + 7) % 14 == 0 and (t.cy0 + 7) % 14 == 0 for t in tiles))
        self.assertIn((0.0, 0.0), [t.origin_m for t in tiles])
        self.assertTrue(min(t.cx0 for t in tiles) <= -21 and max(t.cx0 + 13 for t in tiles) >= 6)
        with self.assertRaises(ValueError):
            og.split(0, 9, 0, 9, 5, pad="middle")

    def test_frames_round_trip(self):
        t = og.Tile(1, 0, -7, -4, 14)
        self.assertEqual(t.origin_m, (0.0, 300.0))          # cell -7 + 14 // 2 = 0, cell -4 + 7 = 3
        self.assertEqual(t.to_local(-989.0286, 1147.2), (-989.0286, 847.2))
        self.assertEqual(t.to_cw(*t.to_local(12.5, -40.0)), (12.5, -40.0))
        x0, x1, y0, y1 = t.bounds_m
        self.assertEqual((x0, x1, y0, y1), (-700.0, 700.0, -400.0, 1000.0))
        lx0, lx1, _, _ = (v - o for v, o in zip(t.bounds_m, (0.0, 0.0, 300.0, 300.0)))
        self.assertEqual(lx0, tg.grid_origin(14))             # the BTD's SW sample in the tile's own frame
        self.assertTrue(t.contains(-700.0, -400.0) and not t.contains(700.0, 0.0))

    def test_adjacent_lattices_continue(self):
        a, b = og.Tile(0, 0, -21, -4, 14), og.Tile(1, 0, -7, -4, 14)
        xa, _ = a.sample_coords()
        xb, _ = b.sample_coords()
        self.assertEqual(len(xa), 14 * 128)
        self.assertEqual(xb[0] - xa[-1], tg.SF_STEP_M)       # one step across the seam, as inside one BTD
        self.assertEqual(xb[0], a.bounds_m[1])

    def test_seams_and_edges(self):
        tiles = og.split(-21, 6, -4, 23, 14)
        s = og.seams(tiles)
        self.assertEqual(len(s), 4)
        self.assertEqual(sorted((x["axis"], x["at_m"]) for x in s),
                         [("x", -700.0), ("x", -700.0), ("y", 1000.0), ("y", 1000.0)])
        self.assertEqual({x["name"] for x in s}, {"T00|T10", "T00/T01", "T10/T11", "T01|T11"})
        self.assertEqual(og.outer_edges(tiles[0], tiles), ("w", "s"))
        self.assertEqual(og.outer_edges(tiles[3], tiles), ("e", "n"))
        self.assertIs(og.tile_at(tiles, -989.0, 1147.0), tiles[2])
        self.assertIsNone(og.tile_at(tiles, 700.0, 0.0))

    def test_height_range(self):
        self.assertEqual(og.height_range(-114.46, 140.67), (-116.0, 142.0))   # experiment 2's range


class Masks(unittest.TestCase):
    def test_ring_only_on_outer_edges(self):
        a = overlay.mask_array(5, edges=("w", "s"))
        self.assertTrue((a[:, :100] == 255).all())               # west column of cells
        self.assertTrue((a[400:, :] == 255).all())               # south row (rows are north-first)
        self.assertTrue((a[:400, 100:] == 0).all())              # seams east and north stay 0
        self.assertEqual(overlay.mask_check(a, 5, edges=("w", "s")), (0, 0))
        self.assertNotEqual(overlay.mask_check(a, 5)[0], 0)      # differs from the full ring
        full = overlay.mask_array(5)
        self.assertTrue((full == overlay.mask_array(5, edges=("w", "e", "s", "n"))).all())
        dds = overlay.dds_bc4(a)
        self.assertTrue((overlay.bc4_decode(dds) == a).all())
        with self.assertRaises(ValueError):
            overlay.mask_array(5, edges=("x",))


    def test_mask_edges_symmetric_by_default(self):
        grid = og.split(-21, 6, -4, 23, 14)                       # 2 x 2
        self.assertEqual([og.mask_edges(t, grid) for t in grid], [("w",), ("e",), ("w",), ("e",)])
        self.assertEqual([og.mask_edges(t, grid, "outer") for t in grid],
                         [("w", "s"), ("e", "s"), ("w", "n"), ("e", "n")])
        one = og.split(-21, 6, -4, 23, 28)                         # a single overlay keeps its full ring
        self.assertEqual(og.mask_edges(one[0], one), ("w", "e", "s", "n"))
        row = og.split(-21, 6, 0, 13, 14)                          # one row of two: north and south both outer
        self.assertEqual([og.mask_edges(t, row) for t in row], [("w", "s", "n"), ("e", "s", "n")])
        for t in grid:                                             # flipping the rows gives the same image
            a = overlay.mask_array(14, edges=og.mask_edges(t, grid))
            self.assertTrue((a == a[::-1]).all())
        with self.assertRaises(ValueError):
            og.mask_edges(grid[0], grid, "rows")


class Planet(unittest.TestCase):
    def test_reference_maps_to_its_measured_offset(self):
        self.assertEqual(og.predicted_offset(*og.WORLD01_LATLON), (30.0, -35.0))

    def test_round_trip_and_scale(self):
        for target in ((-7, -7), (7, 7), (0, 0), (-40, 25)):
            lat, lon = og.latlon_for_offset(target)
            x, y = og.predicted_offset(lat, lon)
            self.assertAlmostEqual(x, target[0], places=6)
            self.assertAlmostEqual(y, target[1], places=6)
        k = og.cells_per_radian(og.MARS_RADIUS_KM)
        self.assertEqual(k, 33900.0)                              # 3,390 km / 100 m per radian
        lat0, lon0 = og.latlon_for_offset((30, -34))              # one cell north of the reference
        self.assertAlmostEqual(lat0 - 0.2, 1 / k, places=12)
        self.assertAlmostEqual(lon0, 1.2, places=12)
        lat1, lon1 = og.latlon_for_offset((31, -35))              # one cell east: 1 / (k cos lat)
        self.assertAlmostEqual(lon1 - 1.2, 1 / (k * math.cos(0.2)), places=12)

    def test_group_targets_are_edge_to_edge(self):
        tiles = og.split(-21, 6, -4, 23, 14)
        t = og.group_targets(tiles)
        self.assertEqual([t[x] for x in tiles], [(-7, -7), (7, -7), (-7, 7), (7, 7)])
        self.assertTrue(og.check_adjacent(tiles, t))
        moved = dict(t)
        moved[tiles[1]] = (8, -7)
        self.assertFalse(og.check_adjacent(tiles, moved))
        nine = og.split(0, 41, 0, 41, 14)
        self.assertTrue(og.check_adjacent(nine, og.group_targets(nine, (3, -2))))


class Drops(unittest.TestCase):
    def test_settle_covers_the_fall(self):
        # 64-cell trial (QA, PR #67): drop 250 m, points down to about -15 m -> about 12 s of free fall at Mars
        # gravity, more than the old fixed 8 s wait plus the runner's ~2.9 s of console steps
        t = mco.fall_seconds(250.0, -15.0)
        self.assertAlmostEqual(t, math.sqrt(2 * 285.0 / 3.71), places=9)
        self.assertGreaterEqual(mco.settle_ms(250.0, -15.0), 1000 * t + 1000)
        self.assertEqual(mco.settle_ms(20.0, 10.0), mco.MIN_SETTLE_MS)
        self.assertEqual(mco.drop_z([{"expect": 101.2}, {"expect": -3.0}]), 145.0)

    def test_whole_cells(self):
        self.assertEqual(og.whole_cells(-1200.0014, -2700.0), (-12, -27))     # exp2b's spawn offset
        self.assertEqual(og.whole_cells(3000.0, -3500.0), (30, -35))
        self.assertIsNone(og.whole_cells(25.32, 49.74))                       # exp1d a2: not a merge offset
        self.assertIsNone(og.whole_cells(-1200.0, -2694.0))


class Locate(unittest.TestCase):
    """og.locate_tile on a made-up overlay: heights from a formula, reads at a known whole-cell shift."""

    @staticmethod
    def surface(lx, ly):
        return 40.0 * math.sin(lx / 170.0) + 25.0 * math.cos(ly / 130.0) + 0.01 * lx * ly / 100.0

    def decode(self, lx, ly):
        return [self.surface(lx, ly)]

    def reads(self, shift, xs, ys, other=lambda x, y: 500.0 + 0.3 * x):
        out = []
        for x in xs:
            for y in ys:
                lx, ly = x - shift[0] * 100.0, y - shift[1] * 100.0
                inside = -200.0 <= lx < 300.0 and -200.0 <= ly < 300.0
                out.append((x, y, self.surface(lx, ly) if inside else other(x, y)))
        return out

    def test_finds_the_shift_and_rejects_others(self):
        reads = self.reads((7, 1), np.arange(0.0, 1300.0, 60.0), [130.0])         # transect along x at y 130
        r = og.locate_tile(reads, 5, self.decode, centre=(5, 0), window=6)
        self.assertEqual(r["best"]["d"], (7, 1))
        self.assertEqual(r["best"]["match"], r["best"]["inside"])
        self.assertGreaterEqual(r["best"]["inside"], 3)
        self.assertNotIn((5, 0), [c["d"] for c in r["consistent"]])

    def test_not_there(self):
        reads = self.reads((40, 40), np.arange(0.0, 1300.0, 60.0), [130.0])      # outside the searched window
        r = og.locate_tile(reads, 5, self.decode, centre=(5, 0), window=6)
        self.assertIsNone(r["best"])

    def test_free_z(self):
        reads = [(x, y, h + 3.25) for x, y, h in self.reads((6, 0), np.arange(0.0, 1300.0, 60.0), [130.0])]
        self.assertIsNone(og.locate_tile(reads, 5, self.decode, centre=(5, 0), window=3)["best"])
        r = og.locate_tile(reads, 5, self.decode, centre=(5, 0), window=3, free_z=True)
        self.assertEqual(r["best"]["d"], (6, 0))
        self.assertAlmostEqual(r["best"]["dz"], 3.25, places=3)


# --------------------------------------------------------------------------------------------- synthetic build
def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rbytes(path):
    with open(path, "rb") as f:
        return f.read()


def synthetic_npz(path, lo=-12, hi=11):
    """FO4 LAND grids for cells lo..hi on both axes from one smooth formula (FO4 units), so shared edges match."""
    grid, heights = [], []
    k = np.arange(33) * 128.0
    for cy in range(lo, hi + 1):
        for cx in range(lo, hi + 1):
            xu = cx * 4096.0 + k[None, :]
            yu = cy * 4096.0 + k[:, None]
            z = 3000.0 * np.sin(xu / 20000.0) + 2000.0 * np.cos(yu / 15000.0) + 0.02 * xu
            grid.append((cx, cy))
            heights.append(z)
    np.savez(path, grid=np.array(grid, np.int32), heights=np.array(heights, np.float32))


def build_args(out, npz, **kw):
    a = dict(cmd="build", fo4=None, fo4_npz=npz, sf_data="unused", out=out, fo4_cells=[-8, 7, -8, 7], tile=5,
             pad="centre", prefix="FO4CWT", plugin="FO4TerrainTest.esm", mars_plugin="FO4TerrainTest_Mars.esm",
             no_mars=False, experiment="terrain_test", alignment="absolute", hnam=0, radius_km=og.MARS_RADIUS_KM,
             ref_lat=0.2, ref_lon=1.2, ref_offset=[30, -35], centre_cell=[0, 0], mask_writer="builtin", grid_points=0,
             mask_ns="symmetric", load_byte="02", max_jump=mco.MAX_JUMP, locate_step=50.0)
    a.update(kw)
    return argparse.Namespace(**a)


def spec_of(entry, n):
    """The runner's test spec for a plan entry (testqueue.py plan_terrain keeps these keys)."""
    return {"id": f"{n:04d}_terrain_{entry['coc']}", "kind": "terrain", "model": entry["label"],
            "world_coc": entry["coc"], "spawn_local": entry["spawn_local"], "anchor": entry.get("anchor"),
            "z_ref": entry["z_ref"], "settle_ms": entry["settle_ms"], "drop_z": entry["drop_z"],
            "points": entry["points"]}


def simulate(prm, raws, entry, place, z_offset=0.0, own_shift=(0, 0), spawn_z=-354.13):
    """Runner observations of one entry in a made-up landing. place: {tag: planet cell of the tile's local origin}
    (missing = not activated); the coc'd tile's spawn arrives at its place (read mid-fall: spawn_z); persistent anchors
    read back their local position (as in exp1d / exp2b); own_shift moves every BTD against its own frame (a wrong
    grid-origin rule). Ground elsewhere: a plane far from the overlay heights."""
    tiles = {o["tag"]: og.Tile(o["ix"], o["iy"], o["cells_cw"]["x"][0], o["cells_cw"]["y"][0], o["n"])
             for o in prm["overlays"]}
    by_ref = {o["anchor"]["ref"]: o for o in prm["overlays"]}
    fo = by_ref[entry["anchor"]["ref"]] if entry.get("anchor") else \
        next(o for o in prm["overlays"] if o["coc"] == entry["coc"])
    fp = place[fo["tag"]]
    off = (fp[0] * 100.0, fp[1] * 100.0)

    def ground(x, y):
        for tag, cell in place.items():
            t = tiles[tag]
            lx = x - (cell[0] + own_shift[0]) * 100.0
            ly = y - (cell[1] + own_shift[1]) * 100.0
            lo = tg.grid_origin(t.n)
            if lo <= lx < lo + t.n * 100.0 and lo <= ly < lo + t.n * 100.0:
                return mco.decode_at(raws[tag], prm["hmin"], prm["hmax"], t.n, lx, ly)["bilinear"] + z_offset
        return 400.0 + 0.05 * x

    sl = entry["spawn_local"]
    pts = []
    for p in entry["points"]:
        x, y = p["x"] + off[0], p["y"] + off[1]
        pts.append({"label": p["label"], "read": f"{x:.2f} {y:.2f} {ground(x, y):.2f}"})
    a = fo["anchor"]["local"]
    return {"kind": "terrain", "spawn_read": f"{sl[0] + off[0]:.2f} {sl[1] + off[1]:.2f} {spawn_z:.2f}",
            "anchor_read": f"{a[0]:.2f} {a[1]:.2f} {a[2]:.2f}", "anchor_unmerged": True, "offset_from": "spawn",
            "offset": [off[0], off[1], 0.0], "points": pts}


def rec(sig, fid, fields, flags=0):
    data = b"".join(k.encode() + struct.pack("<H", len(d)) + d for k, d in fields)
    return sig.encode() + struct.pack("<III", len(data), flags, fid) + bytes(8) + data


def zs(text):
    return text.encode("cp1252") + b"\0"


def write_plugins(out, prm, persistent=True, swap_latlon=False, vanilla=None):
    """Minimal plugins with the records check_plugins walks, laid out as dotnet/TerrainOverlays writes them. This
    tests the raw record walk, not TerrainOverlays itself (its real output is walked by `check` on the staged files)."""
    own = 1 << 24
    body, ents = [], list(vanilla or [(0.1, 0.2, 0x0001000A), (-0.3, 0.4, 0x0001000B)])   # two "vanilla" entries
    for k, o in enumerate(prm["overlays"]):
        w, loc, blk = own | (0x900 + 3 * k), own | (0x901 + 3 * k), own | (0x902 + 3 * k)
        body.append(rec("LCTN", loc, [("EDID", zs(o["location"])), ("KWDA", struct.pack("<I", orc.LOC_TYPE_OVERLAY)),
                                      ("PNAM", struct.pack("<I", orc.MARS_SURFACE))]))
        body.append(rec("SFBK", blk, [("EDID", zs(o["block"])), ("ANAM", zs(o["btd_path"])),
                                      ("DNAM", struct.pack("<2I", o["n"], o["n"])),
                                      ("ENAM", struct.pack("<2f", prm["hmin"], prm["hmax"])),
                                      ("FNAM", struct.pack(f"<{len(o['fnam'])}H", *o["fnam"])),
                                      ("INAM", bytes([1 if prm["alignment"] == "absolute" else 0])),
                                      ("HNAM", struct.pack("<h", prm["hnam"]))]))
        body.append(rec("WRLD", w, [("EDID", zs(o["world"])), ("XLCN", struct.pack("<I", loc)),
                                    ("BFCB", zs("BGSWorldSpaceOverlay_Component")), ("BNAM", struct.pack("<I", blk)),
                                    ("BFCE", b"")]))
        body.append(rec("CELL", own | (0xA00 + k), [("EDID", zs(o["coc"])),
                                                    ("XCLC", struct.pack("<2iI", *o["spawn_cell"], 0))]))
        body.append(rec("REFR", own | (0xB00 + k), [("EDID", zs(o["coc"] + "Marker")),
                                                    ("NAME", struct.pack("<I", mco.COC_MARKER)),
                                                    ("DATA", struct.pack("<6f", *o["spawn"], 0.0, 0.0, 0.0))]))
        body.append(rec("REFR", own | o["anchor"]["form_id"],
                        [("EDID", zs(o["anchor"]["edid"])), ("NAME", struct.pack("<I", orc.XMARKER)),
                         ("DATA", struct.pack("<6f", *o["anchor"]["local"], 0.0, 0.0, 0.0))],
                        flags=orc.PERSISTENT if persistent else 0))
        la, lo = o["latitude"], o["longitude"]
        ents.append((lo, la, own | (w & 0xFFFFFF)) if swap_latlon else (la, lo, own | (w & 0xFFFFFF)))
    with open(os.path.join(out, prm["plugin"]), "wb") as f:
        f.write(rec("TES4", 0, [("MAST", zs("Starfield.esm"))]) + b"".join(body))
    cnam = b"".join(struct.pack("<ddI", *e) for e in ents)
    with open(os.path.join(out, prm["mars"]["plugin"]), "wb") as f:
        f.write(rec("TES4", 0, [("MAST", zs("Starfield.esm")), ("MAST", zs(prm["plugin"]))]) +
                rec("PNDT", orc.MARS_PNDT, [("EDID", zs("MarsPlanetData")), ("CNAM", b"\x01"), ("CNAM", cnam)]))


class SyntheticBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.npz = os.path.join(cls.tmp.name, "fo4.npz")
        synthetic_npz(cls.npz)
        cls.out = os.path.join(cls.tmp.name, "stage")
        os.makedirs(cls.out)
        cls._ltex = mco.ltex_source
        mco.ltex_source = lambda sf_data: ([0x001235C2], bytes([1, 0, 0, 0, 0, 0, 0, 0]))
        with contextlib.redirect_stdout(io.StringIO()):
            mco.build(build_args(cls.out, cls.npz))
        cls.prm = jload(os.path.join(cls.out, "overlays_params.json"))
        cls.plan = jload(os.path.join(cls.out, "plan.json"))

    @classmethod
    def tearDownClass(cls):
        mco.ltex_source = cls._ltex
        cls.tmp.cleanup()

    def test_layout(self):
        ovs = self.prm["overlays"]
        self.assertEqual([o["world"] for o in ovs], ["FO4CWT_T00", "FO4CWT_T10", "FO4CWT_T01", "FO4CWT_T11"])
        self.assertEqual([o["anchor"]["form_id"] for o in ovs], [0x800, 0x801, 0x802, 0x803])
        self.assertEqual([o["anchor"]["ref"] for o in ovs], ["02000800", "02000801", "02000802", "02000803"])
        self.assertEqual(ovs[0]["cells_cw"], {"x": [-5, -1], "y": [-5, -1]})
        self.assertEqual([o["planet_target_cell"] for o in ovs], [[-3, -3], [2, -3], [-3, 2], [2, 2]])
        # mask row order is unresolved: north / south rings only in pairs, so every tile of a 2 x 2 grid keeps 0 on its
        # outer north / south edge and a flipped row order cannot put 255 on the y seam
        self.assertEqual([o["mask_outer_edges"] for o in ovs], [["w"], ["e"], ["w"], ["e"]])
        self.assertEqual(len({o["location"] for o in ovs}), 4)
        for o in ovs:
            self.assertEqual(len(o["fnam"]), 25)
            self.assertEqual(o["spawn"][2], round(o["anchor"]["local"][2] + 2.0, 4))

    def test_tiles_equal_one_big_btd(self):
        """Edge matching: the four tiles' raw samples, side by side, are exactly the samples of one 10 x 10-cell BTD
        of the same region with the same height range."""
        fo4 = mco.Fo4Heights(npz=self.npz)
        big = og.Tile(0, 0, -5, -5, 10)
        want = btd.quantize(mco.tile_heights(fo4, big), self.prm["hmin"], self.prm["hmax"])
        got = np.zeros_like(want)
        for o in self.prm["overlays"]:
            t = btd.read(rbytes(os.path.join(self.out, *o["btd_file"].split("/"))))
            r0 = (o["cells_cw"]["y"][0] + 5) * 128
            c0 = (o["cells_cw"]["x"][0] + 5) * 128
            got[r0:r0 + 640, c0:c0 + 640] = t.heights_raw
            self.assertEqual((t.hmin, t.hmax), (self.prm["hmin"], self.prm["hmax"]))
        self.assertTrue((got == want).all())

    def test_plan_entries(self):
        kinds = [mco.entry_kind(e["label"]) for e in self.plan]
        self.assertEqual(kinds, ["tile"] * 4 + ["group"] + ["locate"] * 3 + ["edges"])
        ovs = {o["anchor"]["ref"]: o for o in self.prm["overlays"]}
        first = self.prm["overlays"][0]
        for e in self.plan:
            o = ovs[e["anchor"]["ref"]]
            # every entry is read in the coc'd tile's own frame; the merge offset comes from that tile's spawn (x, y
            # only: a spawn read mid-fall must not move the drops); no entry depends on another tile's anchor
            self.assertEqual(e["coc"], o["coc"])
            self.assertEqual(e["spawn_local"], o["anchor"]["local"][:2])
            labels = [p["label"] for p in e["points"]]
            self.assertIn(e["z_ref"], labels)
            self.assertTrue(e["z_ref"].startswith("centre_T"))
            self.assertGreaterEqual(e["drop_z"], max(p["expect"] for p in e["points"]) + mco.DROP_MARGIN)
            low = min(p["expect"] for p in e["points"])
            self.assertGreaterEqual(e["settle_ms"], 1000 * mco.fall_seconds(e["drop_z"], low))
        for e in self.plan[4:]:
            self.assertEqual(e["coc"], first["coc"])
        group = self.plan[4]
        self.assertEqual(sum(1 for p in group["points"] if "_near_" in p["label"] or "_ring_" in p["label"]
                             or "_inner_" in p["label"]), 4 * 3 * 2)      # 4 seam segments x 3 distances x 2 sides
        for e in self.plan[5:8]:                                         # locate: clear the whole shared range
            self.assertGreaterEqual(e["drop_z"], self.prm["hmax"] + mco.DROP_MARGIN)
            self.assertGreaterEqual(e["settle_ms"], 1000 * mco.fall_seconds(e["drop_z"], self.prm["hmin"]))
        tiles = {o["anchor"]["ref"]: og.Tile(o["ix"], o["iy"], o["cells_cw"]["x"][0], o["cells_cw"]["y"][0], o["n"])
                 for o in self.prm["overlays"]}
        step = tg.FO4_VERTEX_UNITS / tg.UNITS_PER_METRE
        for e in self.plan:
            ft = tiles[e["anchor"]["ref"]]
            here = e["spawn_local"]
            for p in e["points"]:
                x, y = ft.to_cw(p["x"], p["y"])
                self.assertAlmostEqual(x / step, round(x / step), places=2)   # every point is an FO4 vertex
                self.assertAlmostEqual(y / step, round(y / step), places=2)
                self.assertLessEqual(math.hypot(p["x"] - here[0], p["y"] - here[1]), 1.25 * mco.MAX_JUMP)
                here = [p["x"], p["y"]]

    def test_locate_transects(self):
        exp = jload(os.path.join(self.out, "expected.json"))
        tiles = [og.Tile(o["ix"], o["iy"], o["cells_cw"]["x"][0], o["cells_cw"]["y"][0], o["n"])
                 for o in self.prm["overlays"]]
        for e in exp["entries"]:
            if e["kind"] != "locate":
                continue
            loc = [p for p in e["points"] if p["kind"] == "locate"]
            tag = loc[0]["transect"][1:]
            target = next(t for t in tiles if t.tag == tag)
            inside = [p for p in loc if og.tile_at(tiles, p["x_cw"], p["y_cw"]) is target]
            self.assertGreaterEqual(len(inside), 3)                     # enough probes to identify the tile
            for p in loc:                                               # all away from every merge ring
                t = og.tile_at(tiles, p["x_cw"], p["y_cw"])
                self.assertGreaterEqual(mco.edge_distance(t, p["x_cw"], p["y_cw"]), mco.EDGE_KEEP - 15)

    def test_edges_entry(self):
        e = self.plan[-1]
        lab = [p["label"] for p in e["points"]]
        # T00 is the south-west tile: outer edges w (mask 255) and s (mask 0 in symmetric mode)
        self.assertEqual(sorted(x for x in lab if x.startswith("edge_")),
                         ["edge_s0_inner", "edge_s0_ring_1", "edge_s0_ring_2",
                          "edge_w255_inner", "edge_w255_ring_1", "edge_w255_ring_2"])
        exp = jload(os.path.join(self.out, "expected.json"))
        for p in exp["entries"][-1]["points"]:
            if p["kind"] == "edge":
                lo, hi = mco.DIST[p["distance_class"]]
                self.assertTrue(lo <= p["distance_to_edge_m"] <= hi, p)

    def test_seam_pairs_both_sides(self):
        exp = jload(os.path.join(self.out, "expected.json"))
        seam_pts = [p for pts in exp["points"].values() for p in pts if p["kind"] == "seam"]
        self.assertEqual(len(seam_pts), 24)
        for p in seam_pts:
            lo, hi = mco.DIST[p["distance_class"]]
            self.assertTrue(lo <= p["distance_to_seam_m"] <= hi, p)
        by = {}
        for p in seam_pts:
            by.setdefault((p["seam"], p["distance_class"]), {})[p["side"]] = p
        self.assertEqual(len(by), 12)
        for (seam, cls), d in by.items():
            self.assertEqual(set(d), {"a", "b"})
            along = "y_cw" if seam.count("|") else "x_cw"           # 'x' seams (|) pair along y
            self.assertEqual(d["a"][along], d["b"][along])
            self.assertNotEqual(d["a"]["tile"], d["b"]["tile"])

    def test_offline_check_passes(self):
        ok, rep = mco.check_staging(self.out, self.prm, self.plan, None, plugins=False)
        failed = [c for c in rep["checks"] if not c[1]]
        self.assertTrue(ok, failed[:5])
        self.assertEqual(rep["summary"]["failed"], 0)
        self.assertTrue(all(s["bad"] == 0 for s in rep["seams"]))
        self.assertLessEqual(rep["summary"]["max_point_error_mm"], rep["summary"]["step_mm"])

    def test_strips_equal_one_resample(self):
        """Large overlays are resampled in row strips; the result must be the same as one call, bit for bit."""
        fo4 = mco.Fo4Heights(npz=self.npz)
        t = og.Tile(0, 0, -5, -5, 5)
        whole = mco.tile_heights(fo4, t)
        got = np.full_like(whole, np.nan)
        for r0, h in mco.tile_strips(fo4, t, rows=100):            # 640 rows: six strips of 100 and one of 40
            got[r0:r0 + h.shape[0]] = h
        self.assertTrue((got == whole).all())

    def test_decode_window_matches_full_grid(self):
        rng = np.random.default_rng(5)
        raw = rng.integers(0, 65535, size=(3 * 128, 3 * 128)).astype(np.uint16)
        hmin, hmax = -40.0, 299.0
        full = hmin + raw.astype(np.float64) / 65535.0 * (hmax - hmin)
        o = tg.grid_origin(3)
        pts = [(o, o), (o + 299.9, o + 299.9), (o - 5.0, 12.3), (151.0, o + 400.0), (0.0, 0.0)]
        pts += [tuple(v) for v in rng.uniform(o - 2, o + 302, size=(40, 2))]
        for x, y in pts:
            a = mco.decode_at(raw, hmin, hmax, 3, x, y)
            b = tg.point_interp(full, o, o, tg.SF_STEP_M, x, y)
            for k in b:
                self.assertAlmostEqual(a[k], b[k], places=9)

    def test_single_overlay(self):
        """Option (a): a tile at least as large as the region gives one overlay, ring on all four edges, no seams."""
        out = os.path.join(self.tmp.name, "single")
        os.makedirs(out)
        with contextlib.redirect_stdout(io.StringIO()):
            mco.build(build_args(out, self.npz, tile=10, prefix="FO4CWS", experiment="terrain_single", pad="origin",
                                 grid_points=2))
        prm = jload(os.path.join(out, "overlays_params.json"))
        plan = jload(os.path.join(out, "plan.json"))
        self.assertEqual(len(prm["overlays"]), 1)
        o = prm["overlays"][0]
        self.assertEqual((o["n"], o["cells_cw"]), (10, {"x": [-5, 4], "y": [-5, 4]}))
        self.assertEqual(o["mask_outer_edges"], ["w", "e", "s", "n"])
        self.assertEqual(o["planet_target_cell"], [0, 0])          # the region's centre = the overlay's own origin
        self.assertEqual(o["origin_cw_m"], [0.0, 0.0])             # pad origin: local frame = CW frame
        self.assertEqual(len(plan), 1)
        self.assertEqual(sum(1 for p in plan[0]["points"] if p["label"].startswith("grid_T00_")), 4)
        ok, rep = mco.check_staging(out, prm, plan, None, plugins=False)
        self.assertTrue(ok, [c for c in rep["checks"] if not c[1]][:5])
        self.assertEqual(rep["seams"], [])

    def test_check_catches_entry_contract_errors(self):
        for mutate in (lambda e: e.update(spawn_local=e["spawn_local"] + [0.0]),   # z would shift the drops
                       lambda e: e.update(z_ref="nowhere"),
                       lambda e: e.update(settle_ms=1000),
                       lambda e: e.update(drop_z=e["drop_z"] - 30.0),
                       lambda e: e.update(coc=self.plan[1]["coc"])):             # points not in the coc'd frame
            plan = json.loads(json.dumps(self.plan))
            mutate(plan[0])
            ok, rep = mco.check_staging(self.out, self.prm, plan, None, plugins=False)
            self.assertFalse(ok)

    def test_check_plugins_record_walk(self):
        """check_plugins (raw walk of both plugins) on minimal synthetic plugins: passes, and fails on a swapped
        lat/long entry and on an anchor that is not persistent."""
        good, _ = self._plugins_check()
        self.assertTrue(good)
        self.assertFalse(self._plugins_check(swap_latlon=True)[0])
        self.assertFalse(self._plugins_check(persistent=False)[0])

    def _plugins_check(self, **kw):
        write_plugins(self.out, self.prm, **kw)
        try:
            ok, rep = mco.check_staging(self.out, self.prm, self.plan, 2, plugins=True)
        finally:
            for name in (self.prm["plugin"], self.prm["mars"]["plugin"]):
                os.remove(os.path.join(self.out, name))
        if not kw:
            self.assertEqual(rep["mars"]["entries"], 2 + 4)
            self.assertEqual([m["f64_0_latitude"] for m in rep["mars"]["ours"]],
                             [o["latitude"] for o in self.prm["overlays"]])
        return ok, rep

    def _raws(self):
        return {o["tag"]: btd.read(rbytes(os.path.join(self.out, *o["btd_file"].split("/")))).heights_raw
                for o in self.prm["overlays"]}

    def test_analyse_locates_tiles_off_h_ll(self):
        """A landing where H_ll is wrong for T10 (one cell further east), right for T01, and T11 is missing: the
        locate entries find T10 and T01 where they are, the anchors read their local position, the spawn is read
        mid-fall, and the Z offset comes from the z_ref probe."""
        ovs = self.prm["overlays"]
        pred = {o["tag"]: tuple(o["planet_target_cell"]) for o in ovs}
        place = {"00": pred["00"], "10": (pred["10"][0] + 1, pred["10"][1]), "01": pred["01"]}
        raws = self._raws()
        res = {}
        for n, e in enumerate(self.plan):
            if mco.entry_kind(e["label"]) == "locate":
                obs = simulate(self.prm, raws, e, place, z_offset=2.5)
                r = mco.analyse_attempt(spec_of(e, n), obs, self.prm, raws, window=4)
                res[e["label"].split()[2]] = r
                self.assertEqual(r["spawn_offset_cells"], pred["00"])
                self.assertTrue(r["anchor_unmerged"])
                self.assertAlmostEqual(r["z_offset_m"], 2.5, places=1)
                self.assertEqual(r["locate"]["T00"]["best"]["d"], (0, 0))
        self.assertEqual(res["T10"]["locate"]["T10"]["predicted"], [5, 0])
        self.assertEqual(res["T10"]["locate"]["T10"]["best"]["d"], (6, 0))
        self.assertEqual(res["T01"]["locate"]["T01"]["best"]["d"], (0, 5))
        self.assertIsNone(res["T11"]["locate"]["T11"]["best"])

    def test_analyse_own_tile_shift(self):
        """A wrong grid-origin rule moves a BTD one cell against its own frame: the tile entry's own-tile search finds
        (1, 0) instead of (0, 0)."""
        raws = self._raws()
        e = self.plan[0]
        place = {"00": tuple(self.prm["overlays"][0]["planet_target_cell"])}
        ok = mco.analyse_attempt(spec_of(e, 0), simulate(self.prm, raws, e, place), self.prm, raws, window=2)
        self.assertEqual(ok["locate"]["T00"]["best"]["d"], (0, 0))
        self.assertEqual(ok["summary"]["within_0.5m"], ok["summary"]["of"])
        bad = mco.analyse_attempt(spec_of(e, 0), simulate(self.prm, raws, e, place, own_shift=(1, 0)), self.prm, raws,
                                  window=2)
        self.assertEqual(bad["locate"]["T00"]["best"]["d"], (1, 0))

    def test_analyse_reads_runner_folders(self):
        raws = self._raws()
        q = os.path.join(self.tmp.name, "queue")
        place = {o["tag"]: tuple(o["planet_target_cell"]) for o in self.prm["overlays"]}
        for n, e in enumerate(self.plan[4:6], start=4):
            d = os.path.join(q, "tests", f"{n:04d}_terrain_{e['coc']}", "a1")
            os.makedirs(d)
            with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
                json.dump(spec_of(e, n), f)
            with open(os.path.join(d, "obs.json"), "w", encoding="utf-8-sig") as f:     # PowerShell writes a BOM
                json.dump(simulate(self.prm, raws, e, place), f)
        runs = mco.load_runs([q])
        self.assertEqual(len(runs), 2)
        a = argparse.Namespace(out=self.out, runs=[q], tol=0.5, window=3, free_z=False,
                               json=os.path.join(self.tmp.name, "analysis.json"))
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(mco.analyse(a), 0)
        self.assertIn("T10: predicted (5, 0); found at (5, 0)", buf.getvalue())
        self.assertEqual(len(jload(a.json)), 2)

    def test_check_catches_a_wrong_expectation(self):
        plan = json.loads(json.dumps(self.plan))
        plan[0]["points"][0]["expect"] += 0.05
        ok, rep = mco.check_staging(self.out, self.prm, plan, None, plugins=False)
        self.assertFalse(ok)

    def test_check_catches_a_seam_step(self):
        o = self.prm["overlays"][1]
        path = os.path.join(self.out, *o["btd_file"].split("/"))
        orig = rbytes(path)
        try:
            t = btd.read(orig)
            raw = t.heights_raw.astype(np.int64)
            raw[:, 0] = np.clip(raw[:, 0] + 3000, 0, 65535)          # a 3000-step cliff along the west seam
            t.heights_raw = raw.astype(np.uint16)
            with open(path, "wb") as f:
                f.write(btd.write(t))
            ok, rep = mco.check_staging(self.out, self.prm, self.plan, None, plugins=False)
            self.assertFalse(ok)
            self.assertTrue(any(s["bad"] > 0 for s in rep["seams"]))
        finally:
            with open(path, "wb") as f:
                f.write(orig)


class Rays(unittest.TestCase):
    def test_nearest_ray_and_parse(self):
        self.assertEqual(mco.nearest_ray(mco.RAYS, 170.0), "w")
        self.assertEqual(mco.nearest_ray(mco.RAYS, -170.0), "w")             # wraps across 180
        self.assertEqual(mco.nearest_ray(mco.RAYS, -45.0), "se")
        self.assertEqual(mco.nearest_ray(mco.RAYS, 100.0), "nw")
        self.assertEqual(mco.parse_rays("a:1, b2:-2.5"), (("a", 1.0), ("b2", -2.5)))
        for bad in ("a", "a:1,a:2", "A B:3"):
            with self.assertRaises(ValueError):
                mco.parse_rays(bad)

    def test_latlon_cells(self):
        k = og.cells_per_radian(og.MARS_RADIUS_KM)
        self.assertAlmostEqual(mco.latlon_cells((0.3, -1.2), (0.3 + 10 / k, -1.2)), 10.0, places=6)
        self.assertAlmostEqual(mco.latlon_cells((0.0, math.pi - 1e-4), (0.0, -math.pi + 1e-4)), 2e-4 * k, places=3)


class SingleOverlayRays(unittest.TestCase):
    """--plan rays (terrain_core64): one overlay, one coc arrival per entry, probes at increasing distance from the
    arrival in one direction each, the BTD also staged under meshes/terrain."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.npz = os.path.join(cls.tmp.name, "fo4.npz")
        synthetic_npz(cls.npz)
        cls.out = os.path.join(cls.tmp.name, "rays")
        os.makedirs(cls.out)
        cls._ltex = mco.ltex_source
        mco.ltex_source = lambda sf_data: ([0x001235C2], bytes([1, 0, 0, 0, 0, 0, 0, 0]))
        with contextlib.redirect_stdout(io.StringIO()):
            mco.build(build_args(cls.out, cls.npz, tile=10, pad="origin", prefix="FO4CR", experiment="terrain_rays",
                                 plugin="FO4TerrainRays.esm", mars_plugin="FO4TerrainRays_Mars.esm",
                                 world="FO4CR_Commonwealth", coc="FO4CR_TestSpawn", btd_copy_meshes=True, plan="rays",
                                 rays=mco.RAYS, ray_distances=[0.0, 60.0, 150.0, 300.0, 600.0], edge_keep=100.0,
                                 ref_lat=0.3, ref_lon=-1.2, ref_offset=[-12, -27], centre_cell=[-12, -27]))
        cls.prm = jload(os.path.join(cls.out, "overlays_params.json"))
        cls.plan = jload(os.path.join(cls.out, "plan.json"))
        cls.o = cls.prm["overlays"][0]

    @classmethod
    def tearDownClass(cls):
        mco.ltex_source = cls._ltex
        cls.tmp.cleanup()

    def test_names_and_registration(self):
        o = self.o
        self.assertEqual((o["world"], o["coc"], o["location"], o["block"]),
                         ("FO4CR_Commonwealth", "FO4CR_TestSpawn", "FO4CR_CommonwealthLocation", "FO4CR_CommonwealthBlock"))
        self.assertEqual(o["btd_file"], "Data/Terrain/FO4CR_Commonwealth.btd")
        self.assertEqual(o["btd_copies"], ["Data/meshes/terrain/FO4CR_Commonwealth.btd"])
        self.assertEqual(o["mask_outer_edges"], ["w", "e", "s", "n"])
        self.assertEqual((o["latitude"], o["longitude"]), mco.EXP2B_LATLON)   # exp2b's registration, unchanged
        self.assertEqual(self.prm["plan_mode"], "rays")
        self.assertEqual(rbytes(os.path.join(self.out, *o["btd_file"].split("/"))),
                         rbytes(os.path.join(self.out, *o["btd_copies"][0].split("/"))))

    def test_ray_entries(self):
        o, t = self.o, og.Tile(0, 0, -5, -5, 10)
        self.assertEqual([mco.entry_kind(e["label"]) for e in self.plan], ["ray"] * len(mco.RAYS))
        for e, (name, deg) in zip(self.plan, mco.RAYS):
            self.assertEqual(sorted(e), sorted(mco.RAY_PLAN_KEYS))            # runner format, no anchor
            self.assertEqual(e["coc"], o["coc"])
            self.assertEqual(e["spawn_local"], o["anchor"]["local"])           # the marker's ground, x y z
            p0 = e["points"][0]
            self.assertEqual((e["z_ref"], [p0["x"], p0["y"], p0["expect"]]), ("arrival", o["anchor"]["local"]))
            d = [math.hypot(p["x"] - p0["x"], p["y"] - p0["y"]) for p in e["points"]]
            self.assertEqual(d, sorted(d))
            labels = [p["label"] for p in e["points"]]
            self.assertEqual(labels, ["arrival"] + [f"{name}_{v:g}m" for v in (60, 150, 300)])   # 600 m is outside
            exp = {p["label"]: p for en in jload(os.path.join(self.out, "expected.json"))["entries"] for p in en["points"]}
            self.assertTrue(all(exp[p["label"]]["slope_deg"] <= mco.MAX_SLOPE for p in e["points"]))
            snap = 16 * math.sqrt(2) * tg.FO4_VERTEX_UNITS / tg.UNITS_PER_METRE   # snap radius (flat preferred)
            for p, want in zip(e["points"][1:], (60, 150, 300)):
                ideal = (p0["x"] + want * math.cos(math.radians(deg)), p0["y"] + want * math.sin(math.radians(deg)))
                self.assertLessEqual(math.hypot(p["x"] - ideal[0], p["y"] - ideal[1]), snap + 1e-6)
                self.assertGreaterEqual(mco.edge_distance(t, p["x"], p["y"]), 100.0)
            self.assertGreaterEqual(e["drop_z"], max(p["expect"] for p in e["points"]) + mco.DROP_MARGIN)
            low = min(p["expect"] for p in e["points"])
            self.assertGreaterEqual(e["settle_ms"], 1000 * mco.fall_seconds(e["drop_z"], low))
            self.assertGreaterEqual(e["settle_ms"], 8000)

    def test_offline_check_passes_and_catches(self):
        ok, rep = mco.check_staging(self.out, self.prm, self.plan, None, plugins=False)
        self.assertTrue(ok, [c for c in rep["checks"] if not c[1]][:5])
        ai = rep["archive_inputs"]
        self.assertEqual(ai["folders"], ["Terrain", "meshes", "textures"])
        self.assertEqual(len(ai["files"]), 3)
        x0 = self.o["anchor"]["local"]
        for mutate in (lambda e: e.update(spawn_local=x0[:2]),                       # ground z missing
                       lambda e: e.update(spawn_local=[x0[0], x0[1], x0[2] + 5.0]),
                       lambda e: e.update(z_ref=e["points"][1]["label"]),
                       lambda e: e.update(points=[e["points"][0]] + e["points"][:0:-1]),   # decreasing distance
                       lambda e: e["points"][-1].update(x=470.0),                     # 30 m from the east edge
                       lambda e: e["points"][1].update(expect=e["points"][1]["expect"] + 0.05),
                       lambda e: e.update(label="terrain_rays tile x"),
                       lambda e: e.update(coc="FO4CR_OtherSpawn")):
            plan = json.loads(json.dumps(self.plan))
            mutate(plan[2])
            ok, rep = mco.check_staging(self.out, self.prm, plan, None, plugins=False)
            self.assertFalse(ok)

    def test_archive_inputs_catch_a_bad_copy_and_a_stray_file(self):
        copy = os.path.join(self.out, *self.o["btd_copies"][0].split("/"))
        orig = rbytes(copy)
        try:
            with open(copy, "ab") as f:
                f.write(b"\0")
            self.assertFalse(mco.check_staging(self.out, self.prm, self.plan, None, plugins=False)[0])
        finally:
            with open(copy, "wb") as f:
                f.write(orig)
        stray = os.path.join(self.out, "Data", "Terrain", "stray.btd")
        try:
            with open(stray, "wb") as f:
                f.write(b"x")
            self.assertFalse(mco.check_staging(self.out, self.prm, self.plan, None, plugins=False)[0])
        finally:
            os.remove(stray)
        self.assertTrue(mco.check_staging(self.out, self.prm, self.plan, None, plugins=False)[0])

    def test_cnam_entry_unique_and_clear_of_others(self):
        lat, lon = self.o["latitude"], self.o["longitude"]
        k = og.cells_per_radian(og.MARS_RADIUS_KM)
        for vanilla, good in (([(0.1, 0.2, 0x0001000A)], True),
                              ([(lat, lon, 0x0001000A)], False),                      # same lat / long
                              ([(lat + 3.0 / k, lon, 0x0001000A)], False)):            # 3 cells away: overlaps
            write_plugins(self.out, self.prm, vanilla=vanilla)
            try:
                ok, rep = mco.check_staging(self.out, self.prm, self.plan, 1, plugins=True)
            finally:
                for name in (self.prm["plugin"], self.prm["mars"]["plugin"]):
                    os.remove(os.path.join(self.out, name))
            self.assertEqual(ok, good, [c for c in rep["checks"] if not c[1]][:5])

    def test_analyse_reads_a_ray_entry(self):
        raws = {self.o["tag"]: btd.read(rbytes(os.path.join(self.out, *self.o["btd_file"].split("/")))).heights_raw}
        e = self.plan[0]
        obs = simulate(self.prm, raws, e, {self.o["tag"]: (-12, -27)}, spawn_z=self.o["anchor"]["local"][2])
        r = mco.analyse_attempt(spec_of(e, 0), obs, self.prm, raws, window=2)
        self.assertEqual(r["frame"], "T00")
        self.assertEqual(tuple(r["spawn_offset_cells"]), (-12, -27))
        self.assertEqual(r["summary"]["within_0.5m"], len(e["points"]))
        self.assertEqual(r["summary"]["hung"], 0)
        self.assertEqual([p["from_spawn_m"] for p in r["points"]][0], 0.0)
        self.assertEqual(tuple(r["locate"]["T00"]["best"]["d"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
