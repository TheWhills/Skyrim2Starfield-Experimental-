"""Synthetic tests for the overlay record fixes: src/fo4sf/overlay.py and scripts/terrain/overlay_records.py
(FNAM statistic, overlay mask, BC4 DDS, raw plugin walk helpers). No game data."""
import os
import re
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
from fo4sf import btd, overlay  # noqa: E402
import overlay_records as orc  # noqa: E402


def raw_grid(ncx, ncy, seed=1):
    rng = np.random.default_rng(seed)
    return rng.integers(20000, 30000, size=(ncy * 128, ncx * 128)).astype(np.uint16)


class Fnam(unittest.TestCase):
    def test_vanilla_sizes(self):
        for n, size in ((3, 18), (5, 50), (29, 1682)):
            self.assertEqual(len(overlay.fnam_bytes(np.zeros((n * 128, n * 128), np.uint16))), size)

    def test_sw_corner_of_every_cell_south_row_first(self):
        h = raw_grid(3, 2)
        for cy in range(2):
            for cx in range(3):
                h[cy * 128, cx * 128] = 100 * cy + cx      # the cell's SW corner sample (row 0 = south)
        self.assertEqual(overlay.fnam_values(h), [0, 1, 2, 100, 101, 102])
        self.assertEqual(struct.unpack("<6H", overlay.fnam_bytes(h)), (0, 1, 2, 100, 101, 102))

    def test_corner_is_not_another_statistic(self):
        h = np.full((256, 256), 30000, np.uint16)
        h[0, 0] = 10000                                    # corner far from min/mean/median/max of the rest
        h[5, 5] = 5000
        h[60, 60] = 60000
        v = overlay.fnam_values(h)[0]
        cell = h[:128, :128]
        self.assertEqual(v, 10000)
        self.assertNotIn(v, (int(cell.min()), int(cell.max()), int(np.median(cell)), int(round(cell.mean()))))

    def test_match(self):
        h = raw_grid(3, 3)
        good = overlay.fnam_bytes(h)
        self.assertEqual(overlay.fnam_match(good, h), (9, 9, 0))
        bad = bytearray(good)
        bad[4] ^= 0x10
        exact, cells, worst = overlay.fnam_match(bytes(bad), h)
        self.assertEqual((exact, cells), (8, 9))
        self.assertEqual(worst, 16)
        self.assertEqual(overlay.fnam_match(good[:16], h), (0, 9, None))   # 8 values, like the first experiments

    def test_written_btd_round_trip(self):
        h = raw_grid(2, 2, seed=3)
        t = btd.Btd(6, -500.0, 1000.0, [1], h, np.zeros_like(h), np.zeros((4, 4, 8), np.uint8))
        back = btd.read(btd.write(t))
        self.assertEqual(overlay.fnam_values(back.heights_raw), overlay.fnam_values(h))

    def test_rejects_partial_cells(self):
        with self.assertRaises(ValueError):
            overlay.fnam_values(np.zeros((128, 100), np.uint16))


class Mask(unittest.TestCase):
    def test_ring(self):
        a = overlay.mask_array(5)
        self.assertEqual(a.shape, (500, 500))
        self.assertEqual(a.dtype, np.uint8)
        self.assertTrue((a[100:400, 100:400] == 0).all())
        self.assertEqual(int((a == 255).sum()), 500 * 500 - 300 * 300)
        self.assertTrue((a[:100] == 255).all() and (a[:, 400:] == 255).all())
        self.assertEqual(overlay.mask_array(29).shape, (2900, 2900))

    def test_needs_an_inside(self):
        with self.assertRaises(ValueError):
            overlay.mask_array(2)

    def test_dds_round_trip_lossless(self):
        a = overlay.mask_array(3)
        dds = overlay.dds_bc4(a)
        info = overlay.dds_info(dds)
        self.assertEqual((info["width"], info["height"], info["mips"], info["format"]), (300, 300, 1, "BC4"))
        self.assertEqual(len(dds), 148 + 75 * 75 * 8)
        self.assertTrue((overlay.bc4_decode(dds) == a).all())
        self.assertEqual(overlay.mask_check(overlay.bc4_decode(dds), 3), (0, 0))

    def test_check_finds_a_wrong_pixel(self):
        a = overlay.mask_array(3)
        a[150, 150] = 255
        self.assertEqual(overlay.mask_check(a, 3), (1, 255))
        self.assertEqual(overlay.mask_check(a[:200], 3), (90000, 255))

    def test_bc4_decoder_palettes(self):
        # 8-value mode (r0 > r1): index 2..7 interpolate; 6-value mode (r0 <= r1): 6 -> 0, 7 -> 255
        def block(r0, r1, idx):
            bits = sum(i << (3 * k) for k, i in enumerate(idx))
            return bytes((r0, r1)) + bits.to_bytes(6, "little")
        idx = [0, 1, 2, 3, 4, 5, 6, 7] * 2
        a = overlay.bc4_decode_blocks(block(210, 70, idx), 4, 4).ravel()
        self.assertEqual(a[:8].tolist(), [210, 70, 190, 170, 150, 130, 110, 90])
        b = overlay.bc4_decode_blocks(block(50, 150, idx), 4, 4).ravel()
        self.assertEqual(b[:8].tolist(), [50, 150, 70, 90, 110, 130, 0, 255])

    def test_legacy_header_info(self):
        hdr = bytearray(128)
        hdr[:4] = b"DDS "
        struct.pack_into("<II", hdr, 12, 8, 4)
        struct.pack_into("<I", hdr, 28, 1)
        hdr[84:88] = b"BC4U"
        info = overlay.dds_info(bytes(hdr) + bytes(16))
        self.assertEqual((info["width"], info["height"], info["format"], info["data_offset"]), (4, 8, "BC4", 128))

    def test_write_mask_builtin(self):
        with tempfile.TemporaryDirectory() as d:
            rep = orc.write_mask(d, "FO4TX_Test", 3, writer="builtin")
            self.assertTrue(os.path.isfile(os.path.join(d, "Data", "textures", "terrain", "overlaymasks", "fo4tx_test.dds")))
            self.assertEqual((rep["width"], rep["pixels_differ"], rep["format"]), (300, 0, "BC4"))


