"""FO4 exterior references -> Starfield placements (src/fo4sf/exterior.py), synthetic data only."""
import math
import os
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import exterior as ex  # noqa: E402


def ref(fk, t="Static", model="architecture\\a.nif", pos=(0, 0, 0), rot=(0, 0, 0), scale=1.0, **kw):
    r = {"formkey": fk, "type": t, "base_editor_id": "B" + fk, "model": model, "pos": list(pos), "rot": list(rot),
         "scale": scale, "disabled": 0, "persistent": False, "enable_parent": None, "exterior_cell": [0, 0]}
    r.update(kw)
    return r


def rotate_offset_pluginspike(v, r, scale):
    """PluginSpike.RotateOffset transcribed literally (C#), the oracle for ex.ref_matrix."""
    cx, sx, cy, sy, cz, sz = (math.cos(-r[0]), math.sin(-r[0]), math.cos(-r[1]), math.sin(-r[1]),
                              math.cos(-r[2]), math.sin(-r[2]))
    x, y, z = v[0] * scale, v[1] * scale, v[2] * scale
    y1, z1 = y * cx - z * sx, y * sx + z * cx
    x2, z2 = x * cy + z1 * sy, -x * sy + z1 * cy
    x3, y3 = x2 * cz - y1 * sz, x2 * sz + y1 * cz
    return x3, y3, z2


class ClassifyTests(unittest.TestCase):
    def test_reasons(self):
        self.assertEqual(ex.classify(ref("1")), ("convert", None, ""))
        self.assertEqual(ex.classify(ref("2", t="Light", model=""))[1], "type_not_translated")
        self.assertEqual(ex.classify(ref("3", t="Hazard"))[1], "type_not_translated")
        self.assertEqual(ex.classify(ref("4", t="Activator", model=""))[1], "no_model")
        self.assertEqual(ex.classify(ref("5", model="markers\\xmarker.nif"))[1], "editor_marker")
        self.assertEqual(ex.classify(ref("6", t="MovableStatic", model="effects\\ambient\\fog01.nif"))[1], "effect")
        self.assertEqual(ex.classify(ref("7", t="Flora", model="landscape\\plants\\tato.nif"))[0], "convert")
        self.assertEqual(ex.classify(ref("8", t="Activator", model="Water\\Water1024.nif"))[1], "water")
        self.assertEqual(ex.classify(ref("9", model="SetDressing\\WaterCooler\\WaterCooler01.nif"))[0], "convert")

    def test_select_keeps_every_reference_in_one_list(self):
        export = {"schema_version": 2, "cell": "c", "refs": [ref("1"), ref("2", t="TextureSet", model=""),
                                                             ref("3", model="markers\\m.nif")],
                  "deferred_refs": [{"formkey": "9", "type": "PlacedNpc", "reason": "actor_translation_not_implemented"}]}
        sub, skipped = ex.select(export)
        self.assertEqual([r["formkey"] for r in sub["refs"]], ["1"])
        self.assertEqual(sorted(s["formkey"] for s in skipped), ["2", "3", "9"])
        self.assertEqual(ex.reason_counts(skipped), {"type_not_translated": 1, "editor_marker": 1, "deferred": 1})
        self.assertNotIn("deferred_refs", sub)
        self.assertEqual(sub["schema_version"], 2)

    def test_source_key_matches_convert_batch(self):
        self.assertEqual(ex.source_key("\\Interiors\\RedRocket\\X.nif"), "meshes\\interiors\\redrocket\\x.nif")
        self.assertEqual(ex.source_key("a/b.nif"), "meshes\\a\\b.nif")


