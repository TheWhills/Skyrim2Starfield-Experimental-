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
        self.assertIn('conv.flame_style = getattr(a, "flame_style", "particles")', src)
        self.assertEqual(skyrimfire.FLAME_STYLES, ("skyrim", "starfield", "particles", "layered"))


class ParticleFireChoiceTest(unittest.TestCase):
    def test_chosen_fire_and_scale_reach_the_effects(self):
        from fo4sf import skyrimconvert
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        c.flame_style, c.particle_fire = "particles", [("004630", 0.6)]
        orig = skyrimfire.particle_systems
        skyrimfire.particle_systems = lambda n: [ParticleStyleTest.SYSTEM]
        try:
            fx = c.model_fire_effects(object())
        finally:
            skyrimfire.particle_systems = orig
        self.assertEqual((fx[0]["base"], fx[0]["scale"]), ("004630", 0.6))
        self.assertNotIn("choices", fx[0])
        c.particle_fire = [("004630", 1.0), ("20D560", 0.8)]
        skyrimfire.particle_systems = lambda n: [ParticleStyleTest.SYSTEM]
        try:
            fx = c.model_fire_effects(object())
        finally:
            skyrimfire.particle_systems = orig
        self.assertEqual(fx[0]["choices"], [{"base": "004630", "scale": 1.0}, {"base": "20D560", "scale": 0.8}])
        prog = open(os.path.join(HERE, "..", "dotnet", "PluginSpike", "Program.cs")).read()
        self.assertIn("fxRotation++ % fxKeys.Length", prog)
        cs = open(os.path.join(HERE, "..", "dotnet", "PluginSpike", "Program.cs")).read()
        self.assertIn("fxo.Scale = scale * fxScale", cs)


