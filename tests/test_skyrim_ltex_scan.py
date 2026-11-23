"""scripts/terrain/skyrim_ltex_scan.py (2026-11-23): which Skyrim plugins change ground textures' grass lists."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import skyrim_ltex_scan as S  # noqa: E402


def sub(sig, data):
    return sig + struct.pack("<H", len(data)) + data


def rec(sig, fid, data):
    return struct.pack("<4sIII", sig, len(data), 0, fid) + bytes(8) + data


def grup(label, gtype, body):
    return struct.pack("<4sI", b"GRUP", 24 + len(body)) + label + struct.pack("<I", gtype) + bytes(8) + body


def plugin(path, masters, groups):
    tes4 = b"".join(sub(b"MAST", m.encode() + b"\0") + sub(b"DATA", bytes(8)) for m in masters)
    with open(path, "wb") as f:
        f.write(rec(b"TES4", 0, tes4) + b"".join(groups))


class ScanTest(unittest.TestCase):
    def test_override_gives_nograss_texture_grass(self):
        with tempfile.TemporaryDirectory() as d:
            plugin(os.path.join(d, "Skyrim.esm"), [], [
                grup(b"LTEX", 0, rec(b"LTEX", 0x58176, sub(b"EDID", b"LFieldGrass02NoGrass\0"))),
                grup(b"GRAS", 0, rec(b"GRAS", 0x100, sub(b"EDID", b"FieldGrass01\0")))])
            plugin(os.path.join(d, "Landscape.esp"), ["Skyrim.esm"], [
                grup(b"LTEX", 0, rec(b"LTEX", 0x58176, sub(b"EDID", b"LFieldGrass02NoGrass\0")
                                     + sub(b"GNAM", struct.pack("<I", 0x100))
                                     + sub(b"GNAM", struct.pack("<I", 0x01000800)))),
                grup(b"GRAS", 0, rec(b"GRAS", 0x01000800, sub(b"EDID", b"NewGrass\0")))])
            self.assertEqual(S.plugin_order(["Landscape.esp", "Update.esm", "Skyrim.esm", "A.esm"]),
                             ["Skyrim.esm", "Update.esm", "A.esm", "Landscape.esp"])
            scans = [(n, S.scan_plugin(os.path.join(d, n), ["LFieldGrass02NoGrass"], []))
                     for n in ("Skyrim.esm", "Landscape.esp")]
            lines = S.report(scans, active={"landscape.esp"})
            text = "\n".join(lines)
            self.assertIn("Skyrim.esm  [active]: 1 LTEX, 1 GRAS", text)
            self.assertIn("defines LFieldGrass02NoGrass: grass none", text)
            self.assertIn("Landscape.esp  [active]: 1 LTEX, 1 GRAS", text)
            self.assertIn("overrides skyrim.esm's LFieldGrass02NoGrass: grass FieldGrass01, NewGrass", text)

    def test_land_override_for_a_cell(self):
        with tempfile.TemporaryDirectory() as d:
            cell = rec(b"CELL", 0x9000, sub(b"XCLC", struct.pack("<iiI", 4, -12, 0)))
            children = grup(struct.pack("<I", 0x9000), 6,
                            grup(struct.pack("<I", 0x9000), 9, rec(b"LAND", 0x9001, b"")))
            world = (rec(b"WRLD", 0x3C, sub(b"EDID", b"Tamriel\0"))
                     + grup(struct.pack("<I", 0x3C), 1, grup(bytes(4), 4, grup(bytes(4), 5, cell + children))))
            plugin(os.path.join(d, "Fix.esp"), ["Skyrim.esm"], [grup(b"WRLD", 0, world)])
            s = S.scan_plugin(os.path.join(d, "Fix.esp"), [], [(4, -12), (5, -12)])
            self.assertEqual(s["land_cells"], [(4, -12)])
            self.assertIn("LAND for Tamriel cells [(4, -12)]", S.report([("Fix.esp", s)])[0])

    def test_mo2_profile(self):
        with tempfile.TemporaryDirectory() as d:
            prof = os.path.join(d, "profiles", "Default")
            os.makedirs(prof)
            with open(os.path.join(prof, "modlist.txt"), "w", encoding="utf-8") as f:
                f.write("# top = highest priority\n+Grass Fix\n-Off Mod\n+Textures_separator\n+USSEP\n")
            with open(os.path.join(prof, "plugins.txt"), "w", encoding="utf-8") as f:
                f.write("*Unofficial Skyrim Special Edition Patch.esp\n")
            folder, mods, active = S.mo2_profile(d)
            self.assertEqual(os.path.basename(folder), "Default")
            self.assertEqual(mods, ["USSEP", "Grass Fix"])                 # lowest priority first
            self.assertEqual(active, {"unofficial skyrim special edition patch.esp"})

    def test_active_plugins(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "plugins.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("# comment\n*Unofficial Skyrim Special Edition Patch.esp\nOff.esp\n")
            self.assertEqual(S.active_plugins(p), {"unofficial skyrim special edition patch.esp"})
            self.assertIsNone(S.active_plugins(os.path.join(d, "missing.txt")))


if __name__ == "__main__":
    unittest.main()
