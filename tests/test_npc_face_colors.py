"""Eye colour, skin tone and brow colour for converted NPCs (npc_records + face_fit.face_colors); Skyrim values from
the owner's npc_face_probe run (2026-11-06)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import sfplugin  # noqa: E402
import npc_records as R  # noqa: E402
import face_fit  # noqa: E402

z = sfplugin.zs


class MappingTests(unittest.TestCase):
    def test_eye_color(self):
        self.assertEqual(R.eye_color("MaleEyesHumanIceBlue")[0], "Blue")
        self.assertEqual(R.eye_color("FemaleEyesHumanLightBlue")[0], "Blue")
        self.assertEqual(R.eye_color("FemaleEyesHumanAmber")[0], "Copper")
        self.assertEqual(R.eye_color("MaleEyesHumanDarkBrown")[0], "BrownDark")     # not plain Brown
        self.assertEqual(R.eye_color("MaleEyesHumanBrown")[0], "Brown")
        self.assertEqual(R.eye_color("EyesKhajiitMaleWeird"), (None, "no colour word"))
        self.assertEqual(R.eye_color(None)[0], None)
        for _w, name in R.EYE_WORDS:
            self.assertIn(name, R.EYE_COLORS)

    def test_skin_tone_orders_the_four_npcs(self):
        tones = {n: R.skin_tone(rgb) for n, rgb in {"Ralof": (198, 176, 168), "Ysolda": (185, 179, 170),
                                                     "Saadia": (113, 87, 68), "Nazeem": (53, 39, 34)}.items()}
        self.assertEqual(tones["Ralof"], tones["Ysolda"])
        self.assertLess(tones["Ralof"], tones["Saadia"])
        self.assertLess(tones["Saadia"], tones["Nazeem"])
        self.assertEqual((R.skin_tone((255, 255, 255)), R.skin_tone((0, 0, 0))), (0, 8))
        self.assertIsNone(R.skin_tone(None))

    def test_skin_rgb_prefers_the_skin_tone_tint(self):
        npc = {"female": False, "tints": [{"index": 2, "color": (80, 9, 1, 0)}, {"index": 1, "color": (198, 176, 168, 0)}],
               "texture_lighting": (0.5, 0.5, 0.5)}
        tints = {(False, 1): ("SkinTone.dds", "skin tone"), (False, 2): ("Socket.dds", "eye socket upper")}
        self.assertEqual(R.skyrim_skin_rgb(npc, tints), ([198, 176, 168], "skin tone tint"))
        self.assertEqual(R.skyrim_skin_rgb({"tints": [], "texture_lighting": (0.2, 0.1, 0.0)}, tints),
                         ([51, 26, 0], "texture lighting"))

    def test_with_face_colors_keeps_vanilla_order(self):
        subs = [(b"EDID", z("A")), (b"DPLT", b"1234"), (b"STON", b"\x01"), (b"HCOL", z("Black")), (b"PKID", b"5678")]
        out = R.with_face_colors(subs, {b"STON": b"\x07", b"ECOL": z("Blue"), b"BCOL": z("Blonde")})
        self.assertEqual([s for s, _d in out], [b"EDID", b"DPLT", b"STON", b"HCOL", b"BCOL", b"ECOL", b"PKID"])
        self.assertEqual(dict(out)[b"STON"], b"\x07")
        bare = R.with_face_colors([(b"EDID", z("A"))], {b"ECOL": z("Blue"), b"STON": b"\x00"})
        self.assertEqual([s for s, _d in bare], [b"EDID", b"STON", b"ECOL"])

    def test_race_tints_and_defaults(self):
        u32 = lambda v: struct.pack("<I", v)                        # noqa: E731
        race = [(b"MNAM", b""), (b"TINI", struct.pack("<H", 1)), (b"TINT", z("SkinTone.dds")),
                (b"TINP", struct.pack("<H", 6)), (b"HEAD", u32(0x10)), (b"FNAM", b""), (b"HEAD", u32(0x20)),
                (b"TINI", struct.pack("<H", 23)), (b"TINP", struct.pack("<H", 6))]
        self.assertEqual(R.race_defaults(race), {False: [0x10], True: [0x20]})
        self.assertEqual(R.race_tints(race)[(False, 1)], ("SkinTone.dds", "skin tone"))
        self.assertEqual(R.race_tints(race)[(True, 23)][1], "skin tone")


class FaceColorsTests(unittest.TestCase):
    def real(self):
        hdpt = {0x10: {"edid": "MaleEyesHumanDarkBrown", "type": 2}, 0x11: {"edid": "MaleEyesHumanIceBlue", "type": 2},
                0x12: {"edid": "BrowsMaleHumanoid01", "type": 6}}
        tints = {(False, 1): ("SkinTone.dds", "skin tone")}
        return {"hdpt": hdpt, "races": {0x99: (tints, {False: [0x12, 0x10], True: []})}}

    def test_own_eyes_and_skin(self):
        src = {"race": 0x99, "female": False, "head_parts": [0x12, 0x11],
               "tints": [{"index": 1, "color": (198, 176, 168, 0)}]}
        subs, info = face_fit.face_colors([(b"EDID", z("T")), (b"HCOL", z("Black"))], src, self.real(), "Blonde")
        d = dict(subs)
        self.assertEqual((d[b"ECOL"], d[b"BCOL"], d[b"STON"]), (z("Blue"), z("Blonde"), bytes([R.skin_tone((198, 176, 168))])))
        self.assertEqual(info["eyes"]["from"], "own")

    def test_race_default_eyes(self):                    # Nazeem: no head parts of his own
        src = {"race": 0x99, "female": False, "head_parts": [], "tints": [{"index": 1, "color": (53, 39, 34, 0)}]}
        subs, info = face_fit.face_colors([(b"EDID", z("T"))], src, self.real(), None)
        d = dict(subs)
        self.assertEqual((d[b"ECOL"], d[b"STON"]), (z("BrownDark"), b"\x08"))
        self.assertNotIn(b"BCOL", d)
        self.assertEqual(info["eyes"]["from"], "race default")


NAMES = ["African_Male_Md1_Sk8", "African_Male_md1_Sk1", "African_Male_md1_Sk3", "African_Male_md1_Sk6",
         "African_Male_ol1_Sk8", "African_Female_md1_Sk6", "African_Female_md1_sk8", "European_Male_md1_sk3",
         "European_Male_Md1_Sk1", "European_Female_md1_Sk1", "male_as_md2_sk6_Derm_color"]


class FaceSkinTests(unittest.TestCase):
    def test_choose(self):
        self.assertEqual(R.choose_dermaesthetic(NAMES, "african", False, 8)[0], "African_Male_Md1_Sk8")   # md1 kept
        self.assertEqual(R.choose_dermaesthetic(NAMES, "african", True, 6)[0], "African_Female_md1_Sk6")
        self.assertEqual(R.choose_dermaesthetic(NAMES, "european", False, 1)[0], "European_Male_Md1_Sk1")
        self.assertEqual(R.choose_dermaesthetic(NAMES, "european", True, 1)[0], "European_Female_md1_Sk1")
        self.assertIsNone(R.choose_dermaesthetic(NAMES, "asian", True, 1)[0])
        self.assertEqual((R.skyrim_ethnicity("RedguardRace"), R.skyrim_ethnicity("NordRaceVampire"),
                          R.skyrim_ethnicity("KhajiitRace")), ("african", "european", "european"))

    def test_names_and_layer_edit(self):
        subs = [(b"EDID", z("T")), (b"MNAM", b"\x01\0\0\0"), (b"TNAM", z("Dermaesthetic")),
                (b"QNAM", z("Asian_Female_yo1_Sk3")), (b"VNAM", z("textures/actors/human/face")),
                (b"MNAM", b"\x01\0\0\0"), (b"TNAM", z("Lipstick1")), (b"QNAM", z("Lipstick_Standard"))]
        self.assertEqual(R.dermaesthetic_names([(b"NPC_", b"", subs, 1)]), ["Asian_Female_yo1_Sk3"])
        out, done = R.with_layer_texture(subs, "Dermaesthetic", "African_Female_md1_Sk6")
        self.assertTrue(done)
        q = [d for s_, d in out if s_ == b"QNAM"]
        self.assertEqual(q, [z("African_Female_md1_Sk6"), z("Lipstick_Standard")])
        self.assertFalse(R.with_layer_texture([(b"EDID", z("T"))], "Dermaesthetic", "X")[1])

    def test_face_colors_sets_face_skin(self):
        real = {"hdpt": {}, "races": {0x99: ({(False, 1): ("SkinTone.dds", "skin tone")}, {False: [], True: []})},
                "race_edids": {0x99: "RedguardRace"}, "derma": NAMES}
        src = {"race": 0x99, "female": False, "head_parts": [], "tints": [{"index": 1, "color": (53, 39, 34, 0)}]}
        subs = [(b"EDID", z("T")), (b"TNAM", z("Dermaesthetic")), (b"QNAM", z("European_Male_Md1_Sk1"))]
        out, info = face_fit.face_colors(subs, src, real, None)
        self.assertIn((b"QNAM", z("African_Male_Md1_Sk8")), out)
        self.assertEqual(info["face_skin"]["set"], True)


def sf_npc(fid, edid, female, ston, derma, voiced=True, extra=()):
    acbs = struct.pack("<I", 1 if female else 0) + bytes(12)
    subs = [(b"EDID", z(edid)), (b"ACBS", acbs), (b"RNAM", struct.pack("<I", 0x7D34)), (b"FMSI", b"\0" * 4),
            (b"STON", bytes([ston])), (b"TNAM", z("Dermaesthetic")), (b"QNAM", z(derma))] + list(extra)
    if voiced:
        subs.append((b"VTCK", b"\1\0\0\0"))
    return (b"NPC_", b"", subs, fid)


class TemplateSkinTests(unittest.TestCase):
    RECS = [sf_npc(1, "PaleMan", False, 1, "European_Male_Md1_Sk1"),
            sf_npc(2, "DarkMan", False, 8, "African_Male_Md1_Sk8"),
            sf_npc(3, "DarkManScripted", False, 8, "African_Male_md1_Sk8", extra=[(b"VMAD", b"x")]),
            sf_npc(4, "MidWoman", True, 6, "African_Female_md1_Sk6"),
            sf_npc(5, "PaleWoman", True, 0, "European_Female_md1_Sk1")]

    def test_template_skin(self):
        self.assertEqual(face_fit.template_skin(self.RECS[1][2]), (8, "african"))

    def test_pick_by_skin(self):
        pick = lambda f, skin: face_fit.pick_template(self.RECS, 0x7D34, f, None, skin=skin)[3]   # noqa: E731
        self.assertEqual(pick(False, (8, "african")), 2)                  # not the scripted one
        self.assertEqual(pick(False, (1, "european")), 1)
        self.assertEqual(pick(True, (6, "african")), 4)
        self.assertEqual(pick(True, (1, "european")), 5)
        self.assertEqual(face_fit.pick_template(self.RECS, 0x7D34, False, None)[3], 1)   # no skin: first voiced

    def test_strip_gear_and_hair_fallback(self):
        self.assertTrue({b"DOFT", b"CNTO", b"COCT"} <= set(face_fit.STRIP_GEAR))
        self.assertEqual(R.default_hair_color("RedguardRace", ["Black", "Brown"]), "Black")
        self.assertIsNone(R.default_hair_color("RedguardRace", ["Brown"]))
        self.assertIsNone(R.default_hair_color("KhajiitRace", ["Black"]))


class RaceHairTests(unittest.TestCase):
    def test_race_default_hair_only_when_none(self):
        real = {"hdpt": {0x30: {"type": 3}, 0x31: {"type": 3}, 0x12: {"type": 6}},
                "races": {0x99: ({}, {False: [0x12, 0x30], True: []})}}
        bald = {"race": 0x99, "female": False, "head_parts": [0x12]}
        self.assertEqual(face_fit.with_race_hair(bald, real)["head_parts"], [0x12, 0x30])
        own = {"race": 0x99, "female": False, "head_parts": [0x31]}
        self.assertIs(face_fit.with_race_hair(own, real), own)
        self.assertEqual(bald["head_parts"], [0x12])                        # the parsed NPC is not changed


if __name__ == "__main__":
    unittest.main()
