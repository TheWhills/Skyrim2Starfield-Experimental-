"""Stair-helper ramps over stair steps (src/fo4sf/stairramp.py) on synthetic collision meshes, and the wiring into
native Skyrim collision (a layer-31 body when ramps are found, none when the model has its own stair helpers)."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import stairramp as S  # noqa: E402


class Mesh:
    def __init__(self):
        self.P, self.T = [], []

    def quad(self, a, b, c, d):
        i = len(self.P)
        self.P += [a, b, c, d]
        self.T += [(i, i + 1, i + 2), (i, i + 2, i + 3)]

    def box(self, x0, y0, z0, x1, y1, z1):
        """Top, front (y0) and two sides of an axis box (what a step's collision looks like)."""
        self.quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
        self.quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))
        self.quad((x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1))
        self.quad((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))

    def rotated(self, deg, dx=0.0, dy=0.0):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        m = Mesh()
        m.P = [(x * c - y * s + dx, x * s + y * c + dy, z) for x, y, z in self.P]
        m.T = list(self.T)
        return m


def stairs(n=6, rise=0.2, run=0.3, width=1.2, floor=True, landing=True):
    """Floor (y < 0), n steps going up +y, a landing at the top."""
    m = Mesh()
    if floor:
        m.quad((-1.0, -2.0, 0.0), (width + 1.0, -2.0, 0.0), (width + 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0))
    for k in range(n):
        m.box(0.0, k * run, 0.0, width, (k + 1) * run, (k + 1) * rise)
    if landing:
        m.box(-0.5, n * run, 0.0, width + 0.5, n * run + 2.0, (n + 1) * rise)
    return m


def z_at(pts, tris, x, y):
    """Height of the ramp under (x, y), or None."""
    for t in tris:
        a, b, c = (pts[i] for i in t)
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
        l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) >= -1e-6:
            return l1 * a[2] + l2 * b[2] + l3 * c[2]
    return None


class RampTests(unittest.TestCase):
    def test_straight_stairs(self):
        m = stairs()
        pts, tris, rep = S.stair_ramps(m.P, m.T)
        self.assertEqual(len(rep), 1)
        r = rep[0]
        self.assertEqual(r["steps"], 6)                     # the landing is too deep to count as a step
        self.assertAlmostEqual(r["rise_m"], 0.2)
        self.assertAlmostEqual(r["run_m"], 0.3)
        self.assertAlmostEqual(r["width_m"], 1.2)
        self.assertEqual((r["from_z_m"], r["to_z_m"]), (0.0, 1.4))     # floor in front -> the landing's front edge
        self.assertAlmostEqual(r["slope_deg"], math.degrees(math.atan2(0.2, 0.3)), places=1)
        for k in range(1, 7):                               # through every step's nosing (front edge, top)
            self.assertAlmostEqual(z_at(pts, tris, 0.6, (k - 1) * 0.3 + 1e-4), k * 0.2, places=3)
        a, b, c = (pts[i] for i in tris[0])                 # normal up
        self.assertGreater((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]), 0)

    def test_rotated_and_far_from_origin(self):
        m = stairs(n=4, rise=0.17, run=0.28).rotated(33, 12.5, -40.0)
        _p, _t, rep = S.stair_ramps(m.P, m.T)
        self.assertEqual([r["steps"] for r in rep], [4])
        self.assertAlmostEqual(rep[0]["rise_m"], 0.17)

    def test_without_floor_or_landing_the_ramp_spans_the_steps(self):
        m = stairs(n=5, floor=False, landing=False)
        _p, _t, rep = S.stair_ramps(m.P, m.T)
        self.assertEqual((rep[0]["from_z_m"], rep[0]["to_z_m"]), (0.2, 1.0))

    def test_nothing_for_non_stairs(self):
        m = Mesh()
        m.quad((0, 0, 0), (6, 0, 0), (6, 6, 0), (0, 6, 0))                         # floor
        m.box(1, 1, 0, 2.5, 1.8, 0.75)                                            # table
        m.box(1, 2.2, 0, 2.5, 2.6, 0.45)                                          # bench
        m.box(4, 1, 0, 4.4, 4, 0.3)                                               # a single long low step
        m.quad((0, 7, 0), (1.2, 7, 0), (1.2, 9, 1.2), (0, 9, 1.2))                # an existing ramp
        self.assertEqual(S.stair_ramps(m.P, m.T), ([], [], []))
        two = stairs(n=2)                                                         # two steps: not a flight
        self.assertEqual(S.stair_ramps(two.P, two.T)[2], [])

    def test_two_flights(self):
        a = stairs(n=4)
        b = stairs(n=5, rise=0.18, run=0.32).rotated(90, 20.0, 0.0)
        m = Mesh()
        m.P = a.P + b.P
        m.T = a.T + [(i + len(a.P), j + len(a.P), k + len(a.P)) for i, j, k in b.T]
        _p, tris, rep = S.stair_ramps(m.P, m.T)
        self.assertEqual(sorted(r["steps"] for r in rep), [4, 5])
        self.assertEqual(len(tris), 4)

    def test_min_rect(self):
        ang, length, depth, centre = S.min_rect([(0, 0), (2, 0), (2, 0.5), (0, 0.5), (1, 0.25)])
        self.assertAlmostEqual(ang % math.pi, 0.0)
        self.assertEqual((round(length, 6), round(depth, 6)), (2.0, 0.5))
        self.assertAlmostEqual(centre[0], 1.0)


