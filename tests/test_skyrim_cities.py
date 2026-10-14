"""Synthetic-fixture tests for Skyrim's walled cities: a child worldspace without LAND of its own takes its parent's
terrain under its cells, gets a small overlay centred on it (--frame local) and its objects are shifted into that frame.
No game data."""
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import btd, skyrimland, textures  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
import test_skyrim_objects as T  # noqa: E402
from test_skyrimland import hills  # noqa: E402

CITY_CELLS = [(x, y) for x in range(2, 5) for y in range(1, 4)]
CITY_REFS = {(3, 2): [T.ref_at(0x3001, 0x0A01, 3 * 4096 + 1000.0, 2 * 4096 + 1500.0),       # rock in the city
                      T.ref_at(0x3002, 0x0A03, 3 * 4096 + 3000.0, 2 * 4096 + 500.0)],      # house
             (2, 1): [T.ref_at(0x3003, 0x0A02, 2 * 4096 + 200.0, 1 * 4096 + 300.0)]}       # tree


def write_city_esm(path):
    cells, persistent = T.world_refs()
    with open(path, "wb") as f:
        f.write(F.build_esm(cells, hills, T.EXTENT, persistent_refs=persistent,
                            extra_worlds=[(0x50, "WhiterunWorld", 0x3C, 0x1, CITY_CELLS, CITY_REFS)]))
    return path


class CityLandTests(unittest.TestCase):
    def test_child_world_uses_parent_land_under_its_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            esm = write_city_esm(os.path.join(tmp, "Skyrim.esm"))
            land = skyrimland.SkyrimLand(esm, "WhiterunWorld")
            worlds = {w["edid"]: w for w in skyrimland.list_worlds(esm)}
        self.assertEqual(land.land_source, "Tamriel")
        self.assertEqual(land.extent, (2, 4, 1, 3))
        self.assertTrue(set(CITY_CELLS) <= set(land.grids))
        self.assertEqual(land.grid_bounds, (-2, 5, -3, 4))        # the city +- 4 cells, clipped to Tamriel's LAND
        _, want = __import__("test_skyrimland").cell_vhgt(3, 2)
        self.assertTrue((land.grids[(3, 2)] == want).all())
        self.assertEqual(worlds["WhiterunWorld"], {"edid": "WhiterunWorld", "form_id": "00000050", "parent": "Tamriel",
                                                   "use_parent_land": True, "cells": 9, "land": 0,
                                                   "extent": [2, 4, 1, 3]})
        self.assertEqual(worlds["Tamriel"]["land"], 108)

    def test_world_without_land_or_parent_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "Skyrim.esm")
            cells, persistent = T.world_refs()
            with open(p, "wb") as f:
                f.write(F.build_esm(cells, hills, T.EXTENT, extra_worlds=[(0x51, "Island", 0, 0, [(0, 0)], {})]))
            with self.assertRaises(ValueError):
                skyrimland.SkyrimLand(p, "Island")


class CityBuildTests(unittest.TestCase):
    def test_city_overlay_and_objects_in_local_frame(self):
        import make_cw_overlays as cw
        import make_skyrim_objects as so
        import make_skyrim_overlay as sk
        with tempfile.TemporaryDirectory() as tmp, T.starfield_inputs(tmp) as sf, \
                mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                contextlib.redirect_stdout(io.StringIO()):
            esm = write_city_esm(os.path.join(tmp, "Skyrim.esm"))
            data = F.skyrim_data(os.path.join(tmp, "Data"))
            terrain, work, out = (os.path.join(tmp, d) for d in ("terrain", "work", "out"))
            sk.main(["build", "--skyrim", esm, "--world-edid", "WhiterunWorld", "--frame", "local", "--sf-data", tmp,
                     "--out", terrain, "--mask-writer", "builtin"])
            texconv = os.path.join(tmp, "texconv.exe")
            with open(texconv, "wb") as f:
                f.write(b"MZ")
            so.main(["export", "--skyrim", esm, "--world-edid", "WhiterunWorld", "--work", work])
            so.main(["select", "--work", work, "--terrain", terrain])
            so.main(["convert", "--work", work, "--skyrim-data", data, "--content-resources", sf["content_resources"],
                     "--texconv", texconv, "--collision-template", sf["collision_template"]])
            so.main(["stage", "--work", work, "--terrain", terrain, "--out", out])
            ok, rep = so.check(out)
            with open(os.path.join(terrain, "overlays_params.json"), encoding="utf-8") as f:
                prm = json.load(f)
            with open(os.path.join(out, "objects.json"), encoding="utf-8") as f:
                obj = json.load(f)
            with open(os.path.join(terrain, "Data", "Terrain", "SKY_WhiterunWorld.btd"), "rb") as f:
                t = btd.read(f.read())
            with open(os.path.join(terrain, "plan.json"), encoding="utf-8") as f:
                plan = json.load(f)
        self.assertTrue(ok, [c for c in rep["checks"] if not c[1]])
        o = prm["overlays"][0]
        self.assertEqual((o["world"], o["name"], o["n"]), ("SKY_WhiterunWorld", "Whiterun", 5))
        self.assertEqual(prm["plugin"], "SkyrimTerrainWhiterunWorld.esm")
        self.assertEqual(prm["mars"]["plugin"], "SkyrimTerrainWhiterunWorld_Mars.esm")
        ox, oy = o["origin_cw_m"]
        self.assertNotEqual((ox, oy), (0.0, 0.0))                       # the overlay sits on the city, not on 0, 0
        self.assertEqual((ox % 100.0, oy % 100.0), (0.0, 0.0))          # whole cells
        # terrain: Tamriel's heights / 70 at the city's positions, in the local frame
        n = t.ncx
        for xu, yu in ((3 * 4096 + 1000.0, 2 * 4096 + 1500.0), (2 * 4096 + 2048.0, 1 * 4096 + 2048.0),
                       (1 * 4096 + 1000.0, 0 * 4096 + 900.0)):           # last: outside the city, Tamriel's own hill
            got = tg.btd_height_at(t.heights_m(), n, xu / 70.0 - ox, yu / 70.0 - oy)
            self.assertAlmostEqual(got, hills(xu, yu) / 70.0, delta=0.5)
        # objects: three placed, positions shifted by the overlay origin, sitting on the terrain
        self.assertEqual(rep["refs"], 3)
        self.assertLess(abs(rep["frame"]["median_m"]), 0.05)
        rock = next(r for r in obj["refs"] if r["src"] == "003001:Skyrim.esm")
        self.assertAlmostEqual(rock["pos"][0], (3 * 4096 + 1000.0) / 70.0 - ox, places=3)
        self.assertAlmostEqual(rock["pos"][1], (2 * 4096 + 1500.0) / 70.0 - oy, places=3)
        self.assertTrue(plan and all(len(e["points"]) >= 2 for e in plan))   # city-distance probes fit
        lo, hi = o["bounds_min_m"] + 50.0, o["bounds_max_m"] - 50.0       # inside the overlay, 50 m edge keep
        self.assertTrue(all(lo <= p[k] <= hi for e in plan for p in e["points"] for k in ("x", "y")))


