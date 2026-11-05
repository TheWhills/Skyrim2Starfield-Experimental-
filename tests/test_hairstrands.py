"""fo4sf.hairstrands: Starfield-style strand cards grown over a hair shell, on synthetic shapes only."""
import os
import sys
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import hairstrands as HS, skyrimhair as H  # noqa: E402


def strip_texture():
    """3 rows x 4 strips, as Starfield's hair textures (rows of strand strips)."""
    op = np.zeros((96, 128))
    for r in range(3):
        for k in range(4):
            op[r * 32 + 2:r * 32 + 30, k * 32 + 3:k * 32 + 28] = 255
    return op


def shell():
    """A cap (radius 0.1 round (0, 0, 1.69)) and a hanging skirt to z 1.5, normals out, tangents across the strands
    (horizontal: the strands run down), all on C_Head."""
    th = np.linspace(0, np.pi / 2 * 0.95, 16)
    ph = np.linspace(0, 2 * np.pi, 33)[:-1]
    pts = [[0.1 * np.sin(t) * np.cos(f), 0.1 * np.sin(t) * np.sin(f), 1.69 + 0.1 * np.cos(t)] for t in th for f in ph]
    pts += [[0.1 * np.cos(f), 0.1 * np.sin(f), z] for z in np.linspace(1.68, 1.5, 10) for f in ph]
    p = np.array(pts)
    nr, nc = len(th) + 10, len(ph)
    tris = []
    for r in range(nr - 1):
        for c in range(nc):
            a, b, d, e = r * nc + c, r * nc + (c + 1) % nc, (r + 1) * nc + c, (r + 1) * nc + (c + 1) % nc
            tris += [(a, d, b), (b, d, e)]
    centre = np.where(p[:, 2:3] < 1.69, np.c_[np.zeros(len(p)), np.zeros(len(p)), p[:, 2]], [0, 0, 1.69])
    n = p - centre
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    t = np.cross([0, 0, 1.0], n)
    small = np.linalg.norm(t, axis=1) < 0.3
    t[small] = [1.0, 0, 0]
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    w = [[("C_Head", 0.7), ("Hair1", 0.3)]] * len(p)
    return H.HairShape(b"S", p, n, t, [(0.0, 0.0)] * len(p), tris, w, -1, -1, 0)


class StripTests(unittest.TestCase):
    def test_rows_and_strips(self):
        st = HS.strip_layout(strip_texture())
        self.assertEqual(len(st), 12)
        rows = sorted({round(s[1], 3) for s in st})
        self.assertEqual(len(rows), 3)
        for u0, v0, u1, v1 in st:
            self.assertTrue(0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1)
            self.assertLess(u1 - u0, 0.3)

    def test_empty_falls_back(self):
        self.assertEqual(HS.strip_layout(np.zeros((32, 32))), [])


