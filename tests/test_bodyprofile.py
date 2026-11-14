import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import bodyprofile as BP  # noqa: E402


def tube(a, b, rx, ry, n_t=40, n_a=64):
    """Points of an elliptic tube around the segment a -> b (a vertical or horizontal segment), radii rx (actor's x)
    and ry (actor's y) where they apply."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    fr = BP.segment_frame(a, b)
    pts = []
    for t in np.linspace(0.02, 0.98, n_t):
        c = a + t * (b - a)
        for th in np.linspace(-np.pi, np.pi, n_a, endpoint=False):
            d = np.cos(th) * fr[1] + np.sin(th) * fr[2]
            r = 1.0 / np.sqrt((d[0] / rx) ** 2 + (d[1] / ry) ** 2) if abs(d[2]) < 0.5 else max(rx, ry)
            pts.append(c + d * min(r, max(rx, ry)))
    return np.array(pts)


class BodyProfileTests(unittest.TestCase):
    def test_measure_tube_and_lookup(self):
        """A chest 0.15 m wide (x) and 0.10 m deep (y) around a vertical spine: the profile reads 0.10 forward and
        0.15 to the side; a thigh tube 0.08 round beside it keeps its own points (nearest segment)."""
        joints = {"S0": [0, 0, 1.0], "S1": [0, 0, 1.4], "T0": [0.4, 0, 0.5], "T1": [0.4, 0.45, 0.5]}
        pts = np.concatenate([tube(joints["S0"], joints["S1"], 0.15, 0.10),
                              tube(joints["T0"], joints["T1"], 0.08, 0.08)])
        prof = BP.measure(joints, pts, [("chest", "S0", "S1"), ("thigh", "T0", "T1")])
        self.assertEqual(sorted(prof), ["chest", "thigh"])
        fr = np.array(prof["chest"]["frame"])
        np.testing.assert_allclose(fr[0], [0, 0, 1], atol=1e-9)
        np.testing.assert_allclose(fr[1], [0, 1, 0], atol=1e-9)             # forward first
        fwd = BP.radius_at(prof["chest"], 0.5, 0.0)                           # angle 0 = forward
        side = BP.radius_at(prof["chest"], 0.5, np.arctan2(np.dot([1, 0, 0], fr[2]), np.dot([1, 0, 0], fr[1])))
        self.assertAlmostEqual(float(fwd), 0.10, delta=0.006)
        self.assertAlmostEqual(float(side), 0.15, delta=0.006)
        self.assertAlmostEqual(float(np.mean(prof["thigh"]["radius"])), 0.08, delta=0.002)
        n, d = BP.nearest(prof, [0.4, 0.2, 0.62])                             # 0.12 above the thigh axis
        self.assertEqual(n, "thigh")
        self.assertAlmostEqual(d, 0.04, delta=0.004)

    def test_summary_and_segments(self):
        sky = {"hips": {"radius": [[0.1] * BP.A_BINS] * BP.T_BINS}}
        sf = {"hips": {"radius": [[0.12] * BP.A_BINS] * BP.T_BINS}}
        self.assertEqual(BP.summary(sky, sf), [{"segment": "hips", "skyrim_m": 0.1, "starfield_m": 0.12,
                                                "ratio": 1.2}])
        sk = dict((n, (a, b)) for n, a, b in BP.segments_for("skyrim"))
        sfs = dict((n, (a, b)) for n, a, b in BP.segments_for("starfield"))
        self.assertEqual(sk["L_thigh"], ("NPC L Thigh [LThg]", "NPC L Calf [LClf]"))
        self.assertEqual(sfs["R_forearm"], ("R_Forearm", "R_Wrist"))
        from fo4sf import skeletonmap as M                                    # every pair maps joint to joint
        for _n, ska, skb, sfa, sfb in BP.SEGMENTS:
            self.assertEqual(M.MAP.get(ska), sfa)


if __name__ == "__main__":
    unittest.main()
