import struct
import base64
import unittest
from test_review_fixes import av_fields, trishape_block
from fo4sf import door_motion, nif


def fixture():
    f = nif.NifFile(bs_version=130)
    root, a, b, op = [f.string_index(s) for s in (b"Root", b"LeafA", b"LeafB", b"Open")]
    identity = (1, 0, 0, 0, 1, 0, 0, 0, 1)
    f.add_block("NiNode", av_fields(root, (70, 0, 0), identity, 1) + struct.pack("<Iii", 2, 1, 2))
    f.add_block("NiNode", av_fields(a, (0, 0, 0), identity, 1) + struct.pack("<Ii", 1, 3))
    f.add_block("NiNode", av_fields(b, (140, 0, 0), identity, 1) + struct.pack("<Ii", 1, 4))
    for _ in range(2):
        f.add_block("BSTriShape", trishape_block([(0, 0, 0), (70, 0, 0), (0, 70, 0)], [(0, 1, 2)]))
    targets = b"".join(struct.pack("<iiBiiiii", -1, -1, 0, name, -1, -1, -1, -1) for name in (a, b))
    timing = struct.pack("<fiIfffiiH", 1, -1, 2, 1, 0, 1, -1, root, 0)
    f.add_block("NiControllerSequence", struct.pack("<iII", op, 2, 0) + targets + timing)
    f.footer = struct.pack("<II", 1, 0)
    return f


class DoorMotionTests(unittest.TestCase):
    def test_sequence_timing_and_events_preserved(self):
        f = fixture()
        seq = 5
        event_name = f.string_index(b"Sound: DoorOpen")
        event = f.add_block("NiTextKeyExtraData", struct.pack("<iIfi", -1, 1, .25, event_name))
        data = bytearray(f.blocks[seq])
        struct.pack_into("<fiIfffiiH", data, 12 + 29 * 2, .5, event, 2, 2, .1, .9, -1, 0, 0)
        f.blocks[seq] = bytes(data)
        timing = door_motion.inspect(f)["sequences"][0]["timing"]
        self.assertEqual(timing["frequency"], 2)
        self.assertAlmostEqual(timing["stop"], .9)
        self.assertEqual(timing["text_events"], [{"time": .25, "text": "Sound: DoorOpen"}])

    def test_bind_values_and_source_keys_preserved(self):
        f = fixture()
        keys = struct.pack("<II5fII", 1, 1, 0, 1, 0, 0, 0, 0, 0)
        data = f.add_block("NiTransformData", keys)
        interp = f.add_block("NiTransformInterpolator", struct.pack("<8fi", 1, 2, 3, 1, 0, 0, 0, 2, data))
        result = door_motion.transform_track(f, interp)
        self.assertEqual(result["translation"], [1, 2, 3])
        self.assertEqual(result["quaternion_wxyz"], [1, 0, 0, 0])
        self.assertEqual(result["scale"], 2)
        self.assertEqual(base64.b64decode(result["source_keys"]["data"]), keys)
        with self.assertRaises(nif.NifError):
            door_motion.transform_track(f, 999)

    def test_independent_leaf_and_world_pivots_preserved(self):
        report = door_motion.inspect(fixture())
        self.assertEqual(report["single_hinge_shape_blocks"], [3])
        self.assertEqual(report["animated_shapes_outside_single_hinge"], [4])
        self.assertTrue(report["requires_additional_motion_support"])
        self.assertEqual(report["sequences"][0]["targets"][1]["pivot_source_units"], [210, 0, 0])

    def test_truncated_target_list_rejected(self):
        f = fixture()
        f.blocks[-1] = f.blocks[-1][:-1]
        with self.assertRaises(nif.NifError):
            door_motion.inspect(f)

    def test_missing_binding_reported(self):
        f = fixture()
        struct_name = f.string_index(b"Missing")
        data = bytearray(f.blocks[-1])
        struct.pack_into("<i", data, 12 + 29 + 9, struct_name)
        f.blocks[-1] = bytes(data)
        self.assertTrue(door_motion.inspect(f)["issues"])


if __name__ == "__main__":
    unittest.main()
