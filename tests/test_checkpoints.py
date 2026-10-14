"""Resume behavior uses synthetic NIFs and generated file graphs only."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fo4sf import checkpoints, nif, sfnif
spec = importlib.util.spec_from_file_location("resume_batch", ROOT / "scripts" / "convert_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def generated(staging, stem="chair"):
    files = {
        "geometries/test/mesh.mesh": b"synthetic geometry",
        "materials/fo4port/test.mat": json.dumps({"Objects": [], "texture": "Data\\Textures\\fo4port\\color.dds"}).encode(),
        "textures/fo4port/color.dds": b"synthetic texture",
    }
    shape = sfnif.StaticShape(b"Synthetic", b"test\\mesh", 3, 3, "materials\\fo4port\\test.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
    files[f"meshes/fo4port/{stem}.nif"] = nif.serialize(sfnif.build_static_nif(b"Synthetic", [shape]))
    for name, data in files.items():
        path = Path(staging) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {"ok": True, "out_name": "fo4port/" + stem, "fallback_materials": 0, "shapes": 1}, files


class CheckpointTests(unittest.TestCase):
    def test_batch_failed_conversion_invalidates_previously_successful_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            tools = root / "tool.bin"
            tools.write_bytes(b"synthetic tool")
            source = SimpleNamespace(mesh_names=lambda pattern: ["meshes/chair.nif"])
            failed = False
            def convert(name):
                if failed:
                    return {"ok": False, "reason": "injected conversion failure"}
                result, _ = generated(staging, Path(name).stem)
                return result
            converter = SimpleNamespace(convert_nif=convert, stats={}, material_errors={})
            argv = ["convert_batch.py", "--fo4-data", str(root), "--staging", str(staging),
                    "--content-resources", str(tools), "--texconv", str(tools),
                    "--collision-template", str(tools), "--resume"]
            with patch.object(sys, "argv", argv), \
                    patch.object(batch.pipeline, "Fo4Archives", return_value=source), \
                    patch.object(batch.pipeline, "Converter", return_value=converter), \
                    patch.object(batch.convert_static, "collision_template_from_nif", return_value=b"template"), \
                    patch("builtins.print"):
                batch.main()
                checkpoints_before = list((staging / ".checkpoints").glob("*.json"))
                self.assertEqual(len(checkpoints_before), 1)
                model = staging / "meshes/fo4port/chair.nif"
                model.write_bytes(model.read_bytes() + b"modified to force conversion")
                failed = True
                batch.main()
            self.assertFalse(list((staging / ".checkpoints").glob("*.json")))
            manifest = json.loads((staging / "manifest.json").read_text())
            self.assertEqual(manifest["failures"][0]["reason"], "injected conversion failure")

    def test_omitted_dependency_cannot_make_incomplete_inventory_reusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, files = generated(tmp)
            cache = checkpoints.Checkpoints(tmp, {})
            cache.save("chair.nif", result)
            original = json.loads(cache.path("chair.nif").read_text())
            for name in original["outputs"]:
                with self.subTest(output=name):
                    outputs = dict(original["outputs"])
                    del outputs[name]
                    cache.path("chair.nif").write_text(json.dumps({**original, "outputs": outputs}))
                    self.assertIsNone(cache.load("chair.nif"))

    def test_incomplete_result_cannot_resume_into_batch_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = generated(tmp)
            cache = checkpoints.Checkpoints(tmp, {})
            cache.save("chair.nif", result)
            original = json.loads(cache.path("chair.nif").read_text())
            for field in ("out_name", "shapes", "fallback_materials"):
                with self.subTest(field=field):
                    incomplete = dict(result)
                    del incomplete[field]
                    cache.path("chair.nif").write_text(json.dumps({**original, "result": incomplete}))
                    self.assertIsNone(cache.load("chair.nif"))

    def test_degraded_reconversion_invalidates_previous_success_checkpoint(self):
        for failure in ({"ok": False}, {"fallback_materials": 1}, {"door_error": "missing native rig"}):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                result, _ = generated(tmp)
                cache = checkpoints.Checkpoints(tmp, {})
                self.assertTrue(cache.save("chair.nif", result))
                self.assertFalse(cache.save("chair.nif", {**result, **failure}))
                self.assertIsNone(checkpoints.Checkpoints(tmp, {}).load("chair.nif"))

    def test_valid_json_with_wrong_checkpoint_structure_is_a_cache_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = generated(tmp)
            cache = checkpoints.Checkpoints(tmp, {})
            cache.save("chair.nif", result)
            original = json.loads(cache.path("chair.nif").read_text())
            invalid = [[], None, {**original, "outputs": ["meshes/fo4port/chair.nif"]},
                       {**original, "result": []}, {**original, "outputs": "not an inventory"}]
            for value in invalid:
                with self.subTest(value=value):
                    cache.path("chair.nif").write_text(json.dumps(value))
                    self.assertIsNone(cache.load("chair.nif"))

    def test_non_boolean_success_flag_cannot_be_saved_or_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = generated(tmp)
            cache = checkpoints.Checkpoints(tmp, {})
            malformed = {**result, "ok": "false"}
            self.assertFalse(cache.save("chair.nif", malformed))
            self.assertFalse(cache.path("chair.nif").exists())
            self.assertTrue(cache.save("chair.nif", result))
            saved = json.loads(cache.path("chair.nif").read_text())
            saved["result"]["ok"] = "false"
            cache.path("chair.nif").write_text(json.dumps(saved))
            self.assertIsNone(cache.load("chair.nif"))

    def test_batch_conflict_is_marked_incomplete_without_publishing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            template = root / "template.nif"
            template.write_bytes(b"synthetic")
            source = SimpleNamespace(mesh_names=lambda pattern: ["first.nif", "second.nif"])
            def convert(name):
                result, _ = generated(staging, Path(name).stem)
                if name == "second.nif":
                    material = staging / "materials/fo4port/test.mat"
                    content = json.loads(material.read_text())
                    content["changed"] = True
                    material.write_text(json.dumps(content))
                return result
            converter = SimpleNamespace(convert_nif=convert, stats={}, material_errors={})
            argv = ["convert_batch.py", "--fo4-data", str(root), "--staging", str(staging),
                    "--content-resources", str(template), "--texconv", str(template),
                    "--collision-template", str(template), "--resume"]
            with patch.object(sys, "argv", argv), \
                    patch.object(batch.pipeline, "Fo4Archives", return_value=source), \
                    patch.object(batch.pipeline, "Converter", return_value=converter), \
                    patch.object(batch.convert_static, "collision_template_from_nif", return_value=b"template"), \
                    patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, "not deployable"):
                    batch.main()
            state = json.loads((staging / "build-state.json").read_text())
            self.assertFalse(state["complete"])
            self.assertEqual(state["status"], "dependency_conflict")
            self.assertFalse((staging / "manifest.json").exists())

    def test_later_shared_material_overwrite_invalidates_completed_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, _ = generated(tmp, "first")
            cache = checkpoints.Checkpoints(tmp, {})
            cache.save("first.nif", first)
            self.assertEqual(cache.load("first.nif"), first)
            second, _ = generated(tmp, "second")
            material = Path(tmp) / "materials/fo4port/test.mat"
            content = json.loads(material.read_text())
            content["changed"] = True
            material.write_text(json.dumps(content))
            cache.save("second.nif", second)
            errors = cache.verify_batch()
            self.assertEqual(errors, [{"source": "first.nif", "output": "materials/fo4port/test.mat"}])

    def test_each_missing_or_changed_dependency_invalidates_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, files = generated(tmp)
            cache = checkpoints.Checkpoints(tmp, {"inputs": "same"})
            self.assertTrue(cache.save("meshes/chair.nif", result))
            self.assertEqual(cache.load("Meshes\\Chair.NIF"), result)
            for name, original in files.items():
                path = Path(tmp) / name
                stat = path.stat()
                path.write_bytes(b"X" * len(original))
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                self.assertIsNone(cache.load("meshes/chair.nif"), name)
                path.write_bytes(original)
                path.unlink()
                self.assertIsNone(cache.load("meshes/chair.nif"), name)
                path.write_bytes(original)

    def test_changed_inputs_or_degraded_result_cannot_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = generated(tmp)
            cache = checkpoints.Checkpoints(tmp, {"input": 1})
            cache.save("chair.nif", result)
            self.assertIsNone(checkpoints.Checkpoints(tmp, {"input": 2}).load("chair.nif"))
            self.assertFalse(cache.save("bad.nif", {**result, "fallback_materials": 1}))
            self.assertIsNone(cache.load("bad.nif"))

    def test_corrupt_checkpoint_and_escape_are_cache_misses(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = generated(tmp)
            cache = checkpoints.Checkpoints(tmp, {})
            cache.save("chair.nif", result)
            cache.path("chair.nif").write_text("{")
            self.assertIsNone(cache.load("chair.nif"))
            with self.assertRaises(ValueError):
                checkpoints.local_path(tmp, "../outside.dds")

    def test_interrupted_batch_reuses_first_model_and_preserves_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            collision = root / "template.nif"
            collision.write_bytes(b"synthetic")
            names = ["meshes/a.nif", "meshes/b.nif"]
            source = SimpleNamespace(mesh_names=lambda pattern: names)
            calls = []
            interrupted = True

            def convert(name):
                calls.append(name)
                if interrupted and name == names[1]:
                    raise KeyboardInterrupt("simulated interrupted build")
                result, _ = generated(staging, Path(name).stem)
                return result

            converter = SimpleNamespace(convert_nif=convert, stats={}, material_errors={})
            argv = ["convert_batch.py", "--fo4-data", str(root), "--staging", str(staging),
                    "--content-resources", str(collision), "--texconv", str(collision),
                    "--collision-template", str(collision), "--resume"]
            with patch.object(sys, "argv", argv), \
                    patch.object(batch.pipeline, "Fo4Archives", return_value=source), \
                    patch.object(batch.pipeline, "Converter", return_value=converter), \
                    patch.object(batch.convert_static, "collision_template_from_nif", return_value=b"template"), \
                    patch("builtins.print"):
                with self.assertRaises(KeyboardInterrupt):
                    batch.main()
                self.assertFalse(json.loads((staging / "build-state.json").read_text())["complete"])
                ids = json.loads((staging / "editorids.json").read_text())
                interrupted = False
                calls.clear()
                batch.main()
                self.assertEqual(calls, [names[1]])
                manifest = json.loads((staging / "manifest.json").read_text())
                self.assertEqual(manifest["stats"]["reused"], 1)
                self.assertTrue(json.loads((staging / "build-state.json").read_text())["complete"])
                self.assertEqual(manifest["items"][0]["editor_id"], ids[names[0]])
                calls.clear()
                with patch.object(batch.pipeline, "Converter", side_effect=AssertionError("unneeded converter initialized")):
                    batch.main()
                self.assertEqual(calls, [])
