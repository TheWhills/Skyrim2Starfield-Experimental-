"""core64c builder (scripts/terrain/make_core64c.py): band selection, size measurement, BTD decoding, local world
queries, plan entries and ordering, hard-linked staging and the archive estimate, all on synthetic data."""
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "scripts" / "terrain"))
sys.path.insert(0, str(root / "tests"))
spec = importlib.util.spec_from_file_location("make_core64c", root / "scripts" / "terrain" / "make_core64c.py")
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)
from fo4sf import btd, exterior, textures  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402


def ref(fk, typ="Static", model="Architecture\\A.nif", pos=(0.0, 0.0, 0.0), **kw):
    r = {"formkey": fk, "type": typ, "base_editor_id": "E" + fk[:6], "base_formkey": "000001:Fallout4.esm",
         "model": model, "pos": list(pos), "rot": [0.0, 0.0, 0.0], "scale": 1, "disabled": 0, "persistent": False,
         "exterior_cell": [0, 0], "enable_parent": None, "linked_references": [], "ownership": None}
    r.update(kw)
    return r


def box_tris(x0, y0, z0, x1, y1, z1):
    c = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return [t for q in quads for t in ((c[q[0]], c[q[1]], c[q[2]]), (c[q[0]], c[q[2]], c[q[3]]))]


def synthetic_btd(path, n=2, hmin=-10.0, hmax=90.0, seed=1):
    rng = np.random.default_rng(seed)
    raw = rng.integers(0, 65535, size=(n * 128, n * 128), dtype=np.uint16)
    t = btd.Btd(1, hmin, hmax, [0], raw, np.zeros_like(raw), np.zeros((n * 2, n * 2, 8), np.uint8))
    with open(path, "wb") as f:
        f.write(btd.write(t))
    return raw


def local_world(objects, ground=0.0, origin=-100.0, size=256):
    """A CoreWorld without files: flat terrain at `ground` from `origin` (both axes) and box objects
    [(src, box)] placed at the origin."""
    w = mk.CoreWorld.__new__(mk.CoreWorld)
    w.bases, w.placed, tris, owners = [], [], [], []
    for k, (src, box) in enumerate(objects):
        w.bases.append({"edid": "FO4Core_" + src.lower(), "model": src.lower() + ".nif", "collision": "fo4-native"})
        w.placed.append({"src": src, "base": k, "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 0.0], "scale": 1.0,
                         "disabled": False})
        t = box_tris(*box)
        tris += t
        owners += [k] * len(t)
    w.tris, w.owners = np.array(tris, np.float64).reshape(-1, 3, 3), np.array(owners, np.int64)
    w.index = exterior.SurfaceIndex(w.tris, w.owners)
    w.heights = np.full((size, size), ground, np.float64)
    w.ox = w.oy = origin
    w.step, w.hmin, w.n = 0.004, ground - 50.0, 1
    w.by_src = {p["src"]: k for k, p in enumerate(w.placed)}
    return w


class SelectTests(unittest.TestCase):
    def test_bands_slimmed_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            b1 = {"exterior": {"cells": [{"x": 0, "y": 0}, {"x": 1, "y": 0}]},
                  "refs": [ref("000001:Fallout4.esm"), ref("000002:Fallout4.esm", typ="Light"),
                           ref("000003:Fallout4.esm", model="Effects\\Fog.nif")],
                  "deferred_refs": [{"formkey": "000009:Fallout4.esm", "type": "PlacedNpc", "reason": "actor"}]}
            b2 = {"exterior": {"cells": [{"x": 0, "y": 1}]},
                  "refs": [ref("000004:Fallout4.esm", model="architecture\\a.nif"), ref("000005:Fallout4.esm",
                                                                                      model="Water\\Water1024.nif")]}
            paths = []
            for k, b in enumerate((b1, b2)):
                p = os.path.join(tmp, f"band_{k}.json")
                with open(p, "w") as f:
                    json.dump(b, f)
                paths.append(p)
            kept, skipped, tot = mk.select_bands(paths)
            self.assertEqual(tot, {"bands": 2, "cells": 3, "refs": 5, "deferred": 1})
            self.assertEqual([r["formkey"] for r in kept], ["000001:Fallout4.esm", "000004:Fallout4.esm"])
            self.assertEqual(set(kept[0]), set(mk.SLIM_KEYS) | {"enable_parent"})
            self.assertEqual(exterior.reason_counts(skipped), {"type_not_translated": 1, "effect": 1, "deferred": 1,
                                                               "water": 1})
            self.assertEqual(len(kept) + len(skipped), tot["refs"] + tot["deferred"])
            # one model, two references (case differs): one convert_batch entry
            self.assertEqual(len(mk.convert_list(kept)), 1)

    def test_a_reference_in_two_bands_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for k in range(2):
                p = os.path.join(tmp, f"band_{k}.json")
                with open(p, "w") as f:
                    json.dump({"refs": [ref("000001:Fallout4.esm")]}, f)
                paths.append(p)
            with self.assertRaises(ValueError):
                mk.select_bands(paths)

    def test_regions(self):
        self.assertEqual(mk.region_of((-1, 15)), (-1, 0))
        self.assertEqual(mk.region_of((16, -17)), (1, -2))


