"""scripts/interior/fire_survey.py on synthetic data: a Skyrim candle (a LIGH with a model whose AddOnNode7 pulls in
an ADDN flame with an animated effect-shader card), a hearth (flame card, particles, a heat-haze plane, a light beside
it), placements counted in the batch and in all of Skyrim.esm; Starfield fire models' block types, its ADDN /
lights-with-model records and the material database's component types."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import bsa, nif, sfplugin, skyrimnif  # noqa: E402
from skyrim_fixtures import SseNif, starfield_meshes_ba2  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402
import fire_survey as F  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731
I = lambda v: struct.pack("<I", v)                                  # noqa: E731
FIRE_TEX = "textures\\effects\\fxfireatlas04.dds"


def effect_block(b, texture, emissive=(1.0, 0.6, 0.2, 1.0), mult=3.0, controller=-1):
    t = texture.encode()
    return b.add("BSEffectShaderProperty", struct.pack("<iIi", -1, 0, controller) + struct.pack("<II", 0, 0)
                 + struct.pack("<4f", 0, 0, 1, 1) + struct.pack("<I", len(t)) + t + bytes(4) + bytes(16)
                 + struct.pack("<4f", *emissive) + struct.pack("<f", mult) + bytes(16))


def candle_nif():
    b = SseNif()
    root = b.reserve("NiNode")
    add = b.reserve("BSValueNode")
    b.node(add, b"AddOnNode7", [])
    b.node(root, b"Candle", [add])
    return b.bytes()


def flame_nif():
    b = SseNif()
    root = b.reserve("NiNode")
    ctrl = b.add("BSEffectShaderPropertyFloatController", struct.pack("<i", -1) + bytes(24))
    effect_block(b, FIRE_TEX, controller=ctrl)
    b.node(root, b"Flame", [])
    return b.bytes()


def hearth_nif():
    b = SseNif()
    root = b.reserve("NiNode")
    effect_block(b, FIRE_TEX)
    b.add("NiParticleSystem", bytes(16))
    b.add("NiPSysSpawnModifier", bytes(8))
    b.add("BSLightingShaderProperty", struct.pack("<IiIiII", 1, -1, 0, -1, skyrimnif.SLSF1_REFRACTION, 0) + bytes(80))
    b.node(root, b"Hearth", [])
    return b.bytes()


def knife_nif():
    """A static effect-shader shape with a non-fire texture (2026-11-09: knives, forks and markers carried one)."""
    b = SseNif()
    root = b.reserve("NiNode")
    effect_block(b, "textures\\weapons\\iron\\knife_e.dds")
    b.node(root, b"Knife", [])
    return b.bytes()


def light(fid, edid, model=None, radius=280, color=(255, 160, 80), flicker=True):
    d = struct.pack("<iI", -1, radius) + bytes(color) + b"\0" + I(0x8 if flicker else 0) + struct.pack("<6f", 1, 90, 0, 0.3, 0.2, 0) + bytes(8)
    f = [(b"EDID", Z(edid))] + ([(b"MODL", Z(model))] if model else []) + [(b"DATA", d), (b"FNAM", struct.pack("<f", 1.5))]
    return rec(b"LIGH", fid, f)


def ref(fid, base, pos):
    return rec(b"REFR", fid, [(b"NAME", I(base)), (b"DATA", struct.pack("<6f", *pos, 0, 0, 0))])


def skyrim(d):
    data = os.path.join(d, "Skyrim")
    os.makedirs(data)
    with open(os.path.join(data, "Skyrim - Meshes0.bsa"), "wb") as fh:
        fh.write(bsa.build({"meshes\\clutter\\candle01.nif": candle_nif(), "meshes\\effects\\candleflame01.nif": flame_nif(),
                            "meshes\\clutter\\hearth01.nif": hearth_nif(), "meshes\\clutter\\knife01.nif": knife_nif(),
                            "meshes\\markers\\xmarkerheading.nif": flame_nif()}, version=105, compress=False))
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
    lights = [light(0x100, "CandleLight01", "Clutter\\Candle01.nif", 120), light(0x101, "FireLight", None, 560)]
    stat = rec(b"STAT", 0x110, [(b"EDID", Z("Hearth01")), (b"MODL", Z("Clutter\\Hearth01.nif"))])
    chair = rec(b"STAT", 0x111, [(b"EDID", Z("Chair")), (b"MODL", Z("Furniture\\Chair.nif"))])
    knife = rec(b"MISC", 0x112, [(b"EDID", Z("BasicKnife01")), (b"MODL", Z("Clutter\\Knife01.nif"))])
    marker = rec(b"STAT", 0x113, [(b"EDID", Z("XMarkerHeading")), (b"MODL", Z("Markers\\XMarkerHeading.nif"))])
    addn = rec(b"ADDN", 0x120, [(b"EDID", Z("FXCandleFlameAddon")), (b"MODL", Z("Effects\\CandleFlame01.nif")),
                                (b"DATA", I(7))])
    inn = rec(b"CELL", 0x500, [(b"EDID", Z("RiverwoodSleepingGiantInn"))])
    other = rec(b"CELL", 0x510, [(b"EDID", Z("WhiterunBanneredMare"))])
    in_inn = [ref(0x600, 0x100, (0, 0, 0)), ref(0x601, 0x100, (100, 0, 0)), ref(0x602, 0x110, (500, 0, 0)),
              ref(0x603, 0x101, (500, 70, 0)), ref(0x604, 0x111, (10, 10, 0)), ref(0x605, 0x112, (20, 0, 0)),
              ref(0x606, 0x113, (30, 0, 0))]
    in_other = [ref(0x700, 0x100, (0, 0, 0)), ref(0x701, 0x110, (0, 0, 0))]
    cells = grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [inn, grup(0x500, 6, [grup(0x500, 8, in_inn)]),
                                                      other, grup(0x510, 6, [grup(0x510, 8, in_other)])])])])
    esm = os.path.join(data, "Skyrim.esm")
    with open(esm, "wb") as fh:
        fh.write(tes4 + grup(b"LIGH", 0, lights) + grup(b"STAT", 0, [stat, chair, marker]) + grup(b"MISC", 0, [knife]) + grup(b"ADDN", 0, [addn]) + cells)
    return data, esm


def starfield(d):
    sf = os.path.join(d, "Starfield")
    data = os.path.join(sf, "Data")
    os.makedirs(data)
    n = nif.NifFile(user_version=12, bs_version=172)
    n.string_index(b"Materials\\SetDressing\\Candle_Flame.mat")
    n.add_block("NiNode", bytes(8))
    n.add_block("BSGeometry", bytes(8))
    n.footer = struct.pack("<Ii", 1, 0)
    starfield_meshes_ba2(os.path.join(data, "Starfield - Meshes01.ba2"),
                         {"meshes/setdressing/candles/candle_lit01.nif": nif.serialize(n),
                          "meshes/setdressing/chair01.nif": nif.serialize(n)})
    cdb = (b"BETH" + bytes(20) + b"BSMaterial::LayerID\0BSMaterial::FlipbookComponent\0Columns\0Rows\0FPS\0Loop\0"
           b"BSMaterial::EmissiveSettingsComponent\0EmissiveTint\0BSMaterial::UVStreamID\0")
    starfield_meshes_ba2(os.path.join(data, "Starfield - Materials.ba2"), {"materials/materialsbeta.cdb": cdb})
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
    recs = [rec(b"ADDN", 0x900, [(b"EDID", Z("FX_CandleFlame")), (b"MODL", Z("Effects\\CandleFlame.nif")), (b"DATA", I(3))]),
            rec(b"LIGH", 0x901, [(b"EDID", Z("LightCandleLit")), (b"MODL", Z("SetDressing\\Candle_Lit01.nif"))]),
            rec(b"LIGH", 0x902, [(b"EDID", Z("OmniPlain"))])]
    with open(os.path.join(data, "Starfield.esm"), "wb") as fh:
        fh.write(tes4 + grup(b"ADDN", 0, recs[:1]) + grup(b"LIGH", 0, recs[1:]))
    return sf


class FireTests(unittest.TestCase):
    def test_nif_effects(self):
        e = F.nif_effects(flame_nif())
        s = e["effect_shapes"][0]
        self.assertEqual(s["textures"], [FIRE_TEX])
        self.assertEqual(s["controllers"], ["BSEffectShaderPropertyFloatController"])
        self.assertEqual((s["emissive_color"], s["emissive_multiple"]), ([1.0, 0.6, 0.2, 1.0], 3.0))
        h = F.nif_effects(hearth_nif())
        self.assertEqual((h["particle_blocks"], h["refraction_shapes"]),
                         ({"NiParticleSystem": 1, "NiPSysSpawnModifier": 1}, 1))
        self.assertEqual(F.nif_effects(candle_nif())["addon_indices"], [7])

    def test_survey(self):
        with tempfile.TemporaryDirectory() as d:
            data, esm = skyrim(d)
            sf = starfield(d)
            out = os.path.join(d, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(F.main(["--skyrim", esm, "--skyrim-data", data, "--starfield", sf,
                                         "--cell", "RiverwoodSleepingGiantInn", "--out", out]), 0)
            with open(os.path.join(out, "fire_survey.json")) as fh:
                r = json.load(fh)
            with open(os.path.join(out, "fire_survey.md")) as fh:
                md = fh.read()
        by = {m["edid"]: m for m in r["skyrim"]["models"]}
        self.assertNotIn("Chair", by)                                     # no effects, not fire: left out
        self.assertNotIn("BasicKnife01", by)                              # a static non-fire effect card
        self.assertNotIn("XMarkerHeading", by)                            # editor marker (even with a flame card)
        c = by["CandleLight01"]
        self.assertEqual((c["placed"], c["placed_in_skyrim"], c["type"]), (2, 3, "LIGH"))
        self.assertEqual(c["light"]["radius_m"], 1.714)                       # 120 units
        self.assertTrue(c["light"]["flicker"])
        a = c["addons"][0]
        self.assertEqual((a["index"], a["addn"]), (7, "FXCandleFlameAddon"))
        self.assertEqual(a["effects"]["effect_shapes"][0]["controllers"], ["BSEffectShaderPropertyFloatController"])
        h = by["Hearth01"]
        self.assertEqual((h["placed"], h["placed_in_skyrim"]), (1, 2))
        self.assertEqual(h["nearest_light"]["edid"], "FireLight")
        self.assertEqual(h["nearest_light"]["median_m"], 1.0)
        self.assertEqual(h["nearest_light"]["radius_m"], 8.0)
        self.assertIn("NiParticleSystem", h["effects"]["particle_blocks"])
        self.assertEqual(r["skyrim"]["effect_textures"], {FIRE_TEX: 2})
        s = r["starfield"]
        self.assertEqual([m["path"] for m in s["models"]], ["meshes/setdressing/candles/candle_lit01.nif"])
        self.assertEqual(s["models"][0]["materials"], ["Materials\\SetDressing\\Candle_Flame.mat"])
        self.assertEqual(s["particle_block_models"], 0)
        self.assertIn("BSMaterial::FlipbookComponent", s["material_components"])
        self.assertIn("Columns", s["material_components_near"]["BSMaterial::FlipbookComponent"])
        self.assertEqual((s["addn_records"], s["lights_with_model"]), (1, 1))
        self.assertEqual(s["lights_with_model_fire"], [["LightCandleLit", "SetDressing\\Candle_Lit01.nif"]])
        self.assertIn("| CandleLight01 (Clutter\\Candle01.nif) | LIGH | 2 / 3 |", md)


if __name__ == "__main__":
    unittest.main()
