"""Stationary door bodies must stay separate from the animated leaf (synthetic NIFs)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from fo4sf import nif, sfnif


class DoorFrameCollisionTests(unittest.TestCase):
    def test_stationary_and_leaf_bodies_survive_round_trip(self):
        leaf_blob, left_blob, right_blob = b"leafbody", b"leftbody", b"rightbod"
        f = nif.parse(nif.serialize(sfnif.build_door_nif(
            b"Door", [], [], leaf_collision=leaf_blob,
            frame_collision_blobs=[left_blob, right_blob])))
        nodes = {f.strings[struct.unpack_from("<i", b)[0]]: i
                 for i, b in enumerate(f.blocks) if f.type_of(i) == "NiNode"}
        moving = nif.descendants(f, nodes[sfnif.DOOR_TEMPLATE["anim_root"]])
        fixed = nif.descendants(f, nodes[b"Frame"])
        bodies = {}
        for i, block in enumerate(f.blocks):
            if f.type_of(i) != "bhkNPCollisionObject":
                continue
            target, _, data = struct.unpack_from("<iHi", block)
            size = struct.unpack_from("<I", f.blocks[data])[0]
            bodies[f.blocks[data][4:4 + size]] = target
        self.assertEqual(set(bodies), {leaf_blob, left_blob, right_blob})
        self.assertIn(bodies[leaf_blob], moving)
        for blob in (left_blob, right_blob):
            self.assertIn(bodies[blob], fixed)
            self.assertNotIn(bodies[blob], moving)
            for actual, expected in zip(nif.world_transforms(f)(bodies[blob])[0], sfnif.DOOR_TEMPLATE["hinge_pos"]):
                self.assertAlmostEqual(actual, expected, places=6)

    def test_frame_only_collision_enables_havok(self):
        f = sfnif.build_door_nif(b"Door", [], [], frame_collision_blobs=[b"framebod"])
        flags = [struct.unpack_from("<iI", b)[1] for i, b in enumerate(f.blocks) if f.type_of(i) == "BSXFlags"]
        self.assertEqual(flags, [0x0A])
        self.assertEqual(sum(f.type_of(i) == "bhkNPCollisionObject" for i in range(len(f.blocks))), 1)

    def test_omitted_frame_collision_preserves_existing_output(self):
        self.assertEqual(nif.serialize(sfnif.build_door_nif(b"Door", [], [])),
                         nif.serialize(sfnif.build_door_nif(b"Door", [], [], frame_collision_blobs=[])))

    def test_rotated_frame_body_keeps_pivot_local_transform(self):
        rotation = (0, -1, 0, 1, 0, 0, 0, 0, 1)
        f = nif.parse(nif.serialize(sfnif.build_door_nif(
            b"Door", [], [], frame_collision_blobs=[b"framebod"],
            frame_collision_transforms=[((1, 2, 3), rotation)])))
        collision = next(b for i, b in enumerate(f.blocks) if f.type_of(i) == "bhkNPCollisionObject")
        target = struct.unpack_from("<i", collision)[0]
        translation, actual_rotation, scale = nif.world_transforms(f)(target)
        for actual, expected in zip(translation, (1 + sfnif.DOOR_TEMPLATE["hinge_pos"][0], 2 + sfnif.DOOR_TEMPLATE["hinge_pos"][1], 3)):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertEqual(actual_rotation, rotation)
        self.assertEqual(scale, 1)

    def test_invalid_transforms_are_rejected(self):
        invalid = [[], [((0, 0, 0), (1,) * 9)],
                   [((float("nan"), 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1))],
                   [((0, 0, 0), (-1, 0, 0, 0, 1, 0, 0, 0, 1))]]
        for transforms in invalid:
            with self.subTest(transforms=transforms), self.assertRaises(ValueError):
                sfnif.build_door_nif(b"Door", [], [], frame_collision_blobs=[b"framebod"], frame_collision_transforms=transforms)


if __name__ == "__main__":
    unittest.main()
