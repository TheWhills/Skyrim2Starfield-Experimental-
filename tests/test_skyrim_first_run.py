"""The first-run diagnostic on a synthetic Skyrim + Starfield install (no game data; texconv patched)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import bsa, textures  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
import test_skyrim_objects as T  # noqa: E402


def misplaced_nif():
    """A rock whose collision box sits 100 m away from its geometry: the survey must flag it."""
    n = F.SseNif()
    root = n.reserve("BSFadeNode")
    sh = n.trishape(b"R", [(0, 0, 0), (100, 0, 0), (0, 100, 50)], [(0, 0)] * 3, [(0, 1, 2)],
                    shader=n.lighting("textures\\landscape\\rocks\\rock01.dds", "textures\\landscape\\rocks\\rock01_n.dds"))
    far = n.transform(n.box((1, 1, 1)), (100.0, 0.0, 0.0))
    n.node(root, b"Bad", [sh], coll=n.collision(root, far))
    return n.bytes()


class FirstRunTests(unittest.TestCase):
    def test_full_run_on_synthetic_installs(self):
        import skyrim_first_run as fr
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(textures, "texconv", lambda *a, **k: None):
            sky = os.path.join(tmp, "Skyrim", "Data")
            F.skyrim_data(sky)
            T.write_esm(os.path.join(sky, "Skyrim.esm"))
            with open(os.path.join(sky, "Update.bsa"), "wb") as f:       # later archive: a broken + a misplaced model
                f.write(bsa.build({"meshes\\clutter\\doesnotexist.nif": b"Gamebryo junk",
                                   "meshes\\landscape\\rocks\\rockcliff01.nif": misplaced_nif()}))
            sf = os.path.join(tmp, "Starfield")
            os.makedirs(os.path.join(sf, "Data"))
            os.makedirs(os.path.join(sf, "Tools"))
            with open(os.path.join(sf, "Data", "Starfield.esm"), "wb") as f:
                f.write(b"TES4")
            box = F.collision_template_nif(os.path.join(tmp, "box.nif"))
            with open(box, "rb") as f:
                F.starfield_meshes_ba2(os.path.join(sf, "Data", "Starfield - Meshes01.ba2"),
                                       {fr.BOX_TEMPLATE_NIF: f.read()})
            F.content_resources(os.path.join(sf, "Tools", "ContentResources.zip"))
            texconv = os.path.join(tmp, "texconv.exe")
            with open(texconv, "wb") as f:
                f.write(b"MZ")
            work = os.path.join(tmp, "work")
            with contextlib.redirect_stdout(io.StringIO()) as log:
                fr.main(["--skyrim-data", sky, "--starfield", sf, "--texconv", texconv, "--work", work,
                         "--around", "0,0", "--radius", "3"])
            with open(os.path.join(work, "report.json"), encoding="utf-8") as f:
                rep = json.load(f)
            with open(os.path.join(work, "report.txt"), encoding="utf-8") as f:
                text = f.read()
            if os.environ.get("SHOW_REPORT"):
                print(text, file=sys.stderr)
        for step in ("setup", "terrain", "archives", "objects", "survey", "sample"):
            self.assertTrue(rep[step]["ok"], (step, rep[step].get("error")))
        self.assertTrue(rep["setup"]["box_template"])
        self.assertEqual(rep["terrain"]["extent"], {"x": [-6, 5], "y": [-4, 4]})
        self.assertEqual(rep["terrain"]["arrival"]["cell"], [0, 0])
        self.assertEqual(rep["objects"]["distinct_models_to_convert"], 5)
        sv = rep["survey"]
        self.assertEqual(sv["models"], 5)
        self.assertEqual(sv["parse_failed"], 1)                     # the junk NIF, grouped with its message
        self.assertEqual(sv["collision_misplaced"], 1)              # the rock whose collision is 100 m away
        self.assertEqual(sv["misplaced_examples"][0]["model"], "meshes\\landscape\\rocks\\rockcliff01.nif")
        self.assertEqual(sv["collision_overlaps_render"], 2)        # tree and house
        self.assertIn("bhkConvexTransformShape", sv["havok_and_geometry_block_types"])
        self.assertEqual(list(sv["nif_bs_versions"]), ["100"])
        sm = rep["sample"]
        self.assertEqual(sm["converted"] + sm["failed"], len(sm["results"]))
        self.assertGreaterEqual(sm["converted"], 3)
        self.assertIn("survey: 5 models", text)
        self.assertIn("MISPLACED 1", text)
        self.assertIn("Paste", log.getvalue())

    def test_refuses_work_folder_inside_the_repo(self):
        import skyrim_first_run as fr
        with self.assertRaises(SystemExit):
            fr.main(["--skyrim-data", "x", "--starfield", "y", "--texconv", "z", "--work", os.path.join(ROOT, "work")])


if __name__ == "__main__":
    unittest.main()
