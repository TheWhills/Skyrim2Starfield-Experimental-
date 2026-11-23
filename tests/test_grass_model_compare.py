"""scripts/terrain/grass_model_compare.py (2026-11-23): describe a Starfield grass NIF block by block."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import nif as nifmod, sfnif  # noqa: E402
import grass_model_compare as G  # noqa: E402


class DescribeTest(unittest.TestCase):
    def test_static_nif(self):
        s = sfnif.StaticShape(b"Blade", b"aaaa\\bbbb", 30, 12, "s2s\\grass.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        data = nifmod.serialize(sfnif.build_static_nif(b"Grass", [s]))
        d = G.describe(data)
        types = [b["type"] for b in d["blocks"]]
        self.assertEqual(types, ["NiNode", "BSXFlags", "BSGeometry", "NiIntegerExtraData", "BSLightingShaderProperty"])
        self.assertEqual(d["meshes"], ["geometries\\aaaa\\bbbb.mesh"])
        self.assertEqual(d["materials"], ["s2s\\grass.mat"])
        g = d["blocks"][2]
        self.assertEqual((g["name"], g["meshes"][0]["verts"]), ("Blade", 12))
        self.assertEqual(d["blocks"][0]["name"], "Grass")
        self.assertEqual(d["blocks"][1]["value"], 0)

    def test_archives_loose_and_mesh_head(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "geometries", "aa"))
            with open(os.path.join(d, "geometries", "aa", "b.mesh"), "wb") as fh:
                fh.write(bytes(range(80)))
            arcs = G.Archives([], loose=d)
            self.assertEqual(len(arcs.read("geometries/aa/b.mesh")), 80)
            self.assertIsNone(arcs.read("geometries\\aa\\c.mesh"))
            self.assertEqual(G.mesh_head(arcs.read("geometries\\aa\\b.mesh"))["size"], 80)
        self.assertIsNone(G.mesh_head(b""))


class MaterialsTest(unittest.TestCase):
    def test_grass_materials(self):
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_formats import build_ba2_v1_gnrl
        s = sfnif.StaticShape(b"Blade", b"aa\\bb", 30, 12, "Materials\\Landscape\\Grass\\Bladed\\G1.mat", (0, 0, 0, 1),
                              (0, 0, 0, 1, 1, 1))
        nif = nifmod.serialize(sfnif.build_static_nif(b"Grass", [s]))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Starfield - Meshes01.ba2")
            with open(p, "wb") as fh:
                fh.write(build_ba2_v1_gnrl({"meshes\\landscape\\grass\\a.nif": nif,
                                            "meshes\\landscape\\grass\\b.nif": nif,
                                            "meshes\\setdressing\\c.nif": nif}))
            mats = G.grass_materials([p])
        self.assertEqual(list(mats), ["Materials\\Landscape\\Grass\\Bladed\\G1.mat"])
        self.assertEqual(len(mats["Materials\\Landscape\\Grass\\Bladed\\G1.mat"]), 2)


if __name__ == "__main__":
    unittest.main()
