"""Synthetic tests for the material / texture converters. Texture tests need numpy and are skipped without it."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import convert_material as cm  # noqa: E402

try:
    import numpy as np
    from fo4sf import textures
except ImportError:  # pragma: no cover
    np = None


def fake_bgsm(diffuse="a/b_d.dds", normal="a/b_n.dds", spec="a/b_s.dds"):
    head = b"BGSM" + struct.pack("<II4f", 2, 3, 0.0, 0.0, 1.0, 1.0) + b"\x00" * 20
    def s(t):
        b = t.encode() + b"\0"
        return struct.pack("<I", len(b)) + b
    return head + s(diffuse) + s(normal) + s(spec) + s("") + s("env/c.dds") + s("") + b"\x00" * 40


class BgsmTests(unittest.TestCase):
    def test_parse_textures_and_uv(self):
        b = cm.parse_bgsm(fake_bgsm())
        self.assertEqual((b.diffuse, b.normal, b.smooth_spec, b.envmap), ("a/b_d.dds", "a/b_n.dds", "a/b_s.dds", "env/c.dds"))
        self.assertEqual(b.uv_scale, (1.0, 1.0))
        self.assertTrue(b.tile_u and b.tile_v)

    def test_rejects_other_files(self):
        with self.assertRaises(ValueError):
            cm.parse_bgsm(b"BGEM" + b"\0" * 40)


def mini_template():
    old = cm.TEMPLATE_TEXTURES
    ref = "res:AAAAAAAA:00000001:BBBBBBBB"
    return {
        "Import": ["Data\\MATERIALS\\Common\\Plastic\\PlasticPlainSmooth01.mat"],
        "Objects": [
            {"Components": [{"Type": "BSComponentDB::CTName", "Data": {"Name": "MetalIronCast01"}, "Index": 0}],
             "Parent": "Data\\MATERIALS\\Common\\Plastic\\PlasticPlainSmooth01.mat"},
            {"ID": ref, "Parent": "res:9097DAC9:0005A4D7:A487E721",
             "Components": [{"Type": "BSMaterial::TextureSetID", "Data": {"ID": ref}, "Index": 0},
                            {"Type": "BSMaterial::Color", "Index": 0, "Data": {"Value": {"Data": {"x": "0.5", "y": "0.5", "z": "0.5", "w": "1"}}}}],
             "Edges": [{"To": ref, "Type": "BSComponentDB2::OuterEdge"}]},
        ],
        "Summary": {"Layer1": {"Parent": "p", "Tint": {}, "Textures": {
            "Albedo": {"File": old["Albedo"]}, "Normal": {"File": old["Normal"]}, "Roughness": {"File": old["Roughness"]},
            "Metalness": {"File": "", "UseReplacement": False}}}},
        "Version": 1,
    }


class MatTests(unittest.TestCase):
    def test_build_mat_repoints_textures_and_remaps_ids(self):
        t = mini_template()
        m = cm.build_mat(t, "FO4Port_X", "Data\\textures\\x_color.dds", "Data\\textures\\x_normal.dds", "Data\\textures\\x_rough.dds",
                         tint=(1, 1, 1, 1), metalness=0.25)
        tex = m["Summary"]["Layer1"]["Textures"]
        self.assertEqual(tex["Albedo"]["File"], "Data\\textures\\x_color.dds")
        self.assertEqual(tex["Roughness"]["File"], "Data\\textures\\x_rough.dds")
        self.assertEqual(tex["Metalness"]["Replacement"]["x"], 0.25)
        new_id = m["Objects"][1]["ID"]
        self.assertNotEqual(new_id, t["Objects"][1]["ID"])
        self.assertEqual(m["Objects"][1]["Components"][0]["Data"]["ID"], new_id)      # references follow the remap
        self.assertEqual(m["Objects"][1]["Edges"][0]["To"], new_id)
        self.assertEqual(m["Objects"][1]["Parent"], t["Objects"][1]["Parent"])         # class parents untouched
        self.assertEqual(m["Objects"][0]["Components"][0]["Data"]["Name"], "FO4Port_X")
        self.assertEqual(m["Objects"][1]["Components"][1]["Data"]["Value"]["Data"]["x"], "1")
        self.assertEqual(t["Objects"][1]["ID"], "res:AAAAAAAA:00000001:BBBBBBBB")      # template not mutated

    def test_metalness_component_overrides_template(self):
        t = mini_template()
        t["Objects"][1]["Components"].append(
            {"Type": "BSMaterial::TextureReplacement", "Index": 4, "Data": {"Enabled": "true",
             "Color": {"Data": {"Value": {"Data": {"x": "1", "y": "1", "z": "1", "w": "1"}}}}}})
        m = cm.build_mat(t, "X", "a", "b", "c")
        v = m["Objects"][1]["Components"][-1]["Data"]["Color"]["Data"]["Value"]["Data"]
        self.assertEqual((v["x"], v["y"], v["z"]), ("0", "0", "0"))

    def test_ids_are_deterministic_and_name_dependent(self):
        a = cm.build_mat(mini_template(), "A", "a", "b", "c")
        b = cm.build_mat(mini_template(), "A", "a", "b", "c")
        c = cm.build_mat(mini_template(), "B", "a", "b", "c")
        self.assertEqual(cm.dump_mat(a), cm.dump_mat(b))
        self.assertNotEqual(a["Objects"][1]["ID"], c["Objects"][1]["ID"])


class GlassTests(unittest.TestCase):
    def test_parse_bgem_base_and_normal(self):
        def s(t):
            b = t.encode() + b"\0"
            return struct.pack("<I", len(b)) + b
        d = b"BGEM" + struct.pack("<II", 2, 3) + b"\x00" * 30 + s("a/base_d.dds") + s("") + s("env.dds") + s("a/base_n.dds") + s("")
        self.assertEqual(cm.parse_bgem_textures(d), ("a/base_d.dds", "a/base_n.dds"))

    def test_build_from_template_swaps_files_and_sets_opacity(self):
        t = {"Objects": [
                {"Components": [{"Type": "BSComponentDB::CTName", "Data": {"Name": "Old"}, "Index": 0}], "Parent": "p"},
                {"ID": "res:00000001:00000002:00000003", "Parent": "q", "Components": [
                    {"Type": "BSMaterial::MRTextureFile", "Index": 0, "Data": {"FileName": "Data\\old_color.dds"}},
                    {"Type": "BSMaterial::TextureReplacement", "Index": 2,
                     "Data": {"Color": {"Data": {"Value": {"Data": {"x": "0.09", "y": "0.09", "z": "0.09", "w": "1"}}}}}}]}],
             "Summary": {"Layer1": {"Textures": {"Albedo": {"File": "Data\\old_color.dds"},
                                                 "Opacity": {"File": "", "Replacement": {"x": 0.09}}}}}}
        m = cm.build_from_template(t, "FO4Port_Glass", {"Albedo": "Data\\new_color.dds"}, opacity_value=0.2)
        self.assertEqual(m["Objects"][1]["Components"][0]["Data"]["FileName"], "Data\\new_color.dds")
        self.assertEqual(m["Summary"]["Layer1"]["Textures"]["Albedo"]["File"], "Data\\new_color.dds")
        self.assertEqual(m["Objects"][1]["Components"][1]["Data"]["Color"]["Data"]["Value"]["Data"]["x"], "0.2")
        self.assertNotEqual(m["Objects"][1]["ID"], t["Objects"][1]["ID"])
        self.assertEqual(m["Objects"][0]["Components"][0]["Data"]["Name"], "FO4Port_Glass")


@unittest.skipUnless(np, "numpy not installed")
class TextureTests(unittest.TestCase):
    def test_bc4_endpoint_blocks(self):
        hi = bytes([255, 0]) + b"\x00" * 6                       # all indices 0 -> a0
        lo = bytes([255, 0]) + bytes([0x49, 0x92, 0x24, 0x49, 0x92, 0x24])   # all indices 1 -> a1
        self.assertTrue((textures.decode_bc4(hi, 4, 4) == 255).all())
        self.assertTrue((textures.decode_bc4(lo, 4, 4) == 0).all())

    def test_bc5_layout_two_channels(self):
        blk = bytes([200, 0]) + b"\x00" * 6 + bytes([10, 0]) + bytes([0x49, 0x92, 0x24, 0x49, 0x92, 0x24])
        r, g = textures.decode_bc5(blk, 4, 4)
        self.assertTrue((r == 200).all())
        self.assertTrue((g == 0).all())

    def test_block_order_places_blocks_left_to_right(self):
        blocks = bytes([10, 10]) + b"\x00" * 6 + bytes([90, 90]) + b"\x00" * 6   # two solid BC4 blocks
        plane = textures.decode_bc4(blocks, 8, 4)
        self.assertTrue((plane[:, :4] == 10).all() and (plane[:, 4:] == 90).all())

    def test_roughness_scaled_by_material_smoothness(self):
        g = np.array([[255, 255]], dtype=np.uint8)
        self.assertEqual(textures.roughness_from_smoothness(g, 0.5).tolist(), [[127, 127]])      # 255 - 127.5 -> 127
        self.assertEqual(textures.roughness_from_smoothness(g, 1.0, 0.25).tolist(), [[127, 127]])  # sqrt(0.25) = 0.5

    def test_roughness_and_green_flip(self):
        g = np.array([[0, 255, 100]], dtype=np.uint8)
        self.assertEqual(textures.roughness_from_smoothness(g).tolist(), [[255, 0, 155]])
        self.assertEqual(textures.flip_green(g).tolist(), [[255, 0, 155]])

    def test_dds_writers_produce_valid_headers(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.dds")
            textures.write_r8(p, np.zeros((8, 8), dtype=np.uint8))
            h = textures.read_dds_header(open(p, "rb").read())
            self.assertEqual((h["width"], h["height"], h["dxgi"], h["data_offset"]), (8, 8, textures.DXGI_R8_UNORM, 148))
            textures.write_rg8_snorm(p, np.full((4, 4), 128, np.uint8), np.full((4, 4), 255, np.uint8))
            raw = open(p, "rb").read()
            self.assertEqual(textures.read_dds_header(raw)["dxgi"], textures.DXGI_R8G8_SNORM)
            self.assertEqual(raw[148], 0)             # 128/255 -> +0.004 -> rounds to byte 0
            self.assertEqual(raw[149], 127)           # 255 -> +1.0


if __name__ == "__main__":
    unittest.main()