class SfFireProbeTest(unittest.TestCase):
    def test_fire_names_and_record_lines(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts", "interior"))
        import sf_fire_probe as P
        self.assertTrue(P.is_fire_name("FXCampfireLarge01"))
        self.assertTrue(P.is_fire_name("candlegen_c01_lit.nif"))
        self.assertFalse(P.is_fire_name("FireExtinguisher01"))
        self.assertFalse(P.is_fire_name("LaredoFirearms_Poster01"))
        self.assertEqual(P.printable(b"\x00\x01Effects\\fxemptynode.nif\x00ab"), "Effects\\fxemptynode.nif")
        lines = P.describe_record(b"ADDN", 0x123, [(b"EDID", b"MPSFire\x00"), (b"DATA", b"\x31\x00\x00\x00")])
        self.assertEqual(lines[0], "ADDN 00000123 MPSFire")
        self.assertIn("DATA [4] 31000000", lines[2])


class ParticleStyleTest(unittest.TestCase):
    """2026-11-15: hearths as Starfield's own particle fire (FireMed01) placed by the plugin builder."""
    SYSTEM = {"name": "FlamesSmall01", "textures": ["textures\\effects\\FXFireAtlas02.dds"],
              "origin": (0.0, 0.0, 7.99), "subtextures": [],
              "shader": {"emissive_color": [0.949, 0.729, 0.62, 1.0], "emissive_multiple": 1.5,
                         "palette_color": False, "palette_alpha": True, "greyscale": "g.dds"},
              "modifiers": [{"type": "NiPSysCylinderEmitter", "volume": [20.0, 0.07],
                             "fields": {"speed": 45.0, "radius": 16.0, "life_span": 0.4}}]}

    def conv(self, style):
        from fo4sf import skyrimconvert
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        c.flame_style = style
        c.fire_pattern = skyrimfire.FIRE_EFFECT
        return c

    def test_particles_style_places_firemed01_at_the_emitter_in_metres_and_no_cards(self):
        orig = skyrimfire.particle_systems
        skyrimfire.particle_systems = lambda n: [self.SYSTEM]
        try:
            c = self.conv("particles")
            fx = c.model_fire_effects(object())
            cards = c.model_flames(object())
            other = self.conv("skyrim").model_fire_effects(object())
        finally:
            skyrimfire.particle_systems = orig
        self.assertEqual(fx, [{"base": "1CEDAB", "scale": 0.8, "offset_m": [0.0, 0.0, round(7.99 / 70, 4)]}])
        self.assertEqual(cards, ([], []))
        self.assertEqual(other, [])

    def test_particles_style_drops_the_scrolling_flame_meshes_but_keeps_the_log_glow(self):
        mesh = FakeNif([("BSEffectShaderProperty", effect_block(0xC0000078))])
        glow = FakeNif([("BSEffectShaderProperty", effect_block(0x8C000038,
                                                                source=b"textures\\clutter\\woodfires\\WoodFires01_g.dds"))])
        c = self.conv("particles")
        c.flame_material = lambda *a, **k: "glow.mat"
        self.assertIsNone(c.skyrim_flame_material(mesh, 0))
        self.assertEqual(c.skyrim_flame_material(glow, 0), "glow.mat")

    def test_manifest_and_plugin_carry_sf_effects(self):
        src = open(os.path.join(HERE, "..", "scripts", "terrain", "make_skyrim_objects.py")).read()
        self.assertIn('items[-1]["sf_effects"] = r["sf_effects"]', src)
        cs = open(os.path.join(HERE, "..", "dotnet", "PluginSpike", "Program.cs")).read()
        self.assertIn('it.TryGetProperty("sf_effects"', cs)
        self.assertIn("effectsBySource.TryGetValue(srcModel", cs)


class StarfieldCandleTest(unittest.TestCase):
    """2026-11-16, owner: Starfield's candle flame, in Skyrim's thicker teardrop."""

    def test_candles_get_starfields_own_material_on_one_widened_card(self):
        from fo4sf import skyrimconvert
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        c.candle_style = "starfield"
        calls = []
        c.starfield_flame_material = lambda kind, keep_emittance=False: calls.append((kind, keep_emittance)) or "sf.mat"
        c.flame_material = lambda *a, **k: "skyrim.mat"
        shapes, mats = c.particle_flame_cards([FlameStyleTest.FLAME], (0, 0, 0), "candle")
        self.assertEqual(mats, ["sf.mat"])
        self.assertEqual(calls, [("candle", True)])
        P = np.array(shapes[0].positions)
        self.assertAlmostEqual(P[:, 2].max() - P[:, 2].min(), 2 * 2.0 * skyrimfire.SF_CANDLE_HEIGHT, places=4)
        self.assertAlmostEqual(float(np.hypot(P[:, 0], P[:, 1]).max()), 1.0 * skyrimfire.SF_CANDLE_WIDTH, places=4)
        hearth, _ = c.particle_flame_cards([FlameStyleTest.FLAME], (0, 0, 0), "hearth")
        self.assertEqual(len(hearth), 2)                     # hearths unaffected by the candle style

    def test_keep_emittance_leaves_the_vanilla_emissivity(self):
        mat = skyrimfire.effect_material(fire_template(), "S2S_Flame_c", {}, kind="candle",
                                         flipbook=(12, 12, 90.0), keep_emittance=True)
        em = next(c for o in mat["Objects"] for c in o["Components"]
                  if c["Type"] == "BSMaterial::LayeredEmissivityComponent")
        self.assertEqual(em["Data"], {"AdaptiveEmittance": "true", "ExposureOffset": "8", "LuminousEmittance": "5000"})
        ctrl = next(c for o in mat["Objects"] for c in o["Components"] if c["Type"] == "BSBind::ControllerComponent")
        paths = [m["Data"]["Address"]["Data"]["Path"]["Data"][0]
                 for m in ctrl["Data"]["upControllers"]["Data"]["Data"]["MappingsA"]["Data"]]
        self.assertEqual(paths, ["FlipbookAuto"])


def flame_mesh(n_ring=6):
    """A small radially symmetric Starfield-style flame mesh: x, y +-7, z +-8.46, vertex colours, UVs."""
    from fo4sf import sfmesh
    pts, uvs, cols, tris = [(0.0, 0.0, 8.46), (0.0, 0.0, -8.46)], [(0.5, 0.0), (0.5, 1.0)], [0xFF102030] * 2, []
    for k in range(n_ring):
        a = 2 * math.pi * k / n_ring
        pts.append((7.0 * math.cos(a), 7.0 * math.sin(a), 0.0))
        uvs.append((k / n_ring, 0.5))
        cols.append(0x80FFFFFF)
    for k in range(n_ring):
        a, b = 2 + k, 2 + (k + 1) % n_ring
        tris += [(0, a, b), (1, b, a)]
    m = sfmesh.SfMesh(version=2)
    m.scale, m.positions = sfmesh.encode_positions(pts)
    m.uv1 = [(sfmesh.float_to_half(u), sfmesh.float_to_half(v)) for u, v in uvs]
    m.colors = cols
    m.normals = [sfmesh.encode_packed(*((p[0] / 7.0, p[1] / 7.0, 0.0) if abs(p[2]) < 1 else (0, 0, 1 if p[2] > 0 else -1)),
                                      w=1 / 3) for p in pts]
    m.tangents = [sfmesh.encode_packed(0.0, 0.0, 1.0) for _p in pts]
    m.triangles = tris
    return m


class SfCandleMeshTest(unittest.TestCase):
    """2026-11-16, sf_firepit_probe: Starfield's candle flame is a 228-vertex mesh, not a card; its mesh carries
    Starfield's FireCandleFlame in Skyrim's teardrop."""

    def test_mesh_is_fitted_to_the_flame_box_with_colours_and_uvs(self):
        sh = skyrimfire.sf_flame_shape(flame_mesh(), (10.0, -4.0, 50.0), 3.0, 2.5, b"F")
        P = np.array(sh.positions)
        self.assertAlmostEqual(P[:, 0].max() - P[:, 0].min(), 6.0, places=2)
        self.assertAlmostEqual(P[:, 2].max() - P[:, 2].min(), 5.0, places=2)
        self.assertAlmostEqual((P[:, 2].max() + P[:, 2].min()) / 2, 50.0, places=2)
        self.assertAlmostEqual((P[:, 0].max() + P[:, 0].min()) / 2, 10.0, places=2)
        self.assertEqual(sh.colors[0], (0x10, 0x20, 0x30, 0xFF))           # BGRA u32 -> RGBA
        self.assertEqual(sh.colors[2], (255, 255, 255, 0x80))
        self.assertAlmostEqual(sh.uvs[1][1], 1.0, places=3)
        self.assertEqual(len(sh.triangles), 12)
        self.assertTrue(all(abs(math.hypot(*n) - 1) < 1e-6 for n in sh.normals))

    def test_candles_use_the_mesh_when_the_build_found_it(self):
        from fo4sf import skyrimconvert
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        c.candle_style = "starfield"
        c.sf_candle_mesh = flame_mesh()
        c.starfield_flame_material = lambda kind, keep_emittance=False: "sf.mat"
        shapes, mats = c.particle_flame_cards([FlameStyleTest.FLAME], (0, 0, 0), "candle")
        self.assertEqual(mats, ["sf.mat"])
        self.assertEqual(len(shapes[0].positions), 8)                     # the mesh, not 3 crossed cards (24)
        P = np.array(shapes[0].positions)
        self.assertAlmostEqual(P[:, 0].max(), 1.0 * skyrimfire.SF_CANDLE_WIDTH, places=2)
        self.assertAlmostEqual(P[:, 2].max() - P[:, 2].min(), 2 * 2.0 * skyrimfire.SF_CANDLE_HEIGHT, places=2)

    def test_mesh_path_is_read_from_the_named_shape(self):
        from fo4sf import nif as nifmod, sfnif
        sp, box = sfnif.bounds_from_points([(0, 0, 0), (1, 1, 1)])
        shapes = [sfnif.StaticShape(b"Exotic_Candle:0", b"aaaa\\bbbb", 3, 3, "wax.mat", sp, box),
                  sfnif.StaticShape(b"Flame:0", b"bc78\\1e5b", 3, 3, "flame.mat", sp, box)]
        data = nifmod.serialize(sfnif.build_static_nif(b"CandleGen_C01_Lit", shapes))
        self.assertEqual(skyrimfire.sf_shape_mesh_path(data), "geometries/bc78/1e5b.mesh")
        self.assertIsNone(skyrimfire.sf_shape_mesh_path(data, b"Glow:0"))

    def test_build_reads_the_mesh_only_for_starfield_candles(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts", "terrain"))
        import make_skyrim_objects as mso

        class A:
            candle_style, starfield_data = "skyrim", "nowhere"
        self.assertIsNone(mso.sf_candle_mesh(A()))
        A.candle_style, A.starfield_data = "starfield", None
        self.assertIsNone(mso.sf_candle_mesh(A()))
        A.starfield_data = "x"
        self.assertNotEqual(mso.flame_key(A(), "sf-candle-mesh"), mso.flame_key(A()))


class LayeredStyleTest(unittest.TestCase):
    """2026-11-16: Starfield has no fire-pit flame geometry (sf_firepit_probe); "layered" burns Skyrim's own hearth
    layout with Starfield's geometry fire material LayeredFireV2."""

    def test_card_uvs_stretch_to_0_1_per_piece(self):
        from fo4sf import nif as nifmod
        pos = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (5, 0, 0), (6, 0, 0), (6, 0, 1)]
        uvs = [(0.25, 0.5), (0.5, 0.5), (0.5, 0.0), (0.0, 0.2), (0.1, 0.2), (0.1, 0.1)]
        sh = nifmod.Fo4Shape(b"S", (0, 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0, -1, -1, -1, pos, uvs, [], [], [],
                             [(0, 1, 2), (3, 4, 5)], False)
        out = skyrimfire.normalize_card_uvs(sh)
        self.assertEqual([tuple(round(c, 6) for c in uv) for uv in out.uvs],
                         [(0, 1), (1, 1), (1, 0), (0, 1), (1, 1), (1, 0)])
        self.assertEqual(sh.uvs[0], (0.25, 0.5))                           # the original left alone

    def conv(self):
        from fo4sf import skyrimconvert
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        c.flame_style = "layered"
        c.fire_pattern = skyrimfire.FIRE_EFFECT
        c.layered_fire_material = lambda: "layered.mat"
        c.flame_material = lambda *a, **k: "glow.mat"
        return c

    def test_hearth_flame_meshes_and_particle_cards_take_the_layered_fire(self):
        mesh = FakeNif([("BSEffectShaderProperty", effect_block(0xC0000078))])
        glow = FakeNif([("BSEffectShaderProperty", effect_block(0x8C000038,
                                                                source=b"textures\\clutter\\woodfires\\WoodFires01_g.dds"))])
        c = self.conv()
        self.assertEqual(c.skyrim_flame_material(mesh, 0), "layered.mat")
        self.assertEqual(c.skyrim_flame_material(glow, 0), "glow.mat")      # the log glow keeps Skyrim's texture
        orig = skyrimfire.particle_systems
        skyrimfire.particle_systems = lambda n: [ParticleStyleTest.SYSTEM]
        try:
            shapes, mats = c.model_flames(object())
            fx = c.model_fire_effects(object())
        finally:
            skyrimfire.particle_systems = orig
        self.assertEqual(set(mats), {"layered.mat"})
        self.assertEqual(len(shapes), 5)                                  # emitter + ring of four
        self.assertEqual(fx, [])                                          # no particle fire placed
        candles, cmats = c.particle_flame_cards([FlameStyleTest.FLAME], (0, 0, 0), "candle")
        self.assertEqual(cmats, ["glow.mat"] * 2)                          # candles follow the candle style

    def test_layered_material_is_cloned_once_as_it_is_or_falls_back_to_the_vanilla_path(self):
        import tempfile, zipfile, json
        from fo4sf import skyrimconvert
        t = fire_template()
        with tempfile.TemporaryDirectory() as d:
            z = os.path.join(d, "cr.zip")
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr(skyrimfire.LAYERED_FIRE_MAT, json.dumps(t))
            c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
            c.content_resources, c.staging, c.prefix = z, d, "skyrim"
            c._materials, c.material_errors, c.stats = {}, {}, {}
            p = c.layered_fire_material()
            self.assertEqual(p, "materials\\skyrim\\effects\\sf_layeredfirev2.mat")
            self.assertIs(c.layered_fire_material(), p)
            self.assertIn(p, c._layered)
            self.assertEqual(c.stats["layered_fire"]["template"], skyrimfire.LAYERED_FIRE_MAT)
            written = open(os.path.join(d, *p.split("\\"))).read()
            self.assertIn("Data\\\\Textures\\\\Fx_emissive.DDS", written)   # its own textures kept
            self.assertIn('"LuminousEmittance" : "%s"' % skyrimfire.LAYERED_EMITTANCE["LuminousEmittance"], written)
            self.assertEqual(c.stats["layered_fire"]["emittance_set"], 1)
            em = next(cc["Data"] for o in json.loads(written)["Objects"] for cc in o["Components"]
                      if cc["Type"] == "BSMaterial::LayeredEmissivityComponent")
            tint = em["FirstLayerTint"]["Data"]["Value"]["Data"]
            self.assertEqual((float(tint["x"]), float(tint["y"]), float(tint["z"])), skyrimfire.LAYERED_TINT)
            self.assertGreater(skyrimfire.LAYERED_TINT[0], 2 * skyrimfire.LAYERED_TINT[1])   # orange, not white
            self.assertEqual(c.stats["layered_fire"]["emittance"], [{"AdaptiveEmittance": "true", "ExposureOffset": "8",
                                                                    "LuminousEmittance": "5000"}])   # the vanilla value
            c2 = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
            c2.content_resources, c2.staging, c2.prefix = os.path.join(d, "missing.zip"), d, "skyrim"
            c2._materials, c2.material_errors, c2.stats = {}, {}, {}
            self.assertEqual(c2.layered_fire_material(), skyrimfire.LAYERED_FIRE_MAT.replace("/", "\\"))
            self.assertIn("layeredfire", c2.material_errors)


class FireSpreadTest(unittest.TestCase):
    """2026-11-16, owner: "one fireball in a hearth ... not an actual fire across the hearth"."""

    def test_fires_run_along_the_long_side_of_the_fire_shapes(self):
        pts = [(-50.0, -10.0, 5.0), (50.0, 10.0, 30.0)]          # 100 units along x, 20 across
        spots = skyrimfire.fire_spots(pts, origin_z=8.0, spacing=24.5, max_n=4)
        self.assertEqual(len(spots), 4)
        self.assertEqual([round(p[0], 2) for p in spots], [-37.5, -12.5, 12.5, 37.5])
        self.assertTrue(all(p[1] == 0.0 and p[2] == 8.0 for p in spots))
        along_y = skyrimfire.fire_spots([(0, 0, 0), (10, 60, 0)], spacing=24.5)
        self.assertEqual(len(along_y), 2)
        self.assertEqual({p[0] for p in along_y}, {5.0})
        self.assertEqual(skyrimfire.fire_spots([(0, 0, 3), (5, 5, 9)]), [(2.5, 2.5, 3)])
        self.assertEqual(skyrimfire.fire_spots([]), [])

    def test_hearth_model_gets_several_smaller_fires_in_metres(self):
        from fo4sf import skyrimconvert
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        c.flame_style, c.particle_fire = "particles", [("1CEDAB", 0.8)]
        c._fire_shape_points = lambda src: [(-35.0, 0.0, 4.0), (35.0, 5.0, 40.0)]
        orig = skyrimfire.particle_systems
        skyrimfire.particle_systems = lambda n: [ParticleStyleTest.SYSTEM]
        try:
            fx = c.model_fire_effects(object())
        finally:
            skyrimfire.particle_systems = orig
        self.assertEqual(len(fx), 3)                         # 70 units / 24.5 -> 3
        self.assertEqual({e["scale"] for e in fx}, {round(0.8 * skyrimfire.SPREAD_SCALE, 3)})
        self.assertEqual({e["offset_m"][2] for e in fx}, {round(7.99 / 70, 4)})
        self.assertAlmostEqual(fx[0]["offset_m"][0], round(-70 / 3 / 70, 4), places=4)


class SfFirepitProbeTest(unittest.TestCase):
    def test_fire_materials_and_paths(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts", "interior"))
        import sf_firepit_probe as P
        b = (b"\x00Materials\\Effects\\Fires\\LayeredFireV3.mat\x00Materials\\SetDressing\\Stone01.mat\x00"
             b"Materials\\Effects\\Fires\\FiresGeneric_Sm_01_14x14.mat")
        self.assertEqual(P.fire_materials(b), ["Materials\\Effects\\Fires\\FiresGeneric_Sm_01_14x14.mat",
                                               "Materials\\Effects\\Fires\\LayeredFireV3.mat"])
        self.assertEqual(P.norm("Meshes/SetDressing/FirePit01.nif"), "setdressing\\firepit01.nif")
        self.assertEqual(P.norm("SetDressing\\FirePit01.nif"), "setdressing\\firepit01.nif")


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


class SoftCandleTest(unittest.TestCase):
    """2026-11-21, owner on Skyrim's candle cards: "the candles just look very low quality" (64 px frames, no glow)."""

    def test_atlas_is_a_smooth_flipbook(self):
        a = skyrimfire.procedural_flame_atlas()
        cols, rows = skyrimfire.SOFT_GRID
        fw, fh = skyrimfire.SOFT_FRAME
        self.assertEqual(a.shape, (rows * fh, cols * fw, 4))
        self.assertEqual(a.dtype, np.uint8)
        f0, f5 = a[:fh, :fw], a[fh:2 * fh, fw:2 * fw]
        for f in (f0, f5):
            # nothing at the card's edges (no box around the halo), the flame bright in the middle
            self.assertEqual(int(f[0, :, 3].max()) + int(f[-1, :, 3].max()) + int(f[:, 0, 3].max())
                             + int(f[:, -1, 3].max()), 0)
            self.assertGreater(int(f[fh // 2, fw // 2, 3]), 200)
        self.assertFalse(np.array_equal(f0, f5))                    # the flame moves through the loop
        # white-yellow core, orange-red rim: the core is brighter in blue than the rim (a hot centre)
        mid_row = f0[int(fh * 0.55)]
        lit = mid_row[mid_row[:, 3] > 60]
        self.assertGreater(int(lit[len(lit) // 2, 2]), int(lit[0, 2]) + 60)

    def test_flame_keeps_skyrims_size_inside_the_larger_card(self):
        f = skyrimfire.procedural_flame_frame(0.0)
        fh = f.shape[0]
        rows = np.nonzero(f[:, :, 3].max(1) > 120)[0]                # the flame body (the halo is fainter)
        span = (rows.max() - rows.min()) / fh                        # of the card's height
        want = skyrimfire.SOFT_FLAME_SCALE / skyrimfire.SOFT_CARD[1]
        self.assertGreater(span, want * 0.6)
        self.assertLess(span, want * 1.15)

    def test_candles_get_the_soft_flipbook_on_larger_cards(self):
        from fo4sf import skyrimconvert
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        c.candle_style = "soft"
        calls = []
        c.soft_candle_material = lambda period: calls.append(period) or "soft.mat"
        c.flame_material = lambda *a, **k: "skyrim.mat"
        shapes, mats = c.particle_flame_cards([FlameStyleTest.FLAME], (0, 0, 0), "candle")
        self.assertEqual(mats, ["soft.mat"])
        self.assertEqual(len(calls), 1)
        P = np.array(shapes[0].positions)
        self.assertAlmostEqual(P[:, 2].max() - P[:, 2].min(), 2 * 2.0 * skyrimfire.SOFT_CARD[1], places=4)
        self.assertAlmostEqual(float(np.hypot(P[:, 0], P[:, 1]).max()), 1.0 * skyrimfire.SOFT_CARD[0], places=4)
        hearth, _ = c.particle_flame_cards([FlameStyleTest.FLAME], (0, 0, 0), "hearth")
        self.assertEqual(len(hearth), 2)                             # hearths unaffected by the candle style

    def test_soft_material_written_once_with_flipbook_and_flicker(self):
        import json
        import shutil
        import tempfile
        from unittest import mock
        from fo4sf import skyrimconvert, textures
        c = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
        with tempfile.TemporaryDirectory() as tmp:
            c.staging, c.prefix, c.texconv, c.content_resources = tmp, "s2s", "texconv.exe", "cr.zip"
            c._materials, c.material_errors, c.stats, c._effect_template = {}, {}, {}, fire_template()
            published = []
            c._publish_texture = lambda src, dst, kind: published.append(os.path.basename(dst)) or \
                shutil.copy(src, dst)
            with mock.patch.object(textures, "texconv", lambda *a, **k: None):
                m1 = c.soft_candle_material(1.0)
                m2 = c.soft_candle_material(1.0)
                m3 = c.soft_candle_material(1.5)
            self.assertEqual(c.material_errors, {})
            self.assertEqual(m1, m2)
            self.assertNotEqual(m1, m3)
            self.assertEqual(sorted(published), ["s2s_candleflame_soft_color.dds", "s2s_candleflame_soft_opacity.dds"])
            with open(os.path.join(tmp, *m1.split("\\")), encoding="utf-8") as fh:
                mat = json.load(fh)
        comps = [c_ for o in mat["Objects"] for c_ in o["Components"]]
        fb = next(x for x in comps if x["Type"] == "BSMaterial::FlipbookComponent")["Data"]
        self.assertEqual((fb["Columns"], fb["Rows"], fb["FPS"]), ("4", "4", "16"))
        ctrl = next(x for x in comps if x["Type"] == "BSBind::ControllerComponent")
        paths = sorted(m["Data"]["Address"]["Data"]["Path"]["Data"][0]
                       for m in ctrl["Data"]["upControllers"]["Data"]["Data"]["MappingsA"]["Data"])
        self.assertEqual(paths, ["EmissiveIntensity", "FlipbookAuto"])