class CardTests(unittest.TestCase):
    def test_cards_over_the_shell(self):
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        strips = HS.strip_layout(strip_texture())
        hair, rep = HS.grow_cards(H.Hair([shell()], [], {}, {}), head, strips, max_cards=300)
        self.assertGreater(rep["cards"], 30)
        self.assertEqual(len(hair.shapes), len(rep["layers"]))
        allp = np.vstack([np.asarray(s.positions) for s in hair.shapes])
        r = np.where(allp[:, 2] < 1.69, np.linalg.norm(allp[:, :2], axis=1),
                     np.linalg.norm(allp - [0, 0, 1.69], axis=1))
        self.assertLess(np.abs(r - 0.1).max(), 0.02)                     # on the shell, a little out
        self.assertGreater(np.median(r - 0.1), 0.0)
        sh = hair.shapes[0]
        uv = np.asarray(sh.uvs)
        inside = [any(u0 - 1e-9 <= u <= u1 + 1e-9 and v0 - 1e-9 <= v <= v1 + 1e-9 for u0, v0, u1, v1 in strips)
                  for u, v in uv]
        self.assertTrue(all(inside))                                     # on the texture's strips
        p = np.asarray(sh.positions)
        skirt = [k for k, t in enumerate(sh.triangles) if p[list(t), 2].max() < 1.65]
        self.assertTrue(skirt)
        t = sh.triangles[skirt[0]]
        rows = sorted(t, key=lambda i: -p[i, 2])                         # higher vertex: nearer the root (v0)
        self.assertLessEqual(uv[rows[0], 1], uv[rows[-1], 1] + 1e-9)
        self.assertEqual(sh.weights[0], [("C_Head", 0.7), ("Hair1", 0.3)])   # the guide's weights
        a, b, c = (p[i] for i in sh.triangles[0])
        out = (a + b + c) / 3 - [0, 0, min(1.69, ((a + b + c) / 3)[2])]
        self.assertGreater(np.dot(np.cross(b - a, c - a), out), 0)        # facing out

    def _cap_guide(self):
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        guide = HS.Guide(H.Hair([shell()], [], {}, {}), head)
        th = np.radians(np.arange(0, 90, 3))
        ph = np.radians(np.arange(0, 360, 6))
        scalp = np.array([[0.098 * np.sin(t) * np.sin(f), 0.098 * np.sin(t) * np.cos(f), 1.69 + 0.098 * np.cos(t)]
                          for t in th for f in ph])
        return head, guide, scalp

    def _front_line(self, z0, z1, n=12):
        """Points on the cap's front (+Y) meridian from height z0 up to z1."""
        t = np.arccos((np.linspace(z0, z1, n) - 1.69) / 0.1)
        return np.c_[np.zeros(n), 0.1 * np.sin(t), 1.69 + 0.1 * np.cos(t)]

    def test_hairline_curve_is_smooth_and_follows_the_hair(self):
        head, guide, scalp = self._cap_guide()
        rel = guide.p - head[:3, 3]
        guide.cov = np.where(rel[:, 2] > 0.13 + 0.01 * np.cos(np.arange(len(rel)) * 1.7), 1.0, 0.0)   # ragged edge
        grid, h = HS.hairline_curve(guide, scalp, head)
        self.assertEqual((grid[0], grid[-1]), (-HS.FRONT_ANGLE, HS.FRONT_ANGLE))
        self.assertTrue(np.all((h > 0.12) & (h < 0.155)), h)               # where the hair starts (coarse cap)
        self.assertLess(np.abs(np.diff(h)).max(), 0.002)                  # one smooth line, not the ragged edge
        guide.cov[:] = 0.0
        self.assertIsNone(HS.hairline_curve(guide, scalp, head))

    def test_roots_carried_down_or_cut_to_the_curve(self):
        head, guide, scalp = self._cap_guide()
        curve = (np.array([-80.0, 80.0]), np.array([0.12, 0.12]))         # 12 cm over C_Head: z 1.72
        high = self._front_line(1.76, 1.785)
        out, moved = HS.to_hairline(high, guide, curve, head, scalp)
        self.assertEqual(moved, 1)
        self.assertAlmostEqual(out[0, 2], 1.72, delta=0.005)              # carried down to the line
        self.assertTrue(np.allclose(out[-len(high):], high))
        low = self._front_line(1.70, 1.785)
        out, moved = HS.to_hairline(low, guide, curve, head, scalp)
        self.assertEqual(moved, -1)
        self.assertGreaterEqual(out[0, 2], 1.72 - 0.003 - 1e-9)           # cut off below the line
        on = self._front_line(1.7205, 1.785)
        self.assertEqual(HS.to_hairline(on, guide, curve, head, scalp)[1], 0)
        back = on * [1, -1, 1]                                            # rooted at the back: left alone
        self.assertEqual(HS.to_hairline(back, guide, curve, head, scalp)[1], 0)
        self.assertEqual(HS.to_hairline(high, guide, None, head, scalp)[1], 0)

    def test_fixed_depth_slots(self):
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        strips = HS.strip_layout(strip_texture())

        def depths(slots):
            seen, real = [], HS._ribbon

            def spy(line, normals, width, offset, *rest):
                seen.append(round(offset, 6))
                return real(line, normals, width, offset, *rest)
            with mock.patch.object(HS, "_ribbon", spy):
                HS.grow_cards(H.Hair([shell()], [], {}, {}), head, strips, max_cards=300, layers=1, gap=0.002,
                              slots=slots)
            return np.unique(seen)
        fixed = depths(3)
        self.assertEqual(len(fixed), 3)                              # three depths, gap / 3 apart
        self.assertTrue(np.allclose(fixed, [0.002, 0.002 + 0.002 / 3, 0.002 + 0.004 / 3], atol=1e-6), fixed)
        self.assertGreater(len(depths(0)), 3)                            # random depths otherwise

    def test_trace_stops_at_the_edge(self):
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        g = HS.Guide(H.Hair([shell()], [], {}, {}), head)
        lines = HS.trace(g, np.array([[0.1, 0.0, 1.6]]), +1.0, 0.005, max_steps=200)
        self.assertGreater(lines[0][-1][2], 1.5 - 0.012)                  # ends near the skirt's hem
        self.assertLess(lines[0][-1][2], 1.52)


