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
         "links": [(0, 0, {"event": "MeleeAttackStart"}), (0, 1, {"blend": 0.3}),     # any state -> combo, as vanilla
                   (0, 2, {"condition": CANCEL, "blend": 0.2})]}
    return agx_write.write(g)


CANCEL = "Speed !greaterthan! 1.0 !ampersand! bFreeMovement !greaterthan! 0"


def actions_graph() -> bytes:
    idle = {"nodes": [{"kind": "empty"}], "links": []}
    g = {"name": "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\MeleeActions.agx", "default": 1,
         "nodes": [{"kind": "anim", "tag": "CastSelf", "flags": ["Block POV Switch"]},
                   {"kind": "sm", "name": "IdleTimer", "graph": idle}],
         "links": [(0, 0, {"event": "CastSelfStart", "blend": 0}), (0, 1, {"blend": 0.3})]}
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
        self.assertEqual(agx_edit.set_condition(top, 0, 2, "X", old=CANCEL), 1)
        self.assertEqual(combo_loop.last_frame(var(b"x", 3, 41)), 41)
        self.assertIn((0, 2, "", "X"), agx_edit.transitions(top))
        a = AFX % (b"MeleeAttack_A", b"MeleeAttack_A", 4, 14, var(b"bFreeMovement", 29, 38))
        out = af_writer.set_variable_window(a, "bFreeMovement", 0, 38)
        self.assertIn(b"<name>bFreeMovement</name><start>0</start><end>38</end>", out)
        out = af_writer.set_variable_window(a, "bNew", 3, 7)
        self.assertIn(b"<name>bNew</name><start>3</start><end>7</end>", out)
        self.assertIn(b"<start>29</start>", out)

    def test_set_event_and_clone_state_stay_on_their_level(self):
        root = agx_edit.load(combo_graph())
        top = agx_edit.machine(root, None)
        self.assertEqual(agx_edit.set_event(top, 0, 0, "Renamed", old="MeleeAttackStart"), 1)   # only the self-link
        inner = agx_edit.machine(root, "MeleeAttackCombo")
        self.assertIn((3, 2, "MeleeAttackStart", ""), agx_edit.transitions(inner))            # inner None -> A kept
        act = agx_edit.load(actions_graph())
        atop = agx_edit.machine(act, None)
        k = agx_edit.clone_state(top.findall("node")[0], atop)
        node = atop.findall("node")[k]
        self.assertEqual(k, 2)
        self.assertEqual(node.findall("output"), [])
        self.assertTrue(all(not i.findall("link") for i in node.findall("input")))
        uids = [n.findtext("user_id") for n in atop.findall("node")]
        self.assertEqual(len(uids), len(set(uids)))
        self.assertNotEqual(node.findtext("guid"), top.findall("node")[0].findtext("guid"))
        self.assertEqual(len(agx_edit.transitions(agx_edit.machine(act, "MeleeAttackCombo"))), 3)

    def test_flag_and_upper_body_layer(self):
        root = agx_edit.load(combo_graph())
        combo = agx_edit.machine(root, None).findall("node")[0]
        raw, rep = combo_loop.layer_combo(actions_graph(), combo, upper_body=True)
        top = agx_edit.machine(agx_edit.load(raw))
        node = top.findall("node")[agx_edit.state(top, "MeleeAttackCombo")]
        self.assertEqual([f.text for f in node.find("flags")], ["Force Copy Bone Weights"])
        self.assertFalse(agx_edit.add_flag(node, "Force Copy Bone Weights"))           # once only
        cast = top.findall("node")[0]
        self.assertTrue(agx_edit.add_flag(cast, "Is Busy"))
        self.assertEqual([f.text for f in cast.find("flags")], ["Block POV Switch", "Is Busy"])
        self.assertIn(b"<flags><flag>Force Copy Bone Weights</flag></flags>", raw)
        self.assertTrue(agx_edit.remove_flag(cast, "Block POV Switch"))
        self.assertTrue(agx_edit.remove_flag(cast, "Is Busy"))
        self.assertIsNone(cast.find("flags"))                                          # emptied: removed
        self.assertFalse(agx_edit.remove_flag(cast, "Is Busy"))
        piv = agx_edit.load(combo_graph())
        cnode = agx_edit.machine(piv, None).findall("node")[0]
        agx_edit.add_flag(cnode, "Should Pivot to Camera")
        raw, _ = combo_loop.layer_combo(actions_graph(), cnode, upper_body=True, no_pivot=True)
        self.assertNotIn(b"Should Pivot to Camera", raw)
        a = AFX % (b"MeleeAttack_A", b"MeleeAttack_A", 4, 14, var(b"bAlignWithAimAssistTarget", 0, 23) +
                   var(b"bCanComboAttack", 6, 18))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "MeleeAttack_A.afx"), "wb") as fh:
                fh.write(a)
            combo_loop.fix_descriptors(d, no_pivot=True)
            with open(os.path.join(d, "MeleeAttack_A.afx"), "rb") as fh:
                out = fh.read()
        self.assertNotIn(b"bAlignWithAimAssistTarget", out)
        self.assertIn(b"bCanComboAttack", out)

    def test_combo_loop_script(self):
        with tempfile.TemporaryDirectory() as d:
            graph = os.path.join(d, "meleeattacks.agx")
            with open(graph, "wb") as fh:
                fh.write(combo_graph())
            actions = os.path.join(d, "meleeactions.agx")
            with open(actions, "wb") as fh:
                fh.write(actions_graph())
            clips = os.path.join(d, "pack", "meshes", "actors", "human", "animations", "melee", "onehanded", "player")
            os.makedirs(clips)
            for name, hit, vs in ((b"MeleeAttack_A", 14, var(b"bCanComboAttack", 6, 18)),
                                  (b"MeleeAttack_B", 16, var(b"bCanComboAttack", 6, 18) + var(b"bAllowFinisher", 15, 40)),
                                  (b"MeleeAttack_C", 19, var(b"bDontAllowAttack", 0, 50))):
                with open(os.path.join(clips, name.decode() + ".afx"), "wb") as fh:
                    fh.write(AFX % (name, name, 6, hit, vs))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(combo_loop.main(["--graph", graph, "--clips", clips, "--actions-graph", actions,
                                                  "--free-movement", "--out", os.path.join(d, "pack")]), 0)
            with open(os.path.join(d, "pack", *combo_loop.GRAPH_REL), "rb") as fh:
                root = agx_edit.load(fh.read())
                g = agx_edit.machine(root, "MeleeAttackCombo")
            with open(os.path.join(d, "pack", *combo_loop.ACTIONS_REL), "rb") as fh:
                act = agx_edit.load(fh.read())
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
        self.assertIn(b"<name>bFreeMovement</name><start>0</start><end>18</end>", c)   # experiment: to its last frame
        top_t = agx_edit.transitions(agx_edit.machine(root))
        self.assertIn((0, 0, combo_loop.UNUSED_EVENT, ""), top_t)          # full-body combo no longer entered
        self.assertNotIn((0, 0, "MeleeAttackStart", ""), top_t)
        a_top = agx_edit.machine(act)
        k = agx_edit.state(a_top, "MeleeAttackCombo")
        idle = agx_edit.state(a_top, "IdleTimer")
        self.assertIn((k, k, "MeleeAttackStart", ""), agx_edit.transitions(a_top))   # layered: any state -> combo
        self.assertIn((k, idle, "", ""), agx_edit.transitions(a_top))                 # back to idle at its end
        inner = agx_edit.transitions(agx_edit.machine(act, "MeleeAttackCombo"))
        self.assertIn((0, 1, "MeleeAttackStart", ""), inner)                          # the looping copy
        self.assertIn((3, 2, "MeleeAttackStart", ""), inner)                          # None -> A untouched


if __name__ == "__main__":
    unittest.main()
