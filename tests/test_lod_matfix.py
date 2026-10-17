import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import lodmatfix as lm  # noqa: E402

BLACK = "Data\\textures\\skyrim\\_nonmetal_metal.dds"


def mat():
    return {"Objects": [
        {"ID": "res:1", "Components": [{"Type": "BSComponentDB::CTName", "Data": {"Name": "x"}, "Index": 0}]},
        {"Components": [
            {"Data": {"FileName": "Data\\textures\\a_color.dds"}, "Index": 0, "Type": "BSMaterial::MRTextureFile"},
            {"Data": {"FileName": "Data\\textures\\a_rough.dds"}, "Index": 3, "Type": "BSMaterial::MRTextureFile"},
            {"Data": {"Color": {"Data": {"Value": {"Data": {"x": "0"}}}}}, "Index": 4,
             "Type": "BSMaterial::TextureReplacement"}]}],
        "Summary": {"Layer1": {"Textures": {"Metalness": {"Replacement": {"x": 0}, "UseReplacement": True}}}}}


class MetalFix(unittest.TestCase):
    def test_patch_replaces_constant_with_black_texture(self):
        m = mat()
        self.assertTrue(lm.patch(m, BLACK))
        comps = m["Objects"][1]["Components"]
        slot4 = [c for c in comps if c["Index"] == 4]
        self.assertEqual(slot4, [{"Data": {"FileName": BLACK}, "Index": 4, "Type": "BSMaterial::MRTextureFile",
                                  "Version": 1}])
        self.assertEqual(len(comps), 3)                                   # albedo, rough, metal
        self.assertEqual(m["Summary"]["Layer1"]["Textures"]["Metalness"], {"File": BLACK, "UseReplacement": False})
        self.assertFalse(lm.patch(m, BLACK))                               # rerun: nothing to do

    def test_apply_replaces_hard_links_not_originals(self):
        with tempfile.TemporaryDirectory() as d:
            work = os.path.join(d, "work.mat")
            json.dump(mat(), open(work, "w"))
            data = os.path.join(d, "Data")
            os.makedirs(os.path.join(data, "materials", "skyrim"))
            staged = os.path.join(data, "materials", "skyrim", "a.mat")
            os.link(work, staged)
            with mock.patch.object(lm, "write_black", return_value=BLACK):
                st = lm.apply(data, "texconv.exe")
            self.assertEqual(st, {"materials": 1, "patched": 1, "failed": 0})
            self.assertIn("UseReplacement", json.load(open(work))["Summary"]["Layer1"]["Textures"]["Metalness"])
            self.assertTrue(json.load(open(work))["Summary"]["Layer1"]["Textures"]["Metalness"]["UseReplacement"])
            self.assertFalse(json.load(open(staged))["Summary"]["Layer1"]["Textures"]["Metalness"]["UseReplacement"])


    def test_standalone_only_plain_object_materials(self):
        m = mat()
        m["Summary"]["Layer1"].update({"Parent": "Data\\MATERIALS\\Common\\Plastic\\PlasticPlainSmooth01.mat",
                                       "Tint": {"x": 1.0, "y": 1.0, "z": 1.0, "w": 0.0}})
        m["Summary"]["Layer1"]["Textures"].update({"Albedo": {"File": "Data\\textures\\a_color.dds"},
                                                   "Roughness": {"File": "Data\\textures\\a_rough.dds"}})
        new = lm.standalone(m)
        text = json.dumps(new)
        self.assertNotIn("PlasticPlainSmooth01", text)
        self.assertIn("Layered\\\\Root", text)
        self.assertIn("a_color.dds", text)
        ground = json.loads(json.dumps(m))
        ground["Summary"]["Layer1"]["Parent"] = "Data\\Materials\\Terrain\\DirtFootprints01.mat"
        self.assertIsNone(lm.standalone(ground))
        cut = json.loads(json.dumps(m))
        cut["Objects"][1]["Components"].append({"Data": {"FileName": "x.dds"}, "Index": 2,
                                               "Type": "BSMaterial::MRTextureFile"})
        self.assertIsNone(lm.standalone(cut))


if __name__ == "__main__":
    unittest.main()
