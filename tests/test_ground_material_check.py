"""scripts/terrain/ground_material_check.py (2026-11-22): missing materials / textures and shared resource IDs."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

import ground_material_check as G  # noqa: E402


def mat(ids, colour):
    return json.dumps({"Objects": [{"ID": i, "Components": []} for i in ids] + [
        {"Components": [{"Type": "BSMaterial::MRTextureFile", "Index": 0, "Data": {"FileName": colour}}]}]}).encode()


class CheckTest(unittest.TestCase):
    def test_report(self):
        files = {"materials\\skyrim\\ground\\a.mat": mat(["res:1:2:3", "res:9:9:9"], "Data\\textures\\skyrim\\ground\\a_color.dds"),
                 "materials\\skyrim\\ground\\b.mat": mat(["res:4:2:3", "res:9:9:9"], "Data\\textures\\skyrim\\ground\\gone.dds"),
                 "textures\\skyrim\\ground\\a_color.dds": b"DDS "}
        ov = [{"skyrim": "LA", "form_id": "1", "material": "materials\\skyrim\\ground\\a.mat"},
              {"skyrim": "LB", "form_id": "2", "material": "skyrim\\ground\\b.mat"},
              {"skyrim": "LC", "form_id": "3", "material": "materials\\skyrim\\ground\\c.mat"}]
        out = "\n".join(G.check(files.get, ov))
        self.assertIn("OK       LA", out)
        self.assertIn("TEXTURE? LB", out)
        self.assertIn("gone.dds", out)
        self.assertIn("MISSING  LC", out)
        self.assertIn("resource IDs defined by more than one ground material: 1", out)
        self.assertIn("res:9:9:9: LA, LB", out)


if __name__ == "__main__":
    unittest.main()
