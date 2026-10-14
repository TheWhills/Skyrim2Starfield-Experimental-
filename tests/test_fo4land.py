"""Synthetic-fixture tests for the Fallout 4 LAND reader: every plugin byte is built here; no game data is needed."""
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import fo4land  # noqa: E402

G = fo4land.GRID


def rec(typ, fid, fields, compress=False):
    data = b"".join(sig + struct.pack("<H", len(d)) + d for sig, d in fields)
    flags = 0
    if compress:
        data = struct.pack("<I", len(data)) + zlib.compress(data)
        flags = fo4land.COMPRESSED
    return typ + struct.pack("<III", len(data), flags, fid) + b"\0" * 8 + data


def grup(label, gtype, items):
    body = b"".join(items)
    if isinstance(label, int):
        label = struct.pack("<I", label)
    return b"GRUP" + struct.pack("<I4si", 24 + len(body), label, gtype) + b"\0" * 8 + body


def refr(fid, base, pos, rot=(0.0, 0.0, 0.0)):
    return rec(b"REFR", fid, [(b"NAME", struct.pack("<I", base)), (b"DATA", struct.pack("<6f", *pos, *rot))])


def plane_steps(cx, cy, ax=1, ay=2):
    """Integer 8-unit steps of the plane z = ax * global_col + ay * global_row (cell-relative to its own offset)."""
    r, c = np.mgrid[0:G, 0:G]
    return ax * c + ay * r


def plane_offset(cx, cy, base=100, ax=1, ay=2):
    return float(base + ax * 32 * cx + ay * 32 * cy)


def plane_height(x, y, base=100, ax=1, ay=2):
    return 8.0 * (base + ax * x / 128.0 + ay * y / 128.0)


def build_plugin(cells, persistent_refs=(), stat_obnd=(-50, -50, 0, 60, 60, 300), compress_land=True):
    """cells: {(x, y): (vhgt_bytes, [ref bytes])}. World 'TestWorld' (0x3C) with a persistent cell at XCLC (0, 0)."""
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.0, 0, 0))])
    stats = grup(b"STAT", 0, [rec(b"STAT", 0x100, [(b"EDID", b"RockM01\0"), (b"OBND", struct.pack("<6h", *stat_obnd))]),
                              rec(b"STAT", 0x101, [(b"EDID", b"TestBuilding\0"),
                                                   (b"OBND", struct.pack("<6h", -200, -300, 0, 250, 300, 500))])])
    pcell = rec(b"CELL", 0x200, [(b"EDID", b"\0"), (b"XCLC", struct.pack("<iiI", 0, 0, 0))])
    world_items = [pcell, grup(0x200, 6, [grup(0x200, 8, list(persistent_refs))])]
    sub = []
    fid = 0x400
    for (x, y), (vhgt, refs) in sorted(cells.items()):
        cfid, lfid = fid, fid + 1
        fid += 2
        sub.append(rec(b"CELL", cfid, [(b"DATA", b"\0\0"), (b"XCLC", struct.pack("<iiI", x, y, 0))], compress=True))
        land = rec(b"LAND", lfid, [(b"DATA", b"\0" * 4), (b"VHGT", vhgt)], compress=compress_land)
        sub.append(grup(cfid, 6, [grup(cfid, 9, [land] + list(refs))]))
    world_items.append(grup(b"\0\0\0\0", 4, [grup(b"\0\0\0\0", 5, sub)]))
    wrld = rec(b"WRLD", 0x3C, [(b"EDID", b"TestWorld\0"), (b"DNAM", struct.pack("<ff", 0.0, 450.0))])
    other = rec(b"WRLD", 0x3D, [(b"EDID", b"OtherWorld\0")])
    worlds = grup(b"WRLD", 0, [other, grup(0x3D, 1, []), wrld, grup(0x3C, 1, world_items)])
    return tes4 + stats + worlds


