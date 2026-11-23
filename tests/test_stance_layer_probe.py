"""scripts/armor/stance_layer_probe.py on a synthetic graph: bone-moving nodes and stance switches are listed with
their properties and input links, plain animation nodes are not, Graph Refs are followed."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import stance_layer_probe as P  # noqa: E402


def node(kind, name, rows, links=()):
    props = "".join(f"<row><prop><value>{k}</value></prop><prop><value>{v}</value></prop></row>" for k, v in rows)
    inputs = "".join(f"<input><name>in</name><link><node>{n}</node><property_sheet><row><prop><value>Event</value>"
                     f"</prop><prop><value>{ev}</value></prop></row></property_sheet></link></input>" for n, ev in links)
    return (f"<node><node_type>{kind}</node_type><name>{name}</name><property_sheet>{props}</property_sheet>{inputs}"
            f"</node>")


GRAPH = ("<root><Name>Player_Melee.agx</Name>"
         + node("NT_ANIMATION_NODE", "MeleeAttack_A", [("TagName", "MeleeAttack_A")])
         + node("NT_COPY_BONE_WEIGHTS", "Copy Bone Weights", [("Control Variable", "BoneWeightsAction")], [(1, "")])
         + node("NT_SWITCH_NODE", "Stance", [("Variable Name", "iStance"), ("Tag Alteration", "Prefix")],
                [(1, "WeaponDraw")])
         + node("NT_SWITCH_NODE", "Plain", [("Variable Name", "x"), ("Tag Alteration", "Do Nothing")])
         + node("NT_TWO_BONE_IK", "LeftHand", [("End Bone", "L_Wrist")])
         + node("NT_GRAPH_REF", "Actions", [("Graph Ref", "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\MeleeActions.agx")])
         + "</root>").encode()


class StanceProbeTests(unittest.TestCase):
    def test_probe(self):
        lines, refs = P.probe("player_melee", GRAPH)
        text = "\n".join(lines)
        self.assertIn("NT_COPY_BONE_WEIGHTS 'Copy Bone Weights' (type)", text)
        self.assertIn("Control Variable = BoneWeightsAction", text)
        self.assertIn("NT_SWITCH_NODE 'Stance' (tag alteration)", text)
        self.assertIn("<- input 'in' from node 1: Event=WeaponDraw", text)
        self.assertIn("NT_TWO_BONE_IK 'LeftHand' (type)", text)
        self.assertNotIn("'MeleeAttack_A'", text)
        self.assertNotIn("'Plain'", text)
        self.assertEqual([P.stem(r) for r in refs], ["meleeactions"])
        self.assertIn("node types:", lines[1])


if __name__ == "__main__":
    unittest.main()
