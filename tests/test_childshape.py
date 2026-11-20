"""fo4sf.childshape: a Skyrim child's own face shape on Starfield's child head, feature by feature (2026-11-19)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import childshape as CS  # noqa: E402


def sphere(r=(0.09, 0.1, 0.11), c=(0, 0, 1.65), n=24, m=48):
    """A UV ellipsoid (V, 3), triangles; +Y forward."""
    v = [(c[0], c[1], c[2] + r[2])]
    for i in range(1, n):
        th = np.pi * i / n
        for j in range(m):
            ph = 2 * np.pi * j / m
            v.append((c[0] + r[0] * np.sin(th) * np.sin(ph), c[1] + r[1] * np.sin(th) * np.cos(ph),
                      c[2] + r[2] * np.cos(th)))
    v.append((c[0], c[1], c[2] - r[2]))
    t = [(0, 1 + j, 1 + (j + 1) % m) for j in range(m)]
    for i in range(n - 2):
        a, b = 1 + i * m, 1 + (i + 1) * m
        for j in range(m):
            j2 = (j + 1) % m
            t += [(a + j, b + j, b + j2), (a + j, b + j2, a + j2)]
    last = len(v) - 1
    t += [(1 + (n - 2) * m + j, last, 1 + (n - 2) * m + (j + 1) % m) for j in range(m)]
    return np.array(v, float), np.array(t, int)


class PieceTests(unittest.TestCase):
    def test_prealign_recovers_scale_and_shift(self):
        rng = np.random.default_rng(3)
        sf = {k: rng.normal(size=3) * 0.05 for k in CS.LM_WEIGHTS}
        sky = {k: (p - 0.01) / 1.1 for k, p in sf.items()}
        moved, rep = CS.prealign(np.array(list(sky.values())), sky, sf)
        np.testing.assert_allclose(moved, np.array(list(sf.values())), atol=1e-9)
        self.assertAlmostEqual(rep["scale"], 1.1, places=4)
        self.assertEqual(max(rep["after_mm"].values()), 0.0)
        P = np.array(rep["matrix"])                    # the same move as a matrix
        np.testing.assert_allclose(CS.apply4(P, np.array(list(sky.values()))), moved, atol=1e-6)
        f = np.array(sky["forehead"])                  # the hair's lift: how far the forehead goes up
        self.assertAlmostEqual(rep["hair_lift_m"], float(CS.apply4(P, f[None])[0, 2] - f[2]), places=5)

    def test_closest_points_match_the_exhaustive_search(self):
        v, t = sphere(n=10, m=16)
        rng = np.random.default_rng(1)
        p = rng.normal(size=(200, 3)) * 0.08 + (0, 0, 1.65)
        a, da, _ = CS.closest_points(p, v, t)
        b, db, _ = CS.closest_points_all(p, v, t)
        np.testing.assert_allclose(da, db, atol=1e-9)
        np.testing.assert_allclose(a, b, atol=1e-9)

    def test_smoothing_and_subdivision(self):
        v, t = sphere(n=8, m=12)
        sv, st = CS.subdivide(v, t)
        self.assertEqual(len(st), 4 * len(t))
        self.assertEqual(len(sv), len(v) + len(CS.edges(t)))
        g = np.linspace(0, 0.1, 21)                                    # a flat grid with noise across it
        gv = np.array([(x, y, 0.0) for y in g for x in g])
        gt = np.array([(i * 21 + j, i * 21 + j + 1, (i + 1) * 21 + j) for i in range(20) for j in range(20)] +
                      [(i * 21 + j + 1, (i + 1) * 21 + j + 1, (i + 1) * 21 + j) for i in range(20) for j in range(20)])
        rng = np.random.default_rng(2)
        noisy = gv + np.stack([0 * g[:1].repeat(len(gv)), 0 * g[:1].repeat(len(gv)),
                               rng.normal(size=len(gv)) * 0.002], 1)
        sm = CS.taubin(noisy, CS.edges(gt), len(gv), 10)
        self.assertLess(np.abs(sm[:, 2]).mean(), 0.5 * np.abs(noisy[:, 2]).mean())
        sv2 = CS.taubin(v, CS.edges(t), len(v), 10)                    # Taubin: the whole does not shrink
        r0 = np.linalg.norm(v - v.mean(0), axis=1).mean()
        self.assertLess(abs(np.linalg.norm(sv2 - sv2.mean(0), axis=1).mean() - r0), 0.03 * r0)
        self.assertLess(np.linalg.norm(CS.smooth(v, CS.edges(t), len(v), 10) - v.mean(0), axis=1).mean(),
                        np.linalg.norm(sv2 - sv2.mean(0), axis=1).mean())

    def test_locks_and_weights(self):
        eyes = np.array([(-0.04, 0.083, 1.684), (0.04, 0.083, 1.684)])
        mouth = np.array([0.0, 0.098, 1.608])
        pts = np.array([eyes[0], eyes[0] + (0, -0.03, 0), eyes[0] + (0.03, 0.0, 0), (0, 0.1, 1.65),
                        (0, -0.1, 1.65), (0, 0.06, 1.608), (0, 0.1, 1.80)])
        lock = CS.socket_lock(pts, eyes)
        self.assertEqual(lock[0], 0.0)                     # the opening
        self.assertEqual(lock[1], 0.0)                     # the socket behind it
        self.assertGreater(lock[2], 0.0)                   # beside the eye: free (fading)
        w = CS.face_weight(pts, eyes, mouth)
        self.assertEqual(w[3], 1.0)                        # the face
        self.assertEqual(w[4], 0.0)                        # the back of the head
        self.assertEqual(w[6], 0.0)                        # the crown
        self.assertEqual(list(CS.inside_mouth(pts, mouth)[[3, 5]]), [0.0, 1.0])


class UnderEyeTests(unittest.TestCase):
    def test_under_eye_moves_smoothed(self):
        """Fine bumps in the moves under an eye are smoothed away; above the eyes and far off they stay."""
        g = np.linspace(-0.08, 0.08, 41)                                 # a face-like grid facing +Y
        gv = np.array([(x, 0.09, 1.684 + z) for z in g for x in g])
        n = len(g)
        gt = np.array([(i * n + j, i * n + j + 1, (i + 1) * n + j) for i in range(n - 1) for j in range(n - 1)] +
                      [(i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j) for i in range(n - 1)
                       for j in range(n - 1)])
        eyes = np.array([(-0.04, 0.09, 1.684), (0.04, 0.09, 1.684)])
        rng = np.random.default_rng(5)
        disp = np.zeros_like(gv)
        disp[:, 1] = rng.normal(size=len(gv)) * 0.001 + 0.002
        out = CS.smooth_under_eyes(gv, gt, disp, eyes)
        w = CS.under_eye_weight(gv, eyes)
        lock = CS.socket_lock(gv, eyes)
        band = (w > 0.99) & (lock > 0.5)
        self.assertTrue(band.any())
        self.assertLess(np.std(out[band, 1]), 0.4 * np.std(disp[band, 1]))   # bumps gone
        self.assertAlmostEqual(float(out[band, 1].mean()), 0.002, delta=0.0005)   # the overall move kept
        above = (gv[:, 2] > 1.684 + 0.01) & (np.linalg.norm(gv[:, [0, 2]] - (0, 1.684), axis=1) < 0.08)
        np.testing.assert_allclose(out[above & (lock > 0.99)], disp[above & (lock > 0.99)])
        self.assertTrue(np.all(out[lock == 0] == 0))                          # the eye openings stay put


class FaceSmoothTests(unittest.TestCase):
    def test_smooth_moves_everywhere(self):
        """The whole-face smoothing takes fine bumps out of the moves and keeps their overall size."""
        g = np.linspace(-0.08, 0.08, 41)
        gv = np.array([(x, 0.09, 1.684 + z) for z in g for x in g])
        n = len(g)
        gt = np.array([(i * n + j, i * n + j + 1, (i + 1) * n + j) for i in range(n - 1) for j in range(n - 1)] +
                      [(i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j) for i in range(n - 1)
                       for j in range(n - 1)])
        eyes = np.array([(-0.04, 0.09, 1.684), (0.04, 0.09, 1.684)])
        disp = np.zeros_like(gv)
        disp[:, 1] = np.random.default_rng(7).normal(size=len(gv)) * 0.001 + 0.003
        out = CS.smooth_moves(gv, gt, disp, eyes, CS.FACE_SMOOTH)
        free = CS.socket_lock(gv, eyes) > 0.99
        self.assertLess(np.std(out[free, 1]), 0.3 * np.std(disp[free, 1]))
        self.assertAlmostEqual(float(out[free, 1].mean()), 0.003, delta=0.0005)
        self.assertTrue(np.all(out[CS.socket_lock(gv, eyes) == 0] == 0))
        np.testing.assert_allclose(CS.smooth_moves(gv, gt, disp, eyes, 0), disp * CS.socket_lock(gv, eyes)[:, None])


class AlmondTests(unittest.TestCase):
    def test_upper_lid_lowered_in_the_middle(self):
        """An eye opening (an open loop in a flat face): its upper edge comes down most at the middle, not at the
        corners; the lid skin above follows; the lower edge stays."""
        n = 41
        g = np.linspace(-0.04, 0.04, n)
        v = np.array([(x, 0.09, 1.684 + z) for z in g for x in g])
        tris = []
        for i in range(n - 1):
            for j in range(n - 1):
                q = [i * n + j, i * n + j + 1, (i + 1) * n + j, (i + 1) * n + j + 1]
                c = v[q].mean(0)
                if ((c[0] - 0.0) / 0.015) ** 2 + ((c[2] - 1.684) / 0.006) ** 2 < 1:
                    continue                                  # the opening: an almond-ish hole
                tris += [(q[0], q[1], q[2]), (q[1], q[3], q[2])]
        t = np.array(tris)
        eyes = np.array([(0.0, 0.09, 1.684), (0.5, 0.09, 1.684)])     # the second has no opening
        mv, rep = CS.almond_moves(v, t, eyes, 0.2)
        self.assertEqual(rep["eyes"][1], "no opening edge found")
        rim = CS.eye_rims(v, t, eyes[:1])[0]
        up = rim[v[rim, 2] > 1.684]
        lo = rim[v[rim, 2] < 1.684]
        mid = up[np.argmin(np.abs(v[up, 0]))]
        corner = up[np.argmax(np.abs(v[up, 0]))]
        self.assertLess(mv[mid, 2], -0.001)                           # down at the middle
        self.assertGreater(mv[corner, 2], mv[mid, 2] * 0.5)           # little at the corners
        self.assertTrue(np.all(mv[lo] == 0))
        self.assertGreater(mv[mid, 1], 0)                             # forward: stays on the eyeball
        above = np.argmin(np.linalg.norm(v - (v[mid] + (0, 0, 0.004)), axis=1))
        self.assertLess(mv[above, 2], 0)
        self.assertGreater(mv[above, 2], mv[mid, 2])                  # the skin follows, less


class LandmarkTests(unittest.TestCase):
    def test_eye_shape_names(self):
        """2026-11-19 (Faendal): 'Brown' in an eyes shape's name is not a brow."""
        for name in ("MaleEyesWoodElfDeepBrown", "0RCOChildEyesBlue", "EyesFemaleHumanBrownBlind"):
            self.assertTrue(CS.is_eye_shape(name), name)
        for name in ("BrowsMaleHumanoid04", "FemaleEyeBrow02", "EyelashesFemale", "MaleHeadWoodElf"):
            self.assertFalse(CS.is_eye_shape(name), name)

    def test_mouth_is_the_largest_midline_opening(self):
        """2026-11-19 (Dorthe): a small opening by the nose, in front of the mouth, is not the mouth."""
        n = 81
        g = np.linspace(-0.08, 0.08, n)
        v = np.array([(x, 0.1 - 3 * (x * x + (z * 0.8) ** 2), 1.65 + z) for z in g for x in g])
        holes = [((-0.04, 1.684), 0.012, 0.005), ((0.04, 1.684), 0.012, 0.005),     # eyes
                 ((0.0, 1.608), 0.022, 0.006),                                      # mouth (large)
                 ((0.006, 1.645), 0.004, 0.003)]                                    # small, in front, by the nose
        tris = []
        for i in range(n - 1):
            for j in range(n - 1):
                q = [i * n + j, i * n + j + 1, (i + 1) * n + j, (i + 1) * n + j + 1]
                c = v[q].mean(0)
                if any(((c[0] - hx) / rx) ** 2 + ((c[2] - hz) / rz) ** 2 < 1 for (hx, hz), rx, rz in holes):
                    continue
                tris += [(q[0], q[1], q[2]), (q[1], q[3], q[2])]
        eyes, mouth = CS.starfield_eyes_mouth(v, np.array(tris))
        self.assertIsNotNone(eyes)
        self.assertAlmostEqual(float(mouth[2]), 1.608, delta=0.003)
        self.assertAlmostEqual(float(mouth[0]), 0.0, delta=0.003)


