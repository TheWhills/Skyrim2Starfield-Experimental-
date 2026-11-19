"""fo4sf.childpaint: a Skyrim child's own face paint carried onto Starfield's child head (2026-11-19)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import childpaint as CP  # noqa: E402


def grid(n=17, z=0.0):
    """A flat square (0-1 in x and y) facing +Z: vertices, triangles, and its UVs (= x, y)."""
    g = np.linspace(0, 1, n)
    v = np.array([(x, y, z) for y in g for x in g])
    t = np.array([(i * n + j, i * n + j + 1, (i + 1) * n + j) for i in range(n - 1) for j in range(n - 1)] +
                 [(i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j) for i in range(n - 1) for j in range(n - 1)])
    return v, t, v[:, :2].copy()


class PaintTests(unittest.TestCase):
    def test_pieces(self):
        a, b, c = np.array([[0.0, 0, 0]]), np.array([[1.0, 0, 0]]), np.array([[0.0, 1, 0]])
        np.testing.assert_allclose(CP.barycentric(np.array([[0.25, 0.25, 0]]), a, b, c), [[0.5, 0.25, 0.25]])
        img, cov = CP.raster(np.array([[0, 0], [1, 0], [0, 1]]), np.array([[0, 1, 2]]),
                             np.array([[1.0], [2.0], [3.0]]), 8)
        self.assertTrue(cov[0, 0] and not cov[7, 7])
        self.assertAlmostEqual(img[0, 0, 0], 1.0, delta=0.25)
        ramp = np.tile(np.arange(4, dtype=float)[None, :, None], (4, 1, 1))
        self.assertAlmostEqual(float(CP.sample(ramp, np.array([[0.5, 0.5]]))[0, 0]), 1.5)
        noisy = np.random.default_rng(0).random((32, 32))
        self.assertLess(CP.blur(noisy, 3).std(), 0.3 * noisy.std())
        self.assertAlmostEqual(float(CP.blur(np.full((8, 8), 0.4), 2).mean()), 0.4)

    def test_paint_factor(self):
        """Lightness to STRENGTH, colour to CHROMA: a redder-than-skin spot gets redder, a grey one only lighter or
        darker."""
        grey = CP.paint_factor(np.array([0.5, 0.5, 0.5]), 0.8, 2.0)
        np.testing.assert_allclose(grey, [0.5 ** 0.8] * 3, rtol=1e-6)
        red = np.array([1.2, 0.9, 0.9])
        f = CP.paint_factor(red, 1.0, 2.0)
        self.assertGreater(f[0] / f[1], red[0] / red[1])          # pinker than the tint alone
        luma = lambda c: float((np.asarray(c) * CP.LUMA).sum())    # noqa: E731
        self.assertAlmostEqual(luma(CP.paint_factor(red, 1.0, 1.0)), luma(red))
        np.testing.assert_allclose(CP.paint_factor(np.ones(3)), np.ones(3))

    def test_grain_kept_features_softened(self):
        """Under the paint, Starfield's fine skin grain stays; its larger painted features go."""
        size = 256
        rng = np.random.default_rng(3)
        face = np.full((size, size, 4), 180, np.uint8)
        grain = rng.integers(-12, 13, size=(size, size))
        face[..., :3] = np.clip(180 + grain, 0, 255)[..., None]
        face[117:123, 60:120, :3] -= 60                               # a painted feature (a lid line)
        layer = {"factor": np.ones((size, size, 3)), "weight": np.ones((size, size))}
        out = CP.painted_face(face, layer).astype(int)
        flat = out[10:60, 150:240, 0]
        self.assertGreater(flat.std(), 0.5 * face[10:60, 150:240, 0].astype(int).std())   # grain kept
        self.assertGreater(out[118:122, 80:100, 0].mean(), face[118:122, 80:100, 0].mean() + 30)  # the line mostly gone

    def test_lip_outline_not_softened(self):
        """Starfield's painted lip edge survives under the lip colour; the same line off the lips is softened."""
        size = 256
        face = np.full((size, size, 4), 180, np.uint8)
        face[117:123, 20:120, :3] = 120                              # a painted line, half on the lips
        lips = np.zeros((size, size))
        lips[:, :70] = 1.0
        layer = {"factor": np.ones((size, size, 3)), "weight": np.ones((size, size)), "lips": lips}
        out = CP.painted_face(face, layer).astype(int)
        self.assertLessEqual(abs(out[120, 40, 0] - 120), 2)          # on the lips: crisp as painted
        self.assertGreater(out[120, 100, 0], 140)                    # off them: softened

    def test_lips_and_eyes(self):
        """The lips get LIP_TINT (darker, rosier); the eye surroundings no colour boost."""
        v = np.array([(0.0, 0.098, 1.608), (0.03, 0.098, 1.608), (-0.04, 0.083, 1.684), (0.0, 0.1, 1.64)])
        eyes = np.array([(-0.04, 0.083, 1.684), (0.04, 0.083, 1.684)])
        lips, ew = CP.lip_eye_weights(v, eyes, np.array([0.0, 0.098, 1.608]))
        self.assertEqual(list(lips), [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(list(ew), [0.0, 0.0, 1.0, 0.0])
        vv, t, uv = grid(17)
        tint = np.full((32, 32, 4), 200, np.uint8)
        lip_w = (np.abs(uv[:, 0] - 0.25) < 0.2).astype(float)          # the left part is "lips"
        layer = CP.paint_layer(uv, t, uv, np.ones(len(uv)), tint, 64, lips=lip_w)
        face = np.full((64, 64, 4), 200, np.uint8)
        out = CP.painted_face(face, layer)
        lip_px, skin_px = out[32, 16, :3].astype(int), out[32, 56, :3].astype(int)
        self.assertLess(lip_px[1], skin_px[1] - 20)                    # darker green: rosier, darker
        self.assertGreater(lip_px[0] - lip_px[1], skin_px[0] - skin_px[1])

    def test_upright_uv(self):
        v, _t, uv = grid(9)                       # x right, y up: eyes at y 0.8, mouth at y 0.2
        eyes, mouth = np.array([(0.3, 0.8, 0), (0.7, 0.8, 0)]), np.array([0.5, 0.2, 0])
        got, flipped = CP.upright_uv(uv, v, eyes, mouth, near=0.2)      # v = y: eyes lower in the image
        self.assertTrue(flipped)
        np.testing.assert_allclose(got[:, 1], 1 - uv[:, 1])
        got, flipped = CP.upright_uv(got, v, eyes, mouth, near=0.2)     # already upright
        self.assertFalse(flipped)

    def test_vertex_sky_uv(self):
        sv, st, suv = grid(9)
        pts = np.array([(0.3, 0.6, 0.001), (0.3, 0.6, 0.02)])         # on the face; 2 cm off it
        uv, w = CP.vertex_sky_uv(pts, sv, st, suv, np.ones(2))
        np.testing.assert_allclose(uv[0], (0.3, 0.6), atol=1e-6)
        self.assertEqual(list(w), [1.0, 0.0])

    def test_paint_carries_the_tint(self):
        """A dark freckle in the Skyrim tint lands where its UV leads; the rest keeps the face's own colour."""
        v, t, uv = grid(17)
        size = 64
        sky_uv = uv[:, ::-1].copy()                  # Skyrim's UVs: the square turned (x <-> y)
        weight = (uv[:, 0] < 0.75).astype(float)     # no paint on the right quarter
        tint = np.full((32, 32, 4), 200, np.uint8)
        tint[20:24, 8:12, :3] = 60                   # a freckle at Skyrim (u 0.31, v 0.69)
        layer = CP.paint_layer(uv, t, sky_uv, weight, tint, size)
        self.assertEqual(layer["factor"].shape, (size, size, 3))
        face = np.zeros((size, size, 4), np.uint8)
        face[...] = (210, 170, 150, 255)
        out = CP.painted_face(face, layer)
        # Starfield pixel (u 0.69, v 0.31) <- Skyrim (0.31, 0.69): the freckle
        py, px = int(0.31 * size), int(0.69 * size)
        self.assertLess(int(out[py - 4:py + 4, px - 4:px + 4, 0].min()), 150)
        self.assertTrue(abs(int(out[10, 10, 0]) - 210) <= 2)           # plain skin: unchanged colour
        np.testing.assert_array_equal(out[:, -4:], face[:, -4:])       # unpainted quarter as it was
        self.assertEqual(int(out[0, 0, 3]), 255)
        with self.assertRaises(ValueError):
            CP.painted_face(face[:32, :32], layer)
        with self.assertRaises(ValueError):
            CP.paint_layer(uv, t, sky_uv, np.zeros(len(uv)), tint, size)


if __name__ == "__main__":
    unittest.main()
