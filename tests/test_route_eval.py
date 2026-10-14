import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "route_eval", Path(__file__).resolve().parents[1] / "scripts" / "game" / "route_eval.py")
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


def stair(end, start="0 0 0.3"):
    route = {"kind": "stairs", "expect": {"low": [0, 0, 0], "high": [2, 0, 2], "min_rise": 1.6}}
    return evaluator.judge(route, {"start_read": start, "end_read": end})[0]


def door(end, start="0 0 0"):
    route = {"kind": "door", "expect": {"plane_point": [0, 0, 0], "plane_normal": [2, 0, 0], "min_past": 0.8}}
    return evaluator.judge(route, {"start_read": start, "end_read": end})[0]


class RouteEvalTests(unittest.TestCase):
    def test_real_climbs_and_crossings_still_pass(self):
        self.assertEqual(stair("2.1 0.2 1.9"), "PASS")
        self.assertEqual(stair("2 0 0.4"), "STUCK")
        self.assertEqual(stair("1 0 -1"), "FALL")
        self.assertEqual(door("3 0.2 0"), "PASS")          # 1.5 m past a non-unit normal
        self.assertEqual(door("-0.4 0 0"), "BLOCKED")

    def test_impossible_reads_are_not_passes(self):
        self.assertEqual(stair("2 0 33"), "UNREAD")        # the 31 m Vault 114 climb
        self.assertEqual(stair("2 10 1.9"), "UNREAD")      # height matches, but it is off this stair
        self.assertEqual(stair("-6 0 0.1"), "STUCK")       # walked the other way along the same line
        self.assertEqual(stair("2 0 1.9", start="0 0 0.3"), "PASS")
        self.assertEqual(door("8 0.2 0"), "PASS")          # a few metres down the corridor is still a crossing
        self.assertEqual(evaluator.judge(
            {"kind": "stairs", "expect": {"low": [0, 0, 0], "high": [2, 0, 2], "min_rise": 1.6}},
            {"start_read": "0 0 0", "end_read": "20 0 1"})[0], "UNREAD")
        self.assertEqual(door("30 0 0"), "UNREAD")
        self.assertEqual(door("2 8 0"), "UNREAD")
        self.assertEqual(evaluator.judge(
            {"kind": "door", "expect": {"plane_point": [0, 0, 0], "plane_normal": [0, 0, 0], "min_past": 0.8}},
            {"end_read": "1 0 0"})[0], "UNREAD")
        self.assertEqual(evaluator.judge(
            {"kind": "stairs", "expect": {"low": [0, 0, 0], "high": [2, 0, 2], "min_rise": 1.6}},
            {"end_read": "nope"})[0], "UNREAD")

    def test_missed_start_and_missing_prompt(self):
        stair_route = {"kind": "stairs", "start": [0, 0, 0.3],
                       "expect": {"low": [0, 0, 0], "high": [2, 0, 2], "min_rise": 1.6}}
        self.assertEqual(evaluator.judge(
            stair_route, {"start_read": "10 0 0.3", "end_read": "12 0 1.9"})[0], "UNREAD")
        self.assertEqual(evaluator.judge(
            stair_route, {"start_read": "0.2 0.2 0.1", "end_read": "2.1 0.2 1.9"})[0], "PASS")
        # 0.9 m below the route start still counts; the Rexford stair reads sit about there
        low_start = {"kind": "door", "start": [0, 0, 0],
                     "expect": {"plane_point": [0, 0, 0], "plane_normal": [1, 0, 0], "min_past": 0.8}}
        self.assertEqual(evaluator.judge(
            low_start, {"start_read": "0 0 -0.9", "end_read": "3 0.2 -0.9"})[0], "PASS")
        # Vault 81 19DA36: same X/Y as the door, four metres down in the rock
        rock = {"kind": "door", "start": [-55.31, -17.6, -7.24],
                "expect": {"plane_point": [-55.31, -16.0, -7.24], "plane_normal": [0, 1, 0], "min_past": 0.8}}
        self.assertEqual(evaluator.judge(
            rock, {"start_read": "-55.31 -17.60 -11.18", "end_read": "-55.67 -16.58 -11.18"})[0], "UNREAD")
        door_route = {"kind": "door", "start": [0, 0, 0],
                      "expect": {"plane_point": [0, 0, 0], "plane_normal": [2, 0, 0], "min_past": 0.8}}
        self.assertEqual(evaluator.judge(
            door_route, {"start_read": "0 0 0", "end_read": "-0.4 0 0", "prompt": False})[0], "NOPROMPT")
        self.assertEqual(evaluator.judge(
            door_route, {"start_read": "0 0 0", "end_read": "-0.4 0 0", "prompt": True})[0], "BLOCKED")
        # already open: the second side walks through and the run never saw OPEN
        self.assertEqual(evaluator.judge(
            door_route, {"start_read": "0 0 0", "end_read": "3 0.2 0", "prompt": False})[0], "UNOPENED")
        self.assertEqual(evaluator.judge(
            door_route, {"start_read": "0 0 0", "end_read": "3 0.2 0", "prompt": True, "verb": "CLOSE"})[0], "UNOPENED")
        # older runs did not record a prompt, and a real OPEN still passes
        self.assertEqual(evaluator.judge(
            door_route, {"start_read": "0 0 0", "end_read": "3 0.2 0"})[0], "PASS")
        self.assertEqual(evaluator.judge(
            door_route, {"start_read": "0 0 0", "end_read": "3 0.2 0", "prompt": True, "verb": "OPEN"})[0], "PASS")

    def test_void_drop_from_a_matched_start_is_a_fall(self):
        # Parsons load door 07282D, the side that started on the route and fell through
        route = {"kind": "door", "start": [10.97, 51.41, 7.61],
                 "expect": {"plane_point": [10.971, 53.014, 7.329], "plane_normal": [0, 1, 0], "min_past": 0.8}}
        self.assertEqual(evaluator.judge(route, {
            "start_read": "10.97 51.41 7.31", "end_read": "11.22 57.95 -69.15", "prompt": False})[0], "FALL")
        # the other sample fell too, but the player was still at the cell entrance
        self.assertEqual(evaluator.judge(route, {
            "start_read": "-0.00 6.40 0.00", "end_read": "-0.00 0.97 -71.71", "prompt": False})[0], "UNREAD")
        climbed = {"kind": "stairs", "start": [0, 0, 0.3],
                   "expect": {"low": [0, 0, 0], "high": [2, 0, 2], "min_rise": 1.6}}
        self.assertEqual(evaluator.judge(
            climbed, {"start_read": "0 0 0.3", "end_read": "1 0 20"})[0], "UNREAD")

    def test_both_sides_are_required_and_load_doors_are_not_swings(self):
        wood = {"kind": "door", "ref": "hinge", "model": "PaintedWoodDoor01.nif", "start": [0, 0, 0],
                "expect": {"plane_point": [0, 0, 0], "plane_normal": [1, 0, 0], "min_past": 0.8}}
        other = dict(wood, expect={"plane_point": [0, 0, 0], "plane_normal": [-1, 0, 0], "min_past": 0.8})
        load = {"kind": "door", "ref": "entrance", "model": "BldWoodPDbDoorLoad01.nif", "start": [0, 0, 0],
                "expect": {"plane_point": [0, 0, 0], "plane_normal": [1, 0, 0], "min_past": 0.8}}
        routes = [wood, other, load]
        opened = {"start_read": "0 0 0", "end_read": "3 0 0", "prompt": True, "verb": "OPEN"}
        opened_back = {"start_read": "0 0 0", "end_read": "-3 0 0", "prompt": True, "verb": "OPEN"}
        walked_back = {"start_read": "0 0 0", "end_read": "-3 0 0", "prompt": False}
        walked = {"start_read": "0 0 0", "end_read": "3 0 0", "prompt": False}
        held = {"start_read": "0 0 0", "end_read": "-0.4 0 0", "prompt": True, "verb": "OPEN"}
        shut = evaluator.door_rows(routes, [dict(opened, index=0), dict(opened_back, index=1), dict(held, index=2)])
        self.assertEqual(shut, {"both": 1, "one": 0, "none": 0, "geometry": 0, "load_fail": 0})
        leaked = evaluator.door_rows(routes, [dict(opened, index=0), dict(walked_back, index=1), dict(walked, index=2)])
        self.assertEqual(leaked, {"both": 0, "one": 1, "none": 0, "geometry": 0, "load_fail": 1})
        # both sides crossed, and the file never stored a prompt: not a confirmed swing
        bare = {"start_read": "0 0 0", "end_read": "3 0 0"}
        bare_back = {"start_read": "0 0 0", "end_read": "-3 0 0"}
        old = evaluator.door_rows(routes, [dict(bare, index=0), dict(bare_back, index=1), dict(held, index=2)])
        self.assertEqual(old, {"both": 0, "one": 0, "none": 0, "geometry": 1, "load_fail": 0})
        mixed = evaluator.door_rows(routes, [dict(opened, index=0), dict(bare_back, index=1), dict(held, index=2)])
        self.assertEqual(mixed["both"], 0)
        self.assertEqual(mixed["geometry"], 0)
        self.assertEqual(mixed["one"], 1)
        # the same route twice is one side, not a pair
        twice = evaluator.door_rows(routes, [dict(opened, index=0), dict(opened, index=0), dict(held, index=2)])
        self.assertEqual(twice["both"], 0)
        self.assertEqual(twice["one"], 1)
        # two OPEN crossings on side 1 are still one side
        same = [dict(wood, side=1), dict(wood, side=1), load]
        sided = evaluator.door_rows(same, [dict(opened, index=0), dict(opened, index=1), dict(held, index=2)])
        self.assertEqual(sided["both"], 0)
        self.assertEqual(sided["one"], 1)
        opposite = [dict(wood, side=1), dict(other, side=-1), load]
        paired = evaluator.door_rows(opposite, [dict(opened, index=0), dict(opened_back, index=1), dict(held, index=2)])
        self.assertEqual(paired["both"], 1)
        # labels 1 and -1, but both walks use the same plane normal
        parallel = [dict(wood, side=1), dict(wood, side=-1), load]
        same_way = evaluator.door_rows(parallel, [dict(opened, index=0), dict(opened, index=1), dict(held, index=2)])
        self.assertEqual(same_way["both"], 0)
        self.assertEqual(same_way["one"], 1)
        unlabeled = [wood, dict(wood), load]
        same_plain = evaluator.door_rows(unlabeled, [dict(opened, index=0), dict(opened, index=1), dict(held, index=2)])
        self.assertEqual(same_plain["both"], 0)
        self.assertEqual(same_plain["one"], 1)
        self.assertFalse(evaluator.finished({}, {"load_fail": 0}, 0))
        self.assertTrue(evaluator.finished({"PASS": 2}, {"load_fail": 0}, 2))
        self.assertFalse(evaluator.finished({"PASS": 1}, {"load_fail": 1}, 1))
        self.assertFalse(evaluator.finished({"PASS": 1, "BLOCKED": 1}, {"load_fail": 0}, 2))
        self.assertFalse(evaluator.finished({"PASS": 2}, {"load_fail": 0, "geometry": 1}, 2))
