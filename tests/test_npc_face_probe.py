"""scripts/npc/npc_face_probe.py on synthetic plugins: Starfield NPC field stats, Skyrim head parts and tints."""
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
from fo4sf import sfplugin  # noqa: E402
import npc_face_probe as P  # noqa: E402

HDR = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(8)       # noqa: E731
u32 = lambda v: struct.pack("<I", v)                                 # noqa: E731
z = sfplugin.zs


def rec(t, fid, subs):
    return (t, HDR(t), subs, fid)


class ProbeTests(unittest.TestCase):
    def build(self, d, name, recs):
        path = os.path.join(d, name)
        with open(path, "wb") as fh:
            fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}))
        return path

    def test_starfield(self):
        with tempfile.TemporaryDirectory() as d:
            esm = self.build(d, "s.esm", [
                rec(b"RACE", 0x900, [(b"EDID", z("HumanRace")), (b"SKIN", z("Tone03"))]),
                rec(b"HDPT", 0x901, [(b"EDID", z("Eyes_Blue")), (b"PNAM", u32(2))]),
                rec(b"HDPT", 0x902, [(b"EDID", z("Brows_A")), (b"PNAM", u32(6))]),
                rec(b"NPC_", 0x910, [(b"EDID", z("A")), (b"RNAM", u32(0x900)), (b"PNAM", u32(0x901)),
                                     (b"PNAM", u32(0x902)), (b"STON", b"\x03"), (b"FMSI", u32(1)),
                                     (b"MNAM", u32(1)), (b"TNAM", z("Dermaesthetic")), (b"QNAM", z("African_Male_yo1_Sk7")),
                                     (b"MNAM", u32(1)), (b"TNAM", z("Lipstick1")), (b"QNAM", z("Lipstick_Soft"))]),
                rec(b"NPC_", 0x911, [(b"EDID", z("SarahMorgan")), (b"RNAM", u32(0x900)), (b"PNAM", u32(0x901)),
                                     (b"STON", z("Tone05")), (b"FMSI", u32(1))]),
                rec(b"NPC_", 0x912, [(b"EDID", z("Robot")), (b"RNAM", u32(0x999))])])
            r = P.starfield(esm)
            self.assertEqual(r["human_npcs_with_face"], 2)
            self.assertEqual(r["values"]["STON"]["distinct"], 2)
            self.assertEqual(r["dermaesthetic_by_skin_tone"], [("African_Male_yo1_Sk7 | STON 3", 1)])
            self.assertEqual(dict(r["texture_layers"]), {"Dermaesthetic": 1, "Lipstick1": 1})
            self.assertEqual(r["head_parts_used_by_type"]["2"]["top"], [("Eyes_Blue", 2)])
            self.assertEqual([x["edid"] for x in r["dumps"]], ["SarahMorgan"])
            self.assertEqual(r["editor_ids"], ["HDPT 00000901 Eyes_Blue", "HDPT 00000902 Brows_A"])
            self.assertIn("SKIN: Tone03", r["human_race_text"])

    def test_skyrim(self):
        acbs = struct.pack("<I", 0) + bytes(20)
        with tempfile.TemporaryDirectory() as d:
            esm = self.build(d, "k.esm", [
                rec(b"RACE", 0x13746, [(b"EDID", z("NordRace")), (b"MNAM", b""), (b"TINI", struct.pack("<H", 3)),
                                       (b"TINT", z("SkinTone.dds")), (b"TINP", struct.pack("<H", 6)), (b"FNAM", b""),
                                       (b"TINI", struct.pack("<H", 3)), (b"TINT", z("F.dds")),
                                       (b"TINP", struct.pack("<H", 1))]),
                rec(b"HDPT", 0x200, [(b"EDID", z("MaleEyesHumanLightBlue")), (b"PNAM", u32(2)),
                                     (b"MODL", z("eyes.nif"))]),
                rec(b"NPC_", 0x2BF9D, [(b"EDID", z("Ralof")), (b"ACBS", acbs), (b"RNAM", u32(0x13746)),
                                       (b"PNAM", u32(0x200)), (b"QNAM", struct.pack("<3f", .8, .6, .5)),
                                       (b"TINI", struct.pack("<H", 3)), (b"TINC", bytes([200, 150, 120, 0])),
                                       (b"TINV", u32(100))])])
            rows = P.skyrim(esm, ["Ralof", "Nobody"])
            r = rows[0]
            self.assertEqual((r["race"], r["female"]), ("NordRace", False))
            self.assertEqual(r["head_parts"][0]["type"], "eyes")
            self.assertEqual(r["tints"][0]["mask"], "SkinTone.dds")
            self.assertEqual(r["tints"][0]["kind"], "skin tone")
            self.assertEqual(r["tints"][0]["color"], (200, 150, 120, 0))
            self.assertEqual(rows[1]["error"], "no such NPC")
            json.dumps(rows, default=str)


if __name__ == "__main__":
    unittest.main()
