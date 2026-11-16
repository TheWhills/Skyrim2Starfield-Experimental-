"""scripts/armor/clip_join.py: the forge's pairs, the summary leaves props out of the body maximum (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import clip_join as J  # noqa: E402


class ClipJoinTest(unittest.TestCase):
    def test_pairs(self):
        p = J.forge_pairs()
        self.assertIn(("blacksmithforgediscard.hkx", "blacksmithforgepull.hkx"), p)
        self.assertIn(("blacksmithforgehammer.hkx", "blacksmithforgehammer.hkx"), p)     # the loop itself
        self.assertEqual(len(p), 25)

    def test_summary(self):
        s = J.summary([("AnimObjectL", 120.0, 3.0), ("NPC Spine [Spn0]", 4.5, 0.1)])
        self.assertTrue(s.startswith("body max    4.5 deg"), s)
        self.assertIn("AnimObjectL (prop) 120.0", s)


if __name__ == "__main__":
    unittest.main()
