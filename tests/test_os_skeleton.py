"""scripts/armor/os_skeleton.py: the game's skeleton copied to the name BodySlide's Config.xml asks for (synthetic)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import os_skeleton as S  # noqa: E402


class SkeletonTests(unittest.TestCase):
    def test_config_name(self):
        xml = "<Anim>\n<DefaultSkeletonReference>res\\skeleton_female_sf.nif</DefaultSkeletonReference>\n</Anim>"
        self.assertEqual(S.configured_skeleton(xml), "res\\skeleton_female_sf.nif")
        self.assertEqual(S.configured_skeleton("<x/>"), "res\\skeleton_female_sf.nif")

    def test_copies_once(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Config.xml"), "w") as fh:
                fh.write("<DefaultSkeletonReference>res\\skel_sf.nif</DefaultSkeletonReference>")
            calls = []

            def fake(path, data_dir):
                calls.append(path)
                return b"NIFDATA", path
            with mock.patch.object(S.hkx_to_af, "vanilla_file", fake):
                self.assertEqual(S.main(["--bodyslide", d, "--starfield", d]), 0)
                self.assertEqual(open(os.path.join(d, "res", "skel_sf.nif"), "rb").read(), b"NIFDATA")
                self.assertEqual(calls, [S.SKELETONS["female"]])
                S.main(["--bodyslide", d, "--starfield", d])                  # already there: left alone
                self.assertEqual(len(calls), 1)
                S.main(["--bodyslide", d, "--starfield", d, "--force", "--sex", "male"])
                self.assertEqual(calls[-1], S.SKELETONS["male"])


if __name__ == "__main__":
    unittest.main()
