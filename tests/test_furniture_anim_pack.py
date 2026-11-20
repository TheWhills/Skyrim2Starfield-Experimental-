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
        """The lean markers share a template but get their own sets; the forge plays Skyrim's (2026-11-16)."""
        import make_furniture as MF
        cases = {("chair", "WoodenChair01"): "Sit", ("bench", "FarmBench01F"): "Sit",
                 ("lean_counter", "WallLeanMarker"): "WallLean", ("lean_counter", "RailLeanMarker"): "RailLean",
                 ("lean_counter", "CounterLeanMarker"): "Counter", ("bartender", "CounterBarLeanMarker"): "Counter",
                 ("lean_table", "LeanTableMarker"): "LeanTable", ("sweep", "SweepIdleMarker"): "Sweep",
                 ("alchemy", "CraftingAlchemyWorkbench"): "Alchemy",
                 ("workbench", "CraftingEnchantingWorkbenchTabletop"): "Enchant",
                 ("forge", "CraftingBlackSmithForge"): "Forge",
                 ("grindstone", "CraftingBlacksmithSharpeningWheel"): "Grindstone",
                 ("workbench", "CraftingSmelterMarker1"): None, ("cook", "CraftingCookingPotSm"): "Cook",
                 ("scrape", "CraftingTanningRackMarker"): "Tanning", ("bed", "CommonBed01"): None}
        for (kind, edid), want in cases.items():
            self.assertEqual(MF.anim_set_for({"kind": kind, "edid": edid}), want, edid)

    def test_forge_set(self):
        """2026-11-16 (smithing_probe): Enter = Pull, Idle = Hammer, flavors = Temper / Discard + Pull (the fire is
        reached from the hammering too, not only on entering), Exit; Skyrim's own spot."""
        folder, tpl, rows = P.SETS["Forge"]
        # on the welder's folder, its own (2026-11-16, owner's A/B: sharing the tanning rack's stopped both)
        self.assertEqual((folder, tpl), (P.SF_ANIM + "furniture\\s2s_forge", P.SF_ANIM + "furniture\\welder"))
        d = dict((r[0], r[1]) for r in rows)
        self.assertEqual((d["enterfromstand.afx"], d["idle.afx"], d["exittostand.afx"]),
                         ("blacksmithforgepull.hkx", "blacksmithforgehammer.hkx", "blacksmithforgeexit.hkx"))
        both = "blacksmithforgediscard.hkx+blacksmithforgepull.hkx"
        self.assertEqual([d[f"idle_flavor{i:02d}.afx"] for i in range(1, 5)], ["blacksmithforgetemper.hkx", both] * 2)
        self.assertNotIn("idle_flavor05.afx", d)                                   # the welder has 4
        import stance_plugin as SP
        forge_kw = [v for name, v, _f in SP.FURNITURE_SETS if name == "Forge"][0]
        self.assertEqual(forge_kw, ("AnimFurnWelder",))
        others = [v for name, v, _f in SP.FURNITURE_SETS if name != "Forge"]
        self.assertFalse(any(set(forge_kw) & set(v) for v in others))            # no other set on it
        rep = [x for x in P.replace_args("Forge")[1] if "discard" in x][0]
        self.assertTrue(rep.startswith(P.SKY_ANIM + both + "::"), rep)
        self.assertEqual(d["enterinstant.afx"], "blacksmithforgehammer.hkx")      # spawned at work: props loaded
        self.assertEqual(P.COM_SHIFT["Forge"], (0.0, 0.0))
        # back 2026-11-16 21:19 on the standing repair spot of its own: Enter / Spin / Exit, 9 flavors all Spin
        folder, tpl, rows = P.SETS["Grindstone"]
        self.assertTrue(tpl.endswith("repair_toolstanding"))
        d = dict((r[0], r[1]) for r in rows)
        self.assertEqual((d["enterfromstand.afx"], d["idle.afx"], d["exittostand.afx"], d["idle_flavor09.afx"]),
                         ("blacksmithsharpeningwheelenter.hkx", "blacksmithsharpeningwheelspin.hkx",
                          "blacksmithsharpeningwheelexit.hkx", "blacksmithsharpeningwheelspin.hkx"))
        import stance_plugin as SP
        g = [v for n, v, _f in SP.FURNITURE_SETS if n == "Grindstone"][0]
        self.assertEqual(g, ("AnimFurnRepair_ToolStanding",))                    # its own template's keyword
        self.assertFalse(any(set(g) & set(v) for n, v, _f in SP.FURNITURE_SETS if n != "Grindstone"))

    def test_forge_props(self):
        """2026-11-16: the Forge set loads Skyrim's hammer and iron itself on entering, unequips them on exiting, and
        its clips key both prop bones."""
        enter = ("<?xml version=\"1.0\"?>\r\n<animation>\r\n\t<tag>EnterFromStand</tag>\r\n\t<events>\r\n"
                 "\t\t<event><frame>5</frame><name>Foo</name><payload></payload></event>\r\n\t</events>\r\n</animation>\r\n")
        out = P.add_set_props(enter, P.SET_PROP_OBJECTS["Forge"])
        import re
        evs = re.findall(r"<frame>(\d+)</frame><name>(\w+)</name><payload>([^<]*)</payload>", out)
        self.assertEqual(evs[:4], [("0", "AnimObjLoad", "S2S_AnimObjectForgeHammerSkyrim"),
                                   ("0", "AnimObjDraw", "S2S_AnimObjectForgeHammerSkyrim"),
                                   ("0", "AnimObjLoad", "S2S_AnimObjectForgeIronSkyrim"),
                                   ("0", "AnimObjDraw", "S2S_AnimObjectForgeIronSkyrim")])
        self.assertEqual(evs[4], ("5", "Foo", ""))
        ex = P.add_set_props(enter.replace("EnterFromStand", "ExitToStand"), P.SET_PROP_OBJECTS["Forge"])
        self.assertIn("<name>AnimObjUnequipAll</name>", ex)
        idle = enter.replace("EnterFromStand", "Idle")
        self.assertEqual(P.add_set_props(idle, P.SET_PROP_OBJECTS["Forge"]), idle)
        self.assertEqual(P.SET_PROPS["Forge"], ("AnimObjectR=R_AnimObject1", "AnimObjectL=L_AnimObject1"))
        import stance_plugin
        anio = {e for e, _v, _m in stance_plugin.PROP_OBJECTS}
        self.assertTrue(set(P.SET_PROP_OBJECTS["Forge"]) <= anio)

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

    def test_talk_copies(self):
        """38 talk / dialogue slots and 7 upper-body idle slots, each the Idle descriptor with its own tag and file name, the rest unchanged."""
        idle = ("<root>\n<is_state>1</is_state>\n<tag>Idle</tag>\n<filename>Idle.af</filename>\n"
                "<variables><variable><name>bUseStandToExit</name><start>0</start><end>274</end></variable></variables>"
                "\n</root>")
        got = P.talk_copies(idle)
        self.assertEqual(len(got), 45)
        self.assertIn("<tag>IdlePartialBody_Flavor04</tag>", got["idlepartialbody_flavor04.afx"])
        self.assertIn("idlepartialbody_stop.afx", got)
        self.assertEqual(sorted(got)[:2], ["idle_dialogue01.afx", "idle_dialogue02.afx"])
        t = got["talk_m16.afx"]
        self.assertIn("<tag>Talk_M16</tag>", t)
        self.assertIn("<filename>Talk_M16.af</filename>", t)
        self.assertIn("bUseStandToExit", t)
        self.assertNotIn("<tag>Idle</tag>", t)

    def test_vanilla_leftovers(self):
        """Starfield's own states we do not convert: copied with hand IK / prop events left out; ours, ones with
        nothing to leave out, and a tag an earlier folder already gave are not."""
        ik = ("<root><tag>{t}</tag><filename>{t}.af</filename><variables><variable><name>bEnableHandIK</name>"
              "<start>0</start><end>9</end></variable></variables></root>")
        chair, common = "meshes\\actors\\human\\animations\\furniture\\chair\\", \
            "meshes\\actors\\human\\animations\\furniture\\common\\"
        files = {chair + "rearenterfromstand.afx": ik.format(t="RearEnterFromStand").encode(),
                 chair + "rearenterfromstand.af": b"REAR",
                 chair + "idle.afx": ik.format(t="Idle").encode(),                 # ours already
                 chair + "camera.afx": b"<root><tag>Camera</tag><filename>Camera.af</filename></root>",
                 chair + "female\\enterinstant.afx": ik.format(t="EnterInstant").encode(),   # a subfolder: not read
                 common + "lookdirections.afx": ik.format(t="LookDirections").encode(),
                 common + "lookdirections.af": b"LOOK",
                 common + "rearenterfromstand.afx": ik.format(t="RearEnterFromStand").encode()}
        got = P.vanilla_leftovers(sorted(files), files.get, [chair[:-1], common], {"Idle"})
        self.assertEqual(sorted(got), ["lookdirections.afx", "rearenterfromstand.afx"])
        text, clip = got["rearenterfromstand.afx"]
        self.assertNotIn("bEnableHandIK", text)
        self.assertIn("<tag>RearEnterFromStand</tag>", text)
        self.assertEqual(clip, ("RearEnterFromStand.af", b"REAR"))       # read by its lower-case archive name
        self.assertIn("idle.afx", P.vanilla_leftovers(sorted(files), files.get, [chair, common], set()))
        inst = chair + "enterinstant.afx"                     # no hand IK, but the random-sit graph: copied, swapped
        files[inst] = (b"<root><tag>EnterInstant</tag><filename>EnterInstant.af</filename><events><event><name>"
                       b"LoadFurnitureGraph</name><payload>G\\FurnitureRandomSitChair.agx</payload></event></events>"
                       b"</root>")
        got = P.vanilla_leftovers(sorted(files), files.get, [chair], {"Idle"}, graph_swaps=P.GRAPH_SWAP["Sit"])
        self.assertIn("FurnitureGenericSit.agx", got["enterinstant.afx"][0])
        self.assertNotIn("enterinstant.afx", P.vanilla_leftovers(sorted(files), files.get, [chair], {"Idle"}))

    def test_unanswered_tags(self):
        """Tags of the template folders ours do not answer: idle-like ones flagged, enters / exits / look / camera not;
        ours and repeats skipped."""
        d = "meshes\\actors\\human\\animations\\furniture\\chair\\"
        files = {d + n + ".afx": f"<root><tag>{t}</tag></root>".encode() for n, t in (
            ("idle", "Idle"), ("idle_flavor05", "Idle_Flavor05"), ("breathe", "IdleBreathe"),
            ("rearenterfromstand", "RearEnterFromStand"), ("lookdirections", "LookDirections"), ("camera", "Camera"))}
        files[d + "female\\breathe.afx"] = b"<root><tag>IdleBreathe</tag></root>"
        got = P.unanswered_tags(sorted(files), files.get, [d, d + "female"], {"Idle"})
        self.assertEqual(sorted(got), [("Camera", False), ("IdleBreathe", True), ("Idle_Flavor05", True),
                                       ("LookDirections", False), ("RearEnterFromStand", False)])

    def test_base_tag(self):
        have = {"idle", "enterfromstand", "idle_flavor01"}
        self.assertEqual(P.base_tag("RelaxedIdle", have), "Idle")
        self.assertEqual(P.base_tag("Relaxed_EnterFromStand", have), "EnterFromStand")
        self.assertEqual(P.base_tag("Idle_PoseB", have), "Idle")
        self.assertEqual(P.base_tag("RelaxedIdle_Flavor01PoseC", have), "Idle_Flavor01")
        self.assertIsNone(P.base_tag("Idle", have))                       # not renamed
        self.assertIsNone(P.base_tag("RelaxedCamera", have))

    def test_mood_variants(self):
        af = "meshes\\actors\\human\\animations\\furniture\\chair\\animflavor\\"
        cm = "meshes\\actors\\human\\animations\\common\\"
        names = [af + "analyze_idle.af", af + "confident_idle_flavor02.af", af + "crosslegs_talk_l01.af",
                 af + "bored_lookdirections.af", af + "idle.af", af + "sub\\analyze_idle.af",
                 cm + "relaxed_idlepartialbody_flavor01_handsbehind.af", cm + "castself.af"]
        ours = {"idle": "Idle.af", "idle_flavor02": "Idle_Flavor02.af", "talk_l01": "Talk_L01.af"}
        got = P.mood_variants(names, [af, cm], ours)
        self.assertEqual(got, {"analyze_idle.af": "Idle.af", "confident_idle_flavor02.af": "Idle_Flavor02.af",
                               "crosslegs_talk_l01.af": "Talk_L01.af",
                               "relaxed_idlepartialbody_flavor01_handsbehind.af": "Idle.af"})

    def test_swap_graph(self):
        t = ("<root><events><event><name>LoadFurnitureGraph</name><payload>AnimTextData\\Tables\\Graphs\\"
             "FurnitureRandomSitChair.agx</payload></event><event><name>CullBone</name><payload>C_BackPack</payload>"
             "</event></events></root>")
        got = P.swap_graph(t, P.GRAPH_SWAP["Sit"])
        self.assertIn("<payload>AnimTextData\\Tables\\Graphs\\FurnitureGenericSit.agx</payload>", got)
        self.assertIn("<payload>C_BackPack</payload>", got)
        self.assertEqual(P.swap_graph(got, P.GRAPH_SWAP["Sit"]), got)                   # already swapped
        self.assertEqual(P.swap_graph(t, {}), t)

    def test_swap_anim_objects(self):
        t = ("<root><events><event><name>AnimObjLoad</name><payload>AnimObjectBroom</payload></event>"
             "<event><name>AnimObjDraw</name><payload>animobjectbroom</payload></event>"
             "<event><name>SoundPlay</name><payload>AnimObjectBroom</payload></event></events></root>")
        got = P.swap_anim_objects(t, P.PROP_SWAP["Sweep"])
        self.assertEqual(got.count("S2S_AnimObjectBroomSkyrim"), 2)
        self.assertIn("<name>SoundPlay</name><payload>AnimObjectBroom</payload>", got)    # not an AnimObj event
        self.assertIn("--prop", P.hkx_args(type("A", (), {"calumi": "c", "skyrim_data": "s", "starfield": "f"})(),
                                           "w", "x", [], com=(0, 0), props=P.SET_PROPS["Sweep"]))

    def test_props_at_start(self):
        t = ("<root>\n<events>\n<event><frame>37</frame><name>AnimObjLoad</name><payload>B</payload></event>\n"
             "<event><frame>40</frame><name>AnimObjDraw</name><payload>B</payload></event>\n"
             "<event><frame>50</frame><name>FootLeft</name><payload></payload></event>\n</events>\n</root>")
        got = P.props_at_start(t)
        self.assertIn("<frame>0</frame><name>AnimObjLoad</name>", got)
        self.assertIn("<frame>0</frame><name>AnimObjDraw</name>", got)
        self.assertIn("<frame>50</frame><name>FootLeft</name>", got)
        self.assertEqual(P.props_at_start("<root><tag>Idle</tag></root>"), "<root><tag>Idle</tag></root>")

    def test_dense_keys(self):
        import numpy as np
        t = P.dense_keys([(0, (0, 0, 0)), (4, (4, 0, 0))], 6, False)
        np.testing.assert_allclose(t[:, 0], [0, 1, 2, 3, 4, 4])
        q = P.dense_keys([(0, (0, 0, 0, 1)), (2, (0, 0, 0, -1))], 3, True)        # same rotation, other sign
        np.testing.assert_allclose(np.abs(q[1]), [0, 0, 0, 1], atol=1e-9)

    def test_vanilla_leftovers_force(self):
        d = "meshes\\actors\\human\\animations\\furniture\\standing_sweep\\"
        files = {d + "exittostand.afx": b"<root><tag>ExitToStand</tag><filename>ExitToStand.af</filename></root>",
                 d + "exittostand.af": b"EXIT",
                 d + "lookdirections.afx": b"<root><tag>LookDirections</tag><filename>L.af</filename><flags>"
                                           b"<flag>Additive</flag></flags></root>"}
        self.assertEqual(P.vanilla_leftovers(sorted(files), files.get, [d], set()), {})
        got = P.vanilla_leftovers(sorted(files), files.get, [d], set(), force=True)
        self.assertEqual(sorted(got), ["exittostand.afx"])                     # additive ones stay Starfield's
        self.assertEqual(got["exittostand.afx"][1], ("ExitToStand.af", b"EXIT"))

    def test_pin_bone(self):
        import tempfile
        import numpy as np
        from unittest import mock
        from fo4sf import af_writer, rootmotion
        rig = {"names": ["Root", "R_Wrist", "R_AnimObject1", "C_Head"], "parents": [-1, 0, 1, 0],
               "t": [[0, 0, 0]] * 4, "q": [[0, 0, 0, 1]] * 4}
        rb = {"frames": 3, "bones": ["R_Wrist", "R_AnimObject1"],
              "translations": {"R_Wrist": [(0, (0, 0, 1)), (2, (0, 0, 3))], "R_AnimObject1": [(0, (0, -1.16, 0))]},
              "rotations": {"R_Wrist": [(0, (0, 0, 0, 1))], "R_AnimObject1": [(0, (0, 0, 0, 1))]}}
        seen = {}

        def fake_write(lib, out, name, names, parents, rt, rq, ct, cq, rig_path=None, omit=()):
            seen.update(ct=ct, cq=cq, omit=omit)
            p = os.path.join(out, name + ".af")
            with open(p, "wb") as fh:
                fh.write(b"NEW")
            return {"af": p}
        with tempfile.TemporaryDirectory() as d:
            af = os.path.join(d, "ExitToStand.af")
            with open(af, "wb") as fh:
                fh.write(b"OLD")
            with mock.patch.object(af_writer, "load_rig", lambda *a: rig), \
                    mock.patch.object(af_writer, "read_back", lambda *a: rb), \
                    mock.patch.object(af_writer, "write", fake_write), \
                    mock.patch.object(rootmotion, "read_header", lambda data: ((0, 0, 0, 1), (0.5, 0, 0))), \
                    mock.patch.object(rootmotion, "patch_header", lambda p, t, q: seen.update(head=(tuple(t), tuple(q)))):
                rep = P.pin_bone("calumi", "rig", af, "R_AnimObject1", (0.01, 0.02, -0.03), (0, 0, 0.6, 0.8),
                                 os.path.join(d, "work"))
            with open(af, "rb") as fh:
                self.assertEqual(fh.read(), b"NEW")
        self.assertEqual(rep, {"frames": 3, "bones": 2})
        np.testing.assert_allclose(seen["ct"][:, 2], [[0.01, 0.02, -0.03]] * 3)     # held in the hand
        np.testing.assert_allclose(seen["cq"][:, 2], [[0, 0, 0.6, 0.8]] * 3)
        np.testing.assert_allclose(seen["ct"][:, 1, 2], [1, 2, 3])                   # the rest as it was
        self.assertEqual(seen["omit"], ("Root", "C_Head"))                          # unkeyed bones stay unkeyed
        self.assertEqual(seen["head"], ((0.5, 0, 0), (0, 0, 0, 1)))                  # root motion kept

    def test_leftover_folders(self):
        f = P.leftover_folders("Sit")
        self.assertEqual([x.split("furniture\\")[-1] for x in f],
                         ["chair\\animflavor", "chair\\female\\animflavor", "chair", "chair\\female",
                          "bench\\animflavor", "bench\\female\\animflavor", "bench", "bench\\female", "common"])
        self.assertEqual(len(P.leftover_folders("RailLean")), 5)

    def test_copy_only_reuses_the_conversion(self):
        """--copy-only: no hkx_to_af call; the earlier conversion's files are copied again, cleaned, with talk slots."""
        import contextlib
        import io
        import json
        import tempfile
        from unittest import mock
        import hkx_to_af
        with tempfile.TemporaryDirectory() as d:
            folder = P.SETS["Sweep"][0]
            src = os.path.join(d, "work", "Sweep", "all", *folder.split("\\"))
            os.makedirs(src)
            with open(os.path.join(d, "work", "Sweep", "all", "report.json"), "w") as fh:
                json.dump([{"name": "animobjectsweepingidlebase"}], fh)
            with open(os.path.join(src, "Idle.af"), "wb") as fh:
                fh.write(b"AF")
            with open(os.path.join(src, "Idle.afx"), "w") as fh:
                fh.write("<root><tag>Idle</tag><filename>Idle.af</filename></root>")
            out = os.path.join(d, "out")
            args = ["--calumi", "c", "--skyrim-data", "s", "--starfield", "f", "--out", out, "--work",
                    os.path.join(d, "work"), "--set", "Sweep", "--copy-only"]
            with mock.patch.object(hkx_to_af, "main", side_effect=AssertionError("converted")), \
                    contextlib.redirect_stdout(io.StringIO()) as so:
                P.main(args)
            dst = os.path.join(out, *folder.split("\\"))
            self.assertTrue(os.path.exists(os.path.join(dst, "talk_s05.af")))
            with open(os.path.join(dst, "stale_variant.af"), "wb") as fh:          # from an earlier run
                fh.write(b"OLD")
            with mock.patch.object(hkx_to_af, "main", side_effect=AssertionError("converted")), \
                    contextlib.redirect_stdout(io.StringIO()):
                P.main(args)
            self.assertFalse(os.path.exists(os.path.join(dst, "stale_variant.af")))  # the folder starts empty
            self.assertTrue(os.path.exists(os.path.join(dst, "talk_s05.af")))
            with open(os.path.join(dst, "talk_s05.afx")) as fh:
                self.assertIn("<tag>Talk_S05</tag>", fh.read())
            self.assertIn("copied again (--copy-only)", so.getvalue())

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
            "r": {"kind": "lean_counter", "edid": "RailLeanMarker", "markers": [], "skyrim_markers": sky,
                  "shift_m": list(MF.DEFAULT_SHIFT["lean_counter"])},
            "w": {"kind": "lean_counter", "edid": "WallLeanMarker", "markers": [], "skyrim_markers": sky,
                  "shift_m": [0.0, -0.05, 0.0]},
            "s": {"kind": "sweep", "edid": "SweepIdleMarker", "markers": [],
                  "skyrim_markers": [dict(m) for m in MF.AT_THE_REFERENCE]},
            "a": {"kind": "alchemy", "edid": "CraftingAlchemyWorkbench", "markers": [], "skyrim_markers": sky}}}
        kws = {"S2S_AnimFurnSkyrimRailLean": 0x01000811, "S2S_AnimFurnSkyrimWallLean": 0x01000812,
               "S2S_AnimFurnSkyrimSweep": 0x01000815,
               "S2S_AnimFurnSkyrimAlchemy": 0x01000816}
        MF.add_anim_keywords(out, "S2SStances.esm", read_keywords=lambda p: kws)
        self.assertEqual(out["bases"]["r"]["markers"], sky)
        self.assertNotIn("shift_m", out["bases"]["r"])                   # the bar-lean default dropped
        self.assertEqual(out["bases"]["w"]["shift_m"], [0.0, -0.05, 0.0])   # one given on the command line stays
        self.assertEqual(out["bases"]["s"]["markers"], MF.AT_THE_REFERENCE)
        self.assertEqual(out["bases"]["a"]["markers"], [])
        # 2026-11-16: the forge's Skyrim sequence is laid out around Skyrim's forge marker: a crafting station, but
        # it takes Skyrim's spot when it plays the Forge set
        forge = {"bases": {"f": {"kind": "forge", "edid": "CraftingBlackSmithForge", "markers": [],
                                 "skyrim_markers": sky}}}
        MF.add_anim_keywords(forge, "S2SStances.esm", read_keywords=lambda p: {"S2S_AnimFurnSkyrimForge": 0x0100081B})
        # ... entered from the template's sides (2026-11-16 23:01, owner: walk-ins work with them, not with our 0xF)
        self.assertEqual((forge["bases"]["f"]["anim_set"], forge["bases"]["f"]["markers"]),
                         ("Forge", [dict(sky[0], entry=[])]))
        self.assertEqual(sky[0]["entry"], ["Front"])                                     # the shared list untouched
        tan = {"bases": {"t": {"kind": "scrape", "edid": "CraftingTanningRackMarker", "markers": [],
                               "skyrim_markers": [{"offset_m": [0, 0, 0], "rot_deg": 0.0, "entry": ["Rear"]}]}}}
        MF.add_anim_keywords(tan, "S2SStances.esm", read_keywords=lambda p: {"S2S_AnimFurnSkyrimTanning": 0x01000819})
        self.assertEqual(tan["bases"]["t"]["markers"][0]["entry"], [])
        # FurnitureSpecial on both (2026-11-16: the sandbox's "Allow Special Furniture", like Starfield's bartender)
        # ... and no IgnoreCollisionAtRefForInteractionsKeyword (2026-11-16 23:01: walk-ins work without it)
        both = ["FurnitureSpecial"]
        self.assertEqual(tan["bases"]["t"]["extra_keywords"], both)
        self.assertEqual(forge["bases"]["f"]["extra_keywords"], both)
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


