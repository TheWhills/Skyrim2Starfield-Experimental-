"""scripts/armor/os_export.py: tool-answer parsing, unit calibration, tangents, weight limit, armor records, and the
pull against a fake Outfit Studio (synthetic)."""
import os
import struct
import sys
import tempfile
import unittest
import json
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import sfplugin  # noqa: E402
import os_export as E  # noqa: E402

z = sfplugin.zs
HDR = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(8)       # noqa: E731


class ParseTests(unittest.TestCase):
    def test_geometry_forms(self):
        a = E.geometry({"positions": [[0, 0, 0], [1, 0, 0]], "normals": [[0, 0, 1]] * 2, "uvs": [[0, 0], [1, 0]],
                        "triangles": [[0, 1, 1]]})
        self.assertEqual((len(a["positions"]), a["triangles"]), (2, [(0, 1, 1)]))
        b = E.geometry({"vertices": [{"index": 1, "position": [1, 0, 0], "uv": [1, 0]},
                                     {"index": 0, "position": [0, 0, 0], "uv": [0, 0]}],
                        "triangles": [{"vertices": [0, 1, 1]}]})
        self.assertEqual(b["positions"], [[0, 0, 0], [1, 0, 0]])                  # sorted by index
        self.assertEqual(b["triangles"], [(0, 1, 1)])

    def test_outfit_studio_lists(self):
        ans = {"bounds": {}, "triangleFormat": "[triangle index, vertex 1, vertex 2, vertex 3]",
               "triangleList": [[0, 0, 1, 2], [1, 2, 1, 3]],
               "positionFormat": "[vertex index, x, y, z]", "positionList": [[1, 1.0, 0, 0], [0, 0.0, 0, 0]],
               "normalFormat": "[vertex index, x, y, z]", "normalList": [[0, 0, 0, 1], [1, 0, 0, 1]],
               "uvFormat": "[vertex index, u, v]", "uvList": [[0, 0, 0], [1, 1, 0]]}
        g = E.geometry(ans)
        self.assertEqual(g["triangles"], [(0, 1, 2), (2, 1, 3)])
        self.assertEqual(g["positions"], [[0.0, 0, 0], [1.0, 0, 0]])                # by index
        self.assertEqual(g["uvs"], [[0, 0], [1, 0]])
        combined = {"vertexFormat": "[vertex index, x, y, z, nx, ny, nz, u, v]",
                    "vertexList": [[0, 1, 2, 3, 0, 0, 1, 0.5, 0.25]]}
        c = E.geometry(combined)
        self.assertEqual((c["positions"], c["normals"], c["uvs"]), ([[1, 2, 3]], [[0, 0, 1]], [[0.5, 0.25]]))
        real = {"bounds": {}, "triangleFormat": "[triangle index, vertex 1, vertex 2, vertex 3]",
                "triangleList": [[0, 1, 0, 2]], "triangles": 1, "vertices": 2,
                "vertexData": [{"index": 1, "normal": [0, 0, 1], "position": [1, 2, 3], "uv": [0.5, 0.5]},
                               {"index": 0, "normal": [0, 1, 0], "position": [0, 0, 0], "uv": [0, 0]}]}
        r = E.geometry(real)                     # the owner's answer, 2026-11-06
        self.assertEqual((r["positions"], r["normals"][1], r["triangles"]), ([[0, 0, 0], [1, 2, 3]], [0, 0, 1], [(1, 0, 2)]))
        self.assertEqual(E.weight_list({"bone": "C_Hips", "weightData": [{"index": 3, "weight": 0.4}]}), [(3, 0.4)])
        w = E.weight_list({"weightFormat": "[vertex index, weight]", "weightList": [[4, 0.75], [9, 0.25]]})
        self.assertEqual(w, [(4, 0.75), (9, 0.25)])

    def test_weights_and_bones(self):
        self.assertEqual(E.weight_list({"weights": [{"vertex": 3, "weight": 0.5}]}), [(3, 0.5)])
        self.assertEqual(E.weight_list({"weights": [[2, 1.0]]}), [(2, 1.0)])
        self.assertEqual(E.weight_list({"weights": {"7": 0.25}}), [(7, 0.25)])
        self.assertEqual(E.bone_names({"bones": [{"name": "C_Hips", "vertices": 3}, "L_Foot"]}), ["C_Hips", "L_Foot"])


