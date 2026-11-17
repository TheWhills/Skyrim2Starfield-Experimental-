"""scripts/interior/furniture_record_probe.py: header flags and subrecord differences (synthetic)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
import furniture_record_probe as F  # noqa: E402


def hdr(flags):
    return b"FURN" + struct.pack("<II", 0, flags) + bytes(12)


class FurnitureRecordProbeTest(unittest.TestCase):
    def test_differences(self):
        ours = (hdr(0x10), [(b"EDID", b"a\0"), (b"KWDA", b"\1\0\0\0\2\0\0\0"), (b"OBND", b"x")])
        van = (hdr(0x800010), [(b"EDID", b"b\0"), (b"KWDA", b"\1\0\0\0"), (b"VMAD", b"v")])
        d = F.differences(ours, van)
        self.assertEqual(d[0], "flags: ours only -, vanilla only ['0x00800000']")
        self.assertIn("KWDA: differs (ours 8 / vanilla 4 bytes)", d)
        self.assertIn("OBND: ours only (1 bytes)", d)
        self.assertIn("VMAD: vanilla only (1 bytes)", d)
        self.assertEqual(F.flag_bits(0x5), ["0x00000001", "0x00000004"])


class SnamTest(unittest.TestCase):
    def test_snam_and_pairs(self):
        import struct
        import furniture_record_probe as P
        d = struct.pack("<4fIII", 0.0, -0.728, 0.0, 3.1416, 0, 0xF, 0xFFFFFFFF)
        (line,) = P.snam(d)
        self.assertIn("(0.000, -0.728, 0.000)", line)
        self.assertIn("entry 0xF", line)
        self.assertEqual(P.short2(struct.pack("<h", 180)), 180)
        self.assertIn(("S2S_Furn_CraftingBlackSmithForge", "NPCWelder"), P.PAIRS)


if __name__ == "__main__":
    unittest.main()
