"""scripts/npc/energy_survey.py: a package's Energy through its template's input names (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "src"))
import energy_survey as E  # noqa: E402


class EnergySurveyTest(unittest.TestCase):
    def test_energy_of(self):
        tpl = {"input_names": [{"index": 2, "name": "Location"}, {"index": 18, "name": "Energy"}]}
        pack = {"input_names": [{"index": 2, "name": None}, {"index": 18, "name": None}],
                "inputs": [{"type": "Location", "value": {}}, {"type": "Float", "value": 50.0}]}
        self.assertEqual(E.energy_of(pack, tpl), 50.0)
        self.assertIsNone(E.energy_of({"input_names": [], "inputs": []}, tpl))
        self.assertEqual(E.bucket(0.5), "0.5")


if __name__ == "__main__":
    unittest.main()
