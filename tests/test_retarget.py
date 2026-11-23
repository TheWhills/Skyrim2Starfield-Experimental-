"""fo4sf.retarget on small synthetic skeletons named like the real ones (no game files)."""
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import retarget as R  # noqa: E402
from fo4sf import skeletonmap as M  # noqa: E402

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

    def test_reattach_keeps_the_weapon_in_the_moved_hand(self):
        # chest -> clavicle -> wrist, and the weapon hanging off the chest (Starfield's layout)
        sf = R.Rig(["C_Chest", "R_Clavicle", "R_Wrist", "Weapon"], [-1, 0, 1, 0],
                   [(0, 0, 1.4), (0.1, 0, 0), (0.5, 0, -0.3), (0.65, 0.05, -0.32)], [I, I, I, I])
        lt = np.repeat(sf.t[None], 2, axis=0)
        lq = np.repeat(sf.q[None], 2, axis=0)
        before = sf.fk(lt, lq)
        wr, wp = sf.index["R_Wrist"], sf.index["Weapon"]
        rel0 = R.qrot(R.qinv(before[1][:, wr]), before[0][:, wp] - before[0][:, wr])
        lq2 = lq.copy()
        lq2[:, sf.index["R_Clavicle"]] = qaxis((0, 1, 0), 27)               # the shoulder calibration's turn
        wt, wq = sf.fk(lt, lq2)
        drift = np.linalg.norm(R.qrot(R.qinv(wq[:, wr]), wt[:, wp] - wt[:, wr]) - rel0, axis=-1)
        self.assertGreater(float(drift.max()), 0.05)                          # the bug: the hand left the weapon
        lt3, lq3, moved = R.reattach(sf, lt, lq2, before, {wp: wr})
        wt, wq = sf.fk(lt3, lq3)
        rel = R.qrot(R.qinv(wq[:, wr]), wt[:, wp] - wt[:, wr])
        self.assertTrue(np.allclose(rel, rel0, atol=1e-9))
        self.assertTrue(np.allclose(np.abs(np.sum(R.qmul(R.qinv(wq[:, wr]), wq[:, wp]) *
                                                  R.qmul(R.qinv(before[1][:, wr]), before[1][:, wp]), -1)), 1, atol=1e-9))
        self.assertGreater(moved, 0.05)
        self.assertEqual(R.reattach(sf, lt, lq2, before, {})[2], 0.0)

    def test_look_ahead_turns_the_head_to_the_front_within_the_limit(self):
        sf = R.Rig(["Root", "C_Chest", "C_Neck", "C_Neck1", "C_Head", "C_Eye"], [-1, 0, 1, 2, 3, 4],
                   [(0, 0, 0), (0, 0, 1.4), (0, 0, 0.1), (0, 0, 0.05), (0, 0, 0.05), (0, 0.1, 0.05)], [I] * 6)
        F = 3
        lt = np.repeat(sf.t[None], F, axis=0)
        lq = np.repeat(sf.q[None], F, axis=0)
        head = sf.index["C_Head"]
        lq[0, head] = R.qmul(qaxis((0, 0, 1), -145), qaxis((1, 0, 0), -80))   # the dodge's head: right and down
        lq[1, sf.index["C_Chest"]] = qaxis((0, 0, 1), -100)                     # chest turned far right
        lt2, lq2, rep = R.look_ahead(sf, lt, lq, 75.0)
        _wt, wq = sf.fk(lt2, lq2)
        _rt, rq = sf.rest_world()
        def face(i, f):
            return R.qrot(R.qmul(wq[f, i], R.qinv(rq[i])), np.array([0.0, 1.0, 0.0]))
        self.assertTrue(np.allclose(face(head, 0), [0, 1, 0], atol=1e-6))          # chest forward: fully ahead
        chest_f = face(sf.index["C_Chest"], 1)
        ang = math.degrees(math.acos(np.clip(np.dot(face(head, 1), chest_f), -1, 1)))
        self.assertAlmostEqual(ang, 75.0, places=4)                                # held to the limit off the chest
        self.assertGreater(float(np.dot(face(head, 1), [0, 1, 0])), float(np.dot(chest_f, [0, 1, 0])))
        self.assertTrue(np.allclose(face(head, 2), [0, 1, 0], atol=1e-6))          # already ahead: unchanged
        self.assertTrue(np.allclose(lq2[2], lq[2], atol=1e-9))
        self.assertTrue(np.allclose(lq2[:, sf.index["C_Eye"]], lq[:, sf.index["C_Eye"]]))   # children follow
        self.assertGreater(rep["largest_turn_deg"], 90)
        self.assertEqual(rep["frames_turned"], 2)

    def test_mirror_grip_is_the_mirror_image(self):
        rng = np.random.default_rng(3)
        def rq():
            v = rng.normal(size=4)
            return v / np.linalg.norm(v)
        right_rest, left_rest, gq = rq(), rq(), rq()          # wrists whose axes are NOT mirror images
        gt = np.array([0.07, 0.01, -0.04])
        tl, ql = R.mirror_grip(gt, gq, right_rest, left_rest)
        # the same arm pose seen in a mirror: left wrist world = mirror(right wrist world) * (rest correction)
        pose = rq()
        rw = R.qmul(pose, right_rest)
        lw = R.qmul(R.qmirror_x(pose), left_rest)
        w_right = R.qmul(rw, gq)
        w_left = R.qmul(lw, ql)
        self.assertAlmostEqual(abs(float(np.dot(R.qmirror_x(w_right), w_left))), 1.0, places=9)
        off_r = R.qrot(rw, gt)
        off_l = R.qrot(lw, tl)
        self.assertTrue(np.allclose(off_r * [-1, 1, 1], off_l, atol=1e-12))
        h, t, q = M.LEFT_GRIP["weaponleft"]
        self.assertEqual(h, "L_Wrist")
        self.assertEqual(M.LEFT_WEAPON_AXES["weaponleft"][0], "Shield")

    def test_left_weapon_follows_skyrims_shield_node(self):
        names = ["NPC Root [Root]", "NPC L Hand [LHnd]", "Shield"]
        sk = R.Rig(names, [-1, 0, 1], [(0, 0, 0), (-30, 0, 70), (0, -2, 7)], [I, I, qaxis((1, 0, 0), 35)])
        sf = R.Rig(["Root", "L_Wrist", "WeaponLeft"], [-1, 0, 0], [(0, 0, 0), (-0.45, 0, 1.0), (-0.47, 0.07, 0.95)],
                   [I, qaxis((0, 1, 0), 20), I])
        q_hand = qaxis((0, 0, 1), 70)
        clip = {"frames": 1, "fps": 30.0, "bones": names,
                "tracks": [[(tuple(sk.t[i]), q_hand if i == 1 else tuple(sk.q[i]), (1, 1, 1))] for i in range(3)]}
        _wt_sk, wq_sk = sk.fk(*R.skyrim_locals(clip, sk))
        res = R.retarget(clip, sk, sf, weapon_in_hand=True, left_weapon=True)
        wt, wq = sf.fk(res["t"], res["q"])
        a = np.array(M.LEFT_WEAPON_AXES["weaponleft"][1], float)
        want = R.qmul(wq_sk[0, 2], a / np.linalg.norm(a))
        self.assertAlmostEqual(abs(float(np.dot(want, wq[0, 2]))), 1.0, places=6)      # blade as Skyrim's
        h, gt, gq = M.LEFT_GRIP["weaponleft"]
        rel = R.qmul(R.qinv(wq[0, 1]), wq[0, 2])
        gq = np.array(gq) / np.linalg.norm(gq)
        self.assertAlmostEqual(abs(float(np.dot(rel, gq))), 1.0, places=6)              # in the fist
        self.assertTrue(np.allclose(R.qrot(R.qinv(wq[0, 1]), wt[0, 2] - wt[0, 1]), gt, atol=1e-9))
        off = R.retarget(clip, sk, sf, weapon_in_hand=True)                              # off: WORLD rule as before
        wq_off = sf.fk(off["t"], off["q"])[1]
        self.assertLess(abs(float(np.dot(want, wq_off[0, 2]))), 0.9999)

    def test_fingers_stay_curled_in_a_turned_left_hand(self):
        names = ["NPC Root [Root]", "NPC L Hand [LHnd]", "NPC L Finger10 [LF10]", "Shield"]
        sk = R.Rig(names, [-1, 0, 1, 1], [(0, 0, 0), (-30, 0, 70), (-3, 0, 0), (0, -2, 7)],
                   [I, I, I, qaxis((1, 0, 0), 35)])
        sf = R.Rig(["Root", "L_Wrist", "L_Index", "WeaponLeft"], [-1, 0, 1, 0],
                   [(0, 0, 0), (-0.45, 0, 1.0), (-0.04, 0, 0), (-0.47, 0.07, 0.95)], [I, qaxis((0, 1, 0), 20), I, I])
        q_hand, q_curl = qaxis((0, 0, 1), 70), qaxis((0, 1, 0), 60)            # a curled finger in a turned hand
        tr = [(tuple(sk.t[i]), q_hand if i == 1 else q_curl if i == 2 else tuple(sk.q[i]), (1, 1, 1)) for i in range(4)]
        clip = {"frames": 1, "fps": 30.0, "bones": names, "tracks": [[x] for x in tr]}
        rel = {}
        for dual in (False, True):
            res = R.retarget(clip, sk, sf, weapon_in_hand=True, left_weapon=dual)
            _wt, wq = sf.fk(res["t"], res["q"])
            rel[dual] = R.qmul(R.qinv(wq[0, sf.index["L_Wrist"]]), wq[0, sf.index["L_Index"]])
            if dual:                                                            # the hand really was turned
                self.assertGreater(abs(float(np.dot(wq[0, sf.index["L_Wrist"]], qaxis((0, 1, 0), 20)))), 0)
        self.assertAlmostEqual(abs(float(np.dot(rel[False], rel[True]))), 1.0, places=6)   # same curl in the hand

    def test_pinky_under_the_cup_stays_curled_in_a_turned_left_hand(self):
        # Starfield's pinky hangs off L_Cup (kept at rest, no Skyrim source): the hand's turn must pass through it
        # (owner's run 2026-10-27: the left pinky stood out ~167 deg from rest in the dual attacks)
        names = ["NPC Root [Root]", "NPC L Hand [LHnd]", "NPC L Finger40 [LF40]", "Shield"]
        sk = R.Rig(names, [-1, 0, 1, 1], [(0, 0, 0), (-30, 0, 70), (-3, 1, 0), (0, -2, 7)],
                   [I, I, I, qaxis((1, 0, 0), 35)])
        sf = R.Rig(["Root", "L_Wrist", "L_Cup", "L_Pinky", "WeaponLeft"], [-1, 0, 1, 2, 0],
                   [(0, 0, 0), (-0.45, 0, 1.0), (-0.02, 0.01, 0), (-0.03, 0, 0), (-0.47, 0.07, 0.95)],
                   [I, qaxis((0, 1, 0), 20), qaxis((1, 0, 0), 15), I, I])
        q_hand, q_curl = qaxis((0, 0, 1), 70), qaxis((0, 1, 0), 60)
        tr = [(tuple(sk.t[i]), q_hand if i == 1 else q_curl if i == 2 else tuple(sk.q[i]), (1, 1, 1)) for i in range(4)]
        clip = {"frames": 1, "fps": 30.0, "bones": names, "tracks": [[x] for x in tr]}
        rel = {}
        for dual in (False, True):
            res = R.retarget(clip, sk, sf, weapon_in_hand=True, left_weapon=dual)
            _wt, wq = sf.fk(res["t"], res["q"])
            rel[dual] = R.qmul(R.qinv(wq[0, sf.index["L_Wrist"]]), wq[0, sf.index["L_Pinky"]])
        self.assertAlmostEqual(abs(float(np.dot(rel[False], rel[True]))), 1.0, places=6)   # same curl in the hand

    def test_two_bone_ik_reaches_and_keeps_the_hand(self):
        names = ["Root", "L_Biceps", "L_Forearm", "L_Wrist", "L_Index"]
        rig = R.Rig(names, [-1, 0, 1, 2, 3], [(0, 0, 1.4), (-0.3, 0, 0), (-0.28, 0, 0), (-0.25, 0, 0), (-0.08, 0, 0)],
                    [I, qaxis((0, 0, 1), 10), qaxis((0, 0, 1), 30), qaxis((1, 0, 0), 20), I])
        F = 3
        lt = np.repeat(rig.t[None], F, 0)
        lq = np.repeat(rig.q[None], F, 0)
        wt, wq = rig.fk(lt, lq)
        sh = wt[:, rig.index["L_Biceps"]]
        target = sh + np.array([[-0.2, 0.25, -0.1], [-0.3, 0.1, 0.05], [-2.0, 0.0, 0.0]])   # last: out of reach
        lt2, lq2, left = R.two_bone_ik(rig, lt, lq, "L_Biceps", "L_Forearm", "L_Wrist", target)
        wt2, wq2 = rig.fk(lt2, lq2)
        self.assertTrue(np.all(left[:2] < 1e-6))
        self.assertAlmostEqual(left[2], 2.0 - 0.53, places=4)                 # as far as the arm reaches
        for f in range(F):                                                     # the hand keeps its world rotation
            self.assertAlmostEqual(abs(float(np.dot(wq2[f, 3], wq[f, 3]))), 1.0, places=9)
        bone = lambda w, a, b: np.linalg.norm(w[:, rig.index[a]] - w[:, rig.index[b]], axis=-1)   # noqa: E731
        self.assertTrue(np.allclose(bone(wt2, "L_Biceps", "L_Forearm"), 0.28))  # lengths kept
        self.assertTrue(np.allclose(bone(wt2, "L_Forearm", "L_Wrist"), 0.25))
        self.assertTrue(np.allclose(lt2, lt) and np.allclose(lq2[:, 0], lq[:, 0]))   # nothing else moved

    def test_lift_hands_over_the_thighs(self):
        """Seated: the left hand rests 0.05 m above its thigh line and is lifted to 0.13 (and 0.03 outward), the hand
        keeping its rotation; a hand raised well above the thigh, and the right side with no arm bones, are left."""
        names = ["Root", "L_Thigh", "L_Calf", "L_Biceps", "L_Forearm", "L_Wrist", "R_Thigh", "R_Calf"]
        parents = [-1, 0, 1, 0, 3, 4, 0, 6]
        rig = R.Rig(names, parents, [(0, 0, 0), (-0.1, 0, 0.55), (0, 0.42, 0), (-0.2, -0.05, 1.05), (0, 0.05, -0.29),
                                     (0, 0.2, -0.16), (0.1, 0, 0.55), (0, 0.42, 0)], [I] * 8)
        lt = np.repeat(rig.t[None], 2, 0).copy()
        lq = np.repeat(rig.q[None], 2, 0).copy()
        lt[1, 3] = (-0.2, -0.05, 1.45)                                        # frame 1: the arm 0.4 m higher
        wt, wq = rig.fk(lt, lq)
        np.testing.assert_allclose(wt[0, 5], [-0.2, 0.2, 0.6], atol=1e-9)    # 0.05 above the thigh line, 0.1 outside it
        lt2, lq2, info = R.lift_hands(rig, lt, lq, 0.13, 0.12)
        wt2, wq2 = rig.fk(lt2, lq2)
        np.testing.assert_allclose(wt2[0, 5], [-0.22, 0.2, 0.68], atol=1e-6)  # up 0.08, out to 0.12
        self.assertAlmostEqual(abs(float(np.dot(wq2[0, 5], wq[0, 5]))), 1.0, places=9)
        np.testing.assert_allclose(wt2[1], wt[1], atol=1e-12)                 # raised hand: untouched
        self.assertEqual(info, {"L": {"frames": 1, "max_lift_m": 0.08}})
        _t, _q, none = R.lift_hands(rig, lt, lq, 0.04)
        self.assertEqual(none, {"L": {"frames": 0, "max_lift_m": 0.0}})       # already above: nothing to do
        stand = rig.t.copy()[None]
        stand[0, 2] = (0, 0.02, -0.42)                                        # thigh pointing down: standing
        stand[0, 3] = (-0.2, -0.05, 0.95)                                     # hand level with the thigh, beside it
        _t, _q, standing = R.lift_hands(rig, stand, rig.q[None].copy(), 0.13)
        self.assertEqual(standing["L"]["frames"], 0)
        low = rig.t.copy()[None]
        low[0, 3] = (-0.2, -0.05, 0.90)                                       # seated, hand 0.1 below the thigh line
        _t, _q, below = R.lift_hands(rig, low, rig.q[None].copy(), 0.13)
        self.assertEqual(below["L"]["frames"], 0)
        _t, _q, capped = R.lift_hands(rig, lt[:1], lq[:1], 0.30)
        self.assertEqual(capped["L"]["max_lift_m"], 0.1)                      # never more than max_lift

    def test_keep_contacts_hand_on_thigh(self):
        """Seated: Skyrim's wrist 0.02 m above its thigh's surface (radius 0.08); Starfield's arm, proportioned
        differently, puts it 0.03 inside. keep_contacts puts it 0.02 above Starfield's surface (scale 1), the hand's
        rotation kept; a hand far from the body (frame 1) is left alone."""
        from fo4sf import bodyprofile as BP
        sk = R.Rig(["Root", "NPC L Thigh [LThg]", "NPC L Calf [LClf]", "NPC L UpperArm [LUar]",
                    "NPC L Forearm [LLar]", "NPC L Hand [LHnd]"], [-1, 0, 1, 0, 3, 4],
                   [(0, 0, 0), (-0.1, 0, 0.5), (0, 0.45, 0), (-0.2, -0.05, 1.0), (0, 0.05, -0.25), (0.1, 0.2, -0.15)],
                   [I] * 6)
        sf = R.Rig(["Root", "L_Thigh", "L_Calf", "L_Biceps", "L_Forearm", "L_Wrist"], [-1, 0, 1, 0, 3, 4],
                   [(0, 0, 0), (-0.1, 0, 0.5), (0, 0.45, 0), (-0.2, -0.05, 1.0), (0, 0.05, -0.29), (0.1, 0.2, -0.16)],
                   [I] * 6)
        unit = 1.0
        sk_lt = np.repeat(sk.t[None], 2, 0).copy()
        sk_lt[1, 3] = (-0.2, -0.05, 1.4)                                       # frame 1: hand 0.4 m higher
        wt_sk, wq_sk = sk.fk(sk_lt, np.repeat(sk.q[None], 2, 0))
        flat = [[0.08] * BP.A_BINS] * BP.T_BINS
        a, b = np.array([-0.1, 0, 0.5]), np.array([-0.1, 0.45, 0.5])
        prof = {"radius": flat, "frame": BP.segment_frame(a, b).tolist(), "a": a.tolist(), "b": b.tolist()}
        profiles = {"skyrim": {"L_thigh": prof}, "starfield": {"L_thigh": prof}}
        lt = np.repeat(sf.t[None], 2, 0).copy()
        lt[1, 3] = (-0.2, -0.05, 1.4)
        lq = np.repeat(sf.q[None], 2, 0)
        wt0, wq0 = sf.fk(lt, lq)
        np.testing.assert_allclose(wt0[0, 5], [-0.1, 0.2, 0.55], atol=1e-9)
        lt2, lq2, rep = R.keep_contacts(sk, sf, lt, lq, wt_sk, wq_sk, profiles, unit=unit, sides=("L",))
        wt2, wq2 = sf.fk(lt2, lq2)
        np.testing.assert_allclose(wt2[0, 5], [-0.1, 0.2, 0.60], atol=1e-6)     # 0.08 + 0.02 above the axis
        self.assertAlmostEqual(abs(float(np.dot(wq2[0, 5], wq0[0, 5]))), 1.0, places=9)
        np.testing.assert_allclose(wt2[1], wt0[1], atol=1e-12)
        self.assertEqual(rep["L"]["frames"], 1)
        self.assertEqual(rep["L"]["segments"], {"L_thigh": 1})
        self.assertAlmostEqual(rep["L"]["max_move_m"], 0.05, places=3)
        _t, _q, half = R.keep_contacts(sk, sf, lt, lq, wt_sk, wq_sk, profiles, unit=unit, scale=0.5, sides=("L",))
        self.assertAlmostEqual(half["L"]["max_move_m"], 0.04, places=3)        # the gap scales: 0.08 + 0.01

    def test_shoulder_calibration_round_trip(self):
        """Our clavicles slope 15 deg down, the reference's 8 deg up: the calibration's offset, applied, makes our
        clavicle directions the reference's (in a turned body too), and the upper arm keeps its world rotation, so
        only the shoulder joint moves."""
        def rig_for(slope_deg, turn_deg=0.0):
            names = ["Root", "C_Chest", "C_Neck", "L_Clavicle", "L_Biceps", "L_Forearm", "R_Clavicle", "R_Biceps"]
            parents = [-1, 0, 1, 1, 3, 4, 1, 6]
            a = np.radians(slope_deg)
            arm_l = (-0.15 * np.cos(a), 0.0, -0.15 * np.sin(a))
            arm_r = (0.15 * np.cos(a), 0.0, -0.15 * np.sin(a))
            h = np.radians(turn_deg) / 2
            root_q = (0.0, 0.0, np.sin(h), np.cos(h))
            return R.Rig(names, parents, [(0, 0, 0), (0, 0, 1.2), (0, 0, 0.25), (-0.02, 0, 0.2), arm_l, (0, 0, -0.27),
                                          (0.02, 0, 0.2), arm_r], [root_q] + [I] * 7)
        def dirs(rig):
            wt, _wq = rig.fk(rig.t[None], rig.q[None])
            return R.clavicle_dirs({n: wt[:, rig.index[n]] for n in R.SHOULDER_BONES.values()})
        ours, ref = rig_for(15), rig_for(-8)
        cal = R.shoulder_calibration(dirs(ours), dirs(ref))
        self.assertEqual(sorted(cal), ["L", "R"])
        turned = rig_for(15, turn_deg=70)                                       # the actor faces another way
        lt, lq = turned.t[None].copy(), turned.q[None].copy()
        wt0, wq0 = turned.fk(lt, lq)
        lt2, lq2, rep = R.apply_shoulder_offsets(turned, lt, lq, cal)
        wt2, wq2 = turned.fk(lt2, lq2)
        got = R.clavicle_dirs({n: wt2[:, turned.index[n]] for n in R.SHOULDER_BONES.values()})
        want = dirs(ref)
        for side in ("L", "R"):
            np.testing.assert_allclose(got[side], want[side], atol=1e-6)
        self.assertEqual(rep, {"L": 23.0, "R": 23.0})
        b = turned.index["L_Biceps"]
        self.assertAlmostEqual(abs(float(np.dot(wq2[0, b], wq0[0, b]))), 1.0, places=9)   # the arm's direction kept
        self.assertGreater(wt2[0, b, 2], wt0[0, b, 2] + 0.05)                         # the shoulder joint went up
        self.assertEqual(R.apply_shoulder_offsets(turned, lt, lq, {})[2], None)

    def test_two_hand_grip_puts_the_support_hand_back_on_the_weapon(self):
        sk_names = ["NPC Root [Root]", "NPC R Hand [RHnd]", "Weapon", "NPC L UpperArm [LUar]",
                    "NPC L Forearm [LLar]", "NPC L Hand [LHnd]"]
        sk = R.Rig(sk_names, [-1, 0, 1, 0, 3, 4],
                   [(0, 0, 0), (-45, 5, 95), (2, 0, 5), (-15, 0, 100), (-18, 0, 0), (-16, 0, 0)], [I] * 6)
        sf = R.Rig(["Root", "R_Wrist", "Weapon", "L_Biceps", "L_Forearm", "L_Wrist"], [-1, 0, 0, 0, 3, 4],
                   [(0, 0, 0), (-0.6, 0.1, 1.4), (0.3, 0.4, 1.2), (-0.2, 0, 1.45), (-0.27, 0, 0), (-0.24, 0, 0)],
                   [I] * 6)
        # Skyrim: the left hand next to the weapon node (about 8 units away); the right hand holds the weapon
        bend = qaxis((0, 1, 0), -10)
        clip = {"frames": 2, "fps": 30.0, "bones": sk_names,
                "tracks": [[(tuple(sk.t[i]), bend if i in (3, 4) else tuple(sk.q[i]), (1, 1, 1))] * 2
                           for i in range(6)]}
        res = R.retarget(clip, sk, sf, two_hand_grip=True)
        lt, lq = sk.fk(*R.skyrim_locals(clip, sk))
        rel_sk = R.qrot(R.qinv(lq[0, 2]), lt[0, 5] - lt[0, 2]) * R.SKYRIM_M_PER_UNIT
        axes = np.array(M.WEAPON_AXES["weapon"][1], float)
        want = R.qrot(R.qinv(axes / np.linalg.norm(axes)), rel_sk)
        wt, wq = sf.fk(res["t"], res["q"])
        got = R.qrot(R.qinv(wq[0, 2]), wt[0, 5] - wt[0, 2])
        self.assertLess(res["two_hand_grip"]["after_m"], 1e-6)                  # reachable: exactly there
        self.assertGreater(res["two_hand_grip"]["before_m"], 0.05)              # and it was off before
        self.assertTrue(np.allclose(got, want, atol=1e-6))
        self.assertIsNone(R.retarget(clip, sk, sf)["two_hand_grip"])
        # the left hand lets go (far from the haft in Skyrim): the arm is left as retargeted
        free = {"frames": 1, "fps": 30.0, "bones": sk_names,
                "tracks": [[(tuple(sk.t[i]), qaxis((0, 1, 0), -90) if i == 3 else tuple(sk.q[i]), (1, 1, 1))]
                           for i in range(6)]}
        plain = R.retarget(free, sk, sf)
        held = R.retarget(free, sk, sf, two_hand_grip=True)
        self.assertEqual(held["two_hand_grip"]["released_frames"], 1)
        self.assertTrue(np.allclose(plain["q"], held["q"]) and np.allclose(plain["t"], held["t"]))

    def test_weapon_follows_skyrims_weapon_node_when_it_leaves_the_hand(self):
        names = ["NPC Root [Root]", "NPC R Hand [RHnd]", "Weapon", "NPC L Hand [LHnd]"]
        sk = R.Rig(names, [-1, 0, 1, 0], [(0, 0, 0), (20, 0, 80), (0, 0, 5), (-20, 0, 80)], [I] * 4)
        sf = R.Rig(["Root", "R_Wrist", "L_Wrist", "Weapon"], [-1, 0, 0, 0],             # hands before the weapon,
                   [(0, 0, 0), (0.3, 0, 1.1), (-0.3, 0, 1.1), (0.3, 0.1, 1.2)], [I] * 4)   # as in the real skeleton
        held = [(0, 0, 5), I]
        moved = [(-40, 3, 0), qaxis((0, 0, 1), 90)]               # the weapon node now sits by the left hand
        clip = {"frames": 2, "fps": 30.0, "bones": names,
                "tracks": [[(tuple(sk.t[i]), tuple(sk.q[i]), (1, 1, 1))] * 2 if i != 2 else
                           [(held[0], held[1], (1, 1, 1)), (moved[0], moved[1], (1, 1, 1))] for i in range(4)]}
        res = R.retarget(clip, sk, sf, weapon_in_hand=True)
        wt, wq = sf.fk(res["t"], res["q"])
        wt_sk, wq_sk = sk.fk(*R.skyrim_locals(clip, sk))
        h, gt, _gq = M.GRIP["weapon"]
        inv = R.qinv(wq[0, 1])
        self.assertTrue(np.allclose(R.qrot(inv, wt[0, 3] - wt[0, 1]), gt, atol=1e-9))     # frame 0: in the grip
        want_t = wt[1, 2] + (wt_sk[1, 2] - wt_sk[1, 3]) * R.SKYRIM_M_PER_UNIT               # frame 1: off the left
        self.assertTrue(np.allclose(wt[1, 3], want_t, atol=1e-9))
        a = np.array(M.WEAPON_AXES["weapon"][1], float)
        self.assertAlmostEqual(abs(float(np.dot(wq[1, 3], R.qmul(wq_sk[1, 2], a / np.linalg.norm(a))))), 1.0, places=9)

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

    def test_weapon_stays_in_fist_and_hand_turns_to_aim_it(self):
        names = ["NPC Root [Root]", "NPC R Forearm [RLar]", "NPC R Hand [RHnd]", "Weapon"]
        q_w = qaxis((1, 0, 0), 35)
        sk = R.Rig(names, [-1, 0, 1, 2], [(0, 0, 0), (0, 0, 60), (20, 0, 0), (5, 0, 0)], [I, I, I, q_w])
        sf = R.Rig(["Root", "R_Forearm", "R_Wrist", "Weapon"], [-1, 0, 1, 0],
                   [(0, 0, 0), (0, 0, 0.9), (0.3, 0, 0), (0, 0.5, 1.2)], [I, I, I, I])
        c = {"frames": 1, "fps": 30.0, "bones": names,
             "tracks": [[(tuple(sk.t[i]), tuple(sk.q[i]), (1, 1, 1))] for i in range(4)]}
        _h, gt, gq = M.GRIP["weapon"]
        gq = np.array(gq) / np.linalg.norm(gq)
        blade_sk = R.qrot(np.array(q_w), np.array([0, 1.0, 0]))               # Skyrim blade axis +Y
        for in_hand in (False, True):
            res = R.retarget(c, sk, sf, weapon_in_hand=in_hand)
            wt, wq = sf.fk(res["t"], res["q"])
            w, h = sf.index["Weapon"], sf.index["R_Wrist"]
            rel = R.qmul(R.qinv(wq[0, h]), wq[0, w])                           # always the vanilla grip: in the fist
            self.assertAlmostEqual(abs(float(np.dot(rel, gq))), 1.0, places=6)
            self.assertTrue(np.allclose(R.qrot(R.qinv(wq[0, h]), wt[0, w] - wt[0, h]), gt, atol=1e-6))
            blade_sf = R.qrot(wq[0, w], np.array([0, 0, 1.0]))                # Starfield blade axis +Z
            self.assertEqual(np.allclose(blade_sf, blade_sk, atol=1e-6), in_hand)   # aimed as in Skyrim when asked

    def test_blade_peak_is_fastest_tip_frame(self):
        rig = R.Rig(["Root", "Weapon"], [-1, 0], [(0, 0, 0), (0, 0, 1)], [I, I])
        angles = [0, 5, 10, 15, 60, 70, 72, 73]                       # the big swing is between frames 3 and 4
        q = np.array([[I, qaxis((1, 0, 0), a)] for a in angles], float)
        t = np.tile(rig.t, (len(angles), 1, 1))
        self.assertEqual(R.blade_peak(rig, t, q), 3)
        self.assertIsNone(R.blade_peak(R.Rig(["Root"], [-1], [(0, 0, 0)], [I]), t[:, :1], q[:, :1]))
    def test_hold_rest_rotation_keeps_pose(self):
        rig = R.Rig(["Root", "COM", "Spine", "Chest", "DirectAt"], [-1, 0, 1, 2, 3],
                    [(0, 0, 0), (0, 0, 1), (0, 0.1, 0.2), (0, 0, 0.3), (0, 0.05, 0)],
                    [I, qaxis((0, 1, 0), 90), I, qaxis((1, 0, 0), 10), qaxis((0, 0, 1), -20)])
        F = 3
        lt = np.tile(rig.t, (F, 1, 1))
        lq = np.tile(rig.q, (F, 1, 1))
        for f in range(F):                                             # the body turns, a lot, at COM and chest
            lq[f, 1] = R.qmul(qaxis((0, 0, 1), 40 * f), rig.q[1])
            lq[f, 3] = R.qmul(qaxis((0, 0, 1), 30 * f), rig.q[3])
        wt0, wq0 = rig.fk(lt, lq)
        t2, q2 = R.hold_rest_rotation(rig, lt, lq, ("COM", "DirectAt", "Missing"))
        wt, wq = rig.fk(t2, q2)
        _rt, rq = rig.rest_world()
        self.assertTrue(np.allclose(wt, wt0, atol=1e-9))              # every position unchanged
        for i in (1, 4):                                               # held bones at rest rotation
            self.assertTrue(np.allclose(np.abs(np.sum(wq[:, i] * rq[i], -1)), 1, atol=1e-9))
        for i in (2, 3):                                               # the others keep their world rotation
            self.assertTrue(np.allclose(np.abs(np.sum(wq[:, i] * wq0[:, i], -1)), 1, atol=1e-9))

    def test_copy_world_puts_follower_on_weapon(self):
        rig = R.Rig(["Root", "Chest", "Weapon", "R_Wrist", "R_AnimObject3", "Child"], [-1, 0, 1, 0, 3, 4],
                    [(0, 0, 0), (0, 0, 1), (0.2, 0.3, 0), (0.4, 0, 1), (0, 0, 0), (0, 0, 0.1)],
                    [I, I, qaxis((1, 0, 0), 50), qaxis((0, 1, 0), 30), I, I])
        lt, lq = np.tile(rig.t, (2, 1, 1)), np.tile(rig.q, (2, 1, 1))
        lq[1, 2] = qaxis((0, 0, 1), 70)
        wt0, wq0 = rig.fk(lt, lq)
        t2, q2 = R.copy_world(rig, lt, lq, {"R_AnimObject3": "Weapon", "Absent": "Weapon"})
        wt, wq = rig.fk(t2, q2)
        a, w, c = rig.index["R_AnimObject3"], rig.index["Weapon"], rig.index["Child"]
        self.assertTrue(np.allclose(wt[:, a], wt[:, w]) and np.allclose(np.abs(np.sum(wq[:, a] * wq[:, w], -1)), 1))
        self.assertTrue(np.allclose(wt[:, c], wt0[:, c]))             # its child stays where it was
        self.assertTrue(np.allclose(np.delete(wt, a, 1), np.delete(wt0, a, 1)))

    def test_ease_out_settles_on_last_pose(self):
        F = 12
        lt = np.zeros((F, 1, 3))
        lt[:, 0, 0] = np.linspace(0, 1.1, F)                           # constant speed to the very end
        lq = np.tile([0, 0, 0, 1.0], (F, 1, 1))
        lq[:, 0] = [qaxis((0, 0, 1), a) for a in np.linspace(0, 55, F)]
        t2, q2 = R.ease_out(lt, lq, 6)
        x = t2[:, 0, 0]
        self.assertTrue(np.allclose(x[:6], lt[:6, 0, 0]) and np.isclose(x[-1], 1.1))   # start and last pose kept
        self.assertTrue(np.all(np.diff(x) > 0))                                         # still moving forward
        self.assertLess(x[-1] - x[-2], 0.35 * 0.1)                                      # last step: a third of before
        self.assertTrue(np.allclose(np.linalg.norm(q2, axis=-1), 1))
        self.assertTrue(np.allclose(R.ease_out(lt, lq, 0)[0], lt))


