"""scripts/armor/child_slot_test.py: test armors copied from Starfield's child outfit, one slot / model each."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

from fo4sf import sfplugin  # noqa: E402
import child_slot_test as C  # noqa: E402

z = sfplugin.zs
H = bytes(24)


class TestRecords(unittest.TestCase):
    def test_one_slot_one_model_each(self):
        aa = [(b"EDID", z("AA_Clothes_Child_CoraCoe_NOTPLAYABLE")), (b"BO64", (1 << 3).to_bytes(8, "little")),
              (b"RNAM", struct.pack("<I", 0x2AABCD)), (b"MOD2", z("Clothes\\cora.nif")), (b"FLLD", b"\1\0\0\0")]
        ao = [(b"EDID", z("Clothes_Child_CoraCoe_NOTPLAYABLE")), (b"FULL", z("Cora")),
              (b"BO64", (1 << 3).to_bytes(8, "little")), (b"MODL", struct.pack("<I", 0x4A0C))]
        out = C.test_records([(b"ARMA", H, aa, 0x4A0C), (b"ARMO", H, ao, 0x22669F)])
        by = {sfplugin.edid(s): (t, dict(s), f) for t, _h, s, f in out}
        self.assertEqual(len(out), 8)
        v7 = by["S2S_ChildTest_VanillaSlot7_AA"][1]
        self.assertEqual(v7[b"BO64"], (1 << 7).to_bytes(8, "little"))
        self.assertEqual(v7[b"MOD2"], z("Clothes\\cora.nif"))                 # its own mesh
        ours = by["S2S_ChildTest_OursSlot3_AA"][1]
        self.assertEqual((ours[b"MOD2"], ours[b"BO64"]), (z(C.OURS_SHOES), (1 << 3).to_bytes(8, "little")))
        armo = by["S2S_ChildTest_OursSlot3"]
        self.assertEqual(armo[1][b"MODL"], struct.pack("<I", by["S2S_ChildTest_OursSlot3_AA"][2]))
        self.assertEqual(armo[2] >> 24, 1)


if __name__ == "__main__":
    unittest.main()
