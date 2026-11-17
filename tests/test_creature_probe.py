"""scripts/armor/creature_probe.py helpers on synthetic data: path subrecords, race rows, NPC_ race counts, Skyrim
project-relative path resolution, and the character file's rig / behaviour / clip split."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import creature_probe as C  # noqa: E402


class CreatureProbeTests(unittest.TestCase):
    def test_path_subs_and_race_row(self):
        subs = [(b"EDID", b"ChickenRace\0"), (b"ANAM", b"Actors\\Chicken\\Character Assets\\skeleton.nif\0"),
                (b"DATA", struct.pack("<4f", 1, 2, 3, 4)), (b"MODL", b"Actors\\Chicken\\ChickenProject.hkx\0"),
                (b"FULL", b"Chicken\0"), (b"MTNM", b"WALK"), (b"MTNM", b"RUN1")]
        self.assertEqual(C.path_subs(subs), [("ANAM", "Actors\\Chicken\\Character Assets\\skeleton.nif"),
                                             ("MODL", "Actors\\Chicken\\ChickenProject.hkx")])
        r = C.race_row(subs, 0xA919D)
        self.assertEqual((r["form"], r["edid"], r["counts"]["MTNM"]), ("000A919D", "ChickenRace", 2))

    def test_npc_race_counts(self):
        recs = [(b"NPC_", b"", [(b"RNAM", struct.pack("<I", 7))], 1), (b"NPC_", b"", [(b"RNAM", struct.pack("<I", 7))], 2),
                (b"NPC_", b"", [(b"EDID", b"x\0")], 3)]
        self.assertEqual(C.npc_race_counts(recs), {7: 2})

    def test_resolve_and_character_refs(self):
        self.assertEqual(C.resolve("meshes\\actors\\chicken\\chickenproject.hkx", "Characters\\ChickenCharacter.hkx"),
                         "meshes\\actors\\chicken\\characters\\chickencharacter.hkx")
        refs = C.character_refs(["Character Assets\\skeleton.HKX", "Behaviors\\ChickenBehavior.hkx",
                                 "Animations\\Idle.hkx", "Animations\\WalkForward.hkx", "ChickenCharacter"])
        self.assertEqual(refs, {"rig": ["Character Assets\\skeleton.HKX"], "behaviors": ["Behaviors\\ChickenBehavior.hkx"],
                                "animations": ["Animations\\Idle.hkx", "Animations\\WalkForward.hkx"]})

    def test_starfield_listing(self):
        import tempfile
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_fo4land import grup, rec
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
            race = rec(b"RACE", 0x100, [(b"EDID", b"AshtaRace\0"), (b"ANAM", b"Actors\\Ashta\\skeleton.nif\0"),
                                        (b"NAM5", b"Actors\\Ashta\\CharacterAssets\\skeleton.rig\0"),
                                        (b"NAM6", b"AnimTextData\\Tables\\Graphs\\Ashta_Root.agx\0")])
            npc = rec(b"NPC_", 0x200, [(b"EDID", b"Ashta01\0"), (b"RNAM", struct.pack("<I", 0x100))])
            with open(os.path.join(d, "Starfield.esm"), "wb") as fh:
                fh.write(tes4 + grup(b"RACE", 0, [race]) + grup(b"NPC_", 0, [npc]))
            lines = C.starfield_side(d, [])
        row = next(ln for ln in lines if "AshtaRace" in ln)
        self.assertIn("(1 NPC_)", row)
        self.assertIn("NAM5 Actors\\Ashta\\CharacterAssets\\skeleton.rig", row)
        self.assertIn("NAM6 AnimTextData\\Tables\\Graphs\\Ashta_Root.agx", row)

    def test_graph_path(self):
        self.assertEqual(C.graph_path("AnimTextData\\Tables\\Graphs\\Critter_Root.agx"),
                         "meshes/animtextdata/tables/graphs/critter_root.agx")
        self.assertEqual(C.graph_path("Data\\Meshes\\AnimTextData\\Tables\\Graphs\\X.agx"),
                         "meshes/animtextdata/tables/graphs/x.agx")
        self.assertEqual(C.graph_path("Locomotion"), "meshes/animtextdata/tables/graphs/locomotion.agx")

    def test_contract_follows_graph_refs_and_finds_missing_tags(self):
        def sheet(rows):
            return "<property_sheet>" + "".join(f"<row><prop><value>{k}</value></prop><prop><value>{v}</value></prop></row>"
                                                for k, v in rows) + "</property_sheet>"

        def graph(*nodes):
            return ("<root><Name>x</Name>" + "".join(f"<node><node_type>{ty}</node_type>{sheet(p)}</node>"
                                                    for ty, p in nodes) + "</root>").encode()

        def afx(tag, fn, state="0"):
            return f"<root><is_state>{state}</is_state><tag>{tag}</tag><filename>{fn}</filename></root>".encode()
        G = "meshes/animtextdata/tables/graphs/"
        files = {G + "critter_root.agx": graph(("NT_GRAPH_REF", [("Graph Ref", "Locomotion")])),
                 G + "locomotion.agx": graph(("NT_ANIMATION_NODE", [("TagName", "Idle")]),
                                             ("NT_ANIMATION_NODE", [("TagName", "WalkForward")])),
                 "meshes/actors/critter/animations/idle.afx": afx("Idle", "Idle.af", "1"),
                 "meshes/actors/critter/animations/idle.af": b"",
                 "meshes/actors/critterb/animations/walkforward.afx": afx("WalkForward", "W.af")}
        race = {"paths": [("NAM6", "AnimTextData\\Tables\\Graphs\\Critter_Root.agx"),
                          ("DNAM", "Actors\\Critter\\Animations"), ("DNAM", "Actors\\Critter\\Animations")]}
        lines = C.contract_lines(race, files.get, list(files))
        text = "\n".join(lines)
        self.assertIn("refs ['Locomotion']", text)
        self.assertIn("tags (2): Idle, WalkForward", text)
        self.assertIn("folder Actors\\Critter\\Animations: 1 .afx, 1 .af", text)   # listed once; critterb not under it
        self.assertIn("idle.afx: tag Idle (state) -> Idle.af", text)
        self.assertTrue(lines[-1].endswith("(1): WalkForward"), lines[-1])

    def test_nested_tags_and_rig_names(self):
        nested = (b"<root><Name>x</Name><node><node_type>NT_STATE_MACHINE_EMBEDDED</node_type><graph>"
                  b"<node><node_type>NT_ANIMATION_NODE</node_type><property_sheet><row><prop><value>TagName</value></prop>"
                  b"<prop><value>WalkForward</value></prop></row></property_sheet></node>"
                  b"<node><node_type>NT_GRAPH_REF</node_type><property_sheet><row><prop><value>Graph Ref</value></prop>"
                  b"<prop><value>LookAt</value></prop></row></property_sheet></node></graph></node></root>")
        self.assertEqual(C.deep_tags_refs(nested), (["WalkForward"], ["LookAt"]))
        rig = b"\x01\x02?>\x00" + b"\x9a\x99\x19\x3f" * 24 + b"\0Root\0Pelvis\0Head [Head]\0"
        self.assertEqual(C.rig_names(rig), ["Root", "Pelvis", "Head [Head]"])

    def test_character_refs_dedupes(self):
        refs = C.character_refs(["Character Assets\\skeleton.HKX", "Character Assets\\skeleton.HKX"])
        self.assertEqual(refs["rig"], ["Character Assets\\skeleton.HKX"])

    def test_nif_and_skin_summaries(self):
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import test_skyrim_armor as A
        data = A.skinned_nif_bytes()
        summ = C.nif_summary(data)
        self.assertIn("NiNode 4", summ[0])
        self.assertIn("NPC Spine2 [Spn2]", summ[1])
        skin = C.skin_summary(data)
        self.assertEqual(len(skin), 1)
        self.assertIn("6 verts, 2 tris, 3 bones, unweighted 0", skin[0])
        from fo4sf import nif, sfnif
        sf = sfnif.build_skinned_nif(b"Chicken", [sfnif.SkinnedShape(
            b"Body", b"a\\b", 3, 3, "materials\\x.mat", [b"Pelvis"], [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)])])
        ss = C.nif_summary(nif.serialize(sf))
        self.assertIn("nodes (1): Chicken", ss[1])
        self.assertIn("SkinAttach 'SkinBMP'", ss[2])
        st = sfnif.build_static_nif(b"Skel", [sfnif.StaticShape(b"S", b"a\\b", 3, 3, "materials\\x.mat",
                                                                (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))],
                                    child_collision_blobs=[b"hkRootLevelContainer\0Ragdoll_COM\0"])
        tree = [ln for ln in C.nif_summary(nif.serialize(st)) if ln.startswith("node ")]
        coll = next(ln for ln in tree if "Collision0" in ln)
        self.assertIn("<Skel>", coll)
        self.assertIn("bhkNPCollisionObject -> bhkPhysicsSystem", coll)
        self.assertIn("Ragdoll_COM", coll)

    def test_skin_chain(self):
        armo = {0x10: [(b"EDID", b"SkinCritter\0"), (b"MODL", struct.pack("<I", 0x20)), (b"DATA", b"\0" * 8)]}
        arma = {0x20: [(b"EDID", b"CritterAA\0"), (b"MOD2", b"Actors\\Critter\\Critter.nif\0")]}
        race = [(b"EDID", b"CritterRace\0"), (b"WNAM", struct.pack("<I", 0x10)), (b"RNAM", struct.pack("<I", 0x99))]
        chain = C.skin_chain(race, armo, arma)
        self.assertEqual(chain, [("WNAM", "SkinCritter", [("CritterAA", [("MOD2", "Actors\\Critter\\Critter.nif")])])])
        self.assertIn("ARMA CritterAA [MOD2 Actors\\Critter\\Critter.nif]", C.skin_lines("race skin", chain)[0])

    def test_model_detail_on_disk(self):
        import tempfile
        from fo4sf import creature, gearfit, nif
        import numpy as np
        sh = gearfit.SkyShape(b"chicken", np.array([[0, 0, 0.1], [0.1, 0, 0.1], [0, 0.1, 0.3]], float),
                              np.array([[0, 0, 1]] * 3, float), [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)],
                              ["Pelvis"], [[(0, 1.0)]] * 3, {"Pelvis": np.eye(4)})
        from fo4sf import retarget
        cr = creature.creature_rig(retarget.Rig(["NPC Root [Root]", "Pelvis"], [-1, 0], [(0, 0, 0), (0, 0, 7)],
                                                [(0, 0, 0, 1)] * 2))
        files = creature.skinned_files(sh, "materials\\t.mat", "actors/critter/mesh/t/t", "Pelvis", cr)
        with tempfile.TemporaryDirectory() as d:
            for rel, data in files.items():
                p = os.path.join(d, "Mod", *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "wb").write(data)
            lines = C.models_side(None, [os.path.join(d, "Mod", "meshes", "actors", "critter", "mesh", "t", "t.nif")])
            os.remove(next(os.path.join(dp, f) for dp, _d, fs in os.walk(os.path.join(d, "Mod", "geometries"))
                           for f in fs))
            gone = C.models_side(None, [os.path.join(d, "Mod", "meshes", "actors", "critter", "mesh", "t", "t.nif")])
        text = "\n".join(lines)
        self.assertIn("BSGeometry 'chicken'", text)
        self.assertIn("weights/vertex 4, bone indices used [0]", text)
        self.assertIn("skin instance bone refs -> COM_Twin", text)
        self.assertIn("node 'COM_Twin' <ExportScene>", text)
        self.assertIn("MESH NOT FOUND", "\n".join(gone))

    def test_clip_headers(self):
        from fo4sf import rootmotion
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            af = os.path.join(d, "w.af")
            open(af, "wb").write(bytes(64))
            rootmotion.patch_header(af, (0, 0.5, 0), (0, 0, 0, 1))
            data = open(af, "rb").read()
        files = {"meshes/actors/critter/animations/walkforward.af": data,
                 "meshes/actors/critter/animations/furniture/idle.af": bytes(64)}
        lines = C.clip_headers(list(files), files.get, "Actors\\Critter\\Animations")
        self.assertEqual(len(lines), 2)
        self.assertIn("walkforward.af: header t (+0.000, +0.500, +0.000) m, yaw +0.0 deg", lines[1])

    def test_rig_dump(self):
        names = [b"COM", b"Spine"]
        recs = b"".join(struct.pack("<4f3fi", 0, 0, 0, 1, 0, 0, 0.1 * i, i - 1) + bytes(96 - 32) for i in range(2))
        data = b"HDR!" + recs + b"\0".join(names) + b"\0"
        lines = C.rig_dump(data)
        self.assertIn("2 bone names, name table 10 bytes, record area from 4", lines[0])
        self.assertEqual(lines[1], "header: 48445221")
        self.assertIn("[ 1] Spine", lines[5])
        self.assertIn("+0.100", lines[7])


if __name__ == "__main__":
    unittest.main()
