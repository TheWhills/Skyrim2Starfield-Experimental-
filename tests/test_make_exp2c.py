"""Terrain experiment 2c builder (scripts/terrain/make_exp2c.py): point classification, object choice, raw plugin walk
and dependency check, all on synthetic data (no game files)."""
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest

import numpy as np

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "scripts" / "terrain"))
spec = importlib.util.spec_from_file_location("make_exp2c", root / "scripts" / "terrain" / "make_exp2c.py")
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)
from fo4sf import exterior, nif, sfnif  # noqa: E402


def box_tris(x0, y0, z0, x1, y1, z1):
    c = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return [t for q in quads for t in ((c[q[0]], c[q[1]], c[q[2]]), (c[q[0]], c[q[2]], c[q[3]]))]


def fake_world(objects, ground=0.0, heights=None):
    """A World over a 1 x 1-cell BTD (x, y 0..99 m; flat at `ground` unless a 128 x 128 `heights` grid is given) with
    box objects: [(src, model, collision, box, rot)]."""
    w = mk.World.__new__(mk.World)
    w.bases, w.placed, tris, owners = [], [], [], []
    for k, (src, model, collision, box, rot) in enumerate(objects):
        w.bases.append({"edid": "FO4CW_" + src.lower(), "model": model, "collision": collision})
        w.placed.append({"src": src, "base": k, "pos": [0.0, 0.0, 0.0], "rot": list(rot), "scale": 1.0,
                         "disabled": False})
        t = box_tris(*box)
        tris += t
        owners += [k] * len(t)
    w.tris, w.owners = np.array(tris, np.float64).reshape(-1, 3, 3), np.array(owners, np.int64)
    w.index = exterior.SurfaceIndex(w.tris, w.owners)
    w.n, w.origin, w.step = 1, 0.0, 0.004
    w.heights = np.full((128, 128), ground, np.float64) if heights is None else np.asarray(heights, np.float64)
    w.hmin = float(w.heights.min()) - 50.0
    w.by_src = {p["src"]: k for k, p in enumerate(w.placed)}
    return w