class FitTests(unittest.TestCase):
    def test_fit_narrows_the_face_and_keeps_the_sockets(self):
        """Starfield: a round head; Skyrim: the same 12 % narrower across. The face (front) narrows towards it, the
        back of the head and the eye sockets stay."""
        sf, t = sphere()
        sky, st = sphere(r=(0.09 * 0.88, 0.1, 0.11))
        eyes = np.array([(-0.035, 0.09, 1.69), (0.035, 0.09, 1.69)])
        mouth = np.array([0.0, 0.1, 1.61])
        disp, rep = CS.fit(sf, t, sky, st, eyes, mouth, rounds=((150, 0.7), (100, 0.7), (60, 0.7)),
                           normal_rounds=())
        cur = sf + disp
        cheek = (sf[:, 1] > 0.06) & (np.abs(sf[:, 2] - 1.64) < 0.01) & (np.abs(sf[:, 0]) > 0.03)
        self.assertLess(np.abs(cur[cheek, 0]).mean(), np.abs(sf[cheek, 0]).mean() - 0.002)
        back = sf[:, 1] < -0.02
        self.assertLess(np.abs(disp[back]).max(), 0.001)          # only the final smoothing's spill
        lock = CS.socket_lock(sf, eyes) == 0
        self.assertTrue(lock.any())
        self.assertLess(np.abs(disp[lock]).max(), 1e-12)
        self.assertEqual(rep["version"], CS.VERSION)

    def test_child_shape_needs_the_landmarks(self):
        sf, t = sphere(n=8, m=12)
        with self.assertRaises(ValueError):
            CS.child_shape(sf, t, sf, t, None, None)        # a closed sphere has no eye / mouth openings


