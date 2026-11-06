"""scripts/armor/slot_probe.py: BO64 slot bits and addon rows (synthetic)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import slot_probe as P  # noqa: E402
from fo4sf import sfplugin  # noqa: E402


class SlotTests(unittest.TestCase):
    def test_slots_and_rows(self):
        self.assertEqual(P.slots(((1 << 3) | (1 << 33)).to_bytes(8, "little")), [3, 33])
        self.assertEqual(P.slots(b""), [])
        subs = [(b"EDID", sfplugin.zs("NakedTorsoAA")), (b"BO64", (1 << 2).to_bytes(8, "little")),
                (b"MOD2", sfplugin.zs("Clothes\\Naked\\Naked_M.nif"))]
        row = P.addon_row(0x1234, subs)
        self.assertEqual((row["edid"], row["slots"], row["male"]), ("NakedTorsoAA", [2], "Clothes\\Naked\\Naked_M.nif"))
        armo = [(b"MODL", struct.pack("<I", 0x1234)), (b"MODL", struct.pack("<I", 0x9999))]
        self.assertEqual([r["form"] for r in P.armor_addons(armo, {0x1234: subs})], ["00001234"])


if __name__ == "__main__":
    unittest.main()
