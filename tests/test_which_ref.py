"""scripts/terrain/which_ref.py on a synthetic staged exterior."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
import which_ref as W  # noqa: E402


class WhichRefTests(unittest.TestCase):
    def test_ref_and_near(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "objects.json"), "w") as fh:
                json.dump({"bases": [{"edid": "SKY_RoadChunk01", "source": "meshes\\landscape\\roads\\roadchunk01.nif"}],
                           "refs": [{"src": "01ABCD:Skyrim.esm", "base": 0, "pos": [10.0, 20.0, 400.0], "scale": 1.0},
                                    {"src": "01ABCE:Skyrim.esm", "base": 0, "pos": [50.0, 20.0, 400.0]}]}, fh)
            with open(os.path.join(d, "formids.json"), "w") as fh:
                json.dump({"plugin": "SkyrimTerrainTamriel.esm", "refs": {"01ABCD:Skyrim.esm": "00a123",
                                                                          "01ABCE:Skyrim.esm": "00A124"}}, fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(W.main(["--staging", d, "--ref", "0A00A123", "--near", "11", "20", "--radius", "3"]), 0)
                self.assertEqual(W.main(["--staging", d, "--ref", "FF0185CB"]), 1)
                with open(os.path.join(d, "overlays_params.json"), "w") as fh:
                    json.dump({"overlays": [{"spawn": [11.0, 20.0, 400.0]}]}, fh)
                self.assertEqual(W.main(["--staging", d, "--near", "1", "2", "--spawn-at", "1", "2", "--radius", "1"]), 0)
            text = out.getvalue()
            self.assertIn("roadchunk01.nif", text)
            self.assertIn("1 objects within 3.0 m", text)
            self.assertIn("-> exterior frame (11.00, 20.00)", text)
            self.assertIn("runtime reference", text)


if __name__ == "__main__":
    unittest.main()
