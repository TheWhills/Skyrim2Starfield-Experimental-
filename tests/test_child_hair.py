"""child_hair: children's own hair from their FaceGen NIF, and the child skin tone slots by lightness (2026-11-19)."""
import os
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numpy as np  # noqa: E402

import child_hair as CH  # noqa: E402
from fo4sf import nif as nifmod, skyrimhair, skyrimskin  # noqa: E402
from test_smpcloth import VERTS, hair_nif_bytes  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                 # noqa: E731


class ShapeNameTests(unittest.TestCase):
    def test_hair_part_and_its_extra_parts(self):
        hdpt = {1: {"edid": "0ChainReactionDUPLICATE001", "type": 3, "extra_parts": [2, 3]},
                2: {"edid": "0ChainReactionHLDUPLICATE001", "type": 0, "extra_parts": []},
                3: {"edid": "0_HAIRLINE_Male_Human_CurlyScalpDUPLICATE002", "type": 0, "extra_parts": [1]},
                4: {"edid": "0RCOChildEyesBlue", "type": 2, "extra_parts": []}}
        npc = {"head_parts": [4, 1]}
        self.assertEqual(CH.hair_shape_names(npc, hdpt), ["0chainreactionduplicate001",
                                                          "0chainreactionhlduplicate001",
                                                          "0_hairline_male_human_curlyscalpduplicate002"])
        self.assertEqual(CH.hair_shape_names({"head_parts": [4]}, hdpt), [])
        self.assertEqual(CH.hair_shape_names({"head_parts": [99]}, hdpt), [])

    def test_facegen_shapes_and_missing_textures(self):
        raw = hair_nif_bytes()
        got = CH.facegen_hair_shapes(raw, ["kssmp_test", "other"])
        self.assertEqual([g["name"] for g in got], ["KSSMP_Test"])
        self.assertEqual(got[0]["vertices"], len(VERTS))
        self.assertEqual(got[0]["textures"][0].lower(), "textures\\hair\\h.dds")
        self.assertEqual(CH.facegen_hair_shapes(raw, ["nothing"]), [])
        have = types.SimpleNamespace(texture=lambda p: b"dds")
        none = types.SimpleNamespace(texture=lambda p: None)
        self.assertEqual(CH.missing_textures(got, have), [])
        self.assertEqual(CH.missing_textures(got + got, none), [got[0]["textures"][0]])


class UsableShapeTests(unittest.TestCase):
    def test_layers_without_textures_left_out(self):
        """2026-11-19 (owner's run): KS Hairdos SMP lacks the scalp layer's texture; the hair is built without it,
        and not at all when the hair part's own texture is missing."""
        names = ["0chainreactionduplicate001", "0chainreactionhlduplicate001", "0_hairline_scalp"]
        shapes = [{"name": "0ChainReactionDUPLICATE001", "textures": ["textures\\ks\\chain.dds"]},
                  {"name": "0ChainReactionHLDUPLICATE001", "textures": ["textures\\ks\\chain.dds"]},
                  {"name": "0_HAIRLINE_Scalp", "textures": ["textures\\ks\\scalp.dds"]}]
        src = types.SimpleNamespace(texture=lambda p: None if "scalp" in p else b"dds")
        n, sh, left = CH.usable_shapes(names, shapes, src)
        self.assertEqual(n, names[:2])
        self.assertEqual([x["name"] for x in sh], ["0ChainReactionDUPLICATE001", "0ChainReactionHLDUPLICATE001"])
        self.assertEqual(left, {"0_HAIRLINE_Scalp": "textures\\ks\\scalp.dds"})
        src = types.SimpleNamespace(texture=lambda p: None if "chain" in p else b"dds")
        n, sh, left = CH.usable_shapes(names, shapes, src)
        self.assertEqual(sh, [])
        self.assertIn("0ChainReactionDUPLICATE001", left)
        n, sh, left = CH.usable_shapes(names, shapes[2:], types.SimpleNamespace(texture=lambda p: b"dds"))
        self.assertEqual(sh, [])


