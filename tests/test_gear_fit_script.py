"""scripts/armor/gear_fit.py: refuses an output inside the repository; the writer it shares with os_export."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import gear_fit  # noqa: E402
import os_export  # noqa: E402


class ScriptTests(unittest.TestCase):
    def test_out_inside_repo_refused(self):
        with self.assertRaises(SystemExit):
            gear_fit.main(["--skyrim-data", "x", "--starfield", "y", "--npc", "Ralof", "--name", "R",
                           "--out", os.path.join(ROOT, "tmp_out")])

    def test_sex_ok(self):
        self.assertTrue(gear_fit.sex_ok("malehands.nif", False))
        self.assertFalse(gear_fit.sex_ok("femalehands.nif", False))
        self.assertTrue(gear_fit.sex_ok("femalehands.nif", True))
        self.assertFalse(gear_fit.sex_ok("hands_m.nif", True))
        self.assertTrue(gear_fit.sex_ok("hands.nif", True))

    def test_skin_shapes_by_texture(self):
        t = {"MaleBodyStormcloak": ["textures\\actors\\character\\male\\MaleBody_1.dds"],
             "StormCloak": ["textures\\armor\\stormcloaks\\StormcloaksCuirass.dds"],
             "HandMale_Big1stperson": ["textures/actors/character/male/MaleHands_1.dds"], "X": []}
        self.assertEqual(gear_fit.skin_shapes(t), {"MaleBodyStormcloak", "HandMale_Big1stperson"})

    def test_find_texconv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "texconv.exe")
            open(exe, "wb").close()
            self.assertEqual(gear_fit.find_texconv(exe), exe)
        self.assertIn(gear_fit.find_texconv(os.path.join(ROOT, "nope.exe")), ("", gear_fit.find_texconv()))

    def test_shape_materials_falls_back(self):
        class Conv:
            neutral = "materials\\neutral.mat"
            material_errors = {}

            def _shape_material(self, n, s):
                return self.neutral if s.name == b"A" else "materials\\s2s\\x.mat"
        import numpy as np
        from fo4sf import skyrimskin
        from unittest import mock
        fake = [mock.Mock(name="a"), mock.Mock(name="b")]
        fake[0].name, fake[1].name = b"A", b"B"
        with mock.patch.object(gear_fit.skyrimskin, "skinned_shapes", lambda n: fake), \
                mock.patch.object(gear_fit.nifmod, "parse", lambda b: None):
            out = gear_fit.shape_materials(Conv(), b"")
        self.assertEqual(out, {"A": None, "B": "materials\\s2s\\x.mat"})

    def test_writer_takes_materials(self):
        import inspect
        self.assertIn("materials", inspect.signature(os_export.write_armor).parameters)

    def test_tessellate_shapes(self):
        import numpy as np
        from fo4sf import gearfit
        pts = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]], float)
        s = gearfit.SkyShape(b"Boots", pts, np.tile([0, 0, 1.0], (3, 1)), [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)],
                             ["NPC L Calf [LClf]", "NPC L Foot [Lft ]"], [[(0, 1.0)], [(1, 1.0)], [(0, 0.5), (1, 0.5)]])
        big = gearfit.SkyShape(b"Big", np.vstack([pts, pts[:1]]), np.tile([0, 0, 1.0], (4, 1)), s.uvs + [(0, 0)],
                               s.triangles, s.bones, s.weights + [[(0, 1.0)]])
        out, rep = gear_fit.tessellate_shapes([s, big], 3, below=4)
        self.assertEqual(rep, {"Boots": [3, 10]})
        t = out[0]
        self.assertEqual((len(t.points), len(t.triangles)), (10, 9))
        self.assertTrue(np.allclose(t.points[:, 2], 0))                       # flat: stays on the triangle's plane
        out2, rep2 = gear_fit.tessellate_shapes([s], 3, below=4, skip={"Boots"})
        self.assertEqual(rep2, {})
        self.assertEqual(len(t.weights), 10)
        self.assertTrue(all(0 <= b < 2 for vw in t.weights for b, _w in vw))
        self.assertTrue(all(abs(sum(w for _b, w in vw) - 1.0) < 1e-9 for vw in t.weights))
        self.assertIs(out[1], big)                       # at / over the limit: unchanged

    def test_flat_subdivide_shares_edges(self):
        import numpy as np
        pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], float)
        p, _n, _uv, t, _w = gear_fit.flat_subdivide(pts, np.tile([0, 0, 1.0], (4, 1)), [(0, 0)] * 4,
                                                    [(0, 1, 2), (1, 3, 2)], [[(0, 1.0)]] * 4, 2)
        self.assertEqual((len(p), len(t)), (9, 8))                            # the shared edge's midpoint once

    def test_neck_part(self):
        import numpy as np
        pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
        w = [[("C_Neck", 1.0)], [("C_Neck", 0.5), ("C_Head", 0.5)], [("C_Neck1", 0.4), ("C_Head", 0.6)],
             [("C_Head", 1.0)]]
        p, t, ww, n = gear_fit.neck_part(pts, [(0, 1, 2), (1, 2, 3)], w, gear_fit.NECK_BONES_SF)
        self.assertEqual((n, len(p), t.tolist()), (3, 3, [[0, 1, 2]]))         # the face-only vertex and its face go

    def test_skin_piece_and_morph(self):
        import numpy as np
        from fo4sf import sfmorph
        body = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0], [1, 1, 1], [1.1, 1, 1], [1, 1.1, 1]], float)
        tris = [(0, 1, 2), (3, 4, 5)]
        uvs = [(i * 0.1, 0.0) for i in range(6)]
        w = [[("L_Forearm", 1.0)]] * 6
        src = np.array([[0.02, 0.02, 0.0]])                     # Skyrim's bare arm lies on the first triangle only
        sh, used = gear_fit.skin_piece(body, tris, uvs, w, src, reach=0.2)
        self.assertEqual((used, sh.name, sh.triangles), ([0, 1, 2], gear_fit.SKIN_SHAPE, [(0, 1, 2)]))
        self.assertEqual(sh.uvs, uvs[:3])
        eight = [[(f"B{k}", 0.125) for k in range(8)]] * 6
        sh8, _u = gear_fit.skin_piece(body, tris, uvs, eight, src, reach=0.2)
        self.assertTrue(all(len(vw) == 8 and abs(sum(x for _b, x in vw) - 1) < 1e-9 for vw in sh8.weights))
        # written with 8 weights per vertex
        from fo4sf import sfmesh
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_armor_check import bind_for, WORLD
        bones = {f"B{k}": bind_for(WORLD["A"]) for k in range(8)}
        sh8.tangents = np.tile([1.0, 0, 0], (3, 1))
        files = os_export.body_nif_files([sh8], ["m.mat"], bones, "S2S/T")
        mesh = sfmesh.parse(next(v for k, v in files.items() if k.endswith(".mesh")))
        self.assertEqual(mesh.weights_per_vertex, 8)
        self.assertEqual(len(mesh.weights), 8 * 3)
        m = sfmorph.parse(sfmorph.build(6, ["Overweight"], {"Overweight": {1: (0.01, 0, 0), 4: (0.02, 0, 0)}}))
        d, _e = gear_fit.skin_morph(m, used)
        self.assertEqual(list(d["Overweight"]), [1])             # body vertex 1 -> skin vertex 1, exactly
        self.assertIsNone(gear_fit.skin_piece(body, tris, uvs, w, np.zeros((0, 3)))[0])

    def test_skin_piece_leaves_covered_skin_out(self):
        import numpy as np
        from fo4sf import skyrimhair
        # a flat strip of body (z = 0, normals up): x 0..0.4; gear lies 2 cm above its first half
        xs = np.linspace(0, 0.4, 9)
        body = np.array([[x, y, 0.0] for x in xs for y in (0.0, 0.05)])
        tris = []
        for i in range(8):
            a, b = 2 * i, 2 * i + 2
            tris += [(a, b, a + 1), (b, b + 1, a + 1)]
        gp = np.array([[-0.05, -0.05, 0.02], [0.2, -0.05, 0.02], [-0.05, 0.1, 0.02], [0.2, 0.1, 0.02]])
        gear = skyrimhair.HairShape(b"Coat", gp, np.tile([0, 0, 1.0], (4, 1)), np.zeros((4, 3)), [], [(0, 1, 2),
                                    (1, 3, 2)], [], -1, -1, -1)
        w = [[("C_Chest", 1.0)]] * len(body)
        sh, used = gear_fit.skin_piece(body, tris, [(0, 0)] * len(body), w, body, reach=0.5, gear=[gear], margin=1)
        xs_kept = sorted({round(float(body[i][0]), 2) for i in used})
        self.assertEqual(xs_kept[0], 0.2)           # covered points left out, one ring of overlap under the edge
        self.assertEqual(xs_kept[-1], 0.4)

    def test_body_skin_shapes_and_slots(self):
        t = {"MaleBodyStormcloak": ["textures\\actors\\character\\male\\MaleBody_1.dds"],
             "HandMale": ["textures\\actors\\character\\male\\MaleHands_1.dds"]}
        self.assertEqual(gear_fit.body_skin_shapes(t), {"MaleBodyStormcloak"})
        self.assertEqual(os_export.slot_bits([3, 5, 7]), ((1 << 3) | (1 << 5) | (1 << 7)).to_bytes(8, "little"))
        self.assertEqual(os_export.slot_bits([3], b"\0" * 8 + b"xy")[8:], b"xy")

    def test_debug_meshes(self):
        import numpy as np
        import tempfile
        import zipfile
        from fo4sf import gearfit, skyrimhair
        sh = skyrimhair.HairShape(b"Coat", np.zeros((3, 3)), np.zeros((3, 3)), np.zeros((3, 3)), [], [(0, 1, 2)],
                                  [], -1, -1, -1)
        sk = gearfit.SkyShape(b"Coat", np.eye(3), np.eye(3), [], [(0, 1, 2)], [], [])
        with tempfile.TemporaryDirectory() as d:
            z = gear_fit.debug_meshes(d, [sh], np.eye(4), np.eye(3), np.array([[0, 1, 2]]), [sk], [])
            self.assertEqual(sorted(zipfile.ZipFile(z).namelist()), ["fit_Coat.obj", "sf_surface.obj", "sky_Coat.obj"])
            self.assertIn("f 1 2 3", open(os.path.join(d, "fit_Coat.obj")).read())

    def test_debug_meshes_heads_and_safe_names(self):
        import numpy as np
        import tempfile
        import zipfile
        from fo4sf import gearfit
        sk = gearfit.SkyShape(b"MaleUnderwearBody:0", np.eye(3), np.eye(3), [], [(0, 1, 2)], [], [])
        head = (np.eye(3), np.array([[0, 1, 2]]))
        with tempfile.TemporaryDirectory() as d:
            z = gear_fit.debug_meshes(d, [], np.eye(4), np.eye(3), np.array([[0, 1, 2]]), [], [sk], head, head)
            self.assertEqual(sorted(zipfile.ZipFile(z).namelist()),
                             ["sf_head.obj", "sf_surface.obj", "skybody_MaleUnderwearBody_0.obj", "skyhead_full.obj"])

    def test_shared_writer(self):
        self.assertTrue(callable(os_export.write_armor))


if __name__ == "__main__":
    unittest.main()


class MorphFileTests(unittest.TestCase):
    def test_morph_files_per_shape(self):
        import numpy as np
        from fo4sf import sfmorph, skyrimhair
        body = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]], float)
        m = sfmorph.parse(sfmorph.build(3, ["Overweight"], {"Overweight": {0: (0.02, 0, 0)}}))
        sh = skyrimhair.HairShape(b"StormCloak", body + 0.001, np.tile([0, 0, 1.0], (3, 1)), np.zeros((3, 3)),
                                  [(0, 0)] * 3, [(0, 1, 2)], [[("C_Chest", 1.0)]] * 3, -1, -1, -1)
        out = gear_fit.morph_files([sh], "S2S\\Ralof_outfit.nif", body, m)
        self.assertEqual(list(out), ["meshes/morphs/s2s/ralof_outfit/chargen/stormcloak/morph.dat"])
        back = sfmorph.parse(out["meshes/morphs/s2s/ralof_outfit/chargen/stormcloak/morph.dat"])
        self.assertEqual(back.num_vertices, 3)
        self.assertIn(0, back.deltas["Overweight"])
        two = gear_fit.morph_files([sh], "S2S\\Ralof_outfit.nif", body, m, doubled={"StormCloak"})
        back = sfmorph.parse(two["meshes/morphs/s2s/ralof_outfit/chargen/stormcloak/morph.dat"])
        self.assertEqual(back.num_vertices, 6)                                  # back-face copies
        self.assertEqual(back.deltas["Overweight"][3], back.deltas["Overweight"][0])

    def test_back_faces_double_the_mesh(self):
        import numpy as np
        from fo4sf import sfmesh, skyrimhair
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_armor_check import bind_for, WORLD
        sh = skyrimhair.HairShape(b"Boots", np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]], float),
                                  np.tile([0, 0, 1.0], (3, 1)), np.tile([1.0, 0, 0], (3, 1)), [(0, 0), (1, 0), (0, 1)],
                                  [(0, 1, 2)], [[("A", 1.0)]] * 3, -1, -1, -1)
        binds = {b: bind_for(WORLD[b]) for b in WORLD}
        files = os_export.body_nif_files([sh], ["m.mat"], binds, "S2S/T", None, [True])
        mesh = sfmesh.parse(next(v for k, v in files.items() if k.endswith(".mesh")))
        self.assertEqual((len(mesh.positions), len(mesh.triangles)), (6, 2))


class MorphCapTests(unittest.TestCase):
    def test_long_deltas_are_cut_and_counted(self):
        d = {"Thin": {0: (0.01, 0.0, 0.0), 1: (0.0, 0.0, 3.0)}}
        st = gear_fit.morph_stats(d)
        self.assertEqual((st["Thin"]["vertices"], st["Thin"]["over_cap"], st["Thin"]["max_mm"]), (2, 1, 3000.0))
        c = gear_fit.capped(d)
        self.assertEqual(c["Thin"][0], (0.01, 0.0, 0.0))
        self.assertAlmostEqual(c["Thin"][1][2], gear_fit.MORPH_MAX)


class MorphTestFiles(unittest.TestCase):
    def test_zero_morph_keeps_layout(self):
        from fo4sf import sfmorph
        data = sfmorph.build(3, ["A", "B"], {"A": {0: (0.01, 0, 0), 2: (0, 0.02, 0)}, "B": {2: (0, 0, 0.03)}},
                             {"A": {0: (1, 2, 3)}})
        z = sfmorph.parse(gear_fit.zero_morph(data))
        self.assertEqual({k: sorted(v) for k, v in z.deltas.items()}, {"A": [0, 2], "B": [2]})
        self.assertTrue(all(x == (0.0, 0.0, 0.0) for v in z.deltas.values() for x in v.values()))
        self.assertEqual(len(gear_fit.zero_morph(data)), len(data))

    def test_zero_files_go_next_to_ours(self):
        from fo4sf import sfmorph
        rel = os_export.part_nif("R", "Coat")
        folder = os_export.morph_folder(rel, "Coat")
        ours = {folder.replace("\\", "/").lower() + "/morph.dat": sfmorph.build(1, ["A"], {"A": {0: (0.01, 0, 0)}})}
        tests = [{"tag": "Zero", "parts": [{"morph_folder": folder + os_export.ZERO_SUFFIX}]}]
        out = gear_fit.test_morph_files(tests, ours, "", "")
        self.assertEqual(list(out), [(folder + os_export.ZERO_SUFFIX).replace("\\", "/").lower() + "/morph.dat"])


class MeshMarginTests(unittest.TestCase):
    def test_skinned_mesh_scale_leaves_room_for_morphs(self):
        import numpy as np
        from fo4sf import sfmesh, skyrimhair
        pos = np.array([[0, 0, -1.26], [0.5, 0, 0.0], [0, 0.3, -0.5]])       # the hem: the largest coordinate
        sh = skyrimhair.HairShape(b"S", pos, np.tile([0, 0, 1.0], (3, 1)), np.tile([1.0, 0, 0], (3, 1)),
                                  [(0.0, 0.0)] * 3, [(0, 1, 2)], [[("A", 1.0)]] * 3, -1, -1, -1,
                                  colors=[(255, 255, 255, 255)] * 3)
        m = skyrimhair._mesh(sh, ["A"], False)
        self.assertAlmostEqual(m.scale, 1.26 + skyrimhair.MORPH_MARGIN)
        self.assertGreaterEqual(skyrimhair.MORPH_MARGIN, gear_fit.MORPH_MAX)   # a capped delta always fits
        got = np.array([sfmesh.decode_position(p, m.scale) for p in m.positions])
        self.assertTrue(np.allclose(got, pos, atol=1e-4))
        self.assertEqual(sfmesh.encode_positions([(0, 0, 2.0)], 0.5)[0], 2.5)


class SlotTests(unittest.TestCase):
    def test_slots_by_skyrim_slot(self):
        import numpy as np
        from fo4sf import gearfit
        shapes = {b"Boots": [b"Boots"], b"Cuirass": [b"Cuirass", b"Body"], b"Cuffs": [b"Cuffs"], b"Belt": [b"Belt"]}
        orig = gear_fit.sky_shapes
        gear_fit.sky_shapes = lambda gb: [gearfit.SkyShape(n, np.eye(3), np.eye(3), [], [], [], []) for n in shapes[gb]]
        try:
            out = gear_fit.slots_by_shape([b"Boots", b"Cuirass", b"Cuffs", b"Belt"],
                                          [{"slots": [37]}, {"slots": [32, 38]}, {"slots": [34]}, {"slots": [48]}])
        finally:
            gear_fit.sky_shapes = orig
        self.assertEqual(out, {"Boots": [7], "Cuirass": [3, 5], "Body": [3, 5], "Cuffs": [8], "Belt": [9]})