class WorkbenchSetTest(unittest.TestCase):
    def test_workbench(self):
        """2026-11-16 (workbench_probe): the armor workbench hammers as Skyrim's HammerTable: Enter, Loop as the idle,
        the 9 s rest as the flavors, Exit; its own template (wipe table) and keyword; the table hammer as its prop."""
        folder, tpl, rows = P.SETS["Workbench"]
        self.assertTrue(tpl.endswith("wipetable"))
        d = dict((r[0], r[1]) for r in rows)
        self.assertEqual((d["enterfromstand.afx"], d["idle.afx"], d["idle_flavor03.afx"], d["exittostand.afx"],
                          d["enterinstant.afx"]),
                         ("aohammerenter.hkx", "aohammerloop.hkx", "aohammeridle.hkx", "aohammerexit.hkx",
                          "aohammerloop.hkx"))
        self.assertEqual(P.SET_PROP_OBJECTS["Workbench"], ("S2S_AnimObjectHammerTableSkyrim",))
        import stance_plugin as SP
        import anim_object_convert as AC
        self.assertIn("S2S_AnimObjectHammerTableSkyrim", [p[0] for p in SP.PROP_OBJECTS])
        self.assertEqual(SP.PROP_OBJECTS[-1][0], "S2S_AnimObjectHammerTableSkyrim")       # appended: FormIDs keep
        self.assertIn("S2S_AnimObjectHammerTableSkyrim", AC.PROP_SOURCES)
        w = [v for n, v, _f in SP.FURNITURE_SETS if n == "Workbench"][0]
        self.assertEqual(w, ("AnimFurnWipeTable",))
        self.assertFalse(any(set(w) & set(v) for n, v, _f in SP.FURNITURE_SETS if n != "Workbench"))
        import make_furniture as MF
        self.assertEqual(MF.anim_set_for({"kind": "smith_table", "edid": "CraftingBlacksmithArmorWorkbench"}),
                         "Workbench")


