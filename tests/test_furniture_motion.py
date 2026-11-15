"""scripts/armor/furniture_motion.py: where Skyrim's furniture clips leave the root, on synthetic motion blocks."""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import furniture_motion as M  # noqa: E402


class FurnitureMotionTest(unittest.TestCase):
    def test_end_of_a_block(self):
        s = math.sin(math.radians(45)), math.cos(math.radians(45))
        blk = {"translations": [(0.0, 0, 0, 0), (1.0, 0, -21.0, 0)], "rotations": [(1.0, 0, 0, s[0], s[1])]}
        self.assertEqual(M.end_of(blk), (0.0, -0.3, 0.0, 90.0))       # 21 units back = 0.3 m, a quarter turn
        self.assertEqual(M.end_of({}), (0.0, 0.0, 0.0, 0.0))

    def test_set_motion(self):
        sets = {"WallLean": ("f", "t", [("idle.afx", "wall_idlebackloop.hkx", None),
                                        ("enterfromstand.afx", "Wall_IdleBackEnter.hkx", None)])}
        motion = {"wall_idlebackenter": {"translations": [(1.0, 0, -21.0, 0)], "rotations": []}}
        got = M.set_motion(motion, sets)["WallLean"]
        self.assertIsNone(got[0][2])
        self.assertEqual(got[1][2], (0.0, -0.3, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
