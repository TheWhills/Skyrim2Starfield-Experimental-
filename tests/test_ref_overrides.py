import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import ref_overrides as R  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402


def plugin(path, master_names, refs):
    """A plugin with these masters and REFRs [(raw FormID, flags, z, xesp parent or None)] in one cell group."""
    fields = [(b"HEDR", struct.pack("<fII", 1.0, 0, 0))]
    for m in master_names:
        fields += [(b"MAST", m.encode() + b"\0"), (b"DATA", b"\0" * 8)]
    items = []
    for fid, flags, z, parent in refs:
        f = [(b"NAME", struct.pack("<I", 0x0000ABCD)), (b"DATA", struct.pack("<6f", 1.0, 2.0, z, 0, 0, 0))]
        if parent is not None:
            f.append((b"XESP", struct.pack("<IB3x", parent, 1)))
        r = bytearray(rec(b"REFR", fid, f))
        struct.pack_into("<I", r, 8, flags)
        items.append(bytes(r))
    with open(path, "wb") as fh:
        fh.write(rec(b"TES4", 0, fields) + grup(b"CELL", 0, items))


class RefOverrideTests(unittest.TestCase):
    def test_owner_flags_and_position(self):
        """The terrain plugin's own 01502E (its index past Starfield.esm) and the port's override of it (index 1 in its
        masters) both resolve to the terrain plugin; a same-numbered record of another owner is told apart."""
        with tempfile.TemporaryDirectory() as d:
            terr = os.path.join(d, "Terrain.esm")
            port = os.path.join(d, "Port.esm")
            plugin(terr, ["Starfield.esm"], [(0x0100502E, 0, 184.88, None)])
            plugin(port, ["Starfield.esm", "Terrain.esm"],
                   [(0x0100502E, R.DISABLED, -815.12, 0x00000014), (0x0200502E, 0, 5.0, None)])
            _ml, hits = R.find(terr, 0x0400502E & 0xFFFFFF)
            self.assertEqual([(h[0], h[3]["disabled"], h[3]["pos"][2]) for h in hits], [("Terrain.esm", False, 184.88)])
            ml, hits = R.find(port, 0x00502E)
            self.assertEqual(ml, ["Starfield.esm", "Terrain.esm"])
            self.assertEqual([h[0] for h in hits], ["Terrain.esm", "Port.esm"])
            self.assertTrue(hits[0][3]["disabled"])
            self.assertEqual(hits[0][3]["enable_parent"], "000014:Starfield.esm flags 1")
            self.assertEqual(hits[0][3]["base"], "00ABCD:Starfield.esm")


if __name__ == "__main__":
    unittest.main()
