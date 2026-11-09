"""scripts/npc/mouth_probe.py on synthetic data: jaw / upper labels from an Aah morph (nearest .tri vertex, skin ->
model rotation), Starfield's side from bone names, weights copied from the nearest tooth on the same side, signed
distance to a head surface, the viewer page."""
import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
import mouth_probe as M  # noqa: E402
M_ = M
from fo4sf import facefit  # noqa: E402


def sphere(n=24, m=12, r=1.0):
    th, ph = np.meshgrid(np.linspace(0, 2 * np.pi, n, endpoint=False), np.linspace(0, np.pi, m + 1)[1:-1])
    ring = np.stack([np.sin(ph) * np.cos(th), np.sin(ph) * np.sin(th), np.cos(ph)], -1).reshape(-1, 3)
    v = np.concatenate([[(0, 0, 1)], ring, [(0, 0, -1)]]) * r
    t = []
    for i in range(n):
        j = (i + 1) % n
        t.append((0, 1 + i, 1 + j))
        for k in range(m - 2):
            a, b, c, d = 1 + k * n + i, 1 + k * n + j, 1 + (k + 1) * n + i, 1 + (k + 1) * n + j
            t += [(a, c, d), (a, d, b)]
        last = 1 + (m - 2) * n
        t.append((last + i, len(v) - 1, last + j))
    return v, np.array(t, int)


class MouthTests(unittest.TestCase):
    def test_jaw_labels(self):
        pts = np.array([(0, 0, 1.0), (0, 0, 0.5), (0, 0, -0.5), (0, 0, -1.0)])
        base = pts[::-1] + 1e-4                                   # the .tri in another order
        aah = np.zeros((4, 3))
        aah[0] = (0, 0, -2.0)                                     # base[0] = pts[3]: the chin drops most
        aah[1] = (0, 0, -1.0)
        aah[3] = (0, 0, 0.1)                                      # the top lifts a little
        jaw, drop = M.jaw_labels(pts, base, aah)
        self.assertEqual(jaw.tolist(), [False, False, True, True])
        self.assertEqual(drop.tolist(), [-0.1, 0.0, 1.0, 2.0])
        rot = np.eye(4)
        rot[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]            # skin y -> model z
        aah_y = np.zeros((4, 3))
        aah_y[0] = (0, 2.0, 0)                                    # +y in skin space is -z... after rot: z = y
        jaw2, _ = M.jaw_labels(pts, base, -aah_y, rot)
        self.assertEqual(jaw2.tolist(), [False, False, False, True])
        self.assertFalse(M.jaw_labels(pts, base, np.zeros((4, 3)))[0].any())

    def test_sides_and_weights(self):
        self.assertTrue(M.is_jaw_bone("faceBone_C_Jaw"))
        self.assertFalse(M.is_jaw_bone("C_Head"))
        sf_pts = np.array([(0, 0, 0.0), (0, 0, -1.0), (0, 0.1, 0.0)])
        sf_w = [[("C_Head", 1.0)], [("faceBone_C_Jaw", 0.8), ("C_Head", 0.2)], [("C_Head", 0.6), ("faceBone_C_Jaw", 0.4)]]
        side = M.side_of(sf_w)
        self.assertEqual(side.tolist(), [False, True, False])
        pts = np.array([(0, 0, -0.1), (0, 0, -0.2)])               # both nearest to vertex 0 by distance
        w, d = M.copy_weights(pts, np.array([False, True]), sf_pts, sf_w, side)
        self.assertEqual(w[0], sf_w[0])
        self.assertEqual(w[1], sf_w[1])                            # a jaw vertex: the jaw tooth, though farther
        self.assertAlmostEqual(d[1], 0.8)
        w2, _ = M.copy_weights(pts, np.array([True, True]), sf_pts[[0, 2]], [sf_w[0], sf_w[2]],
                               np.array([False, False]))
        self.assertEqual(w2[0], sf_w[0])                           # no jaw teeth: the nearest of any

    def test_surface_distance(self):
        v, t = sphere()
        p = np.array([(0, 0, 1.5), (0, 0, 0.5), (0.0, 0.0, 0.0)])
        d = M.surface_distance(p, v, t)
        self.assertGreater(d[0], 0.45)
        self.assertLess(d[1], -0.4)
        self.assertLess(d[2], -0.9)
        self.assertTrue(np.allclose(M.surface_distance(p, v, t[:, [0, 2, 1]]), d))   # either winding

    def test_viewer(self):
        v, t = sphere(8, 4)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m.html")
            M.viewer(p, {"male": [("Skyrim", [(v, t, 0xffffff, None, True), (v * 0.5, t, None,
                                                                              np.arange(len(v)) % 2 == 0, False)])]})
            with open(p, encoding="utf-8") as fh:
                s = fh.read()
            self.assertIn('"l": "Skyrim"', s)
            self.assertNotIn("__DATA__", s)