class ConcatTest(unittest.TestCase):
    def clip(self, n, x0, bones=("A", "B"), fps=30.0, ann=()):
        tracks = [[((x0 + k, 0, 0), (0, 0, 0, 1), (1,)) for k in range(n)] for _ in bones]
        return {"fps": fps, "frames": n, "duration": (n - 1) / fps, "bones": list(bones), "bone_indices": [0, 1, 2][:len(bones)],
                "tracks": tracks, "annotations": [{"time": t, "text": x} for t, x in ann]}

    def test_concat(self):
        """2026-11-16 (the forge's Discard + Pull): frames appended, common bones only, annotations shifted, the
        largest bone turn across the cut reported."""
        a = self.clip(3, 0, ann=[(0.0, "a")])
        b = self.clip(4, 10, bones=("B", "A", "C"), ann=[(0.1, "b")])
        c = R.concat([a, b])
        self.assertEqual((c["frames"], c["bones"], c["concatenated"]), (7, ["A", "B"], [3, 4]))
        self.assertAlmostEqual(c["duration"], 6 / 30)
        self.assertEqual([f[0][0] for f in c["tracks"][0]], [0, 1, 2, 10, 11, 12, 13])
        self.assertEqual([round(x["time"], 4) for x in c["annotations"]], [0.0, 0.2])
        self.assertEqual(c["join_turn_deg"], [0.0])
        turned = self.clip(2, 0)
        turned["tracks"][1] = [((0, 0, 0), (0, 0, math.sin(math.radians(45)), math.cos(math.radians(45))), (1,))] * 2
        self.assertAlmostEqual(R.concat([a, turned])["join_turn_deg"][0], 90.0, places=1)
        self.assertEqual(R.concat([a, turned])["join_worst"][0][0], "B 90.0")
        prop = self.clip(2, 0, bones=("A", "AnimObjectL"))
        prop["tracks"][1] = turned["tracks"][1]                             # a prop bone's jump is not the body's
        self.assertEqual(R.concat([self.clip(2, 0, bones=("A", "AnimObjectL")), prop])["join_turn_deg"], [0.0])
        self.assertEqual(R.join_turns(a, turned)[0][:2], ("B", 90.0))
        self.assertIs(R.concat([a])["tracks"], a["tracks"])                 # one clip: itself

    def test_concat_blend(self):
        """A 0.1 s blend at 30 fps: B starts 3 frames early, the overlap moves from A's keys to B's, props cut."""
        a = self.clip(6, 0, bones=("A", "AnimObjectL"))
        b = self.clip(6, 100, bones=("A", "AnimObjectL"), ann=[(0.0, "b")])
        c = R.concat([a, b], blend=0.1)
        self.assertEqual((c["frames"], c["part_starts"], c["blend_frames"]), (9, [0, 3], 3))
        xs = [f[0][0] for f in c["tracks"][0]]
        self.assertEqual(xs[:3], [0, 1, 2])
        self.assertTrue(3 < xs[3] < xs[4] < xs[5] < 103, xs)                 # crossfading toward B
        self.assertEqual(xs[6:], [103, 104, 105])
        self.assertEqual([f[0][0] for f in c["tracks"][1]][3:6], [100, 101, 102])   # the prop: B's keys
        self.assertAlmostEqual(c["annotations"][0]["time"], 0.1)