class MeasureTests(unittest.TestCase):
    def test_bc_size_matches_cap_dds(self):
        from test_texture_cap import bc_dds
        for fmt, dxgi, bb in (("BC1", 71, 8), ("BC5", 83, 16), ("BC4", 80, 8)):
            for w, h, cap in ((64, 64, 0), (64, 32, 16), (128, 64, 128), (32, 128, 8)):
                data = bc_dds(w, h, dxgi=dxgi, bb=bb)
                out, _ = textures.cap_dds(data, cap)
                self.assertEqual(mk.bc_size(fmt, w, h, cap=cap), len(out), (fmt, w, h, cap))

    def test_dry_converter_outputs(self):
        class Entry:
            def __init__(self, w, h):
                self.width, self.height = w, h

        class Arc:
            names = {"textures/a_d.dds": Entry(1024, 512), "textures/a_n.dds": Entry(512, 512),
                     "textures/a_s.dds": Entry(256, 256)}

            def __init__(self):
                self.entries = list(self.names.values())
                self.idx = {k: i for i, k in enumerate(self.names)}

            def find(self, n):
                return self.idx.get(n.replace("\\", "/").lower())

        src = type("Src", (), {"textures": [Arc()]})()
        dry = mk.DryConverter(src)
        dry._texture_set("set1", "a_d.dds", "a_n.dds", "a_s.dds", alpha_test=True)
        dry._texture_set("set2", "a_d.dds", "a_n.dds", "")
        self.assertEqual(dry.outputs["set1"], [("color", "BC1", 1024, 512), ("normal", "BC5", 512, 512),
                                               ("rough", "BC4", 256, 256), ("opacity", "BC4", 1024, 512)])
        self.assertEqual(dry.outputs["set2"][2], ("rough", "BC4", 128, 128))      # no spec: a quarter of the normal
        with self.assertRaises(FileNotFoundError):
            dry._texture_set("set3", "missing_d.dds", "a_n.dds", "")


class TerrainTests(unittest.TestCase):
    def test_bilinear_and_window_match_point_interp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "t.btd")
            raw = synthetic_btd(p)
            t = mk.Terrain(p)
            full = t.hmin + raw.astype(np.float64) / 65535.0 * (t.hmax - t.hmin)
            o = tg.grid_origin(2)
            rng = np.random.default_rng(2)
            xs, ys = rng.uniform(-100, 99, 50), rng.uniform(-100, 99, 50)
            got = t.bilinear(xs, ys)
            win, ox, oy = t.window(-40, -30, 20, 35)
            w = mk.CoreWorld.__new__(mk.CoreWorld)
            w.heights, w.ox, w.oy = win, ox, oy
            for x, y, g in zip(xs, ys, got):
                want = tg.point_interp(full, o, o, tg.SF_STEP_M, x, y)
                self.assertAlmostEqual(g, want["bilinear"], places=9)
                if -40 <= x <= 20 and -30 <= y <= 35:
                    got_all = w.ground_all(x, y)
                    for rule in want:
                        self.assertAlmostEqual(got_all[rule], want[rule], places=9)
            # outside the grid: clamped like point_interp
            self.assertAlmostEqual(t.bilinear([-500.0], [500.0])[0],
                                   tg.point_interp(full, o, o, tg.SF_STEP_M, -500.0, 500.0)["bilinear"], places=9)


