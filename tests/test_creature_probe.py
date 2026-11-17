"""scripts/armor/creature_probe.py helpers on synthetic data: path subrecords, race rows, NPC_ race counts, Skyrim
project-relative path resolution, and the character file's rig / behaviour / clip split."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import creature_probe as C  # noqa: E402


class CreatureProbeTests(unittest.TestCase):
    def test_path_subs_and_race_row(self):
        subs = [(b"EDID", b"ChickenRace\0"), (b"ANAM", b"Actors\\Chicken\\Character Assets\\skeleton.nif\0"),
                (b"DATA", struct.pack("<4f", 1, 2, 3, 4)), (b"MODL", b"Actors\\Chicken\\ChickenProject.hkx\0"),
                (b"FULL", b"Chicken\0"), (b"MTNM", b"WALK"), (b"MTNM", b"RUN1")]
        self.assertEqual(C.path_subs(subs), [("ANAM", "Actors\\Chicken\\Character Assets\\skeleton.nif"),
                                             ("MODL", "Actors\\Chicken\\ChickenProject.hkx")])
        r = C.race_row(subs, 0xA919D)
        self.assertEqual((r["form"], r["edid"], r["counts"]["MTNM"]), ("000A919D", "ChickenRace", 2))

    def test_npc_race_counts(self):
        recs = [(b"NPC_", b"", [(b"RNAM", struct.pack("<I", 7))], 1), (b"NPC_", b"", [(b"RNAM", struct.pack("<I", 7))], 2),
                (b"NPC_", b"", [(b"EDID", b"x\0")], 3)]
        self.assertEqual(C.npc_race_counts(recs), {7: 2})

    def test_resolve_and_character_refs(self):
        self.assertEqual(C.resolve("meshes\\actors\\chicken\\chickenproject.hkx", "Characters\\ChickenCharacter.hkx"),
                         "meshes\\actors\\chicken\\characters\\chickencharacter.hkx")
        refs = C.character_refs(["Character Assets\\skeleton.HKX", "Behaviors\\ChickenBehavior.hkx",
                                 "Animations\\Idle.hkx", "Animations\\WalkForward.hkx", "ChickenCharacter"])
        self.assertEqual(refs, {"rig": ["Character Assets\\skeleton.HKX"], "behaviors": ["Behaviors\\ChickenBehavior.hkx"],
                                "animations": ["Animations\\Idle.hkx", "Animations\\WalkForward.hkx"]})

    def test_starfield_listing(self):
        import tempfile
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_fo4land import grup, rec
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
            race = rec(b"RACE", 0x100, [(b"EDID", b"AshtaRace\0"), (b"ANAM", b"Actors\\Ashta\\skeleton.nif\0"),
                                        (b"NAM5", b"Actors\\Ashta\\CharacterAssets\\skeleton.rig\0"),
                                        (b"NAM6", b"AnimTextData\\Tables\\Graphs\\Ashta_Root.agx\0")])
            npc = rec(b"NPC_", 0x200, [(b"EDID", b"Ashta01\0"), (b"RNAM", struct.pack("<I", 0x100))])
            with open(os.path.join(d, "Starfield.esm"), "wb") as fh:
                fh.write(tes4 + grup(b"RACE", 0, [race]) + grup(b"NPC_", 0, [npc]))
            lines = C.starfield_side(d, [])
        row = next(ln for ln in lines if "AshtaRace" in ln)
        self.assertIn("(1 NPC_)", row)
        self.assertIn("NAM5 Actors\\Ashta\\CharacterAssets\\skeleton.rig", row)
        self.assertIn("NAM6 AnimTextData\\Tables\\Graphs\\Ashta_Root.agx", row)


if __name__ == "__main__":
    unittest.main()
