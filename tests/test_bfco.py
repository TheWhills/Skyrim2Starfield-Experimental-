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
        self.assertEqual(w["bDontAllowAttack"], (0, 6))                 # presses queue from 0.2 s, as vanilla
        self.assertEqual(w["bCanComboAttack"], (6, 17))                 # ends where the next attack starts
        self.assertEqual(w["bDontAllowPowerAttack"], (0, 17))
        self.assertEqual(w["bFreeMovement"], (34, 52))
        self.assertEqual(w["DisableAllowRotation"], (34, 52))
        mco = bfco.markers(MCO)
        self.assertEqual((mco["win"], mco["win_close"], mco["recovery"]), (1.0, 1.67, 2.0))
        self.assertEqual(bfco.windows(mco, 75)["bCanComboAttack"], (12, 30))     # 0.6 s before a late window
        early = bfco.windows(bfco.markers([{"time": 0.1, "text": "BFCO_NextWinStart"}]), 60)
        self.assertEqual(early["bCanComboAttack"], (3, 3))                       # never past the window
        self.assertFalse(bfco.is_attack(bfco.markers([{"time": 0.1, "text": "HitFrame"}])))
        self.assertEqual(bfco.markers([{"time": 1, "text": "BFCO_DIY_Rcovery"}])["recovery"], 1.0)   # typo spelling
        lone = bfco.windows(bfco.markers([{"time": 0, "text": "BFCO_NextIsAttack1"}]), 40)
        self.assertEqual(lone["bDontAllowAttack"], (0, 40))             # no window: locked to the end

    def test_apply_to_descriptor(self):
        out = bfco.apply(AFX, bfco.markers(ATTACK1), 52)
        self.assertIn(b"<name>bDontAllowAttack</name><start>0</start><end>6</end>", out)
        self.assertIn(b"<name>bCanComboAttack</name><start>6</start><end>17</end>", out)
        self.assertIn(b"<name>bFreeMovement</name><start>34</start><end>52</end>", out)
        self.assertIn(b"<frame>17</frame><name>AttackStateNextAttack</name>", out)
        self.assertIn(b"<payload>X=1</payload>", out)                     # template kept
        sneak = AFX.replace(b"<filename>MeleeAttack_A.af</filename>",
                            b"<filename>Sneak_MeleeAttack_B.af</filename>\r\n\t<prefix>Sneak</prefix>")
        un = af_writer.set_tag(sneak, "MeleeAttack_D", "Sneak_MeleeAttack_B.af", prefix=None)
        self.assertNotIn(b"<prefix>", un)
        self.assertIn(b"<filename>Sneak_MeleeAttack_B.af</filename>\r\n\t<events>", un)
        self.assertIn(b"<prefix>Zg</prefix>", af_writer.set_tag(un, "MeleeAttack_D", "x.af", prefix="Zg"))
        self.assertIn(b"<prefix>Sneak</prefix>", af_writer.set_tag(sneak, "T", "x.af"))       # kept by default
        out = af_writer.set_tag(out, "BFCO_Attack3", "BFCO_Attack3.af")
        self.assertIn(b"<tag>BFCO_Attack3</tag>", out)
        self.assertIn(b"<filename>BFCO_Attack3.af</filename>", out)
        self.assertNotIn(b"\r\r", out)
        fin = AFX.replace(b"</variables>", b"\t<variable><name>bAllowFinisher</name><start>15</start><end>48</end>"
                                           b"</variable>\r\n\t</variables>")
        self.assertNotIn(b"bAllowFinisher", bfco.apply(fin, bfco.markers(ATTACK1), 52))
        added = af_writer.set_event_frame(AFX.replace(b"AttackStateNextAttack", b"Other"), "AttackStateNextAttack", 9)
        self.assertEqual(af_writer.event_frame(added, "AttackStateNextAttack"), 9)

    def test_mco_payload_routing_and_speed(self):
        nordic = [{"time": 0.06, "text": "PIE.@SGVF|MCO_AttackSpeed|0.9"},
                  {"time": 0.06, "text": "PIE.@SGVI|MCO_nextattack|1"},
                  {"time": 0.06, "text": "PIE.@SGVI|MCO_nextpowerattack|4"}, {"time": 0.5, "text": "HitFrame"},
                  {"time": 1.17, "text": "MCO_WinOpen"}, {"time": 1.33, "text": "MCO_WinClose"},
                  {"time": 0.2, "text": "HitFrame.@CAMSHAKE|1|0.1"}]
        m = bfco.markers(nordic)
        self.assertEqual((m["next_attack"], m["next_power"], m["speed"]), (1, 4, 0.9))
        self.assertEqual(m["hits"], [0.5])                                  # a payload on HitFrame is not a hit
        self.assertTrue(bfco.is_attack(m))
        typo = bfco.markers([{"time": 0.06, "text": "PIE.@SVGF|MCO_AttackSpeed|1.1"}])
        self.assertIsNone(typo["speed"])                                    # misspelt: Payload Interpreter ignores it
        self.assertEqual(bfco.payload("PIE.@SGVI|MCO_nextattack|2"), ("SGVI", ["MCO_nextattack", "2"]))
        self.assertIsNone(bfco.payload("HitFrame"))
        # Nordic 1H: 1 -> 2 -> 3 -> 4 -> 5 -> 1, attack 6 -> 5 but nothing leads to 6
        marks = {k: {"next_attack": n} for k, n in ((1, 2), (2, 3), (3, 4), (4, 5), (5, 1), (6, 5))}
        r = bfco.chain(marks)
        self.assertEqual(bfco.reachable(r), [1, 2, 3, 4, 5])
        pw = {k: {"next_power": n} for k, n in ((1, 2), (2, 3), (3, 1))}
        self.assertEqual(bfco.chain(pw, "next_power"), {1: 2, 2: 3, 3: 1})

    def test_routing_value_when_the_window_opens(self):
        # LoreRim dual sword: nextattack 2 before the window, reset to 1 late in it (annotations not in time order)
        ann = [{"time": 0.667, "text": "MCO_WinOpen"}, {"time": 0.667, "text": "MCO_PowerWinOpen"},
               {"time": 0.6, "text": "PIE.@SGVI|MCO_nextattack|2"}, {"time": 0.6, "text": "PIE.@SGVI|MCO_nextpowerattack|2"},
               {"time": 1.333, "text": "PIE.@SGVI|MCO_nextattack|1"}, {"time": 1.983, "text": "MCO_WinClose"}]
        m = bfco.markers(ann)
        self.assertEqual((m["next_attack"], m["next_power"]), (2, 2))
        self.assertEqual(m["late_reset"], {"next_attack": 1})
        # set only after the window opened: the first value counts
        m = bfco.markers([{"time": 0.5, "text": "MCO_WinOpen"}, {"time": 0.7, "text": "PIE.@SGVI|MCO_nextattack|3"},
                          {"time": 0.9, "text": "PIE.@SGVI|MCO_nextattack|1"}])
        self.assertEqual(m["next_attack"], 3)
        # no window: the last assignment, as before
        m = bfco.markers([{"time": 0.1, "text": "BFCO_NextIsAttack2"}, {"time": 0.2, "text": "BFCO_NextIsAttack4"}])
        self.assertEqual(m["next_attack"], 4)
        self.assertNotIn("late_reset", m)

    def test_routes_over_normal_and_power_attacks(self):
        attacks = {1: {"next_attack": 2, "next_power": 2}, 2: {"next_attack": 1, "next_power": 9},
                   3: {"next_attack": 1, "next_power": 1}}                       # 3: only a power attack leads here
        powers = {1: {"next_attack": 1, "next_power": 2}, 2: {"next_attack": 3, "next_power": 1},
                  3: {"next_attack": 1, "next_power": 1}}                         # power 3: nothing leads here
        r = bfco.routes(attacks, powers)
        self.assertEqual(r["attack"], {1: 2, 2: 1, 3: 1})
        self.assertEqual(r["attack_power"], {1: 2, 2: 1, 3: 1})                  # unknown power 9 -> the first
        self.assertEqual(r["power_attack"], {1: 1, 2: 3})
        self.assertEqual(r["powers"], [1, 2])
        self.assertEqual(bfco.routes(attacks, {})["powers"], [])
        none = {1: {"next_attack": None, "next_power": None}, 2: {"next_attack": None, "next_power": None}}
        self.assertEqual(bfco.routes(none, {1: {}})["attack_power"], {})          # no power routing at all

    def test_power_states_in_the_combo_graph(self):
        raw = combo_graph()
        power = {"tags": {1: "MeleeAttackPower_A", 2: "MeleeAttack_E"}, "attack_power": {1: 2, 2: 1, 3: 7},
                 "power_attack": {1: 1, 2: 3}, "power_power": {1: 2, 2: 1}}
        out, added = bfco_combo.build(raw, {1: 2, 2: 3, 3: 1}, None, power)
        root = agx_edit.load(out)
        g = agx_edit.machine(root, "MeleeAttackCombo")
        t = agx_edit.transitions(g)
        a = {k: agx_edit.state(g, f"BFCO_Attack{k}") for k in (1, 2, 3)}
        p1, p2 = agx_edit.state(g, "MeleeAttackPower_A"), agx_edit.state(g, "MeleeAttack_E")
        self.assertIn((a[1], p2, "MeleeAttackPowerStart", ""), t)
        self.assertIn((a[3], p1, "MeleeAttackPowerStart", ""), t)                  # untagged power 7 -> first
        self.assertIn((p2, a[3], "MeleeAttackStart", ""), t)
        self.assertIn((p1, p2, "MeleeAttackPowerStart", ""), t)
        self.assertIn((p2, p1, "MeleeAttackPowerStart", ""), t)
        nodes = g.findall("node")
        for n in nodes:                                                   # one transition per output slot
            for link in agx_edit._links_into(n):
                src = nodes[int(link.findtext("node")) - 1]
                self.assertLess(int(link.findtext("output")), len(src.findall("output")))
        self.assertIn("BFCO_Attack1 =power=> MeleeAttack_E", added)

    def test_inner_only_switches_off_the_vanilla_combo_power_transition(self):
        """Vanilla MeleeAttacks.agx: combo -> MeleeAttackPower_A on MeleeAttackPowerStart one level up caught every
        mid-combo power press (owner's run); with inner_only it never fires, the standing one still does."""
        from fo4sf import agx_write
        sm = {"nodes": [{"kind": "anim", "tag": "MeleeAttack_C"}, {"kind": "anim", "tag": "MeleeAttack_B"},
                        {"kind": "anim", "tag": "MeleeAttack_A"}, {"kind": "empty"}], "default": 3,
              "links": [(3, 2, {"event": "MeleeAttackStart"}), (2, 1, {"event": "MeleeAttackStart", "blend": 0.15})]}
        raw = agx_write.write({"name": "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\MeleeAttacks.agx", "default": 2,
                               "nodes": [{"kind": "sm", "name": "MeleeAttackCombo", "graph": sm},
                                         {"kind": "anim", "tag": "MeleeAttackPower_A"}, {"kind": "empty"}],
                               "links": [(2, 0, {"event": "MeleeAttackStart"}),
                                         (0, 1, {"event": "MeleeAttackPowerStart"}),
                                         (2, 1, {"event": "MeleeAttackPowerStart"})]})
        power = {"tags": {1: "MeleeAttack02", 2: "MeleeAttackPower_A"}, "attack_power": {1: 1, 2: 2, 3: 2},
                 "power_attack": {1: 2, 2: 1}, "power_power": {1: 2, 2: 1}, "inner_only": True}
        out, added = bfco_combo.build(raw, {1: 2, 2: 3, 3: 1}, None, power)
        root = agx_edit.load(out)
        top = agx_edit.transitions(root)
        combo, tp, idle = (agx_edit.state(root, "MeleeAttackCombo"), agx_edit.state(root, "MeleeAttackPower_A"),
                           2)
        self.assertIn((combo, tp, bfco_combo.OUTER_OFF, ""), top)
        self.assertNotIn((combo, tp, "MeleeAttackPowerStart", ""), top)
        self.assertIn((idle, tp, "MeleeAttackPowerStart", ""), top)                # standing: unchanged
        self.assertIn("MeleeAttackCombo =power=> MeleeAttackPower_A switched off (1)", added)
        inner = agx_edit.transitions(agx_edit.machine(root, "MeleeAttackCombo"))
        self.assertTrue(any(e == "MeleeAttackPowerStart" for _s, _t, e, _c in inner))     # default event
        out3, _ = bfco_combo.build(raw, {1: 2, 2: 3, 3: 1}, None, dict(power, event="S2S_ComboPower"))
        inner3 = agx_edit.transitions(agx_edit.machine(agx_edit.load(out3), "MeleeAttackCombo"))
        self.assertTrue(any(e == "S2S_ComboPower" for _s, _t, e, _c in inner3))
        self.assertFalse(any(e == "MeleeAttackPowerStart" for _s, _t, e, _c in inner3))
        out2, _ = bfco_combo.build(raw, {1: 2, 2: 3, 3: 1}, None, dict(power, inner_only=False))
        self.assertIn((combo, tp, "MeleeAttackPowerStart", ""), agx_edit.transitions(agx_edit.load(out2)))

    def test_chain_and_files(self):
        marks = {k: {"next_attack": n} for k, n in ((1, 2), (2, 3), (3, 9), (4, None))}
        self.assertEqual(bfco.chain(marks), {1: 2, 2: 3, 3: 1, 4: 1})    # unknown / missing -> back to 1
        mco = {k: {"next_attack": None} for k in (1, 2, 3)}
        self.assertEqual(bfco.chain(mco), {1: 2, 2: 3, 3: 1})            # MCO: in order, last back to 1
        g = bfco.attack_files(["mco_attack1.hkx", "mco_attack2.hkx", "mco_powerattack1.hkx"])
        self.assertEqual((g["attack"], g["power"]), ({1: "mco_attack1.hkx", 2: "mco_attack2.hkx"},
                                                     {1: "mco_powerattack1.hkx"}))
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
        whole = agx_edit.load(out)
        uids = [n.findtext("user_id") for n in whole.iter("node")]
        for k in (4, 5):                                                  # copies get file-wide unique user_ids
            uid = nodes[idx[k]].findtext("user_id")
            self.assertEqual(uids.count(uid), 1, (k, uid))
        two, _ = bfco_combo.build(raw, {1: 2, 2: 1})                      # a two-attack set
        g2 = agx_edit.machine(agx_edit.load(two), "MeleeAttackCombo")
        i1, i2 = agx_edit.state(g2, "BFCO_Attack1"), agx_edit.state(g2, "BFCO_Attack2")
        self.assertIn((i2, i1, "MeleeAttackStart", ""), agx_edit.transitions(g2))
        self.assertEqual(agx_edit.state(g2, "MeleeAttack_C"), 0)        # left as it was, unreachable
        gap, _ = bfco_combo.build(raw, {1: 2, 2: 4, 4: 5, 5: 1})                # attack 3 unreachable: no slot
        g4 = agx_edit.machine(agx_edit.load(gap), "MeleeAttackCombo")
        self.assertEqual(agx_edit.state(g4, "BFCO_Attack4"), agx_edit.state(g, "BFCO_Attack3"))   # on vanilla C
        with self.assertRaises(agx_edit.AgxEditError):
            agx_edit.state(g4, "BFCO_Attack3")
        self.assertIn((agx_edit.state(g4, "BFCO_Attack5"), agx_edit.state(g4, "BFCO_Attack1"), "MeleeAttackStart",
                       ""), agx_edit.transitions(g4))
        named, added = bfco_combo.build(raw, {1: 2, 2: 3, 3: 4, 4: 1}, {1: "MeleeAttack_A", 4: "MeleeAttack_D"})
        g3 = agx_edit.machine(agx_edit.load(named), "MeleeAttackCombo")
        a, d = agx_edit.state(g3, "MeleeAttack_A"), agx_edit.state(g3, "MeleeAttack_D")
        self.assertIn((d, a, "MeleeAttackStart", ""), agx_edit.transitions(g3))
        self.assertIn("MeleeAttack_D -> MeleeAttack_A", added)


if __name__ == "__main__":
    unittest.main()
