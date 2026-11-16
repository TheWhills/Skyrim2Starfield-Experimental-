import os
import struct
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from fo4sf import skyrimfire  # noqa: E402


class FakeNif:
    def __init__(self, blocks, strings=()):
        self.blocks = [b for _t, b in blocks]
        self.types = [t for t, _b in blocks]
        self.strings = list(strings)

    def type_of(self, i):
        return self.types[i]


def sized(s: bytes) -> bytes:
    return struct.pack("<I", len(s)) + s


def effect_block(flags1, source=b"textures\\effects\\FXFireAtlas04.dds",
                 grey=b"textures\\effects\\gradients\\GradFireExplosion.dds", ctrl=-1, color=(1, 0.5, 0.25, 1)):
    b = struct.pack("<iIi", -1, 0, ctrl) + struct.pack("<II", flags1, 0x20) + struct.pack("<4f", 0, 0, 1, 1)
    b += sized(source) + bytes(4) + struct.pack("<4f", 0, 0, 1, 1)
    b += struct.pack("<4f", *color) + struct.pack("<ff", 1.0, 100.0) + sized(grey)
    return b


def v_scroll_controller(period, data_ref, interp_ref):
    return struct.pack("<iHffffi", -1, 72, 1.0, 0.0, 0.0, period, 0) + struct.pack("<iI", interp_ref, 8)


class EffectShaderTest(unittest.TestCase):
    def test_hearth_flame_reads_palette_flags_textures_colour_and_scroll(self):
        keys = struct.pack("<II", 2, 2) + struct.pack("<4f", 0, 0, 0, 0) + struct.pack("<4f", 5.667, 1, 0, 0)
        n = FakeNif([("BSEffectShaderProperty", effect_block(0xC0000078, ctrl=1)),
                     ("BSEffectShaderPropertyFloatController", v_scroll_controller(5.667, 3, 2)),
                     ("NiFloatInterpolator", struct.pack("<fi", 0.0, 3)), ("NiFloatData", keys)])
        info = skyrimfire.effect_shader(n, 0)
        self.assertTrue(info["palette_color"] and info["palette_alpha"] and info["vertex_alpha"])
        self.assertEqual(info["source"], "textures\\effects\\FXFireAtlas04.dds")
        self.assertEqual(info["greyscale"], "textures\\effects\\gradients\\GradFireExplosion.dds")
        self.assertEqual(info["emissive_color"][:3], [1.0, 0.5, 0.25])
        self.assertEqual(skyrimfire.uv_scroll(info["controllers"]), ("V", 1.0, 5.667))
        self.assertTrue(skyrimfire.is_fire_effect(info))

    def test_glow_and_magic_effects_are_not_flames(self):
        n = FakeNif([("BSEffectShaderProperty", effect_block(0x80000000, source=b"textures\\effects\\GlowSoft01.dds",
                                                             grey=b""))])
        info = skyrimfire.effect_shader(n, 0)
        self.assertFalse(info["palette_color"])
        self.assertFalse(skyrimfire.is_fire_effect(info))


class ParticleFlameTest(unittest.TestCase):
    CANDLE = {"name": "CandleFlame01", "textures": ["textures\\effects\\CandleFlame01.dds"], "modifiers": [
        {"type": "NiPSysBoxEmitter", "fields": {"speed": 7.5, "radius": 1.25, "life_span": 0.3333}},
        {"type": "BSPSysScaleModifier", "scales": [0.7, 1.0131, 0.2]},
        {"type": "BSPSysSimpleColorModifier", "fields": {"c2r": 1.0, "c2g": 1.0, "c2b": 1.0}}]}

    def test_candle_particles_become_one_card_sized_from_skyrim(self):
        f = skyrimfire.particle_flame(self.CANDLE)
        self.assertAlmostEqual(f["half_w"], 1.25 * 1.0131, places=4)
        self.assertAlmostEqual(f["lift"], 7.5 * 0.3333 * 0.5, places=4)
        self.assertGreater(f["half_h"], f["half_w"])
        self.assertEqual(f["color"], (1.0, 1.0, 1.0))

    def test_halo_and_smoke_are_left_out(self):
        glow = {"name": "CandleGlow01", "textures": ["textures\\effects\\CandleGlow01.dds"], "modifiers": [
            {"type": "NiPSysBoxEmitter", "fields": {"speed": 6, "radius": 80, "life_span": 0.4}}]}
        smoke = {"name": "smoke", "textures": ["textures\\effects\\SmokeParticles01.dds"], "modifiers": [
            {"type": "NiPSysCylinderEmitter", "fields": {"speed": 60, "radius": 10, "life_span": 2}}]}
        self.assertIsNone(skyrimfire.particle_flame(glow))
        self.assertIsNone(skyrimfire.particle_flame(smoke))


