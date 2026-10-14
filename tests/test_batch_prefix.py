"""convert_batch --prefix: the output folder name reaches the converter; the default keeps old checkpoints valid."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
spec = importlib.util.spec_from_file_location("convert_batch_prefix", root / "scripts" / "convert_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class BatchPrefixTests(unittest.TestCase):
    def run_batch(self, tmp, extra):
        staging = Path(tmp) / "staging"
        collision = Path(tmp) / "collision.nif"
        collision.write_bytes(b"synthetic")
        cell = Path(tmp) / "cell.json"
        cell.write_text(json.dumps({"refs": [{"model": "a\\chair.nif", "type": "Static"}]}))
        seen = {}

        def converter(*args, **kw):
            seen.update(kw)
            prefix = kw.get("prefix", "fo4port")
            return SimpleNamespace(stats={}, material_errors={}, convert_nif=lambda name: {
                "ok": True, "out_name": f"{prefix}/a/chair", "shapes": 1, "fallback_materials": 0})
        argv = ["convert_batch.py", "--fo4-data", "unused", "--staging", str(staging), "--content-resources", "unused",
                "--texconv", "unused", "--collision-template", str(collision), "--cell-json", str(cell)] + extra
        with patch.object(sys, "argv", argv), \
                patch.object(batch.pipeline, "Fo4Archives", return_value=SimpleNamespace()), \
                patch.object(batch.pipeline, "Converter", side_effect=converter), \
                patch.object(batch.convert_static, "collision_template_from_nif", return_value=b"template"), \
                patch("builtins.print"):
            batch.main()
        return seen, json.loads((staging / "manifest.json").read_text())

    def test_prefix_reaches_the_converter_and_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen, manifest = self.run_batch(tmp, ["--prefix", "fo4cw"])
        self.assertEqual(seen["prefix"], "fo4cw")
        self.assertEqual(manifest["items"][0]["model"], "fo4cw\\a\\chair.nif")

    def test_default_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen, manifest = self.run_batch(tmp, [])
        self.assertEqual(seen["prefix"], "fo4port")
        self.assertEqual(manifest["items"][0]["model"], "fo4port\\a\\chair.nif")

    def test_bad_prefix_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                self.run_batch(tmp, ["--prefix", "../up"])

    def test_signature_only_names_a_non_default_prefix(self):
        a = SimpleNamespace(fo4_data="", starfield_data="", texconv="t", content_resources="c", collision_template="x",
                            prefix="fo4port")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(batch.checkpoints, "digest", return_value="d"), \
                patch.object(batch.checkpoints, "archive_identity", return_value={}):
            a.fo4_data = tmp
            self.assertNotIn("prefix", batch.checkpoint_signature(a))
            a.prefix = "fo4cw"
            self.assertEqual(batch.checkpoint_signature(a)["prefix"], "fo4cw")


if __name__ == "__main__":
    unittest.main()
