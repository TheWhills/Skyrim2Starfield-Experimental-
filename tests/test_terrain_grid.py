"""Synthetic tests for the FO4 -> Starfield terrain grid mapping and resampling (src/fo4sf/terrain_grid.py) and the
check-point selection of scripts/terrain/make_exp2.py. No game data: every grid here is made up."""
import importlib.util
import math
import os
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fo4sf import btd  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402


def load_make_exp2():
    spec = importlib.util.spec_from_file_location("make_exp2", ROOT / "scripts" / "terrain" / "make_exp2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GridRule(unittest.TestCase):
    def test_origin_matches_experiment_1(self):
        # experiment 1: 5 x 5 cells, SW corner at -200 m, cells -2..2
        self.assertEqual(tg.grid_origin(5), -200.0)
        self.assertEqual(tg.cell_range(5), (-2, 2))
        xs = tg.sample_coords(5)
        self.assertEqual(len(xs), 640)
        self.assertAlmostEqual(xs[1] - xs[0], 0.78125)
        self.assertAlmostEqual(xs[128], -100.0)          # first sample of the next cell lies on the cell border

    def test_odd_and_even_sizes(self):
        self.assertEqual(tg.grid_origin(29), -1400.0)
        self.assertEqual(tg.cell_range(29), (-14, 14))
        self.assertEqual(tg.cell_range(30), (-15, 14))
        self.assertAlmostEqual(tg.sample_coords(29)[-1], 1500.0 - 0.78125)

    def test_choose_n_off_centre_region(self):
        # the Red Rocket region (patch +- 300 m): far from the origin, so the grid must reach x -1353 and y +1470
        self.assertEqual(tg.choose_n(-1353.26, -636.23, 753.26, 1470.29), 29)
        self.assertEqual(tg.choose_n(-10, 10, -10, 10), 2)   # n = 1 starts at 0 m, so it cannot reach x = -10
        n = tg.choose_n(-120, 80, -50, 50)
        self.assertLessEqual(tg.grid_origin(n), -120)
        self.assertGreaterEqual(tg.sample_coords(n)[-1], 80)

    def test_choose_n_minimal(self):
        for region in ((-1353.26, -636.23, 753.26, 1470.29), (-50, 260, -10, 10), (0, 0.5, 0, 0.5)):
            n = tg.choose_n(*region)
            if n > 1:                                     # one size smaller must not cover the region
                m = n - 1
                covers = tg.grid_origin(m) <= min(region[0], region[2]) and \
                    tg.sample_coords(m)[-1] >= max(region[1], region[3])
                self.assertFalse(covers, (region, n))

    def test_choose_n_respects_vanilla_limit(self):
        with self.assertRaises(ValueError):
            tg.choose_n(-6000, 0, 0, 10)                  # needs > 100 x 100 cells

    def test_fo4_cells_covering(self):
        # -1400 m = -98000 units -> cell -24 (cells start at multiples of 4096); 1499.22 m -> 104945 units -> cell 25
        self.assertEqual(tg.fo4_cells_covering(-1400.0, 1499.21875, -1400.0, 1499.21875), (-24, 25, -24, 25))
        self.assertEqual(tg.fo4_cells_covering(0.0, 58.5, 0.0, 58.52), (0, 0, 0, 1))   # 58.514 m is the cell size

    def test_sf_cell_of(self):
        self.assertEqual(tg.sf_cell_of(-989.03, 1147.2), (-10, 11))
        self.assertEqual(tg.sf_cell_of(-1000.0, 1100.0), (-10, 11))
        self.assertEqual(tg.sf_cell_of(-1000.01, 1099.99), (-11, 10))


class Resample(unittest.TestCase):
    def setUp(self):
        rows, cols = 9, 12
        r, c = np.mgrid[0:rows, 0:cols]
        self.ox, self.oy, self.sp = -300.0, 50.0, 128.0
        x, y = self.ox + c * self.sp, self.oy + r * self.sp
        self.plane = 7000.0 + 0.3 * x - 0.2 * y           # FO4 units
        self.f = lambda x, y: 7000.0 + 0.3 * x - 0.2 * y

    def test_linear_surface_is_exact_inside(self):
        xs = np.linspace(self.ox, self.ox + 11 * self.sp, 37)
        ys = np.linspace(self.oy, self.oy + 8 * self.sp, 23)
        out = tg.resample_bilinear(self.plane, self.ox, self.oy, self.sp, xs, ys)
        self.assertEqual(out.shape, (23, 37))
        X, Y = np.meshgrid(xs, ys)
        np.testing.assert_allclose(out, self.f(X, Y), atol=1e-9)

    def test_rows_are_south_to_north(self):
        g = np.zeros((3, 3))
        g[2, :] = 10.0                                    # north row high
        out = tg.resample_bilinear(g, 0.0, 0.0, 1.0, [1.0], [0.0, 1.0, 1.5, 2.0])
        np.testing.assert_allclose(out[:, 0], [0.0, 0.0, 5.0, 10.0])

    def test_outside_takes_nearest_edge_value(self):
        g = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])  # rows y = 0, 1; cols x = 0, 1, 2
        out = tg.resample_bilinear(g, 0.0, 0.0, 1.0, [-5.0, 0.5, 9.0], [-3.0, 0.5, 4.0])
        # south of the grid: row 0 values; north: row 1; west/east clamp to the edge column (no extrapolation)
        np.testing.assert_allclose(out[0], [1.0, 1.5, 3.0])
        np.testing.assert_allclose(out[1], [2.5, 3.0, 4.5])
        np.testing.assert_allclose(out[2], [4.0, 4.5, 6.0])

    def test_no_cliff_at_the_edge(self):
        xs = np.linspace(self.ox - 500, self.ox + 11 * self.sp + 500, 400)
        out = tg.resample_bilinear(self.plane, self.ox, self.oy, self.sp, xs, [self.oy + 3 * self.sp])
        step = np.abs(np.diff(out[0])).max()
        self.assertLessEqual(step, 0.3 * (xs[1] - xs[0]) + 1e-9)     # never steeper than the surface itself

    def test_matches_point_interp_bilinear(self):
        rng = np.random.default_rng(7)
        g = rng.integers(-50, 50, (6, 7)).astype(float) * 8.0
        for _ in range(20):
            x, y = rng.uniform(0, 6 * 128), rng.uniform(0, 5 * 128)
            a = tg.resample_bilinear(g, 0.0, 0.0, 128.0, [x], [y])[0, 0]
            b = tg.point_interp(g, 0.0, 0.0, 128.0, x, y)["bilinear"]
            self.assertAlmostEqual(a, b, places=9)

    def test_vertices_are_reproduced(self):
        g = np.arange(30, dtype=float).reshape(5, 6) ** 1.5
        xs, ys = np.arange(6) * 128.0, np.arange(5) * 128.0
        np.testing.assert_allclose(tg.resample_bilinear(g, 0.0, 0.0, 128.0, xs, ys), g)


