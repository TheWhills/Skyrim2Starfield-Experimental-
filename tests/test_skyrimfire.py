import math
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

    def test_card_colour_includes_the_shaders_emissive_colour(self):
        f = skyrimfire.particle_flame(dict(self.CANDLE, emissive_color=[1.0, 0.6, 0.2]))
        self.assertEqual(f["color"], (1.0, 0.6, 0.2))
        self.assertEqual(f["grid"], (2, 2))                  # CandleFlame01: four flames in a 2 x 2 atlas

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
        self.assertEqual(em["Data"], skyrimfire.EMITTANCE["candle"])
        ctrl = next(c for c in self.comps(mat) if c["Type"] == "BSBind::ControllerComponent")
        m, = ctrl["Data"]["upControllers"]["Data"]["Data"]["MappingsA"]["Data"]
        self.assertEqual(m["Data"]["Address"]["Data"]["Path"]["Data"], ["EmissiveIntensity"])
        vals = [float(k["Data"]["Value"]) for k in
                m["Data"]["Controller"]["Data"]["Data"]["Curve"]["Data"]["Controls"]["Data"]]
        top = float(skyrimfire.EMITTANCE["candle"]["LuminousEmittance"])
        self.assertEqual(max(vals), top)
        self.assertGreater(min(vals), top * 0.6)

    def test_template_ids_are_renamed(self):
        mat = skyrimfire.effect_material(fire_template(), "S2S_Flame_x", self.FILES)
        self.assertNotIn("res:00000002:0005DB9C:A3FFF5AD", str(mat))


class AddonFlamesTest(unittest.TestCase):
    def test_cards_sit_at_each_addon_node_lifted_by_the_flame(self):
        from fo4sf import skyrimconvert
        conv = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        conv.addon_models = {49: "meshes\\mps\\mpscandleflame01.nif"}
        conv._addon_flames = {49: [{"texture": "textures\\effects\\CandleFlame01.dds", "half_w": 1.0, "half_h": 2.0,
                                    "lift": 1.25, "color": (1, 1, 1), "life": 0.33, "name": "CandleFlame01",
                                    "grid": (2, 2), "origin": (0.0, 0.0, 0.0), "spread": 0.0, "greyscale": "",
                                    "palette_color": False, "palette_alpha": False, "color_row": 1.0,
                                    "alpha_row": 1.0}]}
        calls = []
        conv.flame_material = lambda *a, **k: calls.append(k) or "materials\\skyrim\\effects\\candleflame01_x.mat"
        orig = skyrimfire.addon_nodes
        skyrimfire.addon_nodes = lambda n: [(49, (21.3, 0.0, 127.0)), (49, (0.0, 21.3, 127.0)), (7, (0, 0, 0))]
        try:
            shapes, mats = conv.addon_flames(object())
        finally:
            skyrimfire.addon_nodes = orig
        self.assertEqual(len(shapes), 4)                     # two candle nodes x two layers; node 7 is no flame
        self.assertEqual(mats, ["materials\\skyrim\\effects\\candleflame01_x.mat"] * 4)
        P = np.array(shapes[0].positions)
        self.assertAlmostEqual(P[:, 0].mean(), 21.3, places=4)
        self.assertAlmostEqual(P[:, 2].mean(), 128.25, places=4)
        fps = skyrimfire.FLIPBOOK_FPS["candle"]
        self.assertEqual(calls[0]["flipbook"], (2, 2, fps))
        self.assertEqual(calls[0]["kind"], "candle")
        L2 = skyrimfire.LAYER2
        self.assertEqual(calls[1]["flipbook"], (2, 2, round(fps * L2["fps"], 2)))     # second layer, own frame rate
        self.assertEqual([c["crossfade"][1] for c in calls[:2]], [0, 1])              # opposite phases
        P2 = np.array(shapes[1].positions)                                            # layer 2: smaller, higher
        self.assertAlmostEqual(P2[:, 2].max() - P2[:, 2].min(), 2 * 2.0 * L2["size"], places=4)
        self.assertAlmostEqual(P2[:, 2].mean(), 128.25 + L2["lift"] * 2.0, places=4)


