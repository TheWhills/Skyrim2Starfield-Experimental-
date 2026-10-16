"""scripts/terrain/survey_ltex.py on fake terrain archives and a fake Starfield.esm."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from skyrim_fixtures import starfield_meshes_ba2  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402


def btd(ltex):
    return b"BTDB" + bytes(0x24) + struct.pack(f"<I{len(ltex)}I", len(ltex), *ltex) + bytes(64)


class SurveyTests(unittest.TestCase):
    def test_counts_and_picks(self):
        import survey_ltex
        with tempfile.TemporaryDirectory() as tmp:
            starfield_meshes_ba2(os.path.join(tmp, "Starfield - Terrain01.ba2"),
                                 {"terrain/a.btd": btd([0x10, 0x20]), "terrain/b.btd": btd([0x10]),
                                  "terrain/readme.txt": b"x"})
            esm = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.0, 0, 0x800))])
            esm += grup(b"LTEX", 0, [rec(b"LTEX", 0x10, [(b"EDID", b"LDirtGood\0"), (b"BNAM", b"x.mat\0")]),
                                     rec(b"LTEX", 0x20, [(b"EDID", b"LGrassUsed\0")]),
                                     rec(b"LTEX", 0x30, [(b"EDID", b"LSnowTestUnused\0")])])
            open(os.path.join(tmp, "Starfield.esm"), "wb").write(esm)
            mp = os.path.join(tmp, "ltex_mapping.json")
            json.dump({"categories": {"snow": {"edid": "LSnowTestUnused"}, "dirt": {"edid": "LDirtGood"}},
                       "coverage": {"LDirtGood": 0.9}}, open(mp, "w"))
            out = os.path.join(tmp, "s.json")
            with contextlib.redirect_stdout(io.StringIO()) as so:
                survey_ltex.main(["--sf-data", tmp, "--mapping", mp, "--out", out])
            doc = json.load(open(out))
            self.assertEqual(doc["btds"], 2)
            self.assertEqual([(u["edid"], u["btds"], u["first"]) for u in doc["used"]],
                             [("LDirtGood", 2, 2), ("LGrassUsed", 1, 0)])
            self.assertEqual(doc["unused"], ["LSnowTestUnused"])
            self.assertEqual(doc["picks"]["snow"]["btds"], 0)
            self.assertIn("BNAM=x.mat", so.getvalue())



class MappingUsageTests(unittest.TestCase):
    def test_vanilla_used_pick_wins_and_unused_falls_back(self):
        from fo4sf import landtex
        sf = {"LDirtFootprints01": landtex.PLAIN_GROUND, "LGrassAlpha_Test": 0x50, "LGrassMeadow": 0x51,
              "LSnowDebug": 0x60}
        sky = {0x900: {"edid": "TundraGrass01", "diffuse": "landscape\\grass.dds"},
               0x901: {"edid": "Snow01", "diffuse": "landscape\\snow.dds"}}
        old = landtex.build_mapping(sky, sf)
        self.assertEqual(old["categories"]["grass"]["edid"], "LGrassAlpha_Test")          # alphabetical
        new = landtex.build_mapping(sky, sf, usage={0x51: 30, 0x50: 0, landtex.PLAIN_GROUND: 900})
        self.assertEqual(new["categories"]["grass"]["edid"], "LGrassMeadow")
        self.assertEqual(new["categories"]["grass"]["vanilla_btds"], 30)
        self.assertEqual(new["categories"]["snow"]["edid"], "LDirtFootprints01")          # unused snow: plain ground
        self.assertEqual(new["skyrim"][0x901]["starfield"], "LDirtFootprints01")


if __name__ == "__main__":
    unittest.main()