class WiringTests(unittest.TestCase):
    def run_native(self, bodies, **kw):
        from fo4sf import meshcollision, skyrimconvert, skyrimnif
        calls = []
        orig = skyrimnif.collision_bodies, meshcollision.mesh_body
        try:
            skyrimnif.collision_bodies = lambda src, report: bodies
            meshcollision.mesh_body = lambda pts, tris, tmpl, layer=None: calls.append((layer, len(tris))) or b"blob"
            report = {}
            blobs = skyrimconvert.native_collision(None, b"tmpl", report, **kw)
        finally:
            skyrimnif.collision_bodies, meshcollision.mesh_body = orig
        return blobs, calls, report

    def skyrim_units(self, m):
        from fo4sf import skyrimconvert
        return [(x / skyrimconvert.UNIT, y / skyrimconvert.UNIT, z / skyrimconvert.UNIT) for x, y, z in m.P], m.T

    def test_ramp_body_on_the_stair_layer(self):
        pts, tris = self.skyrim_units(stairs(n=5))
        blobs, calls, report = self.run_native([(1, pts, tris)])
        self.assertEqual(calls, [(1, len(tris)), (31, 2)])
        self.assertEqual(len(blobs), 2)
        self.assertEqual(report["stair_ramps"][0]["steps"], 5)
        self.assertEqual(report["bodies"], 2)

    def test_layer_option_and_off(self):
        pts, tris = self.skyrim_units(stairs(n=5))
        self.assertEqual(self.run_native([(1, pts, tris)], stair_layer=1)[1][-1], (1, 2))
        blobs, calls, report = self.run_native([(1, pts, tris)], stair_layer=None)
        self.assertEqual((len(blobs), "stair_ramps" in report), (1, False))

    def test_models_with_their_own_stair_helpers_get_none(self):
        pts, tris = self.skyrim_units(stairs(n=5))
        _b, calls, report = self.run_native([(1, pts, tris), (31, pts[:3], [(0, 1, 2)])])
        self.assertEqual([c[0] for c in calls], [1, 31])
        self.assertNotIn("stair_ramps", report)

    def test_cli_option(self):
        import types
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "terrain"))
        import make_skyrim_objects as so
        self.assertEqual(so.stair_layer(types.SimpleNamespace(stair_ramp_layer=31)), 31)
        self.assertIsNone(so.stair_layer(types.SimpleNamespace(stair_ramp_layer=0)))
        self.assertEqual(so.stair_layer(types.SimpleNamespace()), 31)


if __name__ == "__main__":
    unittest.main()
