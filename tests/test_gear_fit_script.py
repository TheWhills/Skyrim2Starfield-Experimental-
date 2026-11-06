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
