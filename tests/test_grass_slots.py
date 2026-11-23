"""scripts/terrain/grass_slots.py (2026-11-23): ground-cover slots next to the vanilla LTEX records they re-skin."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import grass_slots as G  # noqa: E402


class RowsTest(unittest.TestCase):
    def test_rows(self):
        overrides = [{"form_id": 0x30137, "skyrim": "LFieldGrass02", "vanilla_edid": "LRockLayered05"},
                     {"form_id": 0x557E2, "skyrim": "LRocks01", "vanilla_edid": "LDirt01"}]
        slots = {"000557E2": ["RockGrass01"], "00030137": ["FieldGrass01", "FieldGrass02"]}
        recs = {0x30137: {"edid": "LRockLayered05", "fields": {"EDID": "x", "BNAM": "m.mat", "MNAM": "rock", "HNAM": "01"}},
                0x557E2: {"edid": "LDirt01", "fields": {"MNAM": "dirt"}}}
        r = G.rows(overrides, slots, recs)
        self.assertEqual([x[0] for x in r], [0x30137, 0x557E2])
        self.assertEqual(r[0][1:4], ("LFieldGrass02", "LRockLayered05", {"MNAM": "rock", "HNAM": "01"}))
        self.assertEqual(r[0][4], ["FieldGrass01", "FieldGrass02"])
        self.assertEqual(r[1][2], "LDirt01")
        self.assertEqual(G.rows([], {"00000001": ["X"]}, {})[0][1:3], ("?", "?"))


if __name__ == "__main__":
    unittest.main()