class GeometryTests(unittest.TestCase):
    def test_ref_matrix_equals_pluginspike(self):
        rnd = random.Random(7)
        for _ in range(50):
            rot = [rnd.uniform(-math.pi, math.pi) for _ in range(3)]
            v = [rnd.uniform(-5, 5) for _ in range(3)]
            s = rnd.uniform(0.5, 2)
            got = ex.to_world(v, (0, 0, 0), rot, s)
            want = rotate_offset_pluginspike(v, rot, s)
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, places=9)

    def test_heading_is_clockwise(self):
        # a model's +y (north) turned by 90 degrees heading points east (+x)
        p = ex.to_world((0, 1, 0), (10, 20, 30), (0, 0, math.pi / 2), 2.0)
        self.assertAlmostEqual(p[0], 12)
        self.assertAlmostEqual(p[1], 20)
        self.assertAlmostEqual(p[2], 30)

    def test_surfaces(self):
        floor = [((0, 0, 1), (4, 0, 1), (4, 4, 1)), ((0, 0, 1), (4, 4, 1), (0, 4, 1))]
        roof = [((1, 1, 3), (3, 1, 3), (3, 3, 3))]
        tris = floor + roof
        self.assertEqual(ex.surfaces_at(tris, 2.5, 1.5), [3, 1])
        self.assertEqual(ex.top_z(tris, 2.5, 1.5), 3)
        self.assertEqual(ex.top_z(tris, 2.5, 1.5, below=2.0), 1)
        self.assertIsNone(ex.top_z(tris, 5, 5))
        self.assertEqual(ex.point_in_triangle_z(floor[0], 4, 0), 1)    # on a corner: inside
        self.assertIsNone(ex.point_in_triangle_z(((0, 0, 0), (1, 1, 0), (2, 2, 0)), 1, 1))   # degenerate

    def test_landing(self):
        slab = [((0, 0, 1.0), (10, 0, 1.0), (10, 10, 1.0)), ((0, 0, 1.0), (10, 10, 1.0), (0, 10, 1.0))]
        ground = lambda x, y: 0.5
        on = ex.landing(ex.triangles_top(slab), ground, 5, 5, 50)
        self.assertTrue(on["on_object"] and on["all_on_object"])
        self.assertAlmostEqual(on["z"], 1.0)
        self.assertAlmostEqual(on["spread"], 0.0)
        edge = ex.landing(ex.triangles_top(slab), ground, 10.2, 5, 50)                   # disc straddles the slab edge
        self.assertFalse(edge["on_object"])
        self.assertAlmostEqual(edge["spread"], 0.5)
        off = ex.landing(ex.triangles_top(slab), ground, 20, 20, 50)
        self.assertFalse(off["on_object"])
        self.assertAlmostEqual(off["z"], 0.5)
        buried = ex.landing(ex.triangles_top(slab), lambda x, y: 2.0, 5, 5, 50)        # terrain above the slab: the drop lands on terrain
        self.assertFalse(buried["on_object"])
        self.assertAlmostEqual(buried["z"], 2.0)
        under_roof = ex.landing(ex.triangles_top(slab), ground, 5, 5, 0.9)             # dropped below the slab: lands on the ground
        self.assertAlmostEqual(under_roof["z"], 0.5)


def box_tris(x0, y0, z0, x1, y1, z1):
    c = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return [t for q in quads for t in ((c[q[0]], c[q[1]], c[q[2]]), (c[q[0]], c[q[2]], c[q[3]]))]