class MainTests(unittest.TestCase):
    def test_main_with_stubs(self):
        # heads: a unit sphere (Starfield, metres) and the same sphere in Skyrim units (x 70); the "orc" mouth a small
        # sphere inside the mouth area whose lower half drops in Aah; Starfield's teeth: a sphere with jaw / head bones
        hv, ht = sphere()
        mv, mt = sphere(8, 4, 0.1)
        mouth = mv * 70 + (0, 0.8 * 70, 0)
        aah = np.where(mouth[:, 2:3] < mouth[:, 2].mean(), [(0, 0, -1.0)], [(0, 0, 0.0)])
        tri = {"base": mouth, "morphs": [{"name": "Aah", "deltas": aah}]}
        head = types.SimpleNamespace(vertices=hv, triangles=ht, model_xf=np.eye(4))
        races = {"faces": ht, "morphs": [{"name": "OrcRace", "deltas": np.zeros_like(hv)}]}
        fake_rp = types.SimpleNamespace(race_transfer=lambda sky, sf, female, smooth, ff: (
            head, hv * 70, races, (1 / 70, np.eye(3), np.zeros(3), 0.008), {"OrcRace": np.zeros_like(hv)},
            {"alignment": {"rms_m": 0.008}}))
        tw = [[("faceBone_C_Jaw", 1.0)] if p[2] < 0 else [("C_Head", 1.0)] for p in mv]
        import face_fit
        saved = (sys.modules.get("race_probe"), M.race_heads_archives, M.skyrim_mesh, M.sf_teeth,
                 face_fit.hkx_to_af.read_any, M.skyrimtri.parse)
        sys.modules["race_probe"] = fake_rp
        M.race_heads_archives = lambda d: None
        M.skyrim_mesh = lambda data: (mouth, mt, mouth, np.eye(4))
        M.sf_teeth = lambda sf, female, ff, hp, node=None, head_pts=None: (
            mv + (0, 0.8, 0), tw, mt, "meshes/teeth.nif", {"matrix": np.eye(4), "report": {"used": "stub"}})
        face_fit.hkx_to_af.read_any = lambda p, sky: b"x"
        M.skyrimtri.parse = lambda d, deltas=False: tri
        try:
            with tempfile.TemporaryDirectory() as d:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(M.main(["--skyrim-data", d, "--starfield", d, "--out", d]), 0)
                with open(os.path.join(d, "mouth_probe.json")) as fh:
                    rep = json.load(fh)
                self.assertTrue(os.path.exists(os.path.join(d, "mouth_view.html")))
        finally:
            if saved[0] is None:
                sys.modules.pop("race_probe", None)
            else:
                sys.modules["race_probe"] = saved[0]
            (M.race_heads_archives, M.skyrim_mesh, M.sf_teeth, face_fit.hkx_to_af.read_any,
             M.skyrimtri.parse) = saved[1:]
        orc = rep["male"]["mouths"]["orc"]
        self.assertEqual(orc["vertices"], len(mv))
        self.assertGreater(orc["jaw_vertices"], 0)
        self.assertLess(orc["jaw_vertices"], len(mv))
        self.assertEqual(orc["weights"]["bones"], ["C_Head", "faceBone_C_Jaw"])
        self.assertLess(orc["weights"]["nearest_tooth_m_max"], 1e-6)       # placed exactly on the stub teeth
        self.assertLess(orc["vs_head_surface"]["difference_m_max"], 1e-6)  # same head both sides
        self.assertEqual(rep["male"]["starfield_teeth"]["jaw_bones"], ["faceBone_C_Jaw"])


