"""wwise_probe: Wwise short ids and .bnk parsing (2026-11-20, how an animation's sound name reaches a bank)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

import wwise_probe as W  # noqa: E402


class WwiseTests(unittest.TestCase):
    def test_fnv1(self):
        self.assertEqual(W.fnv1_32("a"), 0x050C5D7E)            # FNV-1 32 test vector
        self.assertEqual(W.fnv1_32("A"), W.fnv1_32("a"))        # Wwise hashes the lower-case name
        self.assertEqual(W.fnv1_32(""), 2166136261)

    def test_parse_bank(self):
        bkhd = struct.pack("<II", 150, 1234) + bytes(8)
        ev = struct.pack("<BII", 4, 9, 777) + bytes(5)                     # event 777 (size counts the id)
        snd = struct.pack("<BII", 2, 6, 55) + bytes(2)                      # a sound object
        hirc = struct.pack("<I", 2) + ev + snd
        b = b"BKHD" + struct.pack("<I", len(bkhd)) + bkhd + b"HIRC" + struct.pack("<I", len(hirc)) + hirc
        info = W.parse_bank(b)
        self.assertEqual((info["version"], info["bank_id"]), (150, 1234))
        self.assertEqual(info["chunks"], ["BKHD", "HIRC"])
        self.assertEqual(info["events"], [777])
        self.assertEqual(dict(info["objects"]), {4: 1, 2: 1})


if __name__ == "__main__":
    unittest.main()
