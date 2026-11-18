"""fo4sf.creature_race on synthetic records: paths moved to our folder, FormIDs pointed at the copies, the chain found
from the race, and the plugin written."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import creature_race as R, fo4land, sfplugin  # noqa: E402

z = sfplugin.zs
u = lambda v: struct.pack("<I", v)  # noqa: E731
HDR = struct.pack("<4sIII", b"RACE", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
RACE = (b"RACE", HDR, [(b"EDID", z("CritterRace")), (b"FULL", u(1234)), (b"DESC", u(9)),
                       (b"ANAM", z("Actors\\Critter\\CharacterAssets\\skeleton.nif")),
                       (b"NAM5", z("actors\\critter\\characterassets\\skeleton.rig")),
                       (b"NAM6", z("AnimTextData\\Tables\\Graphs\\Critter_Root.agx")),
                       (b"DNAM", z("Actors\\Critter\\Animations")), (b"WNAM", u(0x100)), (b"RNAM", u(0x176B6)),
                       (b"SGNM", z("AnimTextData\\Tables\\Graphs\\Critter_NonStrafing.agx")),
                       (b"SAPT", z("Actors\\Critter\\Animations")), (b"SRAF", b"\x01\x00\x00\x00")], 0x176B6)
SKIN = (b"ARMO", HDR, [(b"EDID", z("Skin_Critter_Trilobite")), (b"RNAM", u(0x176B6)), (b"INDX", b"\0\0"),
                       (b"MODL", u(0x200))], 0x100)
ADDON = (b"ARMA", HDR, [(b"EDID", z("AA_Critter_Trilobite")), (b"RNAM", u(0x176B6)),
                        (b"MOD2", z("Actors\\Critter\\Mesh\\Critter_Trilobite\\Critter_Trilobite.nif"))], 0x200)
NPC = (b"NPC_", HDR, [(b"EDID", z("Traits_Critter_Trilobite")), (b"FULL", u(77)), (b"RNAM", u(0x176B6)),
                      (b"WNAM", u(0x100))], 0x2C180F)


class RaceTests(unittest.TestCase):
    def test_redirect(self):
        self.assertEqual(R.redirect("Actors\\Critter\\Animations", "Actors\\Critter", "Actors\\S2S\\Chicken"),
                         "Actors\\S2S\\Chicken\\Animations")
        self.assertEqual(R.redirect("actors/critter/x.rig", "Actors\\Critter", "Actors\\S2S\\Chicken"),
                         "Actors\\S2S\\Chicken\\x.rig")
        self.assertEqual(R.redirect("Actors\\Critterling\\x", "Actors\\Critter", "B"), "Actors\\Critterling\\x")

    def test_find_chain(self):
        by = {b"RACE": [RACE], b"ARMO": [SKIN], b"ARMA": [ADDON], b"NPC_": [NPC]}
        self.assertEqual(R.find_chain(by, "CritterRace", 0x2C180F), (RACE, SKIN, ADDON, NPC))
        with self.assertRaises(KeyError):
            R.find_chain(by, "NoRace", 0x2C180F)

    def test_build_plugin(self):
        data, rep = R.build_plugin(RACE, SKIN, ADDON, NPC, {"hedr_version": 0.96, "form_version": 555},
                                   "Actors\\Critter", "Actors\\S2S\\Chicken", "Chicken")
        new = {k: int(v, 16) for k, v in rep["form_ids"].items()}
        self.assertEqual(new["S2S_ChickenRace"], 0x01000800)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "S2SCreatures.esm")
            open(p, "wb").write(data)
            recs = {r[0]: dict(r[2]) for r in sfplugin.records(p, [b"RACE", b"ARMO", b"ARMA", b"NPC_"])}
        race = recs[b"RACE"]
        self.assertEqual(fo4land.zstring(race[b"ANAM"]), "Actors\\S2S\\Chicken\\CharacterAssets\\skeleton.nif")
        self.assertEqual(fo4land.zstring(race[b"NAM5"]), "Actors\\S2S\\Chicken\\characterassets\\skeleton.rig")
        self.assertEqual(fo4land.zstring(race[b"DNAM"]), "Actors\\S2S\\Chicken\\Animations")
        self.assertEqual(fo4land.zstring(race[b"SAPT"]), "Actors\\S2S\\Chicken\\Animations")
        self.assertEqual(fo4land.zstring(race[b"NAM6"]), "AnimTextData\\Tables\\Graphs\\Critter_Root.agx")   # graph kept
        self.assertEqual(fo4land.zstring(race[b"FULL"]), "Chicken")
        self.assertNotIn(b"DESC", race)
        self.assertEqual(struct.unpack("<I", race[b"WNAM"])[0], new["S2S_Chicken_Skin"])
        self.assertEqual(struct.unpack("<I", race[b"RNAM"])[0], new["S2S_ChickenRace"])
        self.assertEqual(struct.unpack("<I", recs[b"ARMO"][b"MODL"])[0], new["S2S_Chicken_SkinAA"])
        self.assertEqual(fo4land.zstring(recs[b"ARMA"][b"MOD2"]),
                         "Actors\\S2S\\Chicken\\Mesh\\Critter_Trilobite\\Critter_Trilobite.nif")
        npc = recs[b"NPC_"]
        self.assertEqual(struct.unpack("<I", npc[b"RNAM"])[0], new["S2S_ChickenRace"])
        self.assertEqual(struct.unpack("<I", npc[b"WNAM"])[0], new["S2S_Chicken_Skin"])
        self.assertEqual(fo4land.zstring(npc[b"EDID"]), "S2S_Chicken")


if __name__ == "__main__":
    unittest.main()