class WorldTests(unittest.TestCase):
    def test_segment_blocked(self):
        w = local_world([("WALL", (10, -5, 0, 11, 5, 4)), ("LANDMARK", (20, -2, 0, 24, 2, 6))])
        self.assertTrue(w.segment_blocked((0, 0, 1.7), (22, 0, 3)))                    # through the wall
        self.assertFalse(w.segment_blocked((0, 0, 1.7), (22, 0, 3), ignore={0, 1}))
        self.assertFalse(w.segment_blocked((0, 8, 1.7), (22, 8, 3)))                   # beside it
        self.assertTrue(w.segment_blocked((0, 8, 1.7), (22, 8, -1)))                   # under the terrain

    def test_object_top_and_view_spot(self):
        w = local_world([("ROOF", (-5, 20, 0, 5, 30, 4.0)), ("TREE", (-1, 0, 0, 1, 2, 8))])
        top = mk.object_top(w, w.by_src["ROOF"], "roof", 100.0)
        self.assertEqual(top["kind"], "object_top")
        self.assertAlmostEqual(top["expect"], 4.0)
        self.assertGreaterEqual(top["discrimination"], 3.9)
        v = mk.view_spot(w, "view_roof", ("ROOF",), 100.0)
        self.assertEqual(v["kind"], "view")
        self.assertLess(v["y"], 20)                                                     # south of the roof
        self.assertFalse(w.segment_blocked((v["x"], v["y"], 1.7), v["target"], ignore={0}))
        self.assertGreaterEqual(math.hypot(v["x"], v["y"] - 1) if abs(v["x"]) < 2 else 99, 1.0)

    def test_entry_drop_clears_tops(self):
        w = local_world([("TALL", (-1, -1, 0, 1, 1, 30))])
        pts = [{"label": "a", "x": 0.0, "y": 0.0, "expect": 30.0}, {"label": "b", "x": 50.0, "y": 0.0, "expect": 0.0}]
        self.assertEqual(mk.entry_drop(w, pts), 70.0)                                  # 30 + 40
        pts[0]["expect"] = 0.0                                                          # 1 m from a 30 m top
        pts[0]["x"] = 1.5
        self.assertEqual(mk.entry_drop(w, pts), 40.0)                                   # max(0 + 40, 30 + 10)


