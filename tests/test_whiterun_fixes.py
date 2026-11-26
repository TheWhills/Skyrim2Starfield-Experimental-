"""Owner's Whiterun test 2026-11-26 (synthetic): land the city's cells hide (XCLC), references Skyrim starts disabled
through their enable parent, and models whose root node carries a transform Skyrim ignores."""
import json
import math
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "terrain"))

from fo4sf import btd, nif as nifmod, skyrimland, skyrimnif, skyrimrefs  # noqa: E402
import make_skyrim_overlay as MSO  # noqa: E402

SP = 100.0 / 128                                    # BTD sample spacing, m


class HiddenLandTests(unittest.TestCase):
    def test_quadrant_order(self):
        self.assertEqual(skyrimland.hidden_quadrants({(5, -2): 0x1}), {(10, -4)})          # SW
        self.assertEqual(skyrimland.hidden_quadrants({(5, -2): 0x8}), {(11, -3)})          # NE
        self.assertEqual(skyrimland.hidden_quadrants({(0, 0): 0x6}), {(1, 0), (0, 1)})     # SE, NW

    def test_mask_keeps_the_edges_of_visible_quadrants(self):
        # samples every 64 units (one per 64 / 70 m); quadrants (0, 0) and (1, 0) hidden, everything else visible
        m = skyrimland.hidden_sample_mask((80, 80), 0.0, 0.0, 64 / 70.0, {(0, 0), (1, 0)})
        self.assertFalse(m[0, 0] or m[0, 5] or m[5, 0])          # x = 0 / y = 0: the edge with visible quadrants
        self.assertTrue(m[5, 5] and m[31, 31])                   # inside quadrant (0, 0)
        self.assertTrue(m[5, 32])                                # x = 2048: between two hidden quadrants
        self.assertFalse(m[32, 5])                               # y = 2048: next to visible (0, 1)
        self.assertFalse(m[5, 64] or m[40, 40])                  # x = 4096 edge; quadrant (1, 1) visible
        self.assertEqual(int(m.sum()), 31 * 63)

    def test_terrain_from_lowers_hidden_quadrants(self):
        rng = np.random.default_rng(5)
        n = 6
        t = btd.Btd(6, -100.0, 900.0, [0x10861], rng.integers(20000, 40000, (n * 128, n * 128), dtype=np.uint16),
                    np.zeros((n * 128, n * 128), np.uint16), np.zeros((n * 2, n * 2, 8), np.uint8))
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "skyrim_all"), os.path.join(d, "city")
            for root in (src, out):
                os.makedirs(os.path.join(root, "Data", "Terrain"))
            with open(os.path.join(src, "Data", "Terrain", "T.btd"), "wb") as fh:
                fh.write(btd.write(t))
            with open(os.path.join(src, "overlays_params.json"), "w") as fh:
                json.dump({"overlays": [{"world": "SKY_Tamriel", "cells_cw": {"x": [-3, 2], "y": [-3, 2]},
                                         "origin_cw_m": [0.0, 0.0], "height_offset_m": 385.0,
                                         "btd_file": "Data/Terrain/T.btd"}]}, fh)
            with open(os.path.join(out, "Data", "Terrain", "C.btd"), "wb") as fh:
                fh.write(btd.write(btd.crop(t, 0, 0, 2, 2)))
            prm = {"overlays": [{"world": "SKY_City", "cells_cw": {"x": [0, 1], "y": [-1, 0]},
                                 "origin_cw_m": [100.0, -100.0], "height_offset_m": 385.0,
                                 "btd_file": "Data/Terrain/C.btd"}]}

            class Land:
                land_hide = {(0, 0): 0x1}                        # Skyrim cell (0, 0), SW quadrant: units 0..2048
            rep = MSO.crop_from(prm, out, src, land=Land(), hidden_depth=15.0)
            cut = btd.read(open(os.path.join(out, "Data", "Terrain", "C.btd"), "rb").read())
        before = btd.crop(t, 3, 2, 2, 2).heights_m()
        diff = before - cut.heights_m()
        # city sample (r, c) at shared metres (c * SP, -100 + r * SP); the quadrant is x, y in (0, 29.26) m
        inside = [(int(100 / SP) + k, k) for k in (2, 10, 30)]
        for r, c in inside:
            self.assertAlmostEqual(diff[r, c], 15.0, delta=0.05)
        self.assertEqual(diff[int(100 / SP) + 10, 0], 0.0)        # x = 0: the edge, kept
        self.assertEqual(diff[int(100 / SP) + 10, 40], 0.0)       # x = 31 m: outside
        self.assertEqual(diff[10, 10], 0.0)                       # y < 0: outside
        self.assertEqual(rep["hidden_land"]["quadrants"], 1)
        self.assertEqual(rep["hidden_land"]["samples"], int((np.abs(diff) > 1).sum()))


