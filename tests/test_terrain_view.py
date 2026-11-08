"""scripts/terrain/terrain_view.py on a synthetic one-cell BTD with a 0.5 m step in it."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
from fo4sf import btd  # noqa: E402
import terrain_view as T  # noqa: E402


class TerrainViewTests(unittest.TestCase):
    def test_window_bumps_and_page(self):
        with tempfile.TemporaryDirectory() as d:
            h = np.full((128, 128), 400.0)
            h[60:, :] += 0.5                                    # a 0.5 m step along y = 46.9 m
            raw = btd.quantize(h, 390.0, 410.0)
            t = btd.Btd(version=7, hmin=390.0, hmax=410.0, ltex=[1], heights_raw=raw,
                        weights=np.zeros((128, 128), np.uint16), quad_map=np.zeros((2, 2, 8), np.uint8))
            os.makedirs(os.path.join(d, "Data", "Terrain"))
            with open(os.path.join(d, "Data", "Terrain", "W.btd"), "wb") as fh:
                fh.write(btd.write(t))
            with open(os.path.join(d, "overlays_params.json"), "w") as fh:
                json.dump({"overlays": [{"world": "W", "origin_cw_m": [0, 0], "height_offset_m": 385}]}, fh)
            with open(os.path.join(d, "objects.json"), "w") as fh:
                json.dump({"bases": [{"edid": "SKY_Rock", "source": "rock.nif"}],
                           "refs": [{"src": "01:Skyrim.esm", "base": 0, "pos": [50.0, 50.0, 400.0]}]}, fh)
            out = io.StringIO()
            page = os.path.join(d, "view.html")
            with contextlib.redirect_stdout(out):
                self.assertEqual(T.main(["--terrain", d, "--pos", "50", "45", "--radius", "10", "--out", page]), 0)
            text = out.getvalue()
            self.assertIn("largest bump", text)
            self.assertIn("1 objects in the window", text)
            with open(page, encoding="utf-8") as fh:
                html = fh.read()
            data = json.loads(html.split("const D=", 1)[1].split(";</script>", 1)[0])
            self.assertEqual(len(data["objects"]), 1)
            b = np.array(data["bump"], dtype=float)
            self.assertGreater(np.abs(b).max(), 0.1)              # the step shows as a ridge
            self.assertAlmostEqual(data["player"][2], 400.0, places=1)


if __name__ == "__main__":
    unittest.main()
