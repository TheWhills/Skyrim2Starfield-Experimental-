"""scripts/armor/hkx_to_af.py helpers that need no CALUMI: finding the vanilla clip a --replace targets."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
try:
    import hkx_to_af as H  # noqa: E402  (imports numpy)
except ImportError:                                      # pragma: no cover - environments without numpy
    H = None
import skyrim_fixtures as F  # noqa: E402

AFX = b"<root><is_state>1</is_state><tag>Idle</tag><filename>Idle.af</filename></root>"


@unittest.skipIf(H is None, "numpy not installed")
class VanillaFileTests(unittest.TestCase):
    def test_from_disk_and_from_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            loose = os.path.join(tmp, "x", "Meshes", "Actors", "Human", "Animations", "Furniture", "Chair")
            os.makedirs(loose)
            with open(os.path.join(loose, "idle.afx"), "wb") as fh:
                fh.write(AFX)
            data, rel = H.vanilla_file(os.path.join(loose, "idle.afx"), None)
            self.assertEqual((data, rel), (AFX, "meshes/actors/human/animations/furniture/chair/idle.afx"))
            sf = os.path.join(tmp, "Data")
            os.makedirs(sf)
            F.starfield_meshes_ba2(os.path.join(sf, "Starfield - Animations.ba2"), {
                "meshes\\actors\\human\\animations\\furniture\\chair\\idle.afx": AFX,
                "meshes\\actors\\human\\animations\\furniture\\chair\\female\\idle.afx": b"<root/>"})
            data, rel = H.vanilla_file("Meshes\\Actors\\Human\\Animations\\Furniture\\Chair\\Idle.afx", sf)
            self.assertEqual((data, rel), (AFX, "meshes/actors/human/animations/furniture/chair/idle.afx"))
            with self.assertRaises(SystemExit):
                H.vanilla_file("meshes/actors/human/animations/missing.afx", sf)
            with self.assertRaises(SystemExit):
                H.vanilla_file("meshes/actors/human/animations/missing.afx", None)


if __name__ == "__main__":
    unittest.main()