class PlacementTests(unittest.TestCase):
    def test_convert_puts_points_where_the_face_alignment_does(self):
        raw = hair_nif_bytes()
        M = np.eye(4)
        M[:3, :3] *= 0.0125
        M[:3, 3] = (0.001, 0.02, -1.4)
        head = np.eye(4)
        head[:3, 3] = (0.0, -0.01, 0.05)
        scale, offset = CH.placement(raw, M, head[:3, 3])
        h = skyrimhair.convert(raw, None, {"C_Head": head}, scale, tuple(offset))
        src = np.array(skyrimskin.skinned_shapes(nifmod.parse(raw))[0].positions, float)
        np.testing.assert_allclose(np.asarray(h.shapes[0].positions), src @ M[:3, :3].T + M[:3, 3], atol=1e-9)
        self.assertEqual({b for vw in h.shapes[0].weights for b, _w in vw}, {"C_Head"})

    def test_sky_to_starfield_from_the_alignment_and_node(self):
        node = np.eye(4)                                    # the head mesh stored turned (C_Head's frame) and moved
        node[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        node[:3, 3] = (0, 0.02, 1.2)
        fit = np.eye(4)                                     # model space: scale and shift only
        fit[:3, :3] *= 0.013
        fit[:3, 3] = (0.0, 0.01, -0.3)
        total = np.linalg.inv(node) @ fit
        k = float(np.cbrt(np.linalg.det(total[:3, :3])))
        ctx = {"model_space": True, "al": (k, total[:3, :3] / k, total[:3, 3], 0.001),
               "head": types.SimpleNamespace(model_xf=node)}
        np.testing.assert_allclose(CH.sky_to_starfield(ctx), fit, atol=1e-12)
        with self.assertRaises(ValueError):
            CH.sky_to_starfield(dict(ctx, model_space=False))
        turned = dict(ctx, al=(k, np.eye(3), total[:3, 3], 0.0))
        with self.assertRaises(ValueError):
            CH.sky_to_starfield(turned)

    def test_baked_surface_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(CH.baked_surface(d, d, "meshes/s2s/children/xhead.nif"))


def rec(t, subs, fid):
    return (t, b"", subs, fid)


class ToneSlotTests(unittest.TestCase):
    def records(self):
        race = rec(b"RACE", [(b"EDID", Z("ChildRace")), (b"BSTT", Z("Child_Male_Body")),
                             (b"BSTT", Z("Child_Female_Body")), (b"HSTT", Z("Child_Female_Hands"))], 1)
        male = rec(b"AVMD", [(b"EDID", Z("SimpleGroup_Child_Male_Body")), (b"TNAM", Z("Child_Male_Body")),
                             (b"VNAM", Z("m0.dds")), (b"VNAM", Z("m1.dds")), (b"VNAM", Z("m2.dds"))], 2)
        female = rec(b"AVMD", [(b"EDID", Z("Child_Female_Body")), (b"VNAM", Z("f0.dds")), (b"VNAM", Z("f1.dds")),
                               (b"VNAM", Z("f2.dds"))], 3)
        return [race, male, female]

    def test_slots_lightest_first(self):
        level = {"m0.dds": 120, "m1.dds": 230, "m2.dds": 60, "f0.dds": 200, "f1.dds": 100, "f2.dds": 150}
        decode = lambda key: np.full((4, 4, 4), level[key], np.uint8)       # noqa: E731
        got = CH.child_tone_slots(self.records(), lambda p: p, False, decode)
        self.assertEqual(got["slots"], [1, 0, 2])
        self.assertEqual(got["group"], "Child_Male_Body")
        got = CH.child_tone_slots(self.records(), lambda p: p, True, decode)
        self.assertEqual(got["slots"], [0, 2, 1])
        self.assertEqual(CH.tone_slot(0, [1, 0, 2]), 1)
        self.assertEqual(CH.tone_slot(2, [1, 0, 2]), 2)
        self.assertEqual(CH.tone_slot(5, [1, 0, 2]), 2)
        self.assertEqual(CH.tone_slot(1, None), 1)
        self.assertIsNone(CH.tone_slot(None, [1, 0, 2]))

    def test_face_group_without_textures_reports_its_fields(self):
        recs = self.records()
        recs[0][2].append((b"FSTT", Z("FaceSkinTones_Child")))
        recs.append(rec(b"AVMD", [(b"EDID", Z("ComplexGroup_FaceSkinTones_Child")), (b"TNAM", Z("FaceSkinTones_Child")),
                                  (b"LNAM", Z("child_default")), (b"VNAM", b"")], 4))
        with self.assertRaises(ValueError) as cm:
            CH.child_tone_slots(recs, lambda p: p, False, None, b"FSTT")
        self.assertIn(("LNAM", "child_default"), cm.exception.fields)

    def test_face_group_through_its_complex_group(self):
        """2026-11-19 (owner's run): ChildRace's FSTT names a group listing simple groups, not textures."""
        recs = self.records()
        recs[0][2].append((b"FSTT", Z("FaceSkinTones_Child")))
        recs.append(rec(b"AVMD", [(b"EDID", Z("Complex")), (b"TNAM", Z("FaceSkinTones_Child")),
                                  (b"VNAM", Z("SimpleGroup_FaceSkinTones_Child_Female"))], 4))
        recs.append(rec(b"AVMD", [(b"EDID", Z("SimpleGroup_FaceSkinTones_Child_Female")),
                                  (b"VNAM", Z("c0.dds")), (b"VNAM", Z("c1.dds")), (b"VNAM", Z("c2.dds"))], 5))
        level = {"c0.dds": 90, "c1.dds": 200, "c2.dds": 40}
        got = CH.child_tone_slots(recs, lambda p: p, False, lambda k: np.full((2, 2, 4), level[k], np.uint8), b"FSTT")
        self.assertEqual(got["slots"], [1, 0, 2])
        self.assertIn("SimpleGroup_FaceSkinTones_Child_Female", got["group"])

    def test_template_looks(self):
        import face_fit as S
        I = lambda v: struct.pack("<I", v)                                          # noqa: E731
        hd = [rec(b"HDPT", [(b"EDID", Z("Human_Child_Head_Boy")), (b"PNAM", I(1))], 0x10),
              rec(b"HDPT", [(b"EDID", Z("Child_Hair_Curly")), (b"PNAM", I(3))], 0x11)]
        kid = rec(b"NPC_", [(b"EDID", Z("Kid")), (b"PNAM", I(0x10)), (b"PNAM", I(0x11)), (b"PNAM", I(0x99)),
                            (b"HCOL", Z("Brown")), (b"STON", b"\x02")], 5)
        got = S.child_template_looks(kid, hd)
        self.assertEqual(got, {"ston": 2, "hair_color": "Brown",
                               "head_parts": ["Human_Child_Head_Boy (1)", "Child_Hair_Curly (3)", "00000099 (None)"],
                               "face_layers": [], "face_fields": [],
                               "all_fields": ["EDID", "HCOL", "PNAM", "STON"]})
        kid[2].extend([(b"TNAM", Z("ChildFace")), (b"QNAM", Z("Child_Skin_03")), (b"INTV", I(50))])
        self.assertEqual(S.child_template_looks(kid, hd)["face_layers"], ["ChildFace: Child_Skin_03 (50)"])
        self.assertEqual(S.child_template_looks(kid, hd)["face_fields"], ["QNAM", "TNAM"])
        A = lambda f: (b"ACBS", I(1 if f else 0) + bytes(12))                       # noqa: E731
        npcs = [rec(b"NPC_", [(b"EDID", Z("NGP_KidSarah")), A(True), (b"RNAM", I(0x77)), (b"TPLT", I(5))], 6),
                rec(b"NPC_", [(b"EDID", Z("Kid")), A(False), (b"RNAM", I(0x77)), (b"VTCK", I(1)),
                              (b"PNAM", I(0x10))], 5),
                rec(b"NPC_", [(b"EDID", Z("Adult")), A(False), (b"RNAM", I(0x78))], 7)]
        got = S.child_npc_survey(npcs, 0x77, hd)
        self.assertEqual([(g["edid"], g["female"], g["template"], g["voiced"]) for g in got],
                         [("Kid", False, None, True), ("NGP_KidSarah", True, "Kid", False)])
        self.assertEqual(got[0]["head_parts"], ["Human_Child_Head_Boy (1)"])

    def test_missing_pieces(self):
        recs = self.records()
        with self.assertRaises(KeyError):
            CH.child_tone_slots(recs[1:], lambda p: p, False, None)
        with self.assertRaises(KeyError):
            CH.child_tone_slots(recs[:1], lambda p: p, False, None)


class EyeColourTests(unittest.TestCase):
    def test_skyrim_eye_colour(self):
        """A child's Starfield eye colour from its Skyrim eyes head part, as the adults' (2026-11-19: Frodnar's
        Realistic RS eyes 0RCOChildEyesBlue; he came out brown)."""
        import face_fit as S
        real = {"hdpt": {1: {"edid": "0RCOChildEyesBlue", "type": 2}, 2: {"edid": "EyesHumanBrown", "type": 2},
                         3: {"edid": "Brows", "type": 6}},
                "races": {"NordRaceChild": ({}, {False: [2], True: [2]})}}
        got = S.skyrim_eye_colour({"race": "NordRaceChild", "head_parts": [3, 1], "female": False}, real)
        self.assertEqual(got[0], "Blue")
        self.assertEqual(got[1]["from"], "own")
        got = S.skyrim_eye_colour({"race": "NordRaceChild", "head_parts": [3], "female": False}, real)
        self.assertEqual((got[0], got[1]["from"]), ("Brown", "race default"))


class HairPrealignTests(unittest.TestCase):
    def test_hair_follows_the_face_shape(self):
        """build_child_hair places the hair with the face shape's prealign move after the face alignment."""
        seen = {}

        def fake_placement(fg, M, head_t, shift=None):
            seen["M"] = M
            raise RuntimeError("stop")
        P = np.eye(4)
        P[:3, :3] *= 1.09
        P[2, 3] = -0.148
        M0 = np.eye(4)
        M0[:3, :3] *= 0.0142
        with mock.patch.object(CH, "sky_to_starfield", lambda ctx: M0), \
                mock.patch.object(CH, "placement", fake_placement):
            for pre, want in ((None, M0), (P.tolist(), P @ M0)):
                with self.assertRaises(RuntimeError):
                    CH.build_child_hair("Frodnar", False, b"", "x.nif", [], {}, None,
                                        {CH_SF_HEAD(): np.eye(4)}, None, None, None, "st", types.SimpleNamespace(),
                                        pre)
                np.testing.assert_allclose(seen["M"], want)


class HairLiftTests(unittest.TestCase):
    def test_hair_lift_matrix(self):
        """The hair is lifted with the forehead (capped), never scaled."""
        import face_fit as S
        row = lambda lift: {"child": {"shape": {"prealign": {"hair_lift_m": lift, "scale": 1.11}}}}   # noqa: E731
        m = S.hair_lift_matrix(row(0.0076))
        np.testing.assert_allclose(m[:3, :3], np.eye(3))
        self.assertAlmostEqual(m[2, 3], 0.0076)
        self.assertAlmostEqual(S.hair_lift_matrix(row(0.016))[2, 3], S.HAIR_LIFT_MAX)
        self.assertIsNone(S.hair_lift_matrix({"child": {}}))
        self.assertIsNone(S.hair_lift_matrix(row(None)))


def CH_SF_HEAD():
    from fo4sf import skyrimhair
    return skyrimhair.SF_HEAD


class LightToneTests(unittest.TestCase):
    def test_skin_median_skips_grey(self):
        """The grey background / underwear of a body tone texture does not count as skin."""
        img = np.zeros((8, 8, 4), np.uint8)
        img[...] = (120, 120, 120, 255)                 # grey
        img[:3] = (220, 170, 150, 255)                  # skin
        self.assertEqual(CH.skin_median(img), (220, 170, 150))
        out = CH.recolour_skin(img, (200, 160, 150))
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(CH.skin_median(out), (200, 160, 150))))
        self.assertEqual(int(out[0, 0, 3]), 255)

    def test_appended_entry(self):
        subs = [(b"EDID", Z("G")), (b"ITMC", struct.pack("<I", 2)), (b"LNAM", Z("a")), (b"VNAM", Z("a.dds")),
                (b"NNAM", b"\x07\0\0\0"), (b"LNAM", Z("b")), (b"VNAM", Z("b.dds")), (b"NNAM", b"\x07\0\0\0"),
                (b"XXXX", b"tail")]
        out = CH.with_appended_entry(subs, "new", "n.dds", 3)
        self.assertEqual([d for s_, d in out if s_ == b"VNAM"], [Z("a.dds"), Z("b.dds"), Z("b.dds"), Z("n.dds")])
        self.assertEqual([d for s_, d in out if s_ == b"LNAM"][-1], Z("new"))
        self.assertEqual(dict(out)[b"ITMC"], struct.pack("<I", 4))
        self.assertEqual(out[-1], (b"XXXX", b"tail"))
        self.assertEqual(len([1 for s_, _d in out if s_ == b"NNAM"]), 4)
        with self.assertRaises(ValueError):
            CH.with_appended_entry(subs, "x", "x.dds", 1)

    def test_light_child_tone(self):
        """A 4th child tone: the lightest body with the lightest face recoloured to that body's skin."""
        race = rec(b"RACE", [(b"EDID", Z("ChildRace")), (b"BSTT", Z("Child_Male_Body")),
                             (b"BSTT", Z("Child_Female_Body")), (b"FSTT", Z("FaceSkinTones_Child"))], 1)
        mb = rec(b"AVMD", [(b"EDID", Z("Child_Male_Body")), (b"VNAM", Z("textures/b0.dds")),
                           (b"VNAM", Z("textures/b1.dds")), (b"VNAM", Z("textures/b2.dds"))], 2)
        fb = rec(b"AVMD", [(b"EDID", Z("Child_Female_Body")), (b"VNAM", Z("textures/b0.dds")),
                           (b"VNAM", Z("textures/b1.dds")), (b"VNAM", Z("textures/b2.dds"))], 3)
        cx = rec(b"AVMD", [(b"EDID", Z("Complex")), (b"TNAM", Z("FaceSkinTones_Child")),
                           (b"VNAM", Z("SimpleGroup_Face_Child_Male")), (b"VNAM", Z("SimpleGroup_Face_Child_Female"))], 4)
        fm = rec(b"AVMD", [(b"EDID", Z("SimpleGroup_Face_Child_Male")), (b"VNAM", Z("textures/f0.dds")),
                           (b"VNAM", Z("textures/f1.dds")), (b"VNAM", Z("textures/f2.dds"))], 5)
        ff = rec(b"AVMD", [(b"EDID", Z("SimpleGroup_Face_Child_Female")), (b"VNAM", Z("textures/f0.dds")),
                           (b"VNAM", Z("textures/f1.dds")), (b"VNAM", Z("textures/f2.dds"))], 6)
        col = {"textures/b0.dds": (139, 109, 82), "textures/b1.dds": (210, 170, 160), "textures/b2.dds": (79, 65, 49),
               "textures/f0.dds": (189, 143, 115), "textures/f1.dds": (172, 126, 98), "textures/f2.dds": (106, 74, 57)}

        def decode(p):
            img = np.zeros((4, 4, 4), np.uint8)
            img[...] = col[p] + (255,)
            img[0] = (128, 128, 128, 255)                 # grey patch
            return img
        got = CH.light_child_tone([race, mb, fb, cx, fm, ff], lambda p: p, decode)
        self.assertEqual(got["index"], 3)
        labels = [lab for lab, _lv in CH.FACE_LEVELS]
        self.assertEqual(got["indices"], {lab: 3 + k for k, lab in enumerate(labels)})
        by = {r[3]: r[2] for r in got["records"]}
        self.assertEqual(sorted(by), [2, 3, 5, 6])
        body_v = [d for s_, d in by[2] if s_ == b"VNAM"]
        self.assertEqual(body_v[3:], [Z("textures/b1.dds")] * len(labels))           # lightest body each time
        face_v = [d for s_, d in by[5] if s_ == b"VNAM"]
        self.assertEqual(face_v[3:], [Z(f"textures/s2s/children/tones/male_face_{lab.lower()}_color.dds")
                                      for lab in labels])
        self.assertEqual(dict(by[5]).get(b"ITMC"), None)
        meds = []
        for lab, lv in CH.FACE_LEVELS:
            face = got["textures"][f"s2s/children/tones/male_face_{lab.lower()}_color.dds"]
            want = CH.face_level_target((210, 170, 160), lv)
            self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(CH.skin_median(face), want)))
            meds.append(sum(CH.skin_median(face)))
        self.assertEqual(meds, sorted(meds))                                         # lighter level by level
        self.assertEqual(got["report"]["male_fstt"]["body_skin"], [210, 170, 160])
        t = CH.face_level_target((172, 125, 95), 1.7)
        self.assertTrue(t[0] > 172 and t[2] - 95 > t[0] - 172)          # lighter and less orange than the body
        # one more tone per painted child, after the levels: its own face, the lightest body
        seen = []

        def paint(edid, face):
            seen.append((edid, face.shape))
            return np.full_like(face, 77)
        got = CH.light_child_tone([race, mb, fb, cx, fm, ff], lambda p: p, decode,
                                  children=[("Frodnar", False), ("Dorthe", True)], paint=paint)
        n = 3 + len(CH.FACE_LEVELS)
        self.assertEqual(got["children"], {"Frodnar": n, "Dorthe": n + 1})
        self.assertEqual([e for e, _s in seen], ["Frodnar", "Dorthe"])
        by = {r[3]: r[2] for r in got["records"]}
        mface = [d for s_, d in by[5] if s_ == b"VNAM"]
        self.assertEqual(mface[n], Z("textures/s2s/children/tones/frodnar_face_color.dds"))
        self.assertEqual(len(mface), n + 1)                             # the male group stops at Frodnar's
        fface = [d for s_, d in by[6] if s_ == b"VNAM"]
        self.assertEqual(fface[n + 1], Z("textures/s2s/children/tones/dorthe_face_color.dds"))
        self.assertEqual(len(fface), n + 2)                             # padded at Frodnar's index
        self.assertEqual([d for s_, d in by[2] if s_ == b"VNAM"][n],
                         Z("textures/s2s/children/tones/frodnar_bstt_color.dds"))        # its own tanned body
        face = got["textures"]["s2s/children/tones/frodnar_face_color.dds"]
        np.testing.assert_array_equal(face, CH.tanned(np.full_like(face, 77)))
        body = got["textures"]["s2s/children/tones/frodnar_bstt_color.dds"]
        self.assertLess(int(body[1, 1, 2]), int(decode("textures/b1.dds")[1, 1, 2]))     # tanned: less blue
        got = CH.light_child_tone([race, mb, fb, cx, fm, ff], lambda p: p, decode, children=[("Frodnar", False)],
                                  paint=paint, tan=None)
        by = {r[3]: r[2] for r in got["records"]}
        self.assertEqual([d for s_, d in by[2] if s_ == b"VNAM"][n], Z("textures/b1.dds"))
        self.assertTrue((got["textures"]["s2s/children/tones/frodnar_face_color.dds"] == 77).all())
        got = CH.light_child_tone([race, mb, fb, cx, fm, ff], lambda p: p, decode,
                                  children=[("Frodnar", False)], paint=lambda e, f: (_ for _ in ()).throw(KeyError("x")))
        self.assertEqual(got["children"], {})
        self.assertIn("none", got["report"]["children"]["Frodnar"])
        with self.assertRaises(KeyError):
            CH.light_child_tone([race, mb, fb], lambda p: p, decode)


