"""skintone: race skin tones as recoloured Starfield tone textures (2026-11-11, owner: test the Orc's skin first)."""
import os
import struct
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import skintone as S  # noqa: E402

ORC_M = [(89, 113, 92), (80, 92, 82), (83, 96, 77), (63, 72, 57), (41, 47, 36)]


class RampTests(unittest.TestCase):
    def test_ramp_light_to_dark_through_presets(self):
        r = S.tone_ramp(ORC_M)
        self.assertEqual(len(r), 9)
        self.assertEqual(r[0], (89, 113, 92))          # lightest preset first
        self.assertEqual(r[-1], (41, 47, 36))          # darkest last
        lum = [float(S._luma_lin(np.array(c))) for c in r]
        self.assertEqual(lum, sorted(lum, reverse=True))
        self.assertEqual(S.tone_ramp([(1, 2, 3)], 3), [(1, 2, 3)] * 3)


class DecodeTests(unittest.TestCase):
    def test_raw_round_trip_and_bc1(self):
        img = np.zeros((8, 8, 4), np.uint8)
        img[..., 0], img[..., 3] = np.arange(8)[None, :] * 30, 255
        self.assertTrue(np.array_equal(S.decode_dds(S.raw_dds(img)), img))
        # one BC1 block, c0 red (0xF800) > c1 blue (0x001F), all indices 0 except the last pixel (1)
        block = struct.pack("<HHI", 0xF800, 0x001F, 1 << 30)
        hdr = bytearray(S.raw_dds(np.zeros((4, 4, 4), np.uint8))[:148])
        struct.pack_into("<I", hdr, 128, 72)
        out = S.decode_dds(bytes(hdr) + block)
        self.assertEqual(out[0, 0].tolist(), [255, 0, 0, 255])
        self.assertEqual(out[3, 3].tolist(), [0, 0, 255, 255])


class RecolourTests(unittest.TestCase):
    def test_detail_kept_on_target(self):
        skin = np.zeros((4, 4, 4), np.uint8)
        skin[..., :3] = (200, 150, 130)
        skin[0, 0, :3] = (100, 75, 65)                  # a darker pore
        skin[..., 3] = 255
        out = S.recolour(skin, (89, 113, 92))
        self.assertEqual(out[1, 1, :3].tolist(), [89, 113, 92])        # the median skin becomes the target
        self.assertLess(int(out[0, 0, 1]), 113)                        # the pore stays darker
        self.assertGreater(int(out[0, 0, 1]), int(out[0, 0, 0]))       # and green
        self.assertTrue((out[..., 3] == 255).all())


def Z(t):
    return t.encode() + b"\0"


def I(v):
    return struct.pack("<I", v)


def group(fid, edid, ynam, tnam, tex):
    subs = [(b"EDID", Z(edid)), (b"MNAM", I(1)), (b"YNAM", Z(ynam)), (b"TNAM", Z(tnam)), (b"ITMC", I(len(tex)))]
    for t in tex:
        subs += [(b"LNAM", Z(t.rsplit("/", 1)[-1][:-4])), (b"VNAM", Z(t)), (b"NNAM", I(0))]
    return (b"AVMD", b"hdr", subs, fid)


def vanilla_groups():
    face = "textures/actors/human/faces/chargen/"
    return [
        group(0x163F4, "SimpleGroup_Naked_Body_Skin_Tones", "Naked_Body_Skin_Tones", "Male_Naked_Body_Skin_Tones",
              [f"textures/body/m_sk{k}.dds" for k in range(3)]),
        group(0x16404, "SimpleGroup_Female_Hands", "Female_Hands", "Female_Hands", ["textures/h/f0.dds"]),
        group(0x1F90D, "SimpleGroup_FaceSkinTones_male_eu_md1", "FaceSkinTones_male_eu_md1",
              "FaceSkinTones_male_eu_md1", [face + f"male_eu_md1_sk{k}_color.dds" for k in range(2)]),
        group(0x5405E, "SimpleGroup_FaceSkinTones_male_default", "FaceSkinTones_male_default",
              "FaceSkinTones_male_default", [face + f"male_default_sk{k}_color.dds" for k in range(2)]),
        group(0xEF95F, "SimpleGroup_FaceSkinTones_Child_Female", "FaceSkinTones_Child_Female", "x", ["c.dds"]),
        (b"AVMD", b"hdr", [(b"EDID", Z("ComplexGroup_FaceSkinTones")), (b"MNAM", I(2)), (b"YNAM", Z("FaceSkinTones")),
                           (b"TNAM", Z("FaceSkinTones")), (b"LNAM", Z("male_eu_md1")),
                           (b"VNAM", Z("FaceSkinTones_male_eu_md1")), (b"GNAM", I(0x5405E)), (b"NNAM", I(7))],
         0xC70A2),
        (b"AVMD", b"hdr", [(b"EDID", Z("Eyes_Blue"))], 0x99)]


