"""Batch interior export: one read of Skyrim.esm for many cells, cells picked by name / regex / load-door distance,
load doors linked inside the batch, one shared model list (synthetic plugin, no game data)."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import fo4land, skyriminterior  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402
from test_skyrim_interior import PERSISTENT, interior, ref, xtel, z  # noqa: E402
import test_skyrimnavmesh  # noqa: E402

WALL, BARREL, DOOR_B, NPC_B = 0x100, 0x101, 0x120, 0x130
INN, CELLAR, CRYPT, HOUSE = 0x2000, 0x2100, 0x2200, 0x2300
INN_OUT, INN_DOWN, CELLAR_UP, CELLAR_DOWN, CRYPT_UP, HOUSE_OUT, WORLD_INN, WORLD_HOUSE = (
    0x3001, 0x3002, 0x3101, 0x3102, 0x3201, 0x3301, 0x4001, 0x4002)


def door(fid, to, pos):
    return ref(fid, DOOR_B, pos, flags=PERSISTENT, extra=[xtel(to, (pos[0] + 50.0, pos[1], pos[2]))])


def build():
    """Riverwood-like: the inn (door out, door down to the cellar), the cellar (up, down to a crypt), the crypt (up),
    a house reached only from the worldspace. Inn and cellar navmeshes."""
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800))])
    stat = grup(b"STAT", 0, [rec(b"STAT", WALL, [(b"EDID", z("WRInnWall01")), (b"MODL", z("Architecture\\WRInnWall01.nif"))]),
                             rec(b"STAT", BARREL, [(b"EDID", z("Barrel01")), (b"MODL", z("Clutter\\Barrel01.nif"))])])
    doors = grup(b"DOOR", 0, [rec(b"DOOR", DOOR_B, [(b"EDID", z("WRDoor01")), (b"MODL", z("Architecture\\WRDoor01.nif"))])])
    nav = lambda fid, cell: rec(b"NAVM", fid, [(b"NVNM", test_skyrimnavmesh.skyrim_nvnm(cell=cell))])
    inn = interior(INN, "RiverwoodInn", [ref(0x2001, WALL, (0.0, 0.0, 0.0)), door(INN_OUT, WORLD_INN, (0.0, 0.0, 0.0)),
                                         door(INN_DOWN, CELLAR_UP, (300.0, 0.0, 0.0)), nav(0x2007, INN),
                                         rec(b"ACHR", 0x2005, [(b"NAME", struct.pack("<I", NPC_B)),
                                                               (b"DATA", struct.pack("<6f", 1, 2, 3, 0, 0, 0))])])
    cellar = interior(CELLAR, "RiverwoodInnCellar", [ref(0x2101, BARREL, (10.0, 0.0, 0.0)),
                                                     door(CELLAR_UP, INN_DOWN, (0.0, 0.0, -300.0)),
                                                     door(CELLAR_DOWN, CRYPT_UP, (200.0, 0.0, -300.0)),
                                                     nav(0x2107, CELLAR)])
    crypt = interior(CRYPT, "RiverwoodCrypt", [ref(0x2201, WALL, (0.0, 0.0, 0.0)), door(CRYPT_UP, CELLAR_DOWN, (0.0, 0.0, -900.0))])
    house = interior(HOUSE, "RiverwoodHouse", [ref(0x2301, BARREL, (0.0, 0.0, 0.0)), door(HOUSE_OUT, WORLD_HOUSE, (0.0, 0.0, 0.0))])
    cells = grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, inn + cellar + crypt + house)])])
    wrld = rec(b"WRLD", 0x3C, [(b"EDID", z("Tamriel"))])
    pcell = rec(b"CELL", 0x3D, [(b"DATA", b"\x02\x00")])
    world = grup(b"WRLD", 0, [wrld, grup(0x3C, 1, [pcell, grup(0x3D, 6, [grup(0x3D, 8, [
        door(WORLD_INN, INN_OUT, (5000.0, 6000.0, 700.0)), door(WORLD_HOUSE, HOUSE_OUT, (5400.0, 6000.0, 700.0))])])])])
    return tes4 + stat + doors + cells + world


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esm = os.path.join(self.tmp.name, "Skyrim.esm")
        with open(self.esm, "wb") as f:
            f.write(build())

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, p):
        return skyriminterior.Source(p)

    def test_door_index_and_connected(self):
        with fo4land.Plugin(self.esm) as p:
            src = self.source(p)
            doors = src.doors()
            self.assertEqual(doors[WORLD_INN][0], None)                     # a worldspace door
            self.assertEqual(doors[INN_DOWN][0], INN)
            self.assertEqual(doors[INN_DOWN][1][0], CELLAR_UP)
            self.assertEqual(src.connected("riverwoodinn", 0), ["RiverwoodInn"])
            self.assertEqual(src.connected("RiverwoodInn", 1), ["RiverwoodInn", "RiverwoodInnCellar"])
            self.assertEqual(src.connected("RiverwoodInn", 5), ["RiverwoodInn", "RiverwoodInnCellar", "RiverwoodCrypt"])
            with self.assertRaises(KeyError):
                src.connected("Nowhere", 1)

    def test_pick_cells(self):
        with fo4land.Plugin(self.esm) as p:
            src = self.source(p)
            self.assertEqual(skyriminterior.pick_cells(src, find="house|crypt"), ["RiverwoodCrypt", "RiverwoodHouse"])
            self.assertEqual(skyriminterior.pick_cells(src, names=["riverwoodhouse"], connected_from="RiverwoodInn"),
                             ["RiverwoodHouse", "RiverwoodInn", "RiverwoodInnCellar"])
            self.assertEqual(skyriminterior.pick_cells(src, find="^Riverwood", limit=2), ["RiverwoodCrypt", "RiverwoodHouse"])
            with self.assertRaises(KeyError):
                skyriminterior.pick_cells(src, names=["Nowhere"])

    def test_export_marks_destination_cells(self):
        with fo4land.Plugin(self.esm) as p:
            exp = self.source(p).export("RiverwoodInn")
        dests = {r["formkey"]: r["teleport_destination"]["cell"] for r in exp["refs"] if "teleport_destination" in r}
        self.assertEqual(dests, {"003001:Skyrim.esm": "exterior", "003002:Skyrim.esm": "RiverwoodInnCellar"})
        self.assertIn("004001:Skyrim.esm", exp["arrival"]["source"])          # still the door that leads in
        # same answer as the one-cell path
        self.assertEqual(skyriminterior.export_interior(self.esm, "RiverwoodInn")["arrival"], exp["arrival"])

    def test_link_load_doors(self):
        with fo4land.Plugin(self.esm) as p:
            src = self.source(p)
            exports = [src.export(n) for n in ("RiverwoodInn", "RiverwoodInnCellar")]
        stats = skyriminterior.link_load_doors(exports)
        self.assertEqual(stats["linked"], 2)                                  # inn <-> cellar, both ways
        self.assertEqual(stats["unlinked"], {"to the worldspace (exterior plugin: not linked yet)": 1,
                                             "to a cell outside the batch (RiverwoodCrypt)": 1})
        down = next(r for r in exports[0]["refs"] if r["formkey"] == "003002:Skyrim.esm")
        self.assertEqual(down["teleport"]["door"], "003101:Skyrim.esm")
        self.assertEqual(down["teleport"]["cell"], "RiverwoodInnCellar")
        self.assertEqual(down["teleport"]["pos"], [350.0, 0.0, 0.0])          # the XTEL landing point, as written
        cell = skyriminterior.plugin_cell(exports[0], exports[0]["refs"])
        self.assertEqual([r["formkey"] for r in cell["refs"] if "teleport" in r], ["003002:Skyrim.esm"])
        # relinking a smaller batch drops a link that no longer has a target
        stats = skyriminterior.link_load_doors(exports[:1])
        self.assertEqual(stats["linked"], 0)
        self.assertNotIn("teleport", down)

    def test_batch_navmesh_cut_uses_the_whole_batch(self):
        with fo4land.Plugin(self.esm) as p:
            src = self.source(p)
            inn = src.export("RiverwoodInn")
        geo = inn["navmeshes"][0]["geometry"]
        geo["edge_links"][0]["navmesh"] = "002107:Skyrim.esm"                  # the cellar's navmesh
        alone = skyriminterior.plugin_cell(inn, [])["navmeshes"][0]["geometry"]
        together = skyriminterior.plugin_cell(inn, [], batch_navmeshes={"002107:Skyrim.esm"})["navmeshes"][0]["geometry"]
        self.assertEqual(len(alone["edge_links"]), 0)
        self.assertEqual(len(together["edge_links"]), 1)

    def test_script_batch_and_check(self):
        import make_skyrim_interior as mi
        work = os.path.join(self.tmp.name, "work")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            mi.main(["batch", "--skyrim", self.esm, "--connected-from", "RiverwoodInn", "--depth", "1",
                     "--cells", "RiverwoodHouse", "--work", work])
        self.assertIn("3 cells, 3 models", out.getvalue())
        rep = json.load(open(os.path.join(work, "batch.json")))
        self.assertEqual([c["cell"] for c in rep["cells"]], ["RiverwoodHouse", "RiverwoodInn", "RiverwoodInnCellar"])
        self.assertEqual(rep["load_doors"]["linked"], 2)
        self.assertEqual([c["linked_doors"] for c in rep["cells"]], [0, 1, 1])
        self.assertEqual(rep["cells"][1]["actors"], 1)
        conv = json.load(open(os.path.join(work, "convert_input.json")))
        self.assertEqual(sorted(m["model"] for m in conv["refs"]), ["Architecture\\WRDoor01.nif",
                                                                   "Architecture\\WRInnWall01.nif", "Clutter\\Barrel01.nif"])
        listed = open(os.path.join(work, "cells.txt")).read().split()
        self.assertEqual([os.path.basename(x) for x in listed],
                         ["RiverwoodHouse.json", "RiverwoodInn.json", "RiverwoodInnCellar.json"])
        self.assertTrue(json.load(open(listed[1]))["navmeshes"])
        self.assertEqual(sorted(json.load(open(os.path.join(work, "convert", "lighting.json")))),
                         ["RiverwoodHouse", "RiverwoodInn", "RiverwoodInnCellar"])
        # conversion: everything but the door model
        os.makedirs(os.path.join(work, "convert", "meshes", "skyrim"))
        items = []
        for name, src in (("wall", "architecture\\wrinnwall01.nif"), ("barrel", "clutter\\barrel01.nif")):
            open(os.path.join(work, "convert", "meshes", "skyrim", name + ".nif"), "wb").close()
            items.append({"editor_id": name, "model": f"skyrim\\{name}.nif", "source": "meshes\\" + src})
        json.dump({"items": items, "failures": [{"nif": "meshes\\architecture\\wrdoor01.nif", "reason": "bad"}]},
                  open(os.path.join(work, "convert", "manifest.json"), "w"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = mi.main(["check", "--work", work])
        chk = json.load(open(os.path.join(work, "check.json")))
        inn = chk["cells"][1]
        self.assertEqual((inn["linked_doors"], inn["linked_doors_not_converted"]), (1, 1))
        self.assertIn("@" + os.path.join(work, "cells.txt"), out.getvalue())
        self.assertIn("no teleport", out.getvalue())
        self.assertEqual(code, 0)
        with self.assertRaises(SystemExit):
            mi.main(["batch", "--skyrim", self.esm, "--find", "nothing-matches", "--work", work])


if __name__ == "__main__":
    unittest.main()
