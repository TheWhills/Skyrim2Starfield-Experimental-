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


    def test_hands_on_thighs(self):
        """Hip at x -0.1, knee 0.4 m forward: a left wrist 0.2 m along, 0.05 up and 0.02 outward reads back as such."""
        pose = {"L_Thigh": np.array([-0.1, 0, 0.5]), "L_Calf": np.array([-0.1, 0.4, 0.5]),
                "L_Wrist": np.array([-0.12, 0.2, 0.55]), "R_Thigh": np.array([0.1, 0, 0.5]),
                "R_Calf": np.array([0.1, 0.4, 0.5]), "R_Hand": np.array([0.1, 0.5, 0.45])}
        got = P.hands_on_thighs(pose)
        self.assertEqual(got["L"], (0.5, 0.05, 0.02))
        self.assertEqual(got["R"], (1.0, -0.05, 0.0))                    # past the knee: clamped to it
        self.assertIn("hand over L thigh: 0.50 of the way to the knee, +0.050 m above", P.report("x", pose, set()))
        self.assertEqual(P.hands_on_thighs({"C_Pelvis": np.zeros(3)}), {})


if __name__ == "__main__":
    unittest.main()
