"""scripts/npc/npc_records.py, face_fit.py's real NPC pieces (--hairs-plugin) and hair_color_probe.py."""
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

from fo4sf import sfplugin  # noqa: E402
import npc_records as NR  # noqa: E402
import hair_color_probe as HP  # noqa: E402
import face_fit as FF  # noqa: E402

INFO = {"hedr_version": 0.96, "form_version": 555}
HDR = struct.pack("<4sIII", b"NPC_", 0, 0, 0) + bytes(8)


def zs(t):
    return sfplugin.zs(t)


def write_plugin(path, recs, masters=("Starfield.esm",)):
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, INFO, masters=masters))


class RecordTests(unittest.TestCase):
    def test_masters_and_hairs_index(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "S2SSkyrimHairs.esm")
            hd = lambda e, i: (b"HDPT", HDR.replace(b"NPC_", b"HDPT"), [(b"EDID", zs(e))], sfplugin.new_form_id(i, 2))
            write_plugin(p, [hd("S2S_HairFemaleNord01", 0), hd("S2S_HairFemaleNord01_strandsidg", 1),
                             hd("S2S_BeardNord05", 2), hd("VanillaThing", 3)], masters=("Starfield.esm", "S2SHair.esm"))
            self.assertEqual(NR.plugin_masters(p), ["Starfield.esm", "S2SHair.esm"])
            idx = NR.hairs_index(p)
            self.assertEqual(idx, {"hairfemalenord01": sfplugin.new_form_id(0, 2),
                                   "beardnord05": sfplugin.new_form_id(2, 2)})

    def test_with_parts_replaces_and_drops(self):
        sf_hdpt = {0x100: (b"HDPT", b"", [(b"PNAM", struct.pack("<I", 3))], 0x100),
                   0x200: (b"HDPT", b"", [(b"PNAM", struct.pack("<I", 4))], 0x200),
                   0x300: (b"HDPT", b"", [(b"PNAM", struct.pack("<I", 2))], 0x300)}
        part_type = lambda subs: struct.unpack_from("<I", subs[0][1], 0)[0]
        subs = [(b"EDID", zs("X")), (b"RNAM", b"\0" * 4), (b"PNAM", struct.pack("<I", 0x300)),
                (b"PNAM", struct.pack("<I", 0x100)), (b"PNAM", struct.pack("<I", 0x200)), (b"HCOL", zs("Brown"))]
        out = NR.with_parts(subs, sf_hdpt, {3: 0x03000801}, drop=[4], part_type=part_type)
        pn = [struct.unpack_from("<I", d, 0)[0] for s, d in out if s == b"PNAM"]
        self.assertEqual(pn, [0x300, 0x03000801])                 # eyes kept, hair ours, beard gone
        out = NR.with_parts([(b"RNAM", b"\0" * 4)], sf_hdpt, {3: 7, 4: 8}, part_type=part_type)
        self.assertEqual([s for s, _d in out], [b"RNAM", b"PNAM", b"PNAM"])

    def test_strings(self):
        data = b"Ralof\0Ysolda\0"
        raw = struct.pack("<II", 2, len(data)) + struct.pack("<IIII", 0x10, 0, 0x20, 6) + data
        st = NR.read_strings(raw)
        self.assertEqual(st, {0x10: "Ralof", 0x20: "Ysolda"})
        self.assertEqual(NR.npc_name({"edid": "Ralof", "full_name_id": 0x10}, st), "Ralof")
        self.assertEqual(NR.npc_name({"edid": "Nobody", "full_name_id": 0x99}, st), "Nobody")
        self.assertEqual(NR.read_strings(b""), {})

    def test_hair_color_match(self):
        sf = ["Black", "Brown", "BlackBrown", "DirtyBlonde", "SaltAndBrown", "Jet", "Copper", "Platinum", "Amber",
              "SaltAndPepper", "Auburn", "Grey", "White", "Violet", "Blue", "Blonde", "Ruby", "Teal"]   # the owner's run
        rgb = lambda e, c: {"edid": e, "rgba": c + (0,)}
        self.assertEqual(NR.match_hair_color(rgb("HairColor01", (200, 168, 105)), sf)[0], "Blonde")
        # the owner's run: Skyrim's RGB is a dark tint, its EditorID says the colour (Ralof came out red, then brown)
        self.assertEqual(NR.match_hair_color(rgb("HairColor03BrightBlond", (81, 77, 57)), sf)[0], "Blonde")
        self.assertEqual(NR.match_hair_color(rgb("HairColor06Auburn", (48, 35, 33)), sf)[0], "Auburn")
        self.assertEqual(NR.match_hair_color(rgb("HairColor02BrownDark", (40, 30, 20)), sf)[0], "BlackBrown")
        # 2026-11-13: Skyrim's own colour word names a Starfield colour: Grey stays Grey (was SaltAndPepper by its dark
        # tint, Hilde / Faendal black-haired in game)
        self.assertEqual(NR.match_hair_color(rgb("HairColor14Grey", (70, 75, 85)), sf + ["SaltAndPepper", "Grey"]),
                         ("Grey", "same colour name"))
        self.assertEqual(NR.match_hair_color(rgb("X", (90, 60, 40)), sf)[0], "Brown")
        self.assertEqual(NR.match_hair_color(rgb("X", (20, 18, 17)), sf)[0], "Black")
        self.assertEqual(NR.match_hair_color(rgb("X", (120, 40, 25)), sf)[0], "Auburn")
        self.assertEqual(NR.match_hair_color(rgb("X", (90, 60, 140)), sf)[0] in NR.NAME_RGB, True)  # never Violet
        self.assertEqual(NR.match_hair_color(rgb("X", (90, 60, 40)), sf, {"Ruby": [90, 60, 40]})[0], "Brown")
        names = ["Blonde01", "BrownDark02", "BrownLight03", "Red01", "Black01", "Grey01"]
        blonde = {"edid": "HairColor07Blonde", "rgba": (200, 170, 110, 0)}
        self.assertEqual(NR.match_hair_color(blonde, names)[0], "Blonde01")
        dark = {"edid": "HairColor03BrownDark", "rgba": (60, 40, 20, 0)}
        self.assertEqual(NR.match_hair_color(dark, names)[0], "BrownDark02")
        pal = {"Blonde01": [210, 180, 120], "Black01": [20, 18, 15], "Red01": [150, 40, 20]}
        got = NR.match_hair_color({"edid": "HairColor09", "rgba": (30, 25, 20, 0)}, names, pal)
        self.assertEqual(got, ("Black01", "rgb (palette)"))                    # no colour words: a measured palette
        self.assertEqual(NR.match_hair_color({"edid": "HairColorX", "rgba": None}, names)[0], None)
        self.assertEqual(NR.match_hair_color(None, names)[0], None)