class PointTests(unittest.TestCase):
    def test_terrain_points_classified(self):
        w = fake_world([("SLAB", "fo4cw\\a.nif", "fo4-native", (10, 10, -0.5, 20, 20, 0.3), (0, 0, 0)),
                        ("CRATE", "fo4cw\\b.nif", "fo4-native", (30.4, 29, 0, 31, 31, 1.0), (0, 0, 0))])
        pts = [{"label": "on_slab", "x": 15, "y": 15, "expect": 0.0},
               {"label": "by_crate", "x": 30, "y": 30, "expect": 0.0},
               {"label": "clear", "x": 50, "y": 50, "expect": 0.0}]
        out = {p["label"]: p for p in mk.terrain_points(w, pts, 150)}
        self.assertEqual(out["on_slab"]["kind"], "terrain_covered")
        self.assertAlmostEqual(out["on_slab"]["expect"], 0.3)
        self.assertEqual(out["on_slab"]["terrain_expect"], 0.0)
        self.assertEqual(out["on_slab"]["owner"]["src"], "SLAB")
        self.assertEqual(out["by_crate"]["kind"], "terrain_near_object")
        self.assertEqual(out["by_crate"]["expect"], 0.0)
        self.assertEqual(out["by_crate"]["nearby_object"]["distance"], 0.45)
        self.assertEqual(out["clear"]["kind"], "terrain")
        self.assertIsNone(out["clear"]["nearby_object"])

    def test_large_flat_objects_choice(self):
        w = fake_world([
            ("ROOF", "fo4cw\\bld.nif", "fo4-native", (10, 10, 0, 22, 22, 6), (0, 0, 0)),          # elevated, biggest
            ("ROAD1", "fo4cw\\road.nif", "fo4-native", (30, 10, -0.5, 45, 20, 0.2), (0, 0, 0)),
            ("ROAD2", "fo4cw\\road.nif", "fo4-native", (50, 10, -0.5, 66, 20, 0.2), (0, 0, 0)),   # same model: skipped
            ("WALK", "fo4cw\\walk.nif", "fo4-native", (30, 30, -0.5, 40, 36, 0.3), (0, 0, 0)),
            ("DOCK", "fo4cw\\dock.nif", "fo4-native", (75, 30, 0, 84, 36, 1.4), (0, 0, 0)),     # raised: 1.4 m
            ("SCOL", "fo4cw\\scol\\cm1.nif", "fo4-native", (50, 30, -0.5, 70, 50, 0.2), (0, 0, 0)),  # precombine
            ("GUESS", "fo4cw\\g.nif", "guessed-boxes", (10, 60, -0.5, 30, 80, 0.2), (0, 0, 0)),
            ("TILT", "fo4cw\\t.nif", "fo4-native", (40, 60, -0.5, 60, 80, 0.2), (0.1, 0, 0)),
            ("SMALL", "fo4cw\\s.nif", "fo4-native", (80, 80, 0, 81, 81, 0.5), (0, 0, 0))])
        chosen = mk.large_flat_objects(w, exclude=set())
        self.assertEqual([p["owner"]["src"] for p in chosen], ["ROAD2", "ROOF", "WALK", "DOCK"])
        self.assertEqual([p["label"] for p in chosen], ["flat_road2", "roof_roof", "flat_walk", "top_dock"])
        self.assertEqual([p["object_class"] for p in chosen], ["ground", "elevated", "ground", "raised"])
        self.assertAlmostEqual(chosen[1]["expect"], 6.0)
        self.assertAlmostEqual(chosen[1]["above_terrain"], 6.0)
        self.assertAlmostEqual(chosen[1]["discrimination"], 6.0)
        self.assertAlmostEqual(chosen[3]["discrimination"], 1.4)
        self.assertEqual([p["owner"]["src"] for p in mk.large_flat_objects(
            w, exclude={"ROOF"}, want={"elevated": 1, "raised": 0, "ground": 1})], ["ROAD2"])

    def test_object_class(self):
        self.assertEqual(mk.object_class(4.7), "elevated")
        self.assertEqual(mk.object_class(1.0), "raised")
        self.assertEqual(mk.object_class(0.31), "ground")     # the North bridge: under the runner's 0.5 m tolerance

    def test_collision_kind(self):
        self.assertEqual(mk.collision_kind({"door": {}, "collision_report": {}}), "rigged-door-box")
        self.assertEqual(mk.collision_kind({"collision_report": {"source": "fo4-native"}}), "fo4-native")
        self.assertEqual(mk.collision_kind({"collision_report": {"boxes": 4}}), "guessed-boxes")
        self.assertEqual(mk.collision_kind({"collision_report": {}}), "none")


# ------------------------------------------------------------------------------------------------ plan entries
BASE = {"coc": "FO4CW_RedRocketSpawn", "label": "exp2b", "anchor": {"ref": "02000800", "local": [1, 2, 3]},
        "spawn_local": [1, 2, 3], "settle_ms": 8000, "z_ref": "flat_1", "drop_z": 150.0,
        "points": [{"label": "flat_1", "x": 1, "y": 2, "expect": 3}]}


def pt(label, kind="terrain", x=0.0, y=0.0, expect=0.0, **kw):
    return dict({"label": label, "x": x, "y": y, "expect": expect, "kind": kind}, **kw)


