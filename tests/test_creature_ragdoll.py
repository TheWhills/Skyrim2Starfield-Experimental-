"""fo4sf.creature_ragdoll (and hktagwrite's item alignment) on synthetic data: Skyrim ragdoll bodies and constraints
read from a NIF, moved into the rig's bone frames, constraint frames, and the hknpRagdollData edit."""
import math
import os
import struct
import sys
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import creature_ragdoll as R, hktagfile, hktagwrite, nif  # noqa: E402

HS = 69.99124


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def skyrim_ragdoll_nif() -> bytes:
    """Root > Pelvis (pitched 60 deg about x, at (0, 0, 0.3) m) > Neck0 (at (0, 0.1, 0.1) in Pelvis, unrotated
    relative to it); a capsule body on each, Neck0's constrained to Pelvis."""
    f = nif.NifFile(endian=1, user_version=12, bs_version=100, author=b"\x00", unknown_int=0,
                    export_script=b"\x00")

    def node(name, t, R3, coll, kids):
        return (struct.pack("<iIiI", f.string_index(name), 0, -1, 0xE) + struct.pack("<3f", *t)
                + struct.pack("<9f", *np.asarray(R3, float).ravel()) + struct.pack("<f", 1.0)
                + struct.pack("<iI", coll, len(kids)) + struct.pack(f"<{len(kids)}i", *kids) + struct.pack("<I", 0))
    Rp = rot_x(60)
    root = f.add_block("NiNode", b"")
    pel = f.add_block("NiNode", b"")
    neck = f.add_block("NiNode", b"")

    def capsule(r, a, b):
        return struct.pack("<If8x3ff3ff", 0, r, *a, r, *b, r)

    def body(shape, cons=()):
        rb = bytearray(248 + 4 * len(cons) + 2)
        struct.pack_into("<i", rb, 0, shape)
        rb[116:164] = struct.pack("<12f", 0.01, 0, 0, 0, 0, 0.02, 0, 0, 0, 0, 0.03, 0)
        struct.pack_into("<3f", rb, 164, 0, 0.05, 0)
        struct.pack_into("<f", rb, 180, 4.0)
        struct.pack_into("<I", rb, 244, len(cons))
        for k, c in enumerate(cons):
            struct.pack_into("<i", rb, 248 + 4 * k, c)
        return bytes(rb)
    cs0 = f.add_block("bhkCapsuleShape", capsule(0.1, (0, 0.1, 0), (0, -0.1, 0)))
    rb0 = f.add_block("bhkRigidBody", body(cs0))
    co0 = f.add_block("bhkBlendCollisionObject", struct.pack("<iHi2f", pel, 0x89, rb0, 1, 1))
    cs1 = f.add_block("bhkCapsuleShape", capsule(0.03, (0, 0, 0.02), (0, 0, 0.06)))
    con = len(f.blocks) + 2                              # the constraint comes after the body and its object
    rb1 = f.add_block("bhkRigidBody", body(cs1, [con]))
    co1 = f.add_block("bhkBlendCollisionObject", struct.pack("<iHi2f", neck, 0x89, rb1, 1, 1))
    vecs = [(0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 0),           # A: twist z, plane x, pivot 0
            (0, 1, 0, 0), (1, 0, 0, 0), (0, 0, -1, 0), (0, 0.1, 0.1, 0)]      # B (Pelvis): twist y, pivot
    f.add_block("bhkRagdollConstraint", struct.pack("<I2iI", 2, rb1, rb0, 1)
                + b"".join(struct.pack("<4f", *v) for v in vecs) + struct.pack("<6f", 0.4, -0.3, 0.3, -0.7, 0.7, 10)
                + b"\x00")
    f.blocks[root] = node(b"Skeleton.nif", (0, 0, 0), np.eye(3), -1, [pel])
    f.blocks[pel] = node(b"Pelvis", (0, 0, 0.3 * HS), Rp, co0, [neck])
    f.blocks[neck] = node(b"Neck0", (0, 0.1 * HS, 0.1 * HS), np.eye(3), co1, [])
    f.footer = struct.pack("<II", 1, 0)
    return nif.serialize(f)