class PlanTests(unittest.TestCase):
    def test_spoke_order_needs_no_more_waypoints_than_the_spokes(self):
        start = (0.0, 0.0, 0.0)
        pts = []
        for deg in (0, 45, 135, 180, 270, 320):                    # core64's six rays, probes at 200 and 500 m
            for d in (200, 500):
                a = math.radians(deg)
                pts.append({"label": f"r{deg}_{d}", "x": d * math.cos(a), "y": d * math.sin(a), "expect": 0.0})
        order = mk.order_entry(start, pts)                          # 12 points: spoke zig-zag + 2-opt
        self.assertEqual(sorted(p["label"] for p in order), sorted(p["label"] for p in pts))
        key = mk.seq_key(start, order)
        self.assertLessEqual(key, mk.seq_key(start, mk.spoke_order(start, pts)))
        self.assertLess(key[0], mk.seq_key(start, sorted(pts, key=lambda p: p["label"]))[0])

    def test_exhaustive_order_fewest_waypoints_then_shortest(self):
        pts = [{"label": "a", "x": -200.0, "y": 0.0, "expect": 0.0}, {"label": "b", "x": 250.0, "y": 0.0, "expect": 0.0}]
        # a then b: 200 m (1 waypoint) + 450 m (2) = 3, 650 m; b then a: 250 m (1) + 450 m (2) = 3, 700 m
        self.assertEqual([p["label"] for p in mk.order_entry((0.0, 0.0, 0.0), pts)], ["a", "b"])
        self.assertEqual(mk.seq_key((0.0, 0.0, 0.0), pts), (3, 0, 650.0))
        self.assertEqual([mk.waypoints_needed(d) for d in (0.0, 185.0, 185.1, 370.0, 371.0)], [0, 0, 1, 1, 2])

    def test_plan_entry_and_validation(self):
        base = {"coc": "FO4Core_RedRocketSpawn", "label": "core64", "spawn_local": [1, 2, 3], "z_ref": "arrival",
                "drop_z": 150.0, "settle_ms": 10000, "points": []}
        pts = [{"label": "zref_ground", "x": 1.0, "y": 2.0, "expect": 3.0, "kind": "terrain_ref"},
               {"label": "roof", "x": 4.0, "y": 5.0, "expect": 9.0, "kind": "object_top"}]
        e = mk.plan_entry(base, "core64c", 160.0, pts, "zref_ground", [1, 2, 3.1], 11000)
        self.assertEqual(e["coc"], base["coc"])
        self.assertEqual(e["settle_ms"], 11000)
        self.assertEqual(e["points"][1], {"label": "roof", "x": 4.0, "y": 5.0, "expect": 9.0})
        kinds = {(0, p["label"]): p["kind"] for p in pts}
        self.assertEqual((e["hop_m"], e["hop_wait_ms"]), (mk.HOP_M, mk.HOP_WAIT_MS))
        self.assertEqual(mk.validate_plan([e], base, kinds), [])
        bad = dict(e, z_ref="roof", extra=1)
        probs = mk.validate_plan([bad], base, kinds)
        self.assertTrue(any("extra" in p for p in probs) and any("z_ref" in p for p in probs))
        self.assertTrue(mk.validate_plan([dict(e, coc="Other")], base, kinds))

    def test_order_avoids_teleport_positions_in_objects(self):
        # setpos x comes first: from the start, going to "a" stands the player in the thin wall at (30, 0) on the
        # ground; going to "b" first, and then from b (0, 40) to a, passes north of the wall
        w = local_world([("WALL", (29.8, -3.0, 0.0, 30.2, 3.0, 5.0))], ground=0.0, origin=-100.0, size=256)
        legs = mk.Legs(w, (0.0, 0.0), 50.0)
        a = {"label": "a", "x": 30.0, "y": 40.0, "expect": 0.0}
        b = {"label": "b", "x": 0.0, "y": 40.0, "expect": 0.0}
        self.assertGreater(legs((0.0, 0.0, 0.0), a)["cost"], 0)                  # (30, 0, 0) is inside the wall
        self.assertEqual(legs((0.0, 0.0, 0.0), b)["cost"], 0)
        self.assertEqual([p["label"] for p in mk.order_entry((0.0, 0.0, 0.0), [a, b], legs)], ["b", "a"])
        self.assertEqual([p["label"] for p in mk.order_entry((0.0, 0.0, 0.0), [a, b])], ["b", "a"])  # shorter too
        self.assertEqual(len(legs.memo), 4)

    def test_teleports_as_the_runner_makes_them(self):
        pts = [{"label": "a", "x": 10.0, "y": 0.0}, {"label": "b", "x": 610.0, "y": 0.0},
               {"label": "c", "x": 650.0, "y": 0.0}]
        # no hop before the first point; 600 m -> ceil(600 / 300) = 2 teleports (1 hop); 40 m -> none
        self.assertEqual(mk.runner_teleports(pts, 300), [("a", 10.0, 0.0), (None, 310.0, 0.0), ("b", 610.0, 0.0),
                                                         ("c", 650.0, 0.0)])
        self.assertEqual([t[1] for t in mk.runner_teleports(pts, 200)], [10.0, 210.0, 410.0, 610.0, 650.0])
        self.assertEqual(mk.runner_teleports([{"label": "far", "x": 900.0, "y": 0.0}], 200), [("far", 900.0, 0.0)])
        self.assertEqual(len(mk.runner_teleports(pts, 0)), 3)

    def test_axis_cells_whatever_the_offset(self):
        self.assertEqual([mk.axis_cells(d) for d in (0.0, -0.5, 100.0, 199.99, 200.0, 200.01, -292.6)],
                         [0, 1, 1, 2, 2, 3, 3])
        # core64 e_200m -> e_500m: 292.6 m east, 3 cells in core64's frame (relocated in game); hop_m 200 keeps every
        # teleport at 2 cells or fewer in any frame
        moves = mk.axis_moves((-784.4571, 1148.3429), [("e_500m", -491.8857, 1146.5143)])
        self.assertEqual((moves[0]["cells"], moves[0]["cells_core64"]), (3, 3))
        moves = mk.axis_moves((0.0, 0.0), [("a", 150.0, -20.0)], offset=(-1200.0, -2700.0))
        self.assertEqual((moves[0]["cells"], moves[0]["cells_core64"]), (2, 1))
        moves = mk.axis_moves((-784.4571, 1148.3429), mk.runner_teleports(
            [{"label": "e_200m", "x": -784.4571, "y": 1148.3429}, {"label": "e_500m", "x": -491.8857, "y": 1146.5143}]))
        self.assertEqual([m["to"] for m in moves], ["e_200m", "hop", "e_500m"])
        self.assertLessEqual(max(m["cells"] for m in moves), mk.MAX_AXIS_CELLS)

    def test_travel_time_against_the_step_timeout(self):
        # the old entry 1: 9 points at a 10 s settle and 6 hops: 77 s left; core64b (7 points, 4 hops at 10.5 s): 130 s
        # estimated, 138 s measured (its last point 732 s after the step started)
        self.assertEqual(mk.runner_timeout(9), 1050)
        self.assertEqual(round(mk.runner_seconds(9, 10000, 6)), 973)
        self.assertEqual(round(mk.runner_timeout(7) - mk.runner_seconds(7, 10500, 4)), 130)
        pts = [{"label": f"p{k}", "x": 150.0 * k, "y": 0.0, "expect": 0.0} for k in range(5)]
        t = mk.entry_travel((0.0, 0.0), {"points": pts, "settle_ms": 10000, "hop_m": 200})
        self.assertEqual((t["teleports"], t["hops"], t["max_axis_move_m"], t["max_axis_cells"]), (5, 0, 150.0, 2))
        self.assertEqual(t["margin_s"], round(mk.runner_timeout(5) - mk.runner_seconds(5, 10000, 0)))
        self.assertGreaterEqual(t["margin_s"], mk.MIN_MARGIN_S)
        t = mk.entry_travel((0.0, 0.0), {"points": pts[:1] + [dict(pts[1], x=900.0)], "settle_ms": 10000, "hop_m": 200})
        self.assertEqual(t["hops"], 4)                                                  # 900 m in 5 teleports

    def test_waypoints_keep_every_leg_within_hop_m(self):
        w = local_world([], ground=3.0, origin=-100.0, size=1024)                      # flat, x and y -100 .. 699 m
        seq = [{"label": "far", "x": 500.0, "y": 0.0, "expect": 3.0}]
        pts, left = mk.add_waypoints(w, (0.0, 0.0, 3.0), seq, (0.0, 0.0), 300.0)
        self.assertEqual([p["label"] for p in pts], ["wp_01", "wp_02", "far"])        # 500 m: 2 waypoints at 185 m
        self.assertEqual(left, [])
        here = (0.0, 0.0)
        for p in pts:
            self.assertLessEqual(math.hypot(p["x"] - here[0], p["y"] - here[1]), mk.HOP_M)
            here = (p["x"], p["y"])
        self.assertTrue(all(p["kind"] == "terrain" and p["expect"] == 3.0 for p in pts[:2]))
        self.assertEqual(mk.entry_travel((0.0, 0.0), {"points": pts, "settle_ms": 9000, "hop_m": mk.HOP_M})["hops"], 0)
        # an object over the first ideal place: the waypoint moves to open terrain beside it, legs still within hop_m
        w = local_world([("SHED", (150.0, -12.0, 0.0, 185.0, 12.0, 6.0))], ground=3.0, origin=-100.0, size=1024)
        pts, left = mk.add_waypoints(w, (0.0, 0.0, 3.0), seq, (0.0, 0.0), 300.0)
        self.assertEqual(left, [])
        self.assertGreaterEqual(abs(pts[0]["y"]), 12.0 + 1.0)
        here = (0.0, 0.0)
        for p in pts:
            self.assertLessEqual(math.hypot(p["x"] - here[0], p["y"] - here[1]), mk.HOP_M)
            here = (p["x"], p["y"])
        # no open terrain anywhere near the leg: no waypoint, the runner hops it
        w = local_world([("BLOCK", (60.0, -60.0, 0.0, 440.0, 60.0, 6.0))], ground=3.0, origin=-100.0, size=1024)
        pts, left = mk.add_waypoints(w, (0.0, 0.0, 3.0), seq, (0.0, 0.0), 300.0)
        self.assertEqual([p["label"] for p in pts], ["far"])
        self.assertEqual(left[0]["to"], "far")

    def test_waypoint_ok_wants_moderate_relief(self):
        w = local_world([], ground=0.0, origin=-100.0, size=256)
        self.assertEqual(mk.waypoint_ok(w, 0.0, 0.0, 300.0), (0.0, 0.0))
        w.heights = np.tile(np.arange(256, dtype=np.float64) * tg.SF_STEP_M * 0.2, (256, 1))   # a 20 % grade in x
        self.assertIsNone(mk.waypoint_ok(w, 0.0, 0.0, 300.0))
        w.heights = np.tile(np.arange(256, dtype=np.float64) * tg.SF_STEP_M * 0.05, (256, 1))  # 5 %
        g, spread = mk.waypoint_ok(w, 0.0, 0.0, 300.0)
        self.assertAlmostEqual(g, 100.0 * 0.05, places=6)
        self.assertLess(spread, mk.WAYPOINT_MAX_SPREAD)

    def test_scenarios(self):
        w = local_world([("ROOF", (-5, 20, 0, 5, 30, 4.0))], ground=2.0)
        entry = {"z_ref": "zref_ground", "points": [{"label": "zref_ground", "x": 0.0, "y": 0.0, "expect": 2.0},
                                                     {"label": "roof", "x": 0.0, "y": 25.0, "expect": 4.0}]}
        meta = {"zref_ground": {"kind": "terrain_ref"}, "roof": {"kind": "object_top"}}
        self.assertEqual(mk.scenario_reads(w, entry, meta, "no_objects"), [2.0, 2.0])
        self.assertEqual(mk.scenario_reads(w, entry, meta, "flat_terrain"), [w.hmin, 4.0])
        entry["drop_z"] = 50.0
        entry["points"].append({"label": "edge", "x": 5.3, "y": 25.0, "expect": 2.0})  # terrain 0.3 m from the roof
        meta["edge"] = {"kind": "terrain_near_object"}
        self.assertEqual(mk.scenario_reads(w, entry, meta, "landing_max"), [2.0, 4.0, 4.0])


