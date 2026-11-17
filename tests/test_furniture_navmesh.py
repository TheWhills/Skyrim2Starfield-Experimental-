"""scripts/npc/furniture_navmesh.py: furniture spots against navmesh triangles (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "src"))
import furniture_navmesh as F  # noqa: E402

# one square of navmesh from (0, 0) to (100, 100) at height 0
NAV = [{"geometry": {"vertices": [(0, 0, 0, 0), (100, 0, 0, 0), (100, 100, 0, 0), (0, 100, 0, 0)],
                     "triangles": [{"v": (0, 1, 2), "flags": 0}, {"v": (0, 2, 3), "flags": 0}]}}]


class FurnitureNavmeshTest(unittest.TestCase):
    def test_probe(self):
        tris = F.triangles(NAV)
        self.assertEqual(len(tris), 2)
        self.assertTrue(F.probe((50, 50, 0), tris)[0])
        on, d, _ = F.probe((150, 50, 0), tris)
        self.assertFalse(on)
        self.assertAlmostEqual(d, 50.0)
        self.assertFalse(F.probe((50, 50, 500), tris)[0])        # another floor

    def test_marker_and_sides(self):
        ref = {"pos": [50.0, 50.0, 0.0], "rot": [0.0, 0.0, 0.0]}
        (label, p, heading, entry), = F.marker_points(ref, [{"offset_m": [0, 0.5, 0], "rot_deg": 0.0,
                                                            "entry": ["Rear"]}])
        self.assertAlmostEqual(p[1], 50 + 0.5 / F.UNIT_M)
        self.assertEqual(entry, ["Rear"])
        ref90 = {"pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 1.5707963]}   # turned 90 deg clockwise: +Y -> +X
        (_, p90, h90, _), = F.marker_points(ref90, [{"offset_m": [0, 1.0, 0], "rot_deg": 0.0}])
        self.assertAlmostEqual(p90[0], 1.0 / F.UNIT_M, places=3)
        self.assertAlmostEqual(p90[1], 0.0, places=3)
        rear = F.side_point((0, 0, 0), 0.0, "Rear", 1.0)
        self.assertAlmostEqual(rear[1], -1.0 / F.UNIT_M)

    def test_report(self):
        refs = [{"base_editor_id": "CraftingBlackSmithForge", "formkey": "X", "base_formkey": "B",
                 "pos": [50.0, 50.0, 0.0], "rot": [0, 0, 0]},
                {"base_editor_id": "WoodenChair01", "formkey": "Y", "pos": [0, 0, 0], "rot": [0, 0, 0]}]
        txt = F.report(refs, {"B": {"markers": [{"offset_m": [0, 0, 0], "rot_deg": 0, "entry": ["Rear"]}]}},
                       F.triangles(NAV))
        self.assertIn("CraftingBlackSmithForge", txt)
        self.assertIn("ON navmesh", txt)
        self.assertNotIn("WoodenChair01", txt)


class RefTest(unittest.TestCase):
    def test_ref_position_and_distances(self):
        import struct
        self.assertEqual(F.ref_position([(b"DATA", struct.pack("<6f", 1, 2, 3, 0, 0, 0))]), (1.0, 2.0, 3.0))
        self.assertIsNone(F.ref_position([]))
        refs = [{"pos": [70.0, 0.0, 0.0], "base_editor_id": "Forge", "formkey": "A"},
                {"pos": [0.0, 140.0, 0.0], "base_editor_id": "Tanning", "formkey": "B"}]
        txt = F.distances("XMarkerHeading", (0.0, 0.0, 0.0), refs)
        self.assertLess(txt.index("Forge"), txt.index("Tanning"))
        self.assertIn(f"{70 * F.UNIT_M:6.2f} m", txt)


if __name__ == "__main__":
    unittest.main()
