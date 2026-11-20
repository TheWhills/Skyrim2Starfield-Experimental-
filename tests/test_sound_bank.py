"""sound_bank: WAAPI arguments, file kinds, bank lookup (2026-11-20, Skyrim's forge sounds as Wwise events)."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

import sound_bank as B  # noqa: E402
import wwise_probe as WP  # noqa: E402


class SoundBankTests(unittest.TestCase):
    def test_kinds_and_names(self):
        self.assertEqual(B.wav_kind(b"RIFF\0\0\0\0WAVEfmt "), "pcm")
        self.assertEqual(B.wav_kind(b"RIFF\0\0\0\0XWMAfmt "), "xwma")
        self.assertEqual(B.wav_kind(b"OggS"), "unknown")
        self.assertEqual(B.file_stem("Ev", "sound\\fx\\a\\npc_hammer_01.wav"), "Ev_npc_hammer_01")

    def test_waapi_args(self):
        c = B.container_args("{X}", "NPCHumanBlacksmithHammer")
        self.assertEqual((c["parent"], c["type"], c["name"], c["@RandomOrSequence"]),
                         ("{X}", "RandomSequenceContainer", "S2S_NPCHumanBlacksmithHammer", 1))
        i = B.import_args("\\Actor-Mixer Hierarchy\\P\\S2S_E", ["C:\\w\\E_a.wav"])
        self.assertEqual(i["imports"][0]["objectPath"], "\\Actor-Mixer Hierarchy\\P\\S2S_E\\<Sound SFX>E_a")
        self.assertEqual(i["default"]["importLanguage"], "SFX")
        e = B.event_args("E", "\\Actor-Mixer Hierarchy\\P\\S2S_E")
        self.assertEqual(e["children"][0]["@ActionType"], 1)                     # Play
        self.assertEqual(e["children"][0]["@Target"], "\\Actor-Mixer Hierarchy\\P\\S2S_E")
        inc = B.inclusion_args("\\SoundBanks\\B", ["{1}"])
        self.assertEqual(inc["inclusions"][0]["filter"], ["events", "structures", "media"])

    def test_find_bank(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Windows"))
            p = os.path.join(d, "Windows", f"{WP.fnv1_32('Starfield_XXX_Scratch')}.bnk")
            open(p, "wb").close()
            self.assertEqual(B.find_bank_file(d, "Starfield_XXX_Scratch"), p)
            self.assertIsNone(B.find_bank_file(d, "Other"))

    def test_scratch_bank_id(self):
        # the empty vanilla bank our events go in: its file is named by this id (owner's soundbanksinfo.json)
        self.assertEqual(WP.fnv1_32("Starfield_XXX_Scratch"), 1490023241)


if __name__ == "__main__":
    unittest.main()
