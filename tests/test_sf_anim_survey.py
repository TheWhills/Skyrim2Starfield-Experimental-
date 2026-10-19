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
                "meshes\\clutter\\bucket.nif": b"not animation"})
            out = os.path.join(tmp, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(S.main(["--starfield-data", sf, "--out", out]), 0)
            rep = open(os.path.join(out, "report.txt"), encoding="utf-8").read()
            self.assertIn("5 animation-system files", rep)
            self.assertIn("graphEventPowerCast", rep)                 # binary graph strings printed
            self.assertIn("PowerCast 1", rep)                        # descriptor tag counted
            self.assertIn("[cast / powers] 2", rep)                   # the .af and its .afx
            with zipfile.ZipFile(os.path.join(out, "sf_anim_samples.zip")) as z:
                names = z.namelist()
            self.assertIn("starfield/animtextdata/tables/graphs/humanbase01.agx", names)
            self.assertIn("starfield/meshes/actors/human/characterassets/skeleton.rig", names)
            self.assertNotIn("starfield/animtextdata/tables/graphs/door01.agx", names)


if __name__ == "__main__":
    unittest.main()