def add_to_wrld_group(raw: bytes, payload: bytes) -> bytes:
    """Append records to a plugin's WRLD top group (header: "GRUP", u32 size incl. header, label "WRLD", type 0)."""
    import struct
    i = 0
    while True:
        i = raw.index(b"GRUP", i)
        if raw[i + 8:i + 12] == b"WRLD" and struct.unpack_from("<i", raw, i + 12)[0] == 0:
            break
        i += 4
    size = struct.unpack_from("<I", raw, i + 4)[0]
    return raw[:i + 4] + struct.pack("<I", size + len(payload)) + raw[i + 8:i + size] + payload + raw[i + size:]


class CityTextureTests(unittest.TestCase):
    def test_city_paints_with_its_parents_land_textures(self):
        import make_cw_overlays as cw
        import make_skyrim_overlay as sk
        import test_landtex as L
        from fo4sf import landtex
        with tempfile.TemporaryDirectory() as tmp:
            sky = L.skyrim_esm(os.path.join(tmp, "Skyrim.esm"))
            with open(sky, "rb") as f:
                raw = f.read()
            # append a child worldspace (no LAND) over cells -2..0, -2..0 to the textured Tamriel fixture
            from test_fo4land import grup, rec
            import struct
            csub = []
            for k, (x, y) in enumerate((x, y) for x in range(-2, 1) for y in range(-2, 1)):
                csub += [rec(b"CELL", 0x5000 + k, [(b"XCLC", struct.pack("<iiI", x, y, 0))]),
                         grup(0x5000 + k, 6, [grup(0x5000 + k, 9, [])])]
            child = rec(b"WRLD", 0x50, [(b"EDID", b"WindhelmWorld\0"), (b"WNAM", struct.pack("<I", 0x3C)),
                                        (b"PNAM", struct.pack("<H", 1))]) + \
                grup(0x50, 1, [grup(b"\0\0\0\0", 4, [grup(b"\0\0\0\0", 5, csub)])])
            raw = add_to_wrld_group(raw, child)
            with open(sky, "wb") as f:
                f.write(raw)
            sfd = os.path.join(tmp, "SF")
            os.makedirs(sfd)
            L.starfield_esm(os.path.join(sfd, "Starfield.esm"))
            out = os.path.join(tmp, "out")
            with mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([1, 0, 0, 0, 0, 0, 0, 0]))), \
                    contextlib.redirect_stdout(io.StringIO()):
                sk.main(["build", "--skyrim", sky, "--world-edid", "WindhelmWorld", "--frame", "local",
                         "--sf-data", sfd, "--out", out, "--mask-writer", "builtin", "--land-textures"])
            with open(os.path.join(out, "Data", "Terrain", "SKY_WindhelmWorld.btd"), "rb") as f:
                t = btd.read(f.read())
            with open(os.path.join(out, "overlays_params.json"), encoding="utf-8") as f:
                ox, oy = json.load(f)["overlays"][0]["origin_cw_m"]
        dec = landtex.decode_quadrants(t.quad_map, t.weights, t.ltex)
        o = tg.grid_origin(t.ncx)
        snow = L.SF["LSnowDeep01"]
        c = int(((-1000.0 / 70.0 - ox) - o) / tg.SF_STEP_M)                  # Tamriel's snow quadrant, local frame
        r = int(((-1000.0 / 70.0 - oy) - o) / tg.SF_STEP_M)
        self.assertIn(snow, t.ltex)
        self.assertGreater(float(dec[snow][r, c]), 0.9)


if __name__ == "__main__":
    unittest.main()
