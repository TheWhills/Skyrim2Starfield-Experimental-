"""face_layer_probe: face texture layer blocks of an NPC (2026-11-13, Elder faces)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

import face_layer_probe as P  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                 # noqa: E731


class FaceLayerProbeTests(unittest.TestCase):
    def test_blocks(self):
        subs = [(b"EDID", Z("X")), (b"MNAM", struct.pack("<I", 2)), (b"TNAM", Z("Dermaesthetic")),
                (b"QNAM", Z("european_female_ol1_sk3")), (b"VNAM", Z("a.dds")), (b"TNAM", Z("Accents2")),
                (b"QNAM", Z("Accents_14")), (b"INTV", struct.pack("<f", 0.5)), (b"STON", b"\x03")]
        b = P.layer_blocks(subs)
        self.assertEqual([dict(x)["TNAM"] for x in b], ["Dermaesthetic", "Accents2"])
        self.assertEqual(b[0][0], ("MNAM", "00000002 / 2.803e-45"))
        self.assertEqual(dict(b[1])["QNAM"], "Accents_14")
        self.assertEqual(dict(b[1])["INTV"], "3F000000 / 0.5")
        self.assertEqual(P.show(b"\x01\x02"), "01 02")


if __name__ == "__main__":
    unittest.main()