class ClipEventsTest(unittest.TestCase):
    def test_forge_iron_events(self):
        """2026-11-16 (clip_join): the Discard + Pull flavor blends its join and swaps the iron: unequipped where the
        Pull part starts, a new one drawn 2 s into it (Skyrim's AnimObjDraw time)."""
        self.assertGreater(P.JOIN_BLEND["Forge"], 0)
        rows = [{"clip": P.SKY_ANIM + "blacksmithforgediscard.hkx+blacksmithforgepull.hkx", "part_starts": [0, 177],
                 "template": "meshes/actors/human/animations/furniture/standing_wipewall/Idle_Flavor02.af"},
                {"clip": P.SKY_ANIM + "blacksmithforgetemper.hkx",
                 "template": "meshes/actors/human/animations/furniture/standing_wipewall/Idle_Flavor01.af"}]
        ev = P.clip_event_rows(rows, P.CLIP_EVENTS["Forge"])
        iron = "S2S_AnimObjectForgeIronSkyrim"
        self.assertEqual(ev, {"idle_flavor02": [(177, "AnimObjUnequip", iron), (237, "AnimObjLoad", iron),
                                                (237, "AnimObjDraw", iron)]})
        afx = "<animation><tag>Idle_Flavor02</tag><events>\r\n</events></animation>"
        out = P.add_clip_events(afx, ev["idle_flavor02"])
        self.assertLess(out.index("AnimObjUnequip"), out.index("AnimObjLoad"))
        self.assertLess(out.index("AnimObjLoad"), out.index("AnimObjDraw"))
        self.assertIn("--join-blend", P.hkx_args(type("A", (), {"calumi": "c", "skyrim_data": "s", "starfield": "f"}),
                                                 "w", "x", [], blend=0.8))


