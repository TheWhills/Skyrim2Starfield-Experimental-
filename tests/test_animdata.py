"""src/fo4sf/animdata.py (Skyrim animationdatasinglefile) and hkx_to_af.load_motion_data on synthetic files."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import animdata as A  # noqa: E402

try:
    import hkx_to_af as H  # noqa: E402  (imports numpy)
except ImportError:                                      # pragma: no cover
    H = None


def _project(files, clips, motion):
    """Lines of one project's two sections, in the layout of the real file."""
    block = ["1", str(len(files))] + files
    if clips is None:
        return [str(len(block) + 1)] + block + ["0"]
    block.append("1")
    for name, ident, events in clips:
        block += [name, ident, "1", "0", "0", str(len(events))] + events + [""]
    mot = []
    for ident, dur, tr, rot in motion:
        mot += [ident, dur, str(len(tr))] + tr + [str(len(rot))] + rot + [""]
    return [str(len(block))] + block + [str(len(mot))] + mot


SAMPLE = "\n".join(
    ["3", "Moth.txt", "DefaultMale.txt", "Moth.txt"]
    + _project(["Behaviors\\Moth.hkx"], None, [])
    + _project(["Behaviors\\0_Master.hkx", "Characters\\DefaultMale.hkx"],
               [("TKDodgeForward", "1656", []),
                ("1HM_AttackRight", "12", ["weaponSwing:0.4", "HitFrame:0.5"]),
                ("1HM_AttackRight[mirrored]", "13", []),
                ("NoMotion", "99", [])],
               [("1656", "0.866667", ["0.0666667 0 12.963 0", "0.866667 0 409.283 0"], ["0.866667 0 0 0 1"]),
                ("12", "2", ["2 0 80 0"], ["2 0 0 0.258819 0.965926"]),
                ("13", "2", ["2 0 -80 0"], ["2 0 0 0 1"])])
    + _project(["Behaviors\\Other.hkx"], None, [])) + "\n"


class ParseTests(unittest.TestCase):
    def test_projects_clips_and_motion(self):
        d = A.parse(SAMPLE)
        self.assertEqual(sorted(d), ["DefaultMale", "Moth"])            # the repeated object project kept once
        dm = d["DefaultMale"]
        self.assertEqual(dm["files"], ["Behaviors\\0_Master.hkx", "Characters\\DefaultMale.hkx"])
        self.assertEqual([c["name"] for c in dm["clips"]],
                         ["TKDodgeForward", "1HM_AttackRight", "1HM_AttackRight[mirrored]", "NoMotion"])
        self.assertEqual(dm["clips"][1]["events"], [("weaponSwing", 0.4), ("HitFrame", 0.5)])
        self.assertEqual(sorted(dm["motion"]), ["12", "13", "1656"])
        self.assertEqual(dm["motion"]["12"]["duration"], 2.0)                # a whole-number duration is read
        self.assertEqual(dm["motion"]["1656"]["translations"][-1], (0.866667, 0.0, 409.283, 0.0))
        self.assertEqual(d["Moth"]["clips"], [])

    def test_damaged_files_are_refused(self):
        with self.assertRaises(A.AnimDataError):
            A.parse(SAMPLE.replace("409.283 0\n", "409.283\n"))           # a key with 3 numbers
        with self.assertRaises(A.AnimDataError):
            A.parse(SAMPLE + "extra\n")
        with self.assertRaises(A.AnimDataError):
            A.parse("")

    def test_clip_motion_by_name_and_by_behaviour(self):
        dm = A.parse(SAMPLE)["DefaultMale"]
        rep = {}
        by_name = A.clip_motion(dm, report=rep)
        self.assertEqual(sorted(by_name), ["1hm_attackright", "tkdodgeforward"])
        self.assertEqual(rep["mirrored_skipped"], 1)
        self.assertEqual(rep["no_motion_block"], ["NoMotion"])
        gens = A.clip_generators([{"nodes": {
            1: {"class": "hkbClipGenerator", "name": "1HM_AttackRight", "animation": "Animations\\1hm_attackright2.HKX"},
            2: {"class": "hkbStateMachine", "name": "x"}}}])
        mapped = A.clip_motion(dm, gens, rep)
        self.assertIn("1hm_attackright2", mapped)                         # file stem from the behaviour
        self.assertNotIn("1hm_attackright", mapped)
        self.assertEqual(mapped["1hm_attackright2"]["translations"], [(2.0, 0.0, 80.0, 0.0)])
        self.assertEqual(rep["by_behavior"], 1)

    def test_conflicting_generators_pick_the_common_motion(self):
        dm = A.parse(SAMPLE)["DefaultMale"]
        dm["clips"] += [{"name": "AttackAgain", "id": "12", "speed": 1, "crop": (0, 0), "events": []},
                        {"name": "AttackOdd", "id": "1656", "speed": 1, "crop": (0, 0), "events": []}]
        gens = {"1hm_attackright": "a\\swing.hkx", "attackagain": "a\\swing.hkx", "attackodd": "a\\swing.hkx"}
        rep = {}
        out = A.clip_motion(dm, gens, rep)
        self.assertEqual(out["swing"]["duration"], 2.0)
        self.assertEqual(rep["conflicts"], {"swing": {"12": 2, "1656": 1}})


