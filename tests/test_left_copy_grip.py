"""The left-hand copy's grip constant in the combat plugin (native/combat/src/left_copy.cpp, left_grip()) must be the
converter's left grip (fo4sf.skyrimweapon.left_grip_metres(): WeaponLeft's rest grip on L_Wrist), so the runtime copy
and the worn left blade sit in the same place."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import skyrimweapon  # noqa: E402

SRC = os.path.join(ROOT, "native", "combat", "src", "left_copy.cpp")


class LeftCopyGripTests(unittest.TestCase):
    def test_constant_matches_converter(self):
        with open(SRC, encoding="utf-8") as f:
            text = f.read()
        body = text[text.index("Xform left_grip()"):]
        body = body[:body.index("return g;")]
        nums = [float(v) for v in re.findall(r"-?\d+\.\d+", body)]
        self.assertEqual(len(nums), 12, body)
        rot, trans = skyrimweapon.left_grip_metres()
        for got, want in zip(nums[:9], rot):
            self.assertAlmostEqual(got, want, places=5)
        for got, want in zip(nums[9:], trans):
            self.assertAlmostEqual(got, want, places=5)


if __name__ == "__main__":
    unittest.main()
