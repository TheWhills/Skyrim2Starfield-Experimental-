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
        for sky, sf in ((CLF, "L_Calf"), (FT, "L_Foot")):
            self.assertTrue(np.allclose(self.apply(sky, SKY[sky]), SF[sf], atol=1e-9), sky)
        # the torso moves as one piece by the overall fit: near its joints, not exactly on them
        self.assertLess(np.linalg.norm(self.apply(PELV, SKY[PELV]) - SF["C_Hips"]), 0.05)
        self.assertTrue(np.allclose(self.t[PELV], self.t[SPN2]))
        self.assertTrue(np.allclose(self.t[NECK][:3, :3], self.t[SPN2][:3, :3]))   # the neck moves with the torso,
        self.assertTrue(np.allclose(self.t[NECK][:2, 3], self.t[SPN2][:2, 3]))     # forward / sideways too,
        self.assertAlmostEqual(self.apply(NECK, SKY[NECK])[2], SF["C_Neck"][2])      # at its joint's height
        self.assertLessEqual(self.rep["bones"][NECK]["neck_height_ratio"], 1.0)

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
        self.assertTrue(self.rep["bones"][HEAD]["torso"])                     # the head moves with the torso

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
        nw = G.sf_weights([NECK], [[(0, 1.0)]], {"C_Neck", "C_Neck_Twist"}, {})
        self.assertEqual(nw[0], [("C_Neck_Twist", 1.0)])                        # the neck turns with the head
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

    def test_offsets_need_agreeing_normals_and_are_capped(self):
        sky, sky_n = self.cylinder(0.10)
        sf, sfn = self.cylinder(0.17)                    # 7 cm wider: capped at 4 cm
        off, _ = G.body_offsets(sky, sf, sfn, smooth=0, sky_nrm=sky_n)
        self.assertAlmostEqual(float(np.linalg.norm(off, axis=1).max()), G.CAP, places=6)
        off, rep = G.body_offsets(sky, sf, sfn, smooth=0, sky_nrm=-sky_n)   # facing the other way: no match
        self.assertEqual(rep["matched"], 0)
        self.assertEqual(float(np.abs(off).max()), 0.0)

    def test_triangle_push_reaches_between_vertices(self):
        # a coarse tube (8 sides): a point 1 cm inside the flat middle of a face, far from every vertex
        a = np.linspace(0, 2 * np.pi, 8, endpoint=False)
        z = np.array([0.0, 1.0])
        pts = np.array([[0.1 * np.cos(t), 0.1 * np.sin(t), h] for h in z for t in a])
        nrm = np.array([[np.cos(t), np.sin(t), 0.0] for _h in z for t in a])
        tris = []
        for j in range(8):
            a0, a1 = j, (j + 1) % 8
            tris += [(a0, a1, a0 + 8), (a1, a1 + 8, a0 + 8)]
        mid = (pts[0] + pts[1]) / 2 * 0.9 + [0, 0, 0.5]          # inside, under the middle of face 0
        out, n = G.push_out(np.array([mid]), pts, nrm, gap=0.004, tris=np.array(tris))
        self.assertEqual(n, 1)
        face_n = (pts[0] + pts[1]) / 2
        face_n = face_n / np.linalg.norm(face_n)
        depth = float((out[0] - (pts[0] + pts[1]) / 2 * np.array([1, 1, 0])) @ face_n)
        self.assertAlmostEqual(depth, 0.004, places=4)

    def test_cover_pushes_flat_faces_over_a_round_leg(self):
        # an 8-sided tube (corners at r = 0.1) round a leg of radius 0.095: the corners are outside, the middle of each
        # face (0.0924 from the axis) cuts into the leg
        a = np.linspace(0, 2 * np.pi, 8, endpoint=False)
        gear = np.array([[0.1 * np.cos(t), 0.1 * np.sin(t), h] for h in (0.0, 1.0) for t in a])
        gn = gear * [1, 1, 0]
        gn /= np.linalg.norm(gn, axis=1, keepdims=True)
        tris = []
        for j in range(8):
            a0, a1 = j, (j + 1) % 8
            tris += [(a0, a1, a0 + 8), (a1, a1 + 8, a0 + 8)]
        leg, leg_n = self.cylinder(0.095, n=64, rows=11)
        out, moved = G.cover(gear, gn, tris, leg, leg_n, gap=0.004)
        self.assertEqual(moved, 16)
        mid = (out[0] + out[1]) / 2
        self.assertGreater(np.linalg.norm(mid[:2]), 0.095)                 # faces now clear the leg
        self.assertLess(np.linalg.norm(out[0][:2]), 0.1 + G.COVER_MAX + 1e-9)
        # an inner layer (normals toward the leg) is left alone
        out2, moved2 = G.cover(gear, -gn, tris, leg, leg_n, gap=0.004)
        self.assertEqual(moved2, 0)

    def test_keep_gap_pulls_back_to_skyrims_gap(self):
        a = np.linspace(0, 2 * np.pi, 32, endpoint=False)
        z = np.linspace(0, 1, 6)
        sf = np.array([[0.1 * np.cos(t), 0.1 * np.sin(t), h] for h in z for t in a])
        sfn = np.array([[np.cos(t), np.sin(t), 0.0] for _h in z for t in a])
        tris = []
        for i in range(5):
            for j in range(32):
                a0, a1 = i * 32 + j, i * 32 + (j + 1) % 32
                tris += [(a0, a1, a0 + 32), (a1, a1 + 32, a0 + 32)]
        gear = np.array([[0.14, 0.0, 0.5], [0.12, 0.0, 0.5], [0.3, 0.0, 0.5]])
        sky_gap = np.array([0.01, 0.02, 0.2])              # 1 cm on Skyrim's body, 2 cm, a loose part far away
        out, n = G.keep_gap(gear, sky_gap, sf, np.array(tris), sfn)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(np.linalg.norm(out[0][:2]), 0.11, delta=0.002)    # back to a 1 cm gap
        self.assertTrue(np.allclose(out[1], gear[1]))       # already at its 2 cm
        self.assertTrue(np.allclose(out[2], gear[2]))       # loose: untouched

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
        g = res.report["shapes"]["Cuirass"]["gaps_mm"]["all"]
        self.assertAlmostEqual(g["skyrim"], 10.0, delta=1.0)                # 1 cm off the Skyrim body
        self.assertLess(g["starfield"], 15.0)                                  # kept close on Starfield's
        self.assertEqual(res.report["shapes"]["Cuirass"]["not_finite"], 0)

        # weight_src: gear near it takes its weights (the whole head: a collar turns with the head)
        res2 = G.fit([gear], [body], world, sp, np.array(st),
                     weight_src=(sp, np.array(st), [[("C_Head", 1.0)]] * len(sp)))
        self.assertEqual({b for vw in res2.shapes[0].weights for b, _ in vw}, {"C_Head"})
        # clavicles known: gear above them keeps its own weights, body weights below
        j2 = dict(joints, **{"NPC L Clavicle [LClv]": at([0.05, 0, 1.20]), "NPC R Clavicle [RClv]": at([-0.05, 0, 1.20])})
        body2 = G.SkyShape(b"Body", bp, bn, [(0.0, 0.0)] * len(bp), bt, bones, w, j2)
        w2 = dict(world, L_Clavicle=at([0.05, 0, 1.20]), R_Clavicle=at([-0.05, 0, 1.20]))
        res4 = G.fit([gear], [body2], w2, sp, np.array(st), sf_body_weights=[[("C_Chest", 1.0)]] * len(sp))
        g4 = res4.shapes[0]
        hi = np.asarray(gear.points)[:, 2] > 1.23
        lo = np.asarray(gear.points)[:, 2] < 1.20
        self.assertTrue(all("C_Chest" not in dict(g4.weights[i]) for i in np.nonzero(hi)[0]))
        self.assertTrue(any("C_Chest" in dict(g4.weights[i]) for i in np.nonzero(lo)[0]))
        # heads given: chin_clearance is not part of the fit any more (it dropped the cowl's back)
        top = gp[:, 2].max()
        cap = lambda z: (np.array([[-1, -1, z], [1, -1, z], [0, 1, z]]), [(0, 1, 2)])   # noqa: E731
        res3 = G.fit([gear], [body], world, sp, np.array(st), heads=(cap(top + 0.02), cap(top + 0.005)))
        self.assertEqual(res3.report["shapes"]["Cuirass"]["chin_lowered"], 0)


