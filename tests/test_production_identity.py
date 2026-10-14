"""Exercise converter cache behavior without game assets or texture tools."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fo4sf.pipeline import Converter


class ProductionCacheTests(unittest.TestCase):
    def setUp(self):
        self.converter = Converter.__new__(Converter)
        self.converter._materials = {}
        self.converter.stats = {"materials_ok": 0, "materials_fallback": 0}
        self.converter.material_errors = {}
        self.converter._convert_texture_set = Mock(side_effect=lambda stem, *args: stem + ".mat")

    def test_each_texture_changes_material_identity(self):
        c = self.converter
        original = c.texture_set_material("textures/a.dds", "textures/n.dds", "textures/s.dds")
        for inputs in [("textures/b.dds", "textures/n.dds", "textures/s.dds"),
                       ("textures/a.dds", "textures/n2.dds", "textures/s.dds"),
                       ("textures/a.dds", "textures/n.dds", "textures/s2.dds")]:
            self.assertNotEqual(original, c.texture_set_material(*inputs))
        self.assertEqual(c._convert_texture_set.call_count, 4)

    def test_slashes_and_case_share_one_conversion(self):
        c = self.converter
        first = c.texture_set_material("Textures/A.dds", "Textures/N.dds", "Textures/S.dds")
        self.assertEqual(first, c.texture_set_material("textures\\a.dds", "textures\\n.dds", "textures\\s.dds"))
        c._convert_texture_set.assert_called_once()

    def test_failure_is_cached_and_different_texture_can_succeed(self):
        c = self.converter
        c._convert_texture_set.side_effect = [FileNotFoundError("missing normal"), "good.mat"]
        inputs = ("a.dds", "missing.dds", "s.dds")
        self.assertIsNone(c.texture_set_material(*inputs))
        self.assertIsNone(c.texture_set_material(*inputs))
        self.assertEqual(c.texture_set_material("a.dds", "present.dds", "s.dds"), "good.mat")
        self.assertEqual(c._convert_texture_set.call_count, 2)
        self.assertEqual(c.stats, {"materials_ok": 1, "materials_fallback": 1})
        self.assertEqual(len(c.material_errors), 1)
