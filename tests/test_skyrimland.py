"""Synthetic-fixture tests for the Skyrim terrain source and the Tamriel overlay front end. Every plugin byte is built
here (a Skyrim-shaped Tamriel: compressed CELL/LAND, named exterior cells, a cell without LAND, a persistent cell);
no game data is needed. The Starfield LTEX template is replaced by a fixed table, so no Starfield files either."""
import contextlib
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import btd, fo4land, skyrimland  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402

G = fo4land.GRID
DEFAULT_LAND = -2048.0
DEFAULT_WATER = -14000.0
EXTENT = (-6, 5, -4, 4)                  # inclusive Skyrim cells with LAND (x0, x1, y0, y1)
HOLE = (2, 1)                            # a cell inside the extent with no LAND record
NAMED = {(0, 0): "Riverwood", (-3, 2): "BleakFallsExterior01", (4, -2): "WhiterunExterior07"}
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


PLAIN_LTEX = ([0x001235C2], bytes([0, 0, 0, 0, 0, 0, 0, 1]))


def hills(xu, yu):
    """Smooth terrain in Skyrim units at world (xu, yu): a broad slope plus two hills, steps of 8 units."""
    z = 1200.0 + 0.04 * xu - 0.02 * yu
    z += 2500.0 * math.exp(-((xu - 6000.0) ** 2 + (yu + 4000.0) ** 2) / (2 * 7000.0 ** 2))
    z += 1500.0 * math.exp(-((xu + 12000.0) ** 2 + (yu - 9000.0) ** 2) / (2 * 5000.0 ** 2))
    return 8.0 * round(z / 8.0)


def cell_vhgt(cx, cy):
    """VHGT bytes for cell (cx, cy) from `hills` at its 33 x 33 vertices (shared edges equal by construction)."""
    r, c = np.mgrid[0:G, 0:G]
    xu = cx * 4096.0 + c * 128.0
    yu = cy * 4096.0 + r * 128.0
    steps = np.vectorize(hills)(xu, yu) / 8.0
    base = float(steps[0, 0])
    return fo4land.encode_vhgt(base, (steps - base).astype(np.int64)), steps * 8.0


def build_skyrim(world="Tamriel", extent=EXTENT, hole=HOLE, named=NAMED):
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800)), (b"CNAM", b"test\0")])
    pcell = rec(b"CELL", 0x200, [(b"DATA", b"\x02\0")])            # persistent cell: no XCLC (Skyrim style)
    items = [pcell, grup(0x200, 6, [grup(0x200, 8, [])])]
    sub, fid = [], 0x1000
    x0, x1, y0, y1 = extent
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            cfid, lfid = fid, fid + 1
            fid += 2
            fields = [(b"EDID", named[(x, y)].encode() + b"\0")] if (x, y) in named else []
            fields += [(b"DATA", b"\0\0"), (b"XCLC", struct.pack("<iiI", x, y, 0))]
            sub.append(rec(b"CELL", cfid, fields, compress=True))
            children = []
            if (x, y) != hole:
                vhgt, _ = cell_vhgt(x, y)
                children.append(rec(b"LAND", lfid, [(b"DATA", b"\0" * 4), (b"VHGT", vhgt)], compress=True))
            sub.append(grup(cfid, 6, [grup(cfid, 9, children)]))
    items.append(grup(b"\0\0\0\0", 4, [grup(b"\0\0\0\0", 5, sub)]))
    wrld = rec(b"WRLD", 0x3C, [(b"EDID", world.encode() + b"\0"),
                               (b"DNAM", struct.pack("<ff", DEFAULT_LAND, DEFAULT_WATER))])
    other = rec(b"WRLD", 0x3D, [(b"EDID", b"Sovngarde\0")])
    return tes4 + grup(b"WRLD", 0, [other, grup(0x3D, 1, []), wrld, grup(0x3C, 1, items)])


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esm = os.path.join(self.tmp.name, "Skyrim.esm")
        with open(self.esm, "wb") as f:
            f.write(build_skyrim())

    def tearDown(self):
        self.tmp.cleanup()