class PlanEntryTests(unittest.TestCase):
    def test_entry_carries_every_base_key(self):
        base = dict(BASE, travel="coc FO4CW_RedRocketSpawn", beyond={"x": 1, "y": 2})
        e = mk.plan_entry(base, "objects", 150.0, [pt("zref_ground", "terrain_ref"), pt("roof", "object_top", owner={})],
                          "zref_ground", [1, 2, 3.5])
        self.assertEqual(e["z_ref"], "zref_ground")
        self.assertEqual(e["spawn_local"], [1, 2, 3.5])
        for k in ("coc", "anchor", "settle_ms", "travel", "beyond"):
            self.assertEqual(e[k], base[k])
        self.assertEqual([sorted(p) for p in e["points"]], [["expect", "label", "x", "y"]] * 2)
        with self.assertRaises(ValueError):
            mk.plan_entry(dict(BASE, drop_above_spawn=2.0), "x", 150.0, [pt("zref_ground", "terrain_ref")], "zref_ground", [1, 2, 3])

    def test_validate_names_the_drift(self):
        pts = [pt("zref_ground", "terrain_ref"), pt("roof", "object_top")]
        e = mk.plan_entry(BASE, "objects", 150.0, pts, "zref_ground", [1, 2, 3])
        kinds = {(0, "zref_ground"): "terrain_ref", (0, "roof"): "object_top"}
        self.assertEqual(mk.validate_plan([e], BASE, kinds), [])
        # the first exp2c entry(): copied six keys by hand and lost z_ref (verifier, 2026-10-11)
        old = {k: e[k] for k in ("coc", "label", "anchor", "spawn_local", "drop_z", "settle_ms", "points")}
        self.assertIn("entry 1: no z_ref (the runner then takes the Z offset from the anchor or the arrival)",
                      mk.validate_plan([old], BASE, kinds))
        self.assertIn("entry 1: exp2b key 'new_runner_key' not carried",
                      mk.validate_plan([e], dict(BASE, new_runner_key=1), kinds))
        self.assertIn("entry 1: key 'extra' is not read by the runner", mk.validate_plan([dict(e, extra=1)], BASE, kinds))
        self.assertIn("entry 1: z_ref 'flat_1' is not one of its points", mk.validate_plan([dict(e, z_ref="flat_1")], BASE, kinds))
        self.assertIn("entry 1: z_ref 'roof' is a object_top point, not the terrain reference",
                      mk.validate_plan([dict(e, z_ref="roof")], BASE, kinds))
        dup = dict(e, points=e["points"] + [e["points"][0]])
        self.assertIn("entry 1: duplicate point labels", mk.validate_plan([dup], BASE, kinds))
        extra = dict(e, points=[dict(e["points"][0], kind="terrain_ref")] + e["points"][1:])
        self.assertTrue(any("has keys" in x for x in mk.validate_plan([extra], BASE, kinds)))

    def test_runner_keys_cover_what_plan_terrain_reads(self):
        # scripts/game/testqueue.py (claude/test-queue) reads these from a plan.json entry; when the runner is in the
        # tree (or FO4SF_TESTQUEUE names it), its own plan_terrain must pass every key of our entries through
        src = runner_source()
        if src is None:
            self.skipTest("scripts/game/testqueue.py is not in this tree (set FO4SF_TESTQUEUE)")
        text = Path(src).read_text(encoding="utf-8")
        body = text[text.index("def plan_terrain"):text.index("def judge(")]
        for k in ("spawn_local", "anchor", "drop_above_spawn", "settle_ms", "z_ref", "drop_z", "points", "beyond",
                  "travel", "coc", "label"):
            self.assertIn(f'"{k}"', body, k)
        for k in re.findall(r'"([a-z_]+)"', body[body.index("for k in ("):].split(")")[0]):
            self.assertIn(k, mk.RUNNER_KEYS)

    def test_plan_through_the_runner(self):
        src = runner_source()
        if src is None:
            self.skipTest("scripts/game/testqueue.py is not in this tree (set FO4SF_TESTQUEUE)")
        tq = load_runner(src)
        pts = [pt("zref_ground", "terrain_ref", 1, 1, 105.0), pt("roof", "object_top", 5, 5, 110.0)]
        plan = [mk.plan_entry(BASE, "objects", 150.0, pts, "zref_ground", [1, 2, 3])]
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "exp"))
            os.makedirs(os.path.join(d, "staging"))
            Path(d, "staging", "FO4Port.esm").write_bytes(b"TES4")
            Path(d, "exp", "plan.json").write_text(json.dumps(plan))
            args = type("A", (), dict(staging=os.path.join(d, "staging"), exp_dir=os.path.join(d, "exp"),
                                      out=os.path.join(d, "q"), plugin_index="02", launch_cell="Vault111Cryo",
                                      only=0, plugins="", starfield=""))()
            tq.plan_terrain(args)
            q = json.loads(Path(d, "q", "queue.json").read_text())
        t = q["tests"][0]
        for k in ("z_ref", "spawn_local", "anchor", "settle_ms", "drop_z", "points"):
            self.assertEqual(t[k], plan[0][k], k)


