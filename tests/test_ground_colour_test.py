"""scripts/terrain/ground_colour_test.py (2026-11-22): paint staged ground colour textures solid and restore them."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import ground_colour_test as G  # noqa: E402


class PaintRestoreTest(unittest.TestCase):
    def test_paint_then_restore(self):
        with tempfile.TemporaryDirectory() as st:
            p = G.colour_path(st, "LRocks01NoRocks")
            self.assertTrue(p.endswith(os.path.join("ground", "lrocks01norocks_color.dds")))
            os.makedirs(os.path.dirname(p))
            with open(p, "wb") as fh:
                fh.write(b"original")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(G.main(["paint", "--staging", st, "--colours", "LRocks01NoRocks=magenta,LMissing=cyan"]), 0)
                with open(p, "rb") as fh:
                    self.assertEqual(fh.read(4), b"DDS ")
                G.main(["paint", "--staging", st, "--colours", "LRocks01NoRocks=cyan"])   # a second paint keeps the real backup
                self.assertEqual(G.main(["restore", "--staging", st]), 0)
            self.assertIn("lmissing: no", out.getvalue())
            with open(p, "rb") as fh:
                self.assertEqual(fh.read(), b"original")
            self.assertFalse(os.path.exists(os.path.join(st, G.BACKUP)))


if __name__ == "__main__":
    unittest.main()
