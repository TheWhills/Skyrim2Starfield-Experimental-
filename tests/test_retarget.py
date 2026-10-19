"""fo4sf.retarget on small synthetic skeletons named like the real ones (no game files)."""
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import retarget as R  # noqa: E402

I = (0.0, 0.0, 0.0, 1.0)


def qaxis(axis, deg):
    a = math.radians(deg) / 2
    x, y, z = axis
    return (x * math.sin(a), y * math.sin(a), z * math.sin(a), math.cos(a))


def skyrim_rig():
    # Havok units (70 per metre): COM at 70 (1 m), left leg straight down 63 units (0.9 m)
    names = ["NPC Root [Root]", "NPC COM [COM ]", "NPC Pelvis [Pelv]", "NPC L Thigh [LThg]", "NPC L Calf [LClf]",
             "NPC L Foot [Lft ]", "NPC R Thigh [RThg]", "NPC R Foot [Rft ]", "NPC Spine [Spn0]", "NPC Spine1 [Spn1]",
             "NPC Spine2 [Spn2]"]
    parents = [-1, 0, 1, 2, 3, 4, 2, 6, 1, 8, 9]
    t = [(0, 0, 0), (0, 0, 70), (0, 0, 0), (-7, 0, 0), (0, 0, -31.5), (0, 0, -31.5), (7, 0, 0), (0, 0, -63),
         (0, 0, 5), (0, 0, 10), (0, 0, 10)]
    return R.Rig(names, parents, t, [I] * len(names))


def starfield_rig():
    # metres; legs 0.8 m (shorter), spine with four bones; parents listed after children to test reordering
    names = ["L_Foot", "Root", "COM", "C_Hips", "L_Thigh", "L_Calf", "R_Thigh", "R_Foot", "C_Spine", "C_Spine1",
             "C_Spine2", "C_Chest"]
    parents = [5, -1, 1, 2, 3, 4, 3, 6, 2, 8, 9, 10]
    t = [(0, 0, -0.4), (0, 0, 0), (0, 0, 1.0), (0, 0, 0), (-0.1, 0, 0), (0, 0, -0.4), (0.1, 0, 0), (0, 0, -0.8),
         (0, 0, 0.05), (0, 0, 0.1), (0, 0, 0.1), (0, 0, 0.1)]
    return R.Rig(names, parents, t, [I] * len(names))


def clip(frames):
    """frames: list of {bone: (t, q)} overrides on rest."""
    sk = skyrim_rig()
    tracks = []
    for i, n in enumerate(sk.names):
        tracks.append([(f.get(n, (tuple(sk.t[i]), tuple(sk.q[i])))) for f in frames])
    return {"frames": len(frames), "fps": 30.0, "bones": list(sk.names),
            "tracks": [[(t, q, (1, 1, 1)) for t, q in tr] for tr in tracks]}


class RetargetTests(unittest.TestCase):
    def setUp(self):
        self.sk, self.sf = skyrim_rig(), starfield_rig()

    def test_reordered_parents_first(self):
        self.assertEqual(self.sf.names[0], "Root")
        for i, p in enumerate(self.sf.parents):
            self.assertLess(p, i)

    def test_rest_clip_gives_starfield_rest(self):
        res = R.retarget(clip([{}]), self.sk, self.sf)
        np.testing.assert_allclose(res["t"][0], self.sf.t, atol=1e-9)
        np.testing.assert_allclose(np.abs(res["q"][0][:, 3]), 1.0, atol=1e-9)

    def test_thigh_swing_transfers_and_lengths_stay_starfield(self):
        q = qaxis((1, 0, 0), 90)                              # left thigh forward 90 degrees
        res = R.retarget(clip([{"NPC L Thigh [LThg]": ((-7, 0, 0), q)}]), self.sk, self.sf)
        wt = res["world_t"][0]
        thigh, foot = wt[self.sf.index["L_Thigh"]], wt[self.sf.index["L_Foot"]]
        np.testing.assert_allclose(foot - thigh, (0, 0.8, 0), atol=1e-9)   # leg now points forward, 0.8 m long
        c = R.check(clip([{"NPC L Thigh [LThg]": ((-7, 0, 0), q)}]), self.sk, self.sf, res)
        self.assertEqual(c["segment_angle_change_deg"]["L_Thigh->L_Calf"], 0.0)

    def test_com_drop_scaled_by_leg_length(self):
        res = R.retarget(clip([{"NPC COM [COM ]": ((0, 0, 63), I)}]), self.sk, self.sf)   # COM 0.1 m down in Skyrim
        k = 0.8 / (63 * R.SKYRIM_M_PER_UNIT)                  # Starfield leg / Skyrim leg in metres
        self.assertAlmostEqual(res["height_scale"], k, places=9)
        com = res["world_t"][0][self.sf.index["COM"]]
        self.assertAlmostEqual(com[2], 1.0 - 7 * R.SKYRIM_M_PER_UNIT * k, places=9)

    def test_spine1_split_over_two_starfield_bones(self):
        q = qaxis((0, 1, 0), 40)
        res = R.retarget(clip([{"NPC Spine1 [Spn1]": ((0, 0, 10), q)}]), self.sk, self.sf)
        lq = res["q"][0]
        half = qaxis((0, 1, 0), 20)
        for name in ("C_Spine1", "C_Spine2"):                  # 20 degrees each, 40 in total
            np.testing.assert_allclose(np.abs(lq[self.sf.index[name]]), np.abs(half), atol=1e-6)
        np.testing.assert_allclose(lq[self.sf.index["C_Chest"]], I, atol=1e-6)   # chest: no extra turn

    def test_mat_to_quat_roundtrip(self):
        ax = np.array([0.267, 0.535, 0.802])
        q = np.array(qaxis(tuple(ax / np.linalg.norm(ax)), 73))
        x, y, z, w = q
        m = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
             [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
             [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        got = np.array(R.mat_to_quat(m))
        self.assertTrue(np.allclose(got, q, atol=1e-9) or np.allclose(got, -q, atol=1e-9))


if __name__ == "__main__":
    unittest.main()
