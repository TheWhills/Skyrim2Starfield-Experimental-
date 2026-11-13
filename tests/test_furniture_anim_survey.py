import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import furniture_anim_survey as S  # noqa: E402


def zs(s):
    return s.encode() + b"\0"


class SurveyTests(unittest.TestCase):
    def test_matching_rows_most_specific_first(self):
        rows = [{"role": "Furniture", "perspective": "3rd", "actor": [], "target": ["AnimFurnChair"], "graph": "g1",
                 "paths": ["furniture\\chair"]},
                {"role": "Furniture", "perspective": "3rd", "actor": ["AnimArchetypePlayer"],
                 "target": ["AnimFurnChair", "AnimFurnAllowEating"], "graph": "g2", "paths": ["furniture\\chair\\eat"]},
                {"role": "Furniture", "perspective": "3rd", "actor": [], "target": ["AnimFurnBench"], "graph": "g3",
                 "paths": []},
                {"role": "Weapon", "perspective": "3rd", "actor": [], "target": ["AnimFurnChair"], "graph": "g4",
                 "paths": []}]
        got = S.matching_rows(rows, ["animfurnchair", "AnimFurnAllowEating", "Other"])
        self.assertEqual([r["graph"] for r in got], ["g2", "g1"])
        self.assertEqual(S.matching_rows(rows, ["AnimFurnBed"]), [])

    def test_folders_and_files(self):
        self.assertEqual(S.folder_candidates("Furniture\\Chair"),
                         ["meshes\\actors\\human\\animations\\furniture\\chair\\", "meshes\\furniture\\chair\\"])
        self.assertEqual(S.folder_candidates("Actors/Human/Animations/Furniture"),
                         ["meshes\\actors\\human\\animations\\furniture\\"])
        names = ["meshes\\actors\\human\\animations\\furniture\\chair\\idle.afx",
                 "meshes\\actors\\human\\animations\\furniture\\chair\\idle.af",
                 "meshes\\actors\\human\\animations\\furniture\\chair\\female\\idle.afx"]
        folder = "meshes\\actors\\human\\animations\\furniture\\chair\\"
        self.assertEqual(S.files_in(names, folder, ".afx"), [names[0]])
        self.assertEqual(S.files_in(names, folder, ".af"), [names[1]])

    def test_idle_info_and_behaviour_clips(self):
        self.assertEqual(S.idle_info([(b"EDID", zs("IdleSweepStart")), (b"ENAM", zs("IdleSweepingStart")),
                                      (b"DNAM", zs("Actors\\Character\\Behaviors\\0_Master.hkx"))]),
                         {"edid": "IdleSweepStart", "event": "IdleSweepingStart",
                          "file": "Actors\\Character\\Behaviors\\0_Master.hkx"})
        b = {"nodes": {1: {"class": "hkbClipGenerator", "name": "SweepIdle", "animation": "Animations\\x.hkx"},
                       2: {"class": "hkbClipGenerator", "name": "Walk", "animation": "Animations\\mt_walk.hkx"},
                       3: {"class": "hkbClipGenerator", "name": "c", "animation": "Animations\\ChairIdle.hkx"},
                       4: {"class": "hkbStateMachine", "name": "chair"}}}
        self.assertEqual(S.furniture_clips(b), [("SweepIdle", "Animations\\x.hkx"), ("c", "Animations\\ChairIdle.hkx")])

    def test_markdown(self):
        rep = {"starfield": {"table_rows": 3, "furniture_rows": 2, "templates": {"chair": {
            "template": "FoundCanvasChair01_Free", "form": "001BF52D", "type": "FURN", "keywords": ["AnimFurnChair"],
            "rows": [{"perspective": "3rd", "actor": [], "target": ["AnimFurnChair"], "graph": "Chair.agx",
                      "paths": ["furniture\\chair"]}],
            "folders": {"furniture\\chair": {"afx": 1, "af": 1, "clips": [{"file": "idle.afx", "tag": "Idle",
                                                                          "is_state": "1"}]}},
            "graphs": {"Chair.agx": {"tags": ["Idle", "Enter"], "events": ["EnterFurniture"]}}}}},
            "skyrim": {"bases": [{"base": "000001:Skyrim.esm", "edid": "SweepIdleMarker", "kind": "sweep", "uses": 2,
                                  "type": "IDLM", "idles": [{"edid": "IdleSweep", "event": "IdleSweepStart"}]}],
                       "behaviors": {"meshes\\actors\\character\\behaviors\\idlebehavior.hkx": {
                           "name": "Idle", "clips": [{"name": "SweepIdle", "animation": "Animations\\sweep.hkx"}],
                           "events": ["IdleSweepStart"]}}}}
        md = S.markdown(rep)
        self.assertIn("## chair: FoundCanvasChair01_Free 001BF52D (FURN)", md)
        self.assertIn("tags ['Idle']", md)
        self.assertIn("graph Chair.agx: tags ['Idle', 'Enter'] events ['EnterFurniture']", md)
        self.assertIn("- sweep: SweepIdleMarker (IDLM, 2 uses) idles: IdleSweep ev=IdleSweepStart", md)
        self.assertIn("- SweepIdle: Animations\\sweep.hkx", md)


if __name__ == "__main__":
    unittest.main()
