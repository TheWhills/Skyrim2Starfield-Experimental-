"""scripts/terrain/set_planet_latlon.py on a synthetic planet plugin (no game files)."""
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import set_planet_latlon as S  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402


class SetLatLonTests(unittest.TestCase):
    def test_show_and_move(self):
        with tempfile.TemporaryDirectory() as d:
            stage, game = os.path.join(d, "stage"), os.path.join(d, "game")
            os.makedirs(stage)
            os.makedirs(os.path.join(game, "Data"))
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 1, 0x801))])
            pndt = rec(b"PNDT", 0x02000800, [(b"EDID", b"NirnPlanetData\0"),
                                             (b"CNAM", struct.pack("<ddI", -1.5707963, 0.0, 0x01000800)),
                                             (b"FNAM", struct.pack("<6f", 0, 0, 0, 7484, 0, 0))])
            plugin = os.path.join(stage, "Planet.esm")
            with open(plugin, "wb") as fh:
                fh.write(tes4 + grup(b"PNDT", 0, [pndt]))
            shutil.copy(plugin, os.path.join(game, "Data", "Planet.esm"))
            with open(os.path.join(stage, "overlays_params.json"), "w") as fh:
                json.dump({"mars": {"plugin": "Planet.esm"}, "overlays": [{"latitude": -1.5707963, "longitude": 0}]},
                          fh)
            self.assertEqual(S.main(["--staging", stage]), 0)
            self.assertEqual(S.main(["--staging", stage, "--latlon", "0.3", "0.1", "--starfield", game]), 0)
            for p in (plugin, os.path.join(game, "Data", "Planet.esm")):
                (r,) = S.cnam_entries(p)
                self.assertEqual(r["cnam"][1], [(0.3, 0.1, 0x01000800)])
                self.assertEqual(r["fnam"][3], 7484)
            with open(os.path.join(stage, "overlays_params.json")) as fh:
                self.assertEqual(json.load(fh)["overlays"][0]["latitude"], 0.3)


if __name__ == "__main__":
    unittest.main()
