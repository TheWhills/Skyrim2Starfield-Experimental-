"""src/fo4sf/exteriornavmesh.py and scripts/terrain/make_skyrim_navmesh.py on synthetic exterior navmeshes (no game
files): a strip of 8 triangles across the x = 100 m Starfield cell line plus a one-triangle neighbour."""
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import exteriornavmesh as E, skyrimnavmesh as N  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402

WORLD, NAV1, NAV2, OUTSIDE, DOOR = 0x3C, 0x1001, 0x1002, 0x9999, 0x2001
LINK = (0x1, 0x2, 0x4)


def nvnm(verts, tris, links, doors, grid_cell=(1, 0), world=WORLD):
    """Skyrim NVNM v12 bytes; tris = [(v, e, flags)], one grid cell listing every triangle."""
    out = [struct.pack("<III", 12, N.PATHING_CELL, world), struct.pack("<hh", grid_cell[1], grid_cell[0]),
           struct.pack("<I", len(verts))]
    out += [struct.pack("<3f", *v) for v in verts]
    out.append(struct.pack("<I", len(tris)))
    out += [struct.pack("<3H3hHH", *v, *e, f, 0) for v, e, f in tris]
    out.append(struct.pack("<I", len(links)) + b"".join(struct.pack("<IIh", 0, n, t) for n, t in links))
    out.append(struct.pack("<I", len(doors)) + b"".join(struct.pack("<hII", t, N.PATHING_DOOR, d) for t, d in doors))
    out.append(struct.pack("<I", 0))
    xs, ys = [v[0] for v in verts], [v[1] for v in verts]
    out.append(struct.pack("<I2f6f", 1, max(xs) - min(xs), max(ys) - min(ys), min(xs), min(ys), 0, max(xs), max(ys), 0))
    out.append(struct.pack("<I", len(tris)) + struct.pack(f"<{len(tris)}h", *range(len(tris))))
    return b"".join(out)


def strip():
    """NAV1: 4 quads from x 6720 to 7280 units (96..104 m), 2 triangles each; quads 0-1 lie in Starfield cell 0, 2-3
    in cell 1. Its left end links to a navmesh outside the set, its right end to NAV2; triangle 3 leads through DOOR."""
    xs = [6720, 6860, 7000, 7140, 7280]
    verts = [(x, 0.0, 10.0) for x in xs] + [(x, 140.0, 10.0) for x in xs]
    tris = []
    for q in range(4):
        b0, b1, t0, t1 = q, q + 1, q + 5, q + 6
        right = 2 * (q + 1) + 1 if q < 3 else 1                     # quad 3: edge-link 1 (to NAV2)
        tris.append(((b0, b1, t1), (-1, right, 2 * q + 1), 0x2 if q == 3 else 0))
        left = 2 * (q - 1) if q > 0 else 0                          # quad 0: edge-link 0 (outside)
        tris.append(((b0, t1, t0), (2 * q, -1, left), 0x4 if q == 0 else 0))
    nav1 = nvnm(verts, tris, [(OUTSIDE, 0), (NAV2, 0)], [(3, DOOR)])
    nav2 = nvnm([(7280, 0.0, 10.0), (7420, 0.0, 10.0), (7280, 140.0, 10.0)],
                [((0, 1, 2), (-1, -1, 0), 0x4)], [(NAV1, 6)], [])
    return nav1, nav2


def as_sf(data, fk):
    nm = N.parse_skyrim(data)
    sf = N.to_starfield(nm)
    k = lambda f: f"{f:06X}:Skyrim.esm"                              # noqa: E731
    for l in sf["edge_links"]:
        l["navmesh"] = k(l["navmesh"])
    for d in sf["door_links"]:
        d["door"] = k(d["door"])
    return {"formkey": fk, "geometry": sf}


