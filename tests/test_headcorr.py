"""src/fo4sf/headcorr.py on synthetic meshes: closest points on triangles; seam-split vertices stay together; neighbour
agreement along the source surface; the lip-side term (a mouth slit against a closed mouth pocket, the case of
Skyrim's open mouth against Starfield's closed one)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import facefit, headcorr  # noqa: E402


def grid(xs, zs, y=0.0, skip=lambda i, j: False):
    """A plane at y (facing +Y) over xs x zs; skip(i, j) leaves out the quad between columns i, i+1 / rows j, j+1."""
    v = np.array([(x, y, z) for z in zs for x in xs], float)
    n = len(xs)
    f = []
    for j in range(len(zs) - 1):
        for i in range(n - 1):
            if skip(i, j):
                continue
            a, b, c, d = j * n + i, j * n + i + 1, (j + 1) * n + i, (j + 1) * n + i + 1
            f += [(a, b, d), (a, d, c)]                   # counter-clockwise seen from +Y
    return v, np.array(f, int)


def brute_closest(p, a, b, c, n=120):
    """Closest point on a triangle by dense sampling (for checking)."""
    u, w = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n))
    m = u + w <= 1
    q = a + u[m][:, None] * (b - a) + w[m][:, None] * (c - a)
    return float(np.min(np.sum((q - p) ** 2, 1)))


class ClosestTests(unittest.TestCase):
    def test_against_sampling(self):
        rng = np.random.default_rng(1)
        a, b, c = rng.normal(size=(3, 5, 3))
        p = rng.normal(size=(40, 3)) * 2
        bary, d2 = headcorr.closest_on_triangles(p, a, b, c)
        self.assertTrue(np.allclose(bary.sum(-1), 1) and (bary > -1e-9).all())
        for i in range(0, 40, 4):
            for t in range(5):
                self.assertAlmostEqual(d2[i, t], brute_closest(p[i], a[t], b[t], c[t]), delta=2e-3 * (1 + d2[i, t]))
        q = np.einsum("ntk,ktc->ntc", bary, np.stack([a, b, c]))
        self.assertTrue(np.allclose(((q - p[:, None]) ** 2).sum(-1), d2))


class SeamTests(unittest.TestCase):
    def test_seam_split_vertices_move_together(self):
        xs = np.linspace(-0.05, 0.05, 11)
        zs = np.linspace(-0.05, 0.05, 11)
        src_v, src_f = grid(xs, zs)
        # dst: the same plane, finer, cut along x = 0 into two pieces whose seam vertices are duplicated (UV seam)
        fx = np.linspace(-0.05, 0.05, 21)
        fz = np.linspace(-0.05, 0.05, 21)
        dv, df = grid(fx, fz)
        n = len(fx)
        seam = np.where(np.isclose(dv[:, 0], 0))[0]
        dup = {int(s): len(dv) + k for k, s in enumerate(seam)}
        dv = np.concatenate([dv, dv[seam]])
        df = df.copy()
        for t in range(len(df)):                           # triangles right of the seam use the copies
            if dv[df[t], 0].max() > 1e-9:
                df[t] = [dup.get(int(k), int(k)) for k in df[t]]
        field = np.zeros((len(src_v), 3))
        field[:, 2] = np.where(src_v[:, 0] > 0, 0.01, 0.0) + 0.002 * np.sin(src_v[:, 2] * 90)
        corr = headcorr.correspond(src_v, src_f, dv, df)
        out = corr.transfer(field, smooth=6)
        self.assertLess(np.abs(out[seam] - out[[dup[int(s)] for s in seam]]).max(), 1e-12)
        # the old smoothing over the split topology lets the copies drift apart: the scalp cracks
        old = facefit.smooth_field(corr.sample(field), df, iterations=6)
        self.assertGreater(np.abs(old[seam] - old[[dup[int(s)] for s in seam]]).max(), 1e-4)
        self.assertEqual(corr.report["dst_seam_vertices"], 2 * len(seam))
        self.assertEqual(n, 21)


class NeighbourTests(unittest.TestCase):
    def test_isolated_wrong_nearest_follows_neighbours(self):
        xs = np.linspace(-0.05, 0.05, 6)
        zs = np.linspace(-0.05, 0.05, 6)
        up_v, up_f = grid(xs, zs, y=0.003)
        lo_v, lo_f = grid(xs, zs, y=-0.003)
        src_v = np.concatenate([up_v, lo_v])                 # two sheets 6 mm apart, not connected
        src_f = np.concatenate([up_f, lo_f + len(up_v)])
        field = np.zeros((len(src_v), 3))
        field[:len(up_v), 1] = 1.0                           # the upper sheet's field 1, the lower 0
        dv, df = grid(np.linspace(-0.04, 0.04, 17), np.linspace(-0.04, 0.04, 17), y=0.0005)
        rng = np.random.default_rng(3)
        odd = rng.choice(len(dv), 12, replace=False)
        dv[odd, 1] = -0.0005                                 # a few points nearer the lower sheet
        nearest = headcorr.correspond(src_v, src_f, dv, df, mu=0.0).sample(field)[:, 1]
        self.assertEqual(headcorr.main_triangles(src_f, len(src_v)).shape, src_f.shape)    # both sheets kept
        self.assertTrue(np.allclose(nearest[odd], 0.0))       # by distance alone: the other sheet
        agreed = headcorr.correspond(src_v, src_f, dv, df).sample(field)[:, 1]
        self.assertTrue(np.allclose(agreed, 1.0), agreed[odd])


def slit_face(h=0.01, w=0.025):
    """Skyrim-like: a face plane with a mouth slit between rows z = -h/2 and +h/2 for |x| < w."""
    xs = np.arange(-0.06, 0.0601, h / 2)
    zs = np.concatenate([np.arange(-0.05, -h / 2 + 1e-9, h / 2), np.arange(h / 2, 0.0501, h / 2)])
    j0 = int(np.argmin(np.abs(zs + h / 2)))
    return grid(xs, zs, skip=lambda i, j: j == j0 and abs((xs[i] + xs[i + 1]) / 2) < w)


def pocket_face(h=0.01, w=0.025, depth=0.03, cross=0.001):
    """Starfield-like: closed lips (the upper contact row at z = -cross, the lower at +cross: crossed, as pressed lips
    overhang) joined through a pocket behind the mouth (row at y = -depth); mouth corners closed."""
    s = h / 4
    xs = np.arange(-0.06, 0.0601, s)
    upper = np.arange(s, 0.0501, s)
    lower = -upper[::-1]
    rows = [(x, 0.0, z) for z in lower for x in xs]
    nx = len(xs)
    rows_lo = len(lower)
    v = np.array(rows + [(x, 0.0, z) for z in upper for x in xs], float)
    nl = rows_lo * nx
    inner = np.abs(xs) < w
    top_lo = np.arange(nl - nx, nl)                         # the lower lip's top row
    bot_up = np.arange(nl, nl + nx)                         # the upper lip's bottom row
    v[top_lo[inner], 2] = cross
    v[bot_up[inner], 2] = -cross
    pocket = len(v) + np.arange(nx)
    v = np.concatenate([v, np.array([(x, -depth, 0.0) for x in xs])])
    f = []

    def quads(r0, r1, keep):
        for i in range(nx - 1):
            if keep(i):
                a, b, c, d = r0[i], r0[i + 1], r1[i], r1[i + 1]
                f.extend([(a, b, d), (a, d, c)])
    for j in range(rows_lo - 1):
        quads(np.arange(j * nx, (j + 1) * nx), np.arange((j + 1) * nx, (j + 2) * nx), lambda i: True)
    for j in range(len(upper) - 1):
        quads(nl + np.arange(j * nx, (j + 1) * nx), nl + np.arange((j + 1) * nx, (j + 2) * nx), lambda i: True)
    corner = lambda i: not (inner[i] and inner[i + 1])       # noqa: E731
    quads(top_lo, bot_up, corner)                           # the mouth corners: closed skin
    mouth = lambda i: inner[i] and inner[i + 1]             # noqa: E731
    quads(pocket, bot_up, mouth)                            # upper lip -> pocket
    quads(top_lo, pocket, mouth)                            # pocket -> lower lip
    return v, np.array(f, int), top_lo[inner], bot_up[inner]


class LipTests(unittest.TestCase):
    def test_slit_and_loops(self):
        v, f = slit_face()
        hole = headcorr.mouth_hole(v, f)
        self.assertIsNotNone(hole)
        self.assertLess(np.abs(v[hole, 2]).max(), 0.0051)
        self.assertIsNone(headcorr.mouth_hole(*pocket_face()[:2]))   # closed mouth: no hole

    def test_lip_side_keeps_closed_lips_on_their_own_side(self):
        sv, sf = slit_face()
        field = np.zeros((len(sv), 3))
        field[:, 2] = np.sign(sv[:, 2]) * 0.004              # lips apart: upper up, lower down (an open mouth)
        dv, df, lower_row, upper_row = pocket_face()
        plain = headcorr.correspond(sv, sf, dv, df, mu=0.0, lip_weight=0.0).sample(field)[:, 2]
        # crossed rows: by distance the upper lip's contact row lands on Skyrim's lower lip and the other way round
        self.assertTrue((plain[upper_row] < 0).any() and (plain[lower_row] > 0).any())
        corr = headcorr.correspond(sv, sf, dv, df, to_model=np.eye(4))
        got = corr.sample(field)[:, 2]
        body = np.abs(dv[upper_row, 0]) <= 0.015            # the lips away from the corners (ambiguous there)
        self.assertTrue((got[upper_row][body] > 0).all(), got[upper_row])
        self.assertTrue((got[lower_row][body] < 0).all(), got[lower_row])
        off = headcorr.correspond(sv, sf, dv, df, to_model=np.eye(4), lip_weight=0.0).sample(field)[:, 2]
        self.assertTrue((off[upper_row][body] < 0).any() or (off[lower_row][body] > 0).any())   # needs the lip term
        self.assertEqual(corr.report["mouth"]["hole_vertices"], len(headcorr.mouth_hole(sv, sf)))

    def test_lip_edges_follow_the_src_mouth_edges(self):
        """2026-11-10 (owner: the female Orc's lips gaped on Starfield's head where Skyrim's look closed): the lips'
        meeting rows get the vertical move of Skyrim's visible lip edges, faded over their own lip, nothing far away."""
        sv, sf = slit_face()
        field = np.zeros((len(sv), 3))
        # the lip surfaces open more away from the edge than at it (edge rows at |z| = 5 mm move 1 mm)
        field[:, 2] = np.sign(sv[:, 2]) * (0.001 + 0.4 * np.maximum(np.abs(sv[:, 2]) - 0.005, 0.0))
        dv, df, lower_row, upper_row = pocket_face()
        corr = headcorr.correspond(sv, sf, dv, df, to_model=np.eye(4))
        disp = corr.transfer(field, 4)
        wrong = disp.copy()
        wrong[upper_row, 2] += 0.003                   # as if transferred too open
        wrong[lower_row, 2] -= 0.003
        out, rep = corr.fit_lip_edges(wrong, field)
        body = np.abs(dv[upper_row, 0]) <= 0.015
        self.assertTrue(np.allclose(out[upper_row][body, 2], 0.001, atol=2e-4), out[upper_row][body, 2])
        self.assertTrue(np.allclose(out[lower_row][body, 2], -0.001, atol=2e-4), out[lower_row][body, 2])
        self.assertTrue(np.allclose(out[upper_row][:, :2], wrong[upper_row][:, :2]))    # only up / down
        far = np.linalg.norm(dv - dv[upper_row].mean(0), axis=1) > 0.06
        self.assertTrue(np.allclose(out[far], wrong[far]))
        op = rep["visible_opening_m"]
        self.assertLess(abs(op["skyrim_after"] - op["skyrim_before"] - 0.002), 3e-4)
        self.assertLess(abs(op["after"] - op["starfield_base"] - 0.002), 5e-4)
        self.assertGreater(op["before"], op["after"] + 0.002)
        none = headcorr.correspond(sv, sf, dv, df)                 # no lip term: unchanged
        same, r2 = none.fit_lip_edges(wrong, field)
        self.assertTrue(np.array_equal(same, wrong))
        self.assertEqual(r2, {"lip_edges": "no mouth data"})

    def test_lip_edges_overhang(self):
        """Skyrim's mouth edge rises 3 mm but the lip row above comes down over it: the visible edge rises 1 mm."""
        sv, sf = slit_face()
        field = np.zeros((len(sv), 3))
        mouth = np.abs(sv[:, 0]) < 0.03
        field[mouth & np.isclose(sv[:, 2], 0.005), 2] = 0.003
        field[mouth & np.isclose(sv[:, 2], 0.010), 2] = -0.004
        dv, df, lower_row, upper_row = pocket_face()
        corr = headcorr.correspond(sv, sf, dv, df, to_model=np.eye(4))
        out, rep = corr.fit_lip_edges(corr.transfer(field, 0), field)
        body = np.abs(dv[upper_row, 0]) <= 0.015
        self.assertTrue(np.allclose(out[upper_row][body, 2], 0.001, atol=3e-4), out[upper_row][body, 2])

    def test_loose_triangles_ignored(self):
        sv, sf = slit_face()
        extra = len(sv) + np.arange(3)
        sv2 = np.concatenate([sv, [(0.0, 0.0005, 0.0), (0.002, 0.0005, 0.0), (0.0, 0.0005, 0.002)]])
        sf2 = np.concatenate([sf, [extra]])
        tri = headcorr.main_triangles(sf2, len(sv2))
        self.assertEqual(len(tri), len(sf))
        dv, df, *_ = pocket_face()
        corr = headcorr.correspond(sv2, sf2, dv, df, to_model=np.eye(4))
        self.assertEqual(corr.report["src_loose_triangles"], 1)
        self.assertFalse(np.isin(corr.corners, extra).any())


if __name__ == "__main__":
    unittest.main()
