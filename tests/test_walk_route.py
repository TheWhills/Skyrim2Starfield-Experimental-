import importlib.util
import math
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "walk_route", Path(__file__).resolve().parents[1] / "scripts" / "game" / "walk_route.py")
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def point(x, y, z, name):
    return (x, y, z, name)


class FacingTests(unittest.TestCase):
    def test_cardinal_yaw_matches_creation_engine(self):
        origin = (0, 0, 0)
        self.assertAlmostEqual(route.facing_yaw_degrees(origin, (0, 1, 0)), 0)
        self.assertAlmostEqual(route.facing_yaw_degrees(origin, (1, 0, 0)), 90)
        self.assertAlmostEqual(route.facing_yaw_degrees(origin, (0, -1, 0)), 180)
        self.assertAlmostEqual(route.facing_yaw_degrees(origin, (-1, 0, 0)), 270)


class RouteTests(unittest.TestCase):
    def test_straight_floor_stays_in_order_and_a_void_does_not_connect(self):
        points = [point(i * 2, 0, 0, f"f{i}") for i in range(4)] + [point(30, 0, 0, "far")]
        ordered = route.route(points)
        self.assertEqual([p[3] for p in ordered], ["f0", "f1", "f2", "f3"])

    def test_unwalkable_rise_breaks_the_chain(self):
        points = [point(0, 0, 0, "low"), point(2, 0, 0, "mid"), point(4, 0, 2, "high")]
        ordered = route.route(points)
        self.assertEqual([p[3] for p in ordered], ["low", "mid"])
        self.assertNotIn("high", [p[3] for p in ordered])

    def test_floor_pieces_come_from_cell_metres(self):
        cell = {"refs": [
            {"type": "Static", "model": "meshes\\architecture\\floor01.nif", "pos": [0, 0, 0]},
            {"type": "Static", "model": "meshes\\architecture\\stairs01.nif", "pos": [140, 0, 14]},
            {"type": "Light", "model": "meshes\\architecture\\floor01.nif", "pos": [70, 0, 0]},
            {"type": "Static", "model": "meshes\\clutter\\chair.nif", "pos": [70, 0, 0]},
        ]}
        points = route.floor_points(cell)
        self.assertEqual([p[3] for p in points], ["floor01.nif", "stairs01.nif"])
        self.assertAlmostEqual(points[1][0], 2.0)
        self.assertAlmostEqual(points[1][2], 0.2)


class ScoreTests(unittest.TestCase):
    def test_only_arrival_passes_and_a_drop_is_a_fall(self):
        start, target = (0, 0, 1), (2, 0, 1)
        self.assertEqual(route.score_leg(start, (2.1, 0.1, 1.0), target), "ARRIVED")
        self.assertEqual(route.score_leg(start, (1.0, 0.0, 1.0), target), "PROGRESSED")
        self.assertEqual(route.score_leg(start, (0.0, 0.0, 1.0), target), "STUCK")
        self.assertEqual(route.score_leg(start, (0.1, 0.0, -1.0), target), "FELL")
        self.assertEqual(route.score_leg(start, (0.0, 2.0, 1.0), target), "MISSED")
        labels = route.score_rows([
            {"start": start, "target": target, "end": (2, 0, 1)},
            {"start": start, "target": target, "end": None},
        ])
        self.assertEqual(labels, ["ARRIVED", "UNREAD"])
        self.assertFalse(route.route_failed(["ARRIVED", "ARRIVED"]))
        self.assertTrue(route.route_failed(["ARRIVED", "PROGRESSED"]))
        self.assertTrue(route.route_failed([]))

    def test_step_down_onto_the_next_floor_is_not_a_fall(self):
        self.assertEqual(route.score_leg((0, 0, 1.0), (2, 0, 0.6), (2, 0, 0.6)), "ARRIVED")

    def test_hold_time_tracks_distance(self):
        planned = route.legs([point(0, 0, 0, "a"), point(0, 2, 0, "b")])
        self.assertEqual(len(planned), 1)
        self.assertAlmostEqual(planned[0]["yaw"], 0)
        self.assertGreater(planned[0]["hold_ms"], 1000)
        self.assertLess(planned[0]["hold_ms"], 2000)
        self.assertTrue(math.isfinite(planned[0]["yaw"]))
