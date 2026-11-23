"""scripts/tools/key_names.py on a synthetic blob: a UTF-16 name<TAB>hex table is found at either byte alignment."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tools"))
import key_names as K  # noqa: E402


class KeyNamesTests(unittest.TestCase):
    def test_table(self):
        table = ("Escape\t1b\n" + "".join(f"K{i}\t{i:x}\n" for i in range(30)) + "Left Alt\ta4\n").encode("utf-16-le")
        for pad in (b"\x00junk", b"junk"):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "x.exe")
                with open(p, "wb") as fh:
                    fh.write(pad + table + b"tail")
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(K.main(["--exe", p]), 0)
                self.assertIn("'Left Alt'\t0xA4", out.getvalue())
        self.assertEqual(K.tables("nothing here"), [])
        rows = K.tables("Esc\t0x1B\r\n" + "".join(f"K{i}\t0x{i:X}\r\n" for i in range(30)) + "Left Alt\t0xA4\r\n")
        self.assertIn(("Left Alt", 0xA4), rows[0])                  # 0x prefixes, CRLF


if __name__ == "__main__":
    unittest.main()
