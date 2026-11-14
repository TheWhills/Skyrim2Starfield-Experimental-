import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import af_pose as P  # noqa: E402


class PoseTests(unittest.TestCase):
    def test_world_pose_chain_and_keys(self):
        """A root, a pelvis 1 m up, an arm 0.5 m along x: rotating the pelvis 90 degrees about z swings the arm to y."""
        s = math.sqrt(0.5)
        rig = {"names": ["Root", "C_Pelvis", "L_UpperArm"], "parents": [-1, 0, 1],
               "t": [np.zeros(3), np.array([0, 0, 1.0]), np.array([0.5, 0, 0])],
               "q": [np.array([0, 0, 0, 1.0])] * 3}
        rest = P.world_pose(rig, {"rotations": {}, "translations": {}}, 0)
        np.testing.assert_allclose(rest["L_UpperArm"], [0.5, 0, 1.0], atol=1e-9)
        rb = {"rotations": {"C_Pelvis": [(0, (0, 0, 0, 1.0)), (10, (0, 0, s, s))]}, "translations": {}}
        self.assertTrue(np.allclose(P.world_pose(rig, rb, 5)["L_UpperArm"], [0.5, 0, 1.0]))   # key at/before 5
        np.testing.assert_allclose(P.world_pose(rig, rb, 10)["L_UpperArm"], [0, 0.5, 1.0], atol=1e-9)
        out = P.report("x", P.world_pose(rig, rb, 10), {"C_Pelvis"})
        self.assertIn("L_UpperArm", out)
        self.assertIn("rel pelvis +0.000 +0.500 +0.000", out)
        self.assertIn("(not keyed)", out)
        self.assertEqual(P.joints(["Root", "C_Pelvis", "L_Hand", "R_Finger11"]), ["C_Pelvis", "L_Hand"])


if __name__ == "__main__":
    unittest.main()
