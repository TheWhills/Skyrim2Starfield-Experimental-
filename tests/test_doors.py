"""Door NIF layout (experimental rigged doors): node names, nesting and hinge position follow the vanilla template door."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import nif, sfnif  # noqa: E402


def shape(name):
    return sfnif.StaticShape(name, b"0123456789abcdef0123\\0123456789abcdef0123", 3, 3, "Materials\\x.mat",
                             (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))


def names(f):
    out = {}
    for i in range(len(f.blocks)):
        if f.type_of(i) == "NiNode":
            idx, = struct.unpack_from("<i", f.blocks[i], 0)
            out[f.strings[idx]] = i
    return out


class DoorNifTests(unittest.TestCase):
    def test_layout_matches_template(self):
        t = sfnif.DOOR_TEMPLATE
        f = nif.parse(nif.serialize(sfnif.build_door_nif(b"TestDoor", [shape(b"Frame:0")], [shape(b"Leaf:0")])))
        n = names(f)
        for want in (b"TestDoor", t["anim_root"], t["hinge"], b"REF_ATTACH_NODE", b"LookAtNode", b"Frame"):
            self.assertIn(want, n)
        self.assertEqual(nif.node_children(f, n[b"TestDoor"])[0], n[t["anim_root"]])     # animation root first, as vanilla
        self.assertIn(n[t["hinge"]], nif.node_children(f, n[t["anim_root"]]))
        tr = nif._av_transform(f.blocks[n[t["hinge"]]])[0]
        self.assertEqual([round(x, 3) for x in tr], list(t["hinge_pos"]))
        self.assertTrue(any(f.type_of(i) == "NiStringExtraData" for i in range(len(f.blocks))))   # sgoKeep tags

    def test_leaf_collision_sits_on_moving_node(self):
        f = sfnif.build_door_nif(b"D", [], [shape(b"Leaf:0")], leaf_collision=b"\x00" * 8)
        coll = [i for i in range(len(f.blocks)) if f.type_of(i) == "bhkNPCollisionObject"]
        self.assertEqual(len(coll), 1)
        target, = struct.unpack_from("<i", f.blocks[coll[0]], 0)
        self.assertIn(target, nif.descendants(f, names(f)[sfnif.DOOR_TEMPLATE["hinge"]]))


class ClosedPoseTests(unittest.TestCase):
    def test_xyz_rotation_last_key(self):
        import math
        def group(vals):                              # quadratic float keys: time, value, forward, backward
            return struct.pack("<II", len(vals), 2) + b"".join(struct.pack("<4f", t, v, 0, 0) for t, v in vals)
        d = struct.pack("<II", 1, 4) + group([(0, 0), (1, 0)]) + group([(0, 0)]) + group([(0, 0), (1, math.pi / 2)])
        r = nif._last_rotation_key(d)
        self.assertEqual([round(x, 5) for x in r], [0, -1, 0, 1, 0, 0, 0, 0, 1])   # 90 degrees about Z

    def test_quaternion_last_key(self):
        d = struct.pack("<II", 2, 1) + struct.pack("<5f", 0, 1, 0, 0, 0) + struct.pack("<5f", 1, 0, 0, 0, 1)   # 180 about Z
        self.assertEqual([round(x, 5) for x in nif._last_rotation_key(d)], [-1, 0, 0, 0, -1, 0, 0, 0, 1])


class KeyframedBodyTests(unittest.TestCase):
    def test_copies_only_listed_fields(self):
        from fo4sf import sfcollision
        blob, donor = bytes(2000), bytes(range(256)) * 8
        out = sfcollision.keyframed(blob, donor[:2000])
        for off, n in sfcollision.KEYFRAMED_FIELDS:
            self.assertEqual(out[off:off + n], donor[off:off + n])
        self.assertEqual(out[600:700], bytes(100))                  # box geometry untouched
        with self.assertRaises(ValueError):
            sfcollision.keyframed(blob, donor[:1999])


if __name__ == "__main__":
    unittest.main()