class LightToneWiringTests(unittest.TestCase):
    def test_add_child_light_tone(self):
        """face_fit writes the light tone's face texture and adds its AVMD overrides to the plugin's records."""
        import face_fit as S
        import skin_tone_probe
        img = np.full((4, 4, 4), 200, np.uint8)
        fake = {"index": 3, "indices": {lab: 3 + k for k, (lab, _l) in enumerate(CH.FACE_LEVELS)},
                "records": [(b"AVMD", b"", [(b"EDID", Z("G"))], 5)],
                "textures": {"s2s/children/tones/male_face_light_color.dds": img}, "report": {"male_bstt": {}}}
        recs = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(CH, "light_child_tone", lambda *a, **k: fake), \
                mock.patch.object(S.sfplugin, "records", lambda *a: []), \
                mock.patch.object(skin_tone_probe, "TextureArchives", lambda sf: types.SimpleNamespace(read=None)):
            got = S.add_child_light_tone("sf.esm", "data", d, recs)
            self.assertTrue(os.path.isfile(os.path.join(d, "textures", "s2s", "children", "tones",
                                                        "male_face_light_color.dds")))
        self.assertEqual(got["index"], 3 + CH.FACE_MAIN)                        # the main level's STON
        self.assertEqual(recs, fake["records"])
        with mock.patch.object(CH, "light_child_tone", mock.Mock(side_effect=KeyError("x"))), \
                mock.patch.object(S.sfplugin, "records", lambda *a: []), \
                mock.patch.object(skin_tone_probe, "TextureArchives", lambda sf: types.SimpleNamespace(read=None)):
            self.assertIn("error", S.add_child_light_tone("sf.esm", "data", "out", []))


