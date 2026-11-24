"""scripts/re/ground_cover_weights.py (2026-11-24): Starfield's ground-cover layer weights (synthetic quadrants)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "re"))

import ground_cover_weights as G  # noqa: E402


class LayerIndices(unittest.TestCase):
    def test_bytes_0_to_4_then_6_minus_one(self):
        self.assertEqual(G.layer_indices([10, 11, 12, 13, 14, 99, 57, 98]), [9, 10, 11, 12, 13, 56])

    def test_byte_6_ignored_when_a_layer_is_empty(self):
        self.assertEqual(G.layer_indices([10, 11, 0, 13, 14, 0, 57, 0]), [9, 10])

    def test_byte_5_never_read(self):
        self.assertEqual(G.layer_indices([1, 2, 3, 4, 5, 77, 0, 0]), [0, 1, 2, 3, 4])


class Alphas(unittest.TestCase):
    def test_pack_round_trip(self):
        alphas = [0, 6, 7, 1, 3]
        self.assertEqual(G.unpack_alphas(G.pack_alphas(alphas)), alphas)

    def test_bit_order(self):
        self.assertEqual(G.pack_alphas([7, 0, 0, 0, 0]), 0b111)
        self.assertEqual(G.pack_alphas([0, 0, 0, 0, 7]), 0b111 << 12)

    def test_range(self):
        with self.assertRaises(ValueError):
            G.pack_alphas([8, 0, 0, 0, 0])


class Blend(unittest.TestCase):
    def test_single_layer_takes_all(self):
        self.assertEqual(G.blend(1, [0, 0, 0, 0, 0]), [1.0])

    def test_weights_sum_to_one(self):
        w = G.blend(6, [3, 5, 1, 0, 6])
        self.assertAlmostEqual(sum(w), 1.0)

    def test_mask_layer_gets_nothing_under_full_alpha(self):
        # owner's uniform patch (2026-11-24): every layer at 7 -> no ground cover
        quadrant = [5, 5, 5, 5, 5, 0, 57, 0]
        weights = G.layer_weights(quadrant, G.pack_alphas([7, 7, 7, 7, 7]))
        self.assertEqual(weights[-1][0], 56)
        self.assertEqual(weights[-1][1], 0.0)

    def test_one_full_alpha_anywhere_zeroes_the_mask_layer(self):
        quadrant = [1, 2, 3, 4, 5, 0, 57, 0]
        weights = G.layer_weights(quadrant, G.pack_alphas([0, 0, 0, 7, 0]))
        self.assertEqual(weights[-1][1], 0.0)
        self.assertEqual(weights[3][1], 1.0)

    def test_mask_layer_is_the_product_of_the_rests(self):
        quadrant = [1, 2, 3, 4, 5, 0, 57, 0]
        weights = G.layer_weights(quadrant, G.pack_alphas([3, 3, 3, 3, 3]))
        self.assertAlmostEqual(weights[-1][1], (4 / 7) ** 5)

    def test_all_alpha_zero_gives_the_mask_layer_everything(self):
        quadrant = [1, 2, 3, 4, 5, 0, 57, 0]
        weights = G.layer_weights(quadrant, 0)
        self.assertEqual([w for _, w in weights], [0.0, 0.0, 0.0, 0.0, 0.0, 1.0])


class Cover(unittest.TestCase):
    def test_threshold_and_density(self):
        self.assertEqual(G.cover_weight(0.3, 0.44, 90), 0.0)
        self.assertAlmostEqual(G.cover_weight(0.5, 0.44, 90), 0.45)


if __name__ == "__main__":
    unittest.main()