class ChinTests(unittest.TestCase):
    def test_gap_above(self):
        mp = np.array([[-1, -1, 1.0], [1, -1, 1.0], [0, 1, 1.0]])
        g = G.gap_above(np.array([[0, 0, 0.5], [5, 5, 0.5], [0, 0, 1.5]]), mp, [(0, 1, 2)])
        self.assertAlmostEqual(g[0], 0.5)
        self.assertTrue(np.isinf(g[1]) and np.isinf(g[2]))

    def test_chin_clearance_lowers_to_skyrims_gap(self):
        sky_head = (np.array([[-1, -1, 1.0], [1, -1, 1.0], [0, 1, 1.0]]), [(0, 1, 2)])
        sf_head = (np.array([[-1, -1, 0.97], [1, -1, 0.97], [0, 1, 0.97]]), [(0, 1, 2)])   # chin 3 cm lower
        sky = np.array([[0, 0, 0.95], [0.1, 0, 0.95], [3, 3, 0.95]])     # 5 cm under the Skyrim chin; one far
        pts = sky.copy()
        out, n, drop = G.chin_clearance(sky, pts, [(0, 1, 2)], sky_head, sf_head)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(drop, 0.03)
        self.assertAlmostEqual(out[0, 2], 0.92)                        # 5 cm under the Starfield chin again
        self.assertLess(out[2, 2], 0.95)                               # its neighbour follows a little
        self.assertTrue(np.allclose(out[:, :2], pts[:, :2]))            # only down
        same, n0, _d = G.chin_clearance(sky, pts, [(0, 1, 2)], sky_head, sky_head)
        self.assertEqual(n0, 0)


