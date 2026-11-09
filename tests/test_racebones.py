"""fo4sf.racebones and scripts/npc/skeleton_probe.py: Skyrim CME helper values (Racial Body Morphs style) read from a
synthetic skeleton, mapped onto a synthetic Starfield skeleton, inserted as helper nodes; the probe's report and test
pack (no game data)."""
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
from fo4sf import nif, racebones as RB, sfplugin  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
import skeleton_probe as P  # noqa: E402


def skyrim_skeleton(scale=1.1, offset=(0.0, 0.0, 2.0), head_scale=0.9):
    """NPC Root > NPC COM > CME UBody > CME UBody (scaled, moved) > NPC Spine > NPC Neck > CME Neck > CME Neck (head
    scale) > NPC Head; NPC COM > NPC Pelvis (no helpers)."""
    n = F.SseNif()
    ids = {k: n.reserve("NiNode") for k in ("root", "com", "cme_u", "cme_u2", "spine", "neck", "cme_n", "cme_n2",
                                            "head", "pelvis")}
    n.node(ids["root"], b"NPC Root [Root]", [ids["com"]])
    n.node(ids["com"], b"NPC COM [COM ]", [ids["cme_u"], ids["pelvis"]], t=(0, 0, 70))
    n.node(ids["cme_u"], b"CME UBody [UBody]", [ids["cme_u2"]])
    n.node(ids["cme_u2"], b"CME UBody [UBody]", [ids["spine"]], t=offset, s=scale)
    n.node(ids["spine"], b"NPC Spine [Spn0]", [ids["neck"]], t=(0, 0, 5))
    n.node(ids["neck"], b"NPC Neck [Neck]", [ids["cme_n"]], t=(0, 0, 40))
    n.node(ids["cme_n"], b"CME Neck [Neck]", [ids["cme_n2"]])
    n.node(ids["cme_n2"], b"CME Neck [Neck]", [ids["head"]], s=head_scale)
    n.node(ids["head"], b"NPC Head [Head]", [], t=(0, 0, 8))
    n.node(ids["pelvis"], b"NPC Pelvis [Pelv]", [])
    return n.bytes()


def starfield_skeleton():
    n = F.SseNif()
    ids = {k: n.reserve("NiNode") for k in ("root", "com", "spine", "neck", "neck1", "head", "hips", "deltoid")}
    n.node(ids["root"], b"Root", [ids["com"]])
    n.node(ids["com"], b"COM", [ids["spine"], ids["hips"]], t=(0, 0, 1.0))
    n.node(ids["spine"], b"C_Spine", [ids["neck"]], t=(0, 0, 0.07))
    n.node(ids["neck"], b"C_Neck", [ids["neck1"]], t=(0, 0, 0.55))
    n.node(ids["neck1"], b"C_Neck1", [ids["head"]], t=(0, 0, 0.05))
    n.node(ids["head"], b"C_Head", [], t=(0, 0, 0.06))
    n.node(ids["hips"], b"C_Hips", [ids["deltoid"]])
    n.node(ids["deltoid"], b"L_Deltoid", [])
    return n.bytes()


class RaceBonesTests(unittest.TestCase):
    def test_cme_values_compose_the_helper_chain(self):
        rows = {r["child"]: r for r in RB.cme_values(skyrim_skeleton())}
        self.assertEqual(sorted(rows), ["NPC Head [Head]", "NPC Spine [Spn0]"])     # Pelvis: no helpers
        sp = rows["NPC Spine [Spn0]"]
        self.assertEqual((sp["parent"], sp["scale"], sp["offset_units"]), ("NPC COM [COM ]", 1.1, [0.0, 0.0, 2.0]))
        self.assertEqual(sp["nodes"], ["CME UBody [UBody]", "CME UBody [UBody]"])
        self.assertEqual(rows["NPC Head [Head]"]["parent"], "NPC Neck [Neck]")
        self.assertEqual(RB.cme_values(skyrim_skeleton(1.0, (0, 0, 0), 1.0)), [])       # identity helpers: nothing

    def test_mapped_onto_starfield_bones(self):
        sky, sf = skyrim_skeleton(), starfield_skeleton()
        helpers, notes = RB.to_starfield(RB.cme_values(sky), RB.world_rotations(sky), RB.world_rotations(sf),
                                         RB.nif_parents(sf))
        by = {h["bone"]: h for h in helpers}
        self.assertEqual(by["C_Spine"]["nif_parent"], "COM")
        self.assertEqual(by["C_Spine"]["scale"], 1.1)
        self.assertEqual(by["C_Spine"]["offset_m"], [0.0, 0.0, round(2 / 70, 4)])     # units -> metres
        self.assertEqual((by["C_Head"]["nif_parent"], by["C_Head"]["scale"]), ("C_Neck1", 0.9))
        self.assertTrue(any("helper above C_Head" in n for n in notes))   # Skyrim Neck -> C_Neck, its child C_Neck1

    def test_offsets_follow_the_parent_frames(self):
        """A Skyrim parent turned 90 deg about Z: its local +X offset is world +Y, which in an unturned Starfield
        parent's frame is +Y."""
        n = F.SseNif()
        a, b, c = n.reserve("NiNode"), n.reserve("NiNode"), n.reserve("NiNode")
        d = n.reserve("NiNode")
        n.node(a, b"NPC COM [COM ]", [b], r=(0, -1, 0, 1, 0, 0, 0, 0, 1))
        n.node(b, b"CME X", [c])
        n.node(c, b"CME X", [d], t=(7.0, 0, 0))
        n.node(d, b"NPC Spine [Spn0]", [])
        sky, sf = n.bytes(), starfield_skeleton()
        helpers, _n = RB.to_starfield(RB.cme_values(sky), RB.world_rotations(sky), RB.world_rotations(sf),
                                      RB.nif_parents(sf))
        self.assertEqual(helpers[0]["offset_m"], [0.0, 0.1, 0.0])

    def test_insert_helpers(self):
        sf = starfield_skeleton()
        out = RB.insert_helpers(sf, [{"bone": "C_Spine", "scale": 1.1, "offset_m": [0, 0, 0.02]}])
        par = RB.nif_parents(out)
        self.assertEqual((par["C_Spine"], par["S2S_RB_C_Spine"]), ("S2S_RB_C_Spine", "COM"))
        self.assertEqual(par["C_Hips"], "COM")                                    # siblings untouched
        f = nif.parse(out)
        names = RB._names(f)
        h = next(i for i, n_ in names.items() if n_ == "S2S_RB_C_Spine")
        t, r, s = nif._av_transform(f.blocks[h])
        self.assertAlmostEqual(s, 1.1, places=6)
        self.assertAlmostEqual(t[2], 0.02, places=6)
        sp = next(i for i, n_ in names.items() if n_ == "C_Spine")
        self.assertAlmostEqual(nif._av_transform(f.blocks[sp])[0][2], 0.07, places=6)   # the bone's own local kept
        w = nif.world_transforms(f)
        neck = next(i for i, n_ in names.items() if n_ == "C_Neck")
        self.assertAlmostEqual(w(neck)[0][2], 1.0 + 0.02 + 1.1 * (0.07 + 0.55), places=5)   # scaled below the helper
        with self.assertRaises(ValueError):
            RB.insert_helpers(sf, [{"bone": "Nope", "scale": 1.0}])


