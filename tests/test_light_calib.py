"""scripts/interior/light_calib.py (2026-11-21): the calibration cell's layout, the batch files it writes, and the
screenshot analysis on a synthetic image (no game data)."""
import json
import math
import os
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "src"))
import light_calib as LC  # noqa: E402


class LayoutTest(unittest.TestCase):
    def test_grid_and_spacing(self):
        spots = LC.layout()
        self.assertEqual(len(spots), LC.COLS * LC.ROWS)
        self.assertEqual(sum(1 for s in spots if s[0] == "ladder"), len(LC.LADDER_STEPS))
        xy = [LC.spot_xy(i) for i in range(len(spots))]
        dmin = min(math.dist(a, b) for i, a in enumerate(xy) for b in xy[i + 1:])
        # no light reaches a neighbouring tile: the nearest is farther than the radius
        self.assertGreater(dmin, LC.RADIUS_M)
        self.assertEqual(xy[0][1], max(p[1] for p in xy))                # row 0 is the far row (y max)

    def test_cell_json_lights_and_tiles(self):
        cell = LC.cell_json("Architecture\\Farmhouse\\FarmhouseFloor01.nif", 0.4)
        lights = [r for r in cell["refs"] if r["type"] == "Light"]
        tiles = [r for r in cell["refs"] if r["base_editor_id"] == "S2SCalibTile"]
        self.assertEqual((len(lights), len(tiles)), (36, 36))
        for L, T, s in zip(lights, tiles, LC.layout()):
            self.assertEqual(L["pos"][:2], T["pos"][:2])                  # straight above its tile
            self.assertAlmostEqual(L["pos"][2] / LC.UNITS_PER_M, s[3])
            self.assertEqual(L["light"]["calib_lumens"], round(s[4], 1))
            self.assertEqual(L["light"]["falloff_exponent"], s[2])
        self.assertTrue(any(r["base_editor_id"] == "COCMarkerHeading" for r in cell["refs"]))
        # rows 4, 5: the same test lights as spheres of AREA_RADII_M; no size on the others
        areas = [L["light"].get("area_radius_m", 0.0) for L in lights]
        for r in LC.AREA_RADII_M:
            self.assertEqual(areas.count(r), len(LC.TEST_HEIGHTS_M))
        self.assertEqual(areas.count(0.0), 36 - len(LC.AREA_RADII_M) * len(LC.TEST_HEIGHTS_M))
        self.assertEqual(LC.area_radius("test_a1.5"), 1.5)
        self.assertEqual(LC.area_radius("test_e1"), 0.0)

    def test_pick_floor(self):
        man = {"items": [{"source": "meshes\\Clutter\\Candles\\CandleHornFloor01.nif"},
                         {"source": "meshes\\Architecture\\Farmhouse\\FarmhouseFloorLong01.nif"},
                         {"source": "meshes\\Architecture\\Farmhouse\\FarmFloor01.nif"}]}
        self.assertEqual(LC.pick_floor(man), ("Architecture\\Farmhouse\\FarmFloor01.nif",
                                               "meshes\\Architecture\\Farmhouse\\FarmFloor01.nif"))
        self.assertIsNone(LC.pick_floor({"items": []}))


class MakeTest(unittest.TestCase):
    def test_writes_cell_cells_txt_lighting_layout(self):
        import contextlib
        import io
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as work:
            os.makedirs(os.path.join(work, "convert"))
            with open(os.path.join(work, "convert", "manifest.json"), "w") as fh:
                json.dump({"items": [{"source": "meshes\\Architecture\\FarmFloor01.nif", "model": "x\\y.nif"}]}, fh)
            with open(os.path.join(work, "cells.txt"), "w") as fh:
                fh.write("C:\\w\\cells\\RiverwoodSvensHouse.json\n")
            with contextlib.redirect_stdout(io.StringIO()):
                LC.cmd_make(SimpleNamespace(work=work))
                LC.cmd_make(SimpleNamespace(work=work))                    # twice: listed once
            lines = open(os.path.join(work, "cells.txt")).read().split()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[1].endswith("S2SLightCalib.json"))
            cfg = json.load(open(os.path.join(work, "convert", "lighting.json")))
            self.assertEqual(cfg["S2SLightCalib"]["ADAPT_IS"], "0")
            self.assertEqual(cfg["S2SLightCalib"]["ENV_AMBIENT"], "0")
            lay = json.load(open(os.path.join(work, "light_calib_layout.json")))
            self.assertEqual(lay["scale"], 0.3)                               # unreadable NIF: the default


class AnalyzeTest(unittest.TestCase):
    def synthetic(self, falloff, flip=False, stand=True):
        """A top-down image on the cell's flat grey: tiles in the grid, brightness a tone curve of their light; the
        arrival tile south of the grid; flip = looking back (south at the top)."""
        spots = LC.layout()
        img = np.full((900, 760, 3), 0.83)
        for i, s in enumerate(spots):
            r, c = divmod(i, LC.COLS)
            if flip:
                r, c = LC.ROWS - 1 - r, LC.COLS - 1 - c
            E = s[4] / LC.TEST_LM * falloff(s[3]) / falloff(LC.LADDER_HEIGHT_M)
            v = 0.95 * E / (0.4 + E)                                         # any monotonic tone curve
            y, x = 260 + r * 90, 60 + c * 110
            img[y:y + 40, x:x + 50] = 0.05                                    # a dark outline (the pelt's edge)
            img[y + 3:y + 37, x + 3:x + 47] = v
        if stand:
            y = 10 if flip else 860
            img[y:y + 30, 360:400] = 0.0
        return img, spots

    def check(self, img, spots, falloff):
        lum = img.mean(2)
        blobs = LC.find_tiles(img, len(spots))
        self.assertEqual(len(blobs), len(spots))
        res = LC.analyze([LC.tile_value(lum, b) for b in blobs], spots)
        hits = [t for t in res["tests"] if t["measured"] is not None]
        for t in hits:
            want = falloff(t["d"]) / falloff(LC.LADDER_HEIGHT_M)
            self.assertAlmostEqual(math.log2(t["measured"]), math.log2(want), delta=0.1)
        self.assertGreaterEqual(len(hits), 10)

    def test_looking_north(self):
        f = lambda d: 1 / (d * d + 1.3)                                     # noqa: E731
        self.check(*self.synthetic(f), f)

    def test_looking_back_south(self):
        f = lambda d: 1 / (d * d + 1.3)                                     # noqa: E731
        self.check(*self.synthetic(f, flip=True), f)

    def test_without_the_arrival_tile(self):
        f = lambda d: 1 / (d * d)                                           # noqa: E731
        self.check(*self.synthetic(f, stand=False), f)


class PluginSpikeTest(unittest.TestCase):
    def test_calib_hooks(self):
        cs = open(os.path.join(ROOT, "dotnet", "PluginSpike", "Program.cs"), encoding="utf-8").read()
        self.assertIn('if (F("calib_lumens", 0f) > 0f) lm = F("calib_lumens", 0f);', cs)
        self.assertIn("nl.AreaLight.Type = AreaLight.TypeOption.Sphere;", cs)
        self.assertIn(':{F("area_radius_m", 0f):0.###}");', cs)   # the size is part of the light base key
        self.assertIn('Setting(src4, "ADAPT_IS", "1") != "0"', cs)
        ps = open(os.path.join(ROOT, "tools", "owner", "riverwood_doors.ps1"), encoding="utf-8").read()
        self.assertIn("light_calib.py make --work $Work", ps)


if __name__ == "__main__":
    unittest.main()
