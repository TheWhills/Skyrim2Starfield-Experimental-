"""scripts/terrain/refresh_models.py on a fake work / staging pair."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
import refresh_models as R  # noqa: E402


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


class RefreshTests(unittest.TestCase):
    def test_replaces_only_staged_files(self):
        with tempfile.TemporaryDirectory() as d:
            w, s = os.path.join(d, "work"), os.path.join(d, "stage")
            put(os.path.join(w, "convert", "meshes", "a", "road.nif"), b"native")
            put(os.path.join(w, "convert", "meshes", "a", "same.nif"), b"x")
            put(os.path.join(w, "convert", "meshes", "a", "new.nif"), b"n")
            put(os.path.join(s, "Data", "meshes", "a", "road.nif"), b"boxes")
            put(os.path.join(s, "Data", "meshes", "a", "same.nif"), b"x")
            with open(os.path.join(w, "convert", "manifest.json"), "w") as fh:
                json.dump({"items": [{"collision_report": {"source": "skyrim-native"}}]}, fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                R.main(["--work", w, "--staging", s, "--dry-run"])
                self.assertEqual(open(os.path.join(s, "Data", "meshes", "a", "road.nif"), "rb").read(), b"boxes")
                R.main(["--work", w, "--staging", s])
            self.assertEqual(open(os.path.join(s, "Data", "meshes", "a", "road.nif"), "rb").read(), b"native")
            self.assertFalse(os.path.exists(os.path.join(s, "Data", "meshes", "a", "new.nif")))
            self.assertIn("replaced 1 files; unchanged 1; not in the staging 1", out.getvalue())
            self.assertIn("skyrim-native", out.getvalue())


if __name__ == "__main__":
    unittest.main()
