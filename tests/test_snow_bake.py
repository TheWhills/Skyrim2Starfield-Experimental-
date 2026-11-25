"""Skyrim's directional snow baked into objects (2026-11-25): the vertex snow mask, tilt buckets, the two-layer snow
material and the grouping of snowy references. Synthetic data only."""
import json
import math
import os
import sys
import unittest
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import convert_material as cm, exterior, skyrimsnow  # noqa: E402
from fo4sf.nif import Fo4Shape  # noqa: E402


def shape(normals, colors=None, rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1)):
    n = len(normals)
    return Fo4Shape(name=b"s", translation=(0, 0, 0), rotation=rotation, scale=1.0, shader_ref=-1, alpha_ref=-1,
                    skin_ref=-1, positions=[(0, 0, 0)] * n, uvs=[(0, 0)] * n, normals=normals, tangents=[],
                    colors=colors or [], triangles=[], skinned=False)


class MaskTest(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(skyrimsnow.mask(1.0, 0.35, 0.4), 1.0)            # flat top
        self.assertEqual(skyrimsnow.mask(0.3, 0.35, 0.4), 0.0)            # steep side
        self.assertAlmostEqual(skyrimsnow.mask(0.575, 0.35, 0.4), 0.5)
        self.assertEqual(skyrimsnow.mask(0.6, 0.35, 0.4, max_angle_deg=45), 0.0)   # beyond the base's max angle

    def test_with_snow(self):
        s = shape([(0, 0, 1), (1, 0, 0), (0, 0, -1)], colors=[(10, 20, 30, 40)] * 3)
        out = skyrimsnow.with_snow(s, (0, 0, 1), 0.35, 0.4)
        self.assertEqual(out.colors, [(255, 20, 30, 255), (0, 20, 30, 0), (0, 20, 30, 0)])
        # a shape turned upside down in the model: its local "down" faces up
        flip = shape([(0, 0, -1)], rotation=(1, 0, 0, 0, -1, 0, 0, 0, -1))
        self.assertEqual(skyrimsnow.with_snow(flip, (0, 0, 1), 0.35, 0.4).colors, [(255, 255, 255, 255)])
        # a tilted reference: world up seen tilted in the model frame
        t = math.radians(60)
        out = skyrimsnow.with_snow(shape([(0, 0, 1)]), (math.sin(t), 0, math.cos(t)), 0.35, 0.4)
        self.assertEqual(out.colors[0][0], round(255 * skyrimsnow.mask(math.cos(t), 0.35, 0.4)))
        bare = shape([])
        self.assertIs(skyrimsnow.with_snow(bare, (0, 0, 1), 0.35, 0.4), bare)    # no normals: unchanged

    def test_tilt_buckets(self):
        self.assertEqual(skyrimsnow.tilt_key(exterior.ref_matrix([0, 0, 2.5])), (0, 0))    # yaw only: upright
        for rot in ([0.4, 0, 1.0], [0, 0.7, -2.0], [0.2, 0.3, 0.1]):
            m = exterior.ref_matrix(rot)
            up = (m[6], m[7], m[8])
            c = skyrimsnow.tilt_up(skyrimsnow.tilt_key(m))
            ang = math.degrees(math.acos(max(-1, min(1, sum(a * b for a, b in zip(up, c))))))
            self.assertLess(ang, 15.0, rot)                                 # the bucket's up is near the true one


class SnowMaterialTest(unittest.TestCase):
    def template(self):
        """The shape of CaveSmoothSnow01: root with blender + two layers + an LOD material; layer -> material ->
        texture set; a UV stream with scale 3."""
        def o(i, comps, parent="res:AAAAAAAA:0005A3FB:A06346EA"):
            return {"ID": i, "Parent": parent, "Components": comps}
        ref = lambda t, i, idx=0: {"Type": "BSMaterial::" + t, "Index": idx, "Data": {"ID": i}}  # noqa: E731
        scale = {"Type": "BSMaterial::Scale", "Index": 0, "Data": {"Value": {"Data": {"x": "3", "y": "3"}}}}
        return {"Filename": "MATERIALS\\X.mat", "Import": [], "Summary": {"Layer1": {"Textures": {}}}, "Objects": [
            {"Parent": "2Layer", "Components": [{"Type": "BSComponentDB::CTName", "Index": 0, "Data": {"Name": "T"}},
                                                ref("BlenderID", "res:00000003:0005B6FE:A05E0763"), ref("LayerID", "res:00000004:0005B6FE:A05E0763"),
                                                ref("LayerID", "res:00000008:0005B6FE:A05E0763", 1), ref("LODMaterialID", "res:00000002:0005B6FE:A05E0763", 2)]},
            o("res:00000002:0005B6FE:A05E0763", [ref("LayerID", "res:00000001:0005B6FE:A05E0763")]), o("res:00000001:0005B6FE:A05E0763", []),
            o("res:00000003:0005B6FE:A05E0763", [{"Type": "BSMaterial::ParamBool", "Index": 5, "Data": {"Value": "true"}}]),
            o("res:00000004:0005B6FE:A05E0763", [ref("MaterialID", "res:00000005:0005B6FE:A05E0763"), ref("UVStreamID", "res:00000007:0005B6FE:A05E0763")]),
            o("res:00000005:0005B6FE:A05E0763", [ref("TextureSetID", "res:00000006:0005B6FE:A05E0763")]), o("res:00000006:0005B6FE:A05E0763", []), o("res:00000007:0005B6FE:A05E0763", [scale]),
            o("res:00000008:0005B6FE:A05E0763", [ref("MaterialID", "res:00000009:0005B6FE:A05E0763")]), o("res:00000009:0005B6FE:A05E0763", [])]}

    def test_build(self):
        files = {s: f"Data/t/{s}.dds" for s in cm.SNOW_BASE_SLOTS}
        m = cm.build_snow_mat(self.template(), "SKY_Snow_X", files)
        self.assertNotIn("Filename", m)
        root = m["Objects"][0]
        self.assertFalse(any(c["Type"] == "BSMaterial::LODMaterialID" for c in root["Components"]))
        objs = {o["ID"]: o for o in m["Objects"][1:]}
        self.assertEqual(len(objs), 7)                                    # the LOD material's two objects dropped
        layer = objs[next(c["Data"]["ID"] for c in root["Components"] if c["Type"] == "BSMaterial::LayerID")]
        mat = objs[layer["Components"][0]["Data"]["ID"]]
        ts = objs[mat["Components"][0]["Data"]["ID"]]
        self.assertEqual({c["Index"]: c["Data"]["FileName"] for c in ts["Components"]}, files)
        uv = objs[layer["Components"][1]["Data"]["ID"]]
        self.assertEqual(uv["Components"][0]["Data"]["Value"]["Data"], {"x": "1", "y": "1"})
        with self.assertRaises(ValueError):
            cm.build_snow_mat(self.template(), "X", {0: "a"})


class GroupTest(unittest.TestCase):
    def test_snow_groups(self):
        import snow_bake as S
        objects = {"refs": [{"src": "a"}, {"src": "b"}, {"src": "c"}, {"src": "d"}], "bases": []}
        export = [{"formkey": "a", "base_formkey": "S", "model": "Rocks\\R.nif", "rot": [0, 0, 1.0], "base_editor_id": "RSnow"},
                  {"formkey": "b", "base_formkey": "S", "model": "Rocks\\R.nif", "rot": [0, 0, 2.0], "base_editor_id": "RSnow"},
                  {"formkey": "c", "base_formkey": "S", "model": "Rocks\\R.nif", "rot": [0.6, 0, 0], "base_editor_id": "RSnow"},
                  {"formkey": "d", "base_formkey": "P", "model": "Rocks\\R.nif", "rot": [0, 0, 0], "base_editor_id": "R"}]
        dm = {"S": {"edid": "SnowMaterialObject1P", "max_angle": 90.0, "falloff": [0.35, 0.4]}}
        jobs, refs = S.snow_groups(objects, export, dm, {})
        self.assertEqual(set(refs), {"a", "b", "c"})                     # the plain rock stays plain
        self.assertEqual(refs["a"], refs["b"])                           # yaw does not matter
        self.assertNotEqual(refs["a"], refs["c"])                        # tilt does
        self.assertTrue(all(k.startswith("meshes\\rocks\\r.nif|snow:") for k in jobs))
        self.assertEqual(exterior.mesh_of(refs["a"]), "meshes\\rocks\\r.nif")
        self.assertEqual(sorted(j["refs"] for j in jobs.values()), [1, 2])


if __name__ == "__main__":
    unittest.main()


class SkyrimSnowLayerTest(unittest.TestCase):
    def test_snow_layer_files_and_scale(self):
        t = SnowMaterialTest().template()
        base = {s: f"Data/rock/{s}.dds" for s in cm.SNOW_BASE_SLOTS}
        snow = {s: f"Data/snow01/{s}.dds" for s in cm.SNOW_BASE_SLOTS}
        t["Objects"][-1]["Components"].append({"Type": "BSMaterial::TextureSetID", "Index": 0,
                                               "Data": {"ID": "res:0000000A:0005B6FE:A05E0763"}})
        t["Objects"].append({"ID": "res:0000000A:0005B6FE:A05E0763", "Parent": "res:AAAAAAAA:0005A3FB:A06346EA",
                             "Components": []})
        m = cm.build_snow_mat(t, "S", base, snow_files=snow, snow_uv_scale=2.0)
        sets = [{c["Index"]: c["Data"]["FileName"] for c in o["Components"] if c["Type"] == "BSMaterial::MRTextureFile"}
                for o in m["Objects"][1:]]
        self.assertIn(base, sets)
        self.assertIn(snow, sets)
        with self.assertRaises(ValueError):
            cm.build_snow_mat(t, "S", base, snow_files={0: "x"})

    def test_snow_uv_scale(self):
        # a 340 x 340 unit square mapped once: the snow (170.67 units) repeats twice across it
        sq = Fo4Shape(name=b"q", translation=(0, 0, 0), rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1), scale=1.0, shader_ref=-1,
                      alpha_ref=-1, skin_ref=-1, positions=[(0, 0, 0), (340, 0, 0), (340, 340, 0), (0, 340, 0)],
                      uvs=[(0, 0), (1, 0), (1, 1), (0, 1)], normals=[], tangents=[], colors=[],
                      triangles=[(0, 1, 2), (0, 2, 3)], skinned=False)
        self.assertEqual(skyrimsnow.snow_uv_scale(sq), 2.0)
        self.assertEqual(skyrimsnow.snow_uv_scale(shape([(0, 0, 1)])), 1.0)          # no triangles / UVs


class DegenerateNormalTest(unittest.TestCase):
    def test_nan_and_zero_normals(self):
        out = skyrimsnow.with_snow(shape([(float("nan"), 0, 1), (0, 0, 0)]), (0, 0, 1), 0.35, 0.4)
        self.assertEqual([c[0] for c in out.colors], [0, 0])

    def test_nan_uvs(self):
        q = shape([(0, 0, 1)] * 3)
        q.positions[:] = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        q.uvs[:] = [(0, 0), (float("nan"), 0), (0, 1)]
        q.triangles.append((0, 1, 2))
        self.assertEqual(skyrimsnow.snow_uv_scale(q), 1.0)
