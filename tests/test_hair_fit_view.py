"""scripts/armor/hair_fit_view.py: the head-depth test, region counts and the page, on synthetic data."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts", "armor"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import hair_fit_view as V  # noqa: E402


def sphere(n=4000, r=0.09, c=(0.0, 0.0, 1.65)):
    d = np.random.default_rng(2).normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    return np.asarray(c) + r * d, d


class FitViewTests(unittest.TestCase):
    def test_profile_lift_and_volume(self):
        from fo4sf import skyrimhair
        pts, nrm = sphere(8000)
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.65)

        def ring(height_by_angle):                           # hairline points 3 mm above the sphere
            out = []
            for ang, z in height_by_angle.items():
                a = np.radians(ang)
                horiz = np.sqrt(max(0.093 ** 2 - z ** 2, 0.0))
                out.append(head[:3, 3] + [horiz * np.sin(a), horiz * np.cos(a), z])
            return np.array(out)
        target = {a: 0.05 for a in skyrimhair.HAIRLINE_ANGLES}
        own = {a: (0.03 if abs(a) >= 50 else 0.045) for a in skyrimhair.HAIRLINE_ANGLES}   # low at the temples
        prof = skyrimhair.hairline_profile(ring(own), pts, nrm, head)
        for a in (0, 30, 60):
            self.assertAlmostEqual(prof[a], own[a], delta=0.002)
        lift = skyrimhair.lift_profile(prof, skyrimhair.hairline_profile(ring(target), pts, nrm, head))
        self.assertGreater(lift[70], lift[0] + 0.01)          # more lift at the temples than in the middle
        self.assertTrue(all(0.0 <= v <= 0.03 for v in lift.values()))
        self.assertEqual(skyrimhair.lift_profile({0: None, 10: None}, {0: 0.05, 10: 0.05}), {0: 0.0, 10: 0.0})
        ringed = ring(own)
        sh0 = skyrimhair.HairShape(b"R", ringed, np.zeros_like(ringed), np.zeros_like(ringed),
                                   [(0, 0)] * len(ringed), [(0, 1, 2)], [[("C_Head", 1.0)]] * len(ringed), -1, -1, 0)
        lifted = skyrimhair.lift_hairline(skyrimhair.Hair([sh0], [], {}, {}), pts, nrm, head, lift)
        after = skyrimhair.hairline_profile(np.asarray(lifted.shapes[0].positions), pts, nrm, head)
        self.assertLess(abs(after[60] - 0.05), abs(prof[60] - 0.05) - 0.008)   # the temples came up toward the target
        top = head[:3, 3] + [0.0, 0.0, 0.093]
        low = head[:3, 3] + [0.0, -0.093, -0.02]
        sh = skyrimhair.HairShape(b"S", np.array([top, low]), np.zeros((2, 3)), np.zeros((2, 3)), [(0, 0)] * 2,
                                  [(0, 1, 0)], [[("C_Head", 1.0)]] * 2, -1, -1, 0)
        out = np.asarray(skyrimhair.add_volume(skyrimhair.Hair([sh], [], {}, {}), pts, nrm, head, 0.01)
                         .shapes[0].positions)
        self.assertAlmostEqual(out[0, 2] - top[2], 0.01, delta=0.001)      # the top stands 1 cm off
        np.testing.assert_allclose(out[1], low, atol=1e-9)                  # below C_Head: untouched
        self.assertAlmostEqual(skyrimhair.crown_height(out, head), 0.103, delta=0.001)

    def test_lift_hairline_raises_the_front_keeps_the_back_and_the_gap(self):
        from fo4sf import skyrimhair
        pts, nrm = sphere(8000)
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.65)                      # C_Head at the sphere centre for this test
        d = np.array([[0.0, 0.8, 0.6], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, -0.3]])
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        p = head[:3, 3] + d * 0.094                           # 4 mm above the head: forehead, back, crown, cheek
        p[3] = head[:3, 3] + [0.0, 0.14, -0.04]               # a lock hanging well in front of the face
        sh = skyrimhair.HairShape(b"S", p, np.zeros((4, 3)), np.zeros((4, 3)), [(0, 0)] * 4, [(0, 1, 2)],
                                  [[("C_Head", 1.0)]] * 4, -1, -1, 0)
        out = np.asarray(skyrimhair.lift_hairline(skyrimhair.Hair([sh], [], {}, {}), pts, nrm, head,
                                                  0.015).shapes[0].positions)
        self.assertGreater(out[0, 2] - p[0, 2], 0.005)          # the forehead point went up
        np.testing.assert_allclose(out[1], p[1], atol=1e-9)     # the back stayed
        np.testing.assert_allclose(out[2], p[2], atol=1e-9)     # the crown stayed
        self.assertAlmostEqual(out[3, 2] - p[3, 2], 0.015)      # a lock off the head: lifted as is
        g0, _d, _i = skyrimhair.nearest_surface(p[:1], pts, nrm)
        g1, _d, _i = skyrimhair.nearest_surface(out[:1], pts, nrm)
        self.assertAlmostEqual(float(g1[0]), float(g0[0]), delta=0.0015)   # still ~4 mm above the head

    def test_push_out_conforms_without_pulling_in(self):
        from fo4sf import skyrimhair
        pts, nrm = sphere()
        cap = np.array([[0.0, 0.0, 1.65 + 0.085], [0.01, 0.0, 1.65 + 0.088], [0.0, 0.01, 1.65 + 0.10],
                        [0.0, -0.3, 1.2]])                       # 5 mm in, 2 mm in, 1 cm out, far below
        sh = skyrimhair.HairShape(b"S", cap, np.zeros((4, 3)), np.zeros((4, 3)), [(0, 0)] * 4, [(0, 1, 2)],
                                  [[("C_Head", 1.0)]] * 4, -1, -1, 0)
        out, rep = skyrimhair.push_out(skyrimhair.Hair([sh], [], {}, {}), pts, nrm)
        p = np.asarray(out.shapes[0].positions)
        depth, _dist, _i = skyrimhair.nearest_surface(p[:3], pts, nrm)
        self.assertTrue(np.all(depth >= 0.002 - 1e-4))             # all at least 2 mm outside
        self.assertTrue(np.all(np.linalg.norm(p[:3] - [0, 0, 1.65], axis=1) >=
                               np.linalg.norm(cap[:3] - [0, 0, 1.65], axis=1) - 1e-9))   # never pulled in
        np.testing.assert_allclose(p[3], cap[3])                  # not judged: untouched
        self.assertEqual(rep["vertices_moved"], 2)


    def test_depth_regions_and_page(self):
        pts, nrm = sphere()
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.62)
        probe = np.array([[0.0, 0.0, 1.65 + 0.07],      # 2 cm inside, top
                          [0.0, 0.08, 1.65],            # 1 cm inside, front
                          [0.0, -0.12, 1.60],           # outside, back
                          [0.0, 0.0, 1.65 + 0.095]])    # 5 mm outside
        d = V.head_depth(probe, pts, nrm)
        self.assertAlmostEqual(d[0], -0.02, delta=0.003)
        self.assertAlmostEqual(d[1], -0.01, delta=0.003)
        self.assertTrue(np.isnan(d[2]))                       # 3 cm off the head: not judged
        self.assertAlmostEqual(d[3], 0.005, delta=0.003)
        below = V.head_depth(np.array([[0.0, 0.0, 1.65 - 0.089]]), pts, nrm)   # at the neck cut: not judged
        self.assertTrue(np.isnan(below[0]))
        r = V.regions(probe, d, head)
        self.assertEqual((r["inside"], r["top"], r["forehead / face (front)"], r["back"]), (2, 1, 1, 0))
        self.assertEqual(r["judged (near the head)"], 3)
        self.assertAlmostEqual(r["deepest_mm"], 20.0, delta=3.0)
        line = np.array([[0.0, 0.0911, 1.66], [0.0, 0.0911, 1.70], [0.05, 0.08, 1.60], [0.0, 0.2, 1.50]])
        self.assertAlmostEqual(V.hairline(line, pts, nrm, head), 1.66 - 1.62, places=6)   # lowest on the front
        self.assertIsNone(V.hairline(line[2:], pts, nrm, head))                 # off the band / off the head
        html = V.page({"head": (pts[:10], np.ones((10, 3))), "wig": (probe, np.zeros((4, 3)))}, "T", r)
        self.assertIn("three.min.js", html)
        self.assertIn('"wig":{"p":[0,1720,0,', html)            # model (x, y, z) -> page (x, z, y), mm
        self.assertNotIn("DATAJSON", html)


if __name__ == "__main__":
    unittest.main()
