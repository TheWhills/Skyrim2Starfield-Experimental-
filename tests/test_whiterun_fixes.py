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
sys.path.insert(0, HERE)
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
        # the fountain's shallow water by default (owner: the lake piece's splash too strong in shallow water)
        self.assertEqual((wb["edid"], wb["model"], wb["water_template"], wb["water_type"]),
                         ("SKY_Pool_Water", "skyrim\\pool_water.nif", "03084F", "0560D0"))
        again = {"bases": [{"edid": "SKY_Pool"}, {"edid": "SKY_Rock"}], "refs": []}
        so.model_water_exact(again, bases, placed, items, template="039FD6")
        self.assertEqual(again["bases"][2]["water_template"], "039FD6")
        self.assertNotIn("water_type", again["bases"][2])
        a, b = objects["refs"]
        self.assertEqual((a["base"], a["pos"], a["rot"], a["scale"], a["cell"]),
                         (2, [10.0, 20.0, 5.0], [0.0, 0.0, 1.0], 2.0, [1, 2]))
        self.assertTrue(b["disabled"])

    def test_water_material_is_vanillas(self):
        from fo4sf import sfnif, skyrimconvert as sc
        # vanilla Water\Water16m.nif: NiIntegerExtraData "MaterialID" 0xA456F487 next to WaterPlaceholder.mat
        self.assertEqual(sfnif.material_id(sc.WATER_MATERIAL), 0xA456F487)

    def test_water_volume_is_a_box_under_the_surface(self):
        from fo4sf import sfcollision, skyrimconvert as sc
        from test_collision import fake_template
        # a 1024 x 512 unit surface at z 70 units (1 m), offset by its shape translation
        s = shape([(0, 0, 70), (1024, 0, 70), (1024, 512, 70), (0, 512, 70)], [(0, 1, 2), (0, 2, 3)],
                  translation=(-512.0, 0.0, 0.0))
        c, h = sfcollision.read_box(sc.water_volume([s], fake_template(), depth_m=1.5))
        for got, want in zip(c + h, (0.0, 256 / 70, 1.0 - 0.75, 512 / 70, 256 / 70, 0.75)):
            self.assertAlmostEqual(got, want, places=4)
        self.assertIsNone(sc.water_volume([], fake_template()))

    def test_water_type_per_model(self):
        import make_skyrim_objects as so
        spec = so.WATER_TYPE_PROBE
        self.assertEqual(so.water_type_for(spec, "skyrim\\...\\wrwaterpool01_water.nif"), "0560CF")
        self.assertEqual(so.water_type_for(spec, "skyrim\\...\\WRTreeCircleWater01_water.nif"), "062BE5")
        self.assertEqual(so.water_type_for(spec, "skyrim\\clutter\\horsetrough01_water.nif"), "0560D0")
        self.assertEqual(so.water_type_for("", "x"), "")
        self.assertEqual(so.water_type_for("0560CF", "x"), "0560CF")
        # owner 2026-11-27: the upper pool's WaterOceanDark everywhere, the Gildergreen ring kept
        city = so.WATER_TYPE_NAMED["city"]
        self.assertEqual(so.water_type_for(city, r"skyrim\...\wrwaterpool01_water.nif"), "0560D0")
        self.assertEqual(so.water_type_for(city, r"skyrim\...\water1024_water.nif"), "0560D0")
        self.assertEqual(so.water_type_for(city, r"skyrim\...\WRTreeCircleWater01_water.nif"), "062BE5")
        self.assertIs(so.WATER_TYPE_NAMED["probe"], so.WATER_TYPE_PROBE)

    def test_water_effect_soft_edge_only_where_skyrim_is_soft(self):
        from fo4sf import skyrimconvert as sc
        self.assertEqual(sc.water_effect_soft_depth({"flags1": 0xA0000038}), 0.0)   # the streams' foam: none
        self.assertIsNone(sc.water_effect_soft_depth({"flags1": 0xC0000078}))       # the rocks' foam: template's
        calls = []

        class Conv(sc.SkyrimConverter):
            def __init__(self):
                pass

            def flame_material(self, source, **kw):
                calls.append(kw)
                return "m"
        info = {"source": r"textures\effects\FXWhiteWater01.dds", "flags1": 0xA0000038, "controllers": [],
                "vertex_alpha": True}
        import unittest.mock as um
        with um.patch.object(sc.skyrimfire, "effect_shader", return_value=info):
            self.assertEqual(Conv().skyrim_water_effect_material(None, 0), "m")
        self.assertEqual(calls[0]["soft_depth"], 0.0)

    def test_water_effects(self):
        import re
        from fo4sf import exterior, skyrimconvert as sc
        for tex in ("textures\\effects\\FXWhiteWater01.dds", "textures\\effects\\FXfluidTile01.dds"):
            self.assertTrue(re.search(sc.WATER_EFFECT, tex, re.I), tex)
        for tex in ("textures\\effects\\FXFogHeavy.dds", "textures\\effects\\FXFireAtlas02.dds"):
            self.assertFalse(re.search(sc.WATER_EFFECT, tex, re.I), tex)
        fall = {"type": "MovableStatic", "model": "Effects\\FXWaterfallThin256x128.nif"}
        fog = {"type": "MovableStatic", "model": "Effects\\FXFogHeavy01.nif"}
        self.assertEqual(exterior.classify(fall, ("MovableStatic",))[1], "effect")
        self.assertEqual(exterior.classify(fall, ("MovableStatic",), water=True)[0], "convert")
        self.assertEqual(exterior.classify(fog, ("MovableStatic",), water=True)[1], "effect")

    def test_water_planes_are_selected_for_skyrim_only(self):
        from fo4sf import exterior
        r = {"type": "Activator", "model": "Water\\Water1024.nif"}
        self.assertEqual(exterior.classify(r, ("Activator",))[1], "water")
        self.assertEqual(exterior.classify(r, ("Activator",), water=True)[0], "convert")


