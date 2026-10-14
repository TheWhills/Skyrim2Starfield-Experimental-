"""scripts/terrain/teleport_audit.py on synthetic runner reports (spec.json + obs.json as qstep.ps1 writes them)."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("teleport_audit", root / "scripts" / "terrain" / "teleport_audit.py")
ta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ta)


def write_test(queue, name, spec_, obs):
    d = os.path.join(queue, "tests", name, "a1")
    os.makedirs(d)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec_, f)
    with open(os.path.join(d, "obs.json"), "w", encoding="utf-8-sig") as f:      # the runner writes a BOM
        json.dump(obs, f)


class AuditTests(unittest.TestCase):
    def test_cells_relocation_and_hops(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = os.path.join(tmp, "terrain_x")
            # merge offset (-1200, -2700); the player arrives at local (50, 50) = world (-1150, -2650)
            pts = [{"label": "arrival", "x": 50.0, "y": 50.0, "expect": 10.0},
                   {"label": "e_200", "x": 250.0, "y": 50.0, "expect": 10.0},      # 2 cells east: lands
                   {"label": "e_500", "x": 545.0, "y": 50.0, "expect": 10.0},      # 3 cells east: relocated
                   {"label": "e_600", "x": 645.0, "y": 50.0, "expect": 10.0}]      # starts from the relocated place
            obs = {"spawn_read": "-1150.00 -2650.00 10.00", "offset": [-1200.0, -2700.0, 0.0],
                   "points": [{"label": "arrival", "read": "-1150.00 -2650.00 10.00"},
                              {"label": "e_200", "read": "-950.00 -2650.00 10.00"},
                              {"label": "e_500", "read": "9500.00 -2650.00 150.00"},
                              {"label": "e_600", "read": "-555.00 -2650.00 150.00"}]}
            write_test(q, "0000_terrain_A", {"kind": "terrain", "drop_z": 150.0, "points": pts}, obs)
            # the same ray in hops of 200 m: 295 m east becomes two teleports of 147.5 m
            obs2 = {"spawn_read": "-1150.00 -2650.00 10.00", "offset": [-1200.0, -2700.0, 0.0],
                    "points": [{"label": "arrival", "read": "-1150.00 -2650.00 10.00"},
                               {"label": "e_200", "read": "-950.00 -2650.00 10.00"},
                               {"label": "e_500", "read": "-655.00 -2650.00 10.00"}]}
            write_test(q, "0001_terrain_A", {"kind": "terrain", "drop_z": 150.0, "hop_m": 200, "points": pts[:3]}, obs2)
            write_test(q, "0002_npc", {"kind": "npc_nav"}, {})
            rows, summary = ta.audit([q])
        a = [r for r in rows if r["attempt"].startswith(os.path.join("tests", "0000"))]
        self.assertEqual([(r["to"], r["cells"], r["result"], r["start_landed"]) for r in a],
                         [("arrival", [0, 0], "LANDED", True), ("e_200", [2, 0], "LANDED", True),
                          ("e_500", [3, 0], "RELOC", True), ("e_600", [-101, 0], "HUNG", False)])
        b = [r for r in rows if r["attempt"].startswith(os.path.join("tests", "0001"))]
        self.assertEqual([(r["to"], r["dx"], r["result"]) for r in b],
                         [("arrival", 0.0, "LANDED"), ("e_200", 200.0, "LANDED"), ("hop", 147.5, "LANDED"),
                          ("e_500", 147.5, "LANDED")])
        self.assertEqual(summary["at_most_2_cells"]["teleports"], 6)            # e_600 starts after a relocation
        self.assertEqual(summary["at_most_2_cells"]["hops"], 1)
        self.assertEqual(summary["3_or_more_cells"]["results"], {"RELOC": 1})
        self.assertEqual(summary["3_or_more_cells"]["smallest_axis_move_failed_m"], 295.0)
        self.assertEqual(summary["at_most_2_cells"]["largest_axis_move_landed_m"], 200.0)

    def test_unreadable_attempts_are_skipped(self):
        self.assertEqual(ta.test_teleports({"kind": "terrain", "points": [{"label": "a", "x": 0, "y": 0}]},
                                           {"spawn_read": "fail console 3"}), [])
        self.assertEqual(ta.outcome(None, (0.0, 0.0), 150.0), "NOREAD")
        self.assertEqual(ta.outcome("1.0 2.0 150.01", (0.0, 0.0), 150.0), "HUNG")


if __name__ == "__main__":
    unittest.main()
