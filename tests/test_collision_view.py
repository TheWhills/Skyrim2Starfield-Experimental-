"""scripts/terrain/collision_view.py on the synthetic Skyrim rock (tests/skyrim_fixtures.py: a dome with the same dome
as CMS collision)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
import skyrim_fixtures as F  # noqa: E402
import collision_view as V  # noqa: E402


class CollisionViewTests(unittest.TestCase):
    def test_rock(self):
        rock = next(k for k in F.MODELS if "rock" in k.lower())
        with tempfile.TemporaryDirectory() as d:
            data = F.skyrim_data(os.path.join(d, "Data"))
            page = os.path.join(d, "v.html")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(V.main(["--skyrim-data", data, "--model", rock, "--out", page]), 0)
            with open(page, encoding="utf-8") as fh:
                doc = json.loads(fh.read().split("const D=", 1)[1].split(";</script>", 1)[0])
            r = doc["results"][0]
            self.assertTrue(r["landscape_rule"])
            self.assertGreater(r["boxes"], 0)
            # Skyrim's collision is the same dome as the visible mesh (coarser grid): close to it
            self.assertLess(abs(r["skyrim_collision_top_minus_visible_top_m"]["median"]), 0.1)
            # column boxes take the highest point of each column: mostly at or above Skyrim's top
            self.assertGreaterEqual(r["our_box_top_minus_skyrim_collision_top_m"]["median"], 0.0)
            self.assertGreater(r["our_box_top_minus_skyrim_collision_top_m"]["max"], 0.0)
            self.assertEqual(len(doc["models"][0]["grid"]["excess"]), doc["models"][0]["grid"]["rows"])


if __name__ == "__main__":
    unittest.main()