def race_plugin(path, anams):
    hdr = struct.pack("<4sIII", b"RACE", 0, 0, 0) + bytes(8)
    recs = [(b"RACE", hdr, [(b"EDID", sfplugin.zs(e))] + [(b"ANAM", sfplugin.zs(a)) for a in an], 0x13740 + k)
            for k, (e, an) in enumerate(anams)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 1.71, "form_version": 44}, masters=("Skyrim.esm",)))


class ProbeTests(unittest.TestCase):
    def test_classify_marks_helpers_and_leaves(self):
        sf = starfield_skeleton()
        info = P.classify(sf, ["Root", "COM", "C_Spine", "C_Neck", "C_Neck1", "C_Head", "C_Hips", "C_Neck_Twist"],
                          ["Default"] * 7 + ["Twist"])
        self.assertEqual((info["animated"], info["twist"]), (7, 1))
        self.assertEqual(info["not_in_rig"], {"between": [], "leaves": ["L_Deltoid"]})
        self.assertIn("note", P.classify(sf))

    def test_probe_and_test_pack(self):
        with tempfile.TemporaryDirectory() as d:
            mod = os.path.join(d, "mod")
            folder = os.path.join(mod, "Meshes", "Actors", "Character", "Character Assets", "Body by Race")
            os.makedirs(folder)
            for name, sc in (("skeletonOrc.nif", 1.1), ("skeletonNord.nif", 1.02)):
                with open(os.path.join(folder, name), "wb") as fh:
                    fh.write(skyrim_skeleton(sc))
            race_plugin(os.path.join(mod, "Racial Body Morphs.esp"),
                        [("OrcRace", ["Actors\\Character\\Character Assets\\Body by Race\\skeletonOrc.nif"]),
                         ("NordRace", ["Actors\\Character\\Character Assets\\Body by Race\\skeletonNord.nif"]),
                         ("OrcRaceVampire", ["Actors\\Character\\Character Assets\\Body by Race\\skeletonOrc.nif"])])
            self.assertEqual(sorted(P.race_skeletons(mod)), ["NordRace", "OrcRace", "OrcRaceVampire"])
            sfp = os.path.join(d, "skeleton.nif")
            with open(sfp, "wb") as fh:
                fh.write(starfield_skeleton())
            out = os.path.join(d, "out")
            with mock.patch("builtins.print"):
                rc = P.main(["--skeleton", f"male={sfp}", "--race-mod", mod, "--out", out, "--test-pack", "Orc"])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "skeleton_probe.json"), encoding="utf-8") as fh:
                rep = json.load(fh)
            with open(os.path.join(out, "skeleton_probe.md"), encoding="utf-8") as fh:
                md = fh.read()
            orc = {h["bone"]: h for h in rep["races"]["OrcRace"]["male"]["helpers"]}
            self.assertEqual(orc["C_Spine"]["scale"], 1.1)
            self.assertIn("Orc male (skeletonOrc.nif): C_Spine x1.1", md)
            self.assertIn("OrcRaceVampire male: same skeleton as above", md)       # variants after the playable races
            pack = os.path.join(out, "S2S Skeleton Test", *P.SF_SKELETON["male"].split("/"))
            with open(pack, "rb") as fh:
                par = RB.nif_parents(fh.read())
            self.assertEqual(par["C_Spine"], "S2S_RB_C_Spine")
            self.assertEqual(rep["test_pack"]["race"], "OrcRace")


if __name__ == "__main__":
    unittest.main()
