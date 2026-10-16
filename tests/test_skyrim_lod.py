"""Synthetic-fixture tests for distant-object LOD (src/fo4sf/skyrimlod.py, make_skyrim_objects.py lod). No game data."""
import contextlib
import glob
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import nif, sfmesh, sfnif, skyrimlod, textures  # noqa: E402


class GridTests(unittest.TestCase):
    def test_lodsettings_and_blocks(self):
        data, (x0, y0, size) = skyrimlod.lodsettings(-36, 36)
        self.assertEqual(struct.unpack("<5i", data), (-36, -36, 80, 0, 0))
        # NewAtlantis (vanilla): origin -35, lod1 blocks odd, lod2 at 1 mod 4, lod3 at -3 mod 8
        self.assertEqual(skyrimlod.block_of((2, 2), (-35, -59), 0), (2, 2))
        self.assertEqual(skyrimlod.block_of((2, 2), (-35, -59), 1), (1, 1))
        self.assertEqual(skyrimlod.block_of((2, 2), (-35, -59), 2), (1, 1))
        self.assertEqual(skyrimlod.block_of((2, 2), (-35, -59), 3), (-3, -3))


class CommandTests(unittest.TestCase):
    def test_stage_then_lod(self):
        import make_cw_overlays as cw
        import make_skyrim_objects as so
        import make_skyrim_overlay as sk
        import skyrim_fixtures as F
        import test_skyrim_objects as T
        with tempfile.TemporaryDirectory() as tmp, T.starfield_inputs(tmp) as sf, \
                mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([0, 0, 0, 0, 0, 0, 0, 1]))), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            esm = T.write_esm(os.path.join(tmp, "Skyrim.esm"))
            data = F.skyrim_data(os.path.join(tmp, "Data"))
            terrain, work, out = (os.path.join(tmp, d) for d in ("terrain", "work", "out"))
            sk.main(["build", "--skyrim", esm, "--sf-data", tmp, "--out", terrain, "--mask-writer", "builtin",
                     "--arrival", ""])
            so.main(["export", "--skyrim", esm, "--work", work])
            so.main(["select", "--work", work, "--terrain", terrain])
            texconv = os.path.join(tmp, "texconv.exe")
            open(texconv, "wb").write(b"MZ")
            so.main(["convert", "--work", work, "--skyrim-data", data, "--content-resources", sf["content_resources"],
                     "--texconv", texconv, "--collision-template", sf["collision_template"]])
            so.main(["stage", "--work", work, "--terrain", terrain, "--out", out])
            so.main(["lod", "--out", out, "--lod-min-radius", "1"])
            obj = json.load(open(os.path.join(out, "objects.json")))
            lodset = open(os.path.join(out, "Data", "lodsettings", "sky_tamriel.lod"), "rb").read()
            files = glob.glob(os.path.join(out, "Data", "meshes", "lod", "generated", "composite", "sky_tamriel", "*.nif"))
            rock_ref = next(r for r in obj["refs"] if r["src"] == "002002:Skyrim.esm")
            rock_base = obj["bases"][rock_ref["base"]]
            mine = [f for f in files if os.path.basename(f).startswith(rock_base["edid"].lower() + "_")]
            import math
            cx, cy = (int(math.floor(v / 100.0)) for v in rock_ref["pos"][:2])
            lv0 = [f for f in mine if f.endswith(f"_{cx}_{cy}_lod_0_cell0.nif")]
            pts = []
            for f in lv0:
                n = nif.parse(open(f, "rb").read())
                for i in range(len(n.blocks)):
                    if n.type_of(i) == "BSGeometry":
                        g = sfnif.parse_bsgeometry(n.blocks[i])
                        p = g.meshes[0].path.decode().split("\\")
                        m = sfmesh.parse(open(os.path.join(out, "Data", "geometries", *p) + ".mesh", "rb").read())
                        pts += [sfmesh.decode_position(v, m.scale) for v in m.positions]
            ok, rep = so.check(out)
        self.assertEqual(struct.unpack("<5i", lodset)[3:], (0, 0))
        self.assertTrue(rock_base.get("distant_lod"))
        self.assertEqual(sorted({f.split("_lod_")[1][0] for f in mine}), ["0", "1", "2", "3"])
        self.assertTrue(pts)
        c = np.mean(np.asarray(pts), 0)
        self.assertLess(abs(c[0] - rock_ref["pos"][0]) + abs(c[1] - rock_ref["pos"][1]), 40.0)  # world coordinates
        self.assertTrue(ok, [x for x in rep["checks"] if not x[1]])
        self.assertIn("lod: lodsettings", log.getvalue())


if __name__ == "__main__":
    unittest.main()
