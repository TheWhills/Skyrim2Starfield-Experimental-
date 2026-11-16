"""scripts/armor/sound_records.py: sound-like groups and matching EditorIDs (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import sound_records as S  # noqa: E402


class SoundRecordsTest(unittest.TestCase):
    def test_groups_and_matches(self):
        self.assertEqual(S.sound_groups([b"STAT", b"SNDR", b"WWED"]), [b"WWED", b"SNDR"])
        self.assertEqual(S.matching(["OBJ_Hammer_Impact", "NPC_Footstep", "FX_SteamHiss", "WPNGrenadeThrow"]),
                         ["FX_SteamHiss", "OBJ_Hammer_Impact"])


if __name__ == "__main__":
    unittest.main()
