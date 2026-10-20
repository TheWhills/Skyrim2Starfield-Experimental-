"""fo4sf.bfco, af_writer descriptor helpers and scripts/armor/bfco_combo.py on synthetic data (no game or mod files)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import af_writer, agx_edit, bfco  # noqa: E402
import bfco_combo  # noqa: E402
from test_agx_edit import combo_graph  # noqa: E402

ATTACK1 = [{"time": 0.0, "text": "BFCO_NextIsAttack2"}, {"time": 0.0, "text": "BFCO_NextIsPowerAttack2"},
           {"time": 0.43, "text": "weaponSwing"}, {"time": 0.4833, "text": "HitFrame"},
           {"time": 0.5833, "text": "BFCO_NextPowerWinStart"}, {"time": 0.5833, "text": "BFCO_NextWinStart"},
           {"time": 1.1333, "text": "BFCO_DIY_recovery"}, {"time": 0.1, "text": "animmotion 0 1 0"}]
MCO = [{"time": 1.0, "text": "MCO_WinOpen"}, {"time": 1.0, "text": "MCO_PowerWinOpen"},
       {"time": 0.6, "text": "HitFrame"}, {"time": 1.67, "text": "MCO_WinClose"},
       {"time": 1.67, "text": "MCO_PowerWinClose"}, {"time": 2.0, "text": "MCO_Recovery"},
       {"time": 0.2, "text": "MCO_WinClose"}]                       # a close before the open does not count

AFX = (b"<root>\r\n\t<is_state>0</is_state>\r\n\t<tag>MeleeAttack_A</tag>\r\n\t<filename>MeleeAttack_A.af</filename>"
       b"\r\n\t<events>\r\n\t\t<event><frame>0</frame><name>AssignVariable</name><payload>X=1</payload></event>\r\n"
       b"\t\t<event><frame>22</frame><name>AttackStateNextAttack</name><payload></payload></event>\r\n\t</events>"
       b"\r\n\t<variables>\r\n\t\t<variable><name>bDontAllowAttack</name><start>0</start><end>6</end></variable>\r\n"
       b"\t\t<variable><name>bCanComboAttack</name><start>6</start><end>22</end></variable>\r\n\t</variables>\r\n"
       b"</root>")


class BfcoTests(unittest.TestCase):
    def test_markers_and_windows(self):
        m = bfco.markers(ATTACK1)
        self.assertEqual((m["next_attack"], m["next_power"]), (2, 2))
        self.assertAlmostEqual(m["win"], 0.5833)
        self.assertAlmostEqual(m["recovery"], 1.1333)
        self.assertTrue(bfco.is_attack(m))
        w = bfco.windows(m, 52)
        self.assertEqual(w["bDontAllowAttack"], (0, 14))                # presses buffered from the hit (0.4833 s)
        self.assertEqual(w["bCanComboAttack"], (14, 52))                # to the end: no close marker
        self.assertEqual(w["bDontAllowPowerAttack"], (0, 17))
        self.assertEqual(w["bFreeMovement"], (34, 52))
        self.assertEqual(w["DisableAllowRotation"], (34, 52))
        mco = bfco.markers(MCO)
        self.assertEqual((mco["win"], mco["win_close"], mco["recovery"]), (1.0, 1.67, 2.0))
        self.assertEqual(bfco.windows(mco, 75)["bCanComboAttack"], (18, 50))
        self.assertFalse(bfco.is_attack(bfco.markers([{"time": 0.1, "text": "HitFrame"}])))
        self.assertEqual(bfco.markers([{"time": 1, "text": "BFCO_DIY_Rcovery"}])["recovery"], 1.0)   # typo spelling
        lone = bfco.windows(bfco.markers([{"time": 0, "text": "BFCO_NextIsAttack1"}]), 40)
        self.assertEqual(lone["bDontAllowAttack"], (0, 40))             # no window: locked to the end

    def test_apply_to_descriptor(self):
        out = bfco.apply(AFX, bfco.markers(ATTACK1), 52)
        self.assertIn(b"<name>bDontAllowAttack</name><start>0</start><end>14</end>", out)
        self.assertIn(b"<name>bCanComboAttack</name><start>14</start><end>52</end>", out)
        self.assertIn(b"<name>bFreeMovement</name><start>34</start><end>52</end>", out)
        self.assertIn(b"<frame>17</frame><name>AttackStateNextAttack</name>", out)
        self.assertIn(b"<payload>X=1</payload>", out)                     # template kept
        out = af_writer.set_tag(out, "BFCO_Attack3", "BFCO_Attack3.af")
        self.assertIn(b"<tag>BFCO_Attack3</tag>", out)
        self.assertIn(b"<filename>BFCO_Attack3.af</filename>", out)
        self.assertNotIn(b"\r\r", out)
        added = af_writer.set_event_frame(AFX.replace(b"AttackStateNextAttack", b"Other"), "AttackStateNextAttack", 9)
        self.assertEqual(af_writer.event_frame(added, "AttackStateNextAttack"), 9)

    def test_chain_and_files(self):
        marks = {k: {"next_attack": n} for k, n in ((1, 2), (2, 3), (3, 9), (4, None))}
        self.assertEqual(bfco.chain(marks), {1: 2, 2: 3, 3: 1, 4: 1})    # unknown / missing -> back to 1
        f = bfco.attack_files(["BFCO_Attack1.HKX", "BFCO_Attack10.hkx", "BFCO_PowerAttack2.hkx",
                               "BFCO_SprintAttack.hkx", "config.json"])
        self.assertEqual(f["attack"], {1: "BFCO_Attack1.HKX", 10: "BFCO_Attack10.hkx"})
        self.assertEqual(f["power"], {2: "BFCO_PowerAttack2.hkx"})
        self.assertEqual(list(f["other"]), ["BFCO_SprintAttack"])

    def test_combo_graph_from_routing(self):
        raw = combo_graph()
        out, added = bfco_combo.build(raw, {1: 2, 2: 3, 3: 4, 4: 5, 5: 2})
        g = agx_edit.machine(agx_edit.load(out), "MeleeAttackCombo")
        idx = {k: agx_edit.state(g, f"BFCO_Attack{k}") for k in range(1, 6)}
        t = agx_edit.transitions(g)
        for k, n in ((1, 2), (2, 3), (3, 4), (4, 5), (5, 2)):
            self.assertIn((idx[k], idx[n], "MeleeAttackStart", ""), t, (k, n))
        self.assertEqual(added, ["BFCO_Attack2 -> BFCO_Attack3", "BFCO_Attack3 -> BFCO_Attack4",
                                 "BFCO_Attack4 -> BFCO_Attack5", "BFCO_Attack5 -> BFCO_Attack2"])
        nodes = g.findall("node")
        for n in nodes:                                                   # one transition per output slot
            for link in agx_edit._links_into(n):
                src = nodes[int(link.findtext("node")) - 1]
                self.assertLess(int(link.findtext("output")), len(src.findall("output")))
        two, _ = bfco_combo.build(raw, {1: 2, 2: 1})                      # a two-attack set
        g2 = agx_edit.machine(agx_edit.load(two), "MeleeAttackCombo")
        i1, i2 = agx_edit.state(g2, "BFCO_Attack1"), agx_edit.state(g2, "BFCO_Attack2")
        self.assertIn((i2, i1, "MeleeAttackStart", ""), agx_edit.transitions(g2))
        self.assertEqual(agx_edit.state(g2, "MeleeAttack_C"), 0)        # left as it was, unreachable


if __name__ == "__main__":
    unittest.main()
