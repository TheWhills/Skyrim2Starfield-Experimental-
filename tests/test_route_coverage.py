import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "route_coverage", Path(__file__).resolve().parents[1] / "scripts" / "oracles" / "route_coverage.py")
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def cell():
    return {"cell": "Example", "refs": [
        {"formkey": "swing", "model": "Doors\\Wood.nif"},
        {"formkey": "frame", "model": "Doors\\Doorway.nif"},
        {"formkey": "load", "model": "Doors\\WoodLoad.nif"},
    ]}


def items():
    return {
        "meshes\\doors\\wood.nif": {"door": {"anim_graph": "open.agx"}},
        "meshes\\doors\\doorway.nif": {"door": None},
        "meshes\\doors\\woodload.nif": {},
    }


class RouteCoverageTests(unittest.TestCase):
    def test_a_swing_with_no_route_is_unrouted(self):
        self.assertEqual(coverage.unrouted(cell(), items(), []), ["swing"])

    def test_a_door_route_covers_the_swing_and_ignores_frames(self):
        routes = [{"kind": "door", "ref": "swing"}, {"kind": "stairs", "ref": "frame"}]
        self.assertEqual(coverage.unrouted(cell(), items(), routes), [])

    def test_a_stair_route_for_the_same_ref_does_not_count(self):
        routes = [{"kind": "stairs", "ref": "swing"}]
        self.assertEqual(coverage.unrouted(cell(), items(), routes), ["swing"])

    def test_one_visit_is_not_both_sides(self):
        routes = [
            {"kind": "door", "ref": "swing", "model": "Doors\\Wood.nif"},
            {"kind": "door", "ref": "swing", "model": "Doors\\Wood.nif"},
            {"kind": "door", "ref": "only", "model": "Doors\\Wood.nif"},
            {"kind": "door", "ref": "entrance", "model": "Doors\\WoodLoad.nif"},
        ]
        self.assertEqual(coverage.single_sided(routes), ["only"])

    def test_two_routes_on_one_side_are_not_both_sides(self):
        routes = [
            {"kind": "door", "ref": "swing", "model": "Doors\\Wood.nif", "side": 1},
            {"kind": "door", "ref": "swing", "model": "Doors\\Wood.nif", "side": 1},
            {"kind": "door", "ref": "both", "model": "Doors\\Wood.nif", "side": 1},
            {"kind": "door", "ref": "both", "model": "Doors\\Wood.nif", "side": -1},
        ]
        self.assertEqual(coverage.single_sided(routes), ["swing"])
