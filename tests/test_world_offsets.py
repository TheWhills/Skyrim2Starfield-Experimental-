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

import world_offsets as wo  # noqa: E402
from fo4sf import fo4land  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402


def plugin(cells_xy, extra=()):
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
    cells = []
    for i, (x, y) in enumerate(cells_xy):
        cells.append(rec(b"CELL", 0x100 + i, [(b"XCLC", struct.pack("<iiI", x, y, 0))]))
    kids = grup(struct.pack("<I", 0x10), 1, [rec(b"CELL", 0x20, [(b"DATA", b"\x02")]),
                                             grup(b"\0\0\0\0", 4, [grup(b"\0\0\0\0", 5, cells)])])
    w = rec(b"WRLD", 0x10, [(b"EDID", b"W\0"), (b"NAM0", struct.pack("<2f", -200, -100)),
                            (b"NAM9", struct.pack("<2f", 150, 50)), (b"HNAM", b"\x05"), *extra])
    return tes4 + grup(b"WRLD", 0, [w, kids])


class WorldOffsets(unittest.TestCase):
    def test_verify_then_write(self):
        xy = [(-2, -1), (0, 0), (1, 0), (-1, -1)]
        with tempfile.TemporaryDirectory() as d:
            # a "vanilla" world built with the rule "relative to the WRLD record, x fastest, size with header"
            p = os.path.join(d, "V.esm")
            open(p, "wb").write(plugin(xy))
            wo.write(p, "W", ("WRLD record", True, True), log=lambda *a: None)
            with fo4land.Plugin(p) as pl, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(wo.verify(pl.buf, pl.body, "W"), ("WRLD record", True, True))
            ours = os.path.join(d, "O.esm")
            open(ours, "wb").write(plugin(xy[:2]))
            wo.write(ours, "W", ("WRLD record", True, True), log=lambda *a: None)
            with fo4land.Plugin(ours) as pl:
                _t, woff, fields, _k, cells = wo.find(pl.buf, pl.body, "W")
                f = dict(fields)
                vals = struct.unpack(f"<{len(f[b'OFST']) // 4}I", f[b"OFST"])
                self.assertEqual(len(vals), 4 * 2)                       # x -2..1, y -1..0
                self.assertEqual(vals[2 + 4], cells[(0, 0)][0] - woff)   # (0, 0): row 1, column 2
                self.assertEqual(sum(1 for v in vals if v), 2)
                self.assertEqual([s for s, _d in fields][-3:], [b"HNAM", b"OFST", b"CLSZ"])
                # the plugin still parses: every cell found again
                self.assertEqual(set(cells), set(xy[:2]))


if __name__ == "__main__":
    unittest.main()