def runner_source():
    for c in (os.environ.get("FO4SF_TESTQUEUE"), str(root / "scripts" / "game" / "testqueue.py")):
        if c and os.path.isfile(c):
            return c
    return None


def load_runner(src):
    s = importlib.util.spec_from_file_location("testqueue_under_test", src)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


class JudgeTests(unittest.TestCase):
    def test_heights_relative_to_the_reference(self):
        pts = [{"label": "zref_ground", "expect": 105.0}, {"label": "roof", "expect": 109.7}]
        self.assertEqual(mk.judge_heights(pts, [-116.0, -111.3], "zref_ground")[0], "PASS")      # any Z offset
        v, worst, oz = mk.judge_heights(pts, [-116.0, -116.0], "zref_ground")                    # roof missing
        self.assertEqual(v, "FAIL")
        self.assertAlmostEqual(worst, 4.7)
        self.assertAlmostEqual(oz, -221.0)
        self.assertEqual(mk.judge_heights(pts, [105.0, 109.3], "zref_ground")[0], "PASS")         # 0.4 m: tolerated

    def test_same_verdict_as_the_runner(self):
        src = runner_source()
        if src is None:
            self.skipTest("scripts/game/testqueue.py is not in this tree (set FO4SF_TESTQUEUE)")
        tq = load_runner(src)
        pts = [{"label": "zref_ground", "x": 1.0, "y": 1.0, "expect": 105.0},
               {"label": "floor", "x": 5.0, "y": 5.0, "expect": 105.17}, {"label": "roof", "x": 9.0, "y": 9.0, "expect": 109.7}]
        with tempfile.TemporaryDirectory() as d:
            Path(d, "spawn.png").write_bytes(b"png")
            for reads in ([-116.0, -115.83, -111.3], [-116.0, -115.97, -116.0], [-116.0, -115.97, -111.25]):
                obs = {"shot": "spawn.png", "offset": [-1200.0, -2700.0, -221.14], "offset_from": "spawn",
                       "points": [{"read": f"{p['x'] - 1200:.2f} {p['y'] - 2700:.2f} {r:.2f}"} for p, r in zip(pts, reads)]}
                got = tq.judge({"kind": "terrain", "z_ref": "zref_ground", "points": pts}, obs, d)[0]
                self.assertEqual(got, mk.judge_heights(pts, reads, "zref_ground")[0], reads)


