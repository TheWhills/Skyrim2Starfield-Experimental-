"""Vertex-alpha cutouts (2026-11-25, owner's Whiterun market): Skyrim draws an alpha-tested Vertex_Alpha shape where
texture alpha x vertex alpha passes the threshold; the converter cuts the shape along its vertex alpha (synthetic)."""
import json
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, HERE)

from fo4sf import nif as nifmod, skyrimconvert as sc, skyrimnif  # noqa: E402
from test_materials import mini_template  # noqa: E402


def square(alpha_left=0, alpha_right=255):
    """A 1 x 1 square in two triangles, vertex alpha alpha_left at x = 0 and alpha_right at x = 1."""
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    return nifmod.Fo4Shape(
        name=b"Grass:15", translation=(0, 0, 0), rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1), scale=1.0,
        shader_ref=0, alpha_ref=1, skin_ref=-1, positions=pos, uvs=[(p[0], p[1]) for p in pos],
        normals=[(0.0, 0.0, 1.0)] * 4, tangents=[(1.0, 0.0, 0.0)] * 4,
        colors=[(200, 200, 200, a) for a in (alpha_left, alpha_right, alpha_right, alpha_left)],
        triangles=[(0, 1, 2), (0, 2, 3)], skinned=False, block=5)


def area(s):
    tot = 0.0
    for a, b, c in s.triangles:
        (ax, ay, _), (bx, by, _), (cx, cy, _) = s.positions[a], s.positions[b], s.positions[c]
        tot += ((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2.0
    return tot


class FakeNif:
    """blocks[0] a BSLightingShaderProperty with the given flags, blocks[1] a NiAlphaProperty (test, threshold)."""

    def __init__(self, f1, f2, test=True, ref=128):
        shader = struct.pack("<IiIiII", 0, -1, 0, -1, f1, f2) + b"\0" * 64
        alpha = struct.pack("<iIiHB", -1, 0, -1, 0x200 if test else 0, ref)
        self.blocks = [shader, alpha]

    def type_of(self, i):
        return ("BSLightingShaderProperty", "NiAlphaProperty")[i]


class BandTests(unittest.TestCase):
    def test_bands_raise_the_threshold_where_vertex_alpha_is_low(self):
        b = sc.vertex_alpha_bands(128, True)
        self.assertEqual(len(b), sc.VA_BANDS)
        self.assertAlmostEqual(b[0][0], 128 / 255)
        self.assertIsNone(b[-1][1])                               # the top band runs to full vertex alpha
        for (lo, hi, _t), (lo2, _h, _t2) in zip(b, b[1:]):
            self.assertAlmostEqual(hi, lo2)
        thr = [t for _l, _h, t in b]
        self.assertEqual(thr, sorted(thr, reverse=True))
        self.assertGreaterEqual(thr[-1], 128)
        self.assertLess(thr[-1], 145)                             # near full vertex alpha: about Skyrim's own
        self.assertGreater(thr[0], 200)                           # near the cut: only the texture's most opaque texels

    def test_solid_texture_is_one_cut(self):
        self.assertEqual(sc.vertex_alpha_bands(128, False), [(128 / 255, None, 128)])
        self.assertEqual(sc.vertex_alpha_bands(0, True), [])


class ClipTests(unittest.TestCase):
    def test_keeps_the_part_over_the_level(self):
        s = sc.clip_vertex_alpha(square(), 0.5)
        self.assertAlmostEqual(area(s), 0.5, places=3)
        self.assertTrue(all(p[0] >= 0.5 - 1e-3 for p in s.positions))
        # 2 vertices kept + 3 cut points (bottom, top and the diagonal both triangles share; not shared would be 4)
        self.assertEqual(len(s.positions), 5)
        cut = [i for i, p in enumerate(s.positions) if abs(p[0] - 0.5) < 2e-3]
        self.assertEqual(len(cut), 3)
        for i in cut:
            self.assertAlmostEqual(s.uvs[i][0], s.positions[i][0])
            self.assertIn(s.colors[i][3], (127, 128))
            self.assertEqual(s.normals[i], (0.0, 0.0, 1.0))
        self.assertEqual(s.block, 5)

    def test_bands_tile_the_kept_part(self):
        s = square()
        parts = [sc.clip_vertex_alpha(s, lo, hi) for lo, hi, _t in sc.vertex_alpha_bands(128, True)]
        self.assertAlmostEqual(sum(area(p) for p in parts), area(sc.clip_vertex_alpha(s, 128 / 255)), places=6)
        self.assertTrue(all(area(p) > 0 for p in parts))         # winding kept: no part turned over

    def test_nothing_over_the_level(self):
        self.assertIsNone(sc.clip_vertex_alpha(square(0, 100), 0.5))
        self.assertEqual(len(sc.clip_vertex_alpha(square(255, 255), 0.5).triangles), 2)


class FlagTests(unittest.TestCase):
    def test_needs_vertex_alpha_and_vertex_colours(self):
        self.assertTrue(skyrimnif.vertex_alpha(FakeNif(0x8E400108, 0x00008028), 0))   # WRMainRoadMarket:15's flags
        self.assertFalse(skyrimnif.vertex_alpha(FakeNif(0x82400300, 0x00008028), 0))
        self.assertFalse(skyrimnif.vertex_alpha(FakeNif(0x8E400108, 0x00008008), 0))
        self.assertFalse(skyrimnif.vertex_alpha(FakeNif(0x82400309, 0x22008031), 0))   # TundraShrub01: Tree_Anim
        self.assertFalse(skyrimnif.vertex_alpha(FakeNif(0x8, 0x20), 1))                 # not a shader block


class CutTests(unittest.TestCase):
    def converter(self, staging, stem, opacity):
        c = object.__new__(sc.SkyrimConverter)
        c.prefix, c.staging, c.neutral, c._materials, c.stats = "skyrim", staging, "neutral.mat", {}, {}
        t = mini_template()
        t["Objects"][0]["Components"].append({"Type": "BSMaterial::LayerID", "Data": {"ID": "res:1:2:3"}, "Index": 0})
        c.template_mat = t
        if opacity:
            p = os.path.join(staging, "textures", "skyrim", *f"{stem}_opacity.dds".split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").close()
        return c

    def test_cutout_split_into_bands_with_own_thresholds(self):
        stem = "architecture/whiterun/wrfieldgrass01_0123abcd"
        mat = "materials\\skyrim\\" + stem.replace("/", "\\") + ".mat"
        with tempfile.TemporaryDirectory() as d:
            c = self.converter(d, stem, True)
            rep = {}
            shapes, mats = c._vertex_alpha_cut(FakeNif(0x8E400108, 0x28), [square()], [mat], rep)
            self.assertEqual(len(shapes), sc.VA_BANDS)
            self.assertEqual(rep, {"vertex_alpha_shapes": 1, "vertex_alpha_parts": sc.VA_BANDS})
            self.assertEqual(len(set(mats)), sc.VA_BANDS)
            last = mats[0]
            p = os.path.join(d, *last.split("\\"))
            with open(p, encoding="utf-8") as fh:
                m = json.load(fh)
            alpha = [c2["Data"] for o in m["Objects"] for c2 in o.get("Components", [])
                     if c2["Type"] == "BSMaterial::AlphaSettingsComponent"]
            self.assertEqual(alpha[0]["HasOpacity"], "true")
            self.assertGreater(float(alpha[0]["AlphaTestThreshold"]), 0.75)            # the band at the cut
            self.assertIn("_va", last)

    def test_left_alone(self):
        stem = "a/b_0123abcd"
        mat = "materials\\skyrim\\a\\b_0123abcd.mat"
        with tempfile.TemporaryDirectory() as d:
            c = self.converter(d, stem, False)
            for nif, s in ((FakeNif(0x82400300, 0x28), square()),                  # no Vertex_Alpha flag
                           (FakeNif(0x8, 0x28, test=False), square()),               # not alpha-tested
                           (FakeNif(0x8, 0x28), square(250, 255))):                  # vertex alpha all solid
                out, mats = c._vertex_alpha_cut(nif, [s], [mat], {})
                self.assertEqual((out, mats), ([s], [mat]))
            out, mats = c._vertex_alpha_cut(FakeNif(0x8, 0x28), [square()], [mat], {})  # solid texture: one cut
            self.assertEqual(mats, [mat])
            self.assertAlmostEqual(area(out[0]), 0.5, places=2)
            out, mats = c._vertex_alpha_cut(FakeNif(0x8, 0x28), [square(0, 60)], [mat], {})
            self.assertEqual((out, mats), ([], []))                                  # Skyrim draws none of it


if __name__ == "__main__":
    unittest.main()
