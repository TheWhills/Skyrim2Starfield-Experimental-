"""sound_swap: vanilla events' streamed files and the assignment of Skyrim's files to them (2026-11-20)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

import sound_swap as S  # noqa: E402


class SwapTests(unittest.TestCase):
    def test_event_files(self):
        info = {"SoundBanksInfo": {"SoundBanks": [{"IncludedEvents": [
            {"Name": "A", "ReferencedStreamedFiles": [{"Id": "1"}, {"Id": "2"}]},
            {"Name": "B", "ReferencedStreamedFiles": [{"Id": "2"}]}, {"Name": "C"}]}]}}
        files, users = S.event_files(info)
        self.assertEqual(files, {"A": ["1", "2"], "B": ["2"], "C": []})
        self.assertEqual(users["2"], {"A", "B"})

    def test_assign(self):
        self.assertEqual(S.assign(["h1", "h2", "h3", "h4"], ["a", "b", "c"]), [("a", "h1"), ("b", "h2"), ("c", "h3")])
        self.assertEqual(S.assign(["q"], ["a", "b", "c"]), [("a", "q"), ("b", "q"), ("c", "q")])
        self.assertEqual(S.assign([], ["a"]), [])

    def test_swap_table(self):
        self.assertNotIn("NPCHumanBlacksmithHammerDistant", S.SWAP)
        self.assertEqual(len(set(S.SWAP.values())), len(S.SWAP))


if __name__ == "__main__":
    unittest.main()