class DiscriminationTests(unittest.TestCase):
    def world(self):
        # terrain rising 0.05 m per m east (0 at x = 0), a 4.7 m roof slab at x 20..30, a floor 0.14 m above the
        # terrain under it at x 60..70 (level terrain there, 3 m)
        xs = np.arange(128) * mk.tg.SF_STEP_M
        h = np.tile(np.minimum(xs * 0.05, 3.0), (128, 1))
        return fake_world([("ROOF", "fo4cw\\r.nif", "fo4-native", (20, 20, 0, 30, 30, 6.2), (0, 0, 0)),
                           ("FLOOR", "fo4cw\\f.nif", "fo4-native", (60, 20, 2.5, 70, 30, 3.14), (0, 0, 0))], heights=h)

    def test_objects_entry_fails_without_objects_floor_entry_does_not(self):
        w = self.world()
        ref = pt("zref_ground", "terrain_ref", 80.0, 60.0, 3.0)
        roof = pt("roof", "object_top", 25.0, 25.0, 6.2)
        floor = pt("floor", "floor", 65.0, 25.0, 3.14)
        self.assertGreater(mk.discrimination(w, 25.0, 25.0, 6.2), 4.7)
        self.assertAlmostEqual(mk.discrimination(w, 65.0, 25.0, 3.14), 0.14)
        objects = mk.plan_entry(BASE, "objects", 150.0, [ref, roof], "zref_ground", [1, 2, 3])
        floor_e = mk.plan_entry(BASE, "floor", 3.9, [ref, floor], "zref_ground", [1, 2, 3])
        meta_o = {p["label"]: p for p in (ref, roof)}
        meta_f = {p["label"]: p for p in (ref, floor)}
        v, worst, _ = mk.judge_heights(objects["points"], mk.scenario_reads(w, objects, meta_o, "no_objects"), "zref_ground")
        self.assertEqual(v, "FAIL")
        self.assertGreater(worst, mk.MIN_DISCRIMINATION)
        v, worst, _ = mk.judge_heights(floor_e["points"], mk.scenario_reads(w, floor_e, meta_f, "no_objects"), "zref_ground")
        self.assertEqual(v, "PASS")                                # the verifier's point: 0.14 m is not seen
        self.assertAlmostEqual(worst, 0.14)

    def test_terrain_entry_fails_on_flat_ground(self):
        w = self.world()
        pts = [pt("zref_ground", "terrain_ref", 80.0, 60.0, 3.0), pt("low", "terrain", 10.0, 60.0, 0.5)]
        e = mk.plan_entry(BASE, "terrain", 150.0, pts, "zref_ground", [1, 2, 3])
        meta = {p["label"]: p for p in pts}
        self.assertEqual(mk.judge_heights(e["points"], mk.scenario_reads(w, e, meta, "no_objects"), "zref_ground")[0], "PASS")
        v, worst, _ = mk.judge_heights(e["points"], mk.scenario_reads(w, e, meta, "flat_terrain"), "zref_ground")
        self.assertEqual(v, "FAIL")
        self.assertAlmostEqual(worst, 2.5)


class ReferenceAndOrderTests(unittest.TestCase):
    def test_reference_point_keeps_away_from_objects_and_slopes(self):
        xs = np.arange(128) * mk.tg.SF_STEP_M
        h = np.tile(np.where(xs < 40.0, 0.0, (xs - 40.0) * 0.2), (128, 1))      # level west of x = 40, a slope east
        w = fake_world([("CRATE", "fo4cw\\c.nif", "fo4-native", (30.0, 29.0, 0, 31.0, 31.0, 1.0), (0, 0, 0))], heights=h)
        ref = mk.reference_point(w, (30.0, 30.0), search=15.0)
        self.assertIsNotNone(ref)
        self.assertEqual(ref["kind"], "terrain_ref")
        self.assertEqual(ref["label"], mk.REF_LABEL)
        cx, cy = 30.5, 30.0
        self.assertGreaterEqual(max(abs(ref["x"] - cx) - 0.5, abs(ref["y"] - cy) - 1.0), mk.REF_CLEAR - 1e-9)
        self.assertLess(ref["x"], 40.0)
        self.assertAlmostEqual(ref["expect"], 0.0)
        self.assertIsNone(mk.reference_point(w, (30.0, 30.0), search=15.0, accept=lambda x, y, g: False))
        self.assertIsNone(mk.reference_point(w, (30.0, 30.0), search=15.0, max_ground=-0.5))

    def test_order_avoids_walls(self):
        # a thin wall (0.2 m) across (15, 5); start at (5, 5): going to A (15, 15) first puts the player at
        # (15, 5, 0) after setpos x, inside the wall; B (5, 15) first, then A, never touches it
        w = fake_world([("WALL", "fo4cw\\w.nif", "fo4-native", (14.0, 4.9, -1.0, 16.0, 5.1, 3.0), (0, 0, 0))])
        a, b = pt("a", "terrain", 15.0, 15.0, 0.0), pt("b", "terrain", 5.0, 15.0, 0.0)
        start = (5.0, 5.0, 0.0)
        paths, clear = mk.path_report(w, start, [a, b], 150.0)
        self.assertFalse(clear)
        self.assertEqual(paths[0]["positions"][0], [15.0, 5.0, 0.0, ["WALL"]])
        order = mk.order_points(w, start, [a, b], 150.0)
        self.assertEqual([p["label"] for p in order], ["b", "a"])
        self.assertTrue(mk.path_report(w, start, order, 150.0)[1])
        many = [pt(f"p{i}", "terrain", 50.0 + i, 50.0, 0.0) for i in range(9)]          # greedy branch, no walls
        self.assertEqual([p["label"] for p in mk.order_points(w, (50.0, 40.0, 0.0), many, 150.0)],
                         [p["label"] for p in many])


