"""scripts/interior/navmesh_survey.py on a synthetic Starfield.esm with navmeshes nested in an interior cell."""
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import skyrimnavmesh as N  # noqa: E402
import navmesh_survey as S  # noqa: E402
import test_skyrimnavmesh as T  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402


def sf_nvnm(height, unknown, vunk):
    sf = N.to_starfield(N.parse_skyrim(T.skyrim_nvnm()), {"triangle_height": height, "triangle_unknown": unknown,
                                                          "vertex_unknown": vunk, "tail": (3, 0)})
    return N.serialize_starfield(sf, 1 / 70.0)


class SurveyTests(unittest.TestCase):
    def test_survey_and_defaults(self):
        tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 0, 0x800))])
        cell = rec(b"CELL", 0x500, [(b"EDID", b"TestCell\0"), (b"DATA", b"\x01\x00")])
        navs = [rec(b"NAVM", 0x600 + i, [(b"NVNM", sf_nvnm(1.8, 4, 0))]) for i in range(3)]
        navs.append(rec(b"NAVM", 0x610, [(b"NVNM", sf_nvnm(2.2, 4, 0))]))
        cells = grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [cell, grup(0x500, 6, [grup(0x500, 9, navs)])])])])
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Starfield.esm")
            with open(esm, "wb") as fh:
                fh.write(tes4 + cells)
            out = os.path.join(d, "out")
            self.assertEqual(S.main(["--esm", esm, "--out", out, "--max", "3"]), 0)
            with open(os.path.join(out, "navmesh_defaults.json")) as fh:
                defaults = json.load(fh)
            with open(os.path.join(out, "navmesh_survey.json")) as fh:
                report = json.load(fh)
        self.assertEqual(report["navmeshes"], 3)                            # --max respected
        self.assertEqual(report["errors"], [])
        self.assertAlmostEqual(defaults["triangle_height"], 1.8, places=5)
        self.assertEqual((defaults["triangle_unknown"], defaults["vertex_unknown"], defaults["tail"]), (4, 0, [3, 0]))
        self.assertIn("0x400", report["triangle_height"]["median_by_flag"])  # the door triangle's height
        # the defaults feed the translation
        sf = N.to_starfield(N.parse_skyrim(T.skyrim_nvnm()), defaults)
        self.assertEqual((sf["triangles"][0]["unknown"], sf["tail"]), (4, (3, 0)))


if __name__ == "__main__":
    unittest.main()