class CardsTest(unittest.TestCase):
    def test_cards_are_double_sided_with_winding_matching_normals_and_tip_at_v0(self):
        sh = skyrimfire.crossed_cards((10, 0, 20), 1.0, 2.0, planes=3)
        self.assertEqual(len(sh.positions), 24)
        self.assertEqual(len(sh.triangles), 12)
        P = np.array(sh.positions, float)
        for a, b, c in sh.triangles:
            face = np.cross(P[b] - P[a], P[c] - P[a])
            self.assertGreater(float(np.dot(face, sh.normals[a])), 0)
        for (u, v), p in zip(sh.uvs, sh.positions):
            self.assertEqual(v, 0.0 if p[2] > 20 else 1.0)
        self.assertAlmostEqual(P[:, 2].max(), 22.0)
        self.assertAlmostEqual(P[:, 0].mean(), 10.0)


class PaletteTest(unittest.TestCase):
    def test_grey_picks_palette_colour_and_alpha_then_tint(self):
        pal = np.zeros((2, 4, 4), np.uint8)
        pal[1] = [[0, 0, 0, 0], [255, 0, 0, 80], [0, 255, 0, 160], [0, 0, 255, 255]]
        tex = np.zeros((1, 2, 4), np.uint8)
        tex[0, 0] = [85, 85, 85, 255]           # grey 1/3 -> palette entry 1 (red); alpha 255 -> entry 3
        tex[0, 1] = [255, 255, 255, 0]          # grey 1 -> entry 3 (blue); alpha 0 -> entry 0
        out = skyrimfire.palette_bake(tex, pal, True, True, row=1.0, tint=(0.5, 1, 1))
        self.assertEqual(out[0, 0].tolist(), [128, 0, 0, 255])
        self.assertEqual(out[0, 1].tolist(), [0, 0, 255, 0])

    def test_without_palette_only_the_tint_applies(self):
        tex = np.full((1, 1, 4), 200, np.uint8)
        out = skyrimfire.palette_bake(tex, tex, False, False, tint=(0.5, 0.5, 0.5))
        self.assertEqual(out[0, 0].tolist(), [100, 100, 100, 200])


def fire_template():
    """The vanilla FiresGeneric layout, reduced (names, flipbook, texture set, summary)."""
    tex = {"Albedo": "Data\\Textures\\Fx_color.DDS", "Emissive": "Data\\Textures\\Fx_emissive.DDS",
           "Opacity": "Data\\Textures\\Fx_opacity.DDS"}
    return {"Import": ["materials/layered/shadermodels/1layereffectemissive.mat"], "Objects": [
        {"Components": [{"Data": {"Name": "FiresGeneric"}, "Index": 0, "Type": "BSComponentDB::CTName"},
                        {"Data": {"ID": "res:00000001:0005DB9C:A3FFF5AD"}, "Index": 0, "Type": "BSMaterial::LayerID"},
                        {"Data": {"BlendingMode": "SourceSoftAdditive", "EmissiveOnlyEffect": "true"}, "Index": 0,
                         "Type": "BSMaterial::EffectSettingsComponent"},
                        {"Data": {"AdaptiveEmittance": "true", "ExposureOffset": "8", "LuminousEmittance": "5000"},
                         "Index": 0, "Type": "BSMaterial::LayeredEmissivityComponent"}],
         "Parent": "materials/layered/shadermodels/1layereffectemissive.mat"},
        {"Components": [{"Data": {"Columns": "14", "IsAFlipbook": "true", "Rows": "14"}, "Index": 0,
                         "Type": "BSMaterial::FlipbookComponent"}], "ID": "res:00000002:0005DB9C:A3FFF5AD",
         "Parent": "res:84240012:0005AED3:A06346EA"},
        {"Components": [{"Data": {"FileName": tex["Albedo"]}, "Index": 0, "Type": "BSMaterial::MRTextureFile"},
                        {"Data": {"FileName": tex["Opacity"]}, "Index": 2, "Type": "BSMaterial::MRTextureFile"},
                        {"Data": {"FileName": tex["Emissive"]}, "Index": 7, "Type": "BSMaterial::MRTextureFile"}],
         "ID": "res:00000003:0005DB9C:A3FFF5AD", "Parent": "res:8424006B:0005AED3:A06346EA"}],
        "Summary": {"Layer1": {"Textures": {k: {"File": v} for k, v in tex.items()}}}, "Version": 1}


