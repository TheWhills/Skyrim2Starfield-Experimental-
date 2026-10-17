import contextlib
import io
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tools"))

import compare_worlds  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402


def plugin(worlds):
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
    items = []
    for fid, edid, extra in worlds:
        items.append(rec(b"WRLD", fid, [(b"EDID", edid.encode() + b"\0")] + extra))
        items.append(grup(struct.pack("<I", fid), 1, [rec(b"CELL", fid + 1, [(b"DATA", b"\x02")])]))
    return tes4 + grup(b"WRLD", 0, items)


class CompareWorlds(unittest.TestCase):
    def test_flags_fields_missing_from_ours(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "A.esm"), "wb").write(plugin([(0x10, "W1", [(b"HNAM", b"\x05"), (b"ZZZZ", b"\x01")]),
                                                              (0x20, "W2", [(b"HNAM", b"\x05"), (b"ZZZZ", b"\x02")]),
                                                              (0x30, "W3", [(b"HNAM", b"\x05"), (b"ZZZZ", b"\x03")])]))
            open(os.path.join(d, "B.esm"), "wb").write(plugin([(0x40, "Ours", [(b"HNAM", b"\x05")])]))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                compare_worlds.main(["--data", d, "A.esm::W1", "A.esm::W2", "B.esm::Ours"])
        out = buf.getvalue()
        self.assertIn("ZZZZ  <- every LOD world has it", out)
        self.assertIn("B.esm::Ours: -", out)
        self.assertIn("the same in every world: HNAM", out)
        self.assertIn("{'CELL': 1}", out)


if __name__ == "__main__":
    unittest.main()