class VhgtTests(unittest.TestCase):
    def test_hand_decoded_gradients(self):
        g = np.zeros((G, G), dtype=np.int8)
        g[0, 0], g[1, 0], g[0, 1], g[1, 1], g[0, 2] = 1, 2, 3, -1, -5
        data = struct.pack("<f", 10.0) + g.tobytes() + b"\0\0\0"
        h = fo4land.decode_vhgt(data)
        # row 0 (south): 1, 1+3, 1+3-5 ; row 1 starts at 1+2 and continues west->east from there
        self.assertEqual(h[0, 0], 8 * (10 + 1))
        self.assertEqual(h[0, 1], 8 * (10 + 4))
        self.assertEqual(h[0, 2], 8 * (10 - 1))
        self.assertEqual(h[1, 0], 8 * (10 + 3))
        self.assertEqual(h[1, 1], 8 * (10 + 2))
        self.assertEqual(h[1, 2], 8 * (10 + 2))
        self.assertEqual(h[32, 32], 8 * (10 + 3))

    def test_round_trip_negative_offset_and_large_range(self):
        g = np.random.default_rng(1).integers(-128, 128, (G, G))  # full signed-byte gradient range
        steps = np.empty((G, G), dtype=np.int64)
        steps[:, 0] = np.cumsum(g[:, 0])
        steps[:, 1:] = steps[:, :1] + np.cumsum(g[:, 1:], axis=1)
        data = fo4land.encode_vhgt(-1234.0, steps)
        self.assertEqual(data[4:4 + G * G], g.astype(np.int8).tobytes())
        self.assertEqual(len(data), 1096)
        np.testing.assert_array_equal(fo4land.decode_vhgt(data), 8.0 * (-1234.0 + steps))

    def test_short_vhgt_rejected(self):
        with self.assertRaises(ValueError):
            fo4land.decode_vhgt(b"\0" * (fo4land.VHGT_MIN_SIZE - 1))

    def test_encode_rejects_out_of_range_gradient(self):
        steps = np.zeros((G, G), dtype=int)
        steps[0, 1] = 200
        with self.assertRaises(ValueError):
            fo4land.encode_vhgt(0.0, steps)


