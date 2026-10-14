"""Per-model checkpoints with content-verified generated dependencies.

Archive identity uses resolved path, size and nanosecond modification time.
Archives must be immutable during a run; replace/touch edited archives before
resuming. Small tools/templates and converter sources use content hashes.
"""
import hashlib
import json
import os
import struct
from pathlib import Path
import tempfile

from . import nif, sfnif


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_identity(path):
    path = Path(path).resolve()
    stat = path.stat()
    return [str(path), stat.st_size, stat.st_mtime_ns]


def local_path(staging, relative):
    root = Path(staging).resolve()
    path = (root / relative.replace("\\", "/")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("checkpoint output escapes staging")
    return path


def output_inventory(staging, result, prefix="fo4port"):
    """Follow generated NIF -> mesh/material -> texture dependencies."""
    paths = {"meshes/" + result["out_name"] + ".nif"}
    model = nif.parse(local_path(staging, next(iter(paths))).read_bytes())
    for i, block in enumerate(model.blocks):
        if model.type_of(i) == "BSGeometry":
            for mesh in sfnif.parse_bsgeometry(block).meshes:
                if mesh is not None:
                    paths.add("geometries/" + mesh.path.decode("latin-1").replace("\\", "/") + ".mesh")
    materials = set()
    for value in model.strings:
        name = value.decode("latin-1").replace("\\", "/")
        if name.lower().startswith(f"materials/{prefix}/") and name.lower().endswith(".mat"):
            materials.add(name)
    paths.update(materials)

    def textures(value):
        if isinstance(value, dict):
            for child in value.values():
                textures(child)
        elif isinstance(value, list):
            for child in value:
                textures(child)
        elif isinstance(value, str):
            name = value.replace("\\", "/")
            if name.lower().startswith("data/"):
                name = name[5:]
            if name.lower().startswith(f"textures/{prefix}/") and name.lower().endswith(".dds"):
                paths.add(name)

    for name in materials:
        with local_path(staging, name).open(encoding="utf-8-sig") as f:
            textures(json.load(f))
    return {name: digest(local_path(staging, name)) for name in sorted(paths)}


class Checkpoints:
    def __init__(self, staging, signature):
        self.staging = Path(staging)
        self.signature = signature
        self.directory = self.staging / ".checkpoints"
        self.expected = {}

    def path(self, source):
        key = source.replace("\\", "/").lower()
        return self.directory / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def load(self, source):
        try:
            with self.path(source).open(encoding="utf-8") as f:
                cached = json.load(f)
            if not isinstance(cached, dict) or not isinstance(cached.get("outputs"), dict) or not isinstance(cached.get("result"), dict):
                return None
            if cached["signature"] != self.signature or not cached["outputs"]:
                return None
            result = cached["result"]
            if not isinstance(result.get("out_name"), str) or not result["out_name"]:
                return None
            if any(type(result.get(field)) is not int or result[field] < 0
                   for field in ("shapes", "fallback_materials")):
                return None
            if output_inventory(self.staging, result) != cached["outputs"]:
                return None
            if result.get("ok") is not True:
                return None
            self.expected[source] = cached["outputs"]
            return cached["result"]
        except (OSError, ValueError, KeyError, TypeError, struct.error):
            return None

    def save(self, source, result):
        if result.get("ok") is not True or result.get("fallback_materials") or result.get("door_error"):
            self.path(source).unlink(missing_ok=True)
            return False  # Retry degraded/failing conversions rather than freezing a placeholder.
        try:
            outputs = output_inventory(self.staging, result)
        except (OSError, ValueError, KeyError, TypeError, struct.error):
            # The batch runner may continue after checkpoint I/O errors. Keep an
            # explicit failed expectation so it cannot publish an unverified build.
            self.expected[source] = None
            raise
        self.expected[source] = outputs
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix=".pending-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"signature": self.signature, "result": result, "outputs": outputs}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.path(source))
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
        return True

    def verify_batch(self):
        """Recheck expectations after all writes, including dependencies shared by models."""
        actual, errors = {}, []
        for source, outputs in self.expected.items():
            if not isinstance(outputs, dict):
                errors.append({"source": source, "output": "<dependency inventory unavailable>"})
                continue
            for relative, expected in outputs.items():
                path = local_path(self.staging, relative)
                if path not in actual:
                    try:
                        actual[path] = digest(path)
                    except OSError:
                        actual[path] = None
                if actual[path] != expected:
                    errors.append({"source": source, "output": relative})
        return errors