class NeckWrapTests(unittest.TestCase):
    @staticmethod
    def tube(r, z0, z1, n=24, rows=6):
        a = np.linspace(0, 2 * np.pi, n, endpoint=False)
        pts = np.array([[r * np.cos(t), r * np.sin(t), h] for h in np.linspace(z0, z1, rows) for t in a])
        tris = []
        for i in range(rows - 1):
            for j in range(n):
                a0, a1 = i * n + j, i * n + (j + 1) % n
                tris += [(a0, a1, a0 + n), (a1, a1 + n, a0 + n)]
        return pts, np.array(tris)

    def test_ray_hits(self):
        p, t = self.tube(0.05, 1.3, 1.6)
        d = G.ray_hits(np.array([[0, 0, 1.45], [0, 0, 2.0]]), np.array([[1.0, 0, 0], [1.0, 0, 0]]), p, t)
        self.assertAlmostEqual(d[0], 0.05, delta=0.002)
        self.assertTrue(np.isinf(d[1]))

    def test_collar_follows_the_thinner_neck(self):
        sky_neck = self.tube(0.06, 1.3, 1.6)
        sf_neck = self.tube(0.05, 1.3, 1.6)                       # Starfield's neck 1 cm thinner
        collar, ct = self.tube(0.07, 1.4, 1.5, rows=3)          # 1 cm off Skyrim's neck
        loose = collar * [1.3, 1.3, 1.0]                          # where the fit left it: standing off
        out, n, mx = G.neck_wrap(collar, loose, ct, sky_neck, sf_neck, np.zeros(3), np.zeros(3), 1.2, 1.2)
        r = np.linalg.norm(out[:, :2], axis=1)
        self.assertEqual(n, len(collar))
        self.assertTrue(np.allclose(r, 0.06, atol=0.003))          # 1 cm off the Starfield neck again
        self.assertTrue(np.allclose(out[:, 2], loose[:, 2]))        # horizontal only
        # necks given and the Skyrim ray meets something else first (the shoulders): left alone
        shoulders = self.tube(0.065, 1.3, 1.6)
        out3, n3, _m = G.neck_wrap(collar, loose, ct, shoulders, sf_neck, np.zeros(3), np.zeros(3), 1.2, 1.2,
                                   necks=(sky_neck, sf_neck))
        self.assertEqual(n3, 0)
        out4, n4, _m = G.neck_wrap(collar, loose, ct, sky_neck, sf_neck, np.zeros(3), np.zeros(3), 1.2, 1.2,
                                   necks=(sky_neck, sf_neck))
        self.assertEqual(n4, len(collar))
        far = collar * [1.8, 1.8, 1.0]                             # Skyrim's own gap too big: left alone
        out2, n2, _m = G.neck_wrap(far, far, ct, sky_neck, sf_neck, np.zeros(3), np.zeros(3), 1.2, 1.2)
        self.assertEqual(n2, 0)