def float_data(keys):
    return struct.pack("<II", len(keys), 2) + b"".join(struct.pack("<ffff", t, v, 0, 0) for t, v in keys)


def shader_float_controller(nxt, target, interp, var, stop):
    # NiTimeController (next, flags, frequency, phase, start, stop, target) + interpolator + controlled variable
    return struct.pack("<iHffffi", nxt, 104, 1.0, 0.0, 0.0, stop, target) + struct.pack("<iI", interp, var)


class SequenceScrollTests(unittest.TestCase):
    def test_scroll_from_a_controller_sequence(self):
        from fo4sf import skyrimfire
        # WRRapidRocks01's foam: the shader's V Offset controller holds a blend interpolator; the keys (0 -> -1 over
        # 5.333 s) are on the NiControllerSequence's interpolator for that controller
        blocks = [
            shader_float_controller(-1, 6, 1, 8, 5.333),              # 0: V Offset, blend interpolator
            b"\0" * 10,                                                # 1: NiBlendFloatInterpolator
            struct.pack("<fi", -3.4e38, 3),                            # 2: NiFloatInterpolator -> 3
            float_data([(0.0, 0.0), (5.333, -1.0)]),                   # 3: NiFloatData
            struct.pack("<iII", 0, 1, 0) + struct.pack("<iiB5i", 2, 0, 0, 0, 0, 0, 0, -1)
            + struct.pack("<fiIfffii", 1.0, -1, 0, 1.0, 0.0, 5.333, -1, -1) + struct.pack("<H", 0),  # 4: sequence
        ]
        n = FakeNif(blocks, ["BSEffectShaderPropertyFloatController", "NiBlendFloatInterpolator",
                             "NiFloatInterpolator", "NiFloatData", "NiControllerSequence"])
        self.assertEqual(skyrimfire.sequence_interpolators(n), {0: 2})
        ctrls = skyrimfire.controllers(n, 0)
        self.assertEqual((ctrls[0]["variable"], ctrls[0]["interpolator"]), ("V Offset", "NiFloatInterpolator"))
        self.assertEqual(skyrimfire.uv_scroll(ctrls), ("V", -1.0, 5.333))

    def test_no_sequence_no_scroll(self):
        from fo4sf import skyrimfire
        n = FakeNif([shader_float_controller(-1, 6, 1, 8, 5.333), b"\0" * 10],
                    ["BSEffectShaderPropertyFloatController", "NiBlendFloatInterpolator"])
        self.assertIsNone(skyrimfire.uv_scroll(skyrimfire.controllers(n, 0)))


