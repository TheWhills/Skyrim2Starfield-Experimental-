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

    def test_nested_machine_and_link_bounds(self):
        g = {"name": "X.agx", "nodes": [{"kind": "sm", "name": "Inner", "graph": {
            "nodes": [{"kind": "anim", "tag": "A"}, {"kind": "empty"}], "links": [(0, 1, {"event": "go"})]}}],
             "links": []}
        root = ET.fromstring(agx_write.write(g).decode())
        inner = root.find("node").find("graph")
        self.assertEqual(len(inner.findall("node")), 2)
        with self.assertRaises(ValueError):
            agx_write.write({"name": "Y.agx", "nodes": [{"kind": "empty"}], "links": [(0, 3, {})]})


if __name__ == "__main__":
    unittest.main()
