"""fo4sf.behavior_to_agx + agx_write on the synthetic behaviour graph of test_skyrimbehavior (no game data)."""
import os
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import agx, agx_write, behavior_to_agx as T, skyrimbehavior as SB  # noqa: E402
from test_skyrimbehavior import graph  # noqa: E402


class BehaviorToAgxTests(unittest.TestCase):
    def test_condition_spelling(self):
        self.assertEqual(T.condition("(staggerDirection < .25) || (staggerDirection > .75)"),
                         "(staggerDirection !lessthan! .25) | (staggerDirection !greaterthan! .75)")
        self.assertEqual(T.condition("a >= 1 && b == 0"), "a !greaterthan!= 1 !ampersand! b = 0")
        self.assertEqual(T.condition(None), "")
        self.assertEqual(T.condition("Speed <= 0.05 && x != 1"), "Speed !lessthan!= 0.05 !ampersand! x != 1")

    def test_translate_states_clips_and_transition(self):
        data = graph()
        b = SB.read(data)
        g, rep = T.translate(b, name="Test.agx", reader=SB._Reader(data))
        self.assertEqual([n.get("tag") for n in g["nodes"]], ["IdleClip", "WalkClip"])    # start state first
        self.assertEqual(g["links"], [(0, 1, {"event": "moveStart", "condition": "", "blend": 0.2})])
        self.assertEqual((rep["states"], rep["clip_states"], rep["links"]), (2, 2, 1))
        self.assertEqual(rep["tags"], {"IdleClip": "Animations\\Idle.hkx", "WalkClip": "Animations\\Walk.hkx"})
        out = agx_write.write(g)
        self.assertTrue(out.startswith(b"<root>\r\n<Name>Data\\Meshes\\AnimTextData\\Tables\\Graphs\\Test.agx</Name>"))
        s = agx.summary(agx.read_graph(out))
        self.assertEqual((s["tags"], s["events"]), (["IdleClip", "WalkClip"], ["moveStart"]))
        walk = ET.fromstring(out.decode()).findall("node")[1]
        link = walk.find("input").find("link")
        self.assertEqual((link.findtext("node"), link.findtext("output")), ("0", "0"))

    def test_blend_selector_shared_and_behavior_reference(self):
        # a hand-made graph model (the shape skyrimbehavior.read returns)
        def node(c, name=None, children=(), **kw):
            return dict({"class": c, "name": name, "children": list(children)}, **kw)
        N = {
            1: node("hkbStateMachine", "Root", [10, 11, 12], states=[10, 11, 12], start_state=0, wildcard=None),
            10: node("hkbStateMachineStateInfo", "Move", [20], state_id=0, generator=20, transitions=None),
            11: node("hkbStateMachineStateInfo", "Pick", [30], state_id=1, generator=30, transitions=None),
            12: node("hkbStateMachineStateInfo", "Ref", [40], state_id=2, generator=40, transitions=None),
            20: node("hkbBlenderGenerator", "Speed", [21, 22, 23], blend_children=[21, 22, 23],
                     bindings=[{"member": "blendParameter", "variable": 0, "kind": "variable"}]),
            21: node("hkbBlenderGeneratorChild", None, [50], generator=50, weight=0.0),
            22: node("hkbBlenderGeneratorChild", None, [51], generator=51, weight=0.5),
            23: node("hkbBlenderGeneratorChild", None, [60], generator=60, weight=1.0),
            30: node("hkbManualSelectorGenerator", "Choose", [50, 60],
                     bindings=[{"member": "selectedGeneratorIndex", "variable": 1, "kind": "variable"}]),
            40: node("hkbBehaviorReferenceGenerator", "Ref", [], behavior="Behaviors\\QuadrupedBehavior.hkx"),
            50: node("hkbClipGenerator", "Walk", [], animation="Animations\\Walk.hkx"),
            51: node("hkbClipGenerator", "Jog", [], animation="Animations\\Jog.hkx"),
            60: node("hkbStateMachine", "Shared", [61], states=[61], start_state=0, wildcard=None),
            61: node("hkbStateMachineStateInfo", "S", [52], state_id=0, generator=52, transitions=None),
            52: node("hkbClipGenerator", "Run", [], animation="Animations\\Run.hkx"),
        }
        b = {"nodes": N, "events": [], "variables": ["Speed", "iPick"], "root": 1}
        g, rep = T.translate(b, name="Beast.agx")
        move, pick, ref = g["nodes"]
        self.assertEqual((move["kind"], pick["kind"], ref), ("blendtree", "blendtree",
                                                            {"kind": "ref", "graph_ref": "QuadrupedBehavior"}))
        tree = move["graph"]
        self.assertEqual(tree["nodes"][0]["kind"], "blend")                       # the output is node 0
        self.assertEqual((tree["nodes"][0]["variable"], tree["nodes"][0]["range"]), ("Speed", (0.0, 1.0)))
        self.assertEqual(tree["nodes"][0]["curves"], [[(0.0, 1.0), (0.5, 0.0)], [(0.0, 0.0), (0.5, 1.0), (1.0, 0.0)],
                                                      [(0.5, 0.0), (1.0, 1.0)]])
        self.assertEqual(tree["nodes"][3], {"kind": "ref", "graph_ref": "Beast_Shared"})   # used twice: own graph
        self.assertIn((3, 0, {"data": True, "input": 2}), tree["links"])
        sw = pick["graph"]["nodes"][0]
        self.assertEqual((sw["kind"], sw["variable"], sw["inputs"]), ("switch", "iPick", ["Walk", "Shared"]))
        self.assertEqual(list(rep["extra_graphs"]), ["Beast_Shared"])
        self.assertEqual(rep["extra_graphs"]["Beast_Shared"]["nodes"], [{"kind": "anim", "tag": "Run"}])
        out = agx_write.write(g)
        root = ET.fromstring(out.decode())
        bt = root.findall("node")[0]
        self.assertEqual(bt.findtext("node_type"), "NT_BLEND_TREE_EMBEDDED")
        blend = bt.find("graph").findall("node")[0]
        self.assertEqual([len(bi.findall("point")) for bi in blend.findall("blendInput")], [2, 3, 2])
        self.assertEqual([i.findtext("name").strip() for i in blend.findall("input")], ["input0", "input1", "input2"])
        self.assertIsNone(blend.find("input").find("link").find("property_sheet"))   # data links carry no sheet
        agx_write.write(rep["extra_graphs"]["Beast_Shared"])

    def test_nested_machine_and_link_bounds(self):
        g = {"name": "X.agx", "nodes": [{"kind": "sm", "name": "Inner", "graph": {
            "nodes": [{"kind": "anim", "tag": "A"}, {"kind": "empty"}], "links": [(0, 1, {"event": "go"})]}}],
             "links": []}
        root = ET.fromstring(agx_write.write(g).decode())
        inner = root.find("node").find("graph")
        self.assertEqual(len(inner.findall("node")), 2)
        with self.assertRaises(ValueError):
            agx_write.write({"name": "Y.agx", "nodes": [{"kind": "empty"}], "links": [(0, 3, {})]})

    def test_default_state_flags_and_start_method(self):
        g = {"name": "X.agx", "default": 1, "start_method": "Sync", "start_variable": "iSyncIdleWalkRun",
             "nodes": [{"kind": "anim", "tag": "A"}, {"kind": "anim", "tag": "B", "flags": ["Animation Driven"]}],
             "links": [], }
        out = agx_write.write(g).decode()
        self.assertIn("<node>\r\n<default_state>True</default_state>\r\n\t<node_type>NT_ANIMATION_NODE", out)
        self.assertEqual(out.count("<default_state>"), 1)
        root = ET.fromstring(out)
        a, b = root.findall("node")
        self.assertIsNone(a.find("default_state"))
        self.assertEqual(b.findtext("default_state"), "True")
        self.assertIsNone(a.find("flags"))                                   # vanilla omits empty flags
        self.assertEqual(b.find("flags").findtext("flag"), "Animation Driven")
        sheet = root.findall("property_sheet")[-1]
        rows = {r.findall("prop")[0].findtext("value"): r.findall("prop")[1] for r in sheet.findall("row")}
        self.assertEqual((rows["Start Selection Method"].findtext("value"),
                          rows["Start Selection Method"].findtext("listindex")), ("Sync", "1"))
        self.assertEqual(rows["Start Selection Variable"].findtext("value"), "iSyncIdleWalkRun")
        nested = {"name": "Y.agx", "nodes": [{"kind": "blendtree", "name": "T", "graph": {
            "nodes": [{"kind": "anim", "tag": "Out"}], "links": []}}], "links": []}
        self.assertEqual(agx_write.write(nested).decode().count("<default_state>"), 1)   # root only, not the tree
        with self.assertRaises(ValueError):
            agx_write.write({"name": "Z.agx", "default": 4, "nodes": [{"kind": "empty"}], "links": []})


if __name__ == "__main__":
    unittest.main()
