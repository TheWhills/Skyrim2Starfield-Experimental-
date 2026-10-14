"""Checkpoint inventory failures must block output verification."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fo4sf import checkpoints


class CheckpointInventoryFailureTests(unittest.TestCase):
    def test_missing_success_output_is_reported_by_batch_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = checkpoints.Checkpoints(tmp, {"inputs": "same"})
            result = {"ok": True, "out_name": "fo4port/missing", "shapes": 1,
                      "fallback_materials": 0}

            with self.assertRaises(FileNotFoundError):
                cache.save("meshes/missing.nif", result)

            self.assertEqual(cache.verify_batch(), [{
                "source": "meshes/missing.nif",
                "output": "<dependency inventory unavailable>",
            }])


if __name__ == "__main__":
    unittest.main()
