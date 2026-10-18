import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

import make_planet as mp  # noqa: E402
from fo4sf import fo4land  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402


def jemison_subs():
    return [(b"EDID", b"JemisonPlanetData\0"), (b"FULL", b"\xfd\xa7\0\0"),
            (b"CNAM", struct.pack("<ddI", 0.71, 2.32, 0x1251B)),
            (b"PPBD", struct.pack("<If", mp.OCEAN, 60.0) + b"\0" * 8), (b"PPBD", struct.pack("<If", 0x0FD00D, 10.0)),
            (b"PPBD", struct.pack("<If", mp.LAND, 14.0) + b"\1\2"), (b"FNAM", b"\xd2\xfc\x05\x00"),
            (b"GNAM", struct.pack("<f", 0.59)), (b"ANAM", b"Jemison\0"), (b"CNAM", b"\x02"),
            (b"ENAM", struct.pack("<9d", 2.2e8, 2.1e8, 2.3e8, 0.0, 0.1, 0.0, 2.2e8, 0.0, 0.0)),
            (b"FNAM", struct.pack("<dIffI", 9.5e9, 0x68C75144, 7484.0, 0.91, 215)),
            (b"GNAM", struct.pack("<III", 0x11720, 0, 3))]


class MakePlanet(unittest.TestCase):
    def test_subrecords(self):
        out = dict()
        subs = mp.planet_subrecords(jemison_subs(), "Nirn", "NirnPlanetData", 200, 30, [(-1.5707963, 0.0, 0x01000803)],
                                    {mp.OCEAN: 95.0, mp.LAND: 5.0}, 1.3)
        sigs = [s for s, _d in subs]
        self.assertEqual(sigs.count(b"PPBD"), 2)                          # the frozen biome is dropped
        for s, d in subs:
            out.setdefault(s, []).append(d)
        self.assertEqual(out[b"ANAM"], [b"Nirn\0"])
        self.assertEqual(out[b"FULL"], [b"Nirn\0"])
        self.assertEqual(struct.unpack("<ddI", out[b"CNAM"][0]), (-1.5707963, 0.0, 0x01000803))
        self.assertEqual(out[b"CNAM"][1], b"\x02")                        # the planet-type CNAM is kept
        self.assertAlmostEqual(struct.unpack_from("<f", out[b"FNAM"][1], 12)[0], 200.0)
        self.assertEqual(struct.unpack("<III", out[b"GNAM"][1]), (0x11720, 0, 30))
        self.assertAlmostEqual(struct.unpack("<9d", out[b"ENAM"][0])[0], 2.2e8 * 1.3)
        self.assertEqual(struct.unpack_from("<If", out[b"PPBD"][1]), (mp.LAND, 5.0))
        self.assertEqual(out[b"PPBD"][1][8:], b"\1\2")

    def test_remap_and_clean_biome(self):
        subs = mp.planet_subrecords(jemison_subs(), "Nirn", "NirnPlanetData", 500, 30, [], {mp.OCEAN: 100.0}, 1.0,
                                    remap={mp.OCEAN: 0x02000801})
        self.assertEqual([struct.unpack_from("<If", d) for s, d in subs if s == b"PPBD"], [(0x02000801, 100.0)])
        b = mp.clean_biome([(b"EDID", b"OceanLife04\0"), (b"JNAM", b"w.mat\0"), (b"EFSD", b"gl.mat\0")], "NirnOcean")
        self.assertEqual(b, [(b"EDID", b"NirnOcean\0"), (b"JNAM", b"w.mat\0")])
        with self.assertRaises(ValueError):
            mp.clean_biome(b, "x")

    def test_biome_map_layout(self):
        b = mp.biome_map(3.0)
        self.assertEqual(len(b), 6 + 8 + 4 + 2 * (12 + 4 * 65536 + 4 + 65536))
        ver, n = struct.unpack_from("<HI", b)
        self.assertEqual((ver, n), (0x105, 2))
        first = 6 + 8 + 4 + 12
        px = lambda x, y: struct.unpack_from("<I", b, first + 4 * (y * 256 + x))[0]   # noqa: E731
        self.assertEqual((px(128, 128), px(127, 127), px(0, 0), px(128, 140)), (mp.LAND, mp.LAND, mp.OCEAN, mp.OCEAN))

    def test_single_biome_map(self):
        b = mp.biome_map(0.0, land=0x0FD00D, ocean=0x0FD00D)
        self.assertEqual(struct.unpack_from("<2I", b, 6), (0x0FD00D, 0x0FD00D))
        self.assertEqual(struct.unpack_from("<I", b, 6 + 8 + 4 + 12 + 4 * 32896)[0], 0x0FD00D)

    def test_write_plugin_replaces_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "X_Mars.esm")
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 1, 0x800)), (b"MAST", b"Starfield.esm\0"),
                                    (b"MAST", b"X.esm\0")])
            old = grup(b"PNDT", 0, [rec(b"PNDT", 0x3F5A1, [(b"EDID", b"JemisonPlanetData\0")])])
            open(p, "wb").write(tes4 + old)
            self.assertEqual(mp.masters_of(p), ["Starfield.esm", "X.esm"])
            hdr = struct.pack("<4sIII", b"PNDT", 0, 0x40000, 0x3F5A1) + bytes(8)
            bh = struct.pack("<4sIII", b"BIOM", 0, 0, 0x7F88A) + bytes(8)
            mp.write_plugin(p, hdr, [(b"EDID", b"NirnPlanetData\0"), (b"ANAM", b"Nirn\0")], 0x02000800,
                            [(b"BIOM", bh, [(b"EDID", b"NirnOcean\0")], 0x02000801)])
            with fo4land.Plugin(p) as pl:
                _off, h, subs = mp.find_record(pl.buf, pl.body, b"PNDT", "NirnPlanetData")
                self.assertEqual(struct.unpack_from("<4sIII", h)[2:], (0, 0x02000800))
                self.assertEqual(dict(subs)[b"ANAM"], b"Nirn\0")
                with self.assertRaises(KeyError):
                    mp.find_record(pl.buf, pl.body, b"PNDT", "JemisonPlanetData")
                _o, bh2, _bs = mp.find_record(pl.buf, pl.body, b"BIOM", "NirnOcean")
                self.assertEqual(struct.unpack_from("<I", bh2, 12)[0], 0x02000801)
                hedr = dict(fo4land.iter_subrecords(bytes(pl.buf[24:24 + struct.unpack_from("<I", pl.buf, 4)[0]])))[b"HEDR"]
                self.assertEqual(struct.unpack_from("<II", hedr, 4), (2, 0x802))


if __name__ == "__main__":
    unittest.main()