class SlopedWaterTests(unittest.TestCase):
    def test_sloped_water_is_the_wind_falls_lit_sheet(self):
        from fo4sf import skyrimconvert as sc
        calls = []

        class Conv:
            def skyrim_material(self, *args):
                calls.append(args)
                return "materials\\skyrim\\effects\\fxwatertile01_x.mat"
        self.assertEqual(sc.SkyrimConverter.sloped_water_material(Conv()),
                         "materials\\skyrim\\effects\\fxwatertile01_x.mat")
        # WRTerWind01Waterfall01.nif "WATER": FXwaterTile01 + FXwaterTile02_n, alpha blend (no test), threshold 55
        self.assertEqual(calls, [("textures\\effects\\FXwaterTile01.dds", "textures\\effects\\FXwaterTile02_n.dds",
                                  False, True, 55)])
        self.assertEqual(sc.WATER_DEPTH_M, 1.0)                  # as the fountain's 1 m water

    def test_sloped_sheet_vertex_alpha_raised_to_the_falls_level(self):
        from fo4sf import skyrimconvert as sc
        import dataclasses
        names = [f.name for f in dataclasses.fields(nifmod.Fo4Shape)]
        s = nifmod.Fo4Shape(**{n: None for n in names})
        s = dataclasses.replace(s, colors=[(255, 255, 255, 0), (255, 255, 255, 20), (200, 210, 220, 50),
                                           (255, 255, 255, 100)])
        out = sc.sloped_sheet_alpha(s)
        # the stairs stream's mean 20 / max 50 -> about the Wind District fall's mean 79; RGB kept, clamped at 255
        self.assertEqual(out.colors, [(255, 255, 255, 0), (255, 255, 255, 80), (200, 210, 220, 200),
                                      (255, 255, 255, 255)])
        bare = dataclasses.replace(s, colors=[])
        self.assertIs(sc.sloped_sheet_alpha(bare), bare)        # no vertex colours: unchanged
        # a sheet stream's foam raised to the stairs' foam mean (138), never lowered
        foam = dataclasses.replace(s, colors=[(200, 200, 200, 0), (200, 200, 200, 69), (200, 200, 200, 129)])
        self.assertEqual([c[3] for c in sc.raise_alpha_mean(foam).colors], [0, 144, 255])   # mean 66: x 138 / 66
        strong = dataclasses.replace(s, colors=[(1, 2, 3, 140), (1, 2, 3, 150)])
        self.assertIs(sc.raise_alpha_mean(strong), strong)
        self.assertIs(sc.raise_alpha_mean(bare), bare)


class SoundTests(unittest.TestCase):
    def test_skyrim_sound_markers_become_vanilla_ones(self):
        from fo4sf import skyrimsound

        def ref(fk, edid, pos=(0.0, 0.0, 0.0), disabled=0, t="SoundMarker", rot=(0.0, 0.0, 0.0)):
            return {"formkey": fk, "type": t, "base_editor_id": edid, "pos": list(pos), "rot": list(rot),
                    "disabled": disabled}
        refs = [ref("A", "AMBWaterfallSmallLP", (700.0, -1400.0, 70.0), rot=(0.0, 0.0, 1.0)),
                ref("B", "AMBWaterfallSmallLP", (7000.0, 0.0, 0.0)),        # 100 m east: outside cells -1..0
                ref("C", "AMBTavernExteriorLP"),                             # not mapped: stays skipped
                ref("D", "AMBSewerGrateLP"),
                ref("E", "AMBSewerGrateLP", disabled=1),                     # initially disabled
                ref("F", "AMBSewerGrateLP"),                                 # disabled through its enable parent
                ref("G", "AMBSewerGrateLP", t="Static")]
        objects = {"bases": [{"edid": "SKY_Rock"}], "refs": []}
        rep = skyrimsound.place(objects, refs, -1, 0, "SKY_", disabled={"F"})
        self.assertEqual(rep["placed"], {"AMBWaterfallSmallLP": 1, "AMBSewerGrateLP": 1})
        self.assertEqual((rep["outside"], rep["disabled"]), (1, 2))
        self.assertEqual(rep["placed_src"], {"A", "D"})
        self.assertEqual([b.get("vanilla") for b in objects["bases"]], [None, "234F7D", "1E2870"])
        a = objects["refs"][0]
        self.assertEqual((a["base"], a["pos"], a["cell"], a["rot"]), (1, [10.0, -20.0, 1.0], [0, -1], [0.0, 0.0, 1.0]))
        self.assertEqual(len({b["edid"] for b in objects["bases"]}), 3)

    def test_close_sound_markers_are_thinned_larger_first(self):
        from fo4sf import skyrimsound

        def ref(fk, edid, x):
            return {"formkey": fk, "type": "SoundMarker", "base_editor_id": edid, "pos": [x * 70.0, 0.0, 0.0],
                    "rot": [0.0, 0.0, 0.0], "disabled": 0}
        # a stream marker every 5 m, a waterfall among them, and one stream 30 m on
        refs = [ref("S0", "AMBWaterStreamSmallWhiterunLP", 0.0), ref("S1", "AMBWaterStreamSmallWhiterunLP", 5.0),
                ref("W", "AMBWaterfallSmallLP", 10.0), ref("S2", "AMBWaterStreamSmallWhiterunLP", 15.0),
                ref("S3", "AMBWaterStreamSmallWhiterunLP", 40.0)]
        objects = {"bases": [], "refs": []}
        rep = skyrimsound.place(objects, refs, -4, 4, "SKY_")
        self.assertEqual(rep["placed_src"], {"W", "S3"})
        self.assertEqual(rep["thinned"], 3)
        rep = skyrimsound.place({"bases": [], "refs": []}, refs, -4, 4, "SKY_", spacing=0)
        self.assertEqual(len(rep["placed_src"]), 5)


if __name__ == "__main__":
    unittest.main()
