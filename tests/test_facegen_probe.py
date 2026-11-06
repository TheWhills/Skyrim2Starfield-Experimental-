"""scripts/npc/facegen_probe.py scan() on synthetic archive listings."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
import facegen_probe as P  # noqa: E402


class ScanTests(unittest.TestCase):
    def test_scan(self):
        names = {"Starfield - FaceMeshes.ba2": ["Meshes\\Actors\\Character\\FaceGenData\\Starfield.esm\\0002F617.nif",
                                                "Meshes\\Actors\\Character\\FaceGenData\\Starfield.esm\\0012F617.nif"],
                 "Starfield - Textures01.ba2": ["textures\\other\\x_02f617_y.dds", "textures\\a.dds"]}
        r = P.scan(names, ["0002F617"])
        hits = r["form_id_hits"]["0002F617"]
        self.assertEqual(len(hits), 2)                       # the exact id (8 or 6 digits), not 0012F617
        self.assertTrue(any("FaceGenData" in h for h in hits))
        self.assertEqual(r["face_folders"][0][1], 2)


if __name__ == "__main__":
    unittest.main()
