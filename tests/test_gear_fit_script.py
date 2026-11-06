"""scripts/armor/gear_fit.py: refuses an output inside the repository; the writer it shares with os_export."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import gear_fit  # noqa: E402
import os_export  # noqa: E402


class ScriptTests(unittest.TestCase):
    def test_out_inside_repo_refused(self):
        with self.assertRaises(SystemExit):
            gear_fit.main(["--skyrim-data", "x", "--starfield", "y", "--npc", "Ralof", "--name", "R",
                           "--out", os.path.join(ROOT, "tmp_out")])

    def test_sex_ok(self):
        self.assertTrue(gear_fit.sex_ok("malehands.nif", False))
        self.assertFalse(gear_fit.sex_ok("femalehands.nif", False))
        self.assertTrue(gear_fit.sex_ok("femalehands.nif", True))
        self.assertFalse(gear_fit.sex_ok("hands_m.nif", True))
        self.assertTrue(gear_fit.sex_ok("hands.nif", True))

    def test_shared_writer(self):
        self.assertTrue(callable(os_export.write_armor))


if __name__ == "__main__":
    unittest.main()


class MorphFileTests(unittest.TestCase):
    def test_morph_files_per_shape(self):
        import numpy as np
        from fo4sf import sfmorph, skyrimhair
        body = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]], float)
        m = sfmorph.parse(sfmorph.build(3, ["Overweight"], {"Overweight": {0: (0.02, 0, 0)}}))
        sh = skyrimhair.HairShape(b"StormCloak", body + 0.001, np.tile([0, 0, 1.0], (3, 1)), np.zeros((3, 3)),
                                  [(0, 0)] * 3, [(0, 1, 2)], [[("C_Chest", 1.0)]] * 3, -1, -1, -1)
        out = gear_fit.morph_files([sh], "S2S\\Ralof_outfit.nif", body, m)
        self.assertEqual(list(out), ["meshes/morphs/s2s/ralof_outfit/chargen/stormcloak/morph.dat"])
        back = sfmorph.parse(out["meshes/morphs/s2s/ralof_outfit/chargen/stormcloak/morph.dat"])
        self.assertEqual(back.num_vertices, 3)
        self.assertIn(0, back.deltas["Overweight"])