class SplitTests(unittest.TestCase):
    def setUp(self):
        a, b = strip()
        self.navs = [as_sf(a, f"{NAV1:06X}:Skyrim.esm"), as_sf(b, f"{NAV2:06X}:Skyrim.esm")]
        self.assertEqual(N.check(N.parse_skyrim(a)), [])

    def test_split_at_the_cell_line(self):
        res = E.split_to_cells(self.navs)
        got = {p["key"]: p for p in res["navmeshes"]}
        n1 = f"{NAV1:06X}:Skyrim.esm"
        self.assertEqual(sorted(got), sorted([n1 + "@0,0", n1 + "@1,0", f"{NAV2:06X}:Skyrim.esm"]))
        self.assertEqual(got[n1 + "@0,0"]["cell"], [0, 0])
        self.assertEqual(got[n1 + "@1,0"]["cell"], [1, 0])
        self.assertEqual(len(got[n1 + "@0,0"]["geometry"]["triangles"]), 4)
        s = res["stats"]
        self.assertEqual((s["links_cut"], s["links_added"], s["links_kept"], s["doors"]), (1, 2, 2, 1))
        seam = [l for l in got[n1 + "@0,0"]["geometry"]["edge_links"] if l["navmesh"] == n1 + "@1,0"]
        self.assertEqual([l["type"] for l in seam], [E.LINK_PORTAL])
        # the door stays on its triangle (3, first piece); the outside link is an open edge now
        self.assertEqual(got[n1 + "@0,0"]["geometry"]["door_links"][0]["triangle"], 3)
        t1 = got[n1 + "@0,0"]["geometry"]["triangles"][1]
        self.assertEqual((t1["e"][2], t1["flags"] & 0x4), (0xFFFF, 0))
        # every link meets the triangle it names, both ways across the new seam and to NAV2
        geos = {k: p["geometry"] for k, p in got.items()}
        chk = E.edge_link_problems(geos, tol=0.01)
        self.assertEqual((chk["links"], chk["mismatch"], chk["outside"], chk["bad_index"]), (4, 0, 0, 0))
        # NAV2 stays whole (its own grid) and now points at the second piece's triangle 2
        self.assertEqual(geos[f"{NAV2:06X}:Skyrim.esm"]["edge_links"][0]["navmesh"], n1 + "@1,0")
        self.assertEqual(geos[f"{NAV2:06X}:Skyrim.esm"]["edge_links"][0]["triangle"], 2)
        self.assertIs(geos[f"{NAV2:06X}:Skyrim.esm"]["grid"], self.navs[1]["geometry"]["grid"])
        # rebuilt grids list each triangle, inside the piece's bounding box
        g = geos[n1 + "@1,0"]["grid"]
        self.assertEqual(sorted({t for c in g["cells"] for t in c}), [0, 1, 2, 3])
        self.assertEqual(g["bounds"][0], 7000.0)
        # the split navmesh serializes and reads back as Starfield's layout
        back = N.parse_starfield(N.serialize_starfield(dict(geos[n1 + "@1,0"], parent={"world": 1, "grid": (1, 0)},
                                                            edge_links=[dict(l, navmesh=5) for l in
                                                                        geos[n1 + "@1,0"]["edge_links"]],
                                                            door_links=[]), 1 / 70.0))
        self.assertEqual((back["parent"]["grid"], len(back["triangles"]), back["trailing_bytes"]), ((1, 0), 4, 0))

    def test_no_split_keeps_each_navmesh_whole(self):
        res = E.split_to_cells(self.navs, split=False)
        self.assertEqual(len(res["navmeshes"]), 2)
        self.assertEqual(res["stats"]["links_added"], 0)
        geos = {p["key"]: p["geometry"] for p in res["navmeshes"]}
        self.assertEqual(E.edge_link_problems(geos, tol=0.01)["mismatch"], 0)

    def test_frame_shift_and_grid(self):
        g = self.navs[0]["geometry"]
        moved = E.frame_shift(g, (1.0, -2.0), 385.0)
        self.assertEqual(moved["vertices"][0][:3], (6720 - 70.0, 0 + 140.0, 10 + 385 * 70.0))
        self.assertEqual(moved["grid"]["bounds"][0], 6720 - 70.0)
        self.assertEqual(moved["grid"]["bounds"][2], 385 * 70.0)
        # a 2 x 2 grid: one triangle in the south-west quarter only lands in cell 0, in the north-west one in cell 2
        # ("yx": rows along y) or cell 1 ("xy")
        verts = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (100, 100, 0), (0, 100, 0), (0, 90, 0), (10, 100, 0)]
        tris = [{"v": (0, 1, 2)}, {"v": (4, 5, 6)}, {"v": (3, 3, 3)}]
        yx = E.build_grid(verts, tris, 2, "yx")["cells"]
        xy = E.build_grid(verts, tris, 2, "xy")["cells"]
        self.assertEqual((yx[0], yx[2], yx[3]), ([0], [1], [2]))
        self.assertEqual((xy[0], xy[1], xy[3]), ([0], [1], [2]))
        sf = {"vertices": [v + (0,) for v in verts], "triangles": tris, "grid": E.build_grid(verts, tris, 2, "xy")}
        self.assertEqual(E.grid_agreement(sf, "xy"), 1.0)
        self.assertLess(E.grid_agreement(sf, "yx"), 1.0)
        self.assertEqual(E.piece_divisor(8, (10.0, 10.0), (40.0, 20.0)), 4)     # same 10-unit grid cells
        # exact overlap, not the bounding box: the north-east half-square's bbox covers the south-west quarter, the
        # triangle does not (its long edge x + y = 110 passes the quarter's corner at 50, 50)
        half = [(0, 0, 0), (10, 100, 0), (100, 100, 0), (100, 10, 0)]
        g = E.build_grid(half, [{"v": (1, 2, 3)}], 2, "yx")["cells"]
        self.assertEqual(g, [[], [0], [0], [0]])


