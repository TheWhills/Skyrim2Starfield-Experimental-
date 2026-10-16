"""ba2.Ba2.read on a version-3 DX10 archive with an LZ4 chunk (Starfield's texture archives)."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import ba2, textures  # noqa: E402


class Lz4TextureTests(unittest.TestCase):
    def test_reads_lz4_chunk(self):
        import lz4.block
        w = h = 8
        pixels = bytes(range(256)) * (w * h * 4 // 256)
        packed = lz4.block.compress(pixels, store_size=False)
        name = b"textures\\x.dds"
        head = 24 + 12
        entry_off = head
        data_off = entry_off + 24 + 24
        name_off = data_off + len(packed)
        out = struct.pack("<4sI4sIQ", b"BTDX", 3, b"DX10", 1, name_off) + bytes(8) + struct.pack("<I", 3)
        out += struct.pack("<I4sIBBHHHBBBB", 0, b"dds\0", 0, 0, 1, 24, h, w, 1, 28, 0, 0)
        out += struct.pack("<QIIHHI", data_off, len(packed), len(pixels), 0, 0, 0xBAADF00D)
        out += packed + struct.pack("<H", len(name)) + name
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "Starfield - Textures01.ba2")
            open(p, "wb").write(out)
            data = ba2.Ba2(p).read("textures/x.dds")
        hd = textures.read_dds_header(data)
        self.assertEqual((hd["width"], hd["height"], hd["dxgi"]), (8, 8, 28))
        self.assertEqual(data[hd["data_offset"]:], pixels)


if __name__ == "__main__":
    unittest.main()