class ControlTests(unittest.TestCase):
    def test_child_controls(self):
        import face_fit as S
        from fo4sf import sfplugin
        I = lambda v: struct.pack("<I", v)                                          # noqa: E731
        subs = [(b"EDID", Z("S2SFace_Frodnar")), (b"PNAM", I(0x01000805)), (b"PNAM", I(0x01000806)),
                (b"STON", b"\x01")]
        recs = [(b"HDPT", b"", [], 0x01000805), (b"NPC_", b"", subs, 0x01000807)]
        rows = [{"edid": "Frodnar", "name": "Frodnar", "child": {"files": []}, "test_npc": {"head_part": "01000805"}},
                {"edid": "Ysolda", "test_npc": {"head_part": "01000805"}}]
        S.add_child_controls(rows, recs, {"Frodnar": 1, "Ysolda": 1}, ["Starfield.esm"])
        self.assertEqual(sorted(rows[0]["control_npcs"]), sorted(S.CHILD_CONTROLS))
        self.assertNotIn("control_npcs", rows[1])
        got = {sfplugin.edid(r[2]): r[2] for r in recs[2:]}
        van = got["S2SFaceControl_Frodnar_VanillaHead"]
        self.assertEqual([d for s_, d in van if s_ == b"PNAM"], [I(0x01000806)])
        self.assertEqual(dict(van)[b"STON"], b"\x01")
        self.assertEqual(dict(got["S2SFaceControl_Frodnar_Tone2"])[b"STON"], b"\x02")
        self.assertEqual(len([d for s_, d in got["S2SFaceControl_Frodnar_Tone0"] if s_ == b"PNAM"]), 2)
        self.assertEqual(dict(got["S2SFaceControl_Frodnar_Tone0"])[b"FULL"], Z("Frodnar (Tone0)"))
        names = ["European_Male_Md1_Sk1", "European_Male_yo1_Sk3", "European_Male_yo1_Sk0", "African_Male_yo1_Sk0",
                 "European_Female_md1_Sk2", "European_Male_yo1_Sk10"]
        self.assertEqual(S.child_skin_choices(names, False), ["European_Male_yo1_Sk0", "European_Male_yo1_Sk3",
                                                              "European_Male_yo1_Sk10"])
        self.assertEqual(S.child_skin_choices(names, True), ["European_Female_md1_Sk2"])
        recs2 = [(b"NPC_", b"", [(b"TNAM", Z("Dermaesthetic")), (b"QNAM", Z("European_Male_Md1_Sk1")),
                                 (b"TNAM", Z("Scars")), (b"QNAM", Z("Scar_X"))], 9)]
        self.assertEqual(S.derma_names(recs2), ["European_Male_Md1_Sk1"])
        self.assertEqual([fo for s_, fo in S.with_derma(recs2[0][2], "European_Male_yo1_Sk0") if s_ == b"QNAM"],
                         [Z("European_Male_yo1_Sk0"), Z("Scar_X")])
        subs2 = [(b"EDID", Z("S2SFace_Frodnar")), (b"PNAM", I(0x01000805)), (b"TNAM", Z("Dermaesthetic")),
                 (b"QNAM", Z("European_Male_Md1_Sk1")), (b"STON", b"\x01")]
        recs3 = [(b"HDPT", b"", [], 0x01000805), (b"NPC_", b"", subs2, 0x01000807)]
        rows3 = [{"edid": "Frodnar", "female": False, "child": {"files": []}, "test_npc": {"head_part": "01000805"}}]
        S.add_child_controls(rows3, recs3, {"Frodnar": 1}, ["Starfield.esm"], {False: ["European_Male_yo1_Sk0"]})
        self.assertIn("Skin_European_Male_yo1_Sk0", rows3[0]["control_npcs"])
        sk = next(r for r in recs3 if sfplugin.edid(r[2]) == "S2SFaceControl_Frodnar_Skin_European_Male_yo1_Sk0")
        self.assertEqual(dict(sk[2])[b"QNAM"], Z("European_Male_yo1_Sk0"))


