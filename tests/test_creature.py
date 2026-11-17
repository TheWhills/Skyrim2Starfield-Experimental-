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
        names = [C._node_name(n, i) for i in range(len(n.blocks)) if n.type_of(i) == "NiNode"]
        self.assertEqual(names, [b"ExportScene", b"COM_Twin", b"Head"])            # no Root node in the body
        twin = next(i for i in range(len(n.blocks)) if C._node_name(n, i) == b"COM_Twin")
        np.testing.assert_allclose(struct.unpack_from("<3f", n.blocks[twin], 8 + 4 + 8), (0, 0, 0), atol=1e-9)
        e = struct.unpack_from("<i", n.blocks[twin], 8)[0]
        self.assertEqual((C._node_name(n, e), n.strings[struct.unpack_from("<i", n.blocks[e], 4)[0]]),
                         (b"ParentBoneName", b"COM"))
        bsx = next(n.blocks[i] for i in range(len(n.blocks)) if n.type_of(i) == "BSXFlags")
        self.assertEqual(struct.unpack_from("<I", bsx, 4)[0], 0x1004A)

    def test_with_back_faces(self):
        from fo4sf import gearfit
        sh = gearfit.SkyShape(b"c", np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float), np.array([[0, 0, 1]] * 3, float),
                              [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)], ["Pelvis"], [[(0, 1.0)]] * 3, {"Pelvis": np.eye(4)})
        d, tan = C.with_back_faces(sh, [(1, 0, 0)] * 3)
        self.assertEqual(len(d.points), 6)
        self.assertEqual(d.triangles, [(0, 1, 2), (3, 5, 4)])               # the copy wound the other way
        np.testing.assert_allclose(d.normals[3], (0, 0, -1))
        self.assertEqual((len(d.uvs), len(d.weights), len(tan)), (6, 6, 6))

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