def skyrim_esm(path):
    """Skyrim.esm with Tamriel, cell (1, 0) holding NAV1 and NAV2 (Skyrim cell 1 is 58.5..117 m; fine for the test)."""
    a, b = strip()
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
    world = rec(b"WRLD", WORLD, [(b"EDID", b"Tamriel\0")])
    cell = rec(b"CELL", 0x500, [(b"XCLC", struct.pack("<iiI", 1, 0, 0))])
    navs = [rec(b"NAVM", NAV1, [(b"NVNM", a)]), rec(b"NAVM", NAV2, [(b"NVNM", b)])]
    body = grup(b"WRLD", 0, [world, grup(WORLD, 1, [grup(0, 4, [grup(0, 5, [
        cell, grup(0x500, 6, [grup(0x500, 9, navs)])])])])])
    with open(path, "wb") as fh:
        fh.write(tes4 + body)


def nvmi(nav, world, grid, edges, doors, tail=b"\0\0\0\0\0"):
    """A Starfield NVMI body (xEdit SF1 layout) as PluginSpike writes it."""
    out = struct.pack("<II3ff", nav, 0, 1.0, 2.0, 3.0, 0.0)
    out += struct.pack("<I", len(edges)) + b"".join(struct.pack("<I", e) for e in edges) + struct.pack("<I", 0)
    out += struct.pack("<I", len(doors)) + b"".join(struct.pack("<II", N.PATHING_DOOR, d) for d in doors)
    out += struct.pack("<IB", 0, 0) + struct.pack("<IIhh", N.PATHING_CELL, world, grid[1], grid[0])
    return out + tail


def starfield_plugin(path, export, ids):
    """What PluginSpike writes, done in Python: each exported navmesh in its exterior cell (XCLC), FormIDs `ids`."""
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
    world = rec(b"WRLD", 0x01000800, [(b"EDID", b"SKY_Tamriel\0")])
    cells = {}
    for n in export["navmeshes"]:
        g = dict(n["geometry"], parent={"world": 0x01000800, "grid": tuple(n["cell"])})
        g["grid"] = dict(g["grid"], cells=[[]] * g["grid"]["divisor"] ** 2)
        g["edge_links"] = [dict(l, navmesh=ids[l["navmesh"]]) for l in g["edge_links"]]
        g["door_links"] = [dict(d, door=0x05000900) for d in g["door_links"]]
        g["tail"] = (12, 8)
        cells.setdefault(tuple(n["cell"]), []).append(rec(b"NAVM", ids[n["key"]], [(b"NVNM", N.serialize_starfield(
            g, 1 / 70.0))]))
    items = []
    for i, (xy, navs) in enumerate(sorted(cells.items())):
        cf = 0x05000700 + i
        items += [rec(b"CELL", cf, [(b"XCLC", struct.pack("<iiI", xy[0], xy[1], 0))]), grup(cf, 6, [grup(cf, 9, navs)])]
    # NAVI: one entry per navmesh; a load door with XNDP at the door's triangle
    infos = []
    for n in export["navmeshes"]:
        g = n["geometry"]
        infos.append((b"NVMI", nvmi(ids[n["key"]], 0x01000800, n["cell"],
                                    sorted({ids[l["navmesh"]] for l in g["edge_links"]} - {ids[n["key"]]}),
                                    [0x05000900] * bool(g["door_links"]))))
        if g["door_links"]:
            xndp = struct.pack("<Ihh", ids[n["key"]], g["door_links"][0]["triangle"], 0)
    navi = grup(b"NAVI", 0, [rec(b"NAVI", 0x00000ABC, [(b"NVER", struct.pack("<I", 12))] + infos)])
    door = rec(b"REFR", 0x05000900, [(b"NAME", struct.pack("<I", 0x123)), (b"XTEL", b"\0" * 36), (b"XNDP", xndp)])
    items.append(door)
    body = navi + grup(b"WRLD", 0, [world, grup(0x01000800, 1, [grup(0, 4, [grup(0, 5, items)])])])
    with open(path, "wb") as fh:
        fh.write(tes4 + body)


