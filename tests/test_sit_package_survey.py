"""scripts/npc/sit_package_survey.py: Sit packages' inputs, shown per index (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "src"))
import sit_package_survey as S  # noqa: E402
import make_schedule as M  # noqa: E402


class SitSurveyTest(unittest.TestCase):
    def test_show(self):
        self.assertEqual(S.show({"is_form": True, "value": 0x20B7B4}), "form 0020B7B4")
        self.assertEqual(S.show(2.5), "2.5")
        self.assertEqual(S.show(True), "True")

    def test_rows(self):
        pack = {"edid": "UC07_Gel_Sit_Weld", "template": 7,
                "inputs": [{"type": "SingleRef", "value": {"is_form": True, "value": 0x20B7B4}},
                           {"type": "Float", "value": 0.0}],
                "input_names": [{"index": 0, "name": None}, {"index": 1, "name": None}]}
        other = dict(pack, edid="X", template=8)
        rs = S.rows({1: pack, 2: other}, 7, {0: "Target", 1: "Radius"}, M.value_indexes)
        self.assertEqual(rs, [("UC07_Gel_Sit_Weld", [(0, "Target", "SingleRef", "form 0020B7B4"),
                                                     (1, "Radius", "Float", "0")])])

    def test_form_uses_and_holders(self):
        rs = [("PkgA", [(24, "Restrict Sandbox Targets", "TargetSelector", "form 0018F691 (Keyword)"),
                        (2, "Location", "Location", "form 00000000 (Near linked reference)")]),
              ("PkgB", [(24, "Restrict Sandbox Targets", "TargetSelector", "form 0018F691 (Keyword)")])]
        self.assertEqual(S.form_uses(rs), {(24, "Restrict Sandbox Targets", 0x18F691): ["PkgA", "PkgB"]})
        import struct
        objs = [("FURN", "Bench", struct.pack("<2I", 5, 0x18F691)), ("IDLM", "Lean", struct.pack("<I", 7))]
        self.assertEqual(S.keywords_of(struct.pack("<2I", 5, 9)), [5, 9])
        self.assertEqual(S.holders(objs, 0x18F691), [("FURN", "Bench")])


if __name__ == "__main__":
    unittest.main()