class GeometryTests(unittest.TestCase):
    def test_cell_of_negative_coordinates(self):
        self.assertEqual(fo4land.cell_of(-1, -1), (-1, -1))
        self.assertEqual(fo4land.cell_of(-4096, 0), (-1, 0))
        self.assertEqual(fo4land.cell_of(-4096.5, 4095.9), (-2, 0))
        self.assertEqual(fo4land.cell_of(-69232, 80304), (-17, 19))

    def plane_grids(self, x0, y0):
        return {(x, y): 8.0 * (plane_offset(x - x0, y - y0) + plane_steps(x, y))
                for x in (x0, x0 + 1) for y in (y0, y0 + 1)}

    def test_merge_plane_is_exact_and_edges_match(self):
        merged, rep = fo4land.merge_cells(self.plane_grids(-3, -5), -3, -5, 2, 2)
        self.assertEqual(merged.shape, (65, 65))
        r, c = np.mgrid[0:65, 0:65]
        np.testing.assert_array_equal(merged, 8.0 * (100 + c + 2 * r))
        self.assertEqual(rep["east_west_max_abs"], 0.0)
        self.assertEqual(rep["north_south_max_abs"], 0.0)
        self.assertEqual((rep["east_west_pairs"], rep["north_south_pairs"]), (2, 2))

    def test_merge_reports_edge_mismatch(self):
        grids = self.plane_grids(0, 0)
        grids[(1, 0)][5, 0] += 8.0
        grids[(0, 1)][0, 7] -= 16.0
        _m, rep = fo4land.merge_cells(grids, 0, 0, 2, 2)
        self.assertEqual(rep["east_west_max_abs"], 8.0)
        self.assertEqual(rep["north_south_max_abs"], 16.0)
        allp = fo4land.edge_mismatches(grids)
        self.assertEqual((allp["pairs"], allp["max_abs"], allp["mismatched_vertices"]), (4, 16.0, 2))
        self.assertEqual(sorted((m["cell"], m["neighbour"]) for m in allp["mismatches"]),
                         [([0, 0], [0, 1]), ([0, 0], [1, 0])])

    def test_height_at_on_plane_and_saddle(self):
        merged = 8.0 * (100 + np.mgrid[0:65, 0:65][1] + 2 * np.mgrid[0:65, 0:65][0])
        ox, oy = -3 * 4096.0, -5 * 4096.0
        for m in ("bilinear", "tri_sw_ne", "tri_nw_se"):
            self.assertAlmostEqual(fo4land.height_at(merged, ox, oy, ox + 300.0, oy + 1000.0, m),
                                   plane_height(300.0, 1000.0))
        self.assertIsNone(fo4land.height_at(merged, ox, oy, ox - 1.0, oy))
        saddle = np.array([[0.0, 8.0], [8.0, 0.0]])
        self.assertAlmostEqual(fo4land.height_at(saddle, 0, 0, 64, 64), 4.0)
        self.assertAlmostEqual(fo4land.height_at(saddle, 0, 0, 64, 64, "tri_sw_ne"), 0.0)
        self.assertAlmostEqual(fo4land.height_at(saddle, 0, 0, 64, 64, "tri_nw_se"), 8.0)

    def test_slope_degrees(self):
        r, c = np.mgrid[0:9, 0:9]
        self.assertTrue(np.allclose(fo4land.slope_degrees(128.0 * c.astype(float)), 45.0))
        self.assertTrue(np.allclose(fo4land.slope_degrees(np.zeros((4, 4))), 0.0))


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, data):
        path = os.path.join(self.tmp.name, "Synthetic.esm")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_read_world_cells_land_refs_and_persistent_cell(self):
        steps = plane_steps(-1, -1)
        cells = {(-1, -1): (fo4land.encode_vhgt(-50.0, steps), [refr(0x900, 0x100, (-2048.0, -2048.0, 7.0))]),
                 (0, 0): (fo4land.encode_vhgt(3.0, steps), [])}
        path = self.write(build_plugin(cells, persistent_refs=[refr(0x901, 0x100, (-100.0, -100.0, 5.0))]))
        with fo4land.Plugin(path) as p:
            w = p.read_world("TestWorld")
            self.assertEqual(w["world_fid"], 0x3C)
            self.assertEqual(sorted(w["cells"]), [(-1, -1), (0, 0)])
            self.assertEqual(w["persistent_cell"]["fid"], 0x200)
            self.assertEqual([r["fid"] for r in w["persistent_cell"]["persistent_refs"]], [0x901])
            # the real (0, 0) cell is not replaced by the persistent cell that also says XCLC (0, 0)
            np.testing.assert_array_equal(fo4land.decode_vhgt(w["cells"][(0, 0)]["vhgt"]), 8.0 * (3.0 + steps))
            c = w["cells"][(-1, -1)]
            np.testing.assert_array_equal(fo4land.decode_vhgt(c["vhgt"]), 8.0 * (-50.0 + steps))
            self.assertEqual(c["refs"][0]["base"], 0x100)
            self.assertEqual(c["refs"][0]["pos"], [-2048.0, -2048.0, 7.0])
            only = p.read_world("TestWorld", cells={(-1, -1)})
            self.assertEqual(list(only["cells"]), [(-1, -1)])
            self.assertEqual(p.base_records(wanted={0x100}), {0x100: ("STAT", "RockM01", (-50, -50, 0, 60, 60, 300))})
            self.assertEqual(set(p.base_records(edid_regex="building")), {0x101})
            with self.assertRaises(KeyError):
                p.find_world("Missing")

    def test_patch_script_end_to_end_on_synthetic_plane(self):
        x0, y0 = -2, -1
        cells = {}
        fid = 0x800
        for i in range(2):
            for j in range(2):
                refs = []
                for k in range(3):  # grounded rocks exactly on the plane
                    lx, ly = 500.0 + 1000 * k, 700.0 + 900 * k
                    refs.append(refr(fid, 0x100, ((x0 + i) * 4096 + lx, (y0 + j) * 4096 + ly,
                                                  plane_height(i * 4096 + lx, j * 4096 + ly))))
                    fid += 1
                cells[(x0 + i, y0 + j)] = (fo4land.encode_vhgt(plane_offset(i, j), plane_steps(i, j)), refs)
        sx, sy = 4096.0 + 1000.0, 4096.0 + 1500.0
        cells[(x0 + 1, y0 + 1)][1].append(refr(0x7FF, 0x101, (x0 * 4096 + sx, y0 * 4096 + sy, plane_height(sx, sy))))
        path = self.write(build_plugin(cells))
        out = os.path.join(self.tmp.name, "out")
        script = os.path.join(ROOT, "scripts", "terrain", "fo4_land_patch.py")
        res = subprocess.run([sys.executable, script, "--esm", path, "--world", "TestWorld", "--x0", str(x0),
                              "--y0", str(y0), "--out", out, "--structure", "7FF", "--grounded-regex", "^Rock"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(os.path.join(out, "report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(rep["shared_edges"]["inside_patch"]["east_west_max_abs"], 0.0)
        self.assertEqual(rep["refs_in_cells"]["outside"], [])
        self.assertEqual(rep["refs_in_cells"]["checked"], 13)
        self.assertEqual(rep["grounded_refs"]["residual_units"]["n"], 12)
        self.assertLess(rep["grounded_refs"]["residual_units"]["max_abs"], 1e-3)
        self.assertLess(abs(rep["structure"]["z_minus_terrain_units"]), 1e-3)
        self.assertEqual(rep["structure"]["footprint_disc"]["radius_units"], 200.0)
        self.assertEqual(rep["cells"][0]["origin_units"], [x0 * 4096.0, y0 * 4096.0])
        ctl = rep["orientation_control"]
        self.assertLess(ctl["as_decoded"]["median_abs_residual_units"], 1e-3)
        self.assertGreater(ctl["north_south_flipped"]["median_abs_residual_units"], 10.0)
        merged = np.load(os.path.join(out, "merged_units.npy"))
        self.assertEqual(merged.shape, (65, 65))
        self.assertEqual(merged[0, 0], 8.0 * 100)
        self.assertTrue(os.path.getsize(os.path.join(out, "preview.png")) > 0)


if __name__ == "__main__":
    unittest.main()
