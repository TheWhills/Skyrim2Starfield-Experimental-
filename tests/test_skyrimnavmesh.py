"""src/fo4sf/skyrimnavmesh.py on a synthetic two-room navmesh (no game files)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import skyrimnavmesh as N  # noqa: E402

CELL, OTHER_NAV, DOOR = 0x00013A71, 0x000FF001, 0x0001B2C3


def skyrim_nvnm(cell=CELL, extra=b""):
    """A 2x1 m floor of 4 vertices / 2 triangles (units); triangle 1's edge 1-2 is an edge link to another navmesh,
    triangle 0 leads through a door; one cover triangle; a 2x2 grid."""
    verts = [(0, 0, 0), (140, 0, 0), (140, 70, 0), (0, 70, 0)]
    tris = [((0, 1, 2), (-1, -1, 1), 0x0400, 0), ((0, 2, 3), (0, 0, -1), 0x0002 | 0x0040, 7)]
    out = [struct.pack("<III", 12, N.PATHING_CELL, 0), struct.pack("<I", cell), struct.pack("<I", len(verts))]
    out += [struct.pack("<3f", *v) for v in verts]
    out.append(struct.pack("<I", len(tris)))
    out += [struct.pack("<3H3hHH", *v, *e, f, c) for v, e, f, c in tris]
    out.append(struct.pack("<I", 1) + struct.pack("<IIh", 0, OTHER_NAV, 5))
    out.append(struct.pack("<I", 1) + struct.pack("<hII", 0, N.PATHING_DOOR, DOOR))
    out.append(struct.pack("<I", 1) + struct.pack("<h", 1))
    out.append(struct.pack("<I2f6f", 2, 70.0, 35.0, 0, 0, 0, 140, 70, 0))
    for cell_tris in ([0], [0, 1], [], [1]):
        out.append(struct.pack("<I", len(cell_tris)) + struct.pack(f"<{len(cell_tris)}h", *cell_tris))
    return b"".join(out) + extra


class NavmeshTests(unittest.TestCase):
    def test_parse_skyrim(self):
        nm = N.parse_skyrim(skyrim_nvnm())
        self.assertEqual(nm["parent"], {"cell": CELL})
        self.assertEqual(len(nm["vertices"]), 4)
        self.assertEqual(nm["triangles"][1]["e"], (0, 0, -1))
        self.assertEqual(nm["edge_links"], [{"type": 0, "navmesh": OTHER_NAV, "triangle": 5}])
        self.assertEqual(nm["door_links"][0]["door"], DOOR)
        self.assertEqual(nm["cover_triangles"], [1])
        self.assertEqual(nm["grid"]["cells"], [[0], [0, 1], [], [1]])
        self.assertEqual(nm["trailing_bytes"], 0)
        self.assertEqual(N.check(nm), [])

    def test_bad_data(self):
        with self.assertRaises(N.NavmeshError):
            N.parse_skyrim(skyrim_nvnm()[:40])
        with self.assertRaises(N.NavmeshError):
            N.parse_skyrim(struct.pack("<I", 15) + skyrim_nvnm()[4:])          # a Fallout 4 navmesh
        nm = N.parse_skyrim(skyrim_nvnm())
        nm["triangles"][0]["v"] = (0, 1, 9)
        nm["door_links"][0]["triangle"] = 4
        self.assertEqual(len(N.check(nm)), 2)

    def test_to_starfield_and_back(self):
        nm = N.parse_skyrim(skyrim_nvnm())
        sf = N.to_starfield(nm, {"triangle_height": 2.5, "vertex_unknown": 7})
        self.assertEqual(sf["edge_links"][0]["edge"], 1)                     # left by triangle 1's edge 1-2
        self.assertEqual(sf["triangles"][0]["e"], (0xFFFF, 0xFFFF, 1))        # -1 as u16
        self.assertEqual(sf["dropped"], {"cover_triangles": 1})
        new = {CELL: 0x01000801, OTHER_NAV: 0x01000900, DOOR: 0x01000A00}
        data = N.serialize_starfield(sf, scale=1 / 70.0, form_map=lambda f: new.get(f, f))
        back = N.parse_starfield(data)
        self.assertEqual(back["trailing_bytes"], 0)
        self.assertEqual(back["version"], 17)
        self.assertEqual(back["parent"], {"cell": 0x01000801})
        self.assertAlmostEqual(back["vertices"][2][0], 2.0, places=5)          # 140 units = 2 m
        self.assertEqual(back["vertices"][0][3], 7)
        self.assertEqual(back["triangles"][1]["flags"], 0x42)
        self.assertEqual(back["triangles"][1]["cover"], 7)
        self.assertAlmostEqual(back["triangles"][0]["height"], 2.5)
        self.assertEqual(back["edge_links"][0], {"type": 0, "navmesh": 0x01000900, "triangle": 5, "edge": 1})
        self.assertEqual(back["door_links"][0], {"triangle": 0, "crc": N.PATHING_DOOR, "door": 0x01000A00})
        self.assertEqual(back["grid"]["cells"], [[0], [0, 1], [], [1]])
        self.assertAlmostEqual(back["grid"]["size"][0], 1.0, places=5)
        self.assertEqual(back["tail"], (0, 0))
        # sizes: 16-byte vertices, 21-byte triangles, 11-byte edge links
        head = 4 + 4 + 4 + 4
        self.assertEqual(struct.unpack_from("<I", data, head)[0], 4)
        tri_count_at = head + 4 + 4 * 16
        self.assertEqual(struct.unpack_from("<I", data, tri_count_at)[0], 2)
        links_at = tri_count_at + 4 + 2 * 21
        self.assertEqual(struct.unpack_from("<I", data, links_at)[0], 1)

    def test_cut_links(self):
        sf = N.to_starfield(N.parse_skyrim(skyrim_nvnm()))
        # a second link that stays: triangle 0's edge 0-1 points at it
        sf["edge_links"].append({"type": 0, "navmesh": 0x777, "triangle": 2, "edge": 0})
        sf["triangles"][0] = dict(sf["triangles"][0], e=(1, 0xFFFF, 1), flags=sf["triangles"][0]["flags"] | 0x1)
        cut = N.cut_links(sf, keep={0x777})
        self.assertEqual(cut["edge_links"], [{"type": 0, "navmesh": 0x777, "triangle": 2, "edge": 0}])
        self.assertEqual(cut["triangles"][0]["e"][0], 0)                     # renumbered 1 -> 0
        self.assertEqual(cut["triangles"][1]["e"], (0, 0xFFFF, 0xFFFF))    # edge 1-2 linked to OTHER_NAV: cut ...
        self.assertEqual(cut["triangles"][1]["flags"] & 0x2, 0)             # ... and no longer flagged as a link
        self.assertEqual(cut["dropped"]["edge_links"], 1)
        back = N.parse_starfield(N.serialize_starfield(cut))
        self.assertEqual(len(back["edge_links"]), 1)

    def test_grid_shorts_are_the_serialized_grid(self):
        """Mutagen writes GridArrays as bare Int16s then Unknown3: those must be exactly our bytes after the bounds."""
        sf = N.to_starfield(N.parse_skyrim(skyrim_nvnm()), {"tail": (3, 0x8001)})
        sf["grid"]["cells"][3] = [1, 1, 1]                                   # a few triangles
        raw = N.grid_shorts(sf)
        expect = struct.pack(f"<{len(raw)}h", *raw) + struct.pack("<i", N.tail_int32(sf))
        data = N.serialize_starfield(sf)
        self.assertTrue(data.endswith(expect))
        self.assertEqual(raw[:3], [1, 0, 0])                                 # cell 0: count 1 (low, high), triangle 0
        self.assertEqual(N.tail_int32(sf), struct.unpack("<i", struct.pack("<HH", 3, 0x8001))[0])
        self.assertEqual(N.parse_starfield(data)["grid"]["cells"], sf["grid"]["cells"])

    def test_exterior_parent(self):
        data = struct.pack("<III", 12, N.PATHING_CELL, 0x3C) + struct.pack("<hh", -3, 5) + skyrim_nvnm()[16:]
        nm = N.parse_skyrim(data)
        self.assertEqual(nm["parent"], {"world": 0x3C, "grid": (5, -3)})
        back = N.parse_starfield(N.serialize_starfield(N.to_starfield(nm)))
        self.assertEqual(back["parent"], {"world": 0x3C, "grid": (5, -3)})

    def test_navm_fields(self):
        f = N.navm_fields([(b"EDID", b"\0"), (b"NVNM", skyrim_nvnm()), (b"ONAM", struct.pack("<2I", 1, 2)),
                           (b"NNAM", struct.pack("<3H", 4, 5, 6))])
        self.assertEqual(f["base_objects"], [1, 2])
        self.assertEqual(f["non_connectors"], [4, 5, 6])
        self.assertEqual(N.parse_skyrim(f["nvnm"])["vertices"][1], (140.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
