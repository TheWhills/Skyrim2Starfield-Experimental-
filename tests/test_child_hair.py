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
                               "face_layers": [], "face_fields": []})
        kid[2].extend([(b"TNAM", Z("ChildFace")), (b"QNAM", Z("Child_Skin_03")), (b"INTV", I(50))])
        self.assertEqual(S.child_template_looks(kid, hd)["face_layers"], ["ChildFace: Child_Skin_03 (50)"])
        self.assertEqual(S.child_template_looks(kid, hd)["face_fields"], ["QNAM", "TNAM"])

    def test_missing_pieces(self):
        recs = self.records()
        with self.assertRaises(KeyError):
            CH.child_tone_slots(recs[1:], lambda p: p, False, None)
        with self.assertRaises(KeyError):
            CH.child_tone_slots(recs[:1], lambda p: p, False, None)


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


if __name__ == "__main__":
    unittest.main()
