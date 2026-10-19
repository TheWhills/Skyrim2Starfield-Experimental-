"""fo4sf.skeletonmap: internal consistency of the Skyrim -> Starfield bone table (no game files; the real-skeleton
check is scripts/armor/bone_map_report.py)."""
import os
import sys
import unittest
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import skeletonmap as M  # noqa: E402


def mirror(name):
    for a, b in (("NPC L ", "NPC R "), ("[L", "[R"), ("L_", "R_"), ("AnimObjectL", "AnimObjectR")):
        name = name.replace(a, b)
    return name


class SkeletonMapTests(unittest.TestCase):
    def test_every_starfield_bone_driven_once(self):
        targets = Counter(list(M.MAP.values()) + [b for v in M.SPLIT.values() for b, _ in v])
        self.assertEqual([b for b, n in targets.items() if n > 1], [])
        self.assertFalse(set(targets) & set(M.DERIVED))
        self.assertFalse(set(targets) & set(M.WORLD))
        self.assertFalse(set(M.REST) & (set(targets) | set(M.DERIVED) | set(M.WORLD)))

    def test_left_right_symmetric(self):
        for a, b in M.MAP.items():
            if " L " in a or "[L" in a or a == "AnimObjectL":
                self.assertEqual(M.MAP.get(mirror(a)), mirror(b), a)

    def test_split_weights_sum_to_one_and_sources_exclusive(self):
        for src, parts in M.SPLIT.items():
            self.assertAlmostEqual(sum(w for _, w in parts), 1.0)
            self.assertNotIn(src, M.MAP)
        self.assertFalse(set(M.MAP) & set(M.UNMAPPED))

    def test_fingers_and_limbs(self):
        self.assertEqual(M.MAP["NPC L Finger00 [LF00]"], "L_Thumb")
        self.assertEqual(M.MAP["NPC R Finger42 [RF42]"], "R_Pinky2")
        self.assertEqual(M.MAP["NPC L Hand [LHnd]"], "L_Wrist")
        self.assertEqual(M.starfield_of("NPC Spine1 [Spn1]"), [("C_Spine1", 0.5), ("C_Spine2", 0.5)])
        self.assertEqual(M.starfield_of("Quiver"), [])

    def test_coverage_reports_unknown_names(self):
        cov = M.coverage(list(M.MAP) + ["Mystery Bone"], list(M.MAP.values()))
        self.assertEqual(cov["skyrim_missing_from_table"], ["Mystery Bone"])
        self.assertIn("C_Spine1", cov["table_starfield_not_in_skeleton"])


if __name__ == "__main__":
    unittest.main()