class VanillaEnterTest(unittest.TestCase):
    def test_without_enter(self):
        """--vanilla-enter (2026-11-16 A/B): the forge's walk-in left to the welder's own; the rest kept."""
        f, t, rows = P.without_enter(P.SETS["Forge"])
        names = [r[0] for r in rows]
        self.assertNotIn("enterfromstand.afx", names)
        self.assertIn("enterinstant.afx", names)
        self.assertEqual(len(rows), len(P.SETS["Forge"][2]) - 1)
        self.assertEqual(("enterfromstand", False), ("enterfromstand", not any(w in "enterfromstand" for w in P.NOT_IDLE)))


class FreshDirTest(unittest.TestCase):
    def test_fresh_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            old = os.path.join(d, "all", "x", "Idle_Flavor06.af")
            os.makedirs(os.path.dirname(old))
            open(old, "w").close()
            P.fresh_dir(os.path.join(d, "all"))
            self.assertEqual(os.listdir(os.path.join(d, "all")), [])


class PlainStationsTest(unittest.TestCase):
    """--plain-stations (A/B, 2026-11-16): stations without the extra keywords and with the template's entry sides."""

    def test_plain(self):
        import make_furniture as MF
        sky = [{"offset_m": [0, 0, 0], "rot_deg": 0.0, "entry": ["Rear"]}]
        kws = {"S2S_AnimFurnSkyrimForge": 0x0100081A}
        normal = {"bases": {"f": {"kind": "forge", "edid": "CraftingBlackSmithForge", "markers": [],
                                  "skyrim_markers": [dict(m) for m in sky]}}}
        plain = {"bases": {"f": {"kind": "forge", "edid": "CraftingBlackSmithForge", "markers": [],
                                 "skyrim_markers": [dict(m) for m in sky]}}}
        MF.add_anim_keywords(normal, "S2SStances.esm", read_keywords=lambda p: kws)
        MF.add_anim_keywords(plain, "S2SStances.esm", read_keywords=lambda p: kws, plain=True)
        self.assertEqual(normal["bases"]["f"]["extra_keywords"], MF.SPECIAL_KEYWORDS)
        self.assertNotIn("extra_keywords", plain["bases"]["f"])
        self.assertEqual(plain["bases"]["f"]["markers"][0]["entry"], [])     # PluginSpike: the template's sides
        self.assertEqual(plain["bases"]["f"]["anim_set"], "Forge")
        kept = {"bases": {"f": {"kind": "forge", "edid": "CraftingBlackSmithForge", "markers": [],
                                "skyrim_markers": [dict(m) for m in sky]}}}
        MF.add_anim_keywords(kept, "S2SStances.esm", read_keywords=lambda p: kws, plain=True,
                             keep_keywords=["FurnitureSpecial"])
        self.assertEqual(kept["bases"]["f"]["extra_keywords"], ["FurnitureSpecial"])
        self.assertEqual(kept["bases"]["f"]["markers"][0]["entry"], [])
        # Ignored By Sandbox cleared on every station (the grindstone's template carries it)
        self.assertTrue(normal["bases"]["f"]["sandbox_usable"])
        with open(os.path.join(ROOT, "dotnet", "PluginSpike", "Program.cs"), encoding="utf-8") as fh:
            cs = fh.read()
        self.assertIn('b.TryGetProperty("sandbox_usable"', cs)
        self.assertIn("fv & ~2L", cs)
        self.assertIn("mv & ~0x00800000L", cs)                 # MNAM "Enter With Weapon Drawn" (the wrench template)