class EnableParentTests(unittest.TestCase):
    def test_children_of_a_disabled_parent(self):
        refs = [{"formkey": "A", "disabled": 0x800, "enable_parent": None},           # siege marker, off
                {"formkey": "B", "disabled": 0, "enable_parent": {"reference": "A", "flags": 0}},
                {"formkey": "C", "disabled": 0, "enable_parent": {"reference": "A", "flags": 1}},   # opposite: on
                {"formkey": "D", "disabled": 0, "enable_parent": {"reference": "B", "flags": 0}},   # chain: off
                {"formkey": "E", "disabled": 0, "enable_parent": {"reference": "Z", "flags": 0}},   # unknown parent
                {"formkey": "F", "disabled": 0, "enable_parent": None},
                {"formkey": "G", "disabled": 0, "enable_parent": {"reference": "F", "flags": 1}},   # opposite of on
                {"formkey": "H", "disabled": 0x800, "enable_parent": {"reference": "F", "flags": 0}}]
        self.assertEqual(skyrimrefs.disabled_by_parent(refs), {"B": "A", "D": "B", "G": "F"})

    def test_select_leaves_them_out_and_keeps_the_count(self):
        import contextlib
        import io
        from unittest import mock
        import make_skyrim_objects as so

        def ref(fk, ep=None, disabled=0):
            return {"formkey": fk, "type": "Static", "base_editor_id": "Rock" + fk, "model": f"Rocks\\{fk}.nif",
                    "pos": [100.0, 100.0, 0.0], "rot": [0, 0, 0], "scale": 1.0, "disabled": disabled,
                    "record_flags": disabled, "persistent": False, "exterior_cell": [0, 0], "enable_parent": ep}
        exp = {"schema_version": 2, "refs": [ref("A", disabled=0x800), ref("B", {"reference": "A", "flags": 0}),
                                             ref("C", {"reference": "A", "flags": 1}), ref("D")],
               "deferred_refs": []}
        with tempfile.TemporaryDirectory() as work, contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(so, "terrain_overlay",
                                  return_value=({}, {"cell_min": -9, "cell_max": 8, "origin_cw_m": [0, 0]})):
            with open(os.path.join(work, "export.json"), "w") as fh:
                json.dump(exp, fh)
            so.main(["select", "--work", work, "--terrain", work])
            with open(os.path.join(work, "selection.json")) as fh:
                rep = json.load(fh)
            with open(os.path.join(work, "selected.json")) as fh:
                kept = [r["formkey"] for r in json.load(fh)["refs"]]
        self.assertEqual(rep["refs"], 4)                         # the stage step's accounting: every exported one
        self.assertEqual(rep["skip_reasons"].get("disabled_by_parent"), 1)
        self.assertNotIn("B", kept)
        self.assertIn("C", kept)
        self.assertEqual(rep["to_convert"] + rep["skipped"], 4)

    def test_loop_is_left_alone(self):
        refs = [{"formkey": "A", "disabled": 0, "enable_parent": {"reference": "B", "flags": 0}},
                {"formkey": "B", "disabled": 0, "enable_parent": {"reference": "A", "flags": 1}}]
        self.assertEqual(skyrimrefs.disabled_by_parent(refs), {})