def sub(sig, data):
    return sig + struct.pack("<H", len(data)) + data


def rec(sig, fid, fields, flags=0):
    body = b"".join(fields)
    return sig + struct.pack("<IIIIHH", len(body), flags, fid, 0, 0, 0) + body


def grup(label, items, gtype=0):
    body = b"".join(items)
    return b"GRUP" + struct.pack("<I4siIHH", 24 + len(body), label, gtype, 0, 0, 0) + body


class RawWalk(unittest.TestCase):
    def plugin(self):
        tes4 = rec(b"TES4", 0, [sub(b"HEDR", bytes(12)), sub(b"MAST", b"Starfield.esm\0")])
        wrld = rec(b"WRLD", 0x01000802, [
            sub(b"EDID", b"FO4TX_Test\0"),
            sub(b"BFCB", b"BGSWorldSpaceOverlay_Component\0"), sub(b"SNAM", bytes(4)), sub(b"BNAM", struct.pack("<I", 0x01000801)),
            sub(b"BFCE", b""), sub(b"XLCN", struct.pack("<I", 0x01000803)), sub(b"BNAM", struct.pack("<I", 0x002A3777))])
        anchor = rec(b"REFR", 0x01000800, [sub(b"EDID", b"Anchor\0"), sub(b"NAME", struct.pack("<I", orc.XMARKER)),
                                           sub(b"DATA", struct.pack("<6f", 1, 2, 3, 0, 0, 0))], flags=orc.PERSISTENT)
        cnam = struct.pack("<ddI", 0.2, 1.2, 0x01000802) + struct.pack("<ddI", -0.04, -0.09, 0x02DF8C)
        pndt = rec(b"PNDT", orc.MARS_PNDT, [sub(b"EDID", b"MarsPlanetData\0"), sub(b"CNAM", cnam), sub(b"CNAM", b"\x02")])
        return tes4 + grup(b"WRLD", [wrld, grup(struct.pack("<I", 0x01000802), [anchor], 1)]) + grup(b"PNDT", [pndt])

    def test_walk_and_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.esm")
            with open(p, "wb") as f:
                f.write(self.plugin())
            w = orc.walk_plugin(p)
        self.assertEqual(w["masters"], ["Starfield.esm"])
        sigs = [r["sig"] for r in w["records"]]
        self.assertEqual(sigs, ["WRLD", "REFR", "PNDT"])
        wr, ref, pl = w["records"]
        self.assertEqual(orc.edid(wr), "FO4TX_Test")
        self.assertEqual(orc.overlay_block_ref(wr), 0x01000801)      # the component's BNAM, not the later one
        self.assertEqual(struct.unpack("<I", orc.field(wr, "XLCN"))[0], 0x01000803)
        self.assertTrue(ref["flags"] & orc.PERSISTENT)
        self.assertEqual(orc.pndt_entries(pl), [(0.2, 1.2, 0x01000802), (-0.04, -0.09, 0x02DF8C)])

    def test_anchor_ref_and_paths(self):
        self.assertEqual(orc.anchor_ref(), "02000800")
        self.assertTrue(re.fullmatch(r"[0-9A-Fa-f]{8}", orc.anchor_ref(0xABC, "0F")))
        self.assertEqual(orc.mask_rel("FO4CW_Commonwealth"), "Data/textures/terrain/overlaymasks/fo4cw_commonwealth.dds")


if __name__ == "__main__":
    unittest.main()