class ToneControlTests(unittest.TestCase):
    def test_face_strength_copies(self):
        """With the light tones: only copies at the other face strengths, for children on the main one."""
        import face_fit as S
        from fo4sf import sfplugin
        I = lambda v: struct.pack("<I", v)                                          # noqa: E731
        subs = [(b"EDID", Z("S2SFace_Frodnar")), (b"PNAM", I(0x01000805)), (b"STON", b"\x04")]
        recs = [(b"HDPT", b"", [], 0x01000805), (b"NPC_", b"", subs, 0x01000807), (b"NPC_", b"", subs, 0x01000808)]
        rows = [{"edid": "Frodnar", "female": False, "child": {"files": []}, "test_npc": {"head_part": "01000805", "ston": 4}},
                {"edid": "Dark", "female": False, "child": {"files": []}, "test_npc": {"head_part": "01000805", "ston": 2}}]
        S.add_child_controls(rows, recs, {"Frodnar": 1, "Dark": 2}, ["Starfield.esm"], None,
                             {"Face13": 3, "Face17": 4, "Face22": 5})
        self.assertEqual(sorted(rows[0]["control_npcs"]), ["Face13", "Face22"])
        self.assertNotIn("control_npcs", rows[1])
        got = {sfplugin.edid(r[2]): dict(r[2]) for r in recs[3:]}
        self.assertEqual(got["S2SFaceControl_Frodnar_Face13"][b"STON"], b"\x03")
        self.assertEqual(got["S2SFaceControl_Frodnar_Face22"][b"STON"], b"\x05")
        self.assertEqual(len(recs), 5)


