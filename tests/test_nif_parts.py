"""nif_parts: the shapes of a head-part NIF (2026-11-11: what the player's _facebones twins hold)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

from fo4sf import nif as nifmod, sfnif  # noqa: E402
import nif_parts as P  # noqa: E402


class PartsTests(unittest.TestCase):
    def test_lists_geometry(self):
        sh = sfnif.StaticShape(b"Teeth", b"aaaa\\bbbb", 3, 3, "materials\\teeth.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        lines = P.parts(nifmod.serialize(sfnif.build_static_nif(b"Root", [sh])))
        text = "\n".join(lines)
        self.assertIn("BSGeometry 'Teeth'", text)
        self.assertIn("materials\\teeth.mat", text)
        self.assertIn("LODs [3] first mesh aaaa\\bbbb", text)
        self.assertIn("skin 0 bones", text)


if __name__ == "__main__":
    unittest.main()
