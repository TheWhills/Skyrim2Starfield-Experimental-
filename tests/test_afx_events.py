"""scripts/armor/afx_events.py: events of Starfield descriptors, sound payloads summarised (synthetic .afx text)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import afx_events as E  # noqa: E402

A = ("<animation><tag>Idle</tag><events>\r\n"
     "\t\t<event><frame>12</frame><name>SoundPlay</name><payload>OBJ_RepairHammer_Hit</payload></event>\r\n"
     "\t\t<event><frame>3</frame><name>AnimObjLoad</name><payload>AnimObjectHammer</payload></event>\r\n"
     "\t\t<event><frame>40</frame><name>FootLeft</name></event>\r\n</events></animation>")
B = A.replace("OBJ_RepairHammer_Hit", "NPC_Footstep_Dirt")


class AfxEventsTest(unittest.TestCase):
    def test_events(self):
        self.assertEqual(E.events(A), [(12, "SoundPlay", "OBJ_RepairHammer_Hit"),
                                       (3, "AnimObjLoad", "AnimObjectHammer"), (40, "FootLeft", "")])

    def test_summarize_keeps_matching_sound_payloads(self):
        names, payloads = E.summarize({"a.afx": A, "b.afx": B})
        self.assertEqual(names["SoundPlay"], 2)
        self.assertEqual(dict(payloads), {"SoundPlay": {"OBJ_RepairHammer_Hit": "a.afx"}})   # footstep: no match


if __name__ == "__main__":
    unittest.main()
