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


    def test_paths_and_related(self):
        self.assertEqual(S.sound_path("FX\\NPC\\a.wav"), "sound\\fx\\npc\\a.wav")
        self.assertEqual(S.sound_path("Data\\Sound\\FX\\b.wav"), "sound\\fx\\b.wav")      # was sound\\data\\sound
        self.assertEqual(S.sound_path("sound\\fx\\c.wav"), "sound\\fx\\c.wav")
        self.assertEqual(S.related(["WwiseEvent_WPNGrenadeThrow", "X", None, "wpngrenadethrowsd"], "WPNGrenadeThrow"),
                         ["WwiseEvent_WPNGrenadeThrow", "wpngrenadethrowsd"])

    def test_helpers(self):
        self.assertEqual(S.hexhead(b"\x01\x02", 1), "01 ...")
        self.assertEqual(S.zstr(b"Sound\\FX\\a.wav\0junk"), "Sound\\FX\\a.wav")
        self.assertIn("NPCHumanBlacksmithForgeQuench", S.SKYRIM_FORGE)


if __name__ == "__main__":
    unittest.main()