class FaceFitTests(unittest.TestCase):
    def test_option_and_wrapper(self):
        import types
        sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
        sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import face_fit as S
        a = types.SimpleNamespace(child_shape_npc=["Frodnar"])
        self.assertTrue(S.uses_child_shape(a, {"edid": "frodnar"}))
        self.assertFalse(S.uses_child_shape(a, {"edid": "Dorthe"}))
        self.assertFalse(S.uses_child_shape(types.SimpleNamespace(), {"edid": "Frodnar"}))
        v, t = sphere(n=8, m=12)
        ctx = {"head": types.SimpleNamespace(vertices=v, triangles=t, model_xf=np.eye(4)),
               "al": (0.0143, np.eye(3), np.zeros(3), 0.0), "model_space": True, "base_tris": t}
        with self.assertRaises(ValueError):                       # no eye / mouth openings: the caller falls back
            S.child_shape_disp(ctx, v / 0.0143, b"not a nif")
        self.assertNotEqual(S.npc_fit_key("c", {}, b"f", "NordRaceChild", False),
                            S.npc_fit_key("c", {}, b"f", "NordRaceChild", False, ("child_shape",)))
        self.assertEqual(S.npc_fit_key("c", {}, b"f", "NordRace", False),
                         S.npc_fit_key("c", {}, b"f", "NordRace", False, None))