class RagdollTests(unittest.TestCase):
    def test_skyrim_bodies(self):
        bodies = R.skyrim_bodies(skyrim_ragdoll_nif())
        self.assertEqual([b["node"] for b in bodies], ["Pelvis", "Neck0"])
        self.assertEqual([b["parent"] for b in bodies], [-1, 0])
        self.assertAlmostEqual(bodies[0]["radius"], 0.1, 6)
        self.assertAlmostEqual(bodies[1]["mass"], 4.0, 6)
        np.testing.assert_allclose(bodies[0]["world_t"], (0, 0, 0.3), atol=1e-6)
        k = bodies[1]["constraint"]
        np.testing.assert_allclose(k["pivot_b"], (0, 0.1, 0.1), atol=1e-6)
        self.assertAlmostEqual(k["twist_max"], 0.7, 6)
        self.assertIsNone(bodies[0]["constraint"])

    def test_to_rig_frames_levelled_com(self):
        bodies = R.skyrim_bodies(skyrim_ragdoll_nif())
        Rp = np.asarray(bodies[0]["world_R"])
        com = np.eye(4)
        com[:3, 3] = (0, 0, 0.3)                                  # our COM: same place, levelled (no pitch)
        neck = np.eye(4)
        neck[:3, :3] = Rp
        neck[:3, 3] = bodies[1]["world_t"]
        out = R.to_rig_frames(bodies, {"COM": com, "Neck0": neck}, {"Pelvis": "COM", "Neck0": "Neck0"})
        self.assertEqual([b["bone"] for b in out], ["COM", "Neck0"])
        np.testing.assert_allclose(out[0]["a"], Rp @ np.array([0, 0.1, 0]), atol=1e-6)   # pelvis pitch moved in
        np.testing.assert_allclose(out[1]["a"], (0, 0, 0.02), atol=1e-6)                  # same frame: unchanged
        k = out[1]["constraint"]
        np.testing.assert_allclose(k["twist_b"], Rp @ np.array([0, 1, 0]), atol=1e-6)    # B in the parent's frame
        np.testing.assert_allclose(k["pivot_b"], Rp @ np.array([0, 0.1, 0.1]), atol=1e-6)
        np.testing.assert_allclose(k["twist_a"], (0, 0, 1), atol=1e-6)
        with self.assertRaises(ValueError):
            R.to_rig_frames(bodies, {"COM": com}, {"Pelvis": "COM"})

    def test_transform_columns(self):
        m = R._transform((0, 0, 2), (1, 0, 0.1), (1, 2, 3))
        c0, c1, c2, t = (np.array(m[k:k + 3]) for k in (0, 4, 8, 12))
        np.testing.assert_allclose(c0, (0, 0, 1))
        self.assertAlmostEqual(float(np.dot(c0, c1)), 0, 9)
        np.testing.assert_allclose(c2, np.cross(c0, c1))
        np.testing.assert_allclose(t, (1, 2, 3))

    def test_build_ragdoll_edits_template(self):
        cap = {"shape": {"$class": "hknpCapsuleShape", "convexRadius": 0.0, "hull": {"vertices": []}},
               "collisionFilterInfo": 8200, "materialId": 3, "motionPropertiesId": 3, "qualityId": 255, "flags": 138,
               "mass": 2.0, "position": [0.0] * 4, "orientation": [0, 0, 0, 1.0],
               "massDistribution": {"massDistribution": {"centerOfMassAndVolume": [0] * 4,
                                                         "majorAxisSpace": [0, 0, 0, 1], "inertiaTensor": [0] * 4}}}
        root_body = dict(cap, shape={"$class": "hknpSphereShape"}, collisionFilterInfo=520, materialId=0,
                         motionPropertiesId=0)
        atoms = {"transforms": {}, "twistLimit": {}, "coneLimit": {}, "planesLimit": {}, "angFriction": {}}
        tpl = {"$class": "hknpRagdollData", "bodyCinfos": [root_body, cap],
               "constraintCinfos": [{"constraintData": {"atoms": atoms}}],
               "skeleton": {"bones": [{"lockTranslation": False}, {"lockTranslation": True}],
                            "referencePose": [{"scale": [1, 1, 1, 1]}, {"scale": [1, 1, 1, 0]}], "parentIndices": []},
               "boneToBodyMap": []}
        bodies = R.skyrim_bodies(skyrim_ragdoll_nif())
        com = np.eye(4)
        com[:3, 3] = (0, 0, 0.3)
        neck = np.eye(4)
        neck[:3, :3] = bodies[0]["world_R"]
        neck[:3, 3] = bodies[1]["world_t"]
        rb = R.to_rig_frames(bodies, {"COM": com, "Neck0": neck}, {"Pelvis": "COM", "Neck0": "Neck0"})
        got = {}
        with mock.patch.object(hktagfile, "Tagfile", lambda _b: type("T", (), {"item_value": lambda s, k: tpl})()), \
                mock.patch.object(R, "rewrite", lambda _b, root: got.setdefault("root", root) and b"blob"):
            self.assertEqual(R.build_ragdoll(b"template", rb), b"blob")
        root = got["root"]
        self.assertEqual(len(root["bodyCinfos"]), 2)
        b0, b1 = root["bodyCinfos"]
        self.assertEqual((b0["collisionFilterInfo"], b0["materialId"]), (520, 0))     # root body: the root's ids
        self.assertEqual(b0["shape"]["$class"], "hknpCapsuleShape")
        self.assertAlmostEqual(b1["shape"]["convexRadius"], 0.03, 6)
        self.assertEqual(len(b1["shape"]["hull"]["vertices"]), 2)
        self.assertAlmostEqual(b1["mass"], 4.0, 6)
        self.assertEqual(sorted(round(v, 4) for v in b1["massDistribution"]["massDistribution"]["inertiaTensor"][:3]),
                         [0.01, 0.02, 0.03])
        c = root["constraintCinfos"]
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["bodyA"]["serialAndIndex"], c[0]["bodyB"]["serialAndIndex"]), (1, 0))
        at = c[0]["constraintData"]["atoms"]
        self.assertAlmostEqual(at["planesLimit"]["minAngle"], math.pi / 2 - 0.3, 6)
        self.assertAlmostEqual(at["planesLimit"]["maxAngle"], math.pi / 2 + 0.3, 6)
        self.assertAlmostEqual(at["coneLimit"]["maxAngle"], 0.4, 6)
        self.assertAlmostEqual(at["twistLimit"]["minAngle"], -0.7, 6)
        self.assertEqual(root["skeleton"]["parentIndices"], [-1, 0])
        self.assertEqual(root["boneToBodyMap"], [0, 1])
        self.assertEqual([b["lockTranslation"] for b in root["skeleton"]["bones"]], [False, True])


