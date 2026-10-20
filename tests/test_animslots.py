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
            replace, tags, report = bfco_pack.plan(moveset, ["melee/w"], os.path.join(d, "x"))
        self.assertEqual(tags, {1: "MeleeAttack_A", 2: "MeleeAttack_B", 3: "MeleeAttack_C", 4: "MeleeAttack_D"})
        self.assertTrue(any(r.endswith("sneak_meleeattack_a.afx::tag:MeleeAttack_D") for r in replace))
        self.assertTrue(any("BFCO_PowerAttackA.hkx::" in r and r.endswith("meleeattackpower_a.afx") for r in replace))
        self.assertFalse(any("Sprint" in r for r in replace))                       # no sprint slot in the folder
        self.assertEqual(report["melee/w"][4], ("sneak_meleeattack_a", "MeleeAttack_D"))
        self.assertEqual(bfco_pack.pick(["A.hkx", "BFCO_SprintAttack.hkx"], "bfco_sprintattack"), "BFCO_SprintAttack.hkx")


if __name__ == "__main__":
    unittest.main()
