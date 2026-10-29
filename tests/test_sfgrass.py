"""Starfield grass records (fo4sf.sfgrass), scripts/terrain/grass_survey.py and scripts/terrain/skyrim_grass_native.py
on synthetic data only."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import sfgrass, sfplugin, skyrimgrass, textures  # noqa: E402


def dnam(density=10, lo=0, hi=60, flags=0x8, height=0.2, colour=0.1):
    return struct.pack("<7f4Bf2B", 1.0, 2.0, height, colour, 3.0, 4.0, 5.0, density, lo, hi, flags, 0.75, 10, 200)


def sf_esm(path):
    h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)   # noqa: E731
    recs = [(b"GRAS", h(b"GRAS"), [(b"EDID", b"GrassA\0"), (b"OBND", bytes(12)), (b"MODL", b"Plants\\a.nif\0"),
                                   (b"DNAM", dnam())], 0x10),
            (b"GCVR", h(b"GCVR"), [(b"EDID", b"CoverA\0"), (b"GNAM", struct.pack("<I", 0x10)),
                                   (b"DNAM", struct.pack("<h", -1)), (b"LNAM", struct.pack("<I", 0x30)),
                                   (b"YNAM", struct.pack("<f", 28.0))], 0x20),
            (b"BIOM", h(b"BIOM"), [(b"EDID", b"BiomeA\0"), (b"TNAM", struct.pack("<I", 0)),
                                   (b"LNAM", struct.pack("<3I", 7, 0x30, 0x20)), (b"TX16", b"x\0")], 0x40),
            (b"LTEX", h(b"LTEX"), [(b"EDID", b"LGrassSF\0")], 0x30),
            (b"LTEX", h(b"LTEX"), [(b"EDID", b"LSpare01\0")], 0x31),
            (b"WRLD", h(b"WRLD"), [(b"EDID", b"GreenWorld\0"), (b"BNAM", struct.pack("<I", 0x40)),
                                   (b"DATA", bytes([0x81])), (b"FNAM", bytes([0x08]))], 0x50)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))
    return path


class RecordTests(unittest.TestCase):
    def test_gras_dnam(self):
        d = sfgrass.parse_gras_dnam(dnam())
        self.assertEqual((d["max_density"], d["min_slope"], d["max_slope"], d["flags"]), (10, 0, 60, 8))
        self.assertAlmostEqual(d["coverage"], 0.75)
        self.assertEqual((d["dirtiness_min"], d["dirtiness_max"]), (10, 200))
        sky = skyrimgrass.parse_gras_data(struct.pack("<BBBBHHIffffB3x", 40, 5, 35, 0, 0, 0, 0, 32.0, 0.5, 0.25,
                                                      10.0, 6))
        out = sfgrass.parse_gras_dnam(sfgrass.gras_dnam_from_skyrim(dnam(), sky, 2.0))
        self.assertEqual((out["max_density"], out["min_slope"], out["max_slope"]), (80, 5, 35))
        self.assertEqual(out["flags"], 0x8 | 6)                     # Skyrim's bits in, Starfield's own kept
        self.assertAlmostEqual(out["height_range"], 0.5)
        self.assertAlmostEqual(out["colour_range"], 0.25)
        self.assertAlmostEqual(out["contrast"], 1.0)                # template-only fields untouched
        self.assertAlmostEqual(out["coverage"], 0.75)
        with self.assertRaises(ValueError):
            sfgrass.parse_gras_dnam(b"\0" * 20)

    def test_gcvr(self):
        t = [(b"EDID", b"T\0"), (b"GNAM", struct.pack("<I", 1)), (b"DNAM", struct.pack("<h", 5)),
             (b"LNAM", struct.pack("<I", 9)), (b"YNAM", struct.pack("<f", 28.0))]
        self.assertEqual(sfgrass.parse_gcvr(t), {"grasses": [(1, 5)], "ltex": [9], "threshold": 28.0})
        new = sfgrass.build_gcvr(t, b"New\0", [(0x100, -1), (0x101, 50)], [0x200], 40.0)
        self.assertEqual(new[0], (b"EDID", b"New\0"))
        self.assertEqual(sfgrass.parse_gcvr(new), {"grasses": [(0x100, -1), (0x101, 50)], "ltex": [0x200],
                                                   "threshold": 40.0})
        self.assertEqual(new[-1][0], b"YNAM")

    def test_biome(self):
        subs = [(b"EDID", b"B\0"), (b"TNAM", b"\0" * 4), (b"LNAM", struct.pack("<3I", 7, 0x30, 0x20)),
                (b"ANAM", struct.pack("<3I", 7, 0x31, 0)), (b"TX16", b"x\0")]
        out = sfgrass.biome_with_cover(subs, [(0x30, 0x99), (0x55, 0x98)])
        terr = sfgrass.biome_terrain(out)
        self.assertEqual([(e["kind"], e["mask"], e["ltex"], e["gcvr"]) for e in terr],
                         [("LNAM", 7, 0x30, 0x99), ("LNAM", 7, 0x55, 0x98), ("ANAM", 7, 0x31, 0)])
        every = sfgrass.biome_terrain(sfgrass.biome_with_cover(subs, [(0x55, 0x98)], masks=range(7)))
        self.assertEqual(sorted(e["mask"] for e in every if e["ltex"] == 0x55), list(range(7)))

    def test_cover_plan_only_on_spare_overrides(self):
        mapping = {"1": {"edid": "LFieldGrass01", "starfield": "SKYG_LFieldGrass01"},
                   "2": {"edid": "LTundra", "starfield": "LDirtFootprints01"},       # borrowed vanilla ground
                   "3": {"edid": "LDirt", "starfield": "SKYG_LDirt"},               # no grass in Skyrim
                   "4": {"edid": "LFieldGrass02", "starfield": "SKYG_LFieldGrass01"}}
        overrides = [{"form_id": 0x31, "skyrim": "LFieldGrass01"}, {"form_id": 0x32, "skyrim": "LDirt"}]
        ltex_grass = {0xA: [0x100, 0x101], 0xB: [0x102], 0xD: [0x101, 0x103]}
        sky = {0xA: "LFieldGrass01", 0xB: "LTundra", 0xC: "LDirt", 0xD: "LFieldGrass02"}
        plan = sfgrass.cover_plan(mapping, overrides, ltex_grass, sky)
        self.assertEqual(plan["slots"], {0x31: [0x100, 0x101, 0x103]})
        self.assertEqual([s["skyrim"] for s in plan["skipped"]], ["LTundra"])


class SurveyTests(unittest.TestCase):
    def test_survey_records(self):
        import grass_survey
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Data"))
            sf_esm(os.path.join(d, "Data", "Starfield.esm"))
            out = os.path.join(d, "s.json")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(grass_survey.main(["--starfield", d, "--out", out, "--plugin",
                                                    os.path.join(d, "Data", "Starfield.esm")]), 0)
            with open(out, encoding="utf-8") as fh:
                rep = json.load(fh)
        s = rep["summary"]
        self.assertEqual((s["grass_records"], s["ground_cover_records"], s["ltex_with_cover"]), (1, 1, 1))
        self.assertEqual(s["dnam_sizes"], {"38": 1})
        self.assertEqual(s["gcvr_used_by_biomes"], 1)
        self.assertEqual(s["example_gcvr"]["ltex"], ["LGrassSF"])
        self.assertEqual(rep["biomes"]["00000040"]["terrain"][0]["gcvr"], 0x20)
        self.assertEqual(rep["world_biome"], {"greenworld": "00000040"})
        self.assertTrue(s["our_worlds"]["Starfield.esm:GreenWorld"]["no_grass"])
        self.assertEqual(s["biome_masks"], {"7": 1})
        self.assertEqual((s["worlds"], s["worlds_no_grass"], s["worlds_allow_procgen"]), (1, 1, 1))
        self.assertEqual(rep["world_flags"]["GreenWorld"], {"data_flags": 0x81, "no_grass": True, "fnam_flags": 8,
                                                           "allow_procgen": True, "biome": "00000040"})

    def test_btd_painting_its_biomes_cover(self):
        import grass_survey
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(grass_survey, "btd_tables",
                                  return_value={"terrain/greenworld.btd": [0x31, 0x30], "terrain/other.btd": [0x30]}):
            os.makedirs(os.path.join(d, "Data"))
            sf_esm(os.path.join(d, "Data", "Starfield.esm"))
            out = os.path.join(d, "s.json")
            with contextlib.redirect_stdout(io.StringIO()):
                grass_survey.main(["--starfield", d, "--out", out])
            with open(out, encoding="utf-8") as fh:
                s = json.load(fh)["summary"]
        self.assertEqual(s["btds_painting_a_texture_their_biome_covers"], 1)        # greenworld's own biome
        self.assertEqual(s["btds_painting_a_texture_any_biome_covers"], 2)
        self.assertEqual(s["btds_without_a_world_biome"], 1)
        self.assertEqual(s["examples_own_biome"]["terrain/greenworld.btd"],
                         {"world_biome": "BiomeA", "ltex": ["LGrassSF"]})


class NativeBuildTests(unittest.TestCase):
    def test_end_to_end(self):
        import skyrim_grass_native as N
        import skyrim_fixtures as F
        lg = {0x77: [0x88]}
        gr = {0x88: dict(skyrimgrass.parse_gras_data(struct.pack("<BBBBHHIffffB3x", 30, 0, 40, 0, 0, 0, 0, 0.0,
                                                                  0.3, 0.2, 0.0, 4)),
                         edid="Fern", model="landscape\\plants\\fern01.nif")}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(skyrimgrass, "read_grass", return_value=(lg, gr)), \
                contextlib.redirect_stdout(io.StringIO()):
            sf = os.path.join(tmp, "Starfield")
            os.makedirs(os.path.join(sf, "Data"))
            os.makedirs(os.path.join(sf, "Tools"))
            sf_esm(os.path.join(sf, "Data", "Starfield.esm"))
            F.content_resources(os.path.join(sf, "Tools", "ContentResources.zip"))
            data = F.skyrim_data(os.path.join(tmp, "Data"))
            sky_esm = os.path.join(tmp, "Skyrim.esm")
            h = struct.pack("<4sIII", b"LTEX", 0, 0, 0) + bytes(8)
            with open(sky_esm, "wb") as fh:
                fh.write(sfplugin.build([(b"LTEX", h, [(b"EDID", b"LFernGround\0")], 0x77)],
                                        {"hedr_version": 1.71, "form_version": 44}, masters=()))
            terrain = os.path.join(tmp, "terrain")
            os.makedirs(terrain)
            with open(os.path.join(terrain, "overlays_params.json"), "w") as fh:
                json.dump({"ltex_overrides": [{"form_id": 0x31, "skyrim": "LFernGround"}],
                           "world_overrides": {"biome": "00000040"}}, fh)
            with open(os.path.join(terrain, "ltex_mapping.json"), "w") as fh:
                json.dump({"skyrim": {"119": {"edid": "LFernGround", "starfield": "SKYG_LFernGround"}}}, fh)
            out = os.path.join(tmp, "mod")
            rc = N.main(["--skyrim", sky_esm, "--skyrim-data", data, "--starfield", sf, "--terrain", terrain,
                         "--texconv", "texconv.exe", "--out", out, "--density-scale", "2", "--biome-masks", "0,4"])
            self.assertEqual(rc, 0)
            recs = sfplugin.records(os.path.join(out, N.PLUGIN), [b"GRAS", b"GCVR", b"BIOM"])
            with open(os.path.join(out, "grass_native.json"), encoding="utf-8") as fh:
                rep = json.load(fh)
        by = {sfplugin.edid(r[2]): r for r in recs}
        g = by["S2S_Fern"]
        d = sfgrass.parse_gras_dnam(dict(g[2])[b"DNAM"])
        self.assertEqual((d["max_density"], d["max_slope"], d["flags"] & 7), (60, 40, 4))
        self.assertEqual(dict(g[2])[b"MODL"], b"s2s\\grassnative\\landscape_plants_fern01.nif\0")
        cover = sfgrass.parse_gcvr(by["S2S_Cover_00000031"][2])
        self.assertEqual(cover["grasses"], [(g[3], -1)])
        self.assertEqual(cover["ltex"], [0x31])
        biome = by["BiomeA"]
        self.assertEqual(biome[3], 0x40)                                      # an override of the vanilla record
        added = [e["mask"] for e in sfgrass.biome_terrain(biome[2])
                 if (e["ltex"], e["gcvr"]) == (0x31, by["S2S_Cover_00000031"][3])]
        self.assertEqual(added, [0, 4])                                       # the world's biome, the asked masks
        self.assertEqual(rep["biome"]["edid"], "BiomeA")
        self.assertEqual(rep["templates"]["gras"], "GrassA")
        self.assertEqual(rep["failed"], {})


if __name__ == "__main__":
    unittest.main()
