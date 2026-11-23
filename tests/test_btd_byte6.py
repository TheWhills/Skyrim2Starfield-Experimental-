"""scripts/terrain/btd_byte6.py (2026-11-22): write quadrant byte 6 like vanilla terrain and restore it."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import btd, sfplugin  # noqa: E402
import btd_byte6 as B  # noqa: E402


def esm(path):
    h = struct.pack("<4sIII", b"LTEX", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
    recs = [(b"LTEX", h, [(b"EDID", b"LDefault006Base\0")], 0x50),
            (b"LTEX", h, [(b"EDID", b"LDefault004FlatOut\0")], 0x52),
            (b"LTEX", h, [(b"EDID", b"LGrassSF\0")], 0x60)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))
    return path


def terrain():
    q = np.zeros((2, 2, 8), np.uint8)
    q[0, 0, :2] = (1, 2)
    q[1, 1, 0] = 2                   # quadrant (1, 0) and (0, 1) hold nothing
    w = (np.arange(128 * 128, dtype=np.uint32) % 4096).astype(np.uint16).reshape(128, 128)
    h = (np.arange(128 * 128, dtype=np.uint32) % 60000).astype(np.uint16).reshape(128, 128)
    return btd.Btd(6, 0.0, 10.0, [0x100, 0x200], h, w, q)


class Byte6Test(unittest.TestCase):
    def test_with_byte6(self):
        t = terrain()
        n = B.with_byte6(t, 0x52)
        self.assertEqual(n.ltex, [0x100, 0x200, 0x52])                    # appended: old indices unchanged
        self.assertEqual(n.quad_map[:, :, 6].tolist(), [[3, 0], [0, 3]])
        self.assertTrue(np.array_equal(n.quad_map[:, :, :6], t.quad_map[:, :, :6]))
        self.assertEqual(B.with_byte6(t, 0x200).quad_map[0, 0, 6], 2)      # already in the table

    def test_set_and_restore(self):
        with tempfile.TemporaryDirectory() as st:
            os.makedirs(os.path.join(st, "Data", "Terrain"))
            p = os.path.join(st, "Data", "Terrain", "w.btd")
            raw = btd.write(terrain())
            with open(p, "wb") as fh:
                fh.write(raw)
            with open(os.path.join(st, "overlays_params.json"), "w") as fh:
                json.dump({"overlays": [{"btd_file": "Data/Terrain/w.btd", "btd_copies": ["Data/Terrain/missing.btd"]}]}, fh)
            e = esm(os.path.join(st, "Starfield.esm"))
            with contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertEqual(B.main(["list", "--sf-esm", e]), 0)
                self.assertEqual(B.main(["set", "--staging", st, "--sf-esm", e, "--mask", "flatout"]), 0)
                B.main(["set", "--staging", st, "--sf-esm", e, "--mask", "Base"])   # from the original again
            self.assertIn("LDefault004FlatOut", log.getvalue())
            with open(p, "rb") as fh:
                t = btd.read(fh.read())
            self.assertEqual(t.ltex, [0x100, 0x200, 0x50])
            self.assertEqual(int(t.quad_map[0, 0, 6]), 3)
            with self.assertRaises(SystemExit):
                B.main(["set", "--staging", st, "--sf-esm", e, "--mask", "LDefault"])   # several match
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(B.main(["restore", "--staging", st]), 0)
            with open(p, "rb") as fh:
                self.assertEqual(fh.read(), raw)
            self.assertFalse(os.path.exists(os.path.join(st, B.BACKUP)))
            # 2026-11-23: set after a terrain refresh rewrote the file keeps the refresh (not the first backup)
            with contextlib.redirect_stdout(io.StringIO()):
                B.main(["set", "--staging", st, "--sf-esm", e, "--mask", "flatout"])
            t0 = terrain()
            refreshed = btd.Btd(t0.version, t0.hmin, t0.hmax, t0.ltex, t0.heights_raw, t0.weights ^ 7, t0.quad_map)
            with open(p, "wb") as fh:
                fh.write(btd.write(refreshed))
            with contextlib.redirect_stdout(io.StringIO()):
                B.main(["set", "--staging", st, "--sf-esm", e, "--mask", "flatout"])
            with open(p, "rb") as fh:
                t = btd.read(fh.read())
            self.assertTrue(np.array_equal(t.weights, refreshed.weights))
            self.assertEqual(int(t.quad_map[0, 0, 6]), 3)


if __name__ == "__main__":
    unittest.main()
