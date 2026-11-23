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
    recs = [(b"GRAS", h(b"GRAS"), [(b"EDID", b"GrassA\0"), (b"OBND", bytes(12)), (b"MODL", b"Plants\\a.nif\0"), (b"MODT", b"\x01\x02\x03\x04"),
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
                         "--texconv", "texconv.exe", "--out", out, "--density-scale", "2", "--biome-masks", "0,4",
                         "--biome", "world"])
            self.assertEqual(rc, 0)
            recs = sfplugin.records(os.path.join(out, N.PLUGIN), [b"GRAS", b"GCVR", b"BIOM"])
            with open(os.path.join(out, "grass_native.json"), encoding="utf-8") as fh:
                rep = json.load(fh)
        by = {sfplugin.edid(r[2]): r for r in recs}
        g = by["S2S_Fern"]
        d = sfgrass.parse_gras_dnam(dict(g[2])[b"DNAM"])
        self.assertEqual((d["max_density"], d["max_slope"], d["flags"] & 7), (60, 40, 4))
        self.assertEqual(dict(g[2])[b"MODL"], b"landscape\\grass\\s2s\\landscape_plants_fern01.nif\0")
        cover = sfgrass.parse_gcvr(by["S2S_Cover_00000031"][2])
        self.assertEqual(cover["grasses"], [(g[3], -1)])
        self.assertEqual(cover["ltex"], [])                                  # no texture list (vanilla covers have none)
        biome = by["BiomeA"]
        self.assertEqual(biome[3], 0x40)                                      # an override of the vanilla record
        added = [e["mask"] for e in sfgrass.biome_terrain(biome[2])
                 if (e["ltex"], e["gcvr"]) == (0x31, by["S2S_Cover_00000031"][3])]
        self.assertEqual(added, [0, 4])                                       # the world's biome, the asked masks
        self.assertEqual(rep["biome"]["edid"], "BiomeA")
        self.assertEqual(rep["templates"]["gras"], "GrassA")
        self.assertEqual(rep["failed"], {})



class PlanetBiomeTests(unittest.TestCase):
    """2026-11-22: the cover goes into the planet's own biome under the overlay (Nirn's ocean copy), and --control
    puts a vanilla cover on every converted texture."""

    def test_helpers(self):
        import skyrim_grass_native as N
        m = N.mapping_from_fids({0x77: 0x31, 0x78: 0x99}, {0x77: "LFernGround"}, [{"form_id": 0x31, "skyrim": "LFernGround"}])
        self.assertEqual(m["119"], {"edid": "LFernGround", "starfield": "SKYG_LFernGround"})
        self.assertEqual(m["120"]["starfield"], "00000099")                   # a vanilla LTEX: no cover later
        h = bytes(24)
        recs = [(b"BIOM", h, [(b"EDID", b"NirnLand\0")], 0x02000805),
                (b"BIOM", h, [(b"EDID", b"NirnOceanNoCoating\0")], 0x02000801),
                (b"BIOM", h, [(b"EDID", b"Vanilla\0")], 0x40)]
        self.assertEqual(N.location_biome(recs)[3], 0x02000801)
        self.assertIsNone(N.location_biome([recs[2]]))
        subs = [(b"LNAM", struct.pack("<3I", 0, 1, 0x20)), (b"LNAM", struct.pack("<3I", 1, 2, 0x20)),
                (b"LNAM", struct.pack("<3I", 1, 3, 0x21)), (b"LNAM", struct.pack("<3I", 1, 4, 0))]
        self.assertEqual(N.control_cover(subs), 0x20)

    def _setup(self, tmp):
        import skyrim_fixtures as F
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
        bh = struct.pack("<4sIII", b"BIOM", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
        with open(os.path.join(terrain, "Terr_Mars.esm"), "wb") as fh:
            fh.write(sfplugin.build([(b"BIOM", bh, [(b"EDID", b"NirnOceanNoCoating\0"),
                                                     (b"LNAM", struct.pack("<3I", 0, 0x30, 0))], 0x02000801)],
                                    {"hedr_version": 0.96, "form_version": 555},
                                    masters=("Starfield.esm", "Terr.esm")))
        wh = struct.pack("<4sIII", b"WRLD", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
        with open(os.path.join(terrain, "Terr.esm"), "wb") as fh:
            fh.write(sfplugin.build([(b"WRLD", wh, [(b"EDID", b"SKY_Tamriel\0"), (b"DATA", b"\x01")], 0x01000800)],
                                    {"hedr_version": 0.96, "form_version": 555}, masters=("Starfield.esm",)))
        with open(os.path.join(terrain, "overlays_params.json"), "w") as fh:
            json.dump({"plugin": "Terr.esm", "mars": {"plugin": "Terr_Mars.esm"}, "overlays": [{"world": "SKY_Tamriel"}],
                       "ltex_overrides": [{"form_id": 0x31, "skyrim": "LFernGround"}],
                       "world_overrides": {"biome": "00000040"}}, fh)
        with open(os.path.join(terrain, "ltex_mapping.json"), "w") as fh:
            json.dump({"skyrim": {"119": {"edid": "LFernGround", "starfield": "SKYG_LFernGround"}}}, fh)
        return sf, data, sky_esm, terrain

    def _run(self, extra):
        import skyrim_grass_native as N
        lg = {0x77: [0x88]}
        gr = {0x88: dict(skyrimgrass.parse_gras_data(struct.pack("<BBBBHHIffffB3x", 30, 0, 40, 0, 0, 0, 0, 0.0,
                                                                  0.3, 0.2, 0.0, 4)),
                         edid="Fern", model="landscape\\plants\\fern01.nif")}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(skyrimgrass, "read_grass", return_value=(lg, gr)), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            sf, data, sky_esm, terrain = self._setup(tmp)
            out = os.path.join(tmp, "mod")
            rc = N.main(["--skyrim", sky_esm, "--skyrim-data", data, "--starfield", sf, "--terrain", terrain,
                         "--texconv", "texconv.exe", "--out", out, "--biome-masks", "0,4"] + extra)
            self.assertEqual(rc, 0)
            with open(os.path.join(out, N.PLUGIN), "rb") as fh:
                raw = fh.read()
            recs = sfplugin.records(os.path.join(out, N.PLUGIN), [b"GRAS", b"GCVR", b"BIOM"])
        return raw, {sfplugin.edid(r[2]): r for r in recs}, log.getvalue()

    def test_planet_biome_default(self):
        raw, by, log = self._run([])
        self.assertIn(b"MAST\x0e\x00Starfield.esm\x00", raw)
        self.assertIn(b"Terr_Mars.esm", raw)
        cover = by["S2S_Cover_00000031"]
        self.assertEqual(cover[3] >> 24, 3)                                   # own records after three masters
        self.assertEqual(by["S2S_Fern"][3] >> 24, 3)
        biome = by["NirnOceanNoCoating"]
        self.assertEqual(biome[3], 0x02000801)                                # the planet plugin's own ocean biome
        terr = sfgrass.biome_terrain(biome[2])
        self.assertEqual([(e["mask"], e["gcvr"]) for e in terr if e["ltex"] == 0x31], [(0, cover[3]), (4, cover[3])])
        self.assertEqual(terr[0], {"kind": "LNAM", "mask": 0, "ltex": 0x30, "gcvr": 0})   # its own entry kept
        self.assertIn("load S2SGrass.esm after them", log)

    def test_control_with_procgen(self):
        raw, _by, log = self._run(["--control", "--allow-procgen"])
        import skyrim_grass_native as N
        self.assertIn("SKY_Tamriel (01000800): Allow ProcGen set", log)
        self.assertIn(b"FNAM\x01\x00\x08", raw)

    def test_with_material(self):
        """2026-11-23: a vanilla grass material on our converted geometry (name + MaterialID CRC)."""
        import skyrim_grass_native as N
        from fo4sf import nif as nifmod, sfnif
        sh = sfnif.StaticShape(b"Blade", b"aa\\bb", 30, 12, "materials\\s2s\\x.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        data = nifmod.serialize(sfnif.build_static_nif(b"Grass", [sh]))
        mat = "Materials\\Landscape\\Grass\\Flowers\\GrassFlowersHellebore01.mat"
        n = nifmod.parse(N.with_material(data, mat))
        prop = n.blocks[4]
        self.assertEqual(n.strings[struct.unpack_from("<i", prop, 0)[0]], mat.encode())
        self.assertEqual(struct.unpack_from("<I", n.blocks[3], 4)[0], sfnif.material_id(mat))
        self.assertEqual(n.blocks[2], nifmod.parse(data).blocks[2])          # geometry untouched

    def test_with_geometry(self):
        """2026-11-23: our NIF drawing a vanilla .mesh."""
        import skyrim_grass_native as N
        from fo4sf import nif as nifmod, sfnif
        sh = sfnif.StaticShape(b"Blade", b"aa\\bb", 30, 12, "materials\\s2s\\x.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        data = nifmod.serialize(sfnif.build_static_nif(b"Grass", [sh]))
        ref = sfnif.MeshRef(114, 68, 0x40, b"5787\\7c36")
        n = nifmod.parse(N.with_geometry(data, (ref, (0, 0, 1, 2), (0, 0, 1, 1, 1, 1))))
        g = sfnif.parse_bsgeometry(n.blocks[2])
        self.assertEqual((g.meshes[0].path, g.meshes[0].num_verts, g.sphere[3]), (b"5787\\7c36", 68, 2))
        self.assertEqual(n.blocks[4], nifmod.parse(data).blocks[4])          # material untouched

    def test_with_procgen(self):
        import skyrim_grass_native as N
        self.assertEqual(dict(N.with_procgen([(b"EDID", b"W\0"), (b"FNAM", b"\x01\x02")]))[b"FNAM"], b"\x09\x02")
        added = N.with_procgen([(b"EDID", b"W\0"), (b"DATA", b"\x01"), (b"BNAM", bytes(4))])
        self.assertEqual([sg for sg, _d in added], [b"EDID", b"DATA", b"FNAM", b"BNAM"])

    def test_known_cover_templates_and_vanilla_model(self):
        """2026-11-22: templates come from the cover that grew (the world biome's most used), and
        --keep-template-model keeps its grass's vanilla model."""
        raw, by, log = self._run(["--keep-template-model"])
        self.assertIn("templates: grass GrassA, cover CoverA (vanilla model kept)", log)
        self.assertEqual(dict(by["S2S_Fern"][2])[b"MODL"], b"Plants\\a.nif\0")
        cover = sfgrass.parse_gcvr(by["S2S_Cover_00000031"][2])
        self.assertEqual(cover["threshold"], 28.0)                         # the template cover's own threshold
        self.assertEqual(cover["ltex"], [])
        _raw, by2, _log = self._run(["--cover-textures"])
        self.assertEqual(sfgrass.parse_gcvr(by2["S2S_Cover_00000031"][2])["ltex"], [0x31])

    def test_vanilla_material_build(self):
        raw, by, log = self._run(["--vanilla-material", "Materials\\Landscape\\Grass\\V.mat"])
        self.assertIn("vanilla material Materials\\Landscape\\Grass\\V.mat", log)
        self.assertIn("S2S_Fern", by)

    def test_vanilla_geometry_build(self):
        import skyrim_grass_native as N
        from fo4sf import sfnif
        geo = (sfnif.MeshRef(6, 4, 0x40, b"aa\\bb"), (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        with mock.patch.object(N, "template_geometry", return_value=geo) as tg:
            _raw, by, log = self._run(["--vanilla-geometry"])
        tg.assert_called_once()
        self.assertIn("(our NIFs, the template's vanilla .mesh)", log)
        self.assertIn("S2S_Fern", by)

    def test_copy_template_nif_build(self):
        import skyrim_grass_native as N
        with mock.patch.object(N, "template_nif", return_value=b"NIFBYTES") as tn:
            _raw, by, log = self._run(["--copy-template-nif"])
        tn.assert_called_once()
        self.assertIn("(the template's NIF copied to our paths)", log)
        self.assertEqual(dict(by["S2S_Fern"][2])[b"MODL"], b"landscape\\grass\\s2s\\landscape_plants_fern01.nif\0")

    def test_drop_modt(self):
        _raw, by, _log = self._run(["--drop-modt"])
        self.assertNotIn(b"MODT", dict(by["S2S_Fern"][2]))
        _raw, by, _log = self._run([])
        self.assertIn(b"MODT", dict(by["S2S_Fern"][2]))                     # kept by default

    def test_path_variants(self):
        import skyrim_grass_native as N
        with mock.patch.object(N, "template_nif", side_effect=[b"A", b"B", b"C"]) as tn:
            _raw, by, log = self._run(["--path-variants"])
        self.assertEqual(tn.call_count, 3)
        self.assertEqual(dict(by["S2S_Fern"][2])[b"MODL"], b"Landscape\\Grass\\S2S_fern01.nif\0")   # first grass: variant 0
        self.assertIn("flowers (hellebore): 1 grasses at paths like Landscape\\Grass\\S2S_fern01.nif", log)

    def test_model_path(self):
        _raw, by, log = self._run(["--model-path", "Landscape\\Grass\\GrassMossMounds02.nif"])
        self.assertEqual(dict(by["S2S_Fern"][2])[b"MODL"], b"Landscape\\Grass\\GrassMossMounds02.nif\0")
        self.assertIn("every grass names Landscape\\Grass\\GrassMossMounds02.nif", log)

    def test_replace_vanilla(self):
        import skyrim_grass_native as N
        with mock.patch.object(N, "template_nif", return_value=b"HELLEBORE"):
            _raw, by, log = self._run(["--replace-vanilla", "Landscape\\Grass\\GrassMossMounds04.nif", "--loose"])
        self.assertEqual(dict(by["S2S_Fern"][2])[b"MODL"], b"Landscape\\Grass\\GrassMossMounds04.nif\0")
        self.assertIn("which our archive replaces with the template's NIF", log)
        self.assertIn("files: loose (meshes", log)

    def test_unused_grass_paths(self):
        import skyrim_grass_native as N
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_formats import build_ba2_v1_gnrl
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Starfield - Meshes01.ba2"), "wb") as fh:
                fh.write(build_ba2_v1_gnrl({"meshes\\landscape\\grass\\Used01.nif": b"a",
                                            "meshes\\landscape\\grass\\grass\\Spare01.nif": b"b",
                                            "meshes\\landscape\\grass\\Spare02.nif": b"c",
                                            "meshes\\setdressing\\Chair.nif": b"d"}))
            h = struct.pack("<4sIII", b"GRAS", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
            with open(os.path.join(d, "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build([(b"GRAS", h, [(b"EDID", b"G\0"), (b"MODL", b"Landscape\\Grass\\used01.nif\0")],
                                          0x10)], {"hedr_version": 0.96, "form_version": 555}, masters=()))
            free, shipped, used = N.unused_grass_paths(d)
        self.assertEqual(free, ["meshes\\landscape\\grass\\grass\\spare01.nif", "meshes\\landscape\\grass\\spare02.nif"])
        self.assertEqual((shipped, used), (3, 1))

    def test_vanilla_paths_build(self):
        import skyrim_grass_native as N
        import numpy as np
        pool = (["meshes\\landscape\\grass\\spare01.nif"], 5, 4)
        cells = {(0, 0): {0x77: np.ones((33, 33))}}
        with mock.patch.object(N, "unused_grass_paths", return_value=pool), \
                mock.patch.object(N, "world_cells", return_value=cells):
            _raw, by, log = self._run(["--vanilla-paths", "--loose"])
        self.assertIn("Fern -> meshes\\landscape\\grass\\spare01.nif", log)
        self.assertEqual(dict(by["S2S_Fern"][2])[b"MODL"], b"landscape\\grass\\spare01.nif\0")
        self.assertIn("5 shipped, 4 named by the game's records, 1 free", log)

    def test_vanilla_paths_skip_water_grass(self):
        """2026-11-23: underwater grasses go last for the few free paths."""
        import numpy as np
        import skyrim_grass_native as N
        data = struct.pack("<BBBBHHIffffB3x", 30, 0, 40, 0, 0, 0, 0, 0.0, 0.3, 0.2, 0.0, 4)
        lg = {0x77: [0x88, 0x89]}
        gr = {0x88: dict(skyrimgrass.parse_gras_data(data), edid="Fern", model="landscape\\plants\\fern01.nif"),
              0x89: dict(skyrimgrass.parse_gras_data(data), edid="WaterKelpGrass01",
                         model="landscape\\plants\\fern01.nif")}
        pool = (["meshes\\landscape\\grass\\spare01.nif"], 5, 4)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(skyrimgrass, "read_grass", return_value=(lg, gr)), \
                mock.patch.object(N, "unused_grass_paths", return_value=pool), \
                mock.patch.object(N, "world_cells", return_value={(0, 0): {0x77: np.ones((33, 33))}}), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            sf, data_dir, sky_esm, terrain = self._setup(tmp)
            N.main(["--skyrim", sky_esm, "--skyrim-data", data_dir, "--starfield", sf, "--terrain", terrain,
                    "--texconv", "texconv.exe", "--out", os.path.join(tmp, "mod"), "--vanilla-paths", "--loose"])
        self.assertIn("Fern -> meshes", log.getvalue())
        self.assertNotIn("WaterKelpGrass01 -> meshes", log.getvalue())

    def test_family_shared_coverage(self):
        import skyrim_grass_native as N
        self.assertEqual(N.family("TundraGrass04"), "tundragrass")
        self.assertEqual(N.family("SnowGrass01Forest"), "snowgrass")
        placed = [("ForestGrass01", "a.nif"), ("TundraGrass01", "b.nif")]
        self.assertEqual(N.shared_model("TundraGrass02", placed), "b.nif")
        self.assertEqual(N.shared_model("FieldGrass01", placed), "a.nif")          # commonest otherwise
        self.assertIsNone(N.shared_model("X", []))
        d = bytes(38)
        self.assertEqual(sfgrass.parse_gras_dnam(N.with_coverage(d, 100))["coverage"], 100.0)
        self.assertEqual(N.with_coverage(d, None), d)

    def test_vanilla_paths_share_when_full(self):
        """2026-11-23: past the free paths, a grass shares a converted model instead of failing."""
        import numpy as np
        import skyrim_grass_native as N
        data = struct.pack("<BBBBHHIffffB3x", 30, 0, 40, 0, 0, 0, 0, 0.0, 0.3, 0.2, 0.0, 4)
        lg = {0x77: [0x88, 0x89]}
        gr = {0x88: dict(skyrimgrass.parse_gras_data(data), edid="Fern01", model="landscape\\plants\\fern01.nif"),
              0x89: dict(skyrimgrass.parse_gras_data(data), edid="Fern02", model="landscape\\plants\\fern01.nif")}
        pool = (["meshes\\landscape\\grass\\spare01.nif"], 5, 4)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(skyrimgrass, "read_grass", return_value=(lg, gr)), \
                mock.patch.object(N, "unused_grass_paths", return_value=pool), \
                mock.patch.object(N, "world_cells", return_value={(0, 0): {0x77: np.ones((33, 33))}}), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            sf, data_dir, sky_esm, terrain = self._setup(tmp)
            out = os.path.join(tmp, "mod")
            N.main(["--skyrim", sky_esm, "--skyrim-data", data_dir, "--starfield", sf, "--terrain", terrain,
                    "--texconv", "texconv.exe", "--out", out, "--vanilla-paths", "--loose", "--coverage", "100"])
            recs = {sfplugin.edid(r[2]): r for r in sfplugin.records(os.path.join(out, N.PLUGIN), [b"GRAS"])}
        self.assertIn("Fern02 shares landscape\\grass\\spare01.nif", log.getvalue())
        self.assertNotIn("Fern02 ->", log.getvalue())
        self.assertEqual(dict(recs["S2S_Fern02"][2])[b"MODL"], dict(recs["S2S_Fern01"][2])[b"MODL"])
        self.assertEqual(sfgrass.parse_gras_dnam(dict(recs["S2S_Fern01"][2])[b"DNAM"])["coverage"], 100.0)

    def test_family_material(self):
        import skyrim_grass_native as N
        self.assertEqual(N.family_material("TundraGrass04"), "Materials\\Landscape\\Grass\\Bladed\\GrassFieldDried01.mat")
        self.assertEqual(N.family_material("Unknown01"), "Materials\\Landscape\\Grass\\Bladed\\GrassFieldLive01.mat")
        self.assertTrue(N.family_material("SnowGrass01Forest").endswith("GrassFieldDried01Snow.mat"))

    def test_family_material_overrides(self):
        import skyrim_grass_native as N
        o = N.parse_family_materials(["ForestGrass,fieldgrass=Bladed/GrassCityShort01.mat",
                                      "tundragrass=Materials\\Landscape\\Grass\\Bladed\\GrassSedge01"])
        self.assertEqual(o, {"forestgrass": "Bladed\\GrassCityShort01", "fieldgrass": "Bladed\\GrassCityShort01",
                             "tundragrass": "Bladed\\GrassSedge01"})
        self.assertEqual(N.family_material("ForestGrass02", o),
                         "Materials\\Landscape\\Grass\\Bladed\\GrassCityShort01.mat")
        self.assertTrue(N.family_material("TundraGrass01", o).endswith("Bladed\\GrassSedge01.mat"))
        self.assertTrue(N.family_material("RockGrass01", o).endswith("GrassFieldDried03.mat"))
        with self.assertRaises(ValueError):
            N.parse_family_materials(["forestgrass"])

    def test_one_path_per_family_and_auto_material(self):
        import numpy as np
        import skyrim_grass_native as N
        data = struct.pack("<BBBBHHIffffB3x", 30, 0, 40, 0, 0, 0, 0, 0.0, 0.3, 0.2, 0.0, 4)
        lg = {0x77: [0x88, 0x89]}
        gr = {0x88: dict(skyrimgrass.parse_gras_data(data), edid="TundraGrass01", model="landscape\\plants\\fern01.nif"),
              0x89: dict(skyrimgrass.parse_gras_data(data), edid="TundraGrass02", model="landscape\\plants\\fern01.nif")}
        pool = (["meshes\\landscape\\grass\\spare01.nif", "meshes\\landscape\\grass\\spare02.nif"], 5, 3)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(skyrimgrass, "read_grass", return_value=(lg, gr)), \
                mock.patch.object(N, "unused_grass_paths", return_value=pool), \
                mock.patch.object(N, "world_cells", return_value={(0, 0): {0x77: np.ones((33, 33))}}), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            sf, data_dir, sky_esm, terrain = self._setup(tmp)
            out = os.path.join(tmp, "mod")
            N.main(["--skyrim", sky_esm, "--skyrim-data", data_dir, "--starfield", sf, "--terrain", terrain,
                    "--texconv", "texconv.exe", "--out", out, "--vanilla-paths", "--loose", "--vanilla-material", "auto"])
            with open(os.path.join(out, "grass_native.json"), encoding="utf-8") as fh:
                rep = json.load(fh)
        self.assertIn("TundraGrass02 shares", log.getvalue())               # same family: no second path used
        self.assertEqual(list(rep["vanilla_paths"]), ["TundraGrass01"])
        self.assertTrue(rep["materials"]["TundraGrass01"].endswith("GrassFieldDried01.mat"))
        self.assertIn("[GrassFieldDried01.mat]", log.getvalue())           # the build names each family's material
        self.assertRegex(log.getvalue(), r"TundraGrass01 -> .*\d+ shape\(s\), \d+ tris, \d+ units tall")
        self.assertGreater(rep["model_info"]["TundraGrass01"]["tris"], 0)

    def test_model_from(self):
        import numpy as np
        import skyrim_grass_native as N
        self.assertEqual(N.parse_model_from(["fieldgrass,ForestGrass=SnowGrass01Forest"]),
                         {"fieldgrass": "SnowGrass01Forest", "forestgrass": "SnowGrass01Forest"})
        with self.assertRaises(ValueError):
            N.parse_model_from(["fieldgrass"])
        data = struct.pack("<BBBBHHIffffB3x", 30, 0, 40, 0, 0, 0, 0, 0.0, 0.3, 0.2, 0.0, 4)
        lg = {0x77: [0x88, 0x89]}
        gr = {0x88: dict(skyrimgrass.parse_gras_data(data), edid="SnowGrass01", model="landscape\\plants\\fern01.nif"),
              0x89: dict(skyrimgrass.parse_gras_data(data), edid="FieldGrass01", model="landscape\\plants\\fern01.nif")}
        pool = (["meshes\\landscape\\grass\\spare01.nif", "meshes\\landscape\\grass\\spare02.nif"], 5, 3)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(skyrimgrass, "read_grass", return_value=(lg, gr)), \
                mock.patch.object(N, "unused_grass_paths", return_value=pool), \
                mock.patch.object(N, "world_cells", return_value={(0, 0): {0x77: np.ones((33, 33))}}), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            sf, data_dir, sky_esm, terrain = self._setup(tmp)
            out = os.path.join(tmp, "mod")
            N.main(["--skyrim", sky_esm, "--skyrim-data", data_dir, "--starfield", sf, "--terrain", terrain,
                    "--texconv", "texconv.exe", "--out", out, "--vanilla-paths", "--loose", "--vanilla-material", "auto",
                    "--model-from", "fieldgrass=SnowGrass01"])
            with open(os.path.join(out, "grass_native.json"), encoding="utf-8") as fh:
                rep = json.load(fh)
        self.assertIn("FieldGrass01 uses SnowGrass01's model", log.getvalue())
        self.assertEqual(list(rep["vanilla_paths"]), ["SnowGrass01"])          # FieldGrass01 took no free path
        self.assertEqual(rep["grasses"]["FieldGrass01"]["model"], rep["grasses"]["SnowGrass01"]["model"])

    def test_model_info(self):
        import skyrim_grass_native as N
        from types import SimpleNamespace as NS
        a = NS(positions=[(0, 0, 0), (0, 0, 10)], triangles=[(0, 1, 1)], scale=2.0, translation=(0, 0, 5))
        b = NS(positions=[(0, 0, 3)], triangles=[], scale=1.0, translation=(0, 0, 0))
        i = N.model_info([a, b, b], [a, b])
        self.assertEqual((i["shapes"], i["dropped"], i["tris"], i["verts"]), (2, 1, 1, 3))
        self.assertAlmostEqual(i["height"], 25.0 - 3.0)
        self.assertEqual(N.info_text(i), "2 shape(s) (+1 dropped), 1 tris, 22 units tall")

    def test_grass_coverage(self):
        import numpy as np
        import skyrim_grass_native as N
        cells = {(0, 0): {1: np.full((33, 33), 0.5), 2: np.ones((33, 33))}, (1, 0): {2: np.ones((33, 33))}}
        cov = N.grass_coverage(cells, {1: [0xA, 0xB], 2: [0xB]})
        self.assertAlmostEqual(cov[0xA], 0.5 * 33 * 33)
        self.assertAlmostEqual(cov[0xB], 0.5 * 33 * 33 + 2 * 33 * 33)

    def test_loose_build(self):
        _raw, by, log = self._run(["--loose"])
        self.assertIn("files: loose (meshes", log)

    def test_control(self):
        raw, by, log = self._run(["--control"])
        self.assertNotIn("S2S_Fern", by)                                      # no Skyrim grass converted
        terr = sfgrass.biome_terrain(by["NirnOceanNoCoating"][2])
        self.assertEqual([(e["mask"], e["gcvr"]) for e in terr if e["ltex"] == 0x31], [(0, 0x20), (4, 0x20)])
        self.assertIn("control: vanilla ground cover CoverA", log)


if __name__ == "__main__":
    unittest.main()
