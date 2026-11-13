import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import furniture_anim_pack as P  # noqa: E402
import stance_plugin as SP  # noqa: E402


class PackTests(unittest.TestCase):
    """2026-11-13: Skyrim's sitting clips into our own folder under Starfield's chair tags."""

    def test_sit_mapping(self):
        idle, rest = P.replace_args("Sit")
        self.assertEqual(idle, ["meshes\\actors\\character\\animations\\male\\chair_idlebasevar1.hkx::"
                                "meshes\\actors\\human\\animations\\furniture\\chair\\idle.afx"])
        tpl = {r.split("::")[1].rsplit("\\", 1)[1] for r in rest}
        for t in ("enterfromstand.afx", "frontexittostand.afx", "leftenterfromstand.afx", "rightquickexittostand.afx"):
            self.assertIn(t, tpl)
        self.assertFalse(any("rear" in t for t in tpl))                        # Skyrim has no entry from behind
        self.assertIn("meshes\\actors\\character\\animations\\male\\chair_idlebasevar1shoulders.hkx::"
                      "meshes\\actors\\human\\animations\\furniture\\chair\\idle_flavor03.afx::Idle_Flavor04", rest)

    def test_folder_and_keyword_agree_with_the_plugin(self):
        import make_furniture as MF
        plugin_sets = {st: folder for st, _v, folder in SP.FURNITURE_SETS}
        for st, (folder, _tpl, _rows) in P.SETS.items():
            self.assertEqual("meshes\\" + plugin_sets[st], folder)               # the entry's SAPT = where the pack writes
            self.assertEqual(SP.furniture_keyword_edid(st), MF.anim_keyword_edid(st))
        self.assertTrue(set(MF.ANIM_SETS.values()) <= set(P.SETS))

    def test_hkx_args(self):
        class A:
            calumi, skyrim_data, starfield = "c.dll", "sky", "sf"
        args = P.hkx_args(A, "w", "meshes\\x", ["a::b"])
        self.assertIn("--align-com", args)
        self.assertEqual(args[args.index("--into") + 1], "meshes\\x")
        args = P.hkx_args(A, "w", "meshes\\x", ["a::b"], com=[0.1, -0.05])
        self.assertEqual(args[args.index("--com-shift") + 1], "0.1,-0.05")
        self.assertNotIn("--align-com", args)
        self.assertIn("--no-root-motion", args)


class AnimKeywordTests(unittest.TestCase):
    def test_add_anim_keywords(self):
        import make_furniture as MF
        out = {"bases": {"a": {"kind": "chair"}, "b": {"kind": "bench"}, "c": {"kind": "bed"}}}
        got = MF.add_anim_keywords(out, "X\\S2SStances.esm",
                                   read_keywords=lambda p: {"S2S_AnimFurnSkyrimSit": 0x01000810, "S2S_StanceHigh": 1})
        self.assertEqual(got, {"Sit": 2})
        self.assertEqual(out["bases"]["a"]["anim_keyword"], "000810:S2SStances.esm")
        self.assertEqual(out["bases"]["b"]["anim_set"], "Sit")
        self.assertNotIn("anim_keyword", out["bases"]["c"])
        out2 = {"bases": {"a": {"kind": "chair"}}}
        self.assertEqual(MF.add_anim_keywords(out2, "S2SStances.esm", read_keywords=lambda p: {}),
                         {"missing": ["Sit"]})
        self.assertNotIn("anim_keyword", out2["bases"]["a"])


if __name__ == "__main__":
    unittest.main()
