"""Starfield hair-shader materials for converted Skyrim hair (convert_material.build_hair_mat, the converter's hair
branch, hair_pack's choice), on synthetic data. Layout checked against the game's own hair material format as read
from IDG Elegant Hair Collection (2026-11-02): Hair1Layer, HairSettingsComponent, slots 0 / 2 / 5 / 12 / 20."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts", "armor"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from fo4sf import convert_material as cm  # noqa: E402
from fo4sf import pipeline, skyrimconvert, skyrimhair, textures  # noqa: E402


class HairMaterialTests(unittest.TestCase):
    def test_layout(self):
        files = {"Albedo": "Data\\Textures\\s2s\\a_color.dds", "Opacity": "Data\\Textures\\s2s\\a_opacity.dds",
                 "AmbientOcclusion": "Data\\Textures\\s2s\\_hair_ao.dds", "DepthOffset": "Data\\Textures\\s2s\\z.dds",
                 "HairID": "Data\\Textures\\s2s\\id.dds"}
        mat = cm.build_hair_mat("S2SHair_anna", files)
        objs = mat["Objects"]
        self.assertEqual([o["Parent"].split("\\")[-1] for o in objs],
                         ["LayeredMaterials.mat", "Layers.mat", "Materials.mat", "TextureSets.mat", "UVStreams.mat"])
        root = {c["Type"]: c["Data"] for c in objs[0]["Components"]}
        self.assertEqual(root["BSMaterial::ShaderModelComponent"], {"FileName": "Hair1Layer"})
        self.assertEqual(root["BSMaterial::AlphaSettingsComponent"], {"HasOpacity": "true"})
        self.assertEqual(root["BSMaterial::HairSettingsComponent"]["EdgeMaskMin"], "0.5")
        slots = {c["Index"]: c["Data"]["FileName"] for c in objs[3]["Components"]
                 if c["Type"] == "BSMaterial::MRTextureFile"}
        self.assertEqual(slots, {0: files["Albedo"], 2: files["Opacity"], 5: files["AmbientOcclusion"],
                                 12: files["DepthOffset"], 20: files["HairID"]})
        ids = {o.get("ID") for o in objs}                                # every link points at an object here
        for o in objs:
            for e in o.get("Edges", []):
                self.assertIn(e["To"], ids | {"<this>"})
        layer = next(c["Data"]["ID"] for c in objs[0]["Components"] if c["Type"] == "BSMaterial::LayerID")
        self.assertEqual(objs[1]["ID"], layer)
        self.assertIn('"FileName" : "Hair1Layer"', cm.dump_mat(mat))
        with self.assertRaises(ValueError):
            cm.build_hair_mat("x", {"Albedo": "a"})
        tuned = cm.build_hair_mat("y", files, {"DitherScale": "0.5"})
        self.assertEqual({c["Type"]: c["Data"] for c in tuned["Objects"][0]["Components"]}
                         ["BSMaterial::HairSettingsComponent"]["DitherScale"], "0.5")

    def test_fillers_written_once(self):
        def fake_texconv(exe, src, out_dir, fmt, extra=()):          # texconv writes <out_dir>/<same name>
            dst = os.path.join(out_dir, os.path.basename(src))
            if os.path.abspath(dst) != os.path.abspath(src):
                shutil.copy2(src, dst)
        with tempfile.TemporaryDirectory() as d:
            conv = pipeline.Converter.__new__(pipeline.Converter)
            conv.staging, conv.texconv, conv.prefix = d, "texconv.exe", "s2s"
            with mock.patch.object(textures, "texconv", fake_texconv):
                f = conv._hair_fillers()
                again = conv._hair_fillers()
            self.assertIs(f, again)
            self.assertEqual(sorted(f), ["AmbientOcclusion", "DepthOffset", "HairID"])
            for rel in f.values():
                self.assertTrue(os.path.exists(os.path.join(d, *rel.replace("Data\\", "").split("\\"))))

    def test_converter_and_pack_choose_the_hair_shader(self):
        import hair_pack
        conv = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        conv._materials, conv.stats, conv.material_errors = {}, {"materials_ok": 0}, {}
        seen = []

        def fake_set(stem, diffuse, normal, spec, **kw):
            seen.append((stem, kw.get("hair"), kw.get("alpha_ref")))
            return "materials\\s2s\\" + stem + ".mat"
        conv._convert_texture_set = fake_set
        got = conv.skyrim_hair_material("textures\\KS Hairdo's\\HDT\\anna.dds", "textures\\x_n.dds", 40)
        self.assertEqual(got, "materials\\s2s\\ks hairdo's/hdt/anna_hair.mat")
        self.assertEqual(seen, [("ks hairdo's/hdt/anna_hair", True, 40)])
        conv.skyrim_hair_material("textures\\KS Hairdo's\\HDT\\anna.dds", "textures\\x_n.dds", 40)
        self.assertEqual(len(seen), 1)                                     # cached
        sh = skyrimhair.HairShape(b"KSSMP_Anna", [], [], [], [], [], [], 3, 4, 0)
        with mock.patch.object(hair_pack.skyrimnif, "texture_set", lambda n, r: ["textures\\a.dds", "textures\\a_n.dds"]), \
                mock.patch.object(hair_pack.skyrimnif, "alpha_test", lambda n, r: (True, True, 40)):
            calls = []
            fake = mock.Mock()
            fake.skyrim_hair_material = lambda d, nn, ref, col: calls.append((d, nn, ref, col)) or "materials\\h.mat"
            self.assertEqual(hair_pack.hair_shader_material(fake, None, sh), "materials\\h.mat")
            self.assertEqual(hair_pack.hair_shader_material(fake, None, sh, (200, 160, 90)), "materials\\h.mat")
            self.assertEqual(calls, [("textures\\a.dds", "textures\\a_n.dds", 40, None),
                                     ("textures\\a.dds", "textures\\a_n.dds", 40, (200, 160, 90))])
        no_shader = skyrimhair.HairShape(b"X", [], [], [], [], [], [], -1, -1, 0)
        self.assertIsNone(hair_pack.hair_shader_material(fake, None, no_shader))


class HairColorTests(unittest.TestCase):
    def test_recolor_averages_the_visible_texels_to_the_target(self):
        import numpy as np
        px = np.zeros((4, 4, 4), np.uint8)
        px[:2, :, :3] = (100, 100, 100)
        px[2:, :, :3] = (160, 140, 120)
        px[:, :2, 3] = 255                                   # left half visible, right half cut out
        px[:, 2:, :3] = (255, 0, 0)                          # invisible red must not count
        out = pipeline.recolor(px, (200, 160, 90)).astype(float)
        vis = out[:, :2].reshape(-1, 3)
        np.testing.assert_allclose(vis.mean(axis=0), (200, 160, 90), atol=1.0)
        self.assertLess(out[0, 0, 0], out[3, 0, 0])          # darker strands stay darker
        clear = pipeline.recolor(np.full((2, 2, 4), 0, np.uint8) + np.array([50, 50, 50, 0], np.uint8), (10, 20, 30))
        np.testing.assert_allclose(clear[0, 0], (10, 20, 30), atol=1.0)   # no visible texel: all count

    def test_no_mirrored_back_faces_under_the_hair_shader(self):
        import hair_pack
        sh = skyrimhair.HairShape(b"KSSMP_Anna", [], [], [], [], [], [], 3, 4, 0)
        none = skyrimhair.HairShape(b"X", [], [], [], [], [], [], -1, -1, 0)
        with mock.patch.object(hair_pack.skyrimnif, "double_sided", lambda n, r: True):
            self.assertFalse(hair_pack.back_faces_for(None, sh, True))      # the hair shader draws both sides
            self.assertTrue(hair_pack.back_faces_for(None, sh, False))      # a cutout material needs the copy
            self.assertFalse(hair_pack.back_faces_for(None, none, False))
        with mock.patch.object(hair_pack.skyrimnif, "double_sided", lambda n, r: False):
            self.assertFalse(hair_pack.back_faces_for(None, sh, False))

    def test_hair_setting_override_reaches_the_material(self):
        import argparse
        import hair_pack
        self.assertEqual(hair_pack.hair_setting("MaxDepthOffset=0"), ("MaxDepthOffset", "0"))
        for bad in ("Nope=1", "MaxDepthOffset", "MaxDepthOffset="):
            with self.assertRaises(argparse.ArgumentTypeError):
                hair_pack.hair_setting(bad)
        mat = cm.build_hair_mat("x", {"Albedo": "a", "Opacity": "o"}, dict([hair_pack.hair_setting("MaxDepthOffset=0")]))
        hs = {c["Type"]: c["Data"] for c in mat["Objects"][0]["Components"]}["BSMaterial::HairSettingsComponent"]
        self.assertEqual(hs["MaxDepthOffset"], "0")
        self.assertEqual(hs["DitherScale"], cm.HAIR_SETTINGS["DitherScale"])       # the rest as before
        src = open(pipeline.__file__, encoding="utf-8").read()
        self.assertIn('getattr(self, "hair_settings", None)', src)                  # the converter passes them on

    def test_orient_outward_turns_inward_cards(self):
        import numpy as np
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.6)
        top = 1.6 + 0.09 + 0.1                              # 1 dm over the cranium's centre
        quad = lambda z, dz: np.array([[-0.01, -0.01, z], [0.01, -0.01, z + dz], [0.01, 0.01, z], [-0.01, 0.01, z]])
        p = np.concatenate([quad(top, 0.0), quad(top + 0.01, 0.0)])
        tris = [(0, 1, 2), (0, 2, 3),                        # card 1: counter-clockwise from above: faces up (out)
                (4, 6, 5), (4, 7, 6)]                        # card 2: clockwise: faces down, toward the head
        nrm = np.array([[0, 0, 1.0]] * 4 + [[0, 0, -1.0]] * 4)
        sh = skyrimhair.HairShape(b"A", p, nrm, np.zeros_like(nrm), [(0, 0)] * 8, tris, [[("C_Head", 1.0)]] * 8,
                                  -1, -1, 0)
        out, rep = skyrimhair.orient_outward(skyrimhair.Hair([sh], [], {}, {}), head)
        o = out.shapes[0]
        self.assertEqual(rep, {"cards": 2, "turned": 1})
        self.assertEqual(o.triangles[:2], [(0, 1, 2), (0, 2, 3)])           # the outward card untouched
        self.assertEqual(o.triangles[2:], [(4, 5, 6), (4, 6, 7)])           # the inward one rewound
        np.testing.assert_allclose(o.normals, [[0, 0, 1.0]] * 8)            # and its normals negated
        for a, b, c in o.triangles:
            self.assertGreater(np.cross(p[b] - p[a], p[c] - p[a])[2], 0)
        hang = np.array([[0.1, -0.01, 1.3], [0.1, 0.01, 1.3], [0.1, 0.0, 1.2]])   # a lock beside the body
        hs = skyrimhair.HairShape(b"H", hang, np.array([[-1.0, 0, 0]] * 3), np.zeros((3, 3)), [(0, 0)] * 3,
                                  [(0, 1, 2)], [[("C_Head", 1.0)]] * 3, -1, -1, 0)
        o2, r2 = skyrimhair.orient_outward(skyrimhair.Hair([hs], [], {}, {}), head)
        a, b, c = o2.shapes[0].triangles[0]
        self.assertGreater(np.cross(hang[b] - hang[a], hang[c] - hang[a])[0], 0)   # faces away from the body (+X)
        self.assertEqual(r2["turned"], 1)

    def test_opacity_ramp(self):
        import argparse
        import numpy as np
        import hair_pack
        a = np.array([0, 48, 80, 112, 200, 255], np.uint8)
        np.testing.assert_array_equal(pipeline.ramp_alpha(a, 48, 112), [0, 0, 128, 255, 255, 255])
        np.testing.assert_array_equal(pipeline.ramp_alpha(a, 0, 255), a)          # 0,255: as it is
        self.assertEqual(hair_pack.opacity_ramp("48,112"), (48, 112))
        for bad in ("112,48", "0,300", "x"):
            with self.assertRaises(argparse.ArgumentTypeError):
                hair_pack.opacity_ramp(bad)
        conv = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        conv._materials, conv.stats, conv.material_errors = {}, {"materials_ok": 0}, {}
        seen = []
        conv._convert_texture_set = lambda stem, d, n, s, **kw: seen.append(kw.get("opacity_ramp")) or stem
        conv.skyrim_hair_material("textures\\h\\anna.dds", "", 40, None, (48, 112))
        conv.skyrim_hair_material("textures\\h\\anna.dds", "", 40, None, (0, 255))
        self.assertEqual(seen, [(48, 112), (0, 255)])                           # one material per ramp
        got = []
        conv._convert_texture_set = lambda stem, d, n, s, **kw: got.append(kw.get("strands")) or stem
        conv.skyrim_hair_material("textures\\h\\anna.dds", "", 40, None, None, True)
        self.assertEqual(got, [True])

    def test_strand_maps_keep_the_density_in_crisp_strands(self):
        import numpy as np
        a = np.zeros((64, 64), np.uint8)
        a[:, 16:48] = 128                                   # a half-clear band
        a[:, 48:] = 255
        op, hid = pipeline.strand_maps(a)
        self.assertEqual(op.shape, (128, 128))
        self.assertEqual(set(np.unique(op)), {0, 255})      # crisp: solid or clear
        band = op[8:-8, 40:88]
        self.assertAlmostEqual((band > 0).mean(), 0.5, delta=0.12)   # about half the band's texels solid
        self.assertTrue((op[8:-8, 104:] == 255).all())      # solid stays solid
        self.assertTrue((op[8:-8, :24] == 0).all())         # clear stays clear
        cols = (band > 0).mean(axis=0)
        self.assertGreater((cols > 0.8).mean() + (cols < 0.2).mean(), 0.6)   # strands: whole columns, not noise
        self.assertTrue((hid == hid[0]).all())              # one ID per strand (column)
        self.assertGreater(len(np.unique(hid[0])), 20)

    def test_flatten_albedo_evens_patches_keeps_strands(self):
        import numpy as np
        px = np.zeros((64, 128, 4), np.uint8)
        px[:, :, 3] = 255
        px[:, :64, :3] = 60                                 # a dark painted half
        px[:, 64:, :3] = 180                                # a light half
        px[:, ::4, :3] = (px[:, ::4, :3] * 0.7).astype(np.uint8)   # strand lines
        out = pipeline.flatten_albedo(px, radius=8).astype(float)
        dark, light = out[:, 8:56, 0].mean(), out[:, 72:120, 0].mean()
        self.assertLess(abs(dark - light) / max(dark, light), 0.35)  # was 3x apart
        self.assertLess(out[10, 64 + 8, 0], out[10, 64 + 9, 0])       # the strand line still darker

    def test_hair_color_option_and_material_names(self):
        import argparse
        import hair_pack
        self.assertEqual(hair_pack.hair_color("200,160,90"), (200, 160, 90))
        self.assertEqual(hair_pack.hair_color(" 20, 15 ,10"), (20, 15, 10))
        for bad in ("200,160", "300,1,1", "a,b,c"):
            with self.assertRaises(argparse.ArgumentTypeError):
                hair_pack.hair_color(bad)
        conv = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        conv._materials, conv.stats, conv.material_errors = {}, {"materials_ok": 0}, {}
        seen = []
        conv._convert_texture_set = lambda stem, d, n, s, **kw: seen.append((stem, kw.get("albedo_target"))) or stem
        plain = conv.skyrim_hair_material("textures\\h\\anna.dds", "", 40)
        blonde = conv.skyrim_hair_material("textures\\h\\anna.dds", "", 40, (200, 160, 90))
        self.assertNotEqual(plain, blonde)                    # its own textures and material
        self.assertEqual(seen, [("h/anna_hair", None), ("h/anna_hair_c8a05a", (200, 160, 90))])
        conv.skyrim_material = mock.Mock(return_value="materials\\t.mat")
        sh = skyrimhair.HairShape(b"Hairline", [], [], [], [], [], [], 3, 4, 0)
        with mock.patch.object(hair_pack.skyrimnif, "texture_set", lambda n, r: ["textures\\hl.dds", ""]):
            hair_pack.tint_material(conv, None, sh, 128, (200, 160, 90))
        self.assertEqual(conv.skyrim_material.call_args.kwargs, {"albedo_target": (200, 160, 90)})


class HeadPartTests(unittest.TestCase):
    def test_hair_head_part_copied_from_a_playable_vanilla_hair(self):
        import struct
        import hair_pack
        from fo4sf import sfplugin
        zs = sfplugin.zs

        def hdpt(fid, edid, model, part, flags, extra=()):
            subs = [(b"EDID", zs(edid)), (b"FULL", zs(edid)), (b"MODL", zs(model)), (b"DATA", bytes([flags])),
                    (b"PNAM", struct.pack("<I", part)), (b"HNAM", struct.pack("<I", 0x1234)),
                    (b"NAM2", zs("Hair_Medium")), (b"NAM3", zs("Bob_Cap_mask")), (b"RNAM", struct.pack("<I", 0x24A024)),
                    (b"MNAM", struct.pack("<I", 0x5678))] + list(extra)
            return (b"HDPT", bytes(24), subs, fid)
        recs = [hdpt(1, "BeardA", "Actors\\Human\\beard.nif", 4, 1),
                hdpt(2, "HairBobNPC", "Actors\\Human\\Mesh\\hairs\\bob\\bob_f.nif", 3, 0),     # not playable
                hdpt(3, "Hair_Afro", "Actors\\Human\\Mesh\\hairs\\afro\\afro_f.nif", 3, 1),
                hdpt(4, "Hair_Bob", "Actors\\Human\\Mesh\\hairs\\bob\\bob_f.nif", 3, 5)]
        self.assertEqual(sfplugin.edid(hair_pack.hair_part_template(recs, "bob_f")[2]), "Hair_Bob")
        self.assertEqual(sfplugin.edid(hair_pack.hair_part_template(recs, "nothing")[2]), "Hair_Afro")
        self.assertIsNone(hair_pack.hair_part_template(recs[:2]))
        t, h, subs, fid = hair_pack.hair_part_record(recs[3], 7, "S2S_Hair_Anna", "Anna (Skyrim)", "s2s\\hair\\anna.nif")
        d = dict(subs)
        self.assertEqual(t, b"HDPT")
        self.assertEqual(fid, sfplugin.new_form_id(7))
        self.assertEqual(d[b"EDID"], zs("S2S_Hair_Anna"))
        self.assertEqual(d[b"FULL"], zs("Anna (Skyrim)"))
        self.assertEqual(d[b"MODL"], zs("s2s\\hair\\anna.nif"))
        self.assertEqual(d[b"DATA"][0] & hair_pack.PART_PLAYABLE, 1)
        self.assertEqual(struct.unpack("<I", d[b"PNAM"])[0], hair_pack.HAIR_PART)
        self.assertNotIn(b"HNAM", d)                     # no extra parts of the template
        self.assertNotIn(b"MNAM", d)                     # no morphs made for the template's mesh
        self.assertEqual(d[b"RNAM"], struct.pack("<I", 0x24A024))   # the template's races kept

class ChargenListTests(unittest.TestCase):
    def test_override_appends_once_and_keeps_the_rest(self):
        import struct
        import hair_pack
        from fo4sf import sfplugin
        l = lambda i: (b"LNAM", struct.pack("<I", i))
        rec = (b"FLST", bytes(24), [(b"EDID", sfplugin.zs("HeadPartsChargenOptionsFemale")), l(0x2311), l(0x3A3D6F),
                                    (b"XXXX", b"tail")], 0x3D9B0)
        other = (b"FLST", bytes(24), [(b"EDID", sfplugin.zs("Other"))], 5)
        t, h, subs, fid = hair_pack.chargen_list_override([other, rec], "HeadPartsChargenOptionsFemale",
                                                          [0x1000801, 0x2311, 0x1000803])
        self.assertEqual(fid, 0x3D9B0)                                   # the vanilla record, overridden
        self.assertEqual([s for s, _d in subs], [b"EDID", b"LNAM", b"LNAM", b"LNAM", b"LNAM", b"XXXX"])
        self.assertEqual([struct.unpack("<I", d)[0] for s, d in subs if s == b"LNAM"],
                         [0x2311, 0x3A3D6F, 0x1000801, 0x1000803])
        self.assertIsNone(hair_pack.chargen_list_override([other], "HeadPartsChargenOptionsFemale", [1]))

class ReferenceHairTests(unittest.TestCase):
    def test_reads_nif_and_mesh_from_the_named_archive(self):
        import numpy as np
        import hair_pack
        from fo4sf import nif, sfmesh, sfnif, convert_static
        pts = [(0.0, 0.0, 0.1), (0.05, 0.0, 0.08), (0.0, -0.1, 0.0)]          # head-relative, node at C_Head
        scale, raw = sfmesh.encode_positions(pts)
        m = sfmesh.SfMesh(triangles=[(0, 1, 2)], scale=scale, positions=raw, weights_per_vertex=1,
                          weights=[(0, 65535)] * 3)
        sfmesh.build_meshlets(m)
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        sh = sfnif.SkinnedShape(b"H", f"{d}\\{f}".encode(), 3, 3, "materials\\h.mat", [b"faceBone_C_HeadTop"],
                                [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)])
        n = sfnif.build_skinned_nif(b"H", [sh])
        files = {"meshes/hair/x_f_facebones.nif": nif.serialize(n), f"geometries/{d}/{f}.mesh": data}

        class FakeBa2:
            def __init__(self, path):
                self.names = list(files)

            def read(self, i):
                return files[self.names[i]]
        with mock.patch.object(hair_pack.ba2mod, "Ba2", FakeBa2), \
                mock.patch.object(hair_pack, "read_game_file", lambda sf, rel: None):
            got = hair_pack.reference_hair("C:\\mods\\IDG - Main.ba2:meshes/hair/x_f_facebones.nif", "sf")
            np.testing.assert_allclose(got[0], pts, atol=1e-4)
            self.assertEqual(got[3], [(0, 1, 2)])
            with self.assertRaises(SystemExit):
                hair_pack.reference_hair("C:\\mods\\IDG - Main.ba2:meshes/hair/missing.nif", "sf")
        with self.assertRaises(SystemExit):
            hair_pack.reference_hair("no archive here", "sf")


if __name__ == "__main__":
    unittest.main()
