"""Production conversion must not invent collision for walk-through source models."""
import unittest
from unittest.mock import patch

from test_review_fixes import nested_nif
from fo4sf import convert_static, nif


class SourceCollisionAbsenceTests(unittest.TestCase):
    def test_native_conversion_preserves_absence_for_both_fallback_modes(self):
        for mode in ("box", "surfaces"):
            with self.subTest(mode=mode), patch.object(
                    convert_static.sfcollision, "box_blob",
                    side_effect=AssertionError("invented collision for walk-through source")), patch.object(
                    convert_static.sfcollision, "mesh_boxes",
                    side_effect=AssertionError("invented collision surfaces")):
                report = {}
                files = convert_static.convert_static(
                    nested_nif(), "fo4port/synthetic_walkthrough",
                    collision_template=b"synthetic donor", sf_mesh_template=b"synthetic donor",
                    collision_mode=mode, report=report)
                model = nif.parse(files["meshes/fo4port/synthetic_walkthrough.nif"])
                types = [model.type_of(i) for i in range(len(model.blocks))]
                self.assertIn("BSGeometry", types)
                self.assertNotIn("bhkNPCollisionObject", types)
                self.assertNotIn("bhkPhysicsSystem", types)
                self.assertEqual(report["source"], "fo4-none")
                self.assertTrue(any(name.endswith(".mesh") for name in files))