class BuryTests(unittest.TestCase):
    def test_hidden_rim_stays_inside(self):
        neck = NeckWrapTests.tube(0.05, 1.3, 1.6, n=32, rows=8)
        nrm = neck[0].copy()
        nrm[:, 2] = 0
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
        rim, rt = NeckWrapTests.tube(0.07, 1.40, 1.50, rows=3)    # a collar: bottom row outside, top row pushed out
        sky_gap = np.repeat([0.02, 0.0, -0.02], 24)               # in Skyrim the top row was 2 cm inside the neck
        mask = sky_gap < -G.BURY
        out, n = G.bury(rim, sky_gap, mask, rt, neck[0], neck[1], nrm)
        r = np.linalg.norm(out[:, :2], axis=1)
        self.assertEqual(n, 24)
        self.assertTrue(np.allclose(r[mask], 0.03, atol=0.002))   # 2 cm inside the 5 cm neck
        self.assertTrue((r[~mask] >= 0.05 + G.GAP - 1e-3).all())  # the rest still outside


class DrapeTests(unittest.TestCase):
    @staticmethod
    def plane(z, half=0.3, n=7):
        g = np.linspace(-half, half, n)
        pts = np.array([[x, y, z] for y in g for x in g])
        tris = []
        for j in range(n - 1):
            for i in range(n - 1):
                a = j * n + i
                tris += [(a, a + 1, a + n), (a + 1, a + n + 1, a + n)]
        return pts, np.array(tris)

    def test_surface_below(self):
        p, t = self.plane(1.0)
        h, nz = G.surface_below(np.array([[0.05, 0.02, 1.2], [0.0, 0.0, 0.9], [2.0, 0, 1.2]]), p, t)
        self.assertAlmostEqual(h[0], 1.0)
        self.assertAlmostEqual(nz[0], 1.0)
        self.assertTrue(np.isnan(h[1]) and np.isnan(h[2]))

    def test_cowl_follows_lower_shoulders(self):
        sky_sh = self.plane(1.40)                                 # Skyrim shoulders
        sf_sh = self.plane(1.36)                                  # Starfield's 4 cm lower
        sky = np.array([[0.10, 0.0, 1.43], [-0.12, 0.02, 1.44], [0.10, 0.0, 1.60]])   # 3-4 cm up; one far above
        fitted = sky * [0.8, 0.8, 1.0]                            # where the fit left it: pulled in, same height
        out, n, _mx = G.drape(sky, fitted, [], sky_sh, sf_sh, np.zeros(3), np.zeros(3), 1.35)
        self.assertEqual(n, 2)
        self.assertTrue(np.allclose(out[:2], sky[:2] - [0, 0, 0.04], atol=0.004))   # same spot, 4 cm lower
        self.assertTrue(np.allclose(out[2], fitted[2]))                              # too far above: kept


class ShoulderDropTests(unittest.TestCase):
    def test_field_and_drop(self):
        sky = DrapeTests.plane(1.40)
        sf = DrapeTests.plane(1.36)                               # Starfield's shoulders 4 cm lower
        field = G.shoulder_drop_field(sky[0], sky[1], sf[0], sf[1], np.zeros(2), 2.0)
        self.assertTrue(np.allclose(field, -0.04, atol=1e-6))
        pts = np.array([[0.05, 0.0, 1.50], [0.30, 0.0, 1.50], [0.05, 0.0, 1.20]])   # near the neck; far out; low
        out = G.shoulder_drop(pts, field, np.zeros(2), 1.40)
        self.assertAlmostEqual(out[0, 2], 1.46)
        self.assertAlmostEqual(out[1, 2], 1.50)
        self.assertAlmostEqual(out[2, 2], 1.20)
        self.assertIsNone(G.shoulder_drop_field(sky[0], sky[1], sf[0], sf[1], np.array([5.0, 5.0]), 2.0))


