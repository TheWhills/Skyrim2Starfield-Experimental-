"""--skyrim-ground: Skyrim's own ground textures on spare Starfield LTEX records (synthetic data, texconv stubbed)."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import bsa, btd, landtex, skyrimground, textures  # noqa: E402
from skyrim_fixtures import content_resources, rgba_dds, starfield_meshes_ba2  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402
import test_landtex as TL  # noqa: E402

PLAIN = landtex.PLAIN_GROUND
USED, SPARE1, SPARE2, SPARE3, BIOME_ONLY = 0x00300001, 0x00300010, 0x00300011, 0x00300012, 0x00300013
BNAM = "Materials\\Terrain\\LDirtFootprints01.mat"


def starfield_esm(path):
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
    recs = [(PLAIN, "LDirtFootprints01"), (USED, "LGrassMeadow01"), (SPARE1, "LTestA"), (SPARE2, "LTestB"),
            (SPARE3, "LTestC"), (BIOME_ONLY, "LBiomeOnly")]
    ltex = grup(b"LTEX", 0, [rec(b"LTEX", f, [(b"EDID", e.encode() + b"\0"),
                                              (b"BNAM", (BNAM if f == PLAIN else "x.mat").encode() + b"\0")])
                             for f, e in recs])
    biom = grup(b"BIOM", 0, [rec(b"BIOM", 0x400, [(b"EDID", b"SomeBiome\0"), (b"LNAM", struct.pack("<I", BIOME_ONLY))])])
    with open(path, "wb") as f:
        f.write(tes4 + ltex + biom)


def vanilla_btd(ltex):
    return b"BTDB" + bytes(0x24) + struct.pack(f"<I{len(ltex)}I", len(ltex), *ltex) + bytes(32)


class GroundTests(unittest.TestCase):
    def test_free_slots_skip_vanilla_and_referenced(self):
        with tempfile.TemporaryDirectory() as tmp:
            starfield_esm(os.path.join(tmp, "Starfield.esm"))
            slots = skyrimground.free_slots(os.path.join(tmp, "Starfield.esm"), {USED: 3, PLAIN: 9})
        self.assertEqual(slots, [SPARE1, SPARE2, SPARE3])

    def test_plan_ranks_by_coverage_and_borrows_by_category(self):
        import numpy as np
        ltex = {1: {"edid": "LGrassA", "diffuse": "landscape\\grass01.dds"},
                2: {"edid": "LGrassB", "diffuse": "landscape\\grass02.dds"},
                3: {"edid": "LSnow", "diffuse": "landscape\\snow.dds"},
                4: {"edid": "LNoTex", "diffuse": ""}}
        cells = {(0, 0): {1: np.full((33, 33), 0.6), 2: np.full((33, 33), 0.1), 3: np.full((33, 33), 0.3),
                          4: np.full((33, 33), 0.5)}}
        chosen, fallback = skyrimground.plan(ltex, skyrimground.coverage(cells), [0xA, 0xB])
        self.assertEqual(chosen, [(1, 0xA), (3, 0xB)])
        self.assertEqual(fallback, {2: 1})
        self.assertEqual(skyrimground.bnam_for("materials\\skyrim\\ground\\x.mat", "Terrain\\a.mat"),
                         "skyrim\\ground\\x.mat")
        self.assertEqual(skyrimground.bnam_for("materials\\skyrim\\ground\\x.mat", BNAM),
                         "materials\\skyrim\\ground\\x.mat")

    def test_checker_dds(self):
        from fo4sf import textures as tx
        d = skyrimground.checker_dds(16, 2)
        h = tx.read_dds_header(d)
        px = d[h["data_offset"]:h["data_offset"] + 16 * 16 * 4]
        self.assertEqual((h["width"], h["height"]), (16, 16))
        self.assertEqual((px[:4], px[8 * 4:8 * 4 + 4]), (bytes([0, 255, 0, 255]), bytes([255, 0, 255, 255])))

    def test_overlay_build_with_skyrim_ground(self):
        self._build(test_mode=False)

    def test_test_mode_paints_the_checkerboard(self):
        out, so = self._build(test_mode=True)
        self.assertIn("TEST MODE", so)

    def _build(self, test_mode):
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        with tempfile.TemporaryDirectory() as tmp:
            sky = os.path.join(tmp, "SkyData")
            os.makedirs(sky)
            esm = TL.skyrim_esm(os.path.join(sky, "Skyrim.esm"))
            tex = {"textures\\" + p: rgba_dds() for p in ("landscape\\dirt02.dds", "landscape\\grass\\tundra01.dds",
                                                         "landscape\\snow01.dds", "landscape\\roads\\road01.dds")}
            with open(os.path.join(sky, "Skyrim - Textures0.bsa"), "wb") as f:
                f.write(bsa.build(tex, version=105, compress=False, embed_names=True))
            sfd = os.path.join(tmp, "SF")
            os.makedirs(sfd)
            starfield_esm(os.path.join(sfd, "Starfield.esm"))
            starfield_meshes_ba2(os.path.join(sfd, "Starfield - Terrain01.ba2"),
                                 {"terrain/a.btd": vanilla_btd([PLAIN, USED])})
            cr = os.path.join(tmp, "ContentResources.zip")
            # shaped like the owner's real template (Terrain1Layer, DirtFootprints01.mat): five slots + terrain settings
            tmpl = {"Objects": [{"Components": [{"Type": "BSComponentDB::CTName", "Data": {"Name": "t"}},
                                                {"Type": "BSMaterial::TerrainSettingsComponent",
                                                 "Data": {"MaxDisplacement": "0.24", "TilingDistance": "3.2"}}]},
                                {"Components": [{"Type": "BSMaterial::MRTextureFile", "Index": i, "Data": {"FileName": f}}
                                                for i, f in ((0, "terrain/a.dds"), (1, "terrain/n.dds"),
                                                             (3, "terrain/r.dds"), (5, "terrain/ao.dds"),
                                                             (6, "terrain/h.dds"))]}],
                    "Summary": {"Layer1": {"Textures": {"Albedo": {"File": "terrain/a.dds"},
                                                        "Normal": {"File": "terrain/n.dds"},
                                                        "Roughness": {"File": "terrain/r.dds"},
                                                        "AmbientOcclusion": {"File": "terrain/ao.dds"},
                                                        "Height": {"File": "terrain/h.dds"}}}}}
            content_resources(cr)                                        # the converter's own object templates
            with zipfile.ZipFile(cr, "a") as z:
                z.writestr("Materials/Terrain/LDirtFootprints01.mat", json.dumps(tmpl))
            out = os.path.join(tmp, "out")
            with mock.patch.object(cw, "ltex_source", return_value=([PLAIN], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                    mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                    contextlib.redirect_stdout(io.StringIO()) as so:
                sk.main(["build", "--skyrim", esm, "--sf-data", sfd, "--out", out, "--mask-writer", "builtin",
                         "--arrival", "", "--skyrim-ground", "--content-resources", cr, "--texconv", "texconv.exe",
                         "--skyrim-ground-max", "3"] + (["--skyrim-ground-test"] if test_mode else []))
            if test_mode:
                colours = [os.path.join(r, f) for r, _d, fs in os.walk(os.path.join(out, "Data", "textures"))
                           for f in fs if f.endswith("_color.dds") and "ground" in r.replace("\\", "/")]
                self.assertTrue(colours)
                self.assertTrue(all(open(c, "rb").read() == skyrimground.checker_dds() for c in colours))
            prm = json.load(open(os.path.join(out, "overlays_params.json")))
            t = btd.read(open(os.path.join(out, "Data", "Terrain", "SKY_Tamriel.btd"), "rb").read())
            ov = prm["ltex_overrides"]
            mats = [json.load(open(os.path.join(out, "Data", *("materials\\" + o["material"].split("materials\\", 1)[-1])
                                                .split("\\")))) for o in ov]
        self.assertEqual(len(ov), 3, so.getvalue())                      # 4 Skyrim textures, 3 spare records
        self.assertEqual(sorted(o["form_id"] for o in ov), [SPARE1, SPARE2, SPARE3])
        self.assertTrue(all(o["material"].lower().startswith("materials\\skyrim\\ground\\") for o in ov))
        self.assertTrue(set(o["form_id"] for o in ov) <= set(t.ltex))    # the BTD paints with the overridden records
        self.assertNotIn(BIOME_ONLY, t.ltex)
        for m in mats:                                                   # cloned from the plain ground's material
            files = [v["File"] for v in m["Summary"]["Layer1"]["Textures"].values()]
            self.assertTrue(all("skyrim/ground" in f.replace("\\", "/").lower() for f in files), files)
            comp = [c["Data"]["FileName"] for o in m["Objects"] for c in o["Components"]
                    if c["Type"] == "BSMaterial::MRTextureFile"]
            self.assertFalse([f for f in comp if f.startswith("terrain/")], comp)        # no vanilla map left
            self.assertTrue(any(f.lower().endswith("_flat_height.dds") for f in comp))
            ts = [c["Data"] for o in m["Objects"] for c in o["Components"]
                  if c["Type"] == "BSMaterial::TerrainSettingsComponent"]
            self.assertEqual(ts, [{"MaxDisplacement": "0", "TilingDistance": "9.75"}])
        return out, so.getvalue()



class PlanetTests(unittest.TestCase):
    def test_register_on_another_planet(self):
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        with tempfile.TemporaryDirectory() as tmp:
            esm = TL.skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            sfd = os.path.join(tmp, "SF")
            os.makedirs(sfd)
            starfield_esm(os.path.join(sfd, "Starfield.esm"))
            out = os.path.join(tmp, "out")
            base = ["build", "--skyrim", esm, "--sf-data", sfd, "--out", out, "--mask-writer", "builtin", "--arrival", ""]
            with mock.patch.object(cw, "ltex_source", return_value=([PLAIN], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                    contextlib.redirect_stdout(io.StringIO()):
                sk.main(base + ["--planet", "JemisonPlanetData", "--latlon", "-0.3", "-0.8606", "--biome", "1CBD6A",
                                "--climate", "24E982", "--location-parent", "01AB2B"])
                prm = json.load(open(os.path.join(out, "overlays_params.json")))
                with self.assertRaises(SystemExit):                        # a planet needs its spot
                    sk.main(base + ["--planet", "JemisonPlanetData"])
        self.assertEqual(prm["mars"]["planet"], "JemisonPlanetData")
        self.assertNotIn("templates", prm)                                 # the generic Mars records stay
        self.assertEqual(prm["world_overrides"], {"biome": "1CBD6A", "climate": "24E982"})
        self.assertEqual(prm["location_parent"], "01AB2B")
        self.assertEqual((prm["overlays"][0]["latitude"], prm["overlays"][0]["longitude"]), (-0.3, -0.8606))



class HeightOffsetTests(unittest.TestCase):
    def test_terrain_and_objects_lift_together(self):
        import make_cw_overlays as cw
        import make_skyrim_objects as mo
        import make_skyrim_overlay as sk
        hs = {}
        with tempfile.TemporaryDirectory() as tmp:
            esm = TL.skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            sfd = os.path.join(tmp, "SF")
            os.makedirs(sfd)
            starfield_esm(os.path.join(sfd, "Starfield.esm"))
            for off in (0.0, 200.0):
                out = os.path.join(tmp, f"out{off:g}")
                with mock.patch.object(cw, "ltex_source", return_value=([PLAIN], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                        contextlib.redirect_stdout(io.StringIO()):
                    sk.main(["build", "--skyrim", esm, "--sf-data", sfd, "--out", out, "--mask-writer", "builtin",
                             "--arrival", "", "--height-offset", f"{off:g}"])
                t = btd.read(open(os.path.join(out, "Data", "Terrain", "SKY_Tamriel.btd"), "rb").read())
                prm = json.load(open(os.path.join(out, "overlays_params.json")))
                hs[off] = (t.heights_m(), prm["overlays"][0])
        import numpy as np
        self.assertAlmostEqual(float(np.median(hs[200.0][0] - hs[0.0][0])), 200.0, delta=0.05)
        ov = hs[200.0][1]
        self.assertEqual(ov["height_offset_m"], 200.0)
        r, = mo.to_local([{"pos": [70.0, 140.0, 700.0]}], ov)
        self.assertAlmostEqual(r["pos"][2], 700.0 + 200.0 * 70.0)


if __name__ == "__main__":
    unittest.main()
