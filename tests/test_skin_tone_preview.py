"""skin_tone_preview: vanilla vs our skin tone textures with numbers (2026-11-11, the Orc face came out dark)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

from fo4sf import skintone  # noqa: E402
import skin_tone_preview as P  # noqa: E402


class PreviewTests(unittest.TestCase):
    def test_sheet_and_stats(self):
        img = np.zeros((8, 8, 4), np.uint8)
        img[..., :3] = (200, 150, 130)
        img[:4, :, 3] = 255                                    # half the texture alpha 0
        van = {"v.dds": skintone.raw_dds(img)}
        ours = {"o.dds": skintone.raw_dds(skintone.recolour(img, (89, 113, 92)))}
        sheet, rep = P.preview(van.__getitem__, ours.__getitem__,
                               [("x", "v.dds", "o.dds"), ("missing", "nope.dds", "o.dds")], size=4)
        self.assertEqual(sheet.shape, (8, 16, 3))
        self.assertEqual(rep["x"]["vanilla"]["median_rgb"], [200, 150, 130])
        self.assertEqual(rep["x"]["ours"]["median_rgb"], [89, 113, 92])
        self.assertEqual(rep["x"]["vanilla"]["alpha_min_median_max"][0], 0)
        self.assertEqual(rep["x"]["vanilla"]["alpha_below_250_share"], 0.5)
        self.assertIn("error", rep["missing"]["vanilla"])


if __name__ == "__main__":
    unittest.main()
