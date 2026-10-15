"""Skyrim interior cells -> export, PluginSpike cell JSON and the check step, on a synthetic Skyrim.esm (no game data)."""
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
from fo4sf import skyriminterior  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402

PERSISTENT = 0x400
WALL, COC, TORCH, DOOR_B, NPC_B = 0x100, 0x32, 0x110, 0x120, 0x130
INN, HOUSE, EMPTY = 0x2000, 0x2100, 0x2200
INN_DOOR, OUT_DOOR = 0x3001, 0x4001


def z(s):
    return s.encode() + b"\0"


def ref(fid, base, pos, rot=(0.0, 0.0, 0.0), flags=0, extra=()):
    r = rec(b"REFR", fid, [(b"NAME", struct.pack("<I", base)), (b"DATA", struct.pack("<6f", *pos, *rot)), *extra])
    return r[:8] + struct.pack("<I", flags) + r[12:] if flags else r


def xtel(door, pos, rot=(0.0, 0.0, 1.5)):
    return (b"XTEL", struct.pack("<I6fI", door, *pos, *rot, 0))


def xcll(ambient):
    d = bytes(ambient) + b"\0" + bytes([200, 150, 100, 0]) + bytes(4) + bytes(60)
    return (b"XCLL", d + bytes([10, 20, 30, 0]) + struct.pack("<3fI", 0.0, 1500.0, 3000.0, 0x1))


def interior(fid, edid, children, extra=()):
    cell = rec(b"CELL", fid, [(b"EDID", z(edid)), (b"DATA", b"\x01\x00"), *extra])
    return [cell, grup(fid, 6, [grup(fid, 9, children)])] if children else [cell]


def build():
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800))])
    stat = grup(b"STAT", 0, [rec(b"STAT", WALL, [(b"EDID", z("WRInnWall01")), (b"MODL", z("Architecture\\Whiterun\\WRInnWall01.nif"))]),
                             rec(b"STAT", COC, [(b"EDID", z("COCMarkerHeading")), (b"MODL", z("Marker_COCHeading.nif"))])])
    # a warm flickering torch, radius 512 units, fade 1.5 (DATA as xEdit wbDefinitionsTES5, SSE 48 bytes)
    tdata = struct.pack("<iI4BI6fIf", -1, 512, 255, 160, 80, 0, 0x8, 1.0, 90.0, 0.0, 0.2, 0.3, 0.1, 0, 0.0)
    ligh = grup(b"LIGH", 0, [rec(b"LIGH", TORCH, [(b"EDID", z("TorchSconce01")), (b"DATA", tdata),
                                                  (b"FNAM", struct.pack("<f", 1.5))])])
    door = grup(b"DOOR", 0, [rec(b"DOOR", DOOR_B, [(b"EDID", z("WRInnDoor01")), (b"MODL", z("Architecture\\Whiterun\\WRInnDoor01.nif"))])])
    inn = interior(INN, "SleepingGiantInn", [
        ref(0x2001, WALL, (100.0, 0.0, 0.0)), ref(0x2002, WALL, (300.0, 0.0, 0.0), (0.0, 0.0, 1.57)),
        ref(0x2003, TORCH, (150.0, 50.0, 200.0)),
        ref(0x2004, TORCH, (160.0, 50.0, 200.0), extra=[(b"XRDS", struct.pack("<f", 800.0))]),
        ref(0x2006, TORCH, (400.0, 50.0, 200.0), extra=[(b"XRDS", struct.pack("<f", 9.68))]),   # not a radius
        ref(INN_DOOR, DOOR_B, (0.0, 0.0, 0.0), flags=PERSISTENT, extra=[xtel(OUT_DOOR, (5000.0, 6000.0, 700.0))]),
        rec(b"ACHR", 0x2005, [(b"NAME", struct.pack("<I", NPC_B)), (b"DATA", struct.pack("<6f", 1, 2, 3, 0, 0, 0))])],
        extra=[xcll((90, 70, 50)), (b"LTMP", struct.pack("<I", 0x5000))])
    house = interior(HOUSE, "TestHouse", [ref(0x2101, WALL, (0.0, 0.0, 0.0)), ref(0x2102, COC, (10.0, 20.0, 30.0))])
    empty = interior(EMPTY, "EmptyRoom", [])
    cells = grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, inn + house + empty)])])
    # Tamriel: a persistent exterior door whose teleport lands inside the inn, near (40, 0, 0) facing 3.14
    wrld = rec(b"WRLD", 0x3C, [(b"EDID", z("Tamriel"))])
    pcell = rec(b"CELL", 0x3D, [(b"DATA", b"\x02\x00")])
    out_door = ref(OUT_DOOR, DOOR_B, (5000.0, 6000.0, 700.0), flags=PERSISTENT,
                   extra=[xtel(INN_DOOR, (40.0, 0.0, 0.0), (0.0, 0.0, 3.14))])
    world = grup(b"WRLD", 0, [wrld, grup(0x3C, 1, [pcell, grup(0x3D, 6, [grup(0x3D, 8, [out_door])])])])
    return tes4 + stat + ligh + door + cells + world


class InteriorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esm = os.path.join(self.tmp.name, "Skyrim.esm")
        with open(self.esm, "wb") as f:
            f.write(build())

    def tearDown(self):
        self.tmp.cleanup()

    def test_list(self):
        cells = {c["edid"]: c for c in skyriminterior.list_interiors(self.esm)}
        self.assertEqual(sorted(cells), ["EmptyRoom", "SleepingGiantInn", "TestHouse"])
        inn = cells["SleepingGiantInn"]
        self.assertEqual((inn["refs"], inn["lights"], inn["doors"], inn["actors"], inn["coc"]), (6, 3, 1, 1, False))
        self.assertTrue(cells["TestHouse"]["coc"])
        self.assertEqual(cells["EmptyRoom"]["refs"], 0)

    def test_export_arrival_from_the_door_that_leads_in(self):
        exp = skyriminterior.export_interior(self.esm, "sleepinggiantinn")
        self.assertEqual((exp["cell"], exp["cell_formkey"]), ("SleepingGiantInn", "002000:Skyrim.esm"))
        self.assertEqual(len(exp["refs"]), 6)
        self.assertEqual([d["reason"] for d in exp["deferred_refs"]], ["placed actor: NPCs are not translated"])
        self.assertEqual(exp["arrival"]["pos"], [40.0, 0.0, 0.0])
        self.assertAlmostEqual(exp["arrival"]["rot"][2], 3.14, places=5)
        self.assertIn("004001:Skyrim.esm", exp["arrival"]["source"])
        door = next(r for r in exp["refs"] if r["type"] == "Door")
        self.assertEqual(door["teleport_destination"]["door"], "004001:Skyrim.esm")
        self.assertEqual(exp["load_doors"], ["003001:Skyrim.esm"])
        house = skyriminterior.export_interior(self.esm, "TestHouse")
        self.assertEqual(house["arrival"]["source"], "COCMarkerHeading in the cell")
        with self.assertRaises(KeyError):
            skyriminterior.export_interior(self.esm, "Tamriel")

    def test_lights_and_cell_lighting(self):
        exp = skyriminterior.export_interior(self.esm, "SleepingGiantInn")
        a, b, c = [r["light"] for r in exp["refs"] if r["type"] == "Light"]
        self.assertEqual((c["radius"], c["ref_radius"]), (512.0, 9.68))         # tiny override ignored
        self.assertEqual((a["radius"], a["color"], a["fade"], a["flicker"]), (512.0, [255, 160, 80], 1.5, True))
        self.assertAlmostEqual(a["flicker_period"], 0.2, places=5)
        self.assertEqual(b["radius"], 800.0)                                   # XRDS on the reference wins
        lt = exp["lighting"]
        self.assertEqual((lt["ambient"], lt["directional"], lt["fog_far_color"]), ([90, 70, 50], [200, 150, 100],
                                                                                   [10, 20, 30]))
        self.assertEqual((lt["light_fade_begin"], lt["light_fade_end"], lt["inherits"]), (1500.0, 3000.0, 1))
        self.assertEqual(lt["template"], "005000:Skyrim.esm")
        cell = skyriminterior.plugin_cell(exp, [])
        self.assertEqual(cell["skyrim_lighting"]["ambient"], [90, 70, 50])
        self.assertEqual(sorted(r["light"]["radius"] for r in cell["refs"] if r["type"] == "Light"), [512.0, 512.0, 800.0])
        self.assertIsNone(skyriminterior.export_interior(self.esm, "TestHouse")["lighting"])

    def test_plugin_cell_keeps_selected_refs_lights_and_adds_arrival(self):
        exp = skyriminterior.export_interior(self.esm, "SleepingGiantInn")
        walls = [r for r in exp["refs"] if r["type"] == "Static"]
        cell = skyriminterior.plugin_cell(exp, walls)
        types = sorted(r["type"] for r in cell["refs"])
        self.assertEqual(types, ["Light", "Light", "Light", "Static", "Static", "Static"])      # 2 walls + coc marker
        coc, = [r for r in cell["refs"] if r["base_editor_id"] == "COCMarkerHeading"]
        self.assertEqual(coc["pos"], [40.0, 0.0, 10.0])
        house = skyriminterior.export_interior(self.esm, "TestHouse")
        hc = skyriminterior.plugin_cell(house, [])
        self.assertEqual([r["formkey"] for r in hc["refs"]], ["002102:Skyrim.esm"])   # its own marker, no extra

    def test_script_export_and_check(self):
        import make_skyrim_interior as mi
        work = os.path.join(self.tmp.name, "work")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            mi.main(["list", "--skyrim", self.esm, "--find", "inn"])
        self.assertIn("SleepingGiantInn", out.getvalue())
        self.assertNotIn("TestHouse", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            mi.main(["export", "--skyrim", self.esm, "--cell", "SleepingGiantInn", "--work", work])
        conv = json.load(open(os.path.join(work, "convert_input.json")))
        self.assertEqual(sorted(m["model"] for m in conv["refs"]),
                         ["Architecture\\Whiterun\\WRInnDoor01.nif", "Architecture\\Whiterun\\WRInnWall01.nif"])
        rep = json.load(open(os.path.join(work, "interior.json")))
        self.assertEqual((rep["to_convert"], rep["lights"], rep["models"]), (3, 3, 2))
        # the convert step's manifest (make_skyrim_objects.py convert): the wall converted, the door failed
        os.makedirs(os.path.join(work, "convert", "meshes", "skyrim", "architecture"))
        open(os.path.join(work, "convert", "meshes", "skyrim", "architecture", "wrinnwall01.nif"), "wb").close()
        json.dump({"items": [{"editor_id": "WRInnWall01", "model": "skyrim\\architecture\\wrinnwall01.nif",
                              "source": "meshes\\architecture\\whiterun\\wrinnwall01.nif"}],
                   "failures": [{"nif": "meshes\\architecture\\whiterun\\wrinndoor01.nif", "reason": "NifError: x 12"}]},
                  open(os.path.join(work, "convert", "manifest.json"), "w"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = mi.main(["check", "--work", work])
        chk = json.load(open(os.path.join(work, "check.json")))
        self.assertEqual((chk["placed_refs"], chk["converted_refs"], chk["missing_refs"], chk["coc_marker"]),
                         (3, 2, 1, True))
        self.assertEqual(chk["missing_reasons"], {"NifError: x #": 1})
        self.assertEqual(code, 0)
        self.assertIn("dotnet run --project dotnet\\PluginSpike", out.getvalue())
        self.assertIn("deploy_starfield.py install", out.getvalue())
        self.assertIn("coc FO4Port_SleepingGiantInn", out.getvalue())

    def test_export_writes_brighter_lighting_and_keeps_hand_edits(self):
        import make_skyrim_interior as mi
        work = os.path.join(self.tmp.name, "work")
        path = os.path.join(work, "convert", "lighting.json")
        with contextlib.redirect_stdout(io.StringIO()):
            mi.main(["export", "--skyrim", self.esm, "--cell", "SleepingGiantInn", "--work", work])
        self.assertEqual(json.load(open(path)), {"SleepingGiantInn": {
            "LIGHTING_TEMPLATE": "006658", "LIGHT_MERGE_M": "1", "IMAGE_SPACE": "1C6C37", "CELL_AMBIENT": "skyrim",
            "LIGHT_POWER": "4"}})
        cfg = {"*": {"IMAGE_SPACE": "000123"}, "SleepingGiantInn": {"LIGHTING_TEMPLATE": "0ABCDE", "OMNI_LIGHT": "1"}}
        json.dump(cfg, open(path, "w"))
        with contextlib.redirect_stdout(io.StringIO()):
            mi.main(["export", "--skyrim", self.esm, "--cell", "SleepingGiantInn", "--work", work])
        got = json.load(open(path))
        self.assertEqual(got["*"], {"IMAGE_SPACE": "000123"})
        self.assertEqual(got["SleepingGiantInn"], {"LIGHTING_TEMPLATE": "0ABCDE", "LIGHT_MERGE_M": "1", "OMNI_LIGHT": "1",
                                                   "IMAGE_SPACE": "1C6C37", "CELL_AMBIENT": "skyrim", "LIGHT_POWER": "4"})
        with contextlib.redirect_stdout(io.StringIO()):
            mi.main(["export", "--skyrim", self.esm, "--cell", "SleepingGiantInn", "--work", work,
                     "--lighting-template", "111111", "--light-merge-m", "0.5"])
        got = json.load(open(path))["SleepingGiantInn"]
        self.assertEqual((got["LIGHTING_TEMPLATE"], got["LIGHT_MERGE_M"]), ("111111", "0.5"))

    def test_refuses_work_inside_the_repository(self):
        import make_skyrim_interior as mi
        with self.assertRaises(SystemExit):
            mi.main(["export", "--skyrim", self.esm, "--cell", "TestHouse", "--work", os.path.join(ROOT, "w")])


if __name__ == "__main__":
    unittest.main()