class PointRules(unittest.TestCase):
    def test_plane_same_under_every_rule(self):
        g = np.add.outer(np.arange(4) * 2.0, np.arange(5) * 3.0)
        hs = tg.point_interp(g, 0.0, 0.0, 1.0, 1.3, 2.6)
        for v in hs.values():
            self.assertAlmostEqual(v, 2.6 * 2 + 1.3 * 3)

    def test_rules_differ_on_a_saddle(self):
        g = np.array([[0.0, 0.0], [0.0, 1.0]])           # only the NE corner raised
        hs = tg.point_interp(g, 0.0, 0.0, 1.0, 0.5, 0.5)
        self.assertAlmostEqual(hs["bilinear"], 0.25)
        self.assertAlmostEqual(hs["tri_sw_ne"], 0.5)     # the SW-NE diagonal passes through the raised corner
        self.assertAlmostEqual(hs["tri_nw_se"], 0.0)

    def test_local_slope(self):
        g = np.add.outer(np.zeros(5), np.arange(5) * 64.0)   # 64 units rise per 128-unit step along x
        self.assertAlmostEqual(tg.local_slope_deg(g, 2, 2, 128.0), math.degrees(math.atan(0.5)))
        self.assertAlmostEqual(tg.local_slope_deg(g, 0, 0, 128.0), math.degrees(math.atan(0.5)))

    def test_is_flat(self):
        g = np.zeros((7, 7))
        g[0, 0] = 8.0
        self.assertTrue(tg.is_flat(g, 3, 3, 2))
        self.assertFalse(tg.is_flat(g, 2, 2, 2))
        self.assertFalse(tg.is_flat(g, 1, 3, 2))           # window leaves the grid

    def test_connections_order(self):
        h = np.arange(25).reshape(5, 5)                    # row 0 south, col 0 west
        self.assertEqual(tg.connections_raw(h), [0, 2, 4, 14, 24, 22, 20, 10])


