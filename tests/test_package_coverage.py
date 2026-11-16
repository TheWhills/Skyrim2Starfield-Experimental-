"""scripts/npc/package_coverage.py: furniture inside a package's area (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
import package_coverage as C  # noqa: E402

FURN = {"bases": {"F:Skyrim.esm": {"edid": "CraftingBlackSmithForge", "kind": "forge", "anim_set": "Forge"},
                  "R:Skyrim.esm": {"edid": "RailLeanMarker", "kind": "lean_counter", "anim_set": "RailLean"},
                  "C:Skyrim.esm": {"edid": "WoodenChair01", "kind": "chair", "anim_set": "Sit"}},
        "refs": [{"formkey": "1", "cell": "exterior", "base": "F:Skyrim.esm", "pos": [700.0, 0.0, 0.0]},
                 {"formkey": "2", "cell": "exterior", "base": "R:Skyrim.esm", "pos": [3000.0, 0.0, 0.0]},
                 {"formkey": "3", "cell": "Inn", "base": "C:Skyrim.esm", "pos": [0.0, 0.0, 0.0]}]}


class PackageCoverageTest(unittest.TestCase):
    def test_furniture_in(self):
        near = {"kind": "location", "type": "near_exterior_reference", "pos": [0.0, 0.0, 0.0], "radius_m": 14.3}
        hits = C.furniture_in(near, FURN["refs"], FURN["bases"])
        self.assertEqual([(h[0], h[1]) for h in hits], [(10.0, "forge")])          # 700 units = 10 m; rail 42.9 m out
        self.assertEqual(len(C.furniture_in(dict(near, radius_m=0), FURN["refs"], FURN["bases"])), 0)
        cell = {"kind": "location", "type": "in_cell", "cell": "Inn"}
        self.assertEqual([h[1] for h in C.furniture_in(cell, FURN["refs"], FURN["bases"])], ["chair"])

    def test_report(self):
        actors = [{"name": "Alvor", "skyrim": "Alvor", "packages": [
            {"edid": "S2S_AlvorWork8x12", "skyrim_template": "SandboxWorking", "sf_template": "Sandbox",
             "schedule": {"hour": 8}, "inputs": {"1": {"kind": "location", "type": "near_exterior_reference",
                                                       "pos": [0, 0, 0], "radius_m": 14.3, "skyrim": "Location"}}}]}]
        out = C.report(actors, FURN)
        self.assertIn("radius 14.3 m -> 1 furniture", out[2])
        self.assertIn("forge CraftingBlackSmithForge [Forge]", out[3])


if __name__ == "__main__":
    unittest.main()
