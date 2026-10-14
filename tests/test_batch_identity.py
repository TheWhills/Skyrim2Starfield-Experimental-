"""Persistent batch names must bind to source paths, not conversion order."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
spec = importlib.util.spec_from_file_location("convert_batch", root / "scripts" / "convert_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class BatchIdentityTests(unittest.TestCase):
    def test_case_aliases_cannot_silently_overwrite_reserved_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "editorids.json").write_text(json.dumps({
                "Meshes\\Chair.nif": "Original", "meshes/chair.nif": "Replacement"}))
            with self.assertRaisesRegex(ValueError, "conflicting"):
                batch.load_editor_ids(tmp)

    def test_invalid_persistent_map_is_rejected(self):
        for mapping in [[], {"a.nif": None}, {"a.nif": ""}]:
            with tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "editorids.json").write_text(json.dumps(mapping))
                with self.assertRaises(ValueError):
                    batch.load_editor_ids(tmp)

    def test_batch_failure_does_not_reassign_another_models_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "staging"
            collision = Path(tmp) / "collision.nif"
            collision.write_bytes(b"synthetic")
            a, b = "meshes/folder_a/chair.nif", "meshes/folder_b/chair.nif"
            src = SimpleNamespace(mesh_names=lambda pattern: [a, b])
            converter = SimpleNamespace(stats={}, material_errors={})

            def run(failed):
                def convert(name):
                    if name == failed:
                        return {"ok": False, "reason": "injected failure"}
                    return {"ok": True, "out_name": name[:-4], "shapes": 1, "fallback_materials": 0}
                converter.convert_nif = Mock(side_effect=convert)
                argv = ["convert_batch.py", "--fo4-data", "unused", "--staging", str(staging),
                        "--content-resources", "unused", "--texconv", "unused",
                        "--collision-template", str(collision)]
                with patch.object(sys, "argv", argv), \
                        patch.object(batch.pipeline, "Fo4Archives", return_value=src), \
                        patch.object(batch.pipeline, "Converter", return_value=converter), \
                        patch.object(batch.convert_static, "collision_template_from_nif", return_value=b"template"), \
                        patch("builtins.print"):
                    batch.main()
                manifest = json.loads((staging / "manifest.json").read_text())
                return {i["source"]: i["editor_id"] for i in manifest["items"]}

            original = run(None)
            self.assertNotEqual(original[a], original[b])
            self.assertEqual(run(a), {b: original[b]})
            self.assertEqual(run(None), original)

    def test_same_basename_survives_removal_and_restore(self):
        ids = {}
        a, b = "meshes/folder_a/chair.nif", "meshes/folder_b/chair.nif"
        first_a, first_b = batch.editor_id(a, ids), batch.editor_id(b, ids)
        self.assertNotEqual(first_a.lower(), first_b.lower())
        with tempfile.TemporaryDirectory() as tmp:
            batch.write_json_atomic(str(Path(tmp) / "editorids.json"), ids)
            loaded = batch.load_editor_ids(tmp)
            self.assertEqual(batch.editor_id(b, loaded), first_b)
            batch.editor_id("meshes/folder_c/chair.nif", loaded)
            self.assertEqual(batch.editor_id(a, loaded), first_a)
            self.assertEqual(batch.editor_id(b, loaded), first_b)

    def test_adopts_existing_manifest_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = "Meshes\\Folder\\Chair.nif"
            Path(tmp, "manifest.json").write_text(json.dumps({"items": [
                {"source": source, "editor_id": "FO4Port_Chair_2"}]}))
            ids = batch.load_editor_ids(tmp)
            self.assertEqual(batch.editor_id(source.lower().replace("\\", "/"), ids), "FO4Port_Chair_2")

    def test_case_and_separator_variants_reuse_identity(self):
        ids = {}
        self.assertEqual(batch.editor_id("Meshes\\A\\Chair.NIF", ids),
                         batch.editor_id("meshes/a/chair.nif", ids))
        self.assertEqual(len(ids), 1)

    def test_rejects_duplicate_reserved_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "editorids.json").write_text(json.dumps({"a.nif": "Same", "b.nif": "same"}))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                batch.load_editor_ids(tmp)

    def test_rejects_conflicting_manifest_instead_of_renaming(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "editorids.json").write_text(json.dumps({"a.nif": "Original"}))
            Path(tmp, "manifest.json").write_text(json.dumps({"items": [
                {"source": "a.nif", "editor_id": "Replacement"}]}))
            with self.assertRaisesRegex(ValueError, "conflicting"):
                batch.load_editor_ids(tmp)