class EffectMaterialTest(unittest.TestCase):
    FILES = {"Albedo": "Data\\textures\\skyrim\\effects\\a_color.dds", "Emissive": "Data\\textures\\skyrim\\effects\\a_color.dds",
             "Opacity": "Data\\textures\\skyrim\\effects\\a_opacity.dds"}

    def comps(self, mat):
        return [c for o in mat["Objects"] for c in o["Components"]]

    def test_hearth_scroll_becomes_uvoffset_curve_and_flipbook_is_removed(self):
        mat = skyrimfire.effect_material(fire_template(), "S2S_Flame_x", self.FILES, kind="hearth",
                                         scroll=("V", 1.0, 5.667), vertex_color=True)
        types = [c["Type"] for c in self.comps(mat)]
        self.assertNotIn("BSMaterial::FlipbookComponent", types)
        files = [c["Data"]["FileName"] for c in self.comps(mat) if c["Type"] == "BSMaterial::MRTextureFile"]
        self.assertEqual(sorted(files), sorted(self.FILES.values()))
        ctrl = next(c for c in self.comps(mat) if c["Type"] == "BSBind::ControllerComponent")
        m, = ctrl["Data"]["upControllers"]["Data"]["Data"]["MappingsA"]["Data"]
        self.assertEqual(m["Data"]["Address"]["Data"]["Path"]["Data"], ["UVOffset"])
        c = m["Data"]["Controller"]["Data"]
        self.assertEqual(c["Type"], "BSBind::Float2DCurveController")
        y = c["Data"]["Curve"]["Data"]["YCurve"]["Data"]
        self.assertEqual([(k["Data"]["Input"], k["Data"]["Value"]) for k in y["Controls"]["Data"]],
                         [("0", "0"), ("5.667", "1")])
        self.assertEqual(y["InputDistance"], "5.667")
        self.assertIsNone(c["Data"]["Curve"]["Data"]["XCurve"]["Data"]["Controls"]["Data"])
        d = next(c for c in self.comps(mat) if c["Type"] == "BSBind::DirectoryComponent")
        self.assertIn("UVOffset", str(d))
        fx = next(c for c in self.comps(mat) if c["Type"] == "BSMaterial::EffectSettingsComponent")
        self.assertEqual(fx["Data"]["VertexColorBlend"], "true")

    def test_candle_flicker_drives_emissive_intensity_at_candle_emittance(self):
        mat = skyrimfire.effect_material(fire_template(), "S2S_Flame_c", self.FILES, kind="candle", flicker=1.0)
        em = next(c for c in self.comps(mat) if c["Type"] == "BSMaterial::LayeredEmissivityComponent")
        self.assertEqual(em["Data"], {"LuminousEmittance": "75000", "AdaptiveEmittance": "false"})
        ctrl = next(c for c in self.comps(mat) if c["Type"] == "BSBind::ControllerComponent")
        m, = ctrl["Data"]["upControllers"]["Data"]["Data"]["MappingsA"]["Data"]
        self.assertEqual(m["Data"]["Address"]["Data"]["Path"]["Data"], ["EmissiveIntensity"])
        vals = [float(k["Data"]["Value"]) for k in
                m["Data"]["Controller"]["Data"]["Data"]["Curve"]["Data"]["Controls"]["Data"]]
        self.assertEqual(max(vals), 75000.0)
        self.assertGreater(min(vals), 75000 * 0.6)

    def test_template_ids_are_renamed(self):
        mat = skyrimfire.effect_material(fire_template(), "S2S_Flame_x", self.FILES)
        self.assertNotIn("res:00000002:0005DB9C:A3FFF5AD", str(mat))


class AddonFlamesTest(unittest.TestCase):
    def test_cards_sit_at_each_addon_node_lifted_by_the_flame(self):
        from fo4sf import skyrimconvert
        conv = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        conv.addon_models = {49: "meshes\\mps\\mpscandleflame01.nif"}
        conv._addon_flames = {49: [{"texture": "textures\\effects\\CandleFlame01.dds", "half_w": 1.0, "half_h": 2.0,
                                    "lift": 1.25, "color": (1, 1, 1), "life": 0.33, "name": "CandleFlame01"}]}
        conv.flame_material = lambda *a, **k: "materials\\skyrim\\effects\\candleflame01_x.mat"
        orig = skyrimfire.addon_nodes
        skyrimfire.addon_nodes = lambda n: [(49, (21.3, 0.0, 127.0)), (49, (0.0, 21.3, 127.0)), (7, (0, 0, 0))]
        try:
            shapes, mats = conv.addon_flames(object())
        finally:
            skyrimfire.addon_nodes = orig
        self.assertEqual(len(shapes), 2)
        self.assertEqual(mats, ["materials\\skyrim\\effects\\candleflame01_x.mat"] * 2)
        P = np.array(shapes[0].positions)
        self.assertAlmostEqual(P[:, 0].mean(), 21.3, places=4)
        self.assertAlmostEqual(P[:, 2].mean(), 128.25, places=4)


if __name__ == "__main__":
    unittest.main()
