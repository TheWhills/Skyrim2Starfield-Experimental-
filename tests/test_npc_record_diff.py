"""npc_record_diff: subrecords of one NPC compared across two plugins (Delphine's Riverwood copy vs her face-test NPC)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
import npc_record_diff as D  # noqa: E402


class DiffTests(unittest.TestCase):
    def test_kinds(self):
        a = [(b"EDID", b"X\0"), (b"MWGT", struct.pack("<3f", 0.2, 0.5, 0.3)), (b"MRSV", b"\1\2")]
        b = [(b"EDID", b"X\0"), (b"MWGT", struct.pack("<3f", 0, 0, 0)), (b"FULL", b"N\0")]
        rows = {s: (k, t) for s, k, t in D.diff(a, b)}
        self.assertEqual(set(rows), {b"MWGT", b"MRSV", b"FULL"})
        self.assertEqual(rows[b"MRSV"][0], "only A")
        self.assertEqual(rows[b"FULL"][0], "only B")
        self.assertEqual(rows[b"MWGT"][0], "differs")
        self.assertIn("[0.2, 0.5, 0.3]", rows[b"MWGT"][1])
        self.assertIn("floats [0, 0.7", D.show(b"SNAM", struct.pack("<3f", 0, 0.7, 0) + bytes(4)))

    def test_outline(self):
        subs = [(b"EDID", b"Race\0"), (b"SRAC", struct.pack("<I", 0x347D))] + [(b"SAPT", b"x\0")] * 9
        lines = D.outline(subs)
        self.assertEqual(lines[:2], ["EDID: 'Race'", "SRAC: 0000347D"])
        self.assertEqual(lines[2], "SAPT x9: 'x' ... 'x'")

    def test_find(self):
        recs = {"human_male_beard_full": (1, []), "human_male_hair_buzz": (2, []), "beard_short": (3, [])}
        self.assertEqual(D.find(recs, "Beard"), ["beard_short", "human_male_beard_full"])
        self.assertEqual(D.find(recs, "nothing"), [])


if __name__ == "__main__":
    unittest.main()


class AllAndNamesTests(unittest.TestCase):
    def test_every_value_and_names(self):
        """2026-11-11: which teeth part the player gets: every PNAM value, with head part names."""
        a = [(b"PNAM", struct.pack("<I", 1)), (b"PNAM", struct.pack("<I", 2))]
        b = [(b"PNAM", struct.pack("<I", 1)), (b"PNAM", struct.pack("<I", 3))]
        (_s, kind, text), = D.diff(a, b, every=True)
        self.assertEqual(text, "A 2x [00000001, 00000002] | B 2x [00000001, 00000003]")
        self.assertEqual(D.named(text, {3: "Human_Male_Teeth"}),
                         "A 2x [00000001, 00000002] | B 2x [00000001, 00000003 (Human_Male_Teeth)]")
        self.assertEqual(D.diff(a, b)[0][2], "A 2x 00000001 | B 2x 00000001")
