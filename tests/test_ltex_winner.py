"""scripts/terrain/ltex_winner.py (2026-11-22): which plugin wins each overridden ground LTEX record."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from test_landtex import grup, rec  # noqa: E402
import ltex_winner as W  # noqa: E402


def plugin(path, masters, ltex):
    """ltex: [(raw form id, edid, bnam)]"""
    fields = [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))]
    for m in masters:
        fields += [(b"MAST", m.encode() + b"\0"), (b"DATA", b"\0" * 8)]
    body = grup(b"LTEX", 0, [rec(b"LTEX", fid, [(b"EDID", e.encode() + b"\0"), (b"BNAM", b.encode() + b"\0")])
                             for fid, e, b in ltex])
    with open(path, "wb") as f:
        f.write(rec(b"TES4", 0, fields) + body)


class WinnerTest(unittest.TestCase):
    def test_lost_when_a_later_plugin_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, st = os.path.join(tmp, "Data"), os.path.join(tmp, "st")
            os.makedirs(data)
            os.makedirs(st)
            plugin(os.path.join(data, "Starfield.esm"), [], [(0x030138, "LRockSedCracked01", "Terrain\\Rock.mat"),
                                                             (0x19E83A, "LSandRipple01_Pale", "Terrain\\Sand.mat")])
            plugin(os.path.join(data, "Ours.esm"), ["Starfield.esm"],
                   [(0x030138, "LRockSedCracked01", "skyrim\\ground\\lrocks01norocks.mat"),
                    (0x19E83A, "LSandRipple01_Pale", "skyrim\\ground\\lreachgrass01.mat")])
            plugin(os.path.join(data, "Later.esm"), ["Starfield.esm", "Ours.esm"],
                   [(0x19E83A, "LSandRipple01_Pale", "Terrain\\Sand.mat")])
            pt = os.path.join(tmp, "Plugins.txt")
            with open(pt, "w") as f:
                f.write("# x\n*Ours.esm\n*Later.esm\nOff.esm\n")
            with open(os.path.join(st, "overlays_params.json"), "w") as f:
                json.dump({"ltex_overrides": [
                    {"form_id": "00030138", "skyrim": "LRocks01NoRocks", "material": "materials/skyrim/ground/lrocks01norocks.mat"},
                    {"form_id": "0019E83A", "skyrim": "LReachGrass01", "material": "materials/skyrim/ground/lreachgrass01.mat"}]}, f)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                W.main(["--sf-data", data, "--staging", st, "--plugins", pt])
        text = out.getvalue()
        self.assertIn("load order read: Starfield.esm, Ours.esm, Later.esm", text)
        self.assertIn("OK   00030138 Skyrim LRocks01NoRocks", text)
        self.assertIn("LOST 0019E83A Skyrim LReachGrass01", text)
        self.assertIn("1 of 2 overridden ground textures win with our material; 1 LOST", text)


if __name__ == "__main__":
    unittest.main()
