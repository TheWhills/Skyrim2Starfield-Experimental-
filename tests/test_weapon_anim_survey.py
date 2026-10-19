"""scripts/armor/weapon_anim_survey.py on a synthetic plugin (no game data)."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import weapon_anim_survey as W  # noqa: E402
from test_make_planet import grup, rec  # noqa: E402

z = lambda t: t.encode() + b"\0"  # noqa: E731


class WeaponAnimSurveyTests(unittest.TestCase):
    def test_report(self):
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Starfield.esm")
            data = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 4, 0x800))]) + \
                grup(b"KYWD", 0, [rec(b"KYWD", 0x10, [(b"EDID", z("AnimsGripRifle"))]),
                                  rec(b"KYWD", 0x11, [(b"EDID", z("WeaponTypeRifle"))]),
                                  rec(b"KYWD", 0x12, [(b"EDID", z("AnimsBowUnused"))])]) + \
                grup(b"WEAP", 0, [rec(b"WEAP", 0x20, [(b"EDID", z("Rifle_Grendel")), (b"KSIZ", struct.pack("<I", 2)),
                                                      (b"KWDA", struct.pack("<2I", 0x10, 0x11))])]) + \
                grup(b"SGDA", 0, [rec(b"SGDA", 0x30, [(b"EDID", z("SubgraphRifle")),
                                                      (b"SGPT", z("Actors\\Human\\Animations\\Rifle\\"))])]) + \
                grup(b"RACE", 0, [rec(b"RACE", 0x40, [(b"EDID", z("HumanRace")),
                                                      (b"NAM6", z("AnimTextData\\Tables\\Graphs\\Human_Root.agx")),
                                                      (b"SGNM", z("AnimTextData\\Tables\\Graphs\\1stPerson_Gun.agx")),
                                                      (b"SAPT", z("Actors\\Human\\Animations\\Base\\")),
                                                      (b"STKD", struct.pack("<I", 0x10)),
                                                      (b"SRAF", bytes([1, 0, 1, 0]))])])
            open(esm, "wb").write(data)
            out = os.path.join(d, "out")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(W.main(["--esm", esm, "--out", out]), 0)
            rep = open(os.path.join(out, "report.txt"), encoding="utf-8").read()
            self.assertIn("SGDA        1  SubgraphRifle", rep)
            self.assertIn("SGDA       1 records", rep)                       # animation-path text found by content
            self.assertIn("field SGPT: ...Actors\\Human\\Animations\\Rifle", rep)   # a path field, not the EDID
            self.assertIn("1  AnimsGripRifle", rep)
            self.assertIn("AnimsBowUnused", rep.split("on no weapon")[1])
            self.assertIn("-> AnimsGripRifle, WeaponTypeRifle", rep)       # weapon keywords resolved
            self.assertIn("RACE 00000040 HumanRace", rep)
            self.assertIn("NAM6: AnimTextData\\Tables\\Graphs\\Human_Root.agx", rep)
            self.assertIn("target ['AnimsGripRifle'] -> 1stPerson_Gun.agx | Actors\\Human\\Animations\\Base\\", rep)


if __name__ == "__main__":
    unittest.main()