if __name__ == "__main__":
    unittest.main()


def _sheet_with_holes(tilt_deg=0.0, y=0.09, half=(0.012, 0.005), sep=0.032):
    """A flat face sheet (x across, z up, at depth y) with two elliptical eye holes (24-point edges) tilted tilt_deg
    outer corner up, plus a back sheet 15 cm behind; (vertices, triangles, eye centres)."""
    from scipy.spatial import Delaunay
    a = np.radians(tilt_deg)
    eyes = np.array([[-sep, y, 1.67], [sep, y, 1.67]])
    pts, rims = [], []
    th = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    for c in eyes:
        side = np.sign(c[0])
        u, h = half[0] * np.cos(th), half[1] * np.sin(th)
        ru, rh = u * np.cos(a) - h * np.sin(a), u * np.sin(a) + h * np.cos(a)
        rims.append(np.stack([c[0] + side * ru, c[2] + rh], 1))
    gx, gz = np.meshgrid(np.linspace(-0.08, 0.08, 41), np.linspace(1.61, 1.73, 31))
    grid = np.stack([gx.ravel(), gz.ravel()], 1)
    keep = np.ones(len(grid), bool)
    for c in eyes:
        keep &= np.hypot((grid[:, 0] - c[0]) / (half[0] + 0.003), (grid[:, 1] - c[2]) / (half[0] + 0.003)) > 1
    xz = np.concatenate(rims + [grid[keep]])
    tri = Delaunay(xz).simplices
    cen = xz[tri].mean(1)
    inside = np.zeros(len(tri), bool)
    for rim in rims:
        inside |= _in_poly(cen, rim)
    tri = tri[~inside]
    front = np.stack([xz[:, 0], np.full(len(xz), y), xz[:, 1]], 1)
    back = front.copy()
    back[:, 1] = y - 0.15
    v = np.concatenate([front, back])
    t = np.concatenate([tri, tri[:, ::-1] + len(front)])
    return v, t, eyes


