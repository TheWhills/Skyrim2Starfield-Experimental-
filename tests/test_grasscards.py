"""fo4sf.grasscards: Skyrim grass cards cut into blade strips along their cut-out (2026-11-24, grass "fins")."""
import dataclasses
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import grasscards as G  # noqa: E402


@dataclasses.dataclass
class Sh:
    positions: list
    uvs: list
    normals: list
    tangents: list
    colors: list
    triangles: list
    alpha_ref: int = 128


def stripes(size=64, every=8, width=2):
    """Vertical opaque blades (columns) on a transparent texture."""
    a = np.zeros((size, size), np.uint8)
    for c in range(0, size, every):
        a[:, c:c + width] = 255
    return a


def card():
    """One upright card in the x/z plane: UV (0,1) bottom-left, (1,1) bottom-right, (0.5,0) top."""
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 0.0, 1.0)]
    uv = [(0.0, 1.0), (1.0, 1.0), (0.5, 0.0)]
    return Sh(pos, uv, [(0.0, -1.0, 0.0)] * 3, [], [(255, 255, 255, 0)] * 3, [(0, 1, 2)])


class CardStrips(unittest.TestCase):
    def test_strips_follow_blades_inside_triangle(self):
        uv = [(0.0, 1.0), (1.0, 1.0), (0.5, 0.0)]
        strips = G.card_strips(uv, stripes(), 128, cols=32, rows=32)
        self.assertTrue(strips)
        a = stripes()
        for u0, u1, v0, v1 in strips:
            self.assertLess(u0, u1)
            self.assertLess(v0, v1)
            cols = range(int(u0 * 64), max(int(u0 * 64) + 1, int(np.ceil(u1 * 64))))
            self.assertTrue(any(a[0, c % 64] for c in cols))      # every strip covers some blade texel
        covered = sum((u1 - u0) for u0, u1, _v0, _v1 in strips)
        self.assertLess(covered, 0.5 * 32)                       # far less than full columns: gaps left out

    def test_transparent_card_has_no_strips(self):
        self.assertEqual(G.card_strips([(0, 1), (1, 1), (0.5, 0)], np.zeros((16, 16), np.uint8), 128), [])

    def test_degenerate_uv(self):
        self.assertEqual(G.card_strips([(0.2, 0.2), (0.2, 0.2), (0.2, 0.2)], stripes(), 128), [])


class BladeShape(unittest.TestCase):
    def test_on_card_plane_facing_its_normal(self):
        new, st = G.blade_shape(card(), stripes(), 128, cols=32, rows=32)
        self.assertEqual(st["cards"], 1)
        self.assertGreater(st["strips"], 0)
        self.assertEqual(len(new.triangles), 2 * st["strips"])
        p = np.array(new.positions)
        self.assertTrue(np.allclose(p[:, 1], 0.0))               # on the card's plane y = 0
        self.assertTrue((p[:, 2] >= -1e-6).all() and (p[:, 2] <= 1 + 1e-6).all())
        for a, b, c in new.triangles:                            # wound like the card (normal -y)
            n = np.cross(p[b] - p[a], p[c] - p[a])
            self.assertLessEqual(n[1], 1e-9)
        self.assertEqual(new.colors, [])
        uv = np.array(new.uvs)
        self.assertTrue(((uv >= -1e-6) & (uv <= 1 + 1e-6)).all())

    def test_uv_maps_back_to_position(self):
        new, _st = G.blade_shape(card(), stripes(), 128)
        for (x, _y, z), (u, v) in zip(new.positions, new.uvs):   # the card's affine map: x = u, z = 1 - v
            self.assertAlmostEqual(x, u, places=6)
            self.assertAlmostEqual(z, 1.0 - v, places=6)

    def test_degenerate_triangle_kept(self):
        sh = card()
        sh.uvs = [(0.3, 0.3)] * 3
        new, st = G.blade_shape(sh, stripes(), 128)
        self.assertEqual(st["strips"], 0)
        self.assertEqual(len(new.triangles), 1)

    def test_not_bc4(self):
        self.assertIsNone(G.opacity_plane(b"not a dds"))


if __name__ == "__main__":
    unittest.main()
