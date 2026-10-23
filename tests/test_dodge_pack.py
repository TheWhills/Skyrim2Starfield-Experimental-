"""scripts/armor/dodge_pack.py: the dodge descriptor (no game files) and the full-body dodge graph wiring."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import agx_edit, agx_write  # noqa: E402
import dodge_graph as D  # noqa: E402

try:
    import dodge_pack as P  # noqa: E402
except ImportError as e:                       # hkx_to_af needs numpy etc.
    P = None
    WHY = str(e)


SLIDE = (b"<root>\r\n\t<is_state>0</is_state>\r\n\t<tag>S2S_DodgeBack</tag>\r\n\t<filename>S2S_DodgeBack.af</filename>\r\n"
         b"\t<rampout>12</rampout>\r\n\t<events>\r\n\t\t<event><frame>0</frame><name>Slide</name><payload></payload></event>"
         b"\r\n\t</events>\r\n\t<variables>\r\n\t\t<variable><name>bIsSliding</name><start>0</start><end>25</end></variable>"
         b"\r\n\t</variables>\r\n</root>")


def attacks_graph() -> bytes:
    combo = {"nodes": [{"kind": "anim", "tag": "MeleeAttack_A"}, {"kind": "empty"}], "default": 1,
             "links": [(1, 0, {"event": "MeleeAttackStart"})]}
    return agx_write.write({"name": "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\MeleeAttacks.agx", "default": 2,
                            "nodes": [{"kind": "sm", "name": "MeleeAttackCombo", "graph": combo},
                                      {"kind": "anim", "tag": "MeleeAttackPower_A",
                                       "props": {"Speed Multiplier": "WeaponSpeedMult"}},
                                      {"kind": "empty"}],
                            "links": [(2, 0, {"event": "MeleeAttackStart"}), (2, 1, {"event": "MeleeAttackPowerStart"}),
                                      (1, 2, {"blend": 0.2}), (0, 2, {"blend": 0.2})]})


class DodgePackTests(unittest.TestCase):
    @unittest.skipIf(P is None, "dodge_pack imports hkx_to_af")
    def test_descriptor(self):
        out = P.dodge_descriptor(SLIDE).decode()
        self.assertIn("<tag>S2S_DodgeBack</tag>", out)
        self.assertIn("<rampout>12</rampout>", out)
        self.assertIn("<flag>Allow Rotation</flag>", out)
        self.assertNotIn("Slide", out.replace("S2S_Dodge", ""))
        self.assertNotIn("bIsSliding", out)
        self.assertIn("<filename>Sneak_MeleeAttack_B.af</filename>", P.dodge_descriptor(SLIDE, "Sneak_MeleeAttack_B.af").decode())
        self.assertEqual(sorted(P.FILES), sorted(P.CLIPS))
        self.assertTrue(all(f.startswith("Sneak_") for f in P.FILES.values()))      # never a plain graph tag

    def test_full_body_dodge_states(self):
        data, rep = D.build_attacks(attacks_graph())
        root = agx_edit.load(data)
        nodes = root.findall("node")
        t = agx_edit.transitions(root)
        idle = rep["idle"]
        self.assertEqual(idle, 2)
        states = [st["index"] for st in rep["states"].values()]
        for d, st in rep["states"].items():
            i, ev = st["index"], st["event"]
            self.assertEqual(ev, D.KNOWN_EVENTS[d])                    # names the graph knows
            self.assertEqual(agx_edit._rows(nodes[i])["TagName"], f"S2S_Dodge{d}")
            self.assertEqual(agx_edit._rows(nodes[i]).get("Speed Multiplier") or "", "")
            for src in [idle, 0, 1] + states:                             # idle, combo, power, every dodge
                self.assertIn((src, i, ev, ""), t)
            self.assertIn((i, idle, "", ""), t)                           # back to idle when the clip ends
        self.assertEqual(agx_edit._rows(nodes[1])["Speed Multiplier"], "WeaponSpeedMult")   # power attack untouched
        with self.assertRaises(agx_edit.AgxEditError):
            D.build_attacks(data)                                         # applying twice is refused

    def test_switch_lists(self):
        import copy
        base = agx_write.write({"name": "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\X.agx", "default": 0,
                                "nodes": [{"kind": "anim", "tag": "A"}], "links": []})
        root = agx_edit.load(base)
        sheet = root.find("node").find("property_sheet")
        row = copy.deepcopy(sheet.find("row"))                         # a Switch option row: name ... event list
        props = row.findall("prop")
        props[0].find("value").text = "Attacking"
        props[1].find("value").text = "MeleeAttackPowerStart,MeleeAttackSprintStart"
        sheet.append(row)
        raw = agx_edit.dump(root, base)
        out, n = D.add_switch_events(raw, ["MeleeAttack01", "MeleeAttack02"])
        self.assertEqual(n, 1)
        self.assertIn(b"MeleeAttackPowerStart,MeleeAttackSprintStart,MeleeAttack01,MeleeAttack02", out)
        with self.assertRaises(agx_edit.AgxEditError):
            D.add_switch_events(agx_write.write({"name": "X", "default": 0, "nodes": [{"kind": "empty"}],
                                                 "links": []}), ["MeleeAttack01"])


if __name__ == "__main__":
    unittest.main()