def node(children=(), rot=(1, 0, 0, 0, 1, 0, 0, 0, 1), tr=(0, 0, 0), scale=1.0):
    return (struct.pack("<iIiI", -1, 0, -1, 0) + struct.pack("<3f9ff", *tr, *rot, scale) + struct.pack("<i", -1)
            + struct.pack("<I", len(children)) + struct.pack(f"<{len(children)}i", *children) + struct.pack("<I", 0))


class FakeNif:
    def __init__(self, blocks, types):
        self.blocks, self.types = blocks, types

    def type_of(self, i):
        return self.types[i]


class RootTransformTests(unittest.TestCase):
    def test_root_turn_cleared_child_kept(self):
        quarter = (0, 1, 0, -1, 0, 0, 0, 0, 1)                   # WRCastleBridge01's BSFadeNode
        n = FakeNif([node([1], rot=quarter, tr=(5, 0, 0)), node([], rot=quarter)], ["BSFadeNode", "NiNode"])
        out = skyrimnif.clear_root_transform(n)
        self.assertEqual([i for i, _ in out], [0])
        self.assertEqual(out[0][1][1], tuple(float(v) for v in quarter))
        world = nifmod.world_transforms(n)
        t, r, s = world(1)
        self.assertEqual((t, r, s), ((0.0, 0.0, 0.0), tuple(float(v) for v in quarter), 1.0))
        self.assertEqual(len(n.blocks[0]), len(node([1])))
        self.assertEqual(skyrimnif.clear_root_transform(n), [])  # identity now: nothing to do


def shape(positions, triangles, translation=(0, 0, 0)):
    return nifmod.Fo4Shape(name=b"WATER", translation=translation, rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1), scale=1.0,
                           shader_ref=0, alpha_ref=-1, skin_ref=-1, positions=positions, uvs=[], normals=[], tangents=[],
                           colors=[], triangles=triangles, skinned=False)


