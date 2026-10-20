"""fo4sf.agx_edit and scripts/armor/combo_loop.py on synthetic graphs written by fo4sf.agx_write (no game files)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import af_writer, agx_edit, agx_write  # noqa: E402
import combo_loop  # noqa: E402


def combo_graph() -> bytes:
    sm = {"nodes": [{"kind": "anim", "tag": "MeleeAttack_C"}, {"kind": "anim", "tag": "MeleeAttack_B"},
                    {"kind": "anim", "tag": "MeleeAttack_A"}, {"kind": "empty"}], "default": 3,
          "links": [(3, 2, {"event": "MeleeAttackStart", "blend": 0}), (2, 1, {"event": "MeleeAttackStart",
                                                                                "blend": 0.15}),
                    (1, 0, {"event": "MeleeAttackFinisherStart", "blend": 0.15})]}
    g = {"name": "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\MeleeAttacks.agx", "default": 1,
         "nodes": [{"kind": "sm", "name": "MeleeAttackCombo", "graph": sm}, {"kind": "empty"}, {"kind": "empty"}],
         "links": [(1, 0, {"event": "MeleeAttackStart"}), (0, 1, {"blend": 0.3}),
                   (0, 2, {"condition": combo_loop.CANCEL, "blend": 0.2})]}
    return agx_write.write(g)


AFX = (b"<root>\r\n\t<is_state>0</is_state>\r\n\t<tag>%s</tag>\r\n\t<filename>%s.af</filename>\r\n\t<rampout>%d</rampout>"
       b"\r\n\t<events>\r\n\t\t<event><frame>%d</frame><name>HitFrame</name><payload></payload></event>\r\n\t</events>"
       b"\r\n\t<variables>\r\n%s\t</variables>\r\n</root>")


def var(name, a, b):
    return b"\t\t<variable><name>%s</name><start>%d</start><end>%d</end></variable>\r\n" % (name, a, b)


class AgxEditTests(unittest.TestCase):
    def test_round_trip_and_links_are_one_based(self):
        raw = combo_graph()
        root = agx_edit.load(raw)
        self.assertEqual(agx_edit.dump(root, raw), raw)                     # untouched: identical bytes
        g = agx_edit.machine(root, "MeleeAttackCombo")
        self.assertEqual(agx_edit.transitions(g), [(1, 0, "MeleeAttackFinisherStart", ""),
                                                   (2, 1, "MeleeAttackStart", ""), (3, 2, "MeleeAttackStart", "")])
        with self.assertRaises(agx_edit.AgxEditError):
            agx_edit.machine(root, "Nope")
        with self.assertRaises(agx_edit.AgxEditError):
            agx_edit.state(g, "MeleeAttack_D")

    def test_add_transition(self):
        raw = combo_graph()
        root = agx_edit.load(raw)
        g = agx_edit.machine(root, "MeleeAttackCombo")
        c, b = agx_edit.state(g, "MeleeAttack_C"), agx_edit.state(g, "MeleeAttack_B")
        self.assertTrue(agx_edit.add_transition(root, g, c, b, "MeleeAttackStart", 0.15))
        self.assertFalse(agx_edit.add_transition(root, g, c, b, "MeleeAttackStart", 0.15))   # already there
        out = agx_edit.dump(root, raw)
        g2 = agx_edit.machine(agx_edit.load(out), "MeleeAttackCombo")
        self.assertIn((0, 1, "MeleeAttackStart", ""), agx_edit.transitions(g2))
        nodes = g2.findall("node")
        for n in nodes:                                                     # one link per input, ids unique per node
            self.assertTrue(all(len(i.findall("link")) <= 1 for i in n.findall("input")))
            ids = [x.findtext("id") for t in ("input", "output") for x in n.findall(t)]
            self.assertEqual(len(ids), len(set(ids)))
        used = [(int(l.findtext("node")), l.findtext("output")) for n in nodes for l in n.iter("link")]
        self.assertEqual(len(used), len(set(used)))                         # one transition per output slot
        for s, o in used:                                                   # every link names a real source slot
            self.assertLess(int(o), len(nodes[s - 1].findall("output")))
        self.assertIn(b"\r\n", out)
        self.assertTrue(out.endswith(b"</root>\r\n"))

    def test_descriptor_timing_helpers(self):
        a = AFX % (b"MeleeAttack_A", b"MeleeAttack_A", 4, 14, var(b"bCanComboAttack", 6, 18))
        c = AFX % (b"MeleeAttack_C", b"MeleeAttack_C", 9, 19, var(b"bDontAllowAttack", 0, 50))
        out = af_writer.copy_timing(a, c)
        self.assertIn(b"<tag>MeleeAttack_C</tag>", out)
        self.assertIn(b"<filename>MeleeAttack_C.af</filename>", out)
        self.assertIn(b"<rampout>4</rampout>", out)
        self.assertIn(b"<frame>14</frame><name>HitFrame</name>", out)
        self.assertIn(b"bCanComboAttack", out)
        self.assertNotIn(b"bDontAllowAttack", out)
        self.assertNotIn(b"\r\r", out)
        b = AFX % (b"MeleeAttack_B", b"MeleeAttack_B", 4, 14, var(b"bCanComboAttack", 6, 18) +
                   var(b"bAllowFinisher", 15, 40))
        out, dropped = af_writer.drop_variables(b, {"bAllowFinisher"})
        self.assertEqual(dropped, ["bAllowFinisher"])
        self.assertNotIn(b"bAllowFinisher", out)
        self.assertIn(b"bCanComboAttack", out)

    def test_condition_and_variable_window(self):
        root = agx_edit.load(combo_graph())
        top = agx_edit.machine(root, None)
        self.assertEqual(agx_edit.set_condition(top, 0, 2, "X", old="something else"), 0)
        self.assertEqual(agx_edit.set_condition(top, 0, 2, "X", old=combo_loop.CANCEL), 1)
        self.assertIn((0, 2, "", "X"), agx_edit.transitions(top))
        a = AFX % (b"MeleeAttack_A", b"MeleeAttack_A", 4, 14, var(b"bFreeMovement", 29, 38))
        out = af_writer.set_variable_window(a, "bFreeMovement", 0, 38)
        self.assertIn(b"<name>bFreeMovement</name><start>0</start><end>38</end>", out)
        out = af_writer.set_variable_window(a, "bNew", 3, 7)
        self.assertIn(b"<name>bNew</name><start>3</start><end>7</end>", out)
        self.assertIn(b"<start>29</start>", out)
        self.assertEqual(combo_loop.last_frame(a), 38)

    def test_combo_loop_script(self):
        with tempfile.TemporaryDirectory() as d:
            graph = os.path.join(d, "meleeattacks.agx")
            with open(graph, "wb") as fh:
                fh.write(combo_graph())
            clips = os.path.join(d, "pack", "meshes", "actors", "human", "animations", "melee", "onehanded", "player")
            os.makedirs(clips)
            for name, hit, vs in ((b"MeleeAttack_A", 14, var(b"bCanComboAttack", 6, 18)),
                                  (b"MeleeAttack_B", 16, var(b"bCanComboAttack", 6, 18) + var(b"bAllowFinisher", 15, 40)),
                                  (b"MeleeAttack_C", 19, var(b"bDontAllowAttack", 0, 50))):
                with open(os.path.join(clips, name.decode() + ".afx"), "wb") as fh:
                    fh.write(AFX % (name, name, 6, hit, vs))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(combo_loop.main(["--graph", graph, "--clips", clips, "--move-while-attacking",
                                                  "--out", os.path.join(d, "pack")]), 0)
            with open(os.path.join(d, "pack", *combo_loop.GRAPH_REL), "rb") as fh:
                root = agx_edit.load(fh.read())
                g = agx_edit.machine(root, "MeleeAttackCombo")
            with open(os.path.join(clips, "MeleeAttack_C.afx"), "rb") as fh:
                c = fh.read()
            with open(os.path.join(clips, "MeleeAttack_B.afx"), "rb") as fh:
                b = fh.read()
        t = agx_edit.transitions(g)
        self.assertIn((0, 1, "MeleeAttackStart", ""), t)                   # C -> B
        self.assertIn((1, 0, "MeleeAttackStart", ""), t)                   # B -> C without the finisher
        self.assertIn((1, 0, "MeleeAttackFinisherStart", ""), t)           # vanilla link kept
        self.assertIn(b"bCanComboAttack", c)
        self.assertNotIn(b"bDontAllowAttack</name><start>0</start><end>50", c)
        self.assertNotIn(b"bAllowFinisher", b)
        self.assertIn(b"<name>bFreeMovement</name><start>0</start>", c)       # experiment: free movement throughout
        self.assertIn((0, 2, "", "bFreeMovement !greaterthan! 1"), agx_edit.transitions(agx_edit.machine(root)))


if __name__ == "__main__":
    unittest.main()