class PreviewTests(unittest.TestCase):
    def test_child_preview(self):
        """--preview for a child: a PNG sheet (FaceGen / Starfield / ours) and an .npz of the shapes."""
        import face_fit as S
        from fo4sf import facepreview
        g = np.linspace(-1, 1, 6)
        sf = np.array([(x, 0.05 * np.cos(x) + 0.05 * np.cos(z), z) for x in g for z in g]) * 0.1
        tris = [(i * 6 + j, i * 6 + j + 1, (i + 1) * 6 + j) for i in range(5) for j in range(5)]
        sky = sf / 0.0125
        ctx = {"head": types.SimpleNamespace(vertices=sf, triangles=np.array(tris), model_xf=np.eye(4)),
               "al": (0.0125, np.eye(3), np.zeros(3), 0.0), "model_space": True, "base": sky,
               "base_tris": np.array(tris)}
        disp = np.zeros_like(sf)
        disp[14] = (0, 0.01, 0)
        with tempfile.TemporaryDirectory() as d:
            got = S.child_preview("Kid", ctx, sky * 1.02, disp, d, {})
            self.assertTrue(os.path.getsize(got["png"]) > 0)
            z = np.load(got["npz"])
            self.assertEqual(z["sf_local"].shape, sf.shape)
            self.assertAlmostEqual(float(z["al_s"]), 0.0125)
            self.assertEqual(int(np.argmax(np.linalg.norm(z["disp"], axis=1))), 14)
        a = types.SimpleNamespace(preview=False, preview_npc=["frodnar"])
        self.assertTrue(S.previewing(a, {"edid": "Frodnar"}))
        self.assertFalse(S.previewing(a, {"edid": "Dorthe"}))
        self.assertTrue(S.previewing(types.SimpleNamespace(preview=True, preview_npc=[]), {"edid": "Dorthe"}))
        img = facepreview.render(sf, tris, 64, 0, ((-0.12, 0.12), (-0.12, 0.12)))
        self.assertEqual(img.shape, (64, 64, 3))
        self.assertLess(int(img.min()), 235)                 # something drawn


