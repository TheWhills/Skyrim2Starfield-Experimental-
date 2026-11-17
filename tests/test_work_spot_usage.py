"""scripts/npc/work_spot_usage.py: XLKR pairs and a package's form inputs (synthetic)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
import work_spot_usage as W  # noqa: E402


class WorkSpotUsageTest(unittest.TestCase):
    def test_linked_refs(self):
        subs = [(b"XLKR", struct.pack("<II", 0x10, 0x20)), (b"NAME", b"\0\0\0\0"), (b"XLKR", struct.pack("<II", 0, 0x30))]
        self.assertEqual(W.linked_refs(subs), [(0x10, 0x20), (0, 0x30)])

    def test_form_values(self):
        p = {"inputs": [{"type": "Location", "value": {"is_form": True, "value": 0x55}},
                        {"type": "Bool", "value": True},
                        {"type": "Target", "value": {"is_form": False, "value": 7}}]}
        self.assertEqual(W.form_values(p), [(0, "Location", 0x55)])


if __name__ == "__main__":
    unittest.main()
