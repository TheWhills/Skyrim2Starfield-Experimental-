import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "placed_collision", Path(__file__).resolve().parents[1] / "scripts" / "oracles" / "placed_collision.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def cell(*refs):
    return {"cell": "Example", "refs": list(refs)}


class PlacedCollisionTests(unittest.TestCase):
    def test_native_none_passable_and_rigged_doors_are_not_failures(self):
        items = {
            "meshes\\walls\\floor.nif": {"collision_report": {"source": "fo4-native", "bodies": 1}},
            "meshes\\props\\paper.nif": {"collision_report": {"source": "fo4-none"}},
            "meshes\\doors\\slide.nif": {"collision_report": {"source": "passable-door"}},
            "meshes\\doors\\hinge.nif": {"door": {"anim_graph": "open.agx"}, "collision_report": {}},
        }
        refs = [
            {"formkey": "floor", "model": "Walls\\Floor.nif"},
            {"formkey": "paper", "model": "Props\\Paper.nif"},
            {"formkey": "slide", "model": "Doors\\Slide.nif"},
            {"formkey": "hinge", "model": "Doors\\Hinge.nif"},
        ]
        self.assertEqual(oracle.placed(cell(*refs), items),
                         {"no_collision": [], "guessed": [], "partial": [], "unbuilt": []})

    def test_a_failed_native_body_and_a_guessed_box_are_listed(self):
        items = {
            "meshes\\lights\\hang.nif": {"collision_report": {
                "source": "fo4-native-failed", "fo4_collision_error": "PackfileError: open hull"}},
            "meshes\\pre\\cm.nif": {"collision_report": {
                "fo4_collision_error": "PackfileError: shared vertex", "boxes": 12}},
            "meshes\\pre\\bare.nif": {"collision_report": {"fo4_collision_error": "PackfileError: open hull"}},
            "meshes\\pre\\absent.nif": {"collision_report": {}},
            "meshes\\pre\\unused.nif": {"collision_report": {"source": "fo4-native-failed"}},
        }
        report = oracle.placed(cell(
            {"formkey": "light", "model": "Lights\\Hang.nif"},
            {"formkey": "pre", "model": "Pre\\cm.nif"},
            {"formkey": "bare", "model": "Pre\\Bare.nif"},
            {"formkey": "blank", "model": "Pre\\Absent.nif"},
            {"formkey": "skip", "model": ""},
        ), items)
        self.assertEqual([row["ref"] for row in report["no_collision"]], ["light", "bare", "blank"])
        self.assertEqual(report["no_collision"][0]["reason"], "fo4-native-failed")
        self.assertEqual([row["ref"] for row in report["guessed"]], ["pre"])

    def test_a_failure_that_is_not_placed_is_ignored(self):
        items = {"meshes\\pre\\cm.nif": {"collision_report": {"source": "fo4-native-failed"}}}
        self.assertEqual(oracle.placed(cell({"formkey": "other", "model": "Walls\\Floor.nif"}), items),
                         {"no_collision": [], "guessed": [], "partial": [], "unbuilt": []})

    def test_a_rejected_mesh_is_listed_and_an_unattempted_model_is_not(self):
        failures = [{"nif": "meshes/Lights/StrobeLight01Flash.nif",
                     "reason": "ValueError: only effect-shader shapes (glass/glow), skipped"}]
        report = oracle.placed(cell(
            {"formkey": "flash", "model": "Lights\\StrobeLight01Flash.nif"},
            {"formkey": "actor", "model": "Actors\\Somebody.nif"},
        ), {}, failures)
        self.assertEqual(report["no_collision"], [])
        self.assertEqual(report["guessed"], [])
        self.assertEqual(report["unbuilt"], [{
            "ref": "flash", "model": "Lights\\StrobeLight01Flash.nif",
            "reason": "ValueError: only effect-shader shapes (glass/glow), skipped"}])
        absent = oracle.placed(cell({"formkey": "other", "model": "Lights\\StrobeLight01Flash.nif"}), {})
        self.assertEqual(absent["unbuilt"], [])

    def test_a_skipped_part_with_a_box_fallback_is_still_guessed(self):
        items = {
            "meshes\\pre\\cm.nif": {"collision_report": {
                "skipped_parts": ["body 0: shared vertex index 2130 out of range (22)"],
                "boxes": 38}},
            "meshes\\pre\\kept.nif": {"collision_report": {
                "source": "fo4-native", "bodies": 1,
                "skipped_parts": ["body 0: shared vertex index 2130 out of range (8)"]}},
        }
        report = oracle.placed(cell(
            {"formkey": "cm", "model": "Pre\\cm.nif"},
            {"formkey": "kept", "model": "Pre\\kept.nif"},
        ), items)
        self.assertEqual(report["guessed"][0]["ref"], "cm")
        self.assertIn("2130", report["guessed"][0]["reason"])
        self.assertEqual([row["ref"] for row in report["partial"]], ["kept"])
        self.assertEqual(report["no_collision"], [])
