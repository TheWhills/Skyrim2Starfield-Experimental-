"""scripts/interior/door_survey.py on a synthetic plugin, and the Persistent flag PluginSpike now sets on load doors."""
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
from test_fo4land import grup, rec  # noqa: E402
from test_skyrim_interior import PERSISTENT, interior, ref, z  # noqa: E402
import door_survey  # noqa: E402

DOOR_B, HOUSE, CELLAR, A, B, LONE = 0x120, 0x2000, 0x2100, 0x3001, 0x3101, 0x3201


def xtel36(door, pos, extra=0):
    return (b"XTEL", struct.pack("<I6fII", door, *pos, 0.0, 0.0, 1.5, 0, extra))


def build(path):
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
    door = grup(b"DOOR", 0, [rec(b"DOOR", DOOR_B, [(b"EDID", z("LoadDoor01")), (b"MODL", z("doors\\load01.nif")),
                                                   (b"BFCB", z("BGSAnimationGraph_Component")), (b"FNAM", b"\x04")])])
    house = interior(HOUSE, "House", [ref(A, DOOR_B, (10.0, 0.0, 0.0), flags=PERSISTENT,
                                          extra=[xtel36(B, (0.0, 1.0, 0.0), extra=CELLAR)])])
    cellar = interior(CELLAR, "Cellar", [ref(B, DOOR_B, (0.0, 2.0, 0.0), flags=PERSISTENT,
                                             extra=[xtel36(A, (10.0, 1.5, 0.0))]),
                                         ref(LONE, DOOR_B, (5.0, 5.0, 0.0), extra=[xtel36(0x9999, (0.0, 0.0, 0.0))])])
    with open(path, "wb") as fh:
        fh.write(tes4 + door + grup(b"CELL", 0, house + cellar))


class DoorSurveyTests(unittest.TestCase):
    def test_report(self):
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "t.esm")
            build(esm)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(door_survey.main(["--esm", esm, "--out", d]), 0)
            r = json.load(open(os.path.join(d, "door_survey.json")))
        self.assertEqual(r["load_door_refs"], 3)
        self.assertEqual((r["destinations_found"], r["mutual_pairs"]), (2, 2))     # the lone door's target is unknown
        s = r["semantics"]["xtel_pos_to_destination_door_units"]
        self.assertEqual((s["min"], s["max"]), (1.0, 1.5))                          # A lands 1 m from B, B 1.5 m from A
        self.assertEqual(dict(map(tuple, r["xtel"]["sizes"])), {36: 3})
        self.assertEqual(dict(map(tuple, r["xtel"]["extra"])), {"set": 1, "zero": 2})
        self.assertEqual(dict(map(tuple, r["xtel"]["extra_record_types"])), {"CELL": 1})
        self.assertEqual(dict(map(tuple, r["ref_flags"])), {"persistent": 2, "temporary": 1})
        self.assertEqual(dict(map(tuple, r["base_types"])), {"DOOR": 3})
        db = r["door_bases"]
        self.assertEqual(db["fnam"], [["04", 1]])
        self.assertEqual(db["components"], [["BGSAnimationGraph_Component", 1]])
        self.assertEqual(db["examples"][0]["edid"], "LoadDoor01")


class PluginSpikeSourceTests(unittest.TestCase):
    def test_load_doors_get_the_persistent_flag(self):
        src = open(os.path.join(ROOT, "dotnet", "PluginSpike", "Program.cs"), encoding="utf-8").read()
        self.assertIn("if (tele0(r)) { obj.MajorRecordFlagsRaw |= 0x400; cell.Persistent.Add(obj); }", src)


if __name__ == "__main__":
    unittest.main()