class GeometryTests(unittest.TestCase):
    def test_fit_affine_recovers_units(self):
        rng = np.random.default_rng(1)
        meters = rng.uniform(-0.3, 1.8, (200, 3))
        shown = (meters - [0, 0.0018, 1.632]) * 69.99               # Outfit Studio's view of the body
        t, res = E.fit_affine(shown, meters)
        self.assertLess(res, 1e-9)
        self.assertTrue(np.allclose(E.apply(t, [[0, 0, -114.22]]), [[0, 0.0018, 1.632 - 114.22 / 69.99]]))
        self.assertTrue(np.allclose(E.turn_normals(t, [[0, 0, 5]]), [[0, 0, 1]]))

    def test_tangents_follow_u(self):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        nor = np.tile([0.0, 0.0, 1.0], (3, 1))
        t = E.tangents(pos, nor, [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)])
        self.assertTrue(np.allclose(t, [[1, 0, 0]] * 3))
        t2 = E.tangents(pos, nor, [(0, 0)] * 3, [(0, 1, 2)])               # no UV gradient: still unit, across n
        self.assertTrue(np.allclose(np.linalg.norm(t2, axis=1), 1) and np.allclose(t2 @ [0, 0, 1], 0))

    def test_limit_weights(self):
        w = E.limit_weights([{"a": 0.1, "b": 0.4, "c": 0.3, "d": 0.1, "e": 0.1}, {}], k=4)
        self.assertEqual([b for b, _ in w[0]], ["b", "c", "a", "d"])
        self.assertAlmostEqual(sum(x for _, x in w[0]), 1.0)
        self.assertEqual(w[1], [])


def sf_esm(path):
    recs = [(b"ARMA", HDR(b"ARMA"), [(b"EDID", z("Nightwear_AA")), (b"MOD2", z("Clothes\\nw_m.nif")),
                                     (b"MOD3", z("Clothes\\nw_f.nif")), (b"MOD4", z("Clothes\\nw_1st.nif"))], 0x1000),
            (b"ARMO", HDR(b"ARMO"), [(b"EDID", z(E.TEMPLATE_ARMOR)), (b"FULL", struct.pack("<I", 5)),
                                     (b"INDX", b"\0\0"), (b"MODL", struct.pack("<I", 0x1000)),
                                     (b"INDX", b"\1\0"), (b"MODL", struct.pack("<I", 0x1000))], 0x2000),
            (b"OTFT", HDR(b"OTFT"), [(b"EDID", z("SomeOutfit")), (b"INAM", struct.pack("<I", 0x2000))], 0x3000)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}))


