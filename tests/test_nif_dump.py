"""scripts/armor/nif_dump.py: block description of a skinned NIF written by os_export (synthetic)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import nif_dump as D  # noqa: E402
import os_export as E  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_armor_check import shape, bind_for, WORLD  # noqa: E402


class DumpTests(unittest.TestCase):
    def test_describe_two_shapes(self):
        binds = {b: bind_for(WORLD[b]) for b in WORLD}
        a = shape("A", [[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]], [[("A", 1.0)]] * 3)
        b = shape("B", [[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]], [[("B", 0.5), ("C", 0.5)]] * 3)
        files = E.body_nif_files([a, b], ["m.mat", "m.mat"], binds, "S2S/T")
        d = D.describe(files["meshes/S2S/T.nif"])
        types = [x["type"] for x in d["blocks"]]
        self.assertEqual(types.count("BSGeometry"), 2)
        inst = [x for x in d["blocks"] if x["type"] == "BSSkin::Instance"]
        self.assertEqual([x["bone_refs"] for x in inst], [[-1], [-1, -1]])
        self.assertEqual([x["tail"] for x in inst], ["00000000"] * 2)
        bd = [x for x in d["blocks"] if x["type"] == "BSSkin::BoneData"]
        self.assertEqual([(x["count"], x["bytes_per_bone"]) for x in bd], [(1, 68.0), (2, 68.0)])
        sa = [x for x in d["blocks"] if x["type"] == "SkinAttach"]
        self.assertEqual(sa[1]["bones"], ["B", "C"])
        self.assertTrue(any("BSSkin::Instance" in line for line in D.summary("t", d)))
        self.assertEqual(D.skinned_shape_count(files["meshes/S2S/T.nif"]), 2)
        self.assertEqual(D.skinned_shape_count(b"junk"), 0)


if __name__ == "__main__":
    unittest.main()
