"""scripts/npc/child_skin_preview.py: the children's tone textures and baked faces side by side (2026-11-19)."""
import os
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

import child_skin_preview as P  # noqa: E402
from fo4sf import skintone  # noqa: E402


def dds(rgb):
    img = np.zeros((8, 8, 4), np.uint8)
    img[..., :3] = rgb
    img[..., 3] = 255
    return skintone.raw_dds(img)


class PreviewTests(unittest.TestCase):
    def test_sheet_and_medians(self):
        game = {"t/b0.dds": dds((139, 109, 82)), "t/b1.dds": dds((164, 126, 103)), "t/f0.dds": dds((189, 143, 115)),
                "t/f1.dds": dds((172, 126, 98))}
        report = {"child_skin_tones": {"male": {"textures": ["t/b0.dds", "t/b1.dds"]},
                                       "male_face": {"textures": ["t/f0.dds", "t/f1.dds", "t/missing.dds"]}},
                  "npcs": [{"edid": "Frodnar", "female": False, "child": {"files": []},
                            "test_npc": {"ston": 1, "baked_face": {"files": ["00000814_color.dds"]}}},
                           {"edid": "Ysolda", "female": True}]}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, *P.FACES_DIR)
            os.makedirs(p)
            with open(os.path.join(p, "00000814_color.dds"), "wb") as fh:
                fh.write(dds((170, 130, 110)))

            def read(path):
                return game[path]
            img, meds = P.build(report, read, d)
        self.assertEqual(meds["male slot 1"], [164, 126, 103])
        self.assertEqual(meds["male_face slot 0"], [189, 143, 115])
        self.assertIn("not read", meds["male_face slot 2"])
        self.assertEqual(meds["Frodnar baked face"], [170, 130, 110])
        self.assertEqual(img.shape[0], 3 * P.TILE)                    # body row, face row, Frodnar's face
        self.assertEqual(int(img[0, P.TILE * 3 // 2 + 1, 0]), 255)     # slot 1 framed (his own)


if __name__ == "__main__":
    unittest.main()
