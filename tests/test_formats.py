"""Synthetic-fixture tests: every input byte is built here; no game data is needed."""
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import recon  # noqa: E402


def build_ba2_v1_gnrl(files):
    """files: {name: bytes}. Returns the bytes of a Fallout 4 style v1 GNRL archive (zlib)."""
    n = len(files)
    entries_end = 24 + 36 * n
    blobs, entries, off = [], [], entries_end
    for name, data in files.items():
        packed = zlib.compress(data)
        ext = name.rsplit(".", 1)[-1].encode().ljust(4, b"\0")[:4]
        entries.append(struct.pack("<I4sIIQIII", 0, ext, 0, 0x100, off, len(packed), len(data), 0xBAADF00D))
        blobs.append(packed)
        off += len(packed)
    names = b"".join(struct.pack("<H", len(k)) + k.encode() for k in files)
    header = struct.pack("<4sI4sIQ", b"BTDX", 1, b"GNRL", n, off)
    return header + b"".join(entries) + b"".join(blobs) + names


def build_plugin(records):
    """TES4 header + loose records. records: list of (type, [(subsig, data)])."""
    def subs(items):
        return b"".join(sig.encode() + struct.pack("<H", len(d)) + d for sig, d in items)
    hedr = subs([("HEDR", struct.pack("<fII", 1.0, len(records), 0x800))])
    out = b"TES4" + struct.pack("<IIIIHH", len(hedr), 0, 0, 0, 131, 0) + hedr
    for typ, items in records:
        body = subs(items)
        out += typ.encode() + struct.pack("<IIIIHH", len(body), 0, 0x801, 0, 131, 0) + body
    return out


class Ba2Tests(unittest.TestCase):
    def test_roundtrip_names_and_payload(self):
        payload = {"meshes\\a\\chair.nif": b"nif-bytes" * 50, "textures\\a.dds": b"\x01\x02\x03"}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.ba2")
            with open(p, "wb") as f:
                f.write(build_ba2_v1_gnrl(payload))
            ba2 = recon.read_ba2(p)
            self.assertEqual((ba2["version"], ba2["type"], ba2["file_count"]), (1, "GNRL", 2))
            self.assertEqual(ba2["names"], list(payload))
            for i, (name, data) in enumerate(payload.items()):
                self.assertEqual(recon.extract_gnrl(ba2, i), data, name)

    def test_rejects_non_ba2(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.ba2")
            with open(p, "wb") as f:
                f.write(b"NOPE" + b"\0" * 40)
            with self.assertRaises(ValueError):
                recon.read_ba2(p)


class PluginTests(unittest.TestCase):
    def test_scan_counts_and_subrecords(self):
        data = build_plugin([
            ("STAT", [("EDID", b"Chair\0"), ("MODL", b"a.nif\0")]),
            ("STAT", [("EDID", b"Table\0")]),
            ("MISC", [("EDID", b"Junk\0")]),
        ])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.esm")
            with open(p, "wb") as f:
                f.write(data)
            r = recon.scan_plugin(p)
        self.assertEqual(r["header_form_version"], 131)
        self.assertEqual(r["record_counts"], {"STAT": 2, "MISC": 1})
        self.assertEqual(r["subrecord_sigs"]["STAT"], {"EDID": 2, "MODL": 1})

    def test_compare_reports_type_differences(self):
        a = {"record_counts": {"STAT": 1, "LAND": 5}, "subrecord_sigs": {"STAT": {"EDID": 1, "OBND": 1}}}
        b = {"record_counts": {"STAT": 1, "BIOM": 2}, "subrecord_sigs": {"STAT": {"EDID": 1, "MODL": 1}}}
        c = recon.compare_plugins(a, b)
        self.assertEqual(c["fo4_only_record_types"], ["LAND"])
        self.assertEqual(c["sf_only_record_types"], ["BIOM"])
        self.assertAlmostEqual(c["schema_by_type"]["STAT"]["subrecord_overlap"], 0.33, places=2)


class NifHeaderTests(unittest.TestCase):
    def test_parses_bs_version(self):
        # header line, version, endian byte, user version, num blocks, bs version
        body = b"Gamebryo File Format, Version 20.2.0.7\n" + struct.pack("<I", 0x14020007) + b"\x01" + struct.pack("<III", 12, 3, 130)
        info = recon.parse_nif_header(body + b"\0" * 64)
        self.assertEqual((info["user_version"], info["num_blocks"], info["bs_version"]), (12, 3, 130))


if __name__ == "__main__":
    unittest.main()