class CollarHeightTests(unittest.TestCase):
    def test_field_brings_the_top_down_to_skyrims(self):
        a = np.linspace(0, 2 * np.pi, 32, endpoint=False)
        ring = lambda z: np.column_stack([0.07 * np.sin(a), 0.07 * np.cos(a), np.full(32, z)])  # noqa: E731
        sky = np.concatenate([ring(1.55), ring(1.50)])               # Skyrim top 25 cm under a 1.80 crown
        ours = np.concatenate([ring(1.59), ring(1.50)])              # ours 4 cm higher under the same crown
        vis = np.ones(64, bool)
        f = G.collar_height_field(sky, vis, np.zeros(2), 1.80, ours, vis, np.zeros(2), 1.80)
        self.assertTrue(np.allclose(f, -0.04, atol=1e-6))
        low = np.concatenate([ring(1.53), ring(1.50)])               # already lower: never raised
        self.assertTrue(np.allclose(G.collar_height_field(sky, vis, np.zeros(2), 1.80, low, vis, np.zeros(2), 1.80), 0))
        hidden = np.zeros(64, bool)
        self.assertIsNone(G.collar_height_field(sky, hidden, np.zeros(2), 1.80, ours, hidden, np.zeros(2), 1.80))


class SkirtTests(unittest.TestCase):
    def test_skirt_bones_share_hips_and_thighs(self):
        self.assertEqual(dict(G.skirt_shares("SkirtFBone02")), {"C_Hips": 0.5, "L_Thigh": 0.25, "R_Thigh": 0.25})
        self.assertEqual(dict(G.skirt_shares("SkirtLBone01")), {"C_Hips": 0.6, "L_Thigh": 0.4})
        self.assertEqual(G.skirt_shares("NPC L Thigh [LThg]"), [])
        w = G.sf_weights(["SkirtRBone03", THG], [[(0, 1.0)], [(0, 0.3), (1, 0.7)]], {"C_Hips", "R_Thigh", "L_Thigh"},
                         {})
        self.assertEqual(dict(w[0]), {"C_Hips": 0.6, "R_Thigh": 0.4})
        self.assertEqual(G.skirt_weighted(["SkirtRBone03", THG], [[(0, 1.0)], [(0, 0.3), (1, 0.7)]]).tolist(),
                         [True, False])


class SkirtGradientTests(unittest.TestCase):
    def test_hips_at_top_thighs_below_split_by_side(self):
        j = {PELV: at([0, 0, 1.0]), "NPC L Thigh [LThg]": at([0.1, 0, 0.95]), "NPC R Thigh [RThg]": at([-0.1, 0, 0.95]),
             "NPC L Calf [LClf]": at([0.1, 0, 0.5]), "NPC R Calf [RClf]": at([-0.1, 0, 0.5])}
        w = G.skirt_gradient(np.array([[0, 0, 1.0], [0.15, 0, 0.5], [0, 0.1, 0.75]]), j)
        self.assertAlmostEqual(dict(w[0])["C_Hips"], 1 - G.SKIRT_THIGH[0])
        self.assertAlmostEqual(dict(w[0])["L_Thigh"], G.SKIRT_THIGH[0] / 2)
        self.assertEqual(sorted(dict(w[1])), ["C_Hips", "L_Thigh"])            # left side, at the knee
        self.assertAlmostEqual(dict(w[1])["L_Thigh"], G.SKIRT_THIGH[1])
        self.assertAlmostEqual(dict(w[2])["L_Thigh"], dict(w[2])["R_Thigh"])   # front centre: both thighs
        self.assertIsNone(G.skirt_gradient(np.zeros((1, 3)), {}))


