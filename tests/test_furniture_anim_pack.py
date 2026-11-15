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
        self.assertEqual(set(MF.ANIM_SETS), set(P.SETS))                         # every set is used and built
        self.assertEqual([st for st, _v, _f in SP.FURNITURE_SETS][0], "Sit")     # Sit keeps its keyword FormID
        for st, (folder, tpl, rows) in P.SETS.items():
            self.assertTrue(any(r[0] == "idle.afx" for r in rows), st)             # every set has an Idle
            self.assertTrue(tpl.startswith(P.SF_ANIM + "furniture\\"), st)

    def test_standing_set(self):
        """Every flavor slot of the template is filled (the idle when there are no flavors), exits twice, instant."""
        folder, tpl, rows = P.standing_set("s2s_x", "desklean", "i.hkx", ("f1.hkx", "f2.hkx"), "e.hkx", "x.hkx", 3,
                                           instant=True)
        self.assertEqual(folder, P.SF_ANIM + "furniture\\s2s_x")
        self.assertEqual(rows, [("idle.afx", "i.hkx", None), ("idle_flavor01.afx", "f1.hkx", None),
                                ("idle_flavor02.afx", "f2.hkx", None), ("idle_flavor03.afx", "f1.hkx", None),
                                ("enterfromstand.afx", "e.hkx", None), ("exittostand.afx", "x.hkx", None),
                                ("quickexittostand.afx", "x.hkx", None), ("enterinstant.afx", "i.hkx", None)])
        _f, _t, rows = P.standing_set("s2s_y", "bartender", "i.hkx", n_flavors=2)
        self.assertEqual(rows, [("idle.afx", "i.hkx", None), ("idle_flavor01.afx", "i.hkx", None),
                                ("idle_flavor02.afx", "i.hkx", None)])

    def test_anim_set_for(self):
        """The lean markers share a template but get their own sets; forges keep Starfield's animations."""
        import make_furniture as MF
        cases = {("chair", "WoodenChair01"): "Sit", ("bench", "FarmBench01F"): "Sit",
                 ("lean_counter", "WallLeanMarker"): "WallLean", ("lean_counter", "RailLeanMarker"): "RailLean",
                 ("lean_counter", "CounterLeanMarker"): "Counter", ("bartender", "CounterBarLeanMarker"): "Counter",
                 ("lean_table", "LeanTableMarker"): "LeanTable", ("sweep", "SweepIdleMarker"): "Sweep",
                 ("alchemy", "CraftingAlchemyWorkbench"): "Alchemy",
                 ("workbench", "CraftingEnchantingWorkbenchTabletop"): "Enchant",
                 ("workbench", "CraftingBlackSmithForge"): None, ("cook", "CraftingCookingPotSm"): "Cook",
                 ("scrape", "CraftingTanningRackMarker"): "Tanning", ("bed", "CommonBed01"): None}
        for (kind, edid), want in cases.items():
            self.assertEqual(MF.anim_set_for({"kind": kind, "edid": edid}), want, edid)

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
        self.assertNotIn("--hand-clearance", args)
        args = P.hkx_args(A, "w", "meshes\\x", ["a::b"], com=[0.1, -0.05], hands=(0.13, 0.03))
        self.assertEqual(args[args.index("--hand-clearance") + 1], "0.13,0.03")
        self.assertEqual(P.HAND_CLEARANCE["Sit"], (0.13, 0.03))
        args = P.hkx_args(A, "w", "meshes\\x", ["a::b"], com=[0, 0], profiles="C:\\w\\body_profiles.json",
                          shoulders="C:\\w\\shoulders.json")
        self.assertEqual(args[args.index("--shoulder-calibration") + 1], "C:\\w\\shoulders.json")
        self.assertEqual(args[args.index("--body-profiles") + 1], "C:\\w\\body_profiles.json")

    def test_strip_events(self):
        """The dish rag's AnimObj events go; SetPos events and the audio stay; an emptied <events> goes."""
        afx = ("<root>\n<events>\n<event><frame>0</frame><name>AnimObjLoad</name><payload>AnimObjectDishRag</payload>"
               "</event>\n<event><frame>16</frame><name>SetPosBegin</name><payload></payload></event>\n"
               "<event><frame>26</frame><name>AnimObjDraw</name><payload>AnimObjectDishRag</payload></event>\n"
               "</events>\n<audios><audio><frame>26</frame><foley>X</foley></audio></audios>\n</root>")
        out = P.strip_events(afx)
        self.assertNotIn("AnimObj", out)
        self.assertIn("SetPosBegin", out)
        self.assertIn("<foley>X</foley>", out)
        only = "<root>\n<events>\n<event><frame>0</frame><name>AnimObjLoad</name></event>\n</events>\n</root>"
        self.assertNotIn("<events>", P.strip_events(only))
        self.assertEqual(P.KEEP_PROPS, ("Sweep",))

    def test_parse_pair(self):
        """PowerShell splits an unquoted 0.027,-0.091 into two arguments: every form gives the same pair."""
        for v in ("0.027,-0.091", ["0.027,-0.091"], ["0.027", "-0.091"]):
            self.assertEqual(P.parse_pair(v), [0.027, -0.091])


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

    def test_skyrim_markers_for_our_clips(self):
        """2026-11-15: a lean marker (SPECIAL) playing our clips takes Skyrim's NIF marker; a sweep idle marker (no NIF)
        the reference itself; a crafting station keeps the template's (the menu needs it); without the animations
        plugin the template's marker stays."""
        import make_furniture as MF
        U = MF.U
        lean = {"edid": "RailLeanMarker", "nif_markers": [{"offset": [0, -0.3 * U, 0],
                                                          "heading_deg": 180.0, "entry": ["Front"]}]}
        sky = MF.skyrim_markers(lean, "lean_counter", "floor")
        self.assertEqual(sky, [{"offset_m": [0.0, -0.3, 0.0], "rot_deg": 180.0, "entry": ["Front"]}])
        self.assertEqual(MF.markers(lean, "lean_counter", "floor"), [])                  # SPECIAL: template's
        self.assertEqual(MF.skyrim_markers({"edid": "SweepIdleMarker"}, "sweep", "floor"), MF.AT_THE_REFERENCE)
        out = {"bases": {
            "r": {"kind": "lean_counter", "edid": "RailLeanMarker", "markers": [], "skyrim_markers": sky},
            "s": {"kind": "sweep", "edid": "SweepIdleMarker", "markers": [],
                  "skyrim_markers": [dict(m) for m in MF.AT_THE_REFERENCE]},
            "a": {"kind": "alchemy", "edid": "CraftingAlchemyWorkbench", "markers": [], "skyrim_markers": sky}}}
        kws = {"S2S_AnimFurnSkyrimRailLean": 0x01000811, "S2S_AnimFurnSkyrimSweep": 0x01000815,
               "S2S_AnimFurnSkyrimAlchemy": 0x01000816}
        MF.add_anim_keywords(out, "S2SStances.esm", read_keywords=lambda p: kws)
        self.assertEqual(out["bases"]["r"]["markers"], sky)
        self.assertEqual(out["bases"]["s"]["markers"], MF.AT_THE_REFERENCE)
        self.assertEqual(out["bases"]["a"]["markers"], [])
        none = {"bases": {"r": {"kind": "lean_counter", "edid": "RailLeanMarker", "markers": [], "skyrim_markers": sky}}}
        MF.add_anim_keywords(none, "S2SStances.esm", read_keywords=lambda p: {})
        self.assertEqual(none["bases"]["r"]["markers"], [])


