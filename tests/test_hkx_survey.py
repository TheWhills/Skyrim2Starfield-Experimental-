"""scripts/armor/hkx_survey.py --extract on a synthetic Skyrim Data folder of loose files (no game data)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import hkx_survey as H  # noqa: E402


class ExtractTests(unittest.TestCase):
    def test_extract_copies_matching_clips(self):
        with tempfile.TemporaryDirectory() as tmp:
            anim = os.path.join(tmp, "Data", "meshes", "actors", "character", "animations")
            os.makedirs(anim)
            for name, data in (("1hm_attackleft.hkx", b"clip-a"), ("2hm_attackleft.hkx", b"clip-b")):
                with open(os.path.join(anim, name), "wb") as fh:
                    fh.write(data)
            out = os.path.join(tmp, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(H.main(["--skyrim-data", os.path.join(tmp, "Data"), "--out", out,
                                         "--filter", "animations/1hm_", "--extract"]), 0)
            ex = os.path.join(out, "extract", "meshes", "actors", "character", "animations")
            self.assertEqual(os.listdir(ex), ["1hm_attackleft.hkx"])
            with open(os.path.join(ex, "1hm_attackleft.hkx"), "rb") as fh:
                self.assertEqual(fh.read(), b"clip-a")
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    H.main(["--skyrim-data", os.path.join(tmp, "Data"), "--out", out, "--extract"])


if __name__ == "__main__":
    unittest.main()