def _in_poly(p, poly):
    """(N,) bool: 2D points inside a closed polygon (even-odd)."""
    x, z = p[:, 0], p[:, 1]
    inside = np.zeros(len(p), bool)
    for (x1, z1), (x2, z2) in zip(poly, np.roll(poly, -1, axis=0)):
        cross = ((z1 > z) != (z2 > z)) & (x < (x2 - x1) * (z - z1) / (z2 - z1 + 1e-15) + x1)
        inside ^= cross
    return inside


class EyeTiltTests(unittest.TestCase):
    """2026-11-19 (owner: elves' slanted eyes come with their eyes, per NPC): the slant measured on the NPC's own
    FaceGen eyes behind its lids, Starfield's openings turned to it."""

    def test_long_axis_tilt(self):
        th = np.linspace(0, 2 * np.pi, 60, endpoint=False)
        for deg in (0.0, 12.0, -8.0):
            a = np.radians(deg)
            u, h = 0.012 * np.cos(th), 0.005 * np.sin(th)
            pts = np.stack([-0.03 - (u * np.cos(a) - h * np.sin(a)), np.zeros(60), u * np.sin(a) + h * np.cos(a)], 1)
            self.assertAlmostEqual(CS.long_axis_tilt(pts, -1.0), deg, places=4)       # left eye: outer is -x
            pts[:, 0] = -pts[:, 0]
            self.assertAlmostEqual(CS.long_axis_tilt(pts, 1.0), deg, places=4)        # right eye mirrored

    def test_visible_eye_tilt_follows_the_lids(self):
        """Round eyeballs behind lids with a 15-degree opening: the visible part slants 15 degrees."""
        head_v, head_t, eyes = _sheet_with_holes(15.0)
        balls_v, balls_t = [], []
        th, ph = np.meshgrid(np.linspace(0, np.pi, 16), np.linspace(0, 2 * np.pi, 24, endpoint=False))
        for c in eyes:
            o = sum(len(b) for b in balls_v)
            p = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1).reshape(-1, 3)
            balls_v.append(c - [0, 0.009, 0] + 0.0115 * p[:, [0, 1, 2]])
            i = np.arange(16 * 24).reshape(24, 16)
            q = np.stack([i, np.roll(i, -1, 0), np.roll(i, -1, 0)[:, [*range(1, 16), 0]]], -1)[:, :-1].reshape(-1, 3)
            r = np.stack([i, np.roll(i, -1, 0)[:, [*range(1, 16), 0]], i[:, [*range(1, 16), 0]]], -1)[:, :-1]
            balls_t.append(np.concatenate([q, r.reshape(-1, 3)]) + o)
        rep = CS.visible_eye_tilt(head_v, head_t, np.concatenate(balls_v), np.concatenate(balls_t), samples=3000)
        self.assertIsNotNone(rep)
        for d in rep["tilt_deg"]:
            self.assertAlmostEqual(d, 15.0, delta=2.5)
        for f in rep["visible"]:
            self.assertTrue(0.2 < f < 0.97)

    def test_visible_eye_tilt_none_when_not_behind_the_lids(self):
        """Eyes nowhere near the head (two frames): None, not a made-up slant."""
        head_v, head_t, eyes = _sheet_with_holes(0.0)
        bv = np.array([[-0.03, 2.0, 0.0], [-0.02, 2.0, 0.0], [-0.03, 2.0, 0.01], [0.03, 2.0, 0.0], [0.02, 2.0, 0.0],
                       [0.03, 2.0, 0.01]])
        self.assertIsNone(CS.visible_eye_tilt(head_v, head_t, bv, np.array([[0, 1, 2], [3, 5, 4]]), samples=500))

    def test_tilt_moves_turn_the_openings(self):
        v, t, eyes = _sheet_with_holes(0.0)
        self.assertEqual([round(x) for x in CS.opening_tilts(v, t, eyes)], [0, 0])
        mv, rep = CS.tilt_moves(v, t, eyes, [18.0, 18.0])
        after = CS.opening_tilts(v + mv, t, eyes)
        for d in after:
            self.assertAlmostEqual(d, 18.0, delta=0.5)
        self.assertEqual(rep["turned_deg"], [18.0, 18.0])
        mag = np.linalg.norm(mv, axis=1)
        self.assertEqual(float(mag[len(v) // 2:].max()), 0.0)                          # the back sheet stays
        far = np.abs(v[:, 0]) > 0.032 + 0.012 + CS.TILT_FALLOFF + 0.002
        self.assertEqual(float(mag[far].max()), 0.0)                                   # the cheeks / temples stay
        np.testing.assert_allclose(mv[:, 1], 0.0)                                      # turned in the face plane

    def test_tilt_moves_clamped_and_skipped(self):
        v, t, eyes = _sheet_with_holes(0.0)
        _mv, rep = CS.tilt_moves(v, t, eyes, [80.0, None])
        self.assertEqual(rep["turned_deg"], [CS.TILT_MAX, 0.0])

    def test_human_eyes_turn_nothing(self):
        """An NPC whose eyes slant like Starfield's opening already (a human: -0.6 vs -0.5 measured) barely moves."""
        v, t, eyes = _sheet_with_holes(-0.5)
        mv, rep = CS.tilt_moves(v, t, eyes, [-0.6, -0.6])
        self.assertLess(float(np.linalg.norm(mv, axis=1).max()), 0.0002)
