"""scripts/interior/work_templates.py: grouping by animation keyword (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
import work_templates as W  # noqa: E402


class WorkTemplatesTest(unittest.TestCase):
    def test_group(self):
        rows = [("NPCStanding_WipeWall", 1, 0, ["AnimFurnStanding_WipeWall", "FurnitureClassWork"], "m"),
                ("NPCClipboard", 2, 0, ["FurnitureClassWork", "AnimFurnStanding_Clipboard"], "m"),
                ("Odd", 3, 0, ["FurnitureClassWork"], "")]
        g = W.group(rows)
        self.assertEqual(sorted(g), ["(none)", "AnimFurnStanding_Clipboard", "AnimFurnStanding_WipeWall"])
        self.assertIn("AnimFurnStanding_WipeWall", W.OURS)


if __name__ == "__main__":
    unittest.main()