class DressTests(unittest.TestCase):
    def test_npc_dress(self):
        sf_hdpt = {0x100: (b"HDPT", b"", [(b"PNAM", struct.pack("<I", 3))], 0x100),
                   0x200: (b"HDPT", b"", [(b"PNAM", struct.pack("<I", 4))], 0x200)}
        npc = {"form_id": 1, "edid": "Ralof", "head_parts": [0x50], "hair_color": 0x70, "template": None,
               "template_flags": 0}
        real = dict(sf_hdpt=sf_hdpt, hdpt={0x50: {"edid": "HairMaleNord03", "type": 3, "model": "", "extra_parts": []}},
                    clfm={0x70: {"edid": "HairColor05Blonde", "rgba": (190, 160, 100, 0)}},
                    names={"Blonde02", "Brown01"}, palette=None, index={"hairmalenord03": 0x03000805},
                    part_type=lambda subs: struct.unpack_from("<I", subs[0][1], 0)[0],
                    npc_parts=lambda n, h: {3: (h[0x50], [])},
                    with_hair_color=lambda subs, name: sfplugin.edit(subs, {b"HCOL": zs(name), b"FHCL": zs(name)}))
        subs = [(b"RNAM", b"\0" * 4), (b"PNAM", struct.pack("<I", 0x100)), (b"PNAM", struct.pack("<I", 0x200)),
                (b"HCOL", zs("Brown01"))]
        row = {}
        out = FF.npc_dress(subs, npc, {1: npc}, real, row)
        pn = [struct.unpack_from("<I", d, 0)[0] for s, d in out if s == b"PNAM"]
        self.assertEqual(pn, [0x03000805])                         # his Skyrim hair; the template's beard gone
        self.assertIn((b"HCOL", zs("Blonde02")), out)
        self.assertEqual(row["dressed"]["hair"]["skyrim"], "HairMaleNord03")
        self.assertEqual(row["dressed"]["hair_color"]["starfield"], "Blonde02")

    def test_template_prefers_a_voice(self):
        def npc(e, voice, fid):
            subs = [(b"EDID", zs(e)), (b"ACBS", struct.pack("<I", 1)), (b"RNAM", struct.pack("<I", 9)),
                    (b"FMSI", b"\0" * 4)]
            if voice:
                subs.append((b"VTCK", struct.pack("<I", 0x77)))
            return (b"NPC_", HDR, subs, fid)
        recs = [npc("Mute", False, 1), npc("Talker", True, 2)]
        self.assertEqual(sfplugin.edid(FF.pick_template(recs, 9, True)[2]), "Talker")
        self.assertEqual(sfplugin.edid(FF.pick_template(recs[:1], 9, True)[2]), "Mute")