class GuideTests(unittest.TestCase):
    def head(self):
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        return head

    def test_uv_direction_root_to_tip(self):
        p = np.array([[0, 0.1, 1.7], [0.01, 0.1, 1.7], [0, 0.1, 1.6], [0.01, 0.1, 1.6]])
        sh = H.HairShape(b"C", p, np.array([[0, 1.0, 0]] * 4), np.zeros((4, 3)), [(0, 0), (1, 0), (0, 1), (1, 1)],
                         [(0, 2, 1), (1, 2, 3)], [[("C_Head", 1.0)]] * 4, -1, -1, 0)
        d = HS.uv_strand_dirs(sh)
        self.assertTrue(np.allclose(d, [[0, 0, -1.0]] * 4))                 # +V runs down: root at the top
        flipped = H.HairShape(b"C", p, sh.normals, sh.tangents, [(0, 1), (1, 1), (0, 0), (1, 0)], sh.triangles,
                              sh.weights, -1, -1, 0)
        self.assertTrue(np.allclose(HS.uv_strand_dirs(flipped), [[0, 0, 1.0]] * 4))   # roots at the bottom: up
        across = HS.uv_strand_dirs(sh, np.ones(4, bool))
        self.assertTrue(np.allclose(np.abs(across[:, 0]), 1.0))            # strands along U: +U

    def test_given_directions_win_over_the_crown_guess(self):
        sh = shell()
        up = np.tile([0, 0, 1.0], (len(sh.positions), 1))                 # e.g. slicked back: toward the crown
        g = HS.Guide(H.Hair([sh], [], {}, {}), self.head(), dirs=[up])
        side = np.nonzero(np.asarray(sh.positions)[:, 2] < 1.65)[0][0]
        self.assertGreater(g.s[side][2], 0.9)
        g2 = HS.Guide(H.Hair([sh], [], {}, {}), self.head())
        self.assertLess(g2.s[side][2], -0.9)                               # fallback: away from the crown

    def test_cards_only_where_the_texture_is_hair(self):
        sh = shell()
        cov = (np.asarray(sh.positions)[:, 2] > 1.6).astype(float)         # the lower skirt is see-through
        hair, rep = HS.grow_cards(H.Hair([sh], [], {}, {}), self.head(), HS.strip_layout(strip_texture()),
                                  coverage=[cov], max_cards=150)
        self.assertGreater(rep["cards"], 10)
        allp = np.vstack([np.asarray(s.positions) for s in hair.shapes])
        self.assertGreater(allp[:, 2].min(), 1.6 - 0.025)                   # no cards down the see-through part

    def test_smooth_line_eases_zigzags(self):
        sh = shell()
        g = HS.Guide(H.Hair([sh], [], {}, {}), self.head())
        z = np.linspace(1.67, 1.52, 16)
        line = np.c_[0.1 + 0 * z, 0.004 * (-1) ** np.arange(16), z]           # zig-zag on the skirt
        sm = HS.smooth_line(g, line)
        self.assertLess(np.abs(np.diff(sm[:, 1])).mean(), 0.5 * np.abs(np.diff(line[:, 1])).mean())
        self.assertLess(np.abs(np.linalg.norm(sm[:, :2], axis=1) - 0.1).max(), 0.003)   # still on the guide

    def test_dense_strips_for_the_inner_layer(self):
        op = strip_texture()
        op[:, 64:] *= 0.2                                                  # the right half's strips sparse
        st = HS.strip_layout(op)
        dens = HS.strip_coverage(op, st)
        self.assertEqual(len(dens), len(st))
        hair, _rep = HS.grow_cards(H.Hair([shell()], [], {}, {}), self.head(), st, densities=dens, max_cards=90)
        u = np.asarray(hair.shapes[0].uvs)[:, 0]
        self.assertLess(u.max(), 0.5 + 1e-9)                                # inner layer: the dense strips only