class BtdRoundTripAtWorldPositions(unittest.TestCase):
    """A synthetic n = 3 BTD: world heights written with btd.write and read back at world positions."""

    def test_world_positions(self):
        n = 3
        xs = tg.sample_coords(n)
        X, Y = np.meshgrid(xs, xs)
        h = 50.0 + 0.1 * X - 0.05 * Y
        hmin, hmax = -100.0, 200.0
        t = btd.Btd(6, hmin, hmax, [0x1235C2], btd.quantize(h, hmin, hmax), np.zeros(h.shape, np.uint16),
                    np.tile(np.array([1, 0, 0, 0, 0, 0, 0, 0], np.uint8), (2 * n, 2 * n, 1)))
        back = btd.read(btd.write(t)).heights_m()
        step = (hmax - hmin) / 65535
        for x, y in ((-100.0, -100.0), (0.0, 0.0), (37.3, -61.9), (199.2, 199.2), (-12.34, 150.0)):
            self.assertLessEqual(abs(tg.btd_height_at(back, n, x, y) - (50.0 + 0.1 * x - 0.05 * y)), step)
        # the SW sample is world (-100, -100): moving the origin by one cell would be off by 10 m - 5 m
        self.assertAlmostEqual(back[0, 0], 50.0 - 10.0 + 5.0, delta=step)


class SelectPoints(unittest.TestCase):
    """make_exp2.select_points on a made-up terrain over the real patch cell numbers: a 12 deg tilted plane with a
    flat pad around a fake structure. Every vertex is eligible (err = 0)."""

    def test_kinds_and_uniqueness(self):
        mk = load_make_exp2()
        x0, y0 = -24, 12
        cols, rows = 14 * 32 + 1, 14 * 32 + 1
        origin = (x0 * 4096.0, y0 * 4096.0)
        r, c = np.mgrid[0:rows, 0:cols]
        g = np.round((r * 0.0 + c * 128.0 * math.tan(math.radians(12))) / 8.0) * 8.0 + 6000.0
        sx, sy = -69232.0, 80304.0
        sr, sc = int(round((sy - origin[1]) / 128)), int(round((sx - origin[0]) / 128))
        g[sr - 12:sr + 13, sc - 12:sc + 13] = 7360.0
        pts = mk.select_points(g, origin, (sx, sy), lambda rr, cc: 0.0, 0.004)
        kinds = [p["kind"] for p in pts]
        self.assertEqual(len(pts), 14)
        for k, cnt in (("redrocket", 2), ("flat", 2), ("slope", 4), ("seam_fo4", 2), ("seam_sf", 2),
                       ("resampled_sw", 1), ("resampled_ne", 1)):
            self.assertEqual(kinds.count(k), cnt, k)
        self.assertEqual(len({(p["row"], p["col"]) for p in pts}), 14)
        for p in pts:                                      # metres = units / 70, expect = vertex height / 70
            self.assertAlmostEqual(p["x"], round(p["fo4_units"][0] / 70, 4))
            self.assertAlmostEqual(p["expect"], round(g[p["row"], p["col"]] / 70, 4))
        rr = [p for p in pts if p["kind"] == "redrocket"]
        self.assertTrue(all(p["expect"] == round(7360 / 70, 4) and p["dist_from_origin_m"] < 2.0 for p in rr))
        sw = next(p for p in pts if p["label"] == "seam_sf_west")
        se = next(p for p in pts if p["label"] == "seam_sf_east")
        self.assertLess(sw["x"], -1000.0)
        self.assertGreaterEqual(se["x"], -1000.0)
        fw = next(p for p in pts if p["label"] == "seam_fo4_west")
        fe = next(p for p in pts if p["label"] == "seam_fo4_east")
        self.assertEqual((fw["fo4_cell"][0], fe["fo4_cell"][0]), (-18, -17))


if __name__ == "__main__":
    unittest.main()
