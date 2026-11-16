"""scripts/armor/anim_object_probe.py: ANIO records and AnimObj events, on synthetic data."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import sfplugin  # noqa: E402
import anim_object_probe as P  # noqa: E402


class AnimObjectProbeTest(unittest.TestCase):
    def test_anio_records(self):
        recs = [(b"ANIO", b"ANIO" + bytes(20), [(b"EDID", b"AnimObjectBroom\0"),
                                                (b"MODL", b"AnimObjects\\Broom01.nif\0"), (b"BNAM", b"\x01\x02")],
                 0x1234),
                (b"ANIO", b"ANIO" + bytes(20), [(b"EDID", b"AnimObjectMug\0"), (b"MODL", b"Mug.nif\0")], 0x1235)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.esm")
            with open(p, "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 1.7, "form_version": 44}, masters=()))
            got = P.anio_records(p, "broom")
        self.assertEqual(len(got), 1)
        fid, edid, fields = got[0]
        self.assertEqual((edid, fields["MODL"], fields["BNAM"]), ("AnimObjectBroom", "AnimObjects\\Broom01.nif", "0102"))

    def test_anim_obj_events(self):
        t = ("<root><events><event><time>0</time><name>AnimObjLoad</name><payload>AnimObjectBroom</payload></event>"
             "<event><name>AnimObjDraw</name></event><event><name>FootLeft</name></event></events></root>")
        self.assertEqual(P.anim_obj_events(t), [("AnimObjLoad", "AnimObjectBroom"), ("AnimObjDraw", "")])


if __name__ == "__main__":
    unittest.main()
