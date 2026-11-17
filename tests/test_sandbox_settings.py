"""scripts/npc/sandbox_settings.py: GMST values and the sandbox duration formula (synthetic)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "src"))
import sandbox_settings as S  # noqa: E402


class SandboxSettingsTest(unittest.TestCase):
    def test_values_and_filter(self):
        recs = [("fSandboxDurationBase", struct.pack("<f", 0.1)), ("iSandboxSleepStartMin", struct.pack("<i", 19)),
                ("fJumpHeight", struct.pack("<f", 1.0)), ("fSandBoxInterMarkerMinDist", struct.pack("<f", 256.0))]
        s = S.sandbox_settings(recs)
        self.assertEqual(set(s), {"fSandboxDurationBase", "iSandboxSleepStartMin", "fSandBoxInterMarkerMinDist"})
        self.assertAlmostEqual(s["fSandboxDurationBase"], 0.1, places=5)
        self.assertEqual(s["iSandboxSleepStartMin"], 19)
        self.assertEqual(S.lookup(s, "fsandboxintermarkermindist"), 256.0)

    def test_durations_wiki_example(self):
        # the Fallout 4 CK wiki talk page's example: 0.1 * 3 * (1 + 50 * 0.05 * -0.1) = 0.225 h
        s = {"fSandboxDurationBase": 0.1, "fSandBoxEnergyMult": 0.05, "fSandboxDurationMultFurniture": 3.0,
             "fSandBoxEnergyMultFurniture": -0.1, "fSandboxDurationRangeMult": 0.5,
             "fSandboxDurationMultIdleMarker": 1.0}
        d = S.durations(s, 50.0)
        lo, mid, hi = d["Furniture"]
        self.assertAlmostEqual(mid, 0.225)
        self.assertAlmostEqual(lo, 0.1125)
        self.assertAlmostEqual(hi, 0.3375)
        self.assertAlmostEqual(d["IdleMarker"][1], 0.1)   # no energy multiplier for the type: base * mult
        self.assertEqual(S.durations({}, 50.0), {})
        self.assertIn("Furniture", S.report(s, {}, 50.0))


if __name__ == "__main__":
    unittest.main()
