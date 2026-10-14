"""Synthetic production checks for load-door safety before teleport support."""
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_review_fixes import nested_nif
from fo4sf import pipeline


class LoadDoorPolicyTests(unittest.TestCase):
    def convert(self, name, staging):
        converter = pipeline.Converter.__new__(pipeline.Converter)
        converter.src = SimpleNamespace(mesh=lambda _: nested_nif())
        converter.staging = staging
        converter.prefix = "fo4port"
        converter.no_collision = None
        converter.collision_template = b"synthetic collision"
        converter.sf_mesh_template = b"synthetic native template"
        converter.rig_doors = True
        converter.door_physics_donor = b"synthetic donor"
        converter.neutral = "placeholder.mat"
        converter._shape_material = Mock(return_value="synthetic.mat")
        converter.stats = {"assets": 0, "failed": 0}
        return converter.convert_nif(name)

    def test_load_doors_stay_static_with_collision_and_report_missing_teleport(self):
        for name in ("meshes/doors/SyntheticDoorLoad01.nif", "meshes/doors/LoadSyntheticDoor01.nif"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as staging, \
                    patch.object(pipeline.nif, "door_hinge", return_value=True), \
                    patch.object(pipeline.convert_static, "convert_door", return_value=({}, (0, 0, 0), ((0, 0, 0), (1, 1, 1)))) as swing, \
                    patch.object(pipeline.convert_static, "convert_static", return_value={}) as static:
                result = self.convert(name, staging)
                self.assertTrue(result["ok"], result)
                swing.assert_not_called()
                self.assertNotIn("door", result)
                self.assertIn("teleport not ported", result["load_door"])
                self.assertEqual(static.call_args.kwargs["collision_template"], b"synthetic collision")
                self.assertEqual(static.call_args.kwargs["sf_mesh_template"], b"synthetic native template")

    def test_ordinary_hinged_door_still_uses_moving_conversion(self):
        with tempfile.TemporaryDirectory() as staging, \
                patch.object(pipeline.nif, "door_hinge", return_value=True), \
                patch.object(pipeline.convert_static, "convert_door", return_value=({}, (0, 0, 0), ((0, 0, 0), (1, 1, 1)))) as swing:
            result = self.convert("meshes/doors/SyntheticDoor01.nif", staging)
            self.assertTrue(result["ok"], result)
            swing.assert_called_once()
            self.assertIn("door", result)
            self.assertNotIn("load_door", result)