class FragmentTests(unittest.TestCase):
    def _fragments(self, root):
        d = os.path.join(root, "animationdatasinglefile", "DefaultMale~1")
        os.makedirs(d)
        with open(os.path.join(d, "TKDodgeBack~mod$1.txt"), "w") as fh:
            fh.write("TKDodgeBack\nmod$1\n1\n0\n0\n1\nTKDodgeStop:0.8\n")
        with open(os.path.join(d, "mod$1.txt"), "w") as fh:              # a new block
            fh.write("mod$1\n0.8\n2\n0.4 0 -150 0\n0.8 0 -300 0\n1\n0.8 0 0 0 1\n")
        with open(os.path.join(d, "1656.txt"), "w") as fh:                # a patch of a vanilla block (stale counts)
            fh.write("1656\n<!-- MOD_CODE ~mod~ OPEN -->\n0.7\n<!-- ORIGINAL -->\n0.866667\n<!-- CLOSE -->\n1\n"
                     "<!-- MOD_CODE ~mod~ OPEN -->\n0.3 0 100 0\n<!-- CLOSE -->\n"
                     "<!-- MOD_CODE ~mod~ OPEN -->\n0.7 0 350 0\n<!-- ORIGINAL -->\n0.866667 0 409.283 0\n"
                     "<!-- CLOSE -->\n1\n0.7 0 0 0 1\n")
        return os.path.join(root, "animationdatasinglefile")

    def test_markup(self):
        self.assertEqual(A.apply_markup(["a", "<!-- MOD_CODE ~m~ OPEN -->", "new", "<!-- ORIGINAL -->", "old",
                                         "<!-- CLOSE -->", "<!-- MOD_CODE ~m~ OPEN -->", "added", "<!-- CLOSE -->",
                                         "b"]), ["a", "new", "added", "b"])

    def test_fragments_override_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            fr = A.read_fragments(self._fragments(tmp))
            self.assertEqual(sorted(fr["DefaultMale"]["motion"]), ["1656", "mod$1"])
            patched = fr["DefaultMale"]["motion"]["1656"]
            self.assertEqual(patched["duration"], 0.7)
            self.assertEqual(patched["translations"], [(0.3, 0.0, 100.0, 0.0), (0.7, 0.0, 350.0, 0.0)])
            self.assertEqual(fr["DefaultMale"]["clips"][0]["events"], [("TKDodgeStop", 0.8)])
            merged = A.merge(A.parse(SAMPLE), fr)
            out = A.clip_motion(merged["DefaultMale"])
            self.assertEqual(out["tkdodgeforward"]["duration"], 0.7)            # the mod's version
            self.assertEqual(out["tkdodgeback"]["translations"][-1], (0.8, 0.0, -300.0, 0.0))
            self.assertIn("1hm_attackright", out)                               # vanilla entries stay

    @unittest.skipIf(H is None, "numpy not installed")
    def test_converter_loads_file_and_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "animationdatasinglefile.txt")
            with open(path, "w") as fh:
                fh.write(SAMPLE)
            motion, rep = H.load_motion_data([path, self._fragments(tmp)], "defaultmale")
            self.assertEqual(sorted(motion), ["1hm_attackright", "tkdodgeback", "tkdodgeforward"])
            self.assertEqual(rep["by_name"], 4)
            with self.assertRaises(SystemExit):
                H.load_motion_data([path], "FirstPerson")


if __name__ == "__main__":
    unittest.main()