class ObjectSoundTests(unittest.TestCase):
    def test_object_sounds_added_once(self):
        table = {"spin.hkx": [(0.0, False, "WheelLP")]}
        got = P.with_object_sounds({"spin.hkx": [(1.0, False, "Other")], "x.hkx": [(0.5, False, "X")]},
                                    ["Spin.hkx", "x.hkx"], table)
        self.assertEqual(got["spin.hkx"], [(0.0, False, "WheelLP"), (1.0, False, "Other")])
        self.assertEqual(got["x.hkx"], [(0.5, False, "X")])
        again = P.with_object_sounds(got, ["spin.hkx"], table)
        self.assertEqual(again["spin.hkx"], got["spin.hkx"])
        self.assertNotIn("spin.hkx", P.with_object_sounds({}, ["other.hkx"], table))

    def test_grindstone_spin_gets_the_wheel_sounds(self):
        got = P.with_object_sounds({}, ["blacksmithsharpeningwheelspin.hkx"])
        self.assertEqual({r[2] for r in got["blacksmithsharpeningwheelspin.hkx"]},
                         {"NPCHumanBladeGrindLPM", "NPCHumanBladeGrindPedalLP"})
        rows = P.sound_event_rows([{"template": "idle.afx", "clip": "x\\blacksmithsharpeningwheelspin.hkx",
                                     "frames": 275}], got)
        self.assertEqual(sorted(n for _f, _e, n in rows["idle"]),
                         ["NPCHumanBladeGrindLPM", "NPCHumanBladeGrindPedalLP"])
        self.assertTrue(all(f == 0 for f, _e, _n in rows["idle"]))