class HangSkirtTests(unittest.TestCase):
    def test_hull_radius(self):
        sq = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1], [0, 0]], float)
        h = G._hull(sq)
        self.assertEqual(len(h), 4)
        r = G._hull_radius(h, np.array([0.0, np.pi / 2, np.pi / 4]))
        self.assertTrue(np.allclose(r, [1.0, 1.0, np.sqrt(2)]))

    def test_flared_skirt_hangs_at_its_length(self):
        body, _t = NeckWrapTests.tube(0.15, 0.4, 1.0, n=32, rows=13)     # hips / legs: a 15 cm tube
        a = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        ring = lambda r, z: np.column_stack([r * np.sin(a), r * np.cos(a), np.full(16, z)])   # noqa: E731
        sky = np.concatenate([ring(0.17, 0.95), ring(0.22, 0.85), ring(0.27, 0.75)])   # flared like an A
        out, n = G.hang_skirt(sky.copy(), np.ones(48, bool), body, np.zeros(3), sky_pts=sky, sky_axis=np.zeros(3))
        r = np.hypot(out[:, 0], out[:, 1])
        self.assertEqual(n, 32)                                      # the top ring stays
        exp_hem = 0.15 + G.HANG_GAP + G.HANG_KEEP * 0.12        # outline + gap + kept share of the 12 cm flare
        self.assertTrue(np.allclose(r[32:], exp_hem, atol=0.005))
        self.assertTrue((r[16:32] < 0.22).all() and (r[16:32] > 0.15).all())   # in from the flare, off the legs
        L = np.hypot(0.27 - 0.17, 0.20)
        self.assertTrue(np.allclose(out[32:, 2], 0.95 - np.sqrt(L ** 2 - (exp_hem - 0.17) ** 2), atol=0.01))
        self.assertLess(out[32, 2], 0.75)                                    # longer than the flared hem


class WrapParamsTests(unittest.TestCase):
    def test_head_joint_stands_in_for_the_neck(self):
        tri = (np.eye(3), np.array([[0, 1, 2]]))
        j = {"NPC L Clavicle [LClv]": at([0.05, 0, 1.4]), "NPC Head [Head]": at([0, 0.01, 1.6])}
        w = {"L_Clavicle": at([0.05, 0, 1.38]), "C_Head": at([0, 0.02, 1.58])}
        r = G.wrap_params((tri, tri), np.eye(3), [[0, 1, 2]], np.eye(3), [[0, 1, 2]], j, w)
        self.assertIsNotNone(r)
        self.assertTrue(np.allclose(r[2], [0, 0.01, 1.6]) and np.allclose(r[3], [0, 0.02, 1.58]))


class StretchTests(unittest.TestCase):
    def test_edge_stretch(self):
        sky = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        now = sky * [2.0, 1.0, 1.0]
        st = sorted(G.edge_stretch(sky, now, [(0, 1, 2)]).round(3).tolist())
        self.assertEqual(st, [1.0, round(np.sqrt(5) / np.sqrt(2), 3), 2.0])
        self.assertEqual(len(G.edge_stretch(sky, now, [(0, 1, 2)], mask=[True, True, False])), 0)


class TransplantTests(unittest.TestCase):
    def test_neck_rim_centre(self):
        body, t = NeckWrapTests.tube(0.06, 1.3, 1.5)               # an open tube: rims at 1.3 and 1.5
        c = G.neck_rim_centre(body, t, window=0.05)
        self.assertTrue(np.allclose(c, [0, 0, 1.5], atol=1e-9))

    def test_collar_copied_whole_near_the_opening(self):
        sky = np.array([[0.05, 0, 1.5], [0.30, 0, 1.3]])
        fitted = np.array([[0.04, 0, 1.47], [0.31, 0, 1.25]])
        out, w = G.collar_transplant(sky, fitted, (np.array([0, 0, 1.5]), np.array([0, 0.01, 1.45])))
        self.assertTrue(np.allclose(out[0], [0.05, 0.01, 1.45]))        # copied: same offset from the opening
        self.assertTrue(np.allclose(out[1], fitted[1]))                  # far: the fit's
        self.assertEqual(w.tolist(), [1.0, 0.0])


class FaceLiftTests(unittest.TestCase):
    def test_face_dipping_into_a_bump_is_lifted(self):
        body = np.array([[-1, -1, 0], [1, -1, 0], [0, 1, 0], [0, 0, 0.02]], float)      # a 2 cm bump in the middle
        bt = [(0, 1, 3), (1, 2, 3), (2, 0, 3)]
        bn = np.tile([0, 0, 1.0], (4, 1))
        gear = np.array([[-0.05, -0.05, 0.022], [0.05, -0.05, 0.022], [0.0, 0.05, 0.022]])   # corners just over it
        gear[:, :2] *= 6                                                     # a big face over the bump's top
        gear[:, 2] = [0.016, 0.016, 0.016]                                  # corners 2 mm out, centre 4 mm in
        out, n = G.push_faces_out(gear, [(0, 1, 2)], body, bt, bn)
        c = out.mean(0)
        _cp, dep, _d = G.closest_on_mesh(c[None], body, np.array(bt), bn)
        self.assertGreater(n, 0)
        self.assertGreaterEqual(dep[0], G.FACE_GAP - 1e-4)


