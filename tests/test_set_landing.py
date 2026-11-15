import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import set_landing as SL  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402
from fo4sf import packages  # noqa: E402


def Z(s):
    return s.encode() + b"\0"


def ref(fid, edid, pos):
    return rec(b"REFR", fid, [(b"EDID", Z(edid)), (b"NAME", struct.pack("<I", 0x7145)),
                              (b"DATA", struct.pack("<6f", *pos, 0, 0, 0))])


class SetLandingTests(unittest.TestCase):
    def test_location_marker_and_in_place_patch(self):
        """ThroatoftheWorldLocation's MNAM marker gives the place; an unknown location names similar ones; the
        planet plugin's two markers move in place (same size), the map marker 2 m above the pad."""
        hdr = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
        with tempfile.TemporaryDirectory() as d:
            sky = os.path.join(d, "Skyrim.esm")
            loc = rec(b"LCTN", 0x100, [(b"EDID", Z("ThroatoftheWorldLocation")), (b"MNAM", struct.pack("<I", 0x200))])
            other = rec(b"LCTN", 0x101, [(b"EDID", Z("HighHrothgarLocation"))])
            mk = rec(b"REFR", 0x200, [(b"NAME", struct.pack("<I", 0x10)),
                                      (b"DATA", struct.pack("<6f", 1234.0, -5678.0, 9000.0, 0, 0, 0))])
            with open(sky, "wb") as fh:
                fh.write(hdr + grup(b"LCTN", 0, [loc, other]) + grup(b"REFR", 0, [mk]))
            ix = packages.Index(sky)
            try:
                self.assertEqual(SL.place_of_location(ix, "throatoftheworldlocation"), (1234.0, -5678.0, 9000.0))
                with self.assertRaises(SystemExit) as cm:
                    SL.place_of_location(ix, "HighHrothgarCourtyardLocation")
                self.assertIn("HighHrothgarLocation", str(cm.exception))
            finally:
                ix.close()
            planet = os.path.join(d, "Planet.esm")
            with open(planet, "wb") as fh:
                fh.write(hdr + grup(b"CELL", 0, [ref(0x810, "SKY_NirnLandingMarker", (1, 2, 3)),
                                                 ref(0x811, "SKY_NirnMapMarker", (1, 2, 5)),
                                                 ref(0x812, "SomethingElse", (7, 7, 7))]))
            size = os.path.getsize(planet)
            offs = SL.marker_offsets(planet, "Nirn")
            self.assertEqual(sorted(offs), ["landing", "map"])
            SL.patch_markers(planet, offs, (100.5, -200.25, 640.0))
            self.assertEqual(os.path.getsize(planet), size)
            with open(planet, "rb") as fh:
                buf = fh.read()
            self.assertEqual(struct.unpack_from("<3f", buf, offs["landing"]), (100.5, -200.25, 640.0))
            self.assertEqual(struct.unpack_from("<3f", buf, offs["map"]), (100.5, -200.25, 642.0))
            self.assertIn(struct.pack("<3f", 7, 7, 7), buf)                      # other references untouched


if __name__ == "__main__":
    unittest.main()