class HearthV2Test(unittest.TestCase):
    """Owner's flame_textures run (2026-11-15): GradFireExplosion orange above, blue in its last rows; the hearth
    shaders' emissive colours are greys that pick the row."""
    HEARTH_MESH = {"emissive_color": [0.224, 0.224, 0.224, 1.0], "emissive_multiple": 1.75, "palette_color": True,
                   "palette_alpha": True, "greyscale": "textures\\effects\\gradients\\GradFireExplosion.dds"}

    def test_palette_mapped_flames_take_their_row_from_the_emissive_colour(self):
        b = skyrimfire.bake_params(self.HEARTH_MESH)
        self.assertAlmostEqual(b["color_row"], 0.224)
        self.assertEqual(b["alpha_row"], 1.0)
        self.assertEqual(b["tint"], (1.0, 1.0, 1.0))       # the multiple goes into the emittance, not the texture
        self.assertEqual(b["multiple"], 1.75)

    def test_unmapped_colour_is_tinted_by_emissive_colour(self):
        b = skyrimfire.bake_params({"emissive_color": [0.949, 0.729, 0.62, 1.0], "emissive_multiple": 1.5,
                                    "palette_color": False, "palette_alpha": True, "greyscale": "g.dds"})
        self.assertFalse(b["palette_color"])
        self.assertAlmostEqual(b["tint"][0], 0.949)
        self.assertEqual(b["multiple"], 1.5)

    def test_separate_colour_and_alpha_rows(self):
        pal = np.zeros((3, 2, 4), np.uint8)
        pal[0] = [[10, 0, 0, 0], [200, 100, 0, 0]]        # top: orange colours, no alpha
        pal[2] = [[0, 0, 200, 0], [0, 0, 255, 230]]       # bottom: blue, alpha ramp
        tex = np.array([[[255, 255, 255, 255]]], np.uint8)
        out = skyrimfire.palette_bake(tex, pal, True, True, row=0.0, alpha_row=1.0)
        self.assertEqual(out[0, 0].tolist(), [200, 100, 0, 230])

    def test_subtexture_offsets_found_by_shape(self):
        rects = [(0, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)]
        blk = bytes(17) + bytes([4]) + b"".join(struct.pack("<4f", *r) for r in rects) + struct.pack("<f", 1.0)
        found = skyrimfire.subtexture_offsets(blk)
        self.assertEqual(len(found), 4)
        self.assertEqual(skyrimfire.subtexture_grid({"subtextures": found}), (2, 2))
        self.assertEqual(skyrimfire.subtexture_grid({"textures": ["textures\\effects\\FXFireAtlas02.dds"]}), (4, 2))
        self.assertEqual(skyrimfire.subtexture_grid({"textures": ["x.dds"]}), (1, 1))

    def test_hearth_particles_become_five_cards_across_the_emitter(self):
        system = {"name": "FlamesSmall01", "textures": ["textures\\effects\\FXFireAtlas02.dds"],
                  "origin": (0.0, 0.0, 7.99), "subtextures": [],
                  "shader": {"emissive_color": [0.949, 0.729, 0.62, 1.0], "emissive_multiple": 1.5,
                             "palette_color": False, "palette_alpha": True,
                             "greyscale": "textures\\effects\\gradients\\GradFireExplosion.dds"},
                  "modifiers": [{"type": "NiPSysCylinderEmitter", "volume": [20.0, 0.07],
                                 "fields": {"speed": 45.0, "radius": 16.0, "life_span": 0.4}},
                                {"type": "BSPSysScaleModifier", "scales": [1.0, 1.0148, 0.5]}]}
        f = skyrimfire.particle_flame(system)
        self.assertIsNotNone(f)                              # radius 16: a flame, not a halo
        self.assertEqual(f["grid"], (4, 2))
        self.assertTrue(f["palette_alpha"] and not f["palette_color"])
        centres = skyrimfire.flame_card_centres(f)
        self.assertEqual(len(centres), 5)
        self.assertAlmostEqual(centres[0][2], 7.99 + 45 * 0.4 * 0.5, places=4)
        self.assertAlmostEqual(math.hypot(centres[1][0], centres[1][1]), 20.0 * skyrimfire.RING, places=4)

    def test_emittance_takes_skyrims_multiple_and_the_kind_scale(self):
        mat = skyrimfire.effect_material(fire_template(), "S2S_Flame_h", EffectMaterialTest.FILES, kind="hearth",
                                         multiple=1.75)
        em = next(c for o in mat["Objects"] for c in o["Components"]
                  if c["Type"] == "BSMaterial::LayeredEmissivityComponent")
        want = float(skyrimfire.EMITTANCE["hearth"]["LuminousEmittance"]) * 1.75 * skyrimfire.EMITTANCE_SCALE["hearth"]
        self.assertAlmostEqual(float(em["Data"]["LuminousEmittance"]), want, places=2)

    def test_crossfade_layers_mirror_each_other(self):
        a = skyrimfire.crossfade_controller(1.0, 0)["Data"]["Curve"]["Data"]["Controls"]["Data"]
        b = skyrimfire.crossfade_controller(1.0, 1)["Data"]["Curve"]["Data"]["Controls"]["Data"]
        va = [float(k["Data"]["Value"]) for k in a]
        vb = [float(k["Data"]["Value"]) for k in b]
        lo, hi = skyrimfire.CROSSFADE
        self.assertEqual(va, [hi, lo, hi])
        self.assertEqual(vb, [lo, hi, lo])
        mat = skyrimfire.effect_material(fire_template(), "S2S_Flame_x", EffectMaterialTest.FILES,
                                         flipbook=(2, 2, 12.0), crossfade=(1.0, 1))
        self.assertIn("OverallOpacity", str(mat))

    def test_mirrored_cards_flip_u_only(self):
        a = skyrimfire.crossed_cards((0, 0, 0), 1, 2)
        b = skyrimfire.crossed_cards((0, 0, 0), 1, 2, mirror=True, turn_deg=30)
        self.assertEqual([1 - u for u, _ in a.uvs], [u for u, _ in b.uvs])
        self.assertEqual([v for _, v in a.uvs], [v for _, v in b.uvs])
        self.assertAlmostEqual(b.positions[1][1], math.sin(math.radians(30)), places=6)

    def test_flipbook_material_plays_frames_on_a_timer(self):
        mat = skyrimfire.effect_material(fire_template(), "S2S_Flame_f", EffectMaterialTest.FILES, kind="hearth",
                                         flipbook=(4, 2, 10.0))
        comps = [c for o in mat["Objects"] for c in o["Components"]]
        fb = next(c for c in comps if c["Type"] == "BSMaterial::FlipbookComponent")
        self.assertEqual(fb["Data"], {"Columns": "4", "FPS": "10", "IsAFlipbook": "true", "Loops": "true", "Rows": "2"})
        ctrl = next(c for c in comps if c["Type"] == "BSBind::ControllerComponent")
        m, = ctrl["Data"]["upControllers"]["Data"]["Data"]["MappingsA"]["Data"]
        self.assertEqual(m["Data"]["Address"]["Data"]["Path"]["Data"], ["FlipbookAuto"])
        self.assertEqual(m["Data"]["Controller"]["Data"]["Type"], "BSBind::TimerController")