class RecordTests(unittest.TestCase):
    def test_armor_records(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Starfield.esm")
            sf_esm(p)
            recs, rep = E.armor_records(p, "S2S\\Ralof_outfit.nif", "Ralof_outfit", 1, "Ralof's outfit")
        arma, armo, otft = recs
        self.assertEqual([r[0] for r in recs], [b"ARMA", b"ARMO", b"OTFT"])
        a = dict(arma[2])
        self.assertEqual((a[b"MOD2"], a[b"MOD3"]), (z("S2S\\Ralof_outfit.nif"),) * 2)
        self.assertEqual(a[b"MOD4"], z("Clothes\\nw_1st.nif"))                    # first person kept
        modl = [d for s, d in armo[2] if s == b"MODL"]
        self.assertEqual(modl, [struct.pack("<I", arma[3])])                     # one addon: ours
        self.assertEqual(dict(armo[2])[b"FULL"], z("Ralof's outfit"))
        self.assertEqual(dict(otft[2])[b"INAM"], struct.pack("<I", armo[3]))
        self.assertEqual(rep["template_addon"], "00001000")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Starfield.esm")
            sf_esm(p)
            recs, _ = E.armor_records(p, "S2S\\X.nif", "X", 1, "X", drop=["MOD4"])
        self.assertNotIn(b"MOD4", dict(recs[0][2]))                              # --drop-fields

    def test_field_text(self):
        self.assertEqual(E.field_text(b"\x05\x00Meshes\\a\\morph.dat\x00"), "Meshes\\a\\morph.dat  (21 bytes)")
        self.assertEqual(E.field_text(b"\x01\x02"), "0102")

    def test_nif_material(self):
        self.assertEqual(E.nif_material(b"xx\0Materials\\Clothes\\NW\\nw_01.mat\0yy"), "Materials\\Clothes\\NW\\nw_01.mat")
        self.assertEqual(E.nif_material(b"none"), "")


class Fake:
    """A project with a 4-vertex body and a 3-vertex gear shape; Outfit Studio units = (m - offset) * 70."""

    def __init__(self, real):
        self.real = real
        shown = (real - [0, 0, 1.6]) * 70.0
        self.data = {"Naked_M:0": {"positions": shown.tolist(), "normals": [[0, 0, 1]] * 4, "uvs": [[0, 0]] * 4,
                                   "triangles": [[0, 1, 2]]},
                     "Cuirass": {"positions": ((np.array([[0, 0.1, 1.0], [0.1, 0.1, 1.0], [0, 0.1, 1.1]]) -
                                                [0, 0, 1.6]) * 70).tolist(),
                                 "normals": [[0, 1, 0]] * 3, "uvs": [[0, 0], [1, 0], [0, 1]], "triangles": [[0, 1, 2]]}}

    def call(self, name, args):
        body = {}
        if name == "get_status":
            body = {"reference": {"shape": "Naked_M:0"}, "outfitShapes": ["Naked_M:0", "Cuirass"]}
        elif name == "list_shapes":
            body = {"shapes": [{"name": n, "vertices": len(d["positions"])} for n, d in self.data.items()]}
        elif name == "get_shape_geometry":
            d = self.data[args["shape"]]
            a, c = args["start"], args["count"]
            body = {k: d[k][a:a + c] for k in ("positions", "normals", "uvs")}
            if "triangles" in args["include"]:
                body["triangles"] = d["triangles"]
        elif name == "list_bones":
            body = {"bones": [{"name": "C_Chest"}, {"name": "C_Spine2"}]}
        elif name == "get_weights":
            body = {"weights": [{"vertex": v, "weight": 0.5} for v in range(3)]}
        return {"content": [{"type": "text", "text": json.dumps(body)}]}


ROT = (0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
SKIN = {"bones": [b"C_Chest", b"C_Spine2", b"C_Pelvis"],
        "binds": [((0.0, 0.0, 0.1, 0.2), ROT, (0.0, 0.0, -1.3), 1.0),
                  ((0.0, 0.0, 0.0, 0.3), ROT, (0.0, 0.0, -1.1), 1.0),
                  ((0.0, 0.0, 0.0, 0.3), ROT, (0.0, 0.0, -0.9), 1.0)]}


class ExportTests(unittest.TestCase):
    def test_pull_and_calibrate(self):
        real = np.array([[0, 0, 0], [0.2, 0, 0], [0, 0.2, 0.5], [0, 0, 1.5]], float)
        world = {"C_Chest": np.eye(4), "C_Spine2": np.eye(4)}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E.hkx_to_af, "vanilla_file", lambda p, s: (b"x", p)), \
                mock.patch.object(E.facefit, "starfield_head_parts", lambda b: (["aa\\bb"], SKIN)), \
                mock.patch.object(E.sfmesh, "parse", lambda b: None), \
                mock.patch.object(E.facefit, "mesh_arrays", lambda m: (real, [])), \
                mock.patch.object(E.npc_hair, "skeleton_world", lambda b: world):
            rep = E.export(Fake(real), "data", "Ralof_outfit", d)
        self.assertLess(rep["calibration"]["rms_m"], 1e-9)
        self.assertAlmostEqual(rep["calibration"]["scale"], 1 / 70.0, places=6)
        sh = rep["shapes_data"][0]
        self.assertTrue(np.allclose(sh.positions[0], [0, 0.1, 1.0]))            # back in metres
        self.assertEqual(sh.weights[0], [("C_Chest", 0.5), ("C_Spine2", 0.5)])
        self.assertEqual(rep["shapes"]["Cuirass"]["unweighted"], 0)

    def test_written_files_parse_back(self):
        from fo4sf import nif as nifmod
        real = np.array([[0, 0, 0], [0.2, 0, 0], [0, 0.2, 0.5], [0, 0, 1.5]], float)
        world = {"C_Chest": np.eye(4), "C_Spine2": np.eye(4)}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E.hkx_to_af, "vanilla_file", lambda p, s: (b"x", p)), \
                mock.patch.object(E.facefit, "starfield_head_parts", lambda b: (["aa\\bb"], SKIN)), \
                mock.patch.object(E.sfmesh, "parse", lambda b: None), \
                mock.patch.object(E.facefit, "mesh_arrays", lambda m: (real, [])), \
                mock.patch.object(E.npc_hair, "skeleton_world", lambda b: world):
            rep = E.export(Fake(real), "data", "Ralof_outfit", d)
        files = E.body_nif_files(rep["shapes_data"], ["Materials\\x.mat"], rep["body_binds"], "S2S/Ralof_outfit")
        self.assertIn("meshes/S2S/Ralof_outfit.nif", files)
        meshes = [k for k in files if k.endswith(".mesh")]
        self.assertEqual(len(meshes), 1)
        m = E.sfmesh.parse(files[meshes[0]])
        self.assertEqual((len(m.positions), m.weights_per_vertex), (3, 4))
        n = nifmod.parse(files["meshes/S2S/Ralof_outfit.nif"])
        self.assertIn("BSGeometry", [n.type_of(i) for i in range(len(n.blocks))])
        from fo4sf import sfnif
        skin = sfnif.parse_skin(n)
        self.assertEqual(skin["bones"], [b"C_Chest", b"C_Spine2"])           # only the bones the gear uses
        got = skin["binds"][0]
        self.assertTrue(np.allclose(got[1], ROT) and np.allclose(got[2], (0, 0, -1.3)))   # the body's bind, as is
        self.assertAlmostEqual(got[0][3], 0.2 + E.SPHERE_MARGIN, places=5)

    def test_skip_leaves_shape_out(self):
        real = np.array([[0, 0, 0], [0.2, 0, 0], [0, 0.2, 0.5], [0, 0, 1.5]], float)
        world = {"C_Chest": np.eye(4), "C_Spine2": np.eye(4)}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E.hkx_to_af, "vanilla_file", lambda p, s: (b"x", p)), \
                mock.patch.object(E.facefit, "starfield_head_parts", lambda b: (["aa\\bb"], SKIN)), \
                mock.patch.object(E.sfmesh, "parse", lambda b: None), \
                mock.patch.object(E.facefit, "mesh_arrays", lambda m: (real, [])), \
                mock.patch.object(E.npc_hair, "skeleton_world", lambda b: world):
            with self.assertRaises(E.os_convert.StepFailed):          # nothing left but the body
                E.export(Fake(real), "data", "X", d, skip=["cuirass"])

    def test_reverse_order(self):
        real = np.array([[0, 0, 0], [0.2, 0, 0], [0, 0.2, 0.5], [0, 0, 1.5]], float)
        world = {"C_Chest": np.eye(4), "C_Spine2": np.eye(4)}
        fake = Fake(real)
        fake.data["Belt"] = dict(fake.data["Cuirass"])
        orig = fake.call

        def call(name, args):
            if name == "get_status":
                return {"content": [{"type": "text", "text": json.dumps(
                    {"reference": {"shape": "Naked_M:0"}, "outfitShapes": ["Naked_M:0", "Cuirass", "Belt"]})}]}
            return orig(name, args)
        fake.call = call
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E.hkx_to_af, "vanilla_file", lambda p, s: (b"x", p)), \
                mock.patch.object(E.facefit, "starfield_head_parts", lambda b: (["aa\\bb"], SKIN)), \
                mock.patch.object(E.sfmesh, "parse", lambda b: None), \
                mock.patch.object(E.facefit, "mesh_arrays", lambda m: (real, [])), \
                mock.patch.object(E.npc_hair, "skeleton_world", lambda b: world):
            rep = E.export(fake, "data", "X", d, reverse=True)
        self.assertEqual([sh.name for sh in rep["shapes_data"]], [b"Belt", b"Cuirass"])

    def test_bone_missing_from_body_stops(self):
        real = np.array([[0, 0, 0], [0.2, 0, 0], [0, 0.2, 0.5], [0, 0, 1.5]], float)
        world = {"C_Chest": np.eye(4), "C_Spine2": np.eye(4)}
        skin = {"bones": [b"C_Chest"], "binds": SKIN["binds"][:1]}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E.hkx_to_af, "vanilla_file", lambda p, s: (b"x", p)), \
                mock.patch.object(E.facefit, "starfield_head_parts", lambda b: (["aa\\bb"], skin)), \
                mock.patch.object(E.sfmesh, "parse", lambda b: None), \
                mock.patch.object(E.facefit, "mesh_arrays", lambda m: (real, [])), \
                mock.patch.object(E.npc_hair, "skeleton_world", lambda b: world):
            with self.assertRaises(E.os_convert.StepFailed):
                E.export(Fake(real), "data", "X", d)

    def test_unknown_bone_stops(self):
        real = np.array([[0, 0, 0], [0.2, 0, 0], [0, 0.2, 0.5], [0, 0, 1.5]], float)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E.hkx_to_af, "vanilla_file", lambda p, s: (b"x", p)), \
                mock.patch.object(E.facefit, "starfield_head_parts", lambda b: (["aa\\bb"], SKIN)), \
                mock.patch.object(E.sfmesh, "parse", lambda b: None), \
                mock.patch.object(E.facefit, "mesh_arrays", lambda m: (real, [])), \
                mock.patch.object(E.npc_hair, "skeleton_world", lambda b: {"C_Chest": np.eye(4)}):
            with self.assertRaises(E.os_convert.StepFailed):
                E.export(Fake(real), "data", "X", d)


if __name__ == "__main__":
    unittest.main()