class DescriptorTests(unittest.TestCase):
    def test_strip_hand_ik(self):
        """2026-11-14: Starfield's seat descriptors turn hand IK on; ours leave it out (the arms twisted in game)."""
        afx = ("<root>\n\t<is_state>1</is_state>\n\t<tag>Idle</tag>\n\t<filename>Idle.af</filename>\n"
               "\t<flags>\n\t\t<flag>Disable Foot IK</flag>\n\t</flags>\n\t<variables>\n"
               "\t\t<variable><name>bUseStandToExit</name><start>0</start><end>274</end></variable>\n"
               "\t\t<variable><name>bEnableHandIK</name><start>0</start><end>274</end></variable>\n"
               "\t</variables>\n</root>\n")
        out = P.strip_variables(afx)
        self.assertNotIn("bEnableHandIK", out)
        self.assertIn("<variable><name>bUseStandToExit</name><start>0</start><end>274</end></variable>", out)
        self.assertIn("Disable Foot IK", out)
        from fo4sf import agx
        d = agx.read_descriptor(out.encode())
        self.assertEqual((d["tag"], d["is_state"]), ("Idle", "1"))
        only = afx.replace("\t\t<variable><name>bUseStandToExit</name><start>0</start><end>274</end></variable>\n", "")
        self.assertNotIn("<variables>", P.strip_variables(only))            # an emptied block goes too
        self.assertEqual(P.strip_variables(out), out)                        # nothing to strip: unchanged


if __name__ == "__main__":
    unittest.main()