if __name__ == "__main__":
    unittest.main()


class PropTests(unittest.TestCase):
    def test_place_props_keeps_skyrim_offset_and_rotation_from_the_starfield_hand(self):
        """2026-11-15 (broom): Starfield's prop bone gets Skyrim's prop world rotation and its world offset from the
        hand, measured from the Starfield hand, whatever the Starfield hand's own rotation."""
        import math
        I = [0.0, 0.0, 0.0, 1.0]
        h = math.sqrt(0.5)
        sk = R.Rig(["Root", "Hand", "AnimObjectR"], [-1, 0, 1], [[0, 0, 0], [0, 0, 100], [0, -20, -30]],
                   [I, [0, 0, h, h], [h, 0, 0, h]])
        sf = R.Rig(["Root", "R_Wrist", "R_AnimObject1"], [-1, 0, 1], [[0, 0, 0], [0.1, 0, 1.4], [0, 0, 0]],
                   [I, [0, h, 0, h], I])
        lt_sk, lq_sk = np.array([sk.t]), np.array([sk.q])
        wt_sk, wq_sk = sk.fk(lt_sk, lq_sk)
        out_t, out_q = np.array([sf.t], dtype=float), np.array([sf.q], dtype=float)
        unit = 0.01
        t, q, rep = R.place_props(sk, sf, out_t, out_q, wt_sk, wq_sk, unit, {"AnimObjectR": "R_AnimObject1"})
        wt, wq = sf.fk(t, q)
        want = wt[0, 1] + (wt_sk[0, 2] - wt_sk[0, 1]) * unit
        np.testing.assert_allclose(wt[0, 2], want, atol=1e-9)
        d = min(np.abs(wq[0, 2] - wq_sk[0, 2]).max(), np.abs(wq[0, 2] + wq_sk[0, 2]).max())
        self.assertLess(d, 1e-9)
        self.assertEqual(rep["R_AnimObject1"]["from"], "AnimObjectR")
        np.testing.assert_allclose(rep["R_AnimObject1"]["offset_m"], (wt_sk[0, 2] - wt_sk[0, 1]) * unit, atol=1e-3)
        _t, _q, rep2 = R.place_props(sk, sf, out_t, out_q, wt_sk, wq_sk, unit, {"AnimObjectL": "L_AnimObject1"})
        self.assertTrue(rep2["L_AnimObject1"]["missing"])
