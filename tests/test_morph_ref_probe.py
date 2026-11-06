"""scripts/armor/morph_ref_probe.py: finds the record and field naming a text (synthetic plugin)."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import morph_ref_probe as M  # noqa: E402
from fo4sf import sfplugin  # noqa: E402

HDR = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(8)       # noqa: E731


class ProbeTests(unittest.TestCase):
    def test_search(self):
        recs = [(b"ARMA", HDR(b"ARMA"), [(b"EDID", sfplugin.zs("AA_Test")),
                                         (b"MOD2", sfplugin.zs("Clothes\\x.nif"))], 0x800),
                (b"MRPH", HDR(b"MRPH"), [(b"EDID", sfplugin.zs("Morph_Nightwear")),
                                         (b"MPTH", sfplugin.zs("Clothes\\Outfit_Nightwear_01\\Outfit_Nightwear_01_M"))],
                 0x801)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.esm")
            with open(p, "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}))
            hits = M.search(p, ["outfit_nightwear_01_m"])
        self.assertEqual([(h["type"], h["edid"], h["field"]) for h in hits], [("MRPH", "Morph_Nightwear", "MPTH")])
        self.assertIn("Outfit_Nightwear_01_M", hits[0]["text"])


if __name__ == "__main__":
    unittest.main()
