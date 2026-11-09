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
        self.assertIn("floats [0, 0.7", D.show(b"SNAM", struct.pack("<3f", 0, 0.7, 0)))


if __name__ == "__main__":
    unittest.main()
