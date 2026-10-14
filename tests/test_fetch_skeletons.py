"""scripts/armor/fetch_skeletons.py on synthetic Skyrim BSAs and Starfield BA2s (no game data)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import bsa, nif, sfnif  # noqa: E402
import fetch_skeletons as fs  # noqa: E402
import skyrim_fixtures as F  # noqa: E402

MESH_PATH = "0123456789abcdef0123\\fedcba9876543210fedc"


def starfield_body_nif():
    """A Starfield NIF whose BSGeometry references an external .mesh (as vanilla bodies do)."""
    shape = sfnif.StaticShape(b"Body", MESH_PATH.encode(), 3, 3, "materials\\body.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
    return nif.serialize(sfnif.build_static_nif(b"Body", [shape]))


class FetchSkeletonsTests(unittest.TestCase):
    def test_collects_skyrim_and_starfield_files_into_one_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            sky = os.path.join(tmp, "Skyrim", "Data")
            sf = os.path.join(tmp, "Starfield", "Data")
            os.makedirs(sky)
            os.makedirs(sf)
            with open(os.path.join(sky, "Skyrim - Meshes0.bsa"), "wb") as f:
                f.write(bsa.build({
                    "meshes\\actors\\character\\character assets\\skeleton.nif": b"sk-skel",
                    "meshes\\actors\\character\\character assets\\malebody_0.nif": b"sk-body0",
                    "meshes\\actors\\character\\character assets female\\skeleton_female.nif": b"sk-fskel",
                    "meshes\\actors\\character\\character assets\\1stpersonmalebody_0.nif": b"sk-1st",
                    "meshes\\actors\\character\\character assets\\dummy.nif": b"other",
                    "meshes\\clutter\\bucket01.nif": b"bucket"}))
            loose = os.path.join(sky, "meshes", "actors", "character", "character assets")
            os.makedirs(loose)
            with open(os.path.join(loose, "malebody_0.nif"), "wb") as f:      # loose file wins, as in game
                f.write(b"sk-body0-loose")
            body = starfield_body_nif()
            F.starfield_meshes_ba2(os.path.join(sf, "Starfield - Meshes01.ba2"), {
                "meshes\\actors\\human\\characterassets\\skeleton.nif": b"sf-skel",
                "meshes\\actors\\human\\characterassets\\naked_m.nif": body,
                "meshes\\clothes\\outfit_nightwear_01\\outfit_nightwear_upperbody_01_m.nif": b"sf-nightwear",
                "meshes\\clothes\\outfit_ucpolice\\helmet.nif": b"not wanted"})
            F.starfield_meshes_ba2(os.path.join(sf, "Starfield - Meshes02.ba2"), {
                "geometries\\" + MESH_PATH + ".mesh": b"sf-mesh-bytes"})
            out = os.path.join(tmp, "work")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(fs.main(["--skyrim-data", sky, "--starfield-data", sf, "--out", out]), 0)
            with zipfile.ZipFile(os.path.join(out, "skeletons_for_claude.zip")) as z:
                names = sorted(z.namelist())
                self.assertEqual(z.read("skyrim/meshes/actors/character/character assets/malebody_0.nif"),
                                 b"sk-body0-loose")
                self.assertEqual(z.read("starfield/geometries/" + MESH_PATH.replace("\\", "/") + ".mesh"),
                                 b"sf-mesh-bytes")                       # the body's external mesh, other archive
                cand = z.read("candidates.txt").decode()
            self.assertIn("skyrim/meshes/actors/character/character assets female/skeleton_female.nif", names)
            self.assertIn("skyrim/meshes/actors/character/character assets/1stpersonmalebody_0.nif", names)
            self.assertIn("starfield/meshes/actors/human/characterassets/skeleton.nif", names)
            self.assertIn("starfield/meshes/clothes/outfit_nightwear_01/outfit_nightwear_upperbody_01_m.nif", names)
            for unwanted in ("dummy.nif", "bucket01.nif", "helmet.nif"):
                self.assertFalse(any(n.endswith(unwanted) for n in names), unwanted)
            self.assertIn("Starfield - Meshes01.ba2", cand)
            self.assertLess(cand.index("skeleton.nif"), cand.index("naked_m.nif"))  # skeletons first

    def test_refuses_output_inside_the_repository(self):
        with self.assertRaises(SystemExit):
            fs.main(["--skyrim-data", ".", "--starfield-data", ".", "--out", os.path.join(ROOT, "tmp_out")])
        self.assertFalse(os.path.exists(os.path.join(ROOT, "tmp_out")))


if __name__ == "__main__":
    unittest.main()