class SurfaceIndexTests(unittest.TestCase):
    def test_index_matches_brute_force(self):
        rnd = random.Random(3)
        tris = []
        for _ in range(200):
            x, y, z = rnd.uniform(-20, 20), rnd.uniform(-20, 20), rnd.uniform(0, 5)
            tris.append(((x, y, z), (x + rnd.uniform(0.5, 9), y, z + rnd.uniform(-1, 1)),
                         (x, y + rnd.uniform(0.5, 9), z + rnd.uniform(-1, 1))))
        idx = ex.SurfaceIndex(np.array(tris), np.arange(len(tris)))
        for _ in range(300):
            x, y = rnd.uniform(-22, 30), rnd.uniform(-22, 30)
            got = [round(z, 9) for z, _ in idx.surfaces(x, y)]
            self.assertEqual(got, [round(z, 9) for z in ex.surfaces_at(tris, x, y)])
            top = idx.top(x, y, 2.0)
            want = ex.top_z(tris, x, y, 2.0)
            self.assertEqual(None if top is None else round(top[0], 9), None if want is None else round(want, 9))

    def test_world_triangles_place_scale_and_skip_disabled(self):
        model = {0: np.array([((0, 1, 0), (1, 1, 0), (0, 1, 1))], np.float64)}
        placed = [{"base": 0, "pos": [10, 0, 5], "rot": [0, 0, math.pi / 2], "scale": 2.0, "disabled": False},
                  {"base": 0, "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0, "disabled": True},
                  {"base": 7, "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0, "disabled": False}]
        tris, owners = ex.world_triangles(model, placed)
        self.assertEqual(owners.tolist(), [0])
        np.testing.assert_allclose(tris[0][0], (12, 0, 5), atol=1e-9)     # (0, 1, 0) x 2, heading 90 -> (2, 0, 0)
        np.testing.assert_allclose(tris[0][2], (12, 0, 7), atol=1e-9)
        tris, owners = ex.world_triangles(model, placed, skip_disabled=False)
        self.assertEqual(owners.tolist(), [0, 1])

    def test_pick_points_on_a_floor_under_a_ceiling_and_on_a_roof(self):
        # a 10 x 6 m shop: floor slab top 0.1, ceiling slab bottom 3.0 (owner 1), and a crate on the floor (owner 2)
        floor = box_tris(0, 0, -0.2, 10, 6, 0.1)
        ceiling = box_tris(0, 0, 3.0, 10, 6, 3.2)
        crate = box_tris(2, 2, 0.1, 3, 3, 1.0)
        tris = floor + ceiling + crate
        owners = [0] * len(floor) + [1] * len(ceiling) + [2] * len(crate)
        idx = ex.SurfaceIndex(np.array(tris), np.array(owners))
        ground = lambda x, y: 0.0
        inside = ex.pick_points(idx, ground, 0, (0, 0, 10, 6), drop_z=0.85, count=2, need_clearance=2.6)
        self.assertEqual(len(inside), 2)
        for x, y, land, free in inside:
            self.assertAlmostEqual(land["centre"], 0.1)
            self.assertAlmostEqual(free, 2.9)
            self.assertFalse(1.2 <= x <= 3.8 and 1.2 <= y <= 3.8)        # never beside or on the crate
        self.assertGreaterEqual(math.dist(inside[0][:2], inside[1][:2]), 3.0)
        self.assertEqual(ex.pick_points(idx, ground, 0, (0, 0, 10, 6), drop_z=0.85, need_clearance=3.5), [])
        roof = ex.pick_points(idx, ground, 1, (0, 0, 10, 6), drop_z=150)
        self.assertEqual(len(roof), 1)
        self.assertAlmostEqual(roof[0][2]["centre"], 3.2)
        self.assertEqual(ex.clearance(idx, 8, 5, 3.2), math.inf)

    def test_nearby_object(self):
        crate = box_tris(1.0, -1, 0, 2, 1, 0.5)                           # 0.5 m tall, its edge 1 m east of the point
        idx = ex.SurfaceIndex(np.array(crate), np.zeros(len(crate), np.int64))
        ground = lambda x, y: 0.0
        self.assertIsNone(ex.nearby_object(idx.top, ground, 0, 0, 50))  # rings reach 0.6 m only
        near = ex.nearby_object(idx.top, ground, 0.6, 0, 50)
        self.assertEqual(near["distance"], 0.45)
        self.assertAlmostEqual(near["height"], 0.5)
        self.assertEqual(near["owner"], 0)
        self.assertIsNone(ex.nearby_object(idx.top, ground, 0.6, 0, 50, threshold=0.6))
        self.assertIsNone(ex.nearby_object(idx.top, ground, 0.6, 0, 0.4))   # dropped below the crate top: not seen

    def test_interior_order_prefers_the_middle(self):
        samples = [(x * 0.5, y * 0.5, 1.0) for x in range(11) for y in range(5)]
        best = ex.interior_order(samples, radius=1.0)[0]
        self.assertEqual((best[0], best[1]), (2.5, 1.0))


class TeleportTests(unittest.TestCase):
    def test_setpos_path(self):
        self.assertEqual(ex.setpos_path((1, 2, 3), (10, 20), 150), [(10, 2, 3), (10, 20, 3), (10, 20, 150)])

    def test_capsule_hits_walls_floors_and_terrain(self):
        wall = box_tris(5.0, -5, 0, 5.2, 5, 3.0)                          # a 0.2 m thick wall, 3 m high, at x 5..5.2
        floor = box_tris(-5, -5, -0.3, 5, 5, 0.0)
        tris = wall + floor
        idx = ex.SurfaceIndex(np.array(tris), np.array([0] * len(wall) + [1] * len(floor)))
        flat = lambda x, y: -1.0
        self.assertEqual(ex.capsule_hits(idx, flat, 0, 0, 0.0), [])                 # standing on the floor
        self.assertEqual(ex.capsule_hits(idx, flat, 4.7, 0, 0.0), [0])              # 0.3 m from the wall face
        self.assertEqual(ex.capsule_hits(idx, flat, 4.5, 0, 0.0), [])               # 0.5 m away: clear
        self.assertEqual(ex.capsule_hits(idx, flat, 5.1, 0, 3.5), [])               # above the wall
        self.assertEqual(ex.capsule_hits(idx, flat, 0, 0, -0.2), [1])               # feet inside the floor slab
        self.assertEqual(ex.capsule_hits(idx, lambda x, y: x * 0.5, 0.5, 0, 0.1), ["terrain"])   # slope rises over z
        self.assertEqual(ex.capsule_hits(idx, flat, 20, 20, 0.0), [])
        # a vertical ray never sees the wall's sides: the surface queries alone would call x = 5.1 at z 1 clear
        self.assertEqual([o for _, o in idx.surfaces(5.1, 0) if 1.0 < _ < 2.8], [])
        self.assertEqual(ex.capsule_hits(idx, flat, 5.1, 0, 1.0), [0])

    def test_near_is_a_superset(self):
        tris = box_tris(10, 10, 0, 11, 11, 1)
        idx = ex.SurfaceIndex(np.array(tris), np.zeros(len(tris), np.int64))
        self.assertEqual(len(idx.near(10.5, 10.5, 0.4)), len(tris))
        self.assertEqual(len(idx.near(-10, -10, 0.4)), 0)


class PlaceTests(unittest.TestCase):
    def manifest(self):
        return {"items": [{"editor_id": "FO4Port_a", "model": "fo4cw\\architecture\\a.nif", "source": "meshes\\architecture\\a.nif"},
                          {"editor_id": "FO4Port_door", "model": "fo4cw\\doors\\door.nif", "source": "meshes\\doors\\door.nif",
                           "door": {"origin_offset": [1.0, 0.0, 0.0], "anim_graph": "g", "skeleton": "s", "animations": "a"}}],
                "failures": [{"nif": "meshes\\landscape\\trees\\tree.nif", "reason": "ValueError: no static BSTriShape geometry"}]}

    def test_join(self):
        sel = {"refs": [ref("B", pos=(7000, 14000, 700), rot=(0, 0, 0.5), scale=1.5),
                        ref("A", pos=(-70, -70, 0), disabled=0x800, persistent=True),
                        ref("C", model="landscape\\trees\\tree.nif"),
                        ref("D", model="architecture\\never.nif"),
                        ref("E", pos=(70 * 2000, 0, 0)),
                        ref("F", t="Door", model="doors\\door.nif", pos=(700, 0, 0), rot=(0, 0, math.pi / 2), scale=2.0)]}
        bases, placed, skipped = ex.place(sel, self.manifest(), -14, 14)
        self.assertEqual([b["edid"] for b in bases], ["FO4CW_a", "FO4CW_door"])
        self.assertEqual([p["src"] for p in placed], ["A", "B", "F"])
        a, b, f = placed
        self.assertEqual(a["cell"], [-1, -1])
        self.assertEqual(a["pos"], [-1.0, -1.0, 0.0])
        self.assertTrue(a["disabled"] and a["fo4_persistent"])
        self.assertEqual(b["cell"], [1, 2])
        self.assertEqual(b["pos"], [100.0, 200.0, 10.0])
        self.assertEqual(b["scale"], 1.5)
        self.assertEqual(b["rot"], [0.0, 0.0, 0.5])
        # door: hinge offset (1, 0, 0) x scale 2 turned by a 90 degree heading = (0, -2, 0)
        self.assertEqual(f["base"], 1)
        self.assertAlmostEqual(f["pos"][0], 10.0, places=4)
        self.assertAlmostEqual(f["pos"][1], -2.0, places=4)
        # the cell follows the written (shifted) position: FO4 origin y = 0 is cell 0, the hinge at y = -2 m cell -1
        self.assertEqual(f["cell"], [0, -1])
        reasons = {s["formkey"]: s["reason"] for s in skipped}
        self.assertEqual(reasons, {"C": "conversion_failed", "D": "not_converted", "E": "outside_terrain"})
        self.assertIn("BSTriShape", next(s["detail"] for s in skipped if s["formkey"] == "C"))

    def test_door_shifted_out_of_the_terrain_is_skipped(self):
        # FO4 origin inside cell 13 (x 1399 m), the hinge 2 m east puts the door in cell 14: outside -14..13
        sel = {"refs": [ref("G", t="Door", model="doors\\door.nif", pos=(1399 * 70, 0, 0), scale=2.0)]}
        bases, placed, skipped = ex.place(sel, self.manifest(), -14, 13)
        self.assertEqual(placed, [])
        self.assertEqual([s["reason"] for s in skipped], ["outside_terrain"])

    def test_editor_id_prefix(self):
        self.assertEqual(ex.plugin_editor_id("FO4Port_chair", "FO4CW_"), "FO4CW_chair")
        self.assertEqual(ex.plugin_editor_id("Other", "FO4CW_"), "FO4CW_Other")

    def test_duplicate_editor_ids_are_rejected(self):
        m = {"items": [{"editor_id": "FO4Port_a", "model": "x\\a.nif", "source": "meshes\\one\\a.nif"},
                       {"editor_id": "FO4Port_A", "model": "x\\b.nif", "source": "meshes\\two\\a.nif"}]}
        sel = {"refs": [ref("1", model="one\\a.nif"), ref("2", model="two\\a.nif")]}
        with self.assertRaises(ValueError):
            ex.place(sel, m, -14, 14, edid_prefix="FO4CW_")


if __name__ == "__main__":
    unittest.main()
