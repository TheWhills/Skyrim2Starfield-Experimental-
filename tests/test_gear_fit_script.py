"""scripts/armor/gear_fit.py: refuses an output inside the repository; the writer it shares with os_export."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import gear_fit  # noqa: E402
import os_export  # noqa: E402


class ScriptTests(unittest.TestCase):
    def test_out_inside_repo_refused(self):
        with self.assertRaises(SystemExit):
            gear_fit.main(["--skyrim-data", "x", "--starfield", "y", "--npc", "Ralof", "--name", "R",
                           "--out", os.path.join(ROOT, "tmp_out")])

    def test_shared_writer(self):
        self.assertTrue(callable(os_export.write_armor))


if __name__ == "__main__":
    unittest.main()
