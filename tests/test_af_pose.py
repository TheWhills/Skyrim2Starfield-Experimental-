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


    def test_dump_clip(self):
        rig = {"names": ["C_Hips", "C_Spine", "L_Wrist"], "parents": [-1, 0, 1],
               "t": [np.array([0, 0, 1.0]), np.array([0, 0, 0.2]), np.array([0.3, 0, 0])],
               "q": [np.array([0, 0, 0, 1.0])] * 3}
        rb = {"frames": 3, "rotations": {}, "translations": {"C_Hips": [(0, (0, 0, 1.0)), (2, (0, 0, 0.5))]}}
        d = P.dump_clip("x", rig, rb)
        self.assertEqual(d["joints"], ["C_Hips", "C_Spine", "L_Wrist"])
        self.assertEqual(d["bones"], [("C_Hips", "C_Spine")])
        self.assertEqual(len(d["frames"]), 3)
        self.assertEqual(d["frames"][0][2], [0.3, 0.0, 1.2])
        self.assertEqual(d["frames"][2][2], [0.3, 0.0, 0.7])

    def test_hand_gaps(self):
        """A belly 0.12 m thick around the spine: a wrist 0.2 m in front is outside, one 0.05 m in front inside; the
        own forearm is never counted; the gap report finds the inside frames."""
        ring = [[0.12] * 16 for _ in range(5)]
        profiles = {"belly": {"radius": ring}, "L_forearm": {"radius": [[0.5] * 16 for _ in range(5)]}}
        pose = {"C_Spine": np.array([0, 0, 1.0]), "C_Chest": np.array([0, 0, 1.3]),
                "L_Forearm": np.array([-0.3, 0.2, 1.15]), "L_Wrist": np.array([-0.1, 0.2, 1.15])}
        g = P.hand_gaps(pose, profiles)["L"]
        self.assertEqual(g[1], "belly")
        self.assertAlmostEqual(g[0], math.hypot(-0.02, 0.2) - 0.12, places=3)    # the palm, 8 cm past the wrist
        pose["L_Wrist"] = np.array([0.0, 0.05, 1.15])
        pose["L_Forearm"] = np.array([0.0, 0.3, 1.15])
        self.assertLess(P.hand_gaps(pose, profiles)["L"][0], 0)
        rig = {"names": ["C_Spine", "C_Chest", "L_Forearm", "L_Wrist"], "parents": [-1, -1, -1, -1],
               "t": [pose["C_Spine"], pose["C_Chest"], np.array([-0.3, 0.2, 1.15]), np.array([-0.1, 0.2, 1.15])],
               "q": [np.array([0, 0, 0, 1.0])] * 4}
        rb = {"frames": 11, "rotations": {}, "translations": {
            "L_Wrist": [(0, (-0.1, 0.2, 1.15)), (4, (0.0, 0.05, 1.15)), (7, (-0.1, 0.2, 1.15))],
            "L_Forearm": [(0, (-0.3, 0.2, 1.15)), (4, (0.0, 0.3, 1.15)), (7, (-0.3, 0.2, 1.15))]}}
        lines = P.gap_report("clip", rig, rb, profiles, samples=11)
        self.assertIn("inside the body: frames 4-6 (3 sampled)", lines[1])

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


    def test_shoulders(self):
        """Neck at 1.5 m; left clavicle at x -0.02, 1.48 m, shoulder joint 0.15 m out and 0.05 m lower: 0.07 below the
        neck, 0.17 out, clavicle sloping atan(0.05 / 0.15) = 18.4 deg."""
        pose = {"C_Neck": np.array([0, 0, 1.5]), "L_Clavicle": np.array([-0.02, 0, 1.48]),
                "L_Biceps": np.array([-0.17, 0, 1.43])}
        self.assertEqual(P.shoulders(pose), {"L": (0.07, 0.17, 18.4)})
        self.assertIn("L shoulder: +0.070 m below the neck, 0.170 m out, clavicle +18.4 deg", P.report("x", pose, set()))


if __name__ == "__main__":
    unittest.main()
