"""scripts/armor/furniture_graph_probe.py: tags of a folder and who answers a graph tag, on synthetic files."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import furniture_graph_probe as G  # noqa: E402

A = "meshes\\actors\\human\\animations\\"


class GraphProbeTest(unittest.TestCase):
    def test_folder_tags_and_resolve(self):
        files = {A + "furniture\\chair\\idle.afx": b"<root><tag>Idle</tag></root>",
                 A + "common\\grip.afx": b"<root><tag>GripOffset_LeftArm</tag><variables><variable><name>"
                                         b"bEnableHandIK</name></variable></variables></root>",
                 A + "common\\sub\\deep.afx": b"<root><tag>Deep</tag></root>"}
        names = sorted(files)
        chair = G.folder_tags(names, files.get, A + "furniture\\chair")
        common = G.folder_tags(names, files.get, A + "common")
        self.assertEqual(chair, {"idle": ("idle.afx", False)})
        self.assertEqual(common, {"gripoffset_leftarm": ("grip.afx", True)})       # not the subfolder
        by = {A + "furniture\\chair": chair, A + "common": common}
        chains = [[A + "furniture\\chair", A + "common"]]
        self.assertEqual(G.resolve("Idle", chains, by, {"idle"}), "ours")
        self.assertEqual(G.resolve("GripOffset_LeftArm", chains, by, {"idle"}), ["common\\grip.afx (hand IK)"])
        self.assertEqual(G.resolve("Nothing", chains, by, set()), [])

    def test_third_person_flags(self):
        self.assertTrue(G.THIRD("02 00 00 00"))
        self.assertFalse(G.THIRD("02 00 01 00"))
        self.assertFalse(G.THIRD(None))


if __name__ == "__main__":
    unittest.main()
