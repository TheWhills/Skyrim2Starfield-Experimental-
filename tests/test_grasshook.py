"""fo4sf.grasshook (2026-11-24): S2SGrass.ini for the S2SGrass SFSE plugin (route B, every texture its own cover)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import grasshook  # noqa: E402

MASTERS = ["Starfield.esm", "SkyrimTerrainTamriel.esm", "SkyrimTerrainTamriel_Mars.esm"]


class GrassHookTest(unittest.TestCase):
    def test_form_ref(self):
        self.assertEqual(grasshook.form_ref(0x00030137, MASTERS, "S2SGrass.esm"), "Starfield.esm:030137")
        self.assertEqual(grasshook.form_ref(0x0300080D, MASTERS, "S2SGrass.esm"), "S2SGrass.esm:00080D")
        self.assertEqual(grasshook.form_ref(0x01000801, MASTERS, "S2SGrass.esm"), "SkyrimTerrainTamriel.esm:000801")
        with self.assertRaises(ValueError):
            grasshook.form_ref(0x0400080D, MASTERS, "S2SGrass.esm")

    def test_ini(self):
        text = grasshook.hook_ini([(0x0003C0B8, 0x0300080E), (0x00030137, 0x0300080D)], MASTERS, "S2SGrass.esm",
                                  {0x00030137: "LFieldGrass02"})
        lines = text.split("\r\n")
        self.assertIn("[Settings]", lines)
        self.assertIn("bOnlyEmpty=1", lines)
        covers = lines[lines.index("[Covers]") + 1:]
        entries = [ln for ln in covers if ln and not ln.startswith(";")]
        self.assertEqual(entries, ["Starfield.esm:030137 = S2SGrass.esm:00080D ; LFieldGrass02",
                                   "Starfield.esm:03C0B8 = S2SGrass.esm:00080E"])     # sorted by texture
        self.assertTrue(text.endswith("\r\n"))

    def test_drop_underwater(self):
        slots = {1: ["kelp", "grass"], 2: ["kelp", "coral"], 3: ["grass"]}
        kept, dropped = grasshook.drop_underwater(slots, lambda g: g in ("kelp", "coral"))
        self.assertEqual(kept, {1: ["grass"], 3: ["grass"]})
        self.assertEqual(dropped, [2])


if __name__ == "__main__":
    unittest.main()
