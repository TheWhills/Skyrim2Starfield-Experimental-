"""scripts/armor/head_turn_probe.py's angle helpers: facing from a bone's turn off its rest pose, yaw / pitch, and the
head relative to the chest (wrapped)."""
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import head_turn_probe as P  # noqa: E402


def qz(deg):
    h = math.radians(deg) / 2
    return np.array([0.0, 0.0, math.sin(h), math.cos(h)])


def qx(deg):
    h = math.radians(deg) / 2
    return np.array([math.sin(h), 0.0, 0.0, math.cos(h)])


class HeadProbeTests(unittest.TestCase):
    def test_angles(self):
        rest = qx(90)                                         # a bone whose rest axes are not the world's
        wq = np.stack([P.qmul(qz(30), rest), P.qmul(qx(20), rest), rest])
        yp = P.yaw_pitch(P.facing(wq, rest))
        self.assertAlmostEqual(yp[0, 0], 30.0, places=6)      # turned left
        self.assertAlmostEqual(yp[1, 1], 20.0, places=6)      # tipped up
        self.assertTrue(np.allclose(yp[2], 0.0))
        head = P.facing(np.stack([qz(170)]), np.array([0.0, 0.0, 0.0, 1.0]))
        chest = P.facing(np.stack([qz(-170)]), np.array([0.0, 0.0, 0.0, 1.0]))
        self.assertAlmostEqual(P.relative(head, chest)[0, 0], -20.0, places=6)   # wrapped, not 340


if __name__ == "__main__":
    unittest.main()