class FinalRelaxTests(unittest.TestCase):
    def test_spike_smoothed_and_kept_outside(self):
        body = DrapeTests.plane(0.0, half=0.5, n=11)
        bn = np.tile([0, 0, 1.0], (len(body[0]), 1))
        sky, st = DrapeTests.plane(0.02, half=0.3, n=7)
        noisy = sky.copy()
        noisy[24, 2] += 0.02                                   # one vertex pushed up 2 cm by some step
        out = G.final_relax(sky, noisy, st, body[0], body[1], bn, np.ones(len(sky), bool))
        self.assertLess(out[24, 2] - 0.02, 0.01)               # the spike is spread out
        self.assertTrue((out[:, 2] >= G.GAP - 1e-6).all())     # still outside the body


class KeepHiddenTests(unittest.TestCase):
    def test_hidden_panel_put_back_inside(self):
        body = DrapeTests.plane(0.0, half=0.5, n=11)
        bn = np.tile([0, 0, 1.0], (len(body[0]), 1))
        pts = np.array([[0, 0, 0.004], [0.1, 0, 0.004], [0.2, 0, -0.05]])
        out, n = G.keep_hidden(pts, np.array([-0.01, 0.002, -0.08]), body[0], body[1], bn)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(out[0, 2], -0.01, places=4)      # back to its Skyrim depth
        self.assertAlmostEqual(out[1, 2], 0.004)                 # visible in Skyrim: untouched
        self.assertAlmostEqual(out[2, 2], -0.05)                 # already deep enough: untouched


class MorphTests(unittest.TestCase):
    def test_morph_path(self):
        self.assertEqual(G.morph_path("S2S\\Ralof_outfit.nif", "StormCloak"),
                         "meshes/morphs/s2s/ralof_outfit/chargen/stormcloak/morph.dat")
        self.assertEqual(G.morph_path("meshes/clothes/naked/naked_m.nif", "Naked_M_Swimsuit:0"),
                         "meshes/morphs/clothes/naked/naked_m/chargen/naked_m_swimsuit/morph.dat")

    def test_morph_deltas_follow_the_body(self):
        from fo4sf import sfmorph
        body = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        m = sfmorph.parse(sfmorph.build(3, ["Overweight", "Thin"],
                                        {"Overweight": {0: (0.05, 0, 0), 1: (0.05, 0, 0), 2: (0.05, 0, 0)},
                                         "Thin": {1: (0, 0.02, 0)}}))
        d, extra = G.morph_deltas(np.array([[0.01, 0, 0], [0.99, 0.0, 0.0]]), body, m, k=1)
        self.assertAlmostEqual(d["Overweight"][0][0], 0.05, places=3)
        self.assertNotIn(0, d["Thin"])
        self.assertAlmostEqual(d["Thin"][1][1], 0.02, places=3)
        self.assertEqual(extra["Thin"][1], (0, 0, 0))


class EnvelopeTests(unittest.TestCase):
    def test_box_fit_and_region(self):
        src = np.array([[0, 0, 0], [0.1, 0.25, 0.08]], float)
        dst = np.array([[0.01, -0.02, -0.01], [0.11, 0.28, 0.07]], float)
        m = G.box_fit(src, dst)
        out = src @ m[:3, :3].T + m[:3, 3]
        self.assertTrue(np.allclose(out, dst, atol=1e-9))
        big = G.box_fit(src, src * 3)                               # clamped
        self.assertAlmostEqual(big[0, 0], G.ENVELOPE_SCALE[1])
        pts = np.arange(9, dtype=float).reshape(3, 3)
        r = G.region(pts, ["A", "B"], [[(0, 1.0)], [(0, 0.4), (1, 0.6)], [(1, 1.0)]], {"A"})
        self.assertEqual(len(r), 1)

    def test_feet_reported_in_fit(self):
        bones = [FT, TOE]
        joints = {b: at(SKY[b]) for b in (PELV, SPN0, SPN1, SPN2, NECK, HEAD, THG, CLF, FT, TOE)}
        rng = np.random.default_rng(3)
        foot = rng.uniform([0.05, -0.05, 0.0], [0.15, 0.2, 0.08], size=(40, 3))
        body = G.SkyShape(b"Body", foot, np.tile([0, 0, 1.0], (40, 1)), [(0, 0)] * 40, [(0, 1, 2)], bones,
                          [[(0, 1.0)]] * 40, joints)
        world = {f: at(SKY[s_]) for s_, f in ((PELV, "C_Hips"), (SPN0, "C_Spine"), (SPN1, "C_Spine1"),
                                              (SPN2, "C_Chest"), (NECK, "C_Neck"), (HEAD, "C_Head"),
                                              (THG, "L_Thigh"), (CLF, "L_Calf"), (FT, "L_Foot"), (TOE, "L_Toe"))}
        sf_foot = foot * [1.0, 1.2, 1.0]                            # Starfield's foot 20 % longer
        res = G.fit([], [body], world, sf_foot, np.array([[0, 1, 2]]), sf_body_weights=[[("L_Foot", 1.0)]] * 40,
                    size_feet=True)
        self.assertAlmostEqual(res.report["feet"]["L"]["scale"][1], 1.2, places=1)


