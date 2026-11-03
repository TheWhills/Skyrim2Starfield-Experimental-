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
            fake.skyrim_hair_material = lambda d, nn, ref: calls.append((d, nn, ref)) or "materials\\h.mat"
            self.assertEqual(hair_pack.hair_shader_material(fake, None, sh), "materials\\h.mat")
            self.assertEqual(calls, [("textures\\a.dds", "textures\\a_n.dds", 40)])
        no_shader = skyrimhair.HairShape(b"X", [], [], [], [], [], [], -1, -1, 0)
        self.assertIsNone(hair_pack.hair_shader_material(fake, None, no_shader))


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