class SkyrimLandTests(Fixture):
    def test_extent_holes_defaults_and_heights(self):
        land = skyrimland.SkyrimLand(self.esm)
        self.assertEqual(land.extent, EXTENT)
        self.assertEqual(land.holes, [HOLE])
        self.assertEqual((land.default_land, land.default_water), (DEFAULT_LAND, DEFAULT_WATER))
        self.assertEqual(land.fill_height(), DEFAULT_LAND)
        self.assertEqual(len(land.grids), 12 * 9 - 1)
        _, want = cell_vhgt(-3, 2)
        np.testing.assert_array_equal(land.grids[(-3, 2)], want)
        rep = land.seams()
        self.assertGreater(rep["pairs"], 150)
        self.assertEqual(rep["max_abs"], 0.0)          # shared cell edges agree, as in a real worldspace

    def test_landmarks_by_editor_id_and_coordinates(self):
        land = skyrimland.SkyrimLand(self.esm)
        self.assertEqual(land.landmark("riverwood"), ("riverwood", 0, 2048.0, 2048.0))
        self.assertEqual(land.landmark("-3,2"), ("cell_m3_2", 0, -3 * 4096 + 2048.0, 2 * 4096 + 2048.0))
        self.assertIsNone(land.landmark("Solitude"))
        self.assertIsNone(land.landmark("40,40"))
        self.assertEqual([e for e, _ in land.find_cells("exterior")], ["BleakFallsExterior01", "WhiterunExterior07"])

    def test_heights_fill_missing_cells_with_default_land(self):
        """The hole takes the default height inside; its real neighbours keep their own shared edge vertices."""
        land = skyrimland.SkyrimLand(self.esm)
        h = skyrimland.SkyrimHeights(land)
        g, origin = h.merged(1, 3, 0, 2)
        self.assertEqual(origin, (4096.0, 0.0))
        self.assertEqual(g.shape, (3 * 32 + 1, 3 * 32 + 1))
        self.assertEqual(float(g[32 + 16, 32 + 16]), DEFAULT_LAND)        # centre of the hole (2, 1)
        _, want = cell_vhgt(1, 0)
        np.testing.assert_array_equal(g[:G, :G], want)
        _, east = cell_vhgt(3, 1)                                         # hole's east neighbour
        np.testing.assert_array_equal(g[32:32 + G, 64], east[:, 0])
        _, north = cell_vhgt(2, 2)                                        # hole's north neighbour
        np.testing.assert_array_equal(g[64, 32:32 + G], north[0, :])
        g2, origin2 = h.merged(-50, -5, -50, -3)                          # clamped to the LAND extent
        self.assertEqual(origin2, (-6 * 4096.0, -4 * 4096.0))
        self.assertEqual(g2.shape, (2 * 32 + 1, 2 * 32 + 1))

    def test_missing_world_and_empty_world(self):
        with self.assertRaises(KeyError):
            skyrimland.SkyrimLand(self.esm, "Solstheim")
        with self.assertRaises(ValueError):
            skyrimland.SkyrimLand(self.esm, "Sovngarde")


class Fo4DefaultsTests(unittest.TestCase):
    def test_fo4_heights_keep_commonwealth_defaults(self):
        import make_cw_overlays as cw
        h = cw.Fo4Heights()
        self.assertEqual((h.world, h.grid, h.fill), ("Commonwealth", (-96, 95, -96, 95), None))
        a = cw.parser().parse_args(["build", "--out", "x"])
        self.assertEqual(cw.landmarks(a), cw.LANDMARKS)
        self.assertEqual(cw.arrival_name(a), "redrocket")