class CompoundTopTests(unittest.TestCase):
    """make_core64c.compound_top with a synthetic NIF and packfile (decoders patched): body placement as
    routes.collision_bodies (node translation in game units / 70, Havok units = metres), then the reference."""

    def run_top(self, position=(0.0, 0.0, 0.0), quat=(0.0, 0.0, 0.0, 1.0), node_tr=(70.0, 0.0, 0.0), layer=1):
        from unittest import mock
        from fo4sf import ba2, fo4_compounds, hkpackfile, nif as nifmod
        blocks = [struct.pack("<iHiI", 1, 0, 2, 0), b"", struct.pack("<I", 4) + b"PACK"]
        types = ["bhkNPCollisionObject", "NiNode", "bhkPhysicsSystem"]
        fake_nif = type("F", (), {"blocks": blocks, "type_of": lambda self, i: types[i]})()
        leaf = {"points": [(-1.0, -1.0, 2.0), (1.0, -1.0, 2.0), (1.0, 1.0, 2.0), (-1.0, 1.0, 2.0)],
                "triangles": [(0, 1, 2), (0, 2, 3)]}

        class Pack:
            def __init__(self, blob):
                pass

            def objects(self):
                return [(10, "hknpPhysicsSystemData")]

            def array(self, at):
                return 100, 1

            def unpack(self, fmt, at):
                return (layer,)

        class Arc:
            def __init__(self, path):
                pass

            def find(self, name):
                return 0 if name == "meshes\\a\\b.nif" else None

            def read(self, name):
                return b"NIF"
        owner = {"model": "fo4core\\a\\b.nif", "pos": [10.0, 20.0, 5.0], "rot": [0.0, 0.0, 0.0], "scale": 2.0}
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "Fallout4 - Meshes.ba2"), "wb").close()
            with mock.patch.object(ba2, "Ba2", Arc), mock.patch.object(nifmod, "parse", return_value=fake_nif), \
                    mock.patch.object(nifmod, "world_transforms",
                                      return_value=lambda t: (node_tr, (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0)), \
                    mock.patch.object(fo4_compounds, "decode_body", return_value={
                        "position_havok_units": list(position), "quaternion_xyzw": list(quat), "leaves": [leaf]}), \
                    mock.patch.object(hkpackfile, "Packfile", Pack):
                return mk.compound_top(tmp, owner, 12.0, 20.0, 100.0)

    def test_top_placed_like_routes_then_the_reference(self):
        top, layer, rep = self.run_top()
        # leaf top z 2 m, node +1 m in x (70 units), reference scale 2 at z 5: the square spans x 10..14, top 9
        self.assertAlmostEqual(top, 9.0)
        self.assertEqual((layer, rep["bodies"], rep["leaves"], rep["skipped_body_transform"]), (1, 1, 1, 0))

    def test_body_with_its_own_transform_is_counted_not_placed(self):
        top, layer, rep = self.run_top(position=(0.5, 0.0, 0.0))
        self.assertIsNone(top)
        self.assertEqual(rep["skipped_body_transform"], 1)
        top, _layer, rep = self.run_top(quat=(0.0, 0.0, 0.7071, 0.7071))
        self.assertIsNone(top)


class StageTests(unittest.TestCase):
    def test_link_tree_and_archive_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "convert", "meshes", "fo4core")
            os.makedirs(src)
            with open(os.path.join(src, "a.nif"), "wb") as f:
                f.write(b"x" * 10)
            out = os.path.join(tmp, "out")
            self.assertEqual(mk.link_tree(os.path.join(tmp, "convert", "meshes"), os.path.join(out, "Data", "meshes")),
                             (1, 0, 0))
            self.assertTrue(os.path.samefile(os.path.join(src, "a.nif"), os.path.join(out, "Data", "meshes", "fo4core", "a.nif")))
            self.assertEqual(mk.link_tree(os.path.join(tmp, "convert", "meshes"), os.path.join(out, "Data", "meshes")),
                             (0, 0, 1))
            files = mk.data_files(out)
            self.assertEqual(files, [("meshes/fo4core/a.nif", 10)])
            self.assertEqual(mk.ba2_size(files), 32 + 36 + 10 + 2 + len("meshes/fo4core/a.nif"))

    def test_data_manifest_sees_an_in_place_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "convert", "textures")
            os.makedirs(src)
            with open(os.path.join(src, "a.dds"), "wb") as f:
                f.write(b"x" * 10)
            out = os.path.join(tmp, "out")
            mk.link_tree(os.path.join(tmp, "convert", "textures"), os.path.join(out, "Data", "textures"))
            with open(os.path.join(out, "P.esm"), "wb") as f:
                f.write(b"TES4")
            old = mk.data_manifest(out, ["P.esm"])
            self.assertEqual(sorted(old), ["Data/textures/a.dds", "P.esm"])
            os.replace(os.path.join(src, "a.dds"), os.path.join(src, "b.dds"))         # a new link there: unchanged
            self.assertEqual(mk.manifest_diff(old, mk.data_manifest(out, ["P.esm"])),
                             {"missing": [], "added": [], "changed": []})
            with open(os.path.join(src, "b.dds"), "wb") as f:                          # rewritten in place: changed
                f.write(b"y" * 12)
            self.assertEqual(mk.manifest_diff(old, mk.data_manifest(out, ["P.esm"]))["changed"], ["Data/textures/a.dds"])

    def test_terrain_edids(self):
        prm = {"overlays": [{"world": "W", "block": "WBlock", "location": "WLoc", "anchor": {"edid": "WAnchor"},
                             "coc": "Spawn"}]}
        self.assertEqual(mk.terrain_edids(prm), {"w", "wblock", "wloc", "wanchor", "spawn", "spawnmarker"})

    def test_abs_stats(self):
        s = mk.abs_stats([0.001, -0.002, 0.003, -0.5])
        self.assertEqual((s["count"], s["max_mm"], s["within_1cm"]), (4, 500.0, 3))
        s = mk.signed_stats([1.0, -2.0, 3.0])
        self.assertEqual((s["min"], s["median"], s["max"]), (-2.0, 1.0, 3.0))


if __name__ == "__main__":
    unittest.main()