class RoundThreeTests(unittest.TestCase):
    def head(self):
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        return head

    def test_short_cards_take_the_strip_tip(self):
        line = np.array([[0, 0.1, 1.6 - 0.01 * k] for k in range(7)])        # 6 cm
        pos, nrm, uv, tris, wts = HS._ribbon(line, np.tile([0, 1.0, 0], (7, 1)), 0.01, 0.0, (0.0, 0.2, 0.1, 0.8),
                                             [[("C_Head", 1.0)]] * 7)
        v = np.asarray(uv)[:, 1]
        self.assertAlmostEqual(v[-1], 0.8)                                  # the tip at the strip's tip
        self.assertAlmostEqual(v[0], 0.8 - 0.6 * 0.06 / HS.STRIP_LENGTH)    # its root inside the strip
        long = np.array([[0, 0.1, 1.6 - 0.04 * k] for k in range(10)])      # 36 cm: the whole strip
        _p, _n, uv2, _t, _w = HS._ribbon(long, np.tile([0, 1.0, 0], (10, 1)), 0.01, 0.0, (0.0, 0.2, 0.1, 0.8),
                                         [[("C_Head", 1.0)]] * 10)
        self.assertAlmostEqual(np.asarray(uv2)[0, 1], 0.2)

    def test_root_grows_out_of_the_scalp(self):
        line = np.array([[0, 0.1, 1.7 - 0.01 * k] for k in range(8)])
        pos, _n, uv, _t, _w = HS._ribbon(line, np.tile([0, 1.0, 0], (8, 1)), 0.02, 0.004, (0.0, 0.0, 0.2, 1.0),
                                         [[("C_Head", 1.0)]] * 8)
        widths = np.linalg.norm(pos[1::2] - pos[0::2], axis=1)
        self.assertAlmostEqual(widths[0], 0.02 * HS.ROOT_WIDTH)              # narrow at the root
        self.assertAlmostEqual(widths[-1], 0.02)                             # full after ROOT_TAPER
        heights = pos[0::2, 1] - 0.1
        self.assertLess(heights[0], 0.3 * 0.004 + 1e-9)                      # down on the scalp at the root
        self.assertAlmostEqual(heights[-1], 0.004)
        u = np.asarray(uv)[:, 0]
        self.assertAlmostEqual(u[1] - u[0], 0.2 * HS.ROOT_WIDTH)              # fewer strands, not thinner ones
        self.assertAlmostEqual(u[-1] - u[-2], 0.2)

    def test_root_at_the_hairline(self):
        rng = np.random.default_rng(3)
        d = rng.normal(size=(4000, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        skull = np.array([0, 0, 1.69]) + 0.09 * d
        crown_to_front = np.array([[0, 0.0, 1.785], [0, 0.05, 1.77], [0, 0.085, 1.72]])   # tip at the hairline
        out, flipped = HS.root_at_hairline(crown_to_front, skull, self.head())
        self.assertEqual(flipped, 1)
        self.assertTrue(np.allclose(out[0], crown_to_front[-1]))
        back = np.array([[0, 0.0, 1.785], [0, -0.05, 1.77], [0, -0.085, 1.72]])   # crown to the back: kept
        self.assertEqual(HS.root_at_hairline(back, skull, self.head())[1], 0)
        fringe = np.array([[0, 0.05, 1.77], [0, 0.11, 1.70], [0, 0.12, 1.66]])     # hangs free: kept
        self.assertEqual(HS.root_at_hairline(fringe, skull, self.head())[1], 0)

    def test_gaps_in_the_painted_strands_do_not_end_a_trace(self):
        sh = shell()
        z = np.asarray(sh.positions)[:, 2]
        cov = ((np.round(z / 0.004) % 3) != 0).astype(float)               # every third row of the skin 'empty'
        g = HS.Guide(H.Hair([sh], [], {}, {}), self.head(), coverage=[cov])
        line = HS.trace(g, np.array([[0.1, 0.0, 1.66]]), +1.0, 0.005, max_steps=200)[0]
        self.assertLess(line[-1][2], 1.53)                                  # down to the hem


if __name__ == "__main__":
    unittest.main()
