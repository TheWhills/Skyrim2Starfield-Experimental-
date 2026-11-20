"""scripts/tools/model_bounds.py: a mod archive given with --archive is searched before the game's (2026-11-20)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tools"))

import model_bounds as MB  # noqa: E402


class FakeBa2:
    def __init__(self, path):
        self.path = path
        self.files = {"meshes\\a.nif": os.path.basename(path).encode()}

    def find(self, name):
        return name if name in self.files else None

    def read(self, name):
        return self.files[name]


class ArchiveOrderTests(unittest.TestCase):
    def test_mod_archive_first(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "Starfield - Meshes01.ba2"), "wb").close()
            with mock.patch.object(MB.ba2, "Ba2", FakeBa2):
                self.assertEqual(MB.Archives(d).read("meshes\\a.nif"), b"Starfield - Meshes01.ba2")
                mod = os.path.join(d, "mods", "S2SClothes - Main.ba2")
                self.assertEqual(MB.Archives(d, [mod]).read("meshes\\a.nif"), b"S2SClothes - Main.ba2")


if __name__ == "__main__":
    unittest.main()
