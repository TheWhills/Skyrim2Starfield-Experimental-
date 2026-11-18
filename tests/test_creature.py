"""fo4sf.creature on synthetic data: the Skyrim root folded into COM (world poses kept, metres), clips on the rig,
mesh bone names, weight quantizing, the skinned files and the skeleton shell patch."""
import os
import struct
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import creature as C, nif, retarget  # noqa: E402

U = retarget.SKYRIM_M_PER_UNIT
S = np.sqrt(0.5)


def sky():
    # NPC Root turned 90 deg about z and lifted; Pelvis 10 units up; Spine; Head (case differs from the mesh)
    names = ["NPC Root [Root]", "Pelvis", "Spine", "Head"]
    t = [(0, 0, 5), (0, 0, 10), (0, 3, 1), (0, 4, 0)]
    q = [(0, 0, S, S), (0, 0, 0, 1), (S, 0, 0, S), (0, 0, 0, 1)]
    return retarget.Rig(names, [-1, 0, 1, 2], t, q)


class RigTests(unittest.TestCase):
    def test_fold_keeps_world_rest(self):
        sk = sky()
        cr = C.creature_rig(sk, level_com=False)
        self.assertEqual(cr.names, ["Root", "COM", "Spine", "Head"])
        self.assertEqual(cr.parents, [-1, 0, 1, 2])
        wt_sk, wq_sk = sk.rest_world()
        wt, wq = cr.rig().rest_world()
        np.testing.assert_allclose(wt[1:], wt_sk[1:] * U, atol=1e-9)
        np.testing.assert_allclose(np.abs(np.sum(wq[1:] * wq_sk[1:], axis=1)), 1.0, atol=1e-9)
        np.testing.assert_allclose(cr.t[0], 0, atol=1e-12)
        np.testing.assert_allclose(cr.q[0], (0, 0, 0, 1), atol=1e-12)

    def test_level_com(self):
        # Pelvis pitched -56 deg about x, as the chicken's: COM rests unrotated, the world pose stays
        sk = retarget.Rig(["NPC Root [Root]", "Pelvis", "Spine", "LeftThigh"], [-1, 0, 1, 1],
                          [(0, 0, 0), (0, -5, 20), (0, 3, 1), (2, 0, -1)],
                          [tuple(np.array(v) / np.linalg.norm(v)) for v in
                           ((0, 0, 0, 1), (-0.469, 0, 0, 0.883), (0.1, 0, 0, 0.995), (0, 0.2, 0, 0.98))])
        cr = C.creature_rig(sk)
        np.testing.assert_allclose(cr.q[cr.com_index], (0, 0, 0, 1), atol=1e-9)
        wt_sk, wq_sk = sk.rest_world()
        wt, wq = cr.rig().rest_world()
        np.testing.assert_allclose(wt[1:], wt_sk[1:] * U, atol=1e-9)
        np.testing.assert_allclose(np.abs(np.sum(wq[2:] * wq_sk[2:], axis=1)), 1.0, atol=1e-6)
        F = 2
        clip = {"frames": F, "bones": ["Pelvis", "Spine"],
                "tracks": [[((0, -5, 20 + f), tuple(np.array((-0.469, 0, 0.05 * f, 0.883))
                                                     / np.linalg.norm((-0.469, 0, 0.05 * f, 0.883))), (1,))
                            for f in range(F)],
                           [((0, 3, 1), tuple(np.array((0.1 * f, 0, 0, 1)) / np.linalg.norm((0.1 * f, 0, 0, 1))),
                             (1,)) for f in range(F)]]}
        lt, lq = C.clip_locals(clip, sk, cr)
        slt, slq = retarget.skyrim_locals(clip, sk)
        wts, wqs = sk.fk(slt, slq)
        wtc, wqc = cr.rig().fk(lt, lq)
        np.testing.assert_allclose(wtc[:, 1:], wts[:, 1:] * U, atol=1e-6)
        nq = lambda q: q / np.linalg.norm(q, axis=-1, keepdims=True)
        np.testing.assert_allclose(np.abs(np.sum(nq(wqc[:, 2:]) * nq(wqs[:, 2:]), axis=-1)), 1.0, atol=1e-6)

    def test_clip_on_the_rig(self):
        sk = sky()
        cr = C.creature_rig(sk)
        F = 3
        clip = {"frames": F, "bones": ["NPC Root [Root]", "Spine"],
                "tracks": [[((0, f, 5), (0, 0, S, S), (1,)) for f in range(F)],
                           [((0, 3, 1), (0, 0, np.sin(f / 4), np.cos(f / 4)), (1,)) for f in range(F)]]}
        lt, lq = C.clip_locals(clip, sk, cr)
        self.assertEqual(lt.shape, (F, 4, 3))
        slt, slq = retarget.skyrim_locals(clip, sk)
        wt_sk, _ = sk.fk(slt, slq)
        wt, _ = cr.rig().fk(lt, lq)
        np.testing.assert_allclose(wt[:, 1:], wt_sk[:, 1:] * U, atol=1e-9)     # the root's motion rides on COM

    def test_bone_names_and_weights(self):
        m = C.bone_name_map(["Pelvis", "HEAD"], ["COM", "Spine", "Head"], "Pelvis")
        self.assertEqual(m, {"Pelvis": "COM", "HEAD": "Head"})
        with self.assertRaises(ValueError):
            C.bone_name_map(["Tail"], ["COM"], "Pelvis")
        w = C.quantize_weights([[("COM", 0.5), ("Head", 0.25), ("Spine", 0.25)], [("Head", 1.0)]],
                               {"COM": 0, "Spine": 1, "Head": 2})
        self.assertEqual(len(w), 8)
        self.assertEqual(sum(x for _b, x in w[:4]), 65535)
        self.assertEqual(w[4], (2, 65535))


