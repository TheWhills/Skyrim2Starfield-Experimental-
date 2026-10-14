"""The material oracle checks definitions, not references to shared parents."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("material_ids", Path(__file__).resolve().parents[1]
                                           / "scripts" / "oracles" / "material_ids.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


class MaterialIdOracleTests(unittest.TestCase):
    def test_shared_parents_are_allowed_but_definitions_are_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, identity in [("a", "res:AAAA:1:2"), ("b", "res:BBBB:1:2")]:
                Path(tmp, name + ".mat").write_text(json.dumps({"Objects": [
                    {"ID": identity, "Parent": "res:Shared:1:2"}]}))
            report = oracle.audit_material_ids(tmp)
            self.assertEqual(report["defined_ids"], 2)
            self.assertFalse(report["errors"] or report["duplicates"])

    def test_duplicates_across_files_ignore_hex_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, identity in [("a", "res:AAAA:1:2"), ("b", "res:aaaa:1:2")]:
                Path(tmp, name + ".mat").write_text(json.dumps({"Objects": [{"ID": identity}]}))
            self.assertEqual(len(oracle.audit_material_ids(tmp)["duplicates"]), 1)

    def test_empty_or_malformed_input_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(oracle.audit_material_ids(tmp)["errors"])
            Path(tmp, "broken.mat").write_text("{")
            self.assertTrue(oracle.audit_material_ids(tmp)["errors"])
