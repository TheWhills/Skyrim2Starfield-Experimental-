"""scripts/armor/sf_anim_survey.py on a synthetic Starfield animations archive (no game data)."""
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
import sf_anim_survey as S  # noqa: E402
from test_agx import GRAPH  # noqa: E402
import skyrim_fixtures as F  # noqa: E402


class SfAnimSurveyTests(unittest.TestCase):
    def test_afx_fields(self):
        elems, tags, files = S.afx_fields(b"<root><is_state>0</is_state><tag>Open</tag>"
                                          b"<filename>Open.af</filename></root>")
        self.assertEqual((tags, files), (["Open"], ["Open.af"]))
        self.assertIn("is_state", elems)

    def test_report_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            sf = os.path.join(tmp, "Data")
            os.makedirs(sf)
            F.starfield_meshes_ba2(os.path.join(sf, "Starfield - Animations.ba2"), {
                "meshes\\actors\\human\\characterassets\\skeleton.rig": b"rig",
                "meshes\\actors\\human\\animations\\powers\\cast_start.af": b"af",
                "meshes\\actors\\human\\animations\\powers\\cast_start.afx":
                    b"<root><tag>PowerCast</tag><filename>cast_start.af</filename></root>",
                "animtextdata\\tables\\graphs\\humanbase01.agx": b"\x01\x02\x00graphEventPowerCast\x00AnimSpeed\x00",
                "animtextdata\\tables\\graphs\\door01.agx": b"<graph>door</graph>",
                "animtextdata\\tables\\graphs\\wolfcreature.agx": GRAPH,
                "meshes\\clutter\\bucket.nif": b"not animation"})
            out = os.path.join(tmp, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(S.main(["--starfield-data", sf, "--out", out, "--list", "animations/powers"]), 0)
            rep = open(os.path.join(out, "report.txt"), encoding="utf-8").read()
            with open(os.path.join(out, "listing.txt"), encoding="utf-8") as fh:
                listing = fh.read()
            self.assertIn("meshes/actors/human/animations/powers/\n", listing)
            self.assertIn("  cast_start.afx: tag 'PowerCast', is_state ?, rampout -, file 'cast_start.af'; events []",
                          listing)
            self.assertNotIn("cast_start.af: no descriptor", listing)
            self.assertIn("6 animation-system files", rep)
            self.assertIn("link events (1, graphs using each): BowDrawStart 1", rep)
            self.assertIn("Prefix:iSyncRelaxReadySneak:Relaxed/Sneak x1", rep)
            self.assertIn("wolfcreature.agx: 3 nodes; tags ['BowDraw']", rep)
            self.assertIn("graphEventPowerCast", rep)                 # binary graph strings printed
            self.assertIn("PowerCast 1", rep)                        # descriptor tag counted
            self.assertIn("[cast / powers] 2", rep)                   # the .af and its .afx
            with zipfile.ZipFile(os.path.join(out, "sf_anim_samples.zip")) as z:
                names = z.namelist()
            self.assertIn("starfield/animtextdata/tables/graphs/humanbase01.agx", names)
            self.assertIn("starfield/meshes/actors/human/characterassets/skeleton.rig", names)
            self.assertNotIn("starfield/animtextdata/tables/graphs/door01.agx", names)

    def test_mod_folder_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = os.path.join(tmp, "IdleMod", "Data", "meshes", "actors", "human", "animations", "idles")
            os.makedirs(mod)
            with open(os.path.join(mod, "lean.af"), "wb") as f:
                f.write(b"af")
            with open(os.path.join(mod, "lean.afx"), "wb") as f:
                f.write(b"<root><tag>LeanWall</tag><filename>lean.af</filename></root>")
            zp = os.path.join(tmp, "naf_pack.zip")
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("Data/NAF/dance01.glb", b"glTF")
                z.writestr("Data/readme.txt", b"hi")
            out = os.path.join(tmp, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(S.main(["--mod", os.path.join(tmp, "IdleMod"), "--mod", zp, "--out", out]), 0)
            rep = open(os.path.join(out, "report.txt"), encoding="utf-8").read()
            self.assertIn("3 animation-system files", rep)
            self.assertIn("IdleMod (loose): .af 1, .afx 1", rep)
            self.assertIn("naf_pack.zip: .glb 1", rep)
            self.assertIn("LeanWall 1", rep)
            self.assertIn("  2  meshes/actors/human/animations", rep.replace("     2", "  2"))


if __name__ == "__main__":
    unittest.main()
