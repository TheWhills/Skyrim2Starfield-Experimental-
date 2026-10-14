import importlib.util
import struct
from pathlib import Path
import unittest
from test_collision import fake_template
from fo4sf import nif, sfnif

spec = importlib.util.spec_from_file_location("door_oracle", Path(__file__).resolve().parents[1] / "scripts/oracles/door_bodies.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def body(motion):
    data = bytearray(fake_template())
    struct.pack_into("<I", data, 240, motion)
    return bytes(data)


class DoorBodyOracleTests(unittest.TestCase):
    def test_moving_and_fixed_motion_types(self):
        data = nif.serialize(sfnif.build_door_nif(b"Door", [], [], leaf_collision=body(2), frame_collision_blobs=[body(1)]))
        report = oracle.audit(data)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["unassessed"], [])
        self.assertEqual((report["moving_bodies"], report["frame_bodies"]), (1, 1))

    def test_pinned_leaf_and_moving_frame_fail(self):
        data = nif.serialize(sfnif.build_door_nif(b"Door", [], [], leaf_collision=body(1), frame_collision_blobs=[body(2)]))
        self.assertEqual(len(oracle.audit(data)["errors"]), 2)

    def test_missing_leaf_is_error(self):
        self.assertTrue(oracle.audit(nif.serialize(sfnif.build_door_nif(b"Door", [], [])))["errors"])

    def test_unknown_physics_is_unassessed(self):
        report = oracle.audit(nif.serialize(sfnif.build_door_nif(b"Door", [], [], leaf_collision=b"unknown!")))
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["unassessed"])


if __name__ == "__main__":
    unittest.main()