class OverlayBuildTests(Fixture):
    def build(self, *extra):
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        out = os.path.join(self.tmp.name, "stage")
        argv = ["build", "--skyrim", self.esm, "--sf-data", self.tmp.name, "--out", out,
                "--mask-writer", "builtin", "--landmark", "BleakFallsExterior01", "--landmark", "Solitude", *extra]
        with mock.patch.object(cw, "ltex_source", return_value=PLAIN_LTEX), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            sk.main(argv)
        return out, log.getvalue()

    def test_tamriel_overlay_end_to_end(self):
        import make_cw_overlays as cw
        out, log = self.build()
        self.assertIn("WARNING: landmark 'Solitude'", log)
        prm = load_json(os.path.join(out, "overlays_params.json"))
        o = prm["overlays"][0]
        self.assertEqual(len(prm["overlays"]), 1)
        self.assertEqual((o["world"], o["name"], o["coc"]), ("SKY_Tamriel", "Skyrim", "SKY_TamrielRiverwoodSpawn"))
        self.assertEqual(prm["plugin"], "SkyrimTerrainTamriel.esm")
        self.assertEqual(prm["mars"]["plugin"], "SkyrimTerrainTamriel_Mars.esm")
        n = o["n"]
        self.assertEqual(n, 8)                          # Skyrim cells -6..5, -4..4 -> Starfield cells -4..3
        self.assertEqual(o["origin_cw_m"], [0.0, 0.0])  # local frame = Skyrim position / 70

        data = read_bytes(os.path.join(out, "Data", "Terrain", "SKY_Tamriel.btd"))
        self.assertEqual(data, read_bytes(os.path.join(out, "Data", "meshes", "terrain", "SKY_Tamriel.btd")))
        t = btd.read(data)
        self.assertEqual((t.ncx, t.ncy), (n, n))
        dec = t.heights_m()
        step = (t.hmax - t.hmin) / 65535.0
        # 1) exact pipeline check: every BTD sample = bilinear resample of the Skyrim vertex grid (hole filled) / 70,
        #    within one quantisation step
        land = skyrimland.SkyrimLand(self.esm)
        x0, x1, y0, y1 = EXTENT
        g, (ox, oy) = skyrimland.SkyrimHeights(land).merged(x0, x1, y0, y1)
        xs = tg.sample_coords(n)
        want = tg.resample_bilinear(g, ox, oy, 128.0, xs * 70.0, xs * 70.0) / 70.0
        self.assertLessEqual(float(np.abs(dec - want).max()), step * 1.0001)
        # 2) Skyrim vertices away from the hole: resampling a 1.83 m grid onto 0.78 m keeps them within the runner's
        #    0.5 m tolerance (kinks between Skyrim quads are not on the BTD lattice, so not exact)
        errs = []
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                if max(abs(cx - HOLE[0]), abs(cy - HOLE[1])) <= 1:
                    continue
                for r in (0, 7, 16, 31):
                    for c in (0, 9, 16, 30):
                        xu, yu = cx * 4096.0 + c * 128.0, cy * 4096.0 + r * 128.0
                        x, y = xu / 70.0, yu / 70.0
                        if -400.0 <= x < 400.0 - tg.SF_STEP_M and -400.0 <= y < 400.0 - tg.SF_STEP_M:
                            errs.append(abs(tg.btd_height_at(dec, n, x, y) - hills(xu, yu) / 70.0))
        self.assertGreater(len(errs), 800)
        self.assertLess(max(errs), 0.5)
        self.assertLess(float(np.median(errs)), 0.05)
        hx, hy = (HOLE[0] + 0.5) * 4096.0 / 70.0, (HOLE[1] + 0.5) * 4096.0 / 70.0
        self.assertAlmostEqual(tg.btd_height_at(dec, n, hx, hy), DEFAULT_LAND / 70.0, delta=step)
        self.assertAlmostEqual(t.hmin, math.floor(DEFAULT_LAND / 70.0) - 1, delta=1.0)

        plan = load_json(os.path.join(out, "plan.json"))
        self.assertTrue(plan)
        arrival = plan[0]["points"][0]
        self.assertEqual(arrival["label"], "arrival")
        self.assertLess(math.hypot(arrival["x"] - 2048 / 70.0, arrival["y"] - 2048 / 70.0), 40.0)
        labels = {p["label"] for e in plan for p in e["points"]}
        self.assertIn("bleakfallsexterior01", labels)    # the extra landmark rides on the ray nearest its bearing
        for e in plan:
            self.assertEqual(e["coc"], "SKY_TamrielRiverwoodSpawn")
            for p in e["points"]:
                self.assertLess(abs(tg.btd_height_at(dec, n, p["x"], p["y"]) - p["expect"]), 2 * step)

        src = load_json(os.path.join(out, "skyrim_source.json"))
        self.assertEqual(src["filled_cells_in_overlay"], 1)
        self.assertEqual([r["found"] for r in src["landmarks"]], [True, True, False])
        for name in ("expected.json", "README.txt", "preview.png",
                     os.path.join("Data", "textures", "terrain", "overlaymasks", "sky_tamriel.dds")):
            self.assertTrue(os.path.exists(os.path.join(out, name)), name)

        ca = cw.parser().parse_args(["check", "--out", out, "--sf-data", self.tmp.name, "--no-plugins"])
        prm2 = json.loads(read_bytes(os.path.join(out, "overlays_params.json")))
        ok, rep = cw.check_staging(out, prm2, plan, None, plugins=False)
        failed = [w for w, good in rep["checks"] if not good]
        self.assertTrue(ok, failed)
        del ca

    def test_options_pass_through_and_centre_arrival(self):
        out, _ = self.build("--arrival", "", "--no-mars", "--world", "SKY_Test", "--display-name", "Tamriel",
                            "--landmark", "-3,-2")
        prm = load_json(os.path.join(out, "overlays_params.json"))
        o = prm["overlays"][0]
        self.assertIsNone(prm["mars"])
        self.assertEqual((o["world"], o["name"], o["coc"]), ("SKY_Test", "Tamriel", "SKY_TestSpawn"))
        src = load_json(os.path.join(out, "skyrim_source.json"))
        self.assertIn({"spec": "-3,-2", "found": True}, [{k: r[k] for k in ("spec", "found")} for r in src["landmarks"]])

    def test_rejects_region_larger_than_vanilla_maximum(self):
        import make_skyrim_overlay as sk
        self.assertEqual(sk.single_tile_n(EXTENT), 8)
        self.assertIsNone(sk.single_tile_n((-200, 199, -10, 10)))

    def test_info_reads_only_skyrim(self):
        import make_skyrim_overlay as sk
        with contextlib.redirect_stdout(io.StringIO()) as log:
            sk.main(["info", "--skyrim", self.esm, "--find", "whiterun"])
        info = json.loads(log.getvalue())
        self.assertEqual(info["source"]["extent"], {"x": [-6, 5], "y": [-4, 4]})
        self.assertEqual(info["plan"]["overlay_n"], 8)
        self.assertEqual(info["find"], [{"edid": "WhiterunExterior07", "cell": [4, -2]}])


if __name__ == "__main__":
    unittest.main()
