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

    def test_plant_feet_lifts_a_sunk_ankle_by_bending_the_knee(self):
        c = clip([{}])
        res = R.retarget(c, self.sk, self.sf)
        res["t"] = res["t"].copy()
        res["t"][0, self.sf.index["COM"], 2] -= 0.05                    # Starfield hips 5 cm lower than Skyrim's
        res["world_t"], _ = self.sf.fk(res["t"], res["q"])
        foot = self.sf.index["L_Foot"]
        self.assertAlmostEqual(res["world_t"][0, foot, 2], 0.2 - 0.05, places=6)
        out = R.plant_feet(c, self.sk, self.sf, res)
        w = out["world_t"][0]
        self.assertAlmostEqual(w[foot, 2], 0.2, places=6)              # back at its rest height (Skyrim's foot never moved)
        th, ca = self.sf.index["L_Thigh"], self.sf.index["L_Calf"]
        self.assertAlmostEqual(np.linalg.norm(w[ca] - w[th]), 0.4, places=6)   # bone lengths kept
        self.assertAlmostEqual(np.linalg.norm(w[foot] - w[ca]), 0.4, places=6)
        self.assertGreater(w[ca, 1], 0.0)                              # straight leg: the knee bends forward
        self.assertAlmostEqual(out["feet_planted"], 0.05, places=4)

    def test_mat_to_quat_roundtrip(self):
        ax = np.array([0.267, 0.535, 0.802])
        q = np.array(qaxis(tuple(ax / np.linalg.norm(ax)), 73))
        x, y, z, w = q
        m = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
             [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
             [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        got = np.array(R.mat_to_quat(m))
        self.assertTrue(np.allclose(got, q, atol=1e-9) or np.allclose(got, -q, atol=1e-9))

    def test_rehome_into_another_hierarchy_keeps_world_pose(self):
        # source: Root -> COM -> Hips -> Thigh, WEAPON under Hips; target (like the game rig): Root first, Weapon
        # (other case) parented to COM, an extra Waist bone the source lacks, Thigh under Hips
        src = R.Rig(["Root", "COM", "C_Hips", "R_Thigh", "WEAPON"], [-1, 0, 1, 2, 2],
                    [(0, 0, 0), (0, 0, 1), (0, 0, 0.1), (0.1, 0, 0), (0.3, 0.2, 0)], [I, I, qaxis((0, 0, 1), 90), I, I])
        F = 3
        lt = np.repeat(src.t[None], F, 0)
        lq = np.repeat(src.q[None], F, 0)
        for f in range(F):
            lq[f, 3] = qaxis((1, 0, 0), 20 * f)                 # the thigh swings
            lt[f, 1] = (0, 0.05 * f, 1)                          # COM moves
        names, parents = ["Root", "COM", "C_Waist", "C_Hips", "R_Thigh", "Weapon"], [-1, 0, 1, 1, 3, 1]
        rest_t = np.array([(0, 0, 0), (0, 0, 1), (0, 0, 0.2), (0, 0, 0.1), (0.1, 0, 0), (0, 0, 0)])
        rest_q = np.array([I, I, qaxis((0, 1, 0), 30), I, I, I])
        ot, oq = R.rehome(src, lt, lq, names, parents, rest_t, rest_q)
        self.assertEqual(ot.shape, (F, 6, 3))
        wt, wq = src.fk(lt, lq)
        dst = R.Rig(names, parents, rest_t, rest_q)
        dt, dq = dst.fk(ot, oq)
        for j_src, j_dst in ((1, 1), (2, 3), (3, 4), (4, 5)):      # shared bones keep their world pose
            self.assertTrue(np.allclose(dt[:, j_dst], wt[:, j_src], atol=1e-9))
            self.assertTrue(np.allclose(np.abs(np.sum(dq[:, j_dst] * wq[:, j_src], -1)), 1, atol=1e-9))
        self.assertTrue(np.allclose(ot[:, 2], rest_t[2]) and np.allclose(oq[:, 2], rest_q[2]))   # rig-only: rest
        with self.assertRaises(ValueError):
            R.rehome(src, lt, lq, ["A", "B"], [1, -1], rest_t[:2], rest_q[:2])

    def test_rest_directions_are_aligned_to_skyrim(self):
        sk = R.Rig(["NPC Root [Root]", "NPC L Calf [LClf]", "NPC L Foot [Lft ]"], [-1, 0, 1],
                   [(0, 0, 0), (0, 0, 35), (0, 0, -30)], [I, I, I])           # Skyrim shin straight down
        tilt = math.radians(20)
        sf = R.Rig(["Root", "L_Calf", "L_Foot"], [-1, 0, 1],
                   [(0, 0, 0), (0, 0, 0.5), (0, 0.42 * math.sin(tilt), -0.42 * math.cos(tilt))], [I, I, I])
        c = {"frames": 1, "fps": 30.0, "bones": sk.names,
             "tracks": [[(tuple(sk.t[i]), tuple(sk.q[i]), (1, 1, 1))] for i in range(3)]}
        res = R.retarget(c, sk, sf)
        wt, _wq = sf.fk(res["t"], res["q"])
        shin = wt[0, 2] - wt[0, 1]
        self.assertTrue(np.allclose(shin / np.linalg.norm(shin), [0, 0, -1], atol=1e-9))   # points like Skyrim's
        self.assertAlmostEqual(float(np.linalg.norm(shin)), 0.42, places=9)             # Starfield's length

    def test_weapon_held_with_the_vanilla_grip(self):
        names = ["NPC Root [Root]", "NPC R Forearm [RLar]", "NPC R Hand [RHnd]", "WEAPON"]
        sk = R.Rig(names, [-1, 0, 1, 2], [(0, 0, 0), (0, 0, 60), (20, 0, 0), (5, 0, 0)], [I, I, I, I])
        sf = R.Rig(["Root", "R_Forearm", "R_Wrist", "Weapon", "R_HandIk"], [-1, 0, 1, 0, 3],
                   [(0, 0, 0), (0, 0, 0.9), (0.3, 0, 0), (0, 0.5, 1.2), (0, 0, 0)], [I, I, I, I, I])
        q_arm = qaxis((0, 0, 1), 50)
        c = {"frames": 1, "fps": 30.0, "bones": names,
             "tracks": [[(tuple(sk.t[i]), q_arm if i == 1 else tuple(sk.q[i]), (1, 1, 1))] for i in range(4)]}
        res = R.retarget(c, sk, sf)
        wt, wq = sf.fk(res["t"], res["q"])
        wr, wp, ik = sf.index["R_Wrist"], sf.index["Weapon"], sf.index["R_HandIk"]
        _h, gt, gq = R.M.GRIP["weapon"]
        gq = np.array(gq) / np.linalg.norm(gq)
        inv = R.qinv(wq[0, wr])
        self.assertTrue(np.allclose(R.qrot(inv, wt[0, wp] - wt[0, wr]), gt, atol=1e-9))
        rel = R.qmul(inv, wq[0, wp])
        self.assertTrue(np.allclose(rel, gq, atol=1e-6) or np.allclose(rel, -np.array(gq), atol=1e-6))
        self.assertTrue(np.allclose(wt[0, ik], wt[0, wr], atol=1e-9))           # IK target on the hand

    def test_hand_roll_is_aligned_by_the_knuckles(self):
        sk_names = ["NPC Root [Root]", "NPC R Hand [RHnd]", "NPC R Finger20 [RF20]", "NPC R Finger10 [RF10]",
                    "NPC R Finger40 [RF40]"]
        sk = R.Rig(sk_names, [-1, 0, 1, 1, 1], [(0, 0, 0), (0, 0, 70), (0, 7, 0), (-2, 6, 0), (2, 6, 0)], [I] * 5)
        r = math.radians(30)                                                # knuckle line rolled 30 deg about y
        sf = R.Rig(["Root", "R_Wrist", "R_Middle", "R_Index", "R_Pinky"], [-1, 0, 1, 1, 1],
                   [(0, 0, 0), (0, 0, 1.0), (0, 0.1, 0), (-0.03 * math.cos(r), 0.09, 0.03 * math.sin(r)),
                    (0.03 * math.cos(r), 0.09, -0.03 * math.sin(r))], [I] * 5)
        c = {"frames": 1, "fps": 30.0, "bones": sk_names,
             "tracks": [[(tuple(sk.t[i]), tuple(sk.q[i]), (1, 1, 1))] for i in range(5)]}
        res = R.retarget(c, sk, sf)
        wt, _ = sf.fk(res["t"], res["q"])
        across = wt[0, sf.index["R_Pinky"]] - wt[0, sf.index["R_Index"]]
        self.assertTrue(np.allclose(across / np.linalg.norm(across), [1, 0, 0], atol=1e-9))


if __name__ == "__main__":
    unittest.main()
