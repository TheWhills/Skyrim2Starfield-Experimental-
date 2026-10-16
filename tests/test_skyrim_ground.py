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
            if not test_mode:                                # the ground colour has no alpha left
                from fo4sf import textures as tx
                import numpy as np
                cols = [os.path.join(r, f) for r, _d, fs in os.walk(os.path.join(out, "Data", "textures"))
                        for f in fs if f.endswith("_color.dds") and "ground" in r.replace("\\", "/")]
                self.assertTrue(cols)
                for c in cols:
                    d = open(c, "rb").read()
                    h = tx.read_dds_header(d)
                    px = np.frombuffer(d[h["data_offset"]:h["data_offset"] + h["width"] * h["height"] * 4], np.uint8)
                    self.assertEqual(int(px.reshape(-1, 4)[:, 3].max()), 0)        # default: alpha zero
            if test_mode:
                colours = [os.path.join(r, f) for r, _d, fs in os.walk(os.path.join(out, "Data", "textures"))
                           for f in fs if f.endswith("_color.dds") and "ground" in r.replace("\\", "/")]
                self.assertTrue(colours)
                from fo4sf import textures as tx2

                def rgb(d):
                    h = tx2.read_dds_header(d)
                    return d[h["data_offset"]:h["data_offset"] + h["width"] * h["height"] * 4][0::4][:64], \
                        d[h["data_offset"]:h["data_offset"] + h["width"] * h["height"] * 4][1::4][:64]
                self.assertTrue(all(rgb(open(c, "rb").read()) == rgb(skyrimground.checker_dds()) for c in colours))
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
            self.assertEqual([f for f in files if "skyrim/ground" not in f.replace("\\", "/").lower()],
                             ["terrain/r.dds"], files)
            comp = [c["Data"]["FileName"] for o in m["Objects"] for c in o["Components"]
                    if c["Type"] == "BSMaterial::MRTextureFile"]
            self.assertEqual([f for f in comp if f.startswith("terrain/")], ["terrain/r.dds"], comp)   # only roughness
            self.assertTrue(any(f.lower().endswith("_height.dds") and "_flat_" not in f.lower() for f in comp), comp)
            self.assertTrue(any(f.lower().endswith("_flat_ao.dds") for f in comp))
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



class HeightMapTests(unittest.TestCase):
    def test_height_from_diffuse_is_centred_detail(self):
        import numpy as np
        from fo4sf import textures as tx
        rng = np.random.default_rng(1)
        px = np.zeros((64, 64, 4), np.uint8)
        px[..., :3] = (200 + rng.integers(-40, 40, (64, 64, 1))).clip(0, 255)   # bright (snow-like) with detail
        px[..., 3] = 255
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "s.dds")
            tx.write_dds_dx10(src, 64, 64, tx.DXGI_R8G8B8A8_UNORM, px.tobytes(), 4)
            dst = os.path.join(tmp, "out", "h.dds")
            with mock.patch.object(textures, "texconv", lambda *a, **k: None):
                skyrimground.height_from_diffuse(open(src, "rb").read(), "texconv", dst, size=32)
            d = open(dst, "rb").read()
        h = tx.read_dds_header(d)
        v = np.frombuffer(d[h["data_offset"]:h["data_offset"] + h["width"] * h["height"]], np.uint8)
        self.assertEqual((h["width"], h["height"]), (32, 32))
        self.assertAlmostEqual(float(v.mean()), 128.0, delta=4.0)     # brightness removed: no texture always "on top"
        self.assertGreater(float(v.std()), 20.0)


class ColourTestTests(unittest.TestCase):
    def test_parse_and_colour_dds(self):
        from fo4sf import textures as tx
        cols = skyrimground.parse_colours("LDirt02=cyan, LPineForest01=red")
        self.assertEqual(cols, {"ldirt02": (0, 255, 255), "lpineforest01": (255, 0, 0)})
        with self.assertRaises(ValueError):
            skyrimground.parse_colours("LDirt02=chartreuse")
        d = skyrimground.colour_dds((0, 255, 255), 16)
        h = tx.read_dds_header(d)
        self.assertEqual(d[h["data_offset"]:h["data_offset"] + 4], bytes([0, 255, 255, 255]))


class AlbedoTests(unittest.TestCase):
    def test_dark_skyrim_dirt_is_brought_to_starfield_brightness(self):
        import numpy as np
        from fo4sf import textures as tx
        rng = np.random.default_rng(2)
        rgb = np.clip(rng.normal((44, 43, 36), 12, (64, 64, 3)), 0, 255).astype(np.uint8)   # Skyrim Dirt02-like
        out = tx.scale_albedo(rgb, 0.15)
        lum = float((tx.srgb_to_linear(out) @ np.array([0.2126, 0.7152, 0.0722])).mean())
        self.assertAlmostEqual(lum, 0.15, delta=0.02)
        self.assertGreater(float(out.mean()), 90.0)                       # visibly brighter in sRGB
        self.assertGreater(float(out[..., 0].mean()), float(out[..., 2].mean()))   # hue kept (warmer than blue)
        self.assertGreater(float(out.std()), float(rgb.std()))            # detail scaled with it, not flattened


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



class HypothesesTests(unittest.TestCase):
    def test_readings_differ(self):
        import ground_at
        table = [0x10, 0x20, 0x30]
        q = [1, 2, 0, 0, 0, 3, 0, 0]                 # head: overlay 0 = 0x10, overlay 1 = 0x20, base 0x30
        word = 7 << 3                                # only alpha group 1 on
        got = dict(ground_at.hypotheses(q, word, table))
        self.assertEqual(got["index head, alpha bits 3i (build)"], 0x20)
        self.assertEqual(got["index head, alpha bits 3(4-i)"], 0x30)      # group 1 belongs to byte 3 (empty)
        self.assertEqual(got["index tail, alpha bits 3i"], 0x20)          # byte 1 -> entry 3 - 2 = 1


class GroundAtTests(unittest.TestCase):
    def test_reports_skyrim_layers_and_btd_bytes(self):
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        import ground_at
        with tempfile.TemporaryDirectory() as tmp:
            esm = TL.skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            sfd = os.path.join(tmp, "SF")
            os.makedirs(sfd)
            TL.starfield_esm(os.path.join(sfd, "Starfield.esm"))
            out = os.path.join(tmp, "out")
            with mock.patch.object(cw, "ltex_source", return_value=([PLAIN], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                    contextlib.redirect_stdout(io.StringIO()):
                sk.main(["build", "--skyrim", esm, "--sf-data", sfd, "--out", out, "--mask-writer", "builtin",
                         "--arrival", "", "--land-textures"])
            spawn = json.load(open(os.path.join(out, "overlays_params.json")))["overlays"][0]["spawn"]
            with contextlib.redirect_stdout(io.StringIO()) as so:          # cell (-1, -1) NE quadrant: all snow
                # positions as the game reports them: shifted by a merge offset of (500, -300) m
                ground_at.main(["--skyrim", esm, "--terrain", out,
                                "--pos", f"{-1000 / 70 + 500:.3f}", f"{-1000 / 70 - 300:.3f}",
                                "--spawn-at", f"{spawn[0] + 500:.3f}", f"{spawn[1] - 300:.3f}"])
        txt = so.getvalue()
        self.assertIn("LSnow01", txt)
        self.assertIn("cell (-1, -1)", txt)
        self.assertIn(f"{TL.SF['LSnowDeep01']:08X}", txt)              # the BTD draws the snow pick there


if __name__ == "__main__":
    unittest.main()