class RelativeTests(unittest.TestCase):
    def test_relative_and_solid(self):
        px = np.zeros((1, 2, 4), np.uint8)
        px[0, 0], px[0, 1] = (240, 192, 153, 255), (200, 100, 100, 7)
        same = S.relative(px, (90, 90, 90), (90, 90, 90))
        self.assertTrue(np.array_equal(same, px))                     # race == human: unchanged
        out = S.relative(px, (89, 113, 92), (198, 176, 168))           # Orc vs human, lightest rank
        self.assertEqual(out[0, 0, :3].tolist(), [109, 124, 83])
        self.assertGreater(int(out[0, 0, 1]), int(out[0, 0, 0]))      # greener than red
        self.assertEqual(int(out[0, 1, 3]), 7)                        # alpha kept
        sol = S.solid(px, (0, 255, 0))
        self.assertEqual(sol[0, 1].tolist(), [0, 255, 0, 7])


class MedianTests(unittest.TestCase):
    def test_match_median(self):
        img = np.full((3, 3, 4), 255, np.uint8)
        img[..., :3] = (200, 150, 130)
        img[0, 0, :3] = (100, 75, 65)
        self.assertEqual(S.median_colour(img), (200, 150, 130))
        out = S.match_median(img, (90, 120, 80))
        self.assertEqual(S.median_colour(out), (90, 120, 80))
        self.assertLess(int(out[0, 0, 1]), 120)


class GroupTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(S.tone_group_kind("SimpleGroup_Female_Naked_Body_Skin_Tones"), ("body", True))
        self.assertEqual(S.tone_group_kind("SimpleGroup_Male_Hands"), ("hands", False))
        self.assertEqual(S.tone_group_kind("SimpleGroup_FaceSkinTones_female_af_md1"), ("face", True))
        self.assertEqual(S.tone_group_kind("ComplexGroup_FaceSkinTones"), ("complex", None))
        for e in ("SimpleGroup_Child_Male_Hands_Skin_Tones", "ComplexGroup_FaceSkinTones_Child",
                  "SimpleGroup_Mannequin_Body_and_Hands", "Eyes_Blue", ""):
            self.assertIsNone(S.tone_group_kind(e))

    def test_race_copies(self):
        ids = iter(range(0x01000900, 0x01000990))
        taken = {}
        recs, names, jobs, rep = S.race_tone_groups(vanilla_groups(), "S2S_Orc_", "textures/s2s/races/orc",
                                                    lambda n: taken.setdefault(n, next(ids)))
        self.assertEqual(rep["groups"], 5)                              # child group and eyes left out
        by = {S._text(dict(r[2])[b"EDID"]): r for r in recs}
        body = dict(by["S2S_Orc_SimpleGroup_Naked_Body_Skin_Tones"][2])
        self.assertEqual(S._text(body[b"TNAM"]), "S2S_Orc_Male_Naked_Body_Skin_Tones")
        vn = [S._text(d) for s, d in by["S2S_Orc_SimpleGroup_Naked_Body_Skin_Tones"][2] if s == b"VNAM"]
        self.assertEqual(vn, [f"textures/s2s/races/orc/body/male_sk{k}_color.dds" for k in range(3)])
        self.assertEqual(jobs[vn[1]], ("textures/body/m_sk1.dds", "body", False, 1))
        # every male face phenotype shares one set, made from male_default's textures
        f1 = [S._text(d) for s, d in by["S2S_Orc_SimpleGroup_FaceSkinTones_male_eu_md1"][2] if s == b"VNAM"]
        self.assertEqual(f1, ["textures/s2s/races/orc/face/male_sk0_color.dds",
                              "textures/s2s/races/orc/face/male_sk1_color.dds"])
        self.assertTrue(jobs[f1[0]][0].endswith("male_default_sk0_color.dds"))
        cx = by["S2S_Orc_ComplexGroup_FaceSkinTones"]
        d = dict(cx[2])
        self.assertEqual(S._text(d[b"YNAM"]), "S2S_Orc_FaceSkinTones")
        self.assertEqual(S._text(d[b"LNAM"]), "male_eu_md1")                         # phenotype keys kept
        self.assertEqual(S._text(d[b"VNAM"]), "S2S_Orc_FaceSkinTones_male_eu_md1")   # group names pointed at copies
        self.assertEqual(d[b"GNAM"], I(taken["S2S_Orc_SimpleGroup_FaceSkinTones_male_default"]))
        self.assertEqual(d[b"NNAM"], I(7))
        self.assertEqual(rep["complex"]["pointed_at_copies"], 2)
        race = [(b"MNAM", b""), (b"BSTT", Z("Male_Naked_Body_Skin_Tones")), (b"HSTT", Z("Male_Hands")),
                (b"FNAM", b""), (b"HSTT", Z("Female_Hands")), (b"FSTT", Z("FaceSkinTones")), (b"FULL", Z("Female_Hands"))]
        out = S.with_tone_names(race, names)
        self.assertEqual([S._text(d) for s, d in out[1:]], [
            "S2S_Orc_Male_Naked_Body_Skin_Tones", "Male_Hands", None, "S2S_Orc_Female_Hands", "S2S_Orc_FaceSkinTones",
            "Female_Hands"])                                   # Male_Hands not copied here; FULL untouched

    def test_appended_tones(self):
        """2026-11-11: SW Aliens.esm's green skins are entries appended to the vanilla groups (sk9..), not groups of
        their own; our renamed groups drew no face."""
        van = vanilla_groups()
        recs, jobs, rep = S.appended_tones(van, "textures/s2s/races/orc", count=2)
        self.assertEqual(rep["groups"], 4)                      # body, hands, 2 faces; not child / complex / eyes
        by = {r[3]: r for r in recs}
        self.assertNotIn(0xC70A2, by)
        body = by[0x163F4][2]
        self.assertEqual(body[:2], van[0][2][:2])                # same record (FormID), EDID kept
        self.assertEqual(dict(body)[b"ITMC"], I(5))
        lnams = [S._text(d) for s, d in body if s == b"LNAM"]
        self.assertEqual(lnams[3:], ["m_sk3", "m_sk4"])          # first LNAM's sk number moved on
        vn = [S._text(d) for s, d in body if s == b"VNAM"]
        self.assertEqual(vn[:3], [f"textures/body/m_sk{k}.dds" for k in range(3)])
        self.assertEqual(vn[3:], ["textures/s2s/races/orc/body/male_sk0_color.dds",
                                  "textures/s2s/races/orc/body/male_sk1_color.dds"])
        face = by[0x1F90D][2]
        self.assertEqual([S._text(d) for s, d in face if s == b"LNAM"][2:],
                         ["male_eu_md1_sk2_color", "male_eu_md1_sk3_color"])
        self.assertEqual(len([1 for s, _d in face if s == b"NNAM"]), 4)
        self.assertTrue(jobs["textures/s2s/races/orc/face/male_sk1_color.dds"][0].endswith("male_default_sk1_color.dds"))
        self.assertEqual(rep["first_index"], [1, 2, 3])

    def test_slot_colours_follow_vanilla_brightness(self):
        imgs = {k: np.full((2, 2, 4), v, np.uint8) for k, v in ((0, 90), (1, 200), (2, 40))}
        ramp = [(9, 9, 9), (5, 5, 5), (1, 1, 1)]
        self.assertEqual(S.slot_colours(imgs, ramp), {1: (9, 9, 9), 0: (5, 5, 5), 2: (1, 1, 1)})


if __name__ == "__main__":
    unittest.main()