class WaterTests(unittest.TestCase):
    def test_squares_stay_inside_the_footprint(self):
        from fo4sf import skyrimconvert as sc
        # an L: 1024 x 512 plus 512 x 512 on top of its left half, at z 100 (+ the shape's own 16)
        pts = [(0, 0, 100), (1024, 0, 100), (1024, 512, 100), (512, 512, 100), (512, 1024, 100), (0, 1024, 100)]
        tris = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 5)]
        w = sc.water_squares(shape(pts, tris, translation=(0, 0, 16)))
        self.assertEqual(w["z"], 116.0)
        self.assertGreater(w["covered"] / (1024 * 512 + 512 * 512), 0.97)   # the inner corner falls between grid lines
        for cx, cy, side in w["squares"]:
            for x in (cx - side / 2, cx + side / 2):
                for y in (cy - side / 2, cy + side / 2):
                    inside_l = (0 <= x <= 1024 and 0 <= y <= 512) or (0 <= x <= 512 and 0 <= y <= 1024)
                    self.assertTrue(inside_l, (cx, cy, side))
        self.assertGreater(max(sq[2] for sq in w["squares"]), 480.0)       # the largest square: most of 512

    def test_pieces_follow_the_reference(self):
        import make_skyrim_objects as so
        bases = [{"key": "pool", "edid": "SKY_Pool"}]
        items = {"pool": {"water": [{"z": 70.0, "squares": [[140.0, 0.0, 1120.0]]},
                                    {"sloped": True, "material": "Materials\\W.mat"}]}}
        placed = [{"src": "A", "base": 0, "pos": [10.0, 20.0, 5.0], "rot": [0.0, 0.0, math.pi / 2], "scale": 2.0,
                   "disabled": False},
                  {"src": "B", "base": 0, "pos": [0.0, 0.0, 0.0], "rot": [0.5, 0.0, 0.0], "scale": 1.0,
                   "disabled": False}]
        objects = {"bases": [{"edid": "SKY_Pool", "model": "m.nif"}], "refs": []}
        rep = so.model_water(objects, bases, placed, items, -9, 8, overlap=1.0)
        self.assertEqual((rep["pieces"], rep["refs"], rep["tilted"], rep["sloped"]), (1, 1, 1, 2))
        self.assertEqual(objects["bases"][1]["vanilla"], "039FD6")
        r = objects["refs"][0]
        # (140, 0, 70) units x scale 2 = (4, 0, 2) m, turned a quarter clockwise (Bethesda z): +x -> -y
        self.assertAlmostEqual(r["pos"][0], 10.0, places=4)
        self.assertAlmostEqual(r["pos"][1], 16.0, places=4)
        self.assertAlmostEqual(r["pos"][2], 7.0, places=4)
        self.assertAlmostEqual(r["scale"], 1120 * 2 / 70 / 16, places=4)   # 32 m of water from a 16 m piece
        self.assertEqual(r["rot"][:2], [0.0, 0.0])

    def test_water_models_ride_on_their_references(self):
        import make_skyrim_objects as so
        bases = [{"key": "pool", "edid": "SKY_Pool", "source": "pool.nif"}, {"key": "rock", "edid": "SKY_Rock"}]
        items = {"pool": {"water_model": {"model": "skyrim\\pool_water.nif", "bounds": [[-1, -1, 0], [1, 1, 0]]}},
                 "rock": {}}
        placed = [{"src": "A", "base": 0, "cell": [1, 2], "pos": [10.0, 20.0, 5.0], "rot": [0.0, 0.0, 1.0],
                   "scale": 2.0, "disabled": False},
                  {"src": "B", "base": 0, "cell": [3, 4], "pos": [1.0, 2.0, 3.0], "rot": [0.0, 0.0, 0.0],
                   "scale": 1.0, "disabled": True},
                  {"src": "C", "base": 1, "cell": [0, 0], "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 0.0],
                   "scale": 1.0, "disabled": False},
                  {"src": "A#spin", "spin_of": "A", "base": 0, "cell": [1, 2], "pos": [0, 0, 0], "rot": [0, 0, 0],
                   "scale": 1.0}]
        objects = {"bases": [{"edid": "SKY_Pool"}, {"edid": "SKY_Rock"}], "refs": []}
        rep = so.model_water_exact(objects, bases, placed, items, water_type="0560D0")
        self.assertEqual((rep["bases"], rep["refs"]), (1, 2))
        wb = objects["bases"][2]
        self.assertEqual((wb["edid"], wb["model"], wb["water_template"], wb["water_type"]),
                         ("SKY_Pool_Water", "skyrim\\pool_water.nif", "039FD6", "0560D0"))
        a, b = objects["refs"]
        self.assertEqual((a["base"], a["pos"], a["rot"], a["scale"], a["cell"]),
                         (2, [10.0, 20.0, 5.0], [0.0, 0.0, 1.0], 2.0, [1, 2]))
        self.assertTrue(b["disabled"])

    def test_water_material_is_vanillas(self):
        from fo4sf import sfnif, skyrimconvert as sc
        # vanilla Water\Water16m.nif: NiIntegerExtraData "MaterialID" 0xA456F487 next to WaterPlaceholder.mat
        self.assertEqual(sfnif.material_id(sc.WATER_MATERIAL), 0xA456F487)

    def test_water_planes_are_selected_for_skyrim_only(self):
        from fo4sf import exterior
        r = {"type": "Activator", "model": "Water\\Water1024.nif"}
        self.assertEqual(exterior.classify(r, ("Activator",))[1], "water")
        self.assertEqual(exterior.classify(r, ("Activator",), water=True)[0], "convert")


if __name__ == "__main__":
    unittest.main()