class NearWeightTests(unittest.TestCase):
    def test_body_weights_near(self):
        body = np.array([[0, 0, 0], [1, 0, 0]], float)
        nrm = np.array([[0, 0, 1.0], [0, 0, 1.0]])
        bw = [[("L_Foot", 1.0)], [("L_Calf", 1.0)]]
        pts = np.array([[0, 0, 0.01], [0, 0, 0.0375], [1, 0, 0.2]])
        own = [[("L_Calf", 1.0)]] * 3
        out, n = G.body_weights_near(pts, own, body, nrm, bw, {"L_Foot", "L_Calf"})
        self.assertEqual(out[0], [("L_Foot", 1.0)])                   # on the body: the body's weights
        self.assertAlmostEqual(dict(out[1])["L_Foot"], 0.5)          # half way: blended
        self.assertEqual(out[2], [("L_Calf", 1.0)])                   # far: its own
        self.assertEqual(n, 2)


class WeldTests(unittest.TestCase):
    def test_weld_seam_copies(self):
        orig = np.array([[0, 0, 0], [0, 0, 0], [1, 0, 0]], float)
        moved = np.array([[0, 0, 0.01], [0, 0, 0.03], [1, 0, 0.5]], float)
        out, n = G.weld(orig, moved)
        self.assertEqual(n, 2)
        self.assertTrue(np.allclose(out[0], [0, 0, 0.02]) and np.allclose(out[1], [0, 0, 0.02]))
        self.assertTrue(np.allclose(out[2], moved[2]))


class NeckAndFoldTests(unittest.TestCase):
    def test_neck_squash(self):
        params = (0.5, 1.4, np.array([0.0, 0.0]))
        pts = np.array([[0.0, 0.0, 1.6], [0.3, 0.0, 1.6], [0.0, 0.0, 1.3]])
        out = G.neck_squash(pts, params)
        self.assertAlmostEqual(out[0, 2], 1.5)                    # on the neck: halved above the clavicles
        self.assertAlmostEqual(out[1, 2], 1.6)                    # out at the shoulder: untouched
        self.assertAlmostEqual(out[2, 2], 1.3)                    # below the clavicles: untouched
        joints = {"NPC L Clavicle [LClv]": np.eye(4), "NPC Head [Head]": np.eye(4)}
        joints["NPC Head [Head]"][2, 3] = 0.4
        world = {"L_Clavicle": np.eye(4), "C_Head": np.eye(4), "C_Neck": np.eye(4)}
        world["C_Head"][2, 3] = 0.3
        r, base, _axis = G.neck_squash_params(joints, {"NPC Spine2 [Spn2]": np.eye(4)}, world)
        self.assertAlmostEqual(r, 0.75)

    def test_smooth_moves(self):
        base = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], float)
        pts = base.copy()
        pts[0, 2] = 0.04                                          # one vertex pushed alone
        out = G.smooth_moves(base, pts, [(0, 1, 2), (1, 3, 2)], rounds=1)
        self.assertLess(out[0, 2], 0.04)
        self.assertGreater(out[3, 2], -1e-12)
        self.assertAlmostEqual(out[:, 2].sum(), 0.04 / 3 + 0.04 / 4 * 2, places=6)


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
