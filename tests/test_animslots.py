"""fo4sf.animslots and scripts/armor/bfco_pack.py's planning on synthetic folders (no game or mod files)."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import animslots as A  # noqa: E402
import bfco_pack  # noqa: E402


class SlotTests(unittest.TestCase):
    def test_allocate(self):
        have = ["meleeattack_a", "meleeattack_b", "meleeattack_c", "sneak_meleeattack_b", "zerog_meleeattack_a"]
        s = A.allocate(5, have)
        self.assertEqual(s[1], ("meleeattack_a", "MeleeAttack_A", False))
        self.assertEqual(s[3], ("meleeattack_c", "MeleeAttack_C", False))
        self.assertEqual(s[4], ("sneak_meleeattack_b", "MeleeAttack_D", True))     # first host present
        self.assertEqual(s[5], ("zerog_meleeattack_a", "MeleeAttack_E", True))
        with self.assertRaises(A.SlotError):
            A.allocate(6, have)                                                     # only two hosts
        with self.assertRaises(A.SlotError):
            A.allocate(2, ["meleeattack_b"])                                        # combo file missing
        self.assertEqual(len(A.allocate(2, have)), 2)

    def test_plan_from_folders(self):
        with tempfile.TemporaryDirectory() as d:
            moveset = os.path.join(d, "moveset")
            os.makedirs(moveset)
            for n in ("BFCO_Attack1.hkx", "BFCO_Attack2.HKX", "BFCO_Attack3.hkx", "BFCO_Attack4.hkx",
                      "BFCO_PowerAttack1.hkx", "BFCO_PowerAttackA.hkx", "BFCO_SprintAttack.hkx", "config.json"):
                open(os.path.join(moveset, n), "wb").close()
            folder = os.path.join(d, "x", "meshes", "actors", "human", "animations", "melee", "w")
            os.makedirs(folder)
            for stem in ("meleeattack_a", "meleeattack_b", "meleeattack_c", "sneak_meleeattack_a",
                         "meleeattackpower_a"):
                open(os.path.join(folder, stem + ".afx"), "wb").close()
            replace, tags, report, ptags = bfco_pack.plan(moveset, ["melee/w"], os.path.join(d, "x"))
        self.assertEqual(ptags, {})                                                  # no power routing here
        self.assertEqual(tags, {1: "MeleeAttack_A", 2: "MeleeAttack_B", 3: "MeleeAttack_C", 4: "MeleeAttack_D"})
        self.assertTrue(any(r.endswith("sneak_meleeattack_a.afx::tag:MeleeAttack_D") for r in replace))
        self.assertTrue(any("BFCO_PowerAttackA.hkx::" in r and r.endswith("meleeattackpower_a.afx") for r in replace))
        self.assertFalse(any("Sprint" in r for r in replace))                       # no sprint slot in the folder
        self.assertEqual(report["melee/w"][4], ("sneak_meleeattack_a", "MeleeAttack_D"))
        self.assertEqual(bfco_pack.pick(["A.hkx", "BFCO_SprintAttack.hkx"], "bfco_sprintattack"), "BFCO_SprintAttack.hkx")

    def test_plan_gives_power_attacks_the_spare_slots(self):
        with tempfile.TemporaryDirectory() as d:
            moveset = os.path.join(d, "moveset")
            os.makedirs(moveset)
            for n in ["mco_attack%d.hkx" % k for k in (1, 2, 3, 4, 5)] + ["mco_powerattack%d.hkx" % k for k in (1, 2, 3)]:
                open(os.path.join(moveset, n), "wb").close()
            folder = os.path.join(d, "x", "meshes", "actors", "human", "animations", "melee", "w")
            os.makedirs(folder)
            for stem in ("meleeattack_a", "meleeattack_b", "meleeattack_c", "sneak_meleeattack_a",
                         "sneak_meleeattack_b", "meleeattackpower_a"):
                open(os.path.join(folder, stem + ".afx"), "wb").close()
            routes = {"attack": {1: 2, 2: 3, 3: 4, 4: 1}, "attack_power": {1: 2, 2: 3, 3: 1, 4: 1},
                      "power_attack": {1: 1, 2: 3, 3: 4}, "power_power": {1: 2, 2: 3, 3: 1}, "powers": [1, 2, 3]}
            orig = bfco_pack.bfco_combo.routes_of
            bfco_pack.bfco_combo.routes_of = lambda folder: routes
            try:
                replace, tags, report, ptags = bfco_pack.plan(moveset, ["melee/w"], os.path.join(d, "x"))
            finally:
                bfco_pack.bfco_combo.routes_of = orig
        self.assertEqual(sorted(tags), [1, 2, 3, 4])                                 # attack 5 unreachable: no slot
        self.assertEqual(tags[4], "MeleeAttack_D")
        self.assertEqual(ptags, {1: "MeleeAttackPower_A", 2: "MeleeAttack_E"})      # one spare host left: power 2
        self.assertTrue(any("mco_powerattack2.hkx::" in r and r.endswith("sneak_meleeattack_b.afx::tag:MeleeAttack_E")
                            for r in replace))
        self.assertFalse(any("mco_powerattack3.hkx" in r for r in replace))         # no room: falls back to power 1


if __name__ == "__main__":
    unittest.main()
