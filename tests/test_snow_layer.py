"""Snow on rocks as Starfield's global snow layer per exterior cell (2026-11-25): esm_patch.set_cell_fields,
skyrimrefs.directional_materials, snow_layer.plan_cells. Synthetic plugins only."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fo4sf import esm_patch, fo4land, skyrimrefs  # noqa: E402
from test_alt_textures import field, group, record, tes4, walk_ok, z  # noqa: E402

W = 0x01000700


def cell(fid, xy, *extra):
    return record(b"CELL", fid, field(b"DATA", b"\x02\x00"), field(b"XCLC", struct.pack("<ii", *xy) + bytes(4)), *extra)


def plugin():
    ref = record(b"REFR", 0x01000900, field(b"NAME", struct.pack("<I", 0x01000800)), field(b"DATA", bytes(24)))
    persistent = cell(0x01000701, (0, 0))                                  # the world's persistent cell: XCLC 0, 0
    a = cell(0x01000702, (1, 2))
    b = cell(0x01000703, (0, 0), field(b"XCGD", z("old.mat")))
    kids = group(struct.pack("<I", 0x01000702), ref, gtype=9)
    sub = group(struct.pack("<hh", 0, 0), a, kids, b, gtype=5)
    block = group(struct.pack("<hh", 0, 0), sub, gtype=4)
    wrld = group(b"WRLD", record(b"WRLD", W, field(b"EDID", z("SKY_Tamriel"))),
                 group(struct.pack("<I", W), persistent, block, gtype=1))
    return tes4(["Starfield.esm"], count=6, nxt=0x901) + group(b"STAT", record(b"STAT", 0x01000800)) + wrld


class SetCellFieldsTest(unittest.TestCase):
    def test_add_replace_remove(self):
        src = plugin()
        out, changed, missing = esm_patch.set_cell_fields(
            src, W, {(1, 2): {b"XCGD": z("snow.mat")}, (5, 5): {b"XCGD": z("x.mat")}}, remove=(b"XCGD",))
        self.assertEqual((changed, missing), (2, [(5, 5)]))     # (1, 2) gains it, (0, 0) loses its old one
        recs = walk_ok(out)                                      # every group size adds up
        self.assertEqual(fo4land.zstring(recs[0x01000702][1][b"XCGD"]), "snow.mat")
        self.assertNotIn(b"XCGD", recs[0x01000703][1])
        self.assertNotIn(b"XCGD", recs[0x01000701][1])           # the persistent cell (also 0, 0) never touched
        self.assertEqual(recs[0x01000900][0], b"REFR")           # the cell's references kept
        # set on the exterior (0, 0): the persistent cell with the same XCLC stays as it was
        out2, changed2, _ = esm_patch.set_cell_fields(src, W, {(0, 0): {b"XCGD": z("snow.mat")}})
        recs2 = walk_ok(out2)
        self.assertEqual(changed2, 1)
        self.assertEqual(fo4land.zstring(recs2[0x01000703][1][b"XCGD"]), "snow.mat")
        self.assertNotIn(b"XCGD", recs2[0x01000701][1])
        # nothing to do: the bytes stay the same
        same, n, _ = esm_patch.set_cell_fields(out, W, {(1, 2): {b"XCGD": z("snow.mat")}}, remove=(b"XCGD",))
        self.assertEqual((same, n), (out, 0))

    def test_other_world_untouched(self):
        src = plugin()
        out, changed, missing = esm_patch.set_cell_fields(src, 0x01000999, {(1, 2): {b"XCGD": z("s.mat")}})
        self.assertEqual((out, changed, missing), (src, 0, [(1, 2)]))


class DirectionalMaterialsTest(unittest.TestCase):
    def test_load_order(self):
        with tempfile.TemporaryDirectory() as d:
            sky = tes4() + group(b"STAT",
                                 record(b"STAT", 0x0B0001, field(b"DNAM", struct.pack("<fI", 90.0, 0x025129))),
                                 record(b"STAT", 0x0B0002, field(b"DNAM", struct.pack("<fI", 90.0, 0))),
                                 record(b"STAT", 0x0B0003, field(b"DNAM", struct.pack("<fI", 60.0, 0x02871B)))) \
                + group(b"MATO", record(b"MATO", 0x025129, field(b"EDID", z("SnowMaterialObject1P"))),
                        record(b"MATO", 0x02871B, field(b"EDID", z("SnowMaterialObjectLight1P"))))
            upd = tes4(["Skyrim.esm"]) + group(b"STAT", record(b"STAT", 0x0B0003, field(
                b"DNAM", struct.pack("<fII", 75.0, 0x025129, 1))))     # Update's 12-byte DNAM, another material
            for name, data in (("Skyrim.esm", sky), ("Update.esm", upd)):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(data)
            dm = skyrimrefs.directional_materials(d)
        self.assertEqual(dm["0B0001:Skyrim.esm"], {"max_angle": 90.0, "material": "025129:Skyrim.esm",
                                                   "edid": "SnowMaterialObject1P"})
        self.assertNotIn("0B0002:Skyrim.esm", dm)
        self.assertEqual(dm["0B0003:Skyrim.esm"]["max_angle"], 75.0)
        self.assertEqual(dm["0B0003:Skyrim.esm"]["edid"], "SnowMaterialObject1P")


class PlanTest(unittest.TestCase):
    def test_snow_class_and_cells(self):
        import snow_layer as S
        self.assertEqual(S.snow_class("SnowMaterialObject1P"), "medium")
        self.assertEqual(S.snow_class("SnowMaterialMountainLight1P"), "light")
        self.assertIsNone(S.snow_class("SnowLODMaterial"))
        self.assertIsNone(S.snow_class("TundraMossMaterialObject"))
        dm = {"S": {"edid": "SnowMaterialObject1P"}, "L": {"edid": "SnowMaterialObjectLight1P"},
              "M": {"edid": "TundraMossMaterialObject"}}
        refs = ([{"src": f"a{i}", "cell": [0, 0]} for i in range(4)] + [{"src": f"b{i}", "cell": [1, 0]} for i in range(4)]
                + [{"src": f"c{i}", "cell": [2, 0]} for i in range(2)] + [{"src": "grass#1", "cell": [3, 0]}])
        base_of = {"a0": "S", "a1": "S", "a2": "R", "a3": "R",           # half snow: medium
                   "b0": "L", "b1": "L", "b2": "S", "b3": "R",           # light wins
                   "c0": "M", "c1": "R"}                                 # moss is not snow
        cells, per = S.plan_cells({"refs": refs}, base_of, dm, min_share=0.25)
        self.assertEqual(cells, {(0, 0): "medium", (1, 0): "light"})
        self.assertNotIn((3, 0), per)                                    # not a Skyrim reference


if __name__ == "__main__":
    unittest.main()