class ScriptTests(unittest.TestCase):
    def test_export_then_compare(self):
        import make_skyrim_navmesh as M
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Skyrim.esm")
            skyrim_esm(esm)
            ext = os.path.join(d, "ext")
            os.makedirs(ext)
            with open(os.path.join(ext, "overlays_params.json"), "w") as fh:
                json.dump({"overlays": [{"origin_cw_m": [0, 0], "height_offset_m": 385}]}, fh)
            with open(os.path.join(ext, "formids.json"), "w") as fh:
                json.dump({"world": "SKY_Tamriel", "plugin": "SkyrimTerrainTamriel.esm", "refs": {}}, fh)
            work = os.path.join(d, "work")
            self.assertEqual(M.main(["export", "--skyrim", esm, "--exterior", ext, "--out", work,
                                     "--around", "1,0", "--radius", "0"]), 0)
            with open(os.path.join(work, "exterior_navmesh.json")) as fh:
                exp = json.load(fh)
            self.assertEqual(len(exp["navmeshes"]), 3)
            n = exp["navmeshes"][0]["geometry"]
            self.assertEqual(n["vertices"][0][2], 10 + 385 * 70.0)               # lifted by the height offset
            self.assertEqual(n["triangles"][0]["height"], E.FLT_MAX)
            self.assertIn("grid_raw", n)
            self.assertEqual(n["grid"]["bounds"][5], E.FLT_MAX)                  # vanilla exterior grids' top
            ids = {p["key"]: 0x05000A00 + i for i, p in enumerate(exp["navmeshes"])}
            plugin = os.path.join(d, "FO4Port.esm")
            starfield_plugin(plugin, exp, ids)
            with open(os.path.join(d, "source_map.json"), "w") as fh:
                json.dump({k: f"{v & 0xFFFFFF:06X}:FO4Port.esm" for k, v in ids.items()}, fh)
            self.assertEqual(M.main(["compare", "--skyrim", esm, "--work", work, "--plugin", plugin]), 0)
            with open(os.path.join(work, "compare.json")) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["navmeshes"]["in_plugin"], 3)
            self.assertEqual(rep["navmeshes"]["missing"], [])
            self.assertEqual(rep["triangles"], {"skyrim": 9, "plugin": 9})
            self.assertLess(rep["vertex_offset_m"]["skyrim_to_ours"]["max"], 0.001)
            self.assertEqual(rep["parent_cell_mismatch"]["count"], 0)
            self.assertEqual(rep["edge_links"]["ours"]["mismatch"], 0)
            self.assertEqual(rep["door_links"], {"skyrim": 1, "plugin": 1})
            h = rep["height_above_terrain_m"]
            self.assertAlmostEqual(h["ours"]["median"], h["skyrim"]["median"], places=3)
            self.assertTrue(os.path.getsize(os.path.join(work, "compare.html")) > 1000)
            pth = rep["pathing"]
            self.assertEqual((pth["navi"]["ours_listed"], pth["navi"]["mismatch"]), (3, 0))
            self.assertEqual((pth["xndp"]["load_doors"], pth["xndp"]["to_door_triangle"]), (1, 1))
            self.assertEqual(pth["xndp"]["navmeshes_without_navi"], 0)

    def test_survey_exterior(self):
        import navmesh_survey as S
        import make_skyrim_navmesh as M
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Skyrim.esm")
            skyrim_esm(esm)
            ext = os.path.join(d, "ext")
            os.makedirs(ext)
            with open(os.path.join(ext, "overlays_params.json"), "w") as fh:
                json.dump({"overlays": [{"origin_cw_m": [0, 0], "height_offset_m": 0}]}, fh)
            with open(os.path.join(ext, "formids.json"), "w") as fh:
                json.dump({"world": "SKY_Tamriel"}, fh)
            work = os.path.join(d, "work")
            M.main(["export", "--skyrim", esm, "--exterior", ext, "--out", work, "--around", "1,0", "--radius", "0"])
            with open(os.path.join(work, "exterior_navmesh.json")) as fh:
                exp = json.load(fh)
            plugin = os.path.join(d, "Starfield.esm")
            starfield_plugin(plugin, exp, {p["key"]: 0x100 + i for i, p in enumerate(exp["navmeshes"])})
            out = os.path.join(d, "survey")
            self.assertEqual(S.main(["--esm", plugin, "--out", out, "--exterior"]), 0)
            with open(os.path.join(out, "navmesh_survey_exterior.json")) as fh:
                rep = json.load(fh)
            with open(os.path.join(out, "navmesh_defaults_exterior.json")) as fh:
                dflt = json.load(fh)
            self.assertEqual(rep["navmeshes"], 3)
            self.assertEqual(rep["parent_grid_vs_xclc"], {"same as XCLC": 3})
            self.assertEqual(rep["outside_own_cell"]["navmeshes_over_5pct"], 0)
            self.assertEqual(dflt["tail"], [12, 8])
            self.assertIn(dflt["grid_order"], E.GRID_ORDERS)
            navi = rep["navi"]["Starfield.esm"][0]
            self.assertEqual((navi["entries"], navi["crc_ok"], navi["exterior"], navi["tails"]), (3, 3, 3, [["0000000000", 3]]))


if __name__ == "__main__":
    unittest.main()
