"""scripts/armor/hair_probe.py: reading a vanilla hairstyle's materials and textures, on synthetic files only."""
import os
import struct
import sys
import tempfile
import unittest
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import convert_material as cm, nif, sfnif  # noqa: E402
import hair_probe as HP  # noqa: E402


class ProbeTests(unittest.TestCase):
    def test_material_paths_of_a_nif(self):
        ident = (1, 0, 0, 0, 1, 0, 0, 0, 1)
        sh = sfnif.SkinnedShape(b"Hair", b"aa\\bb", 3, 3, "materials\\actors\\hair\\bob.mat", [b"C_Head"],
                                [((0.0, 0.0, 0.0, 1.0), ident, (0, 0, 0), 1.0)])
        raw = nif.serialize(sfnif.build_skinned_nif(b"Hair", [sh]))
        self.assertEqual(HP.material_paths(raw), ["materials\\actors\\hair\\bob.mat"])

    def test_material_info_and_stats(self):
        mat = cm.build_hair_mat("X", {"Albedo": "Data\\a.dds", "Opacity": "Data\\o.dds", "DepthOffset": "Data\\z.dds"},
                                {"MaxDepthOffset": "0.02"})
        info = HP.material_info(mat)
        self.assertEqual(info["shader"], "Hair1Layer")
        self.assertEqual(info["textures"], {"Albedo": "Data\\a.dds", "Opacity": "Data\\o.dds",
                                            "DepthOffset": "Data\\z.dds"})
        self.assertEqual(info["hair_settings"]["MaxDepthOffset"], "0.02")
        px = np.zeros((32, 64, 4), np.uint8)
        px[:, ::2, 0] = 255                                       # strands down the texture
        st = HP.texture_stats("Opacity", px)
        self.assertEqual(st["size"], [64, 32])
        self.assertEqual(st["solid_share"], 0.5)
        self.assertLess(st["strands_along_u_share"], 0.1)
        z = HP.texture_stats("DepthOffset", np.full((8, 8, 4), 40, np.uint8))
        self.assertEqual(z["percentiles_10_50_90"], [40.0, 40.0, 40.0])

    def test_png_and_shrink(self):
        img = (np.arange(600 * 300) % 255).astype(np.uint8).reshape(300, 600)
        small = HP.shrink(img, 128)
        self.assertLessEqual(max(small.shape), 128)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.png")
            HP.write_png(p, small)
            with open(p, "rb") as fh:
                data = fh.read()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        w, h = struct.unpack(">II", data[16:24])
        self.assertEqual((w, h), (small.shape[1], small.shape[0]))
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        self.assertEqual(len(zlib.decompress(idat)), h * (w + 1))


if __name__ == "__main__":
    unittest.main()