if __name__ == "__main__":
    unittest.main()


class ModelSpaceTests(unittest.TestCase):
    def test_bone_route_when_the_overall_transform_is_identity(self):
        """2026-11-09: vanilla eyesmale.nif / maleheadargonian.nif have an identity NiSkinData overall transform with
        vertices in bone space; the model position is bone world x skin->bone."""
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import skyrim_fixtures as F
        from fo4sf import facefit, nif as nifmod, skyrimskin
        n = F.SseNif()
        root, head = n.reserve("NiNode"), n.reserve("NiNode")
        n.node(root, b"NPC Root [Root]", [head])
        n.node(head, b"NPC Head [Head]", [], t=(0, 0, 120))
        nf = nifmod.parse(n.bytes())
        ident = skyrimskin.Bind((1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)
        shape = types.SimpleNamespace(bones=[b"NPC Head [Head]"], binds=[skyrimskin.Bind((1, 0, 0, 0, 1, 0, 0, 0, 1),
                                                                                       (0, 0, 2), 1.0)],
                                      weights=[[(0, 1.0)]], skin_transform=ident)
        m = facefit.skyrim_model_matrix(nf, shape)
        self.assertTrue(np.allclose(facefit.apply4(m, np.array([[1.0, 0, 0]])), [[1, 0, 122]]))
        shape.bones = [b"Missing"]                                        # no node: the overall transform
        self.assertTrue(np.allclose(facefit.skyrim_model_matrix(nf, shape), np.eye(4)))

    def test_teeth_morphs_report_the_jaw_key(self):
        from fo4sf import sfmorph, sfplugin
        hdr = lambda t: __import__("struct").pack("<4sIII", t, 0, 0, 0) + bytes(8)      # noqa: E731
        tcmp = __import__("struct").pack("<H", 26) + b"Meshes\\Morphs\\Teeth\\Perf" + b"\0"
        with tempfile.TemporaryDirectory() as d:
            sf = os.path.join(d, "Data")
            os.makedirs(sf)
            with open(os.path.join(sf, "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build([
                    (b"MRPH", hdr(b"MRPH"), [(b"EDID", sfplugin.zs("MORPH_Teeth")), (b"TMPP", tcmp)], 0x5000),
                    (b"HDPT", hdr(b"HDPT"), [(b"EDID", sfplugin.zs(M.SF_TEETH_PART[False])),
                                             (b"MNAM", (0x5000).to_bytes(4, "little"))], 0x5001)],
                    {"hedr_version": 0.96, "form_version": 555}))
            teeth = np.array([[0, 0, 1.70], [0.01, 0, 1.70], [0, 0, 1.66], [0.01, 0, 1.66]])
            md = sfmorph.build(4, ["JawOpen", "Smile"], {"JawOpen": {2: (0, 0, -0.01), 3: (0, 0, -0.01)},
                                                         "Smile": {0: (0.002, 0, 0)}})
            seen = []

            def vf(rel, data):
                seen.append(rel)
                return md, rel
            ff = types.SimpleNamespace(hkx_to_af=types.SimpleNamespace(vanilla_file=vf))
            rep = M.teeth_morphs(sf, False, ff, teeth)
        self.assertEqual(seen, ["meshes/morphs/teeth/perf/morph.dat"])
        keys = rep["folders"]["TMPP"]["per_key"]
        self.assertEqual(keys["JawOpen"], {"vertices": 2, "lower_mean_drop_m": 0.01,
                                           "lower_mean_delta_m": [0.0, 0.0, -0.01]})
        self.assertEqual(rep["MRPH"], "MORPH_Teeth")
        self.assertIn("error", M.teeth_morphs(os.path.join(d, "nope"), False, ff))

    def test_teeth_placed_through_the_c_head_binds(self):
        """2026-11-09 owner run: Starfield's teeth 1.6 m below the mouths. Their .mesh is in C_Head's frame (x up);
        the head's node takes the head to model space, and the two C_Head binds relate the teeth to the head."""
        R = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], float)        # C_Head frame x up -> model z up
        H = np.eye(4)
        H[:3, :3], H[:3, 3] = R, (0, 0, 1.6)
        head_local = np.array([[x, y, z] for x in (-0.12, 0.12) for y in (-0.1, 0.1) for z in (-0.1, 0.1)])
        head_model = facefit.apply4(H, head_local)
        bind = lambda t: ((0, 0, 0, 0.2), (1, 0, 0, 0, 1, 0, 0, 0, 1), t, 1.0)       # noqa: E731
        skin = lambda t: {"bones": [b"C_Head"], "binds": [bind(t)]}                    # noqa: E731
        teeth_local = np.array([[-0.5, 0.05, 0.0], [-0.52, 0.06, 0.01]])  # 0.5 m off in its own mesh frame
        M, rep = M_.teeth_placement(teeth_local, H, skin((0, 0, 0)), skin((0.45, 0, 0)), head_model, np.eye(4))
        self.assertEqual(rep["used"], "C_Head binds + head node")
        got = facefit.apply4(M, teeth_local)
        self.assertTrue(np.allclose(got, facefit.apply4(H, teeth_local + (0.45, 0, 0))))
        self.assertFalse(rep["candidates"]["head node"]["inside_head_box"])
        self.assertFalse(rep["candidates"]["teeth node"]["inside_head_box"])
        M2, rep2 = M_.teeth_placement(teeth_local + (0.45, 0, 0), H, {}, {}, head_model)   # no binds: the head node
        self.assertEqual(rep2["used"], "head node")
        self.assertTrue(np.allclose(M2, H))

    def test_teeth_morph_deltas_turned_into_model_space(self):
        """jawOpen moves the lower teeth along C_Head's x (up in its frame): reported as a drop once turned."""
        from fo4sf import sfmorph, sfplugin
        hdr = lambda t: __import__("struct").pack("<4sIII", t, 0, 0, 0) + bytes(8)      # noqa: E731
        tcmp = __import__("struct").pack("<H", 26) + b"Meshes\\Morphs\\Teeth\\Perf" + b"\0"
        with tempfile.TemporaryDirectory() as d:
            sf = os.path.join(d, "Data")
            os.makedirs(sf)
            with open(os.path.join(sf, "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build([
                    (b"MRPH", hdr(b"MRPH"), [(b"EDID", sfplugin.zs("MORPH_Teeth")), (b"TMPP", tcmp)], 0x5000),
                    (b"HDPT", hdr(b"HDPT"), [(b"EDID", sfplugin.zs(M_.SF_TEETH_PART[False])),
                                             (b"MNAM", (0x5000).to_bytes(4, "little"))], 0x5001)],
                    {"hedr_version": 0.96, "form_version": 555}))
            teeth = np.array([[0, 0, 1.70], [0.01, 0, 1.70], [0, 0, 1.66], [0.01, 0, 1.66]])
            md = sfmorph.build(4, ["jawOpen"], {"jawOpen": {2: (-0.01, 0, 0), 3: (-0.01, 0, 0)}})
            ff = types.SimpleNamespace(hkx_to_af=types.SimpleNamespace(vanilla_file=lambda rel, data: (md, rel)))
            T = np.eye(4)
            T[:3, :3], T[:3, 3] = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], float), (0, 0, 1.6)
            raw = M_.teeth_morphs(sf, False, ff, teeth)
            turned = M_.teeth_morphs(sf, False, ff, teeth, T)
        self.assertEqual(raw["folders"]["TMPP"]["per_key"]["jawOpen"]["lower_mean_drop_m"], 0.0)
        self.assertEqual(turned["folders"]["TMPP"]["per_key"]["jawOpen"]["lower_mean_drop_m"], 0.01)
