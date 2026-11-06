"""fo4sf.gearfit: Skyrim gear carried onto Starfield's skeleton and body (synthetic skeletons and surfaces)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import gearfit as G  # noqa: E402

PELV, SPN0, SPN1, SPN2 = "NPC Pelvis [Pelv]", "NPC Spine [Spn0]", "NPC Spine1 [Spn1]", "NPC Spine2 [Spn2]"
NECK, HEAD = "NPC Neck [Neck]", "NPC Head [Head]"
THG, CLF, FT, TOE = "NPC L Thigh [LThg]", "NPC L Calf [LClf]", "NPC L Foot [Lft ]", "NPC L Toe0 [LToe]"
SKIRT = "SkirtFBone01"


def at(p):
    m = np.eye(4)
    m[:3, 3] = p
    return m


SKY = {PELV: [0, 0, 1.0], SPN0: [0, 0, 1.1], SPN1: [0, 0, 1.25], SPN2: [0, 0, 1.4], NECK: [0, 0, 1.55],
       HEAD: [0, 0, 1.65], THG: [0.1, 0, 0.95], CLF: [0.1, 0, 0.5], FT: [0.1, 0, 0.08], TOE: [0.1, 0.12, 0.0],
       SKIRT: [0.05, 0.1, 0.8]}
# Starfield: 5 % smaller, 2 cm forward, the neck 4 cm lower relative to the chest, the left calf 20 % longer
SF = {"C_Hips": [0, 0.02, 0.95], "C_Spine": [0, 0.02, 1.045], "C_Spine1": [0, 0.02, 1.19], "C_Spine2": [0, 0.02, 1.26],
      "C_Chest": [0, 0.02, 1.33], "C_Neck": [0, 0.02, 1.43], "C_Head": [0, 0.02, 1.53],
      "L_Thigh": [0.095, 0.02, 0.9], "L_Calf": [0.095, 0.02, 0.4725], "L_Foot": [0.095, 0.02, -0.0265],
      "L_Toe": [0.095, 0.134, -0.1025]}
JOINTS = {b: at(p) for b, p in SKY.items() if b != SKIRT}
JOINTS_ALL = {b: at(p) for b, p in SKY.items()}
WORLD = {b: at(p) for b, p in SF.items()}


class MathTests(unittest.TestCase):
    def test_similarity(self):
        src = np.random.default_rng(1).normal(size=(10, 3))
        r = G.rot_between([1, 0, 0], [0, 1, 0])
        dst = 0.9 * src @ r.T + [1, 2, 3]
        m = G.similarity(src, dst)
        self.assertTrue(np.allclose(src @ m[:3, :3].T + m[:3, 3], dst))

    def test_rot_between(self):
        for a, b in (([1, 0, 0], [0, 0, 1]), ([0, 0, 1], [0, 0, -1]), ([1, 1, 0], [1, 1, 0])):
            r = G.rot_between(a, b)
            self.assertTrue(np.allclose(r @ (np.array(a) / np.linalg.norm(a)), np.array(b) / np.linalg.norm(b)))
            self.assertAlmostEqual(np.linalg.det(r), 1.0)


class BoneTests(unittest.TestCase):
    def setUp(self):
        self.t, self.rep = G.bone_transforms(JOINTS_ALL, WORLD)

    def apply(self, b, p):
        m = self.t[b]
        return m[:3, :3] @ np.array(p, float) + m[:3, 3]

    def test_joints_land_on_starfield_joints(self):
        for sky, sf in ((PELV, "C_Hips"), (NECK, "C_Neck"), (CLF, "L_Calf"), (FT, "L_Foot")):
            self.assertTrue(np.allclose(self.apply(sky, SKY[sky]), SF[sf], atol=1e-9), sky)

    def test_child_joint_reached_along_the_bone(self):
        # the calf's own transform carries the Skyrim foot joint onto Starfield's foot (length stretched)
        self.assertTrue(np.allclose(self.apply(CLF, SKY[FT]), SF["L_Foot"], atol=1e-6))
        sky_len = np.linalg.norm(np.subtract(SKY[FT], SKY[CLF])) * self.rep["global_scale"]
        sf_len = np.linalg.norm(np.subtract(SF["L_Foot"], SF["L_Calf"]))
        self.assertAlmostEqual(self.rep["bones"][CLF]["stretch"], sf_len / sky_len, places=3)

    def test_neck_and_spine_split(self):
        self.assertEqual(self.rep["bones"][SPN1]["to"], "C_Spine1")
        self.assertTrue(self.rep["bones"][PELV]["torso"])                    # torso: no turn, no stretch
        self.assertTrue(np.allclose(self.t[PELV][:3, :3], self.t[SPN0][:3, :3]))
        self.assertEqual(self.rep["bones"][HEAD]["turn_from"], NECK)

    def test_unmapped_bone_follows_nearest(self):
        self.assertIn("follows", self.rep["bones"][SKIRT])
        f = G.follow_map(JOINTS_ALL, self.t)
        self.assertIn(f[SKIRT], (PELV, THG))

    def test_blend_and_weights(self):
        bones = [CLF, FT, SKIRT, SPN1]
        pts = np.array([SKY[CLF], SKY[FT], SKY[SKIRT]], float)
        w = [[(0, 1.0)], [(0, 0.5), (1, 0.5)], [(2, 1.0)]]
        out, _n = G.blend(pts, np.tile([0.0, 1, 0], (3, 1)), bones, w, self.t)
        self.assertTrue(np.allclose(out[0], SF["L_Calf"], atol=1e-6))
        self.assertTrue(np.allclose(out[1], SF["L_Foot"], atol=1e-6))
        sw = G.sf_weights(bones, [[(0, 0.6), (2, 0.4)], [(3, 1.0)]], set(WORLD) | {"C_Spine2"},
                          G.follow_map(JOINTS_ALL, self.t))
        self.assertEqual(sw[1], [("C_Spine1", 0.5), ("C_Spine2", 0.5)])          # SPLIT shares the weight
        self.assertAlmostEqual(sum(w for _b, w in sw[0]), 1.0)
        self.assertIn("L_Calf", dict(sw[0]))


class AxialFitTests(unittest.TestCase):
    def test_arm_pose_does_not_tilt_the_torso(self):
        sky = {b: at(SKY[b]) for b in (PELV, SPN0, SPN1, SPN2, NECK, HEAD, THG, CLF, FT)}
        world = {f: at(SKY[s_]) for s_, f in ((PELV, "C_Hips"), (SPN0, "C_Spine"), (SPN1, "C_Spine1"),
                                              (SPN2, "C_Chest"), (NECK, "C_Neck"), (HEAD, "C_Head"),
                                              (THG, "L_Thigh"), (CLF, "L_Calf"), (FT, "L_Foot"))}
        arm = ["NPC L UpperArm [LUar]", "NPC L Forearm [LLar]", "NPC L Hand [LHnd]"]
        for k, b in enumerate(arm):                      # Skyrim arm out at 45 deg, Starfield's straight down
            sky[b] = at([0.2 + 0.2 * k, 0, 1.4 - 0.2 * k])
        for k, f in enumerate(["L_Biceps", "L_Forearm", "L_Wrist"]):
            world[f] = at([0.2, 0, 1.4 - 0.28 * k])
        t, rep = G.bone_transforms(sky, world)
        self.assertNotIn("NPC L UpperArm [LUar]", rep["fit_joints"])
        self.assertTrue(np.allclose(t[PELV][:3, :3], np.eye(3), atol=1e-9))
        self.assertGreater(rep["bones"]["NPC L UpperArm [LUar]"]["turn_deg"], 40)


class SurfaceTests(unittest.TestCase):
    def cylinder(self, r, n=24, rows=12):
        a = np.linspace(0, 2 * np.pi, n, endpoint=False)
        z = np.linspace(0, 1, rows)
        pts = np.array([[r * np.cos(t), r * np.sin(t), h] for h in z for t in a])
        nrm = np.array([[np.cos(t), np.sin(t), 0.0] for _h in z for t in a])
        return pts, nrm

    def test_offsets_and_push(self):
        sky, _ = self.cylinder(0.10)
        sf, sfn = self.cylinder(0.13)
        off, rep = G.body_offsets(sky, sf, sfn)
        self.assertGreater(rep["matched"], 0)
        self.assertAlmostEqual(float(np.median(np.linalg.norm(off, axis=1))), 0.03, places=2)
        gear = np.array([[0.11, 0.0, 0.5], [0.3, 0, 0.5]])
        out, n = G.push_out(gear, sf, sfn, gap=0.004)
        self.assertEqual(n, 1)
        self.assertGreater(out[0, 0], 0.13)
        self.assertTrue(np.allclose(out[1], gear[1]))

    def test_outward(self):
        pts, nrm = self.cylinder(0.1)
        self.assertTrue(np.allclose(G.outward(pts, -nrm), nrm))


class FitTests(unittest.TestCase):
    def tube(self, r, z0, z1, n=16, rows=8):
        a = np.linspace(0, 2 * np.pi, n, endpoint=False)
        pts = np.array([[r * np.cos(t), r * np.sin(t), h] for h in np.linspace(z0, z1, rows) for t in a])
        nrm = np.array([[np.cos(t), np.sin(t), 0.0] for _h in range(rows) for t in a])
        tris = []
        for i in range(rows - 1):
            for j in range(n):
                a0, a1 = i * n + j, i * n + (j + 1) % n
                tris += [(a0, a1, a0 + n), (a1, a1 + n, a0 + n)]
        return pts, nrm, tris

    def test_gear_on_a_wider_body(self):
        bones = [SPN0, SPN1]
        joints = {b: at(SKY[b]) for b in (PELV, SPN0, SPN1, SPN2, NECK, HEAD, THG, CLF, FT)}
        bp, bn, bt = self.tube(0.10, 1.05, 1.35)
        gp, gn, gt = self.tube(0.11, 1.10, 1.30)
        w = [[(0, 0.5), (1, 0.5)]] * len(bp)
        body = G.SkyShape(b"Body", bp, bn, [(0.0, 0.0)] * len(bp), bt, bones, w, joints)
        gear = G.SkyShape(b"Cuirass", gp, gn, [(0.0, 0.0)] * len(gp), gt, bones, [[(0, 0.5), (1, 0.5)]] * len(gp))
        skin = G.SkyShape(b"Skin", bp[:48].copy(), bn[:48], [(0.0, 0.0)] * 48, bt[:10], bones, w[:48])
        # Starfield: the same skeleton (no turn), a body 3 cm wider
        world = {f: at(SKY[s]) for s, f in ((PELV, "C_Hips"), (SPN0, "C_Spine"), (SPN1, "C_Spine1"),
                                            (SPN2, "C_Chest"), (NECK, "C_Neck"), (HEAD, "C_Head"),
                                            (THG, "L_Thigh"), (CLF, "L_Calf"), (FT, "L_Foot"))}
        world["C_Spine2"] = at([0, 0, 1.32])
        sp, _sn, st = self.tube(0.13, 1.0, 1.4, rows=12)
        res = G.fit([gear, skin], [body], world, sp, np.array(st))
        g = res.shapes[0]
        radius = np.linalg.norm(np.asarray(g.positions)[:, :2], axis=1)
        self.assertGreater(radius.min(), 0.13)                    # outside the Starfield body
        self.assertLess(radius.max(), 0.16)                       # moved with the body, not blown up
        self.assertFalse(res.report["shapes"]["Cuirass"]["skin_piece"])
        self.assertTrue(res.report["shapes"]["Skin"]["skin_piece"])
        self.assertEqual(sorted({b for vw in g.weights for b, _ in vw}), ["C_Spine", "C_Spine1", "C_Spine2"])
        self.assertEqual(res.report["shapes"]["Cuirass"]["far_outside"], 0)
        self.assertEqual(res.report["shapes"]["Cuirass"]["not_finite"], 0)


class BindTests(unittest.TestCase):
    def test_frame_and_binds(self):
        frame = at([0, 0, 1.632])
        binds = {}
        for b in ("C_Hips", "L_Calf"):
            m = np.linalg.inv(WORLD[b]) @ frame
            binds[b] = ((0, 0, 0, 0.1), tuple(m[:3, :3].reshape(9)), tuple(m[:3, 3]), 1.0)
        f = G.mesh_frame(binds, WORLD)
        self.assertTrue(np.allclose(f, frame))
        out = G.skeleton_binds(["L_Foot"], WORLD, f)
        rot, trans = np.array(out["L_Foot"][1]).reshape(3, 3), np.array(out["L_Foot"][2])
        # a mesh point at the foot joint lands at the bone origin
        p_mesh = np.linalg.inv(frame)[:3, :3] @ SF["L_Foot"] + np.linalg.inv(frame)[:3, 3]
        self.assertTrue(np.allclose(rot @ p_mesh + trans, 0, atol=1e-9))


if __name__ == "__main__":
    unittest.main()