class BakedFaceTests(unittest.TestCase):
    def test_child_baked_face(self):
        """A child's test NPC gets its baked face as an adult test NPC does: the European template nearest its adult
        skin tone, recoloured (human_face_colour) only when the template's tone is far from it."""
        import face_fit as S
        tpl = (b"NPC_", b"", [(b"EDID", Z("YoungEuro")), (b"STON", b"\x02"), (b"TNAM", Z("Dermaesthetic")),
                              (b"QNAM", Z("European_Male_yo1_Sk2"))], 0x123)
        row = {"edid": "Frodnar", "female": False, "test_npc": {"form_id": "0A000814", "ston": 1}}
        seen = {}

        def write(index, tpl_fid, new_fid, data_dir, out, plugin=None, colour=None):
            seen.update(tpl=tpl_fid, new=new_fid, colour=colour)
            return [os.path.join(out, "x", "00000814_color.dds")]
        asked = []

        def hfc(tpl_subs, ston, female, read):
            asked.append((ston, female))
            return (None, None) if ston == 2 else ("conv", {"ston": ston})
        with mock.patch.object(S, "pick_template", lambda *a, **k: tpl), \
                mock.patch.object(S, "write_baked_face", write), \
                mock.patch.object(S, "human_face_colour", hfc), \
                mock.patch.object(S, "target_skin", lambda n, npcs, real: (2, "european")):
            got = S.child_baked_face(row, {}, {}, {}, [tpl], 0x3CDB, {0x123: {}}, "sf", "out", read=lambda p: b"")
            self.assertEqual(got["template"], "YoungEuro")
            self.assertEqual(got["adult_ston"], 2)
            self.assertIn("no", got["recoloured"])              # the template's own face, as for adults
            self.assertIsNone(seen["colour"])
            self.assertEqual(asked, [(2, False)])
            self.assertEqual((seen["tpl"], seen["new"]), (0x123, 0x0A000814))
        with mock.patch.object(S, "pick_template", lambda *a, **k: tpl), \
                mock.patch.object(S, "write_baked_face", write), \
                mock.patch.object(S, "human_face_colour", hfc), \
                mock.patch.object(S, "target_skin", lambda n, npcs, real: (6, "european")):
            got = S.child_baked_face(row, {}, {}, {}, [tpl], 0x3CDB, {0x123: {}}, "sf", "out", read=lambda p: b"",
                                     fid=0x0A000900)
            self.assertEqual(got["recoloured"], {"ston": 6})
            self.assertEqual((seen["colour"], seen["new"]), ("conv", 0x0A000900))
        with mock.patch.object(S, "pick_template", lambda *a, **k: None), \
                mock.patch.object(S, "target_skin", lambda n, npcs, real: (2, "european")):
            self.assertIn("none", S.child_baked_face(row, {}, {}, {}, [], 0x3CDB, {}, "sf", "out"))


class BuildPartFilterTests(unittest.TestCase):
    def test_keep_shapes(self):
        import skyrim_hairs as SH
        raw = hair_nif_bytes()
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        ctx = CH.shape_settings("")
        ctx.head_scale, ctx.head_offset = skyrimhair.HEAD_SCALE, skyrimhair.HEAD_OFFSET
        ctx.head_surface = ctx.sky_head = ctx.vanilla_profile = ctx.vanilla_crown = None
        src = CH._OneMesh(raw)
        with tempfile.TemporaryDirectory() as d:
            row = SH.build_part({"edid": "X"}, ["fg.nif"], src, None, {"C_Head": head}, ctx, None, d,
                                keep_shapes=["nothing"])
            self.assertFalse(row["ok"])
            self.assertIn("no shape named nothing", row["skipped"][0])
            seen = {}

            def mats(conv, nifs, hair, a, **kw):
                seen["shapes"] = [s.name for s in hair.shapes]
                return [None] * len(hair.shapes), [False] * len(hair.shapes)
            with mock.patch("hair_pack.hair_materials", mats):
                row = SH.build_part({"edid": "Y"}, ["fg.nif"], src, None, {"C_Head": head}, ctx, None, d,
                                    keep_shapes=["KSSMP_TEST"])
            self.assertEqual(seen["shapes"], [b"KSSMP_Test"])
            self.assertEqual(row["reason"], "a shape has no material")