class DecodeDxtTest(unittest.TestCase):
    def dds(self, fourcc, blocks):
        return (b"DDS " + struct.pack("<7I", 124, 0, 4, 4, 0, 0, 1) + bytes(44) + struct.pack("<II4s", 32, 4, fourcc)
                + bytes(40) + blocks)

    def test_dxt5_colour_and_alpha(self):
        from fo4sf import textures
        alpha = bytes([255, 0]) + bytes([0x49, 0x92, 0x24, 0x49, 0x92, 0x24])     # every index 1 -> a1 = 0
        colour = struct.pack("<HHI", 0xF800, 0x001F, 0x55555555)                  # every index 1 -> c1 = blue
        img = textures.decode_dxt(self.dds(b"DXT5", alpha + colour))
        self.assertEqual(img.shape, (4, 4, 4))
        self.assertEqual(img[2, 1].tolist(), [0, 0, 255, 0])

    def test_dxt1_three_colour_mode_has_transparent_black(self):
        from fo4sf import textures
        img = textures.decode_dxt(self.dds(b"DXT1", struct.pack("<HHI", 0x001F, 0xF800, 0xFFFFFFFF)))
        self.assertEqual(img[0, 0].tolist(), [0, 0, 0, 0])


class FlameTexturesScriptTest(unittest.TestCase):
    def test_contact_sheet_helpers(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts", "interior"))
        import flame_textures
        img = np.zeros((4, 2, 3), np.uint8)
        self.assertEqual(flame_textures.fit(img, 8).shape, (8, 4, 3))
        rgba = np.full((1, 1, 4), 255, np.uint8)
        rgba[0, 0, 3] = 0
        self.assertEqual(flame_textures.over_black(rgba).tolist(), [[[0, 0, 0]]])
        sheet = flame_textures.row([np.zeros((3, 2, 3), np.uint8), np.zeros((3, 5, 3), np.uint8)])
        self.assertEqual(sheet.shape, (3, 11, 3))


class FlameStyleTest(unittest.TestCase):
    FLAME = {"texture": "textures\\effects\\CandleFlame01.dds", "half_w": 1.0, "half_h": 2.0, "lift": 1.25,
             "color": (1, 1, 1), "life": 0.33, "name": "CandleFlame01", "grid": (2, 2), "origin": (0.0, 0.0, 0.0),
             "spread": 0.0, "greyscale": "", "palette_color": False, "palette_alpha": False, "color_row": 1.0,
             "alpha_row": 1.0}

    def conv(self, style):
        from fo4sf import skyrimconvert
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        c.flame_style = style
        c.flame_material = lambda *a, **k: "skyrim.mat"
        c.starfield_flame_material = lambda kind: f"sf_{kind}.mat"
        return c

    def test_starfield_style_puts_starfields_flipbook_on_the_same_single_layer_cards(self):
        shapes, mats = self.conv("starfield").particle_flame_cards([self.FLAME], (5, 0, 100), "candle")
        self.assertEqual(mats, ["sf_candle.mat"])
        P = np.array(shapes[0].positions)
        self.assertAlmostEqual(P[:, 0].mean(), 5.0, places=4)
        self.assertAlmostEqual(P[:, 2].mean(), 101.25, places=4)

    def test_skyrim_style_keeps_two_layers(self):
        shapes, mats = self.conv("skyrim").particle_flame_cards([self.FLAME], (0, 0, 0), "candle")
        self.assertEqual(mats, ["skyrim.mat"] * 2)

    def test_starfield_candle_material_rebuilds_its_own_flipbook_timer(self):
        t = fire_template()
        t["Objects"][0]["Components"].insert(1, {"Data": {"x": 1}, "Index": 0, "Type": "BSBind::DirectoryComponent"})
        mat = skyrimfire.effect_material(t, "S2S_Flame_sf", {}, kind="candle", flipbook=(12, 12, 90.0), flicker=1.0)
        comps = [c for o in mat["Objects"] for c in o["Components"]]
        self.assertEqual(sum(c["Type"] == "BSBind::DirectoryComponent" for c in comps), 1)
        ctrl = next(c for c in comps if c["Type"] == "BSBind::ControllerComponent")
        paths = [m["Data"]["Address"]["Data"]["Path"]["Data"][0]
                 for m in ctrl["Data"]["upControllers"]["Data"]["Data"]["MappingsA"]["Data"]]
        self.assertEqual(paths, ["EmissiveIntensity", "FlipbookAuto"])
        files = [c["Data"]["FileName"] for c in comps if c["Type"] == "BSMaterial::MRTextureFile"]
        self.assertIn("Data\\Textures\\Fx_emissive.DDS", files)          # Starfield's own textures kept

    def test_flame_style_reaches_the_converter(self):
        src = open(os.path.join(HERE, "..", "scripts", "terrain", "make_skyrim_objects.py")).read()
        self.assertIn('conv.flame_style = getattr(a, "flame_style", "skyrim")', src)
        self.assertEqual(skyrimfire.FLAME_STYLES, ("skyrim", "starfield"))


class ParticleScanTest(unittest.TestCase):
    def test_finds_particle_block_types_in_the_header_only(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts", "interior"))
        import particle_scan
        head = b"Gamebryo File Format\x00" + b"\x0dNiPSysEmitter\x10NiParticleSystem\x06NiNode"
        self.assertEqual(particle_scan.particle_types(head), {"NiPSysEmitter", "NiParticleSystem"})
        self.assertEqual(particle_scan.particle_types(b"\x06NiNode\x0aBSGeometry"), set())
        late = b"\x06NiNode" + bytes(70000) + b"NiPSysData"
        self.assertEqual(particle_scan.particle_types(late), set())


if __name__ == "__main__":
    unittest.main()
