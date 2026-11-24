"""scripts/re/exe_xrefs.py (2026-11-24): string references and their functions in a PE32+ (synthetic image)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "re"))

import exe_xrefs as X  # noqa: E402

TEXT_VA, RDATA_VA, PDATA_VA = 0x1000, 0x2000, 0x3000
TEXT_RAW, RDATA_RAW, PDATA_RAW = 0x400, 0x600, 0x800


def image():
    """Two functions: F1 at 0x1000 loads 'terrain_flatinner.dds' (lea rcx, [rip+d]) and calls F2; F2 at 0x1040
    loads 'fDensity:Grass'."""
    rdata = bytearray(0x200)
    s1 = b"terrain_flatinner.dds\0"
    s2 = b"fDensity:Grass\0"
    rdata[0:len(s1)] = s1
    rdata[0x40:0x40 + len(s2)] = s2
    text = bytearray(b"\xCC" * 0x200)

    def lea(at, target):                       # 48 8D 0D disp32 at rva at
        d = target - (at + 7)
        return b"\x48\x8D\x0D" + struct.pack("<i", d)
    f1 = TEXT_VA
    text[0:7] = lea(f1, RDATA_VA)
    call_at = f1 + 7
    text[7:12] = b"\xE8" + struct.pack("<i", (TEXT_VA + 0x40) - (call_at + 5))
    text[12] = 0xC3
    f2 = TEXT_VA + 0x40
    text[0x40:0x47] = lea(f2, RDATA_VA + 0x40)
    text[0x47] = 0xC3
    pdata = struct.pack("<3I", f1, f1 + 0x20, 0) + struct.pack("<3I", f2, f2 + 0x10, 0)
    pdata = pdata + bytes(0x200 - len(pdata))

    pe = 0x80
    head = bytearray(0x400)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, pe)
    head[pe:pe + 4] = b"PE\0\0"
    opt_size = 112 + 16 * 8
    struct.pack_into("<HH", head, pe + 4, 0x8664, 3)
    struct.pack_into("<H", head, pe + 20, opt_size)
    opt = pe + 24
    struct.pack_into("<H", head, opt, 0x20B)
    struct.pack_into("<Q", head, opt + 24, 0x140000000)
    struct.pack_into("<I", head, opt + 108, 16)
    struct.pack_into("<II", head, opt + 112 + 8 * 3, PDATA_VA, 24)
    sec = opt + opt_size
    for i, (name, va, raw, ch) in enumerate([(b".text", TEXT_VA, TEXT_RAW, 0x60000020),
                                              (b".rdata", RDATA_VA, RDATA_RAW, 0x40000040),
                                              (b".pdata", PDATA_VA, PDATA_RAW, 0x40000040)]):
        o = sec + 40 * i
        head[o:o + 8] = name.ljust(8, b"\0")
        struct.pack_into("<IIII", head, o + 8, 0x200, va, 0x200, raw)
        struct.pack_into("<I", head, o + 36, ch)
    return bytes(head) + bytes(text) + bytes(rdata) + pdata


class XrefTest(unittest.TestCase):
    def test_report(self):
        pe = X.PE(image())
        self.assertEqual(len(pe.functions()), 2)
        want = X.strings(pe, "flatinner")
        self.assertEqual(list(want.values()), [("terrain_flatinner.dds", "a")])
        self.assertEqual(X.rip_refs(pe, want), [(TEXT_VA + 3, RDATA_VA)])
        self.assertEqual(X.calls_in(pe, TEXT_VA, TEXT_VA + 0x20), [TEXT_VA + 0x40])
        text = "\n".join(X.report(pe, "flatinner"))
        self.assertIn("1 references in 1 functions", text)
        self.assertIn("function 0x140001000 (32 bytes): matches 'terrain_flatinner.dds'", text)
        self.assertIn("calls 0x140001040: 'fDensity:Grass'", text)

    def test_not_pe(self):
        with self.assertRaises(ValueError):
            X.PE(b"XX" + bytes(100))


if __name__ == "__main__":
    unittest.main()