class WriterAlignTests(unittest.TestCase):
    def test_array_align(self):
        from test_sfcloth import TagBuilder
        b = TagBuilder()
        f32 = b.type("float", 0x174605, 4)
        u32 = b.type("unsigned int", 0x8004, 4)
        f3 = b.type("hkFloat3", 0x7, 12, align=4, fields=[("x", f32, 0), ("y", f32, 4), ("z", f32, 8)])
        arr = b.type("hkArray", 0x8, 16, sub=f3, params=[("tT", f3)])
        rt = b.type("Holder", 0x7, 20, align=4, fields=[("pad", u32, 0), ("verts", arr, 4)])
        b.item(rt, bytes(20), single=True)
        template = b.build()
        val = {"pad": 7, "verts": [{"x": 1.0, "y": 2.0, "z": 3.0}, {"x": 4.0, "y": 5.0, "z": 6.0}]}
        for aa, oa in ((1, 1), (16, 8)):
            out = hktagwrite.Writer(template, aa, oa).write(val, "Holder")
            tf = hktagfile.Tagfile(out)
            arrays = [it.offset for it in tf.items[1:] if it.flags & 0x20]
            if aa == 16:
                self.assertTrue(arrays and all(o % 16 == 0 for o in arrays), arrays)
            else:
                self.assertTrue(any(o % 16 for o in arrays), arrays)        # the cloth default packs tighter
            back = tf.item_value(1)
            self.assertEqual(back["pad"], 7)
            self.assertEqual([v["z"] for v in back["verts"]], [3.0, 6.0])


if __name__ == "__main__":
    unittest.main()
