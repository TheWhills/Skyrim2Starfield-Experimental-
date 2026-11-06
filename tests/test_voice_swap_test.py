"""scripts/npc/voice_swap_test.py: a vanilla line written under each of our greeting file names (synthetic)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
import voice_swap_test as VS  # noqa: E402

FACES = {"npcs": [
    {"edid": "Ralof", "female": False, "voice": {"voice_type": "S2S_MaleNord_Ralof", "greetings": [
        {"file": "00000805"}, {"file": "00000806"}]}},
    {"edid": "Ysolda", "female": True, "voice": {"voice_type": "S2S_FemaleYoungEager_Ysolda", "greetings": [
        {"file": "00000812"}]}},
    {"edid": "NoVoice", "female": False}]}


class VoiceSwapTests(unittest.TestCase):
    def test_plan(self):
        rows = VS.plan(FACES)
        self.assertEqual([(f, s) for f, _d, s in rows], [(False, "00000805"), (False, "00000806"), (True, "00000812")])
        self.assertEqual(rows[0][1], os.path.join("Sound", "Voice", "S2SFaceTest.esm", "S2S_MaleNord_Ralof"))

    def test_main_writes_the_vanilla_line_per_sex(self):
        with tempfile.TemporaryDirectory() as d:
            faces = os.path.join(d, "faces.json")
            json.dump(FACES, open(faces, "w"))
            os.makedirs(os.path.join(d, "sf", "Data"))
            fake = lambda _data, voice: (voice + ".wem", voice.encode())     # noqa: E731
            with mock.patch.object(VS, "vanilla_wem", fake):
                self.assertEqual(VS.main(["--starfield", os.path.join(d, "sf"), "--faces", faces,
                                          "--out", os.path.join(d, "mod")]), 0)
            base = os.path.join(d, "mod", "Sound", "Voice", "S2SFaceTest.esm")
            self.assertEqual(open(os.path.join(base, "S2S_MaleNord_Ralof", "00000806.wem"), "rb").read(),
                             b"genericmaleeventoned")
            self.assertEqual(open(os.path.join(base, "S2S_FemaleYoungEager_Ysolda", "00000812.wem"), "rb").read(),
                             b"genericfemaleeventoned")


if __name__ == "__main__":
    unittest.main()
