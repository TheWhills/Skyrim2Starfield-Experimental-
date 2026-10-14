"""Opt-in writer integration: FO4SF_PLUGIN_WRITER points to a built PluginSpike.dll.

All fixtures and output are synthetic and temporary. No game deployment occurs.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get("FO4SF_PLUGIN_WRITER"), "set FO4SF_PLUGIN_WRITER to built PluginSpike.dll")
class PluginIdentityTests(unittest.TestCase):
    def test_add_remove_reorder_restore_keep_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "empty-data"
            data.mkdir()
            output = root / "output"
            manifest = root / "manifest.json"
            cell = root / "cell.json"
            env = dict(os.environ, STARFIELD_DATA=str(data))
            # Keep this fixture independent of optional game-test environment hooks.
            for key in list(env):
                if key.startswith("FO4PORT_"):
                    del env[key]

            def build(names):
                manifest.write_text(json.dumps({"items": [
                    {"editor_id": "Synthetic_" + name, "model": "synthetic/" + name + ".nif",
                     "source": "meshes/synthetic/" + name + ".nif"} for name in names]}))
                cell.write_text(json.dumps({"cell": "SyntheticRoom", "refs": [
                    {"formkey": f"{ord(name):06X}:Fallout4.esm", "model": "synthetic\\" + name + ".nif",
                     "base_editor_id": "Synthetic_" + name, "type": "Static", "pos": [0, 0, 0],
                     "rot": [0, 0, 0], "scale": 1, "disabled": 0} for name in names]}))
                result = subprocess.run(["dotnet", os.environ["FO4SF_PLUGIN_WRITER"],
                                         str(output), str(manifest), str(cell)], env=env, capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((output / "FO4Port.esm").exists())
                return json.loads((output / "formids.json").read_text())

            first = build(["a", "b"])
            self.assertEqual(len(first), 5)  # two bases, two placed references, one cell
            self.assertEqual(first, build(["b", "a"]))
            added = build(["c", "b", "a"])
            for key, value in first.items():
                self.assertEqual(added[key], value)
            self.assertEqual(len(set(added.values())), len(added))
            self.assertEqual(added, build(["c", "a"]))
            self.assertEqual(added, build(["b", "a", "c"]))