if __name__ == "__main__":
    unittest.main()


class SoundTriggerTests(unittest.TestCase):
    """2026-11-20: Skyrim's forge sounds are clip triggers in its behaviour graph; they become SoundPlay events at
    the clip's frames (a joined clip's parts offset by part_starts; relative-to-end triggers counted from the end)."""

    def test_trigger_sounds(self):
        b = {"events": ["SoundPlay", "AnimObjDraw", "SoundPlay.NPCHumanBlacksmithForgeTake"], "nodes": {
            1: {"class": "hkbClipGenerator", "animation": "Furniture\\BlacksmithForgeHammer.hkx", "triggers": 2},
            2: {"class": "hkbClipTriggerArray", "triggers": [
                {"time": 0.5, "event": 0, "payload": 3}, {"time": 0.2, "event": 1, "payload": 4},
                {"time": -0.1, "event": 2, "payload": None, "relative_to_end": True}]},
            3: {"class": "hkbStringEventPayload", "data": "NPCHumanBlacksmithHammer"},
            4: {"class": "hkbStringEventPayload", "data": "AnimObjectIron"}}}
        self.assertEqual(P.trigger_sounds(b), {"blacksmithforgehammer.hkx": [
            (-0.1, True, "NPCHumanBlacksmithForgeTake"), (0.5, False, "NPCHumanBlacksmithHammer")]})

    def test_sound_event_rows(self):
        sounds = {"a.hkx": [(1.0, False, "S1")], "b.hkx": [(0.5, False, "S2"), (0.0, True, "S3")]}
        rows = [{"clip": "C:\\x\\a.hkx+b.hkx", "template": "f/welder/Idle_Flavor02.af", "part_starts": [0, 100],
                 "concatenated_frames": [120, 60]},
                {"clip": "C:\\x\\b.hkx", "template": "f/welder/Idle.af", "frames": 60},
                {"clip": "C:\\x\\c.hkx", "template": "f/welder/Exit.af", "frames": 10}]
        got = P.sound_event_rows(rows, sounds)
        self.assertEqual(got["idle_flavor02"], [(30, "SoundPlay", "S1"), (115, "SoundPlay", "S2"),
                                                (159, "SoundPlay", "S3")])
        self.assertEqual(got["idle"], [(15, "SoundPlay", "S2"), (59, "SoundPlay", "S3")])
        self.assertNotIn("exit", got)

    def test_add_sound_audios(self):
        welder = ("<root><tag>EnterFromStand</tag><events><event><frame>0</frame><name>AnimObjLoad</name><payload>x"
                  "</payload></event></events><audios><audio><frame>139</frame><foley>ITM_Microscope_Up</foley></audio>"
                  "</audios></root>")
        out = P.add_sound_audios(welder, [(315, "SoundPlay", "NPCHumanBlacksmithForgeTake"),
                                          (51, "SoundPlay", "OBJBlacksmithForge")])
        self.assertNotIn("ITM_Microscope_Up", out)
        self.assertLess(out.index("OBJBlacksmithForge"), out.index("NPCHumanBlacksmithForgeTake"))
        self.assertIn("<foley>NPCHumanBlacksmithForgeTake</foley>", out)
        self.assertIn("<name>AnimObjLoad</name>", out)
        self.assertNotIn("<audio>", P.add_sound_audios(welder, []))           # a set with sounds: no welder foley

    def test_talk_copies_without_sounds(self):
        idle = ("<root><tag>Idle</tag><filename>Idle.af</filename><audios><audio><frame>7</frame><foley>X</foley>"
                "</audio></audios><variables><variable><name>v</name></variable></variables></root>")
        out = P.talk_copies(idle, ("Talk_L01",))["talk_l01.afx"]
        self.assertNotIn("<audio", out)
        self.assertIn("<tag>Talk_L01</tag>", out)
        self.assertIn("<variables>", out)
