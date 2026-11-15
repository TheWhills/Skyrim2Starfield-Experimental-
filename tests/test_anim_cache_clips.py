"""scripts/armor/anim_cache_clips.py: clips a cache file resolves outside our folder, on synthetic text."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import anim_cache_clips as C  # noqa: E402


class CacheClipsTest(unittest.TestCase):
    def test_outside_clips(self):
        text = ("3\n1\n123\n4\nActors\\Human\\Animations\\Furniture\\s2s_sit\\Idle.af\n"
                "Actors\\Human\\Animations\\Common\\PartialBody\\HandsBehind.af\n"
                "Actors\\Human\\Animations\\Furniture\\chair\\RearEnterFromStand.af\n"
                "Actors\\Human\\Animations\\Common\\PartialBody\\HandsBehind.af\n")
        ours, other = C.outside_clips(text, "s2s_sit")
        self.assertTrue(ours)
        self.assertEqual(other["Actors\\Human\\Animations\\Common\\PartialBody\\HandsBehind.af"], 2)
        self.assertEqual(len(other), 2)
        self.assertFalse(C.outside_clips("Actors\\X\\chair\\Idle.af\n", "s2s_sit")[0])


if __name__ == "__main__":
    unittest.main()
