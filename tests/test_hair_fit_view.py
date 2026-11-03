"""scripts/armor/hair_fit_view.py: the head-depth test, region counts and the page, on synthetic data."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts", "armor"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import hair_fit_view as V  # noqa: E402


def sphere(n=4000, r=0.09, c=(0.0, 0.0, 1.65)):
    d = np.random.default_rng(2).normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    return np.asarray(c) + r * d, d


class FitViewTests(unittest.TestCase):
    def test_profile_lift_and_volume(self):
        from fo4sf import skyrimhair
        pts, nrm = sphere(8000)
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.65)

        def ring(height_by_angle):                           # hairline points 3 mm above the sphere
            out = []
            for ang, z in height_by_angle.items():
                a = np.radians(ang)
                horiz = np.sqrt(max(0.093 ** 2 - z ** 2, 0.0))
                out.append(head[:3, 3] + [horiz * np.sin(a), horiz * np.cos(a), z])
            return np.array(out)
        target = {a: 0.05 for a in skyrimhair.HAIRLINE_ANGLES}
        own = {a: (0.03 if abs(a) >= 50 else 0.045) for a in skyrimhair.HAIRLINE_ANGLES}   # low at the temples
        prof = skyrimhair.hairline_profile(ring(own), pts, nrm, head)
        for a in (0, 30, 60):
            self.assertAlmostEqual(prof[a], own[a], delta=0.002)
        lift = skyrimhair.lift_profile(prof, skyrimhair.hairline_profile(ring(target), pts, nrm, head))
        self.assertGreater(lift[70], lift[0] + 0.01)          # more lift at the temples than in the middle
        self.assertTrue(all(0.0 <= v <= 0.03 for v in lift.values()))
        self.assertEqual(skyrimhair.lift_profile({0: None, 10: None}, {0: 0.05, 10: 0.05}), {0: 0.0, 10: 0.0})
        ringed = ring(own)
        sh0 = skyrimhair.HairShape(b"R", ringed, np.zeros_like(ringed), np.zeros_like(ringed),
                                   [(0, 0)] * len(ringed), [(0, 1, 2)], [[("C_Head", 1.0)]] * len(ringed), -1, -1, 0)
        lifted = skyrimhair.lift_hairline(skyrimhair.Hair([sh0], [], {}, {}), pts, nrm, head, lift)
        after = skyrimhair.hairline_profile(np.asarray(lifted.shapes[0].positions), pts, nrm, head)
        self.assertLess(abs(after[60] - 0.05), abs(prof[60] - 0.05) - 0.008)   # the temples came up toward the target
        top = head[:3, 3] + [0.0, 0.0, 0.093]
        low = head[:3, 3] + [0.0, -0.093, -0.02]
        sh = skyrimhair.HairShape(b"S", np.array([top, low]), np.zeros((2, 3)), np.zeros((2, 3)), [(0, 0)] * 2,
                                  [(0, 1, 0)], [[("C_Head", 1.0)]] * 2, -1, -1, 0)
        out = np.asarray(skyrimhair.add_volume(skyrimhair.Hair([sh], [], {}, {}), pts, nrm, head, 0.01,
                                               low=0.0, high=0.07).shapes[0].positions)
        self.assertAlmostEqual(out[0, 2] - top[2], 0.01, delta=0.001)      # the top stands 1 cm off
        np.testing.assert_allclose(out[1], low, atol=1e-9)                  # below C_Head: untouched
        self.assertAlmostEqual(skyrimhair.crown_height(out, head), 0.103, delta=0.001)
        # the edge stays on the skin: no push at the hairline, full 3 cm above it; the scalp tint never moves
        fore = np.radians(0)
        at_line = head[:3, 3] + [0.0, 0.093 * np.cos(np.arcsin(0.05 / 0.093)), 0.05]
        above = head[:3, 3] + [0.0, 0.093 * np.cos(np.arcsin(0.085 / 0.093)), 0.085]
        hs = skyrimhair.HairShape(b"KSSMP_X", np.array([at_line, above]), np.zeros((2, 3)), np.zeros((2, 3)),
                                  [(0, 0)] * 2, [(0, 1, 0)], [[("C_Head", 1.0)]] * 2, -1, -1, 0)
        tint = skyrimhair.HairShape(b"Hairline", np.array([above]), np.zeros((1, 3)), np.zeros((1, 3)), [(0, 0)],
                                    [], [[("C_Head", 1.0)]], -1, -1, 0)
        edge = {a: 0.05 for a in skyrimhair.HAIRLINE_ANGLES}
        out = skyrimhair.add_volume(skyrimhair.Hair([hs, tint], [], {}, {}), pts, nrm, head, 0.01, edge=edge,
                                    low=0.0, high=0.07)
        moved = np.linalg.norm(np.asarray(out.shapes[0].positions) - hs.positions, axis=1)
        self.assertLess(moved[0], 1e-6)                                   # on the hairline: stays on the skin
        self.assertGreater(moved[1], 0.007)                               # 3.5 cm up the 5 cm rise: ~0.8 of it
        np.testing.assert_allclose(out.shapes[1].positions, tint.positions)   # 'Hairline' tint untouched
        side = head[:3, 3] + [0.093 * np.cos(np.arcsin(0.04 / 0.093)), 0.0, 0.04]   # above the ear
        ss = skyrimhair.HairShape(b"S", np.array([side, top]), np.zeros((2, 3)), np.zeros((2, 3)), [(0, 0)] * 2,
                                  [(0, 1, 0)], [[("C_Head", 1.0)]] * 2, -1, -1, 0)
        out = np.asarray(skyrimhair.add_volume(skyrimhair.Hair([ss], [], {}, {}), pts, nrm, head, 0.008)
                         .shapes[0].positions)                             # defaults: the top only
        np.testing.assert_allclose(out[0], side, atol=1e-9)                # the side stays snug
        self.assertGreater(out[1, 2] - top[2], 0.001)                      # the very top still gains some
        both = skyrimhair.Hair([hs, tint], [], {}, {})
        self.assertEqual(len(skyrimhair.hair_points(both)), 2)              # the measurements skip the tint layer
        self.assertTrue(skyrimhair.is_tint(tint) and not skyrimhair.is_tint(hs))

    def test_fill_layers_stack_turned_copies_of_the_raised_top(self):
        from fo4sf import skyrimhair
        pts, nrm = sphere(8000)
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.65)
        c = head[:3, 3]

        def on_head(el, az, r=0.091):
            e, a = np.radians(el), np.radians(az)
            return c + r * np.array([np.cos(e) * np.sin(a), np.cos(e) * np.cos(a), np.sin(e)])
        # a crown triangle (fully raised), a side triangle below `low` (never raised), and the scalp tint
        crown = np.array([on_head(80, 0), on_head(80, 90), on_head(75, 45)])
        side = np.array([on_head(10, 90), on_head(15, 90), on_head(10, 100)])
        pos = np.concatenate([crown, side])
        sh = skyrimhair.HairShape(b"KSSMP_X", pos, nrm[:6].copy(), nrm[:6].copy(), [(i * 0.1, 0.0) for i in range(6)],
                                  [(0, 1, 2), (3, 4, 5)], [[("C_Head", 1.0)]] * 3 + [[("Hair1", 1.0)]] * 3, 7, 8, 0)
        tint = skyrimhair.HairShape(b"Hairline", crown.copy(), np.zeros((3, 3)), np.zeros((3, 3)), [(0, 0)] * 3,
                                    [(0, 1, 2)], [[("C_Head", 1.0)]] * 3, -1, -1, 0)
        out = skyrimhair.add_volume(skyrimhair.Hair([sh, tint], [], {}, {}), pts, nrm, head, 0.02,
                                    low=0.0, high=0.07, layers=3)
        names = [s.name for s in out.shapes]
        self.assertEqual(names, [b"KSSMP_X", b"KSSMP_X_layer1", b"KSSMP_X_layer2", b"KSSMP_X_layer3", b"Hairline"])
        np.testing.assert_allclose(out.shapes[0].positions, pos)             # the wig itself stays on the scalp
        np.testing.assert_allclose(out.shapes[4].positions, crown)           # and so does the tint
        for k, layer in enumerate(out.shapes[1:4], 1):
            self.assertEqual(len(layer.positions), 3)                        # the crown only: the side never rose
            self.assertEqual(layer.triangles, [(0, 1, 2)])
            self.assertEqual(layer.uvs, sh.uvs[:3])
            self.assertEqual(layer.weights, sh.weights[:3])
            self.assertEqual((layer.shader_ref, layer.alpha_ref), (7, 8))
            off = np.linalg.norm(layer.positions - c, axis=1) - 0.091
            np.testing.assert_allclose(off, 0.02 * k / 3, atol=0.002)        # evenly up to the full amount
        turned = [np.degrees(np.arctan2(l.positions[1, 0] - c[0], l.positions[1, 1] - c[1])) for l in out.shapes[1:4]]
        d = [t - 90.0 for t in turned]                                       # alternating sides, so the cards
        self.assertGreater(abs(d[0]), 0.5)                                   # of one layer cover the gaps of
        self.assertLess(d[0] * d[1], 0.0)                                    # the next
        self.assertGreater(d[2] * d[0], 0.0)
        self.assertGreater(abs(d[2]), abs(d[0]) + 0.5)
        self.assertEqual(out.report["layers"], 3)
        self.assertEqual(out.report["layer_vertices"], 9)
        self.assertEqual(out.report["vertices"], 6 + 3 + 9)
        moved = skyrimhair.add_volume(skyrimhair.Hair([sh], [], {}, {}), pts, nrm, head, 0.02, low=0.0, high=0.07)
        self.assertEqual(len(moved.shapes), 1)                               # layers=0: the old move
        self.assertGreater(np.linalg.norm(moved.shapes[0].positions[0] - pos[0]), 0.015)

    def test_drop_duplicate_shapes_keeps_one_copy_of_ks_two_pass_wig(self):
        from fo4sf import skyrimhair
        p = np.array([[0.0, 0.0, 1.7], [0.01, 0.0, 1.7], [0.0, 0.01, 1.7]])

        def shape(name, pos, uvs=((0, 0), (1, 0), (0, 1))):
            return skyrimhair.HairShape(name, pos, None, None, list(uvs), [(0, 1, 2)], [[("C_Head", 1.0)]] * 3,
                                        -1, -1, 0)
        hair = skyrimhair.Hair([shape(b"KSSMP_A", p), shape(b"KSSMP_A_HL", p.copy()), shape(b"Hairline", p + 0.001),
                                shape(b"Other", p.copy(), uvs=((0, 0), (0.5, 0), (0, 0.5)))], [], {}, {})
        out, dropped = skyrimhair.drop_duplicate_shapes(hair)
        self.assertEqual(dropped, ["KSSMP_A_HL"])
        self.assertEqual([s.name for s in out.shapes], [b"KSSMP_A", b"Hairline", b"Other"])
        self.assertEqual(out.report["vertices"], 9)
        same, none = skyrimhair.drop_duplicate_shapes(out)
        self.assertIs(same, out)
        self.assertEqual(none, [])

    def test_lift_hairline_raises_the_front_keeps_the_back_and_the_gap(self):
        from fo4sf import skyrimhair
        pts, nrm = sphere(8000)
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.65)                      # C_Head at the sphere centre for this test
        d = np.array([[0.0, 0.8, 0.6], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, -0.3]])
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        p = head[:3, 3] + d * 0.094                           # 4 mm above the head: forehead, back, crown, cheek
        p[3] = head[:3, 3] + [0.0, 0.14, -0.04]               # a lock hanging well in front of the face
        sh = skyrimhair.HairShape(b"S", p, np.zeros((4, 3)), np.zeros((4, 3)), [(0, 0)] * 4, [(0, 1, 2)],
                                  [[("C_Head", 1.0)]] * 4, -1, -1, 0)
        out = np.asarray(skyrimhair.lift_hairline(skyrimhair.Hair([sh], [], {}, {}), pts, nrm, head,
                                                  0.015).shapes[0].positions)
        self.assertGreater(out[0, 2] - p[0, 2], 0.005)          # the forehead point went up
        np.testing.assert_allclose(out[1], p[1], atol=1e-9)     # the back stayed
        np.testing.assert_allclose(out[2], p[2], atol=1e-9)     # the crown stayed
        self.assertAlmostEqual(out[3, 2] - p[3, 2], 0.015)      # a lock off the head: lifted as is
        g0, _d, _i = skyrimhair.nearest_surface(p[:1], pts, nrm)
        g1, _d, _i = skyrimhair.nearest_surface(out[:1], pts, nrm)
        self.assertAlmostEqual(float(g1[0]), float(g0[0]), delta=0.0015)   # still ~4 mm above the head

    def test_push_out_conforms_without_pulling_in(self):
        from fo4sf import skyrimhair
        pts, nrm = sphere()
        cap = np.array([[0.0, 0.0, 1.65 + 0.085], [0.01, 0.0, 1.65 + 0.088], [0.0, 0.01, 1.65 + 0.10],
                        [0.0, -0.3, 1.2]])                       # 5 mm in, 2 mm in, 1 cm out, far below
        sh = skyrimhair.HairShape(b"S", cap, np.zeros((4, 3)), np.zeros((4, 3)), [(0, 0)] * 4, [(0, 1, 2)],
                                  [[("C_Head", 1.0)]] * 4, -1, -1, 0)
        out, rep = skyrimhair.push_out(skyrimhair.Hair([sh], [], {}, {}), pts, nrm)
        p = np.asarray(out.shapes[0].positions)
        depth, _dist, _i = skyrimhair.nearest_surface(p[:3], pts, nrm)
        self.assertTrue(np.all(depth >= 0.002 - 1e-4))             # all at least 2 mm outside
        self.assertTrue(np.all(np.linalg.norm(p[:3] - [0, 0, 1.65], axis=1) >=
                               np.linalg.norm(cap[:3] - [0, 0, 1.65], axis=1) - 1e-9))   # never pulled in
        np.testing.assert_allclose(p[3], cap[3])                  # not judged: untouched
        self.assertEqual(rep["vertices_moved"], 2)


    def test_depth_regions_and_page(self):
        pts, nrm = sphere()
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.62)
        probe = np.array([[0.0, 0.0, 1.65 + 0.07],      # 2 cm inside, top
                          [0.0, 0.08, 1.65],            # 1 cm inside, front
                          [0.0, -0.12, 1.60],           # outside, back
                          [0.0, 0.0, 1.65 + 0.095]])    # 5 mm outside
        d = V.head_depth(probe, pts, nrm)
        self.assertAlmostEqual(d[0], -0.02, delta=0.003)
        self.assertAlmostEqual(d[1], -0.01, delta=0.003)
        self.assertTrue(np.isnan(d[2]))                       # 3 cm off the head: not judged
        self.assertAlmostEqual(d[3], 0.005, delta=0.003)
        below = V.head_depth(np.array([[0.0, 0.0, 1.65 - 0.089]]), pts, nrm)   # at the neck cut: not judged
        self.assertTrue(np.isnan(below[0]))
        r = V.regions(probe, d, head)
        self.assertEqual((r["inside"], r["top"], r["forehead / face (front)"], r["back"]), (2, 1, 1, 0))
        self.assertEqual(r["judged (near the head)"], 3)
        self.assertAlmostEqual(r["deepest_mm"], 20.0, delta=3.0)
        line = np.array([[0.0, 0.0911, 1.66], [0.0, 0.0911, 1.70], [0.05, 0.08, 1.60], [0.0, 0.2, 1.50]])
        self.assertAlmostEqual(V.hairline(line, pts, nrm, head), 1.66 - 1.62, places=6)   # lowest on the front
        self.assertIsNone(V.hairline(line[2:], pts, nrm, head))                 # off the band / off the head
        html = V.page({"head": (pts[:10], np.ones((10, 3))), "wig": (probe, np.zeros((4, 3)))}, "T", r)
        self.assertIn("three.min.js", html)
        self.assertIn('"wig":{"p":[0,1720,0,', html)            # model (x, y, z) -> page (x, z, y), mm
        self.assertNotIn("DATAJSON", html)


if __name__ == "__main__":
    unittest.main()
