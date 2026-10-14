import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "route_activation", Path(__file__).resolve().parents[1] / "scripts" / "oracles" / "route_activation.py")
activation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activation)

eval_spec = importlib.util.spec_from_file_location(
    "route_eval", Path(__file__).resolve().parents[1] / "scripts" / "game" / "route_eval.py")
evaluator = importlib.util.module_from_spec(eval_spec)
eval_spec.loader.exec_module(evaluator)


def hinge(ref, normal):
    return {"kind": "door", "ref": ref, "model": "Doors\\Wood.nif", "start": [0, 0, 0],
            "expect": {"plane_point": [0, 0, 0], "plane_normal": normal, "min_past": 0.8}}


def opened(index, end):
    return {"index": index, "start_read": "0 0 0", "end_read": end, "prompt": True, "verb": "OPEN"}


class RouteActivationTests(unittest.TestCase):
    def test_one_open_leaves_the_other_doors_unproven(self):
        routes = [hinge("near", [1, 0, 0]), hinge("near", [-1, 0, 0]),
                  hinge("far", [1, 0, 0]), hinge("far", [-1, 0, 0])]
        report = evaluator.unproven(routes, [opened(0, "3 0 0")])
        self.assertEqual(report["unproven"], ["near", "far"])
        self.assertEqual(report["load_fail"], [])
        self.assertTrue(evaluator.finished({"PASS": 1}, {"load_fail": 0, "geometry": 0}, 1))

    def test_both_opens_prove_only_that_ref(self):
        routes = [hinge("near", [1, 0, 0]), hinge("near", [-1, 0, 0])]
        report = evaluator.unproven(routes, [opened(0, "3 0 0"), opened(1, "-3 0 0")])
        self.assertEqual(report, {"unproven": [], "load_fail": []})

    def test_a_crossing_without_open_is_not_proof(self):
        routes = [hinge("near", [1, 0, 0]), hinge("near", [-1, 0, 0])]
        bare = [{"index": 0, "start_read": "0 0 0", "end_read": "3 0 0"},
                {"index": 1, "start_read": "0 0 0", "end_read": "-3 0 0"}]
        self.assertEqual(evaluator.unproven(routes, bare)["unproven"], ["near"])

    def test_two_opens_on_the_same_side_stay_unproven(self):
        routes = [dict(hinge("near", [1, 0, 0]), side=1), dict(hinge("near", [1, 0, 0]), side=1)]
        report = evaluator.unproven(routes, [opened(0, "3 0 0"), opened(1, "3 0 0")])
        self.assertEqual(report["unproven"], ["near"])

    def test_opposite_recorded_sides_prove_that_ref(self):
        routes = [dict(hinge("near", [1, 0, 0]), side=1), dict(hinge("near", [-1, 0, 0]), side=-1)]
        report = evaluator.unproven(routes, [opened(0, "3 0 0"), opened(1, "-3 0 0")])
        self.assertEqual(report, {"unproven": [], "load_fail": []})

    def test_opposite_labels_on_the_same_direction_stay_unproven(self):
        routes = [dict(hinge("near", [1, 0, 0]), side=1), dict(hinge("near", [1, 0, 0]), side=-1)]
        report = evaluator.unproven(routes, [opened(0, "3 0 0"), opened(1, "3 0 0")])
        self.assertEqual(report["unproven"], ["near"])

    def test_two_visits_the_same_way_without_side_stay_unproven(self):
        routes = [hinge("near", [1, 0, 0]), hinge("near", [1, 0, 0])]
        report = evaluator.unproven(routes, [opened(0, "3 0 0"), opened(1, "3 0 0")])
        self.assertEqual(report["unproven"], ["near"])

    def test_the_same_route_twice_is_one_side(self):
        routes = [hinge("near", [1, 0, 0]), hinge("near", [-1, 0, 0])]
        report = evaluator.unproven(routes, [opened(0, "3 0 0"), opened(0, "3 0 0")])
        self.assertEqual(report["unproven"], ["near"])

    def test_a_crossed_load_door_is_listed_and_a_bad_index_is_ignored(self):
        routes = [hinge("near", [1, 0, 0]), hinge("near", [-1, 0, 0]),
                  {"kind": "door", "ref": "entrance", "model": "Doors\\WoodLoad.nif", "start": [0, 0, 0],
                   "expect": {"plane_point": [0, 0, 0], "plane_normal": [1, 0, 0], "min_past": 0.8}}]
        fell = {"index": 2, "start_read": "0 0 0", "end_read": "3 0 -70", "prompt": False}
        report = evaluator.unproven(routes, [opened(0, "3 0 0"), opened(1, "-3 0 0"), fell, {"index": 9}])
        self.assertEqual(report["unproven"], [])
        self.assertEqual(report["load_fail"], ["entrance"])

    def test_no_hinged_doors_exits_zero_and_one_open_exits_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            empty = root / "routes.json"
            results = root / "results.jsonl"
            empty.write_text(json.dumps({"routes": []}), encoding="utf-8")
            results.write_text("", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(activation.main(["--routes", str(empty), "--results", str(results)]), 0)
            routes = root / "doors.json"
            routes.write_text(json.dumps({"routes": [hinge("near", [1, 0, 0]), hinge("near", [-1, 0, 0])]}),
                              encoding="utf-8")
            results.write_text(json.dumps(opened(0, "3 0 0")) + "\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(activation.main(["--routes", str(routes), "--results", str(results)]), 1)
