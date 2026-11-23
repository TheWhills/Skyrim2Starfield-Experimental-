"""scripts/terrain/density_maps.py (2026-11-23): uniform biome-mask density maps for the staged terrain."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import density_maps as D  # noqa: E402
from fo4sf import overlay  # noqa: E402


class DensityMapTest(unittest.TestCase):
    def test_uniform_dds_decodes(self):
        dds = D.uniform_bc4_dds(16, 8, 200)
        info = overlay.dds_info(dds)
        self.assertEqual((info["width"], info["height"], info["format"], info["data_offset"]), (16, 8, "BC4", 128))
        img = overlay.bc4_decode(dds)
        self.assertEqual(img.shape, (8, 16))
        self.assertTrue((img == 200).all())
        self.assertEqual(len(dds), 128 + 8 * 4 * 2)            # legacy header, 8 bytes per 4 x 4 block
        with self.assertRaises(ValueError):
            D.uniform_bc4_dds(10, 8, 1)

    def test_uniform_and_remove(self):
        with tempfile.TemporaryDirectory() as st:
            with open(os.path.join(st, "overlays_params.json"), "w") as f:
                json.dump({"overlays": [{"btd_file": "Data/Terrain/SKY_Tamriel.btd"}]}, f)
            with contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertEqual(D.main(["uniform", "--staging", st, "--cells", "2", "1", "--value", "255"]), 0)
            self.assertIn("2 x 1 cells -> 200 x 100 px", log.getvalue())
            flat = os.path.join(st, "Data", "textures", "terrain", "sky_tamriel_flatouter.dds")
            nested = os.path.join(st, "Data", "textures", "terrain", "sky_tamriel", "sky_tamriel_base.dds")
            self.assertTrue(os.path.exists(flat) and os.path.exists(nested))
            with open(flat, "rb") as f:
                self.assertTrue((overlay.bc4_decode(f.read()) == 255).all())
            with contextlib.redirect_stdout(io.StringIO()) as log:
                D.main(["remove", "--staging", st])
            self.assertIn("removed 12 density map(s)", log.getvalue())
            self.assertFalse(os.path.exists(flat) or os.path.exists(nested))


if __name__ == "__main__":
    unittest.main()
