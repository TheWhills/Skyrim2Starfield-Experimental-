"""scripts/interior/sf_animated_object_probe.py on synthetic records: graph / rig / folder found in any subrecord,
grouped by graph, loopy names listed with their folder's clips."""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import sf_animated_object_probe as P  # noqa: E402

FAN = [(b"EDID", b"ShipFan01\0"), (b"MODL", b"Ships\\Fan01.nif\0"),
       (b"BFCB", b"AnimationGraphComponent\0"),
       (b"ANAM", b"AnimTextData\\Tables\\Graphs\\SimpleLoop01.agx\0"),
       (b"BNAM", b"ships\\animated\\fan01\\characterassets\\skeleton.rig\0"),
       (b"CNAM", b"ships\\animated\\fan01\\animations\0")]
CRATE = [(b"EDID", b"Crate01\0"), (b"MODL", b"Crate.nif\0")]
BOX = [(b"EDID", b"Box01\0"), (b"ANAM", b"AnimTextData\\Tables\\Graphs\\SimpleOpenClose01.agx\0"),
       (b"BNAM", b"x\\skeleton.rig\0")]


class ProbeTests(unittest.TestCase):
    def test_scan_record(self):
        r = P.scan_record(FAN)
        self.assertEqual(r["edid"], "ShipFan01")
        self.assertTrue(r["graph"].endswith("SimpleLoop01.agx"))
        self.assertEqual(r["where"]["rig"], "BNAM")
        self.assertEqual(r["anims"], "ships\\animated\\fan01\\animations")
        self.assertEqual(P.scan_record(CRATE)["graph"], "")
        self.assertTrue(P.loopy(r))
        self.assertFalse(P.loopy(P.scan_record(BOX)))

    def test_main(self):
        import sf_anim_survey as SAS
        files = {"meshes/ships/animated/fan01/animations/idle.afx":
                 b"<root><is_state>1</is_state><tag>Idle</tag><filename>Spin.af</filename></root>",
                 "meshes/ships/animated/fan01/animations/spin.af": b"af"}

        class Ba2:
            names = list(files)

            def read(self, i):
                return files[self.names[i]]
        recs = [(b"STAT", b"", FAN, 0x100), (b"STAT", b"", CRATE, 0x101), (b"ACTI", b"", BOX, 0x102)]
        out = io.StringIO()
        with mock.patch.object(P.sfplugin, "records", lambda _p, _t: recs), \
                mock.patch.object(SAS, "archives", lambda _d: [("x", Ba2())]), contextlib.redirect_stdout(out):
            self.assertEqual(P.main(["--starfield", "S"]), 0)
        text = out.getvalue()
        self.assertIn("== 2 records with a graph and a rig", text)
        self.assertLess(text.index("SimpleLoop01"), text.index("SimpleOpenClose01"))      # loopy graphs first
        self.assertIn("idle.afx  tag Idle file Spin.af", text)
        self.assertNotIn("Crate01", text)


if __name__ == "__main__":
    unittest.main()
