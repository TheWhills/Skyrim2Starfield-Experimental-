"""wem_info: RIFF header of a .wem (2026-11-20)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

import wem_info as W  # noqa: E402


class WemTests(unittest.TestCase):
    def test_header(self):
        fmt = struct.pack("<HHIIHH", 0xFFFF, 1, 48000, 12000, 0, 0) + bytes(2)
        data = b"RIFF" + struct.pack("<I", 0) + b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + \
            b"data" + struct.pack("<I", 4) + bytes(4)
        h = W.wem_header(data)
        self.assertEqual((h["codec"], h["channels"], h["sample_rate"]), ("Vorbis", 1, 48000))
        self.assertEqual(h["chunks"], ["fmt :18", "data:4"])
        self.assertEqual(W.wem_header(b"OggS")["chunks"], [])


if __name__ == "__main__":
    unittest.main()