class FileTests(unittest.TestCase):
    def test_quat_to_rot9(self):
        r = C.quat_to_rot9((0, 0, S, S))                                  # 90 deg about z: x -> y
        np.testing.assert_allclose(np.array(r).reshape(3, 3) @ (1, 0, 0), (0, 1, 0), atol=1e-9)
        np.testing.assert_allclose(retarget.mat_to_quat(r), (0, 0, S, S), atol=1e-9)

    def test_skinned_files(self):
        from fo4sf import gearfit
        eye = np.eye(4)
        up = np.eye(4)
        up[2, 3] = 0.2
        sh = gearfit.SkyShape(b"chicken", np.array([[0, 0, 0.1], [0.1, 0, 0.1], [0, 0.1, 0.3]], float),
                              np.array([[0, 0, 1]] * 3, float), [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)],
                              ["Pelvis", "HEAD"], [[(0, 1.0)], [(0, 0.5), (1, 0.5)], [(1, 1.0)]],
                              {"Pelvis": eye, "HEAD": up})
        U = retarget.SKYRIM_M_PER_UNIT
        cr = C.creature_rig(retarget.Rig(["NPC Root [Root]", "Pelvis", "Head"], [-1, 0, 1],
                                         [(0, 0, 0), (0, 0, 0), (0, 0, 0.2 / U)], [(0, 0, 0, 1)] * 3))
        files = C.skinned_files(sh, "materials\\s2s\\chicken.mat", "actors/s2schicken/chicken", "Pelvis", cr,
                                tangents=[(1, 0, 0)] * 3)
        self.assertIn("meshes/actors/s2schicken/chicken.nif", files)
        n = nif.parse(files["meshes/actors/s2schicken/chicken.nif"])
        names = [C._node_name(n, i) for i in range(len(n.blocks)) if n.type_of(i) == "NiNode"]
        self.assertEqual(names, [b"ExportScene", b"COM_Twin", b"Head"])
        att = next(n.blocks[i] for i in range(len(n.blocks)) if n.type_of(i) == "SkinAttach")
        self.assertEqual(att[4:], struct.pack("<I", 2) + b"\0" * 8)          # two empty names, as vanilla
        inst = next(n.blocks[i] for i in range(len(n.blocks)) if n.type_of(i) == "BSSkin::Instance")
        root, _d, cnt = struct.unpack_from("<iiI", inst, 0)
        refs = struct.unpack_from(f"<{cnt}i", inst, 12)
        self.assertEqual((root, [C._node_name(n, r) for r in refs]), (0, [b"COM_Twin", b"Head"]))
        head = next(i for i in range(len(n.blocks)) if n.type_of(i) == "NiNode" and C._node_name(n, i) == b"Head")
        self.assertIn(head, nif.node_children(n, next(i for i in range(len(n.blocks))
                                                      if C._node_name(n, i) == b"COM_Twin")))
        self.assertAlmostEqual(struct.unpack_from("<3f", n.blocks[head], 8 + 4 + 8)[2], 0.2, places=6)
        from fo4sf import sfmesh
        mesh = sfmesh.parse(next(v for k, v in files.items() if k.endswith(".mesh")))
        self.assertEqual(len(mesh.tangents), 3)
        bd = next(n.blocks[i] for i in range(len(n.blocks)) if n.type_of(i) == "BSSkin::BoneData")
        # Head's bind is the inverse of its bind world: translation z -0.2
        head_t = struct.unpack_from("<3f", bd, 4 + 68 + 16 + 36)
        self.assertAlmostEqual(head_t[2], -0.2, places=6)

    def test_body_with_ragdoll(self):
        from fo4sf import gearfit
        eye = np.eye(4)
        sh = gearfit.SkyShape(b"chicken", np.array([[0, 0, 0.1], [0.1, 0, 0.1], [0, 0.1, 0.3]], float),
                              np.array([[0, 0, 1]] * 3, float), [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)],
                              ["Pelvis"], [[(0, 1.0)]] * 3, {"Pelvis": eye})
        U = retarget.SKYRIM_M_PER_UNIT
        cr = C.creature_rig(retarget.Rig(["NPC Root [Root]", "Pelvis", "Head"], [-1, 0, 1],
                                         [(0, 0, 0), (0, 0, 0), (0, 0, 0.2 / U)], [(0, 0, 0, 1)] * 3))
        files = C.skinned_files(sh, "materials\\x.mat", "actors/x/x", "Pelvis", cr, ragdoll=(b"TAGBLOB", ["COM", "Head"]))
        n = nif.parse(files["meshes/actors/x/x.nif"])
        sys_i = next(i for i in range(len(n.blocks)) if n.type_of(i) == "bhkRagdollSystem")
        self.assertEqual(n.blocks[sys_i], struct.pack("<I", 7) + b"TAGBLOB")
        objs = [i for i in range(len(n.blocks)) if n.type_of(i) == "bhkNPCollisionObject"]
        got = []
        for o in objs:
            target, flags, system, body = struct.unpack_from("<iHiI", n.blocks[o], 0)
            self.assertEqual((flags, system), (0x80, sys_i))
            ni, ne = struct.unpack_from("<iI", n.blocks[target], 0)
            coll, = struct.unpack_from("<i", n.blocks[target], 8 + 4 * ne + 4 + 4 + 52)
            self.assertEqual(coll, o)                                     # the node points back at its object
            got.append((C._node_name(n, target), body))
        self.assertEqual(sorted(got), [(b"COM_Twin", 0), (b"Head", 1)])
        with self.assertRaises(ValueError):
            C.skinned_files(sh, "materials\\x.mat", "actors/x/x", "Pelvis", cr, ragdoll=(b"x", ["Tail"]))

    def test_body_in_com_space(self):
        from fo4sf import gearfit
        U = retarget.SKYRIM_M_PER_UNIT
        # COM 0.3 m up, its Skyrim rest turned 90 deg about z (levelled out of COM); Head 0.1 m above it
        cr = C.creature_rig(retarget.Rig(["NPC Root [Root]", "Pelvis", "Head"], [-1, 0, 1],
                                         [(0, 0, 0), (0, 0, 0.3 / U), (0, 0, 0.1 / U)],
                                         [(0, 0, 0, 1), (0, 0, S, S), (0, 0, 0, 1)]))
        com = C.com_world(cr)
        np.testing.assert_allclose(com[:3, :3], np.eye(3), atol=1e-9)              # COM level
        np.testing.assert_allclose(com[:3, 3], (0, 0, 0.3), atol=1e-9)
        pel = np.eye(4)
        pel[:3, :3] = np.array(C.quat_to_rot9((0, 0, S, S))).reshape(3, 3)
        pel[2, 3] = 0.3
        head = pel @ np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0.1], [0, 0, 0, 1]])
        p = np.array([[0.1, 0, 0.3], [0, 0, 0.45], [0, 0.1, 0.3]])     # actor model space
        sh = gearfit.SkyShape(b"c", p, np.array([[1, 0, 0]] * 3, float), [(0, 0)] * 3, [(0, 1, 2)],
                              ["Pelvis", "Head"], [[(0, 1.0)], [(1, 1.0)], [(0, 1.0)]], {"Pelvis": pel, "Head": head})
        moved, tan = C.to_com_space(sh, cr, [(1, 0, 0)] * 3)
        np.testing.assert_allclose(moved.points[0], (0.1, 0, 0), atol=1e-9)       # only lowered by COM's height
        np.testing.assert_allclose(moved.normals[0], (1, 0, 0), atol=1e-9)
        files = C.skinned_files(sh, "materials\\x.mat", "actors/x/x", "Pelvis", cr)
        n = nif.parse(files["meshes/actors/x/x.nif"])
        from fo4sf import sfnif
        g = sfnif.parse_bsgeometry(next(n.blocks[i] for i in range(len(n.blocks)) if n.type_of(i) == "BSGeometry"))
        self.assertEqual(len([m for m in g.meshes if m is not None]), 4)          # LOD0-3 filled, as vanilla
        self.assertEqual(len({m.path for m in g.meshes}), 1)
        one = nif.parse(C.skinned_files(sh, "materials\\x.mat", "actors/x/x", "Pelvis", cr, lods=1)["meshes/actors/x/x.nif"])
        g1 = sfnif.parse_bsgeometry(next(one.blocks[i] for i in range(len(one.blocks)) if one.type_of(i) == "BSGeometry"))
        self.assertEqual([m is not None for m in g1.meshes], [True, False, False, False])
        names = [C._node_name(n, i) for i in range(len(n.blocks)) if n.type_of(i) == "NiNode"]
        self.assertEqual(names, [b"ExportScene", b"COM_Twin", b"Head"])            # no Root node in the body
        twin = next(i for i in range(len(n.blocks)) if C._node_name(n, i) == b"COM_Twin")
        np.testing.assert_allclose(struct.unpack_from("<3f", n.blocks[twin], 8 + 4 + 8), (0, 0, 0), atol=1e-9)
        e = struct.unpack_from("<i", n.blocks[twin], 8)[0]
        self.assertEqual((C._node_name(n, e), n.strings[struct.unpack_from("<i", n.blocks[e], 4)[0]]),
                         (b"ParentBoneName", b"COM"))
        bsx = next(n.blocks[i] for i in range(len(n.blocks)) if n.type_of(i) == "BSXFlags")
        self.assertEqual(struct.unpack_from("<I", bsx, 4)[0], 0x1004A)
        # at rest every bone's model world cancels its bind: COM (the pitched Pelvis, levelled) included
        bd = next(n.blocks[i] for i in range(len(n.blocks)) if n.type_of(i) == "BSSkin::BoneData")
        inst = next(n.blocks[i] for i in range(len(n.blocks)) if n.type_of(i) == "BSSkin::Instance")
        cnt = struct.unpack_from("<I", inst, 8)[0]
        refs = struct.unpack_from(f"<{cnt}i", inst, 12)

        def node_world(i):
            m = np.eye(4)
            b = n.blocks[i]
            m[:3, 3] = struct.unpack_from("<3f", b, 20)
            m[:3, :3] = np.array(struct.unpack_from("<9f", b, 32)).reshape(3, 3)
            par = next((p for p in range(len(n.blocks)) if n.type_of(p) == "NiNode" and i in nif.node_children(n, p)), None)
            return (node_world(par) if par is not None else np.eye(4)) @ m
        for k, r in enumerate(refs):
            rot = np.array(struct.unpack_from("<9f", bd, 4 + k * 68 + 16)).reshape(3, 3)
            tr = np.array(struct.unpack_from("<3f", bd, 4 + k * 68 + 52))
            bind = np.eye(4)
            bind[:3, :3], bind[:3, 3] = rot, tr
            np.testing.assert_allclose(node_world(r) @ bind, np.eye(4), atol=1e-5,
                                       err_msg=C._node_name(n, r).decode())

    def test_with_back_faces(self):
        from fo4sf import gearfit
        sh = gearfit.SkyShape(b"c", np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float), np.array([[0, 0, 1]] * 3, float),
                              [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)], ["Pelvis"], [[(0, 1.0)]] * 3, {"Pelvis": np.eye(4)})
        d, tan = C.with_back_faces(sh, [(1, 0, 0)] * 3)
        self.assertEqual(len(d.points), 6)
        self.assertEqual(d.triangles, [(0, 1, 2), (3, 5, 4)])               # the copy wound the other way
        np.testing.assert_allclose(d.normals[3], (0, 0, -1))
        self.assertEqual((len(d.uvs), len(d.weights), len(tan)), (6, 6, 6))

    def test_set_rig_fields(self):
        # three records shaped like CALUMI's: 12 x 0xFF, then mirror -1 / level 0, weight 0.0 at +40
        n = 3
        data = bytearray(C.RIG_RECORDS + C.RIG_RECORD * n + 40)
        for k in range(n):
            r = C.RIG_RECORDS + C.RIG_RECORD * k
            data[r + 12:r + 24] = b"\xff" * 12
            struct.pack_into("<ii", data, r + C.RIG_MIRROR, -1, 0)
        out = C.set_rig_fields(bytes(data), [0, 2, 1], [5, 4, 2], [1.0, 1.0, 5.0])
        got = [struct.unpack_from("<ii", out, C.RIG_RECORDS + C.RIG_RECORD * k + C.RIG_MIRROR)
               + struct.unpack_from("<f", out, C.RIG_RECORDS + C.RIG_RECORD * k + C.RIG_WEIGHT) for k in range(n)]
        self.assertEqual(got, [(0, 5, 1.0), (2, 4, 1.0), (1, 2, 5.0)])
        self.assertEqual(len(out), len(data))
        with self.assertRaises(ValueError):                 # a layout it does not know is left alone
            C.set_rig_fields(bytes(len(data)), [0, 1, 2], [5, 4, 2], [1.0] * 3)

    def test_rig_fields_vanilla_critter(self):
        # the vanilla critter rig's bones and parents (owner's rig, 2026-11-17): Root 5, COM 4, the two spines 3
        names = ("Root COM C_spine1 C_spine2 C_Head1 R_FrontLegA1 R_FrontLegB1 L_FrontLegA1 L_FrontLegB1 R_Antenna1 "
                 "L_Antenna1 R_MiddleLegA1 R_MiddleLegB1 L_MiddleLegA1 L_MiddleLegB1 C_hips1 C_Hips2 R_BackLegC1 "
                 "L_BackLegC1 R_BackLegA1 R_BackLegB1 L_BackLegA1 L_BackLegB1 R_FrontLegA2 L_FrontLegA2 R_Antenna2 "
                 "L_Antenna2 R_BackLegC2 L_BackLegC2 R_Antenna3 L_Antenna3").split()
        parents = [-1, 0, 1, 2, 3, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 1, 15, 16, 16, 15, 15, 15, 15, 5, 7, 9, 10, 17, 18,
                   25, 26]
        cr = type("R", (), {"names": names, "parents": parents})()
        mirror, level, weight = C.rig_fields(cr)
        vanilla_mirror = [0, 1, 2, 3, 4, 7, 8, 5, 6, 10, 9, 13, 14, 11, 12, 15, 16, 18, 17, 21, 22, 19, 20, 24, 23, 26,
                          25, 28, 27, 30, 29]
        self.assertEqual(mirror, vanilla_mirror)
        vanilla_level = [5, 4, 3, 3] + [2] * 19 + [1] * 6 + [0] * 2
        self.assertEqual(level, vanilla_level)
        self.assertEqual(weight[:4], [1.0, 1.0, 2.0, 2.0])

    def test_sorted_by_level(self):
        # COM > [Spine > Head > Comb (deep chain), Leg > Foot]: Comb (level 0) is listed before the legs (2)
        rig = retarget.Rig(["Pelvis", "Spine", "Head", "Comb", "Leg", "Foot"], [-1, 0, 1, 2, 0, 4],
                           np.array([[0, 0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], [1, 0, 0], [0, 0, -1]], float),
                           np.tile([0, 0, 0, 1.0], (6, 1)))
        cr = C.creature_rig(rig, "Pelvis", level_com=False)
        s = C.sorted_by_level(cr)
        _m, lv, _w = C.rig_fields(s)
        self.assertEqual(lv, sorted(lv, reverse=True))
        self.assertTrue(all(p < i for i, p in enumerate(s.parents)))
        self.assertLess(s.names.index("Foot"), s.names.index("Comb"))
        # the same clip folds to the same per-bone locals, in the new order
        lt = np.random.default_rng(1).normal(size=(2, 6, 3))
        lq = np.tile([0, 0, 0, 1.0], (2, 6, 1))
        t0, q0 = cr.fold(lt, lq)
        t1, q1 = s.fold(lt, lq)
        for i, n in enumerate(s.names):
            np.testing.assert_allclose(t1[:, i], t0[:, cr.names.index(n)])
        with self.assertRaises(ValueError):
            cr.reordered([1, 0, 2, 3, 4, 5, 6])

    def _legs(self, r_rest_q=(0, 0, 0, 1.0)):
        # Root > COM > LeftLeg (-x), RightLeg (+x); RightLeg's rest frame may carry its own turn
        q = np.array([[0, 0, 0, 1.0], [0, 0, 0, 1.0], [0, 0, 0, 1.0], r_rest_q], float)
        return C.CreatureRig(["Root", "COM", "LeftLeg", "RightLeg"], [-1, 0, 1, 1],
                             np.array([[0, 0, 0], [0, 0, 0.3], [-0.1, 0, 0], [0.1, 0, 0]], float), q,
                             [-1, 0, 1, 2], -1, 0)

    def test_mirror_clip_rest_and_swing(self):
        from fo4sf.retarget import qinv, qrot
        down = np.array([0, 0, -0.2])
        for r_rest in ((0, 0, 0, 1.0), (0, 0, 1.0, 0)):                     # mirrored, or turned 180 about z
            cr = self._legs(r_rest)
            mirror = C.rig_fields(cr)[0]
            self.assertEqual(mirror, [0, 1, 3, 2])
            rest_t, rest_q = np.tile(cr.t, (2, 1, 1)), np.tile(cr.q, (2, 1, 1))
            t, q = C.mirror_clip(cr, rest_t, rest_q, mirror)
            np.testing.assert_allclose(t, rest_t, atol=1e-9)
            np.testing.assert_allclose(np.abs(np.sum(q * rest_q, -1)), 1, atol=1e-9)        # rest stays rest
            foot_local_r = qrot(qinv(np.array(r_rest, float)), down)       # the right foot in its leg's frame
            for axis in ((1, 0, 0), (0, 1, 0)):                            # swing forward, swing out sideways
                lq = rest_q.copy()
                ang = np.radians(30)
                lq[1, 2] = tuple(np.sin(ang / 2) * np.array(axis)) + (np.cos(ang / 2),)
                _t, q = C.mirror_clip(cr, rest_t, lq, mirror)
                left_foot = qrot(lq[1, 2], down)                            # COM rests unrotated
                right_foot = qrot(C.qmul(q[1, 1], q[1, 3]), foot_local_r)
                np.testing.assert_allclose(right_foot, left_foot * np.array([-1, 1, 1]), atol=1e-9)
                np.testing.assert_allclose(np.abs(np.sum(q[1, 2] * rest_q[1, 2])), 1, atol=1e-9)  # left leg rests

    def test_mirror_clip_root_turn(self):
        cr = self._legs()
        mirror = C.rig_fields(cr)[0]
        t, q = np.tile(cr.t, (2, 1, 1)), np.tile(cr.q, (2, 1, 1))
        h = np.sqrt(0.5)
        q[1, 0] = (0, 0, h, h)                                                         # +90 yaw (a left turn)
        t[1, 0] = (0.2, 0.1, 0)
        mt, mq = C.mirror_clip(cr, t, q, mirror)
        np.testing.assert_allclose(mq[1, 0], (0, 0, -h, h), atol=1e-9)                # a right turn
        np.testing.assert_allclose(mt[1, 0], (-0.2, 0.1, 0), atol=1e-9)

    def test_mirror_names_chicken(self):
        for a, b in (("LeftThigh", "RightThigh"), ("LAnkleToe00", "RAnkleToe00"), ("HeadWattleL", "HeadWattleR"),
                     ("L_Clavicle", "R_Clavicle"), ("Spine", "Spine"), ("HeadComb", "HeadComb"), ("COM", "COM")):
            self.assertEqual(C.mirror_name(a), b)
            self.assertEqual(C.mirror_name(b), a)

    def test_shell_skeleton(self):
        f = nif.NifFile(endian=1, user_version=12, bs_version=173, author=b"\x00", unknown_int=0,
                        export_script=b"\x00", sf_data=b"\x7a\x00")
        ident = struct.pack("<3f9ff", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0)

        def node(name, kids, t=(0, 0, 0)):
            return (struct.pack("<iIiI", f.string_index(name), 0, -1, 0xE) + struct.pack("<3f", *t) + ident[12:]
                    + struct.pack("<iI", -1, len(kids)) + struct.pack(f"<{len(kids)}i", *kids))
        f.add_block("NiNode", node(b"Critter_mrRigRoot", [1, 3]))
        f.add_block("NiNode", node(b"Root", [2]))
        f.add_block("NiNode", node(b"COM", [], (0, -0.113, 0.149)))
        f.add_block("NiNode", node(b"CharacterController", []))
        f.footer = struct.pack("<II", 1, 0)
        out = nif.parse(C.shell_skeleton(nif.serialize(f), "S2SChicken_mrRigRoot", (0, 0.01, 0.2), (0, 0, S, S)))
        np.testing.assert_allclose(struct.unpack_from("<9f", out.blocks[2], 28), C.quat_to_rot9((0, 0, S, S)),
                                   atol=1e-6)
        np.testing.assert_allclose(struct.unpack_from("<f", out.blocks[2], 64), (1.0,), atol=1e-9)   # scale kept
        self.assertEqual(C._node_name(out, 0), b"S2SChicken_mrRigRoot")
        self.assertEqual(C._node_name(out, 3), b"CharacterController")
        np.testing.assert_allclose(struct.unpack_from("<3f", out.blocks[2], 16), (0, 0.01, 0.2), atol=1e-6)
        self.assertEqual(nif.node_children(out, 0), [1, 3])


if __name__ == "__main__":
    unittest.main()