class FaceFitWiringTests(unittest.TestCase):
    def test_add_child_hair_files(self):
        """face_fit.add_child_hair_files: the child's test NPC gets a hair head part of ours (copied from its
        template's hair) in place of the template's, with its matched hair colour; a child whose textures are missing
        keeps the template's hair, reported."""
        import face_fit as S
        from fo4sf import sfplugin
        I = lambda v: struct.pack("<I", v)                                          # noqa: E731
        h = struct.pack("<4sIII", b"HDPT", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
        sf_parts = [(b"HDPT", h, [(b"EDID", Z("Child_Hair_Curly")), (b"MODL", Z("Actors\\Child\\Hair\\Curly.nif")),
                                  (b"PNAM", I(3)), (b"HNAM", I(0x55)), (b"DATA", b"\x02")], 0x500),
                    (b"HDPT", h, [(b"EDID", Z("Human_Child_Head_Boy")), (b"PNAM", I(1))], 0x501)]
        hdpt = {0x10: {"edid": "0ChainReactionDUPLICATE001", "type": 3, "extra_parts": []}}
        kid = {"edid": "Frodnar", "form_id": 0x1347E, "female": False, "head_parts": [0x10], "hair_color": 0x77}
        kid2 = dict(kid, edid="Dorthe", form_id=0x13477)
        npc_subs = [(b"EDID", Z("S2SFace_Frodnar")), (b"PNAM", I(0x501)), (b"PNAM", I(0x500)), (b"HCOL", Z("Brown"))]
        recs = [(b"HDPT", h, [], 0x01000800), (b"NPC_", h, list(npc_subs), 0x01000801),
                (b"NPC_", h, list(npc_subs), 0x01000802)]
        rows = [{"edid": "Frodnar", "female": False, "test_npc": {"form_id": "x"},
                 "child": {"files": ["meshes/s2s/children/frodnarhead.nif"]}},
                {"edid": "Dorthe", "female": False, "test_npc": {"form_id": "y"}, "child": {"files": []}},
                {"edid": "Ysolda", "female": True, "test_npc": {"form_id": "z"}}]
        real = {"clfm": {0x77: {"edid": "HairColorBlond", "rgba": (200, 170, 100, 0)}}, "names": {"Blonde"},
                "palette": None, "with_hair_color": lambda subs, n: sfplugin.edit(subs, {b"HCOL": Z(n)})}
        textures = {"Frodnar": "ok", "Dorthe": None}

        class Sky:
            def texture(self, p):
                return b"dds" if "ok" in p else None

        def shapes(fg, names):
            return [{"name": names[0], "vertices": 3, "textures": [f"textures\\{fg.decode()}.dds"]}]
        with tempfile.TemporaryDirectory() as tmp:
            sf = os.path.join(tmp, "sf")
            os.makedirs(os.path.join(sf, "Data"))
            with open(os.path.join(sf, "Data", "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build(sf_parts, {"hedr_version": 0.96, "form_version": 555}, masters=()))
            cr = os.path.join(tmp, "cr.zip")
            open(cr, "wb").close()
            a = types.SimpleNamespace(starfield=sf, texconv="t.exe", content_resources=cr, archive2=None,
                                      load_order=None)
            head = np.eye(4)
            built = []

            def build(edid, *args, **kw):
                built.append(edid)
                return {"ok": True, "model": f"s2s\\children\\hair\\{edid.lower()}.nif", "shapes": 1}
            with mock.patch.object(S.hkx_to_af, "vanilla_file", lambda p, d: (b"skel", p)), \
                    mock.patch.object(S.hkx_to_af, "read_any",
                                      lambda p, s=None: (textures["Frodnar" if "1347E" in p.upper() else "Dorthe"]
                                                         or "missing").encode()), \
                    mock.patch.object(S, "facegen_mesh", lambda lo, fid: f"facegeom\\{fid:08X}.nif"), \
                    mock.patch.object(S, "child_context", lambda *x, **k: {"ctx": 1}), \
                    mock.patch("child_faces.facegen_points", lambda *x: np.zeros((3, 3))), \
                    mock.patch.object(CH, "child_world", lambda b: {"C_Head": head}), \
                    mock.patch.object(CH, "facegen_hair_shapes", shapes), \
                    mock.patch.object(CH, "baked_surface", lambda *x: None), \
                    mock.patch.object(CH, "build_child_hair", build), \
                    mock.patch("hair_pack.facebones_template", lambda *x: None), \
                    mock.patch("hair_pack.pack", lambda *x: {"archives": ["m"]}), \
                    mock.patch("npc_records.match_hair_color", lambda c, n, p: ("Blonde", "nearest")), \
                    mock.patch("fo4sf.skyrimconvert.SkyrimConverter",
                               lambda *x, **k: types.SimpleNamespace(stats={}, material_errors=[])):
                res = S.add_child_hair_files(a, tmp, Sky(), os.path.join(sf, "Data"), rows,
                                             {"frodnar": kid, "dorthe": kid2}, recs,
                                             {"Frodnar": 1, "Dorthe": 2, "Ysolda": 0}, ["Starfield.esm"], real,
                                             {"_sky": (None, hdpt)})
        self.assertEqual(built, ["Frodnar"])
        self.assertEqual(res["children_with_own_hair"], 1)
        new = recs[-1]
        self.assertEqual(sfplugin.edid(new[2]), "S2S_ChildHair_Frodnar")
        self.assertEqual(dict(new[2])[b"MODL"], Z("s2s\\children\\hair\\frodnar.nif"))
        self.assertNotIn(b"HNAM", dict(new[2]))
        pn = [struct.unpack("<I", d)[0] for s, d in recs[1][2] if s == b"PNAM"]
        self.assertEqual(pn, [0x501, new[3]])
        self.assertEqual(dict(recs[1][2])[b"HCOL"], Z("Blonde"))
        self.assertEqual(rows[0]["hair"]["hair_color"]["starfield"], "Blonde")
        self.assertIn("KS Hairdos", rows[1]["hair"]["error"])
        self.assertEqual(recs[2][2], npc_subs)
        self.assertNotIn("hair", rows[2])


    def test_skin_frame_shift(self):
        """Hair shapes that read far from their head (vanilla FaceGen: 120 units low) take their bone route's shift;
        ones on the head (Realistic RS Children) none."""
        from fo4sf import facefit, skyrimhair, skyrimskin
        pos = [(0.0, 0.0, 8.0), (1.0, 0.0, 9.0), (-1.0, 0.0, 9.0)]
        shape = types.SimpleNamespace(name=b"HairX", positions=pos)
        up = np.eye(4)
        up[2, 3] = 120.0
        with mock.patch("fo4sf.nif.parse", lambda b: "nif"), \
                mock.patch.object(skyrimskin, "skinned_shapes", lambda n: [shape]), \
                mock.patch.object(skyrimhair, "skin_to_model", lambda s: ((lambda v: np.asarray(v, float)), None)), \
                mock.patch.object(facefit, "skyrim_model_matrix", lambda n, s: up):
            shift, rep = CH.skin_frame_shift(b"x", ["hairx"], np.array([[0, 0, 121.0], [0, 0, 131.0]]))
            np.testing.assert_allclose(shift, [0, 0, 120.0])
            shift, rep = CH.skin_frame_shift(b"x", ["hairx"], np.array([[0, 0, 0.0], [0, 0, 10.0]]))
            np.testing.assert_allclose(shift, 0.0)                                         # already on its head
            shift, _r = CH.skin_frame_shift(b"x", ["hairx"], None)
            np.testing.assert_allclose(shift, 0.0)
        # placement adds the shift through M's scale
        with mock.patch("fo4sf.nif.parse", lambda b: "nif"), \
                mock.patch.object(skyrimhair, "node_worlds", lambda n: ({}, {})), \
                mock.patch.object(skyrimhair, "head_anchor", lambda n, nodes: np.eye(4)):
            M = np.diag([0.01, 0.01, 0.01, 1.0])
            _s, off0 = CH.placement(b"x", M, np.zeros(3))
            _s, off1 = CH.placement(b"x", M, np.zeros(3), np.array([0, 0, 120.0]))
            np.testing.assert_allclose(off1 - off0, [0, 0, 1.2])

if __name__ == "__main__":
    unittest.main()