# ------------------------------------------------------------------------------------------------ synthetic plugin
def sub(sig, data):
    return sig + struct.pack("<H", len(data)) + data


def rec(sig, fid, fields, flags=0):
    body = b"".join(fields)
    return sig + struct.pack("<III", len(body), flags, fid) + bytes(8) + body


def grup(label, gtype, content):
    return b"GRUP" + struct.pack("<I", 24 + len(content)) + label + struct.pack("<i", gtype) + bytes(8) + content


def refr(fid, base, pos, rot=(0, 0, 0), flags=0):
    return rec(b"REFR", fid, [sub(b"NAME", struct.pack("<I", base)), sub(b"DATA", struct.pack("<6f", *pos, *rot))], flags)


def plugin(refs_a, flags_b=0):
    tes4 = rec(b"TES4", 0, [sub(b"HEDR", bytes(12)), sub(b"MAST", b"Starfield.esm\0"), sub(b"DATA", bytes(8))])
    stat = grup(b"STAT", 0, rec(b"STAT", 0x01000B00, [sub(b"EDID", b"FO4CW_x\0"), sub(b"MODL", b"fo4cw\\x.nif\0")]))
    top = rec(b"CELL", 0x01000900, [sub(b"DATA", b"\0\0")])
    top_kids = grup(struct.pack("<I", 0x01000900), 6, grup(struct.pack("<I", 0x01000900), 8,
                                                          refr(0x01000800, 0x3B, (1, 2, 3), flags=0x400)))
    cell = rec(b"CELL", 0x01000901, [sub(b"XCLC", struct.pack("<ii", -1, 2) + bytes(4))])
    temp = refs_a + refr(0x01000A01, 0x01000B00, (4.0, 5.0, 6.0), (0, 0, 1.5), flags_b)
    kids = grup(struct.pack("<I", 0x01000901), 6, grup(struct.pack("<I", 0x01000901), 9, temp))
    blocks = grup(struct.pack("<hh", 0, -1), 4, grup(struct.pack("<hh", -1, 0), 5, cell + kids))
    world = grup(b"WRLD", 0, rec(b"WRLD", 0x01000802, [sub(b"EDID", b"W\0")]) +
                 grup(struct.pack("<I", 0x01000802), 1, top + top_kids + blocks))
    return tes4 + stat + world


