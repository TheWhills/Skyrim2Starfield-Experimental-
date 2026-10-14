import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("collision_coverage", Path(__file__).resolve().parents[1]
                                           / "scripts" / "oracles" / "collision_coverage.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


class CollisionCoverageOracleTests(unittest.TestCase):
    def test_source_collision_failure_remains_unassessed_after_box_fallback(self):
        result = oracle.audit({"items": [{"source": "stairs", "collision_report": {
            "boxes": 5, "fo4_collision_error": "unsupported source body"}}]})
        self.assertEqual(result["unassessed"], ["stairs"])
        self.assertEqual(len(result["fallbacks"]), 1)
        self.assertEqual(result["reported_without_drops"], 0)

    def test_empty_collision_and_invalid_resolution_cannot_pass(self):
        for report in [{"boxes": 0}, {"boxes": 2, "surface_cell": float("nan")},
                       {"boxes": 2, "fo4_collision_error": True}]:
            result = oracle.audit({"items": [{"source": "bad", "collision_report": report}]})
            self.assertEqual(result["reported_without_drops"], 0)
            self.assertTrue(result["errors"] or result["unassessed"])

    def test_dropped_fallback_is_still_incomplete(self):
        result = oracle.audit({"items": [{"source": "bad", "collision_report": {
            "boxes": 2, "floor_dropped": 1, "fo4_collision_error": "failed to decode"}}]})
        self.assertEqual(len(result["incomplete"]), 1)

    def test_missing_report_is_not_a_pass(self):
        result = oracle.audit({"items": [{"source": "unknown", "collision_report": {}}]})
        self.assertEqual(result["unassessed"], ["unknown"])
        self.assertEqual(result["reported_without_drops"], 0)

    def test_any_dropped_coverage_is_incomplete(self):
        result = oracle.audit({"items": [{"source": key, "collision_report": {"boxes": 2, key: 1}}
                                        for key in oracle.COUNTS]})
        self.assertEqual(len(result["incomplete"]), 3)
        self.assertEqual(result["reported_without_drops"], 0)

    def test_coarse_resolution_is_exposed_even_without_drops(self):
        result = oracle.audit({"items": [{"source": "floor", "collision_report": {"boxes": 2, "surface_cell": 1.0}}]})
        self.assertEqual(len(result["coarsened"]), 1)
        self.assertEqual(result["reported_without_drops"], 1)

    def test_malformed_counts_cannot_pass(self):
        for value in [-1, "1", True, 1.5]:
            result = oracle.audit({"items": [{"source": "bad", "collision_report": {"floor_dropped": value}}]})
            self.assertTrue(result["errors"])
            self.assertEqual(result["reported_without_drops"], 0)

    def test_malformed_manifest_entries_are_reported(self):
        for manifest in [[], {"items": []}, {"items": [None]},
                         {"items": [{"collision_report": {"boxes": -1}}]}]:
            self.assertTrue(oracle.audit(manifest)["errors"])