class ProbeTests(unittest.TestCase):
    def test_names_records_hits_palette(self):
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Starfield.esm")
            npc = lambda e, h, i: (b"NPC_", HDR, [(b"EDID", zs(e)), (b"HCOL", zs(h)), (b"FHCL", zs(h))], 0x800 + i)
            clfm = (b"CLFM", HDR.replace(b"NPC_", b"CLFM"), [(b"EDID", zs("Blonde01")), (b"CNAM", bytes([220, 190, 130, 0]))],
                    0x900)
            write_plugin(esm, [npc("A", "Blonde01", 0), npc("B", "Brown02", 1), npc("C", "Blonde01", 2), clfm],
                         masters=())
            names = HP.npc_color_names(esm)
            self.assertEqual(names["hair"], {"Blonde01": 2, "Brown02": 1})
            recs = HP.color_records(esm, ["Blonde01", "Brown02"])
            self.assertEqual(recs[0]["rgba"][:3], [220, 190, 130])
            self.assertTrue(HP.matches("textures/actors/human/hair/HairColor_LUT.dds", []))
            self.assertTrue(HP.matches("textures/actors/hair/brown02_grad.dds", ["Brown02"]))
            self.assertFalse(HP.matches("textures/lod/shrubyucca01_color.dds", ["Ruby"]))     # the first run's mistake
            self.assertFalse(HP.matches("textures/x/brown02_grad.dds", ["Brown02"]))          # not under a hair folder
            self.assertFalse(HP.matches("textures/x/rock.dds", ["Brown02"]))
            cr = os.path.join(d, "ContentResources.zip")
            with zipfile.ZipFile(cr, "w") as z:
                z.writestr("materials/actors/hair/haircolor_brown02.mat",
                           json.dumps({"x": {"FileName": "Data\\textures\\hair\\brown02_ramp.dds"}}))
                z.writestr("materials/rock.mat", "{}")
            mats = HP.material_hits(cr, ["Brown02"])
            self.assertEqual(len(mats), 1)
            self.assertEqual(mats[0]["textures"], ["Data\\textures\\hair\\brown02_ramp.dds"])
            pal = HP.palette_from(["Blonde01", "Brown02", "Red9"], recs,
                                  [{"path": "textures/hair/brown02_ramp.dds", "mean_rgb": [90, 60, 30]},
                                   {"path": "textures/lod/shrubred9yucca.dds", "mean_rgb": [1, 2, 3]}])
            self.assertEqual(pal, {"Blonde01": [220, 190, 130], "Brown02": [90, 60, 30]})


class GradientTests(unittest.TestCase):
    """2026-11-13: the looks menu's hair colours are gradient textures named per hairstyle group in AVMD records."""

    def test_gradient_textures_palette_and_decode(self):
        def avmd(edid, pairs):
            subs = [(b"EDID", zs(edid)), (b"MNAM", struct.pack("<I", 1))]
            for n, v in pairs:
                subs += [(b"LNAM", zs(n)), (b"VNAM", zs(v)), (b"NNAM", bytes(4))]
            return (b"AVMD", HDR, subs, 0)
        recs = [avmd("SimpleGroup_Hair_Long_Straight", [("Grey", "textures/h/ls_grey_color.dds"),
                                                         ("White", "textures/h/ls_white_color.dds")]),
                avmd("ComplexGroup_HairColor", [("Hair_Long_Straight", "SimpleGroup_Hair_Long_Straight")]),
                avmd("SimpleGroup_Accents2_color", [("Bags", "textures/x.dds")])]
        groups = HP.gradient_textures(recs)
        self.assertEqual(groups, {"Long_Straight": [("Grey", "textures/h/ls_grey_color.dds"),
                                                    ("White", "textures/h/ls_white_color.dds")]})
        import numpy as np
        ramp = np.zeros((4, 32, 4), np.uint8)
        ramp[:, :, :3] = np.linspace(0, 248, 32)[None, :, None].astype(np.uint8)
        prof = HP.gradient_profile(ramp, samples=4)
        self.assertEqual([p[0] for p in prof], [0, 80, 168, 248])
        import hair_probe
        old = hair_probe.decode_rgba, hair_probe.write_png
        hair_probe.decode_rgba = lambda raw, texconv: ramp // (2 if raw == b"grey" else 1)
        hair_probe.write_png = lambda path, px: None
        try:
            with tempfile.TemporaryDirectory() as d:
                files = {"textures/h/ls_grey_color.dds": b"grey", "textures/h/ls_white_color.dds": b"white"}
                grads = HP.decode_gradients(dict(groups, Short=[("Grey", "textures/h/missing.dds")]),
                                            files.get, "texconv.exe", d)
        finally:
            hair_probe.decode_rgba, hair_probe.write_png = old
        self.assertEqual(grads["Short"]["Grey"]["error"], "not found in the archives")
        ls = grads["Long_Straight"]
        self.assertLess(ls["Grey"]["lightness"], ls["White"]["lightness"])
        self.assertEqual(len(ls["White"]["profile"]), 16)
        pal = HP.gradient_palette(grads, "long_straight")
        self.assertEqual(sorted(pal), ["Grey", "White"])
        self.assertEqual(HP.gradient_palette(grads, "Afro"), {})


if __name__ == "__main__":
    unittest.main()
