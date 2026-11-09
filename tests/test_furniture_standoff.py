"""scripts/interior/furniture_standoff.py on synthetic plugins: a bartender marker facing a counter (Starfield: float
bounds in metres; Skyrim: int16 bounds in units), the counter turned 90 degrees, a wall too tall and a stool too low
ignored, a marker facing away hits nothing."""
import contextlib
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_fo4land import grup, rec  # noqa: E402
import furniture_standoff as S  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731


def ref(fid, base, pos, rz=0.0):
    return rec(b"REFR", fid, [(b"NAME", struct.pack("<I", base)), (b"DATA", struct.pack("<6f", *pos, 0, 0, rz))])


def plugin(path, starfield, u):
    ob = (lambda lo, hi: struct.pack("<6f", *lo, *hi)) if starfield else \
        (lambda lo, hi: struct.pack("<6h", *[round(v * u) for v in lo + hi]))
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.0, 0, 0x800))])
    counter = rec(b"STAT", 0x10, [(b"EDID", Z("BarCounter")), (b"OBND", ob([-1.0, -0.3, 0.0], [1.0, 0.3, 1.1]))])
    wall = rec(b"STAT", 0x11, [(b"EDID", Z("Wall")), (b"OBND", ob([-3.0, -0.1, 0.0], [3.0, 0.1, 4.0]))])
    stool = rec(b"STAT", 0x12, [(b"EDID", Z("Stool")), (b"OBND", ob([-0.2, -0.2, 0.0], [0.2, 0.2, 0.5]))])
    mark = rec(b"FURN", 0x20, [(b"EDID", Z("Bartender"))])
    # marker at the origin facing +Y; the counter's near face 0.45 m ahead (centre 0.75, half depth 0.3), turned 90
    # degrees so its long side faces the marker: local x (2 m) becomes the world's y extent -> use depth along local x
    refs = [ref(0x100, 0x20, (0, 0, 0)), ref(0x101, 0x10, (0, 0.75 * u, 0)), ref(0x102, 0x11, (0, 0.2 * u, 0)),
            ref(0x103, 0x12, (0, 0.1 * u, 0)),
            ref(0x110, 0x20, (10 * u, 0, 0), math.pi / 2), ref(0x111, 0x10, (10 * u + 1.3 * u, 0, 0), math.pi / 2),
            ref(0x120, 0x20, (30 * u, 0, 0), math.pi)]
    cell = rec(b"CELL", 0x500, [(b"EDID", Z("Inn"))])
    with open(path, "wb") as fh:
        fh.write(tes4 + grup(b"STAT", 0, [counter, wall, stool]) + grup(b"FURN", 0, [mark])
                 + grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [cell, grup(0x500, 6, [grup(0x500, 8, refs)])])])]))


class StandoffTests(unittest.TestCase):
    def run_one(self, starfield, u):
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "x.esm")
            plugin(esm, starfield, u)
            out = os.path.join(d, "o.json")
            args = ["--esm", esm, "--base", "Bartender", "--out", out] + ([] if starfield else ["--units", str(u)])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(S.main(args), 0)
            with open(out) as fh:
                r = json.load(fh)["Bartender"]
            rows = {x["marker"]: x for x in r["refs"]}
            a = rows["00000100"]
            # the wall (4 m tall) is ignored, the stool (0.5 m) too: the counter's face, 0.45 m ahead, top 1.1 m
            self.assertEqual((a["base"], a["standoff_m"], a["top_m"]), ("BarCounter", 0.45, 1.1))
            b = rows["00000110"]                    # facing +X (90 degrees clockwise), counter turned the same way
            self.assertEqual((b["base"], b["standoff_m"]), ("BarCounter", 1.0))
            self.assertNotIn("standoff_m", rows["00000120"])          # facing away (-Y): nothing in front
            self.assertEqual(r["summary"]["with_hit"], 2)

    def test_starfield(self):
        self.run_one(True, 1.0)

    def test_skyrim(self):
        self.run_one(False, 70.0)


if __name__ == "__main__":
    unittest.main()