class PluginWalkTests(unittest.TestCase):
    def objects(self):
        return ({"bases": [{"edid": "FO4CW_x"}],
                 "refs": [{"src": "A", "base": 0, "cell": [-1, 2], "pos": [-150.5, 250.25, 100.0], "rot": [0, 0, 0],
                           "scale": 1.0, "disabled": False},
                          {"src": "B", "base": 0, "cell": [-1, 2], "pos": [4.0, 5.0, 6.0], "rot": [0, 0, 1.5],
                           "scale": 1.0, "disabled": False}]},
                {"bases": {"FO4CW_x": "000B00"}, "refs": {"A": "000A00", "B": "000A01"}})

    def walk(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "t.esm")
            Path(p).write_bytes(data)
            return mk.overlay_records.walk_plugin(p), mk.walk_cells(p)

    def test_cells_and_refs_match(self):
        good = refr(0x01000A00, 0x01000B00, (-150.5, 250.25, 100.0))
        walked, cells = self.walk(plugin(good))
        self.assertEqual(walked["masters"], ["Starfield.esm"])
        self.assertEqual(cells[0x01000901], {"grid": (-1, 2), "refs": [0x01000A00, 0x01000A01]})
        self.assertEqual(cells[0x01000900], {"grid": None, "refs": [0x01000800]})
        objects, ids = self.objects()
        problems, worst_pos, worst_rot = mk.ref_record_check(walked["records"], 0x01000000, objects, ids)
        self.assertEqual(problems, [])
        self.assertLess(worst_pos, 1e-4)
        self.assertLess(worst_rot, 1e-6)

    def test_mismatches_are_reported(self):
        moved = refr(0x01000A00, 0x01000B00, (-150.5, 250.25, 101.0))
        walked, _ = self.walk(plugin(moved, flags_b=0x800))
        objects, ids = self.objects()
        problems, worst_pos, _ = mk.ref_record_check(walked["records"], 0x01000000, objects, ids)
        self.assertAlmostEqual(worst_pos, 1.0)
        self.assertEqual(problems, ["B: disabled flag"])
        ids["refs"]["A"] = "000A05"
        problems, _, _ = mk.ref_record_check(walked["records"], 0x01000000, objects, ids)
        self.assertIn("A: no REFR 01000A05", problems)


class DependencyTests(unittest.TestCase):
    def test_meshes_materials_and_textures(self):
        with tempfile.TemporaryDirectory() as data:
            shape = sfnif.StaticShape(b"S", b"aa\\bb", 3, 3, "materials\\fo4cw\\m.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
            f = sfnif.build_static_nif(b"X", [shape])
            os.makedirs(os.path.join(data, "meshes", "fo4cw"))
            Path(data, "meshes", "fo4cw", "x.nif").write_bytes(nif.serialize(f))
            os.makedirs(os.path.join(data, "materials", "fo4cw"))
            mat = {"Objects": [{"Components": [{"Data": {"File": "Data\\textures\\fo4cw\\x_color.dds"}},
                                               {"Data": {"File": "Data\\Textures\\common\\vanilla.DDS"}}]}]}
            Path(data, "materials", "fo4cw", "m.mat").write_text(json.dumps(mat))
            res = mk.dependency_check(data, ["fo4cw\\x.nif"], vanilla={"textures/common/vanilla.dds"})
            self.assertEqual(sorted(res["missing"]), ["geometries\\aa\\bb.mesh", "textures\\fo4cw\\x_color.dds"])
            os.makedirs(os.path.join(data, "geometries", "aa"))
            Path(data, "geometries", "aa", "bb.mesh").write_bytes(b"m")
            os.makedirs(os.path.join(data, "textures", "fo4cw"))
            Path(data, "textures", "fo4cw", "x_color.dds").write_bytes(b"d")
            res = mk.dependency_check(data, ["fo4cw\\x.nif"], vanilla={"textures/common/vanilla.dds"})
            self.assertEqual(res["missing"], [])
            self.assertEqual(res["counts"]["meshes"], 1)
            self.assertEqual((res["counts"]["textures_own"], res["counts"]["textures_vanilla"]), (1, 1))
            self.assertEqual(mk.dependency_check(data, ["fo4cw\\x.nif"], vanilla=set())["missing"],
                             ["textures\\common\\vanilla.dds"])
            self.assertEqual(mk.dependency_check(data, ["fo4cw\\x.nif"])["counts"]["vanilla_unverified"], 1)


if __name__ == "__main__":
    unittest.main()
