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
            first = len(glob.glob(os.path.join(out, "Data", "meshes", "lod", "generated", "composite", "*", "*.nif")))
            so.main(["lod", "--out", out, "--lod-min-radius", "100000"])          # a rerun cleans up the first
            self.assertEqual(glob.glob(os.path.join(out, "Data", "meshes", "lod", "generated", "composite", "*",
                                                    "*.nif")), [])
            self.assertGreater(first, 0)
            so.main(["lod", "--out", out, "--lod-min-radius", "1", "--lod-layer", "NA_LOD_TheMast"])
            one = glob.glob(os.path.join(out, "Data", "meshes", "lod", "generated", "composite", "*", "*.nif"))
            one_obj = json.load(open(os.path.join(out, "objects.json")))
            so.main(["lod", "--out", out, "--lod-min-radius", "1"])
            obj = json.load(open(os.path.join(out, "objects.json")))
            lodset = open(os.path.join(out, "Data", "lodsettings", "sky_tamriel.lod"), "rb").read()
            files = glob.glob(os.path.join(out, "Data", "meshes", "lod", "generated", "composite", "sky_tamriel", "*.nif"))
            rock_ref = next(r for r in obj["refs"] if r["src"] == "002002:Skyrim.esm")
            rock_base = obj["bases"][rock_ref["base"]]
            mine = [f for f in files if os.path.basename(f).startswith(rock_base["edid"].lower() + "_lod_")]
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
            lod_dir_files = sorted(os.listdir(os.path.join(out, "Data", "lodsettings")))
            any_nif = open(files[0], "rb").read()
            first_sphere = skyrimlod._first_sphere(nif.parse(open(files[-1], "rb").read()))

            seen_meshes = {}

            def read_vanilla(name):                    # our first composite stands in for Gagarin's crane
                if name.endswith(".mesh"):             # kept: vanilla_test removes our own meshes
                    if name not in seen_meshes:
                        seen_meshes[name] = open(os.path.join(out, "Data", *name.split("\\")), "rb").read()
                    return seen_meshes[name]
                return any_nif
            n = skyrimlod.vanilla_test(os.path.join(out, "Data"), "SKY_Tamriel", read_vanilla)
            ov = skyrimlod.override_test(os.path.join(out, "Data"), [
                ("meshes\\lod\\generated\\composite\\NewAtlantis\\NA_LOD_X_0_0_lod_0_cell0.nif", any_nif)], read_vanilla)
            ov_nif = nif.parse(open(os.path.join(out, "Data", *ov[0].split("/")), "rb").read())
            moved = nif.parse(open(files[-1], "rb").read())
            tr = nif._av_transform(moved.blocks[0])[0]
            mg = sfnif.parse_bsgeometry(next(moved.blocks[i] for i in range(len(moved.blocks))
                                             if moved.type_of(i) == "BSGeometry"))
            mm = sfmesh.parse(open(os.path.join(out, "Data", "geometries", *mg.meshes[0].path.decode().split("\\"))
                                   + ".mesh", "rb").read())
            self.assertTrue(mm.positions)
        self.assertEqual(n, len(files))
        self.assertEqual(tuple(tr), (0.0, 0.0, 0.0))                         # identity root, as vanilla
        self.assertEqual(ov[0], "meshes/lod/generated/composite/newatlantis/na_lod_x_0_0_lod_0_cell0.nif")
        self.assertTrue(ov[1].startswith("geometries/") and ov_nif.strings[0].startswith(b"Composite\\newatlantis\\"))
        self.assertLess(abs(mg.sphere[2] - first_sphere[2] - 60.0), 1.0)     # baked into the vertices
        self.assertEqual(struct.unpack("<5i", lodset)[3:], (0, 0))
        self.assertTrue(rock_base.get("distant_lod"))
        lo, hi = rock_base["bounds"]                                          # OBND for every static
        self.assertTrue(all(a < b for a, b in zip(lo, hi)))
        self.assertIn([cx, cy], rock_ref["large_cells"])                     # a large reference (WRLD RNAM)
        self.assertTrue(rock_ref.get("full_lod"))                              # REFR Is Full LOD
        self.assertTrue(all("large_cells" not in r or obj["bases"][r["base"]].get("distant_lod") for r in obj["refs"]))
        self.assertEqual(rock_base.get("lod_layer"), rock_base["edid"] + "_LOD")
        self.assertEqual(sorted({f.rsplit("_lod_", 1)[1][0] for f in mine}), ["0", "1", "2", "3"])
        self.assertTrue(pts)
        c = np.mean(np.asarray(pts), 0)
        self.assertLess(abs(c[0] - rock_ref["pos"][0]) + abs(c[1] - rock_ref["pos"][1]), 40.0)  # world coordinates
        self.assertTrue(ok, [x for x in rep["checks"] if not x[1]])
        self.assertIn("lod: lodsettings", log.getvalue())
        self.assertTrue(one and all(os.path.basename(f).startswith("na_lod_themast_") for f in one))
        self.assertLessEqual(len(one), first)                                  # one file per block, not per object
        self.assertEqual({b["lod_layer"] for b in one_obj["bases"] if b.get("distant_lod")}, {"NA_LOD_TheMast"})
        self.assertEqual(lod_dir_files, ["sky_tamriel.lod"])                 # nothing else gets packed there

    def test_installer_packs_lodsettings(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("deploy", os.path.join(ROOT, "scripts", "deploy_skyrim_exterior.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIn("lodsettings", mod.DATA_DIRS)


if __name__ == "__main__":
    unittest.main()
