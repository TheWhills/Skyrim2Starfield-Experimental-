"""child_probe: what Skyrim's and Starfield's children are made of (races roadmap I2, 2026-11-12)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

import numpy as np  # noqa: E402

import child_probe as C  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                 # noqa: E731
I = lambda v: struct.pack("<I", v)                               # noqa: E731


class ChildProbeTests(unittest.TestCase):
    def test_race_heads(self):
        subs = [(b"EDID", Z("NordRaceChild")), (b"MNAM", b""), (b"INDX", I(0)), (b"HEAD", I(0x1C22E)),
                (b"INDX", I(1)), (b"HEAD", I(0x51401)), (b"FNAM", b""), (b"INDX", I(0)), (b"HEAD", I(0x1C558))]
        self.assertEqual(C.race_heads(subs), {False: [0x1C22E, 0x51401], True: [0x1C558]})

    def test_size_and_facegen_path(self):
        self.assertEqual(C.size_of(np.array([[0, 0, 0], [0.2, 0.25, 0.3]])),
                         {"vertices": 2, "size": [0.2, 0.25, 0.3]})
        self.assertEqual(C.facegen_path(0x00013477),
                         "meshes/actors/character/facegendata/facegeom/skyrim.esm/00013477.nif")

    def test_summarize_sf_children(self):
        child = 0x2AABCD
        npcs = [([(b"EDID", Z("Kid1")), (b"ACBS", I(1) + bytes(12)), (b"RNAM", I(child)), (b"FMSI", I(0)),
                  (b"VTCK", I(5))], 0x10),
                ([(b"EDID", Z("Kid2")), (b"ACBS", I(0) + bytes(12)), (b"RNAM", I(child)), (b"TPLT", I(0x10))], 0x11),
                ([(b"EDID", Z("Adult")), (b"ACBS", I(0) + bytes(12)), (b"RNAM", I(0x347D)), (b"FMSI", I(0))], 0x12)]
        out = C.summarize_sf_children(npcs, child, {0x10: {}})
        self.assertEqual(out["female"], {"npcs": 1, "dials": 1, "blends": 0, "baked_face": 1, "voiced": 1,
                                         "templated": 0, "examples": ["Kid1 00000010"]})
        self.assertEqual(out["male"]["npcs"], 1)
        self.assertEqual(out["male"]["templated"], 1)
        self.assertEqual(out["male"]["examples"], [])


if __name__ == "__main__":
    unittest.main()
