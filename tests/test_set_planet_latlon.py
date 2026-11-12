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


    def test_day_length_and_tilt(self):
        """2026-11-12 (owner: a 24-hour planet): ENAM f32 at 48 = axial tilt (rad), at 52 = turns per Earth day."""
        import math
        with tempfile.TemporaryDirectory() as d:
            enam = struct.pack("<6d", 2.2e8, 2.2e8, 2.3e8, 0.06, 0.09, 2.2e8) + struct.pack("<4f", 0.087266, 0.48, 0, 0) \
                + struct.pack("<II", 1, 0)
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 1, 0x801))])
            pndt = rec(b"PNDT", 0x02000800, [(b"EDID", b"NirnPlanetData\0"),
                                             (b"CNAM", struct.pack("<ddI", 0.8, 0.0, 0x01000800)), (b"ENAM", enam)])
            plugin = os.path.join(d, "Planet.esm")
            with open(plugin, "wb") as fh:
                fh.write(tes4 + grup(b"PNDT", 0, [pndt]))
            with open(os.path.join(d, "overlays_params.json"), "w") as fh:
                json.dump({"mars": {"plugin": "Planet.esm"}, "overlays": [{"latitude": 0.8, "longitude": 0}]}, fh)
            (r,) = S.cnam_entries(plugin)
            self.assertAlmostEqual(S.day_hours(r["enam"][1][1]), 50.0, places=3)        # Jemison's ~50 h
            self.assertIsNone(S.day_hours(0.0))                                            # tidally locked
            self.assertEqual(S.main(["--staging", d, "--day-hours", "24", "--axial-tilt-deg", "23.4"]), 0)
            (r,) = S.cnam_entries(plugin)
            tilt, spin = r["enam"][1]
            self.assertAlmostEqual(spin, 1.0, places=6)
            self.assertAlmostEqual(math.degrees(tilt), 23.4, places=4)
            self.assertEqual(r["cnam"][1], [(0.8, 0.0, 0x01000800)])                        # place untouched
            with open(os.path.join(d, "overlays_params.json")) as fh:
                self.assertEqual(json.load(fh)["planet"], {"day_hours": 24.0, "axial_tilt_deg": 23.4})


if __name__ == "__main__":
    unittest.main()
