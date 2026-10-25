"""fo4sf.agx: .agx graph and .afx descriptor readers on synthetic files written in the shipped layout."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import agx  # noqa: E402


def sheet(rows):
    r = "".join(f"<row><prop><type>2</type><value>{k}</value></prop><prop><type>2</type><value>{v}</value></prop></row>"
                for k, v in rows)
    return f"<property_sheet><num_columns>2</num_columns>{r}</property_sheet>"


GRAPH = ("<root>\r\n<Name>Data\\Meshes\\AnimTextData\\Tables\\Graphs\\Test.agx</Name>\r\n<Link_Style>1</Link_Style>"
         "<node><node_type>NT_ANIMATION_NODE</node_type><name>Animation</name>"
         "<input><name></name><id>9</id><idx>0</idx><link><node>1</node><output>0</output><hidden>False</hidden>"
         + sheet([("Event", "BowDrawStart"), ("Condition", "bDontAllowAttack=0"), ("Blend Time", "0.15")]) +
         "</link></input><output><name></name><id>8</id><idx>0</idx></output>"
         + sheet([("TagName", "BowDraw"), ("State Variable", "iAttackState0"), ("Speed Multiplier", "WeaponSpeedMult")]) +
         "</node>"
         "<node><node_type>NT_SWITCH_NODE</node_type>"
         "<input><name>Relaxed</name><id>1</id><idx>0</idx></input><input><name>Sneak</name><id>2</id><idx>1</idx></input>"
         + sheet([("Name", "RelaxReadySneakSwitch"), ("Variable Name", "iSyncRelaxReadySneak"),
                  ("Tag Alteration", "Prefix")]) + "</node>"
         "<node><node_type>NT_GRAPH_REF</node_type>" + sheet([("Graph Ref", "MeleeActions")]) + "</node>"
         "</root>").encode()

AFX = (b"<root><is_state>0</is_state><tag>MeleeAttack_A</tag><filename>Sneak_MeleeAttack_A.af</filename>"
       b"<rampout>6</rampout><flags></flags><events><event><frame>8</frame><name>PreHitFrame</name><payload></payload>"
       b"</event><event><frame>20</frame><name>HitFrame</name><payload></payload></event></events><variables>"
       b"<variable><name>bDontAllowBlock</name><start>0</start><end>30</end></variable></variables></root>")


class AgxTests(unittest.TestCase):
    def test_graph_summary(self):
        g = agx.read_graph(GRAPH)
        self.assertEqual(len(g["nodes"]), 3)
        self.assertEqual(g["nodes"][0]["inputs"][0]["links"][0]["props"]["Event"], "BowDrawStart")
        s = agx.summary(g)
        self.assertEqual((s["tags"], s["graph_refs"], s["events"]), (["BowDraw"], ["MeleeActions"], ["BowDrawStart"]))
        self.assertEqual(s["conditions"], ["bDontAllowAttack=0"])
        self.assertEqual(s["tag_alterations"], [{"switch": "RelaxReadySneakSwitch", "mode": "Prefix",
                                                 "variable": "iSyncRelaxReadySneak", "cases": ["Relaxed", "Sneak"]}])
        self.assertIn("WeaponSpeedMult", s["variables"])

    def test_descriptor(self):
        d = agx.read_descriptor(AFX)
        self.assertEqual((d["tag"], d["filename"], d["rampout"]), ("MeleeAttack_A", "Sneak_MeleeAttack_A.af", 6))
        self.assertEqual(d["events"], [(8, "PreHitFrame", ""), (20, "HitFrame", "")])
        self.assertEqual(d["variables"], [("bDontAllowBlock", 0, 30)])


class LinkBlendTests(unittest.TestCase):
    def sheet(self, event, blend):
        return ("\t<property_sheet>\r\n\t\t<row>\r\n\t\t\t<prop> <type>2</type> <value>Event</value> </prop>\r\n"
                f"\t\t\t<prop> <type>2</type> <value>{event}</value> </prop>\r\n\t\t</row>\r\n\t\t<row>\r\n"
                "\t\t\t<prop> <type>2</type> <value>Blend Time</value> </prop>\r\n"
                f"\t\t\t<prop> <type>1</type> <value>{blend}</value> </prop>\r\n\t\t</row>\r\n\t</property_sheet>\r\n")

    def test_only_that_event(self):
        data = ("<root>\r\n" + self.sheet("BlockStart", "0.3") + self.sheet("BlockStop", "0.3")
                + self.sheet("BlockStartX", "0.3") + "</root>\r\n").encode()
        out, n = agx.set_link_blend(data, "BlockStart", 0.1)
        self.assertEqual(n, 1)
        self.assertEqual(out.decode().count("<value>0.1</value>"), 1)
        self.assertEqual(out.decode().count("<value>0.3</value>"), 2)
        self.assertEqual(len(out), len(data))                          # "0.3" -> "0.1": nothing else moved
        self.assertIn(self.sheet("BlockStart", "0.1").encode(), out)
        self.assertEqual(agx.set_link_blend(data, "Nope", 0.1), (data, 0))


if __name__ == "__main__":
    unittest.main()
