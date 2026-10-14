"""scripts/armor/af_roundtrip_survey.py with a fake CALUMI backend and a fake archive (no DLL, no game data)."""
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
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import af_roundtrip_survey as sv  # noqa: E402


class FakeArchive:
    def __init__(self, files):
        self.names = list(files)
        self.files = files

    def read(self, i):
        return self.files[self.names[i]]


def track(rot=(), trn=(), scl=()):
    return {"index": 0, "rot": list(rot), "trn": list(trn), "scl": list(scl)}


Q0, Q90 = [0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.7071068, 0.7071068]
GOOD = {"frames": 31, "tracks": {"Root": track([(0, Q0), (30, Q90)], [(0, [0.0, 0.0, 1.0])], [(0, 1.0)])}}


class FakeCalumi:
    """decode() returns a fixed animation per input bytes; save() writes a marker; behaviour keyed by file content."""

    def __init__(self, dll):
        self.saved = {}

    def decode(self, rig, path):
        data = open(path, "rb").read()
        if data == b"unreadable":
            raise RuntimeError("[CALUMI] Error, bad preamble")
        if data == b"crash":
            raise SystemExit("simulated DLL crash")
        if data.startswith(b"rewritten:"):
            kind = data[len(b"rewritten:"):]
            if kind == b"differ":
                bad = json.loads(json.dumps(GOOD))
                bad["tracks"]["Root"]["trn"] = [(0, [0.0, 0.0, 1.5])]
                return bad, "scene", "anim"
            # every-frame rewrite of a sparse original with the same values (q and -q mixed): must compare equal
            dense = [(f, Q0) for f in range(30)] + [(30, [-v for v in Q90])]
            return {"frames": 31, "tracks": {"Root": track(dense, [(0, [0.0, 0.0, 1.0])], [(0, 1.0)]),
                                             "Extra": track([(0, Q0)])}}, "scene", "anim"
        return json.loads(json.dumps(GOOD)), "scene", data.decode()

    def save(self, anim, out, rig):
        if anim == "unsavable":
            raise RuntimeError("save returned false")
        with open(out, "wb") as f:
            f.write(b"rewritten:" + anim.encode())

    def free(self, scene):
        pass


class SurveyTests(unittest.TestCase):
    def test_find_rig_prefers_characterassets_then_a_lone_rig(self):
        rigs = {"meshes/actors/human/characterassets/skeleton.rig", "meshes/doors/a/door.rig"}
        self.assertEqual(sv.find_rig("Meshes\\Actors\\Human\\Animations\\Idle\\x.af", rigs),
                         "meshes/actors/human/characterassets/skeleton.rig")
        self.assertEqual(sv.find_rig("meshes/doors/a/animations/open.af", rigs), "meshes/doors/a/door.rig")
        self.assertIsNone(sv.find_rig("meshes/creatures/x/animations/y.af", rigs))

    def test_compare_tolerates_dense_rewrite_and_quaternion_sign(self):
        dense = {"frames": 31, "tracks": {"Root": track([(f, Q0) for f in range(30)] + [(30, [-v for v in Q90])],
                                                        [(0, [0.0, 0.0, 1.0])], [(0, 1.0)])}}
        r = sv.compare(GOOD, dense)
        self.assertTrue(r["equal"], r)
        moved = {"frames": 31, "tracks": {"Root": track([(0, Q0), (30, Q90)], [(0, [0.0, 0.0, 1.002])], [(0, 1.0)])}}
        r = sv.compare(GOOD, moved)
        self.assertFalse(r["equal"])
        self.assertAlmostEqual(r["max"]["trn"], 0.002, places=6)
        r = sv.compare(GOOD, {"frames": 31, "tracks": {}})
        self.assertEqual(r["missing_bones"], ["Root"])

    def run_survey(self, files, extra=(), resume=False, out=None):
        arc = FakeArchive(files)
        index = {sv.norm(n): (arc, i) for i, n in enumerate(arc.names)}
        out = out or tempfile.mkdtemp()
        with mock.patch.object(sv, "index_archives", return_value=index), \
                mock.patch.object(sv, "Calumi", FakeCalumi), contextlib.redirect_stdout(io.StringIO()):
            sv.main(["--dll", "x.dll", "--starfield-data", ".", "--out", out, *extra] + (["--resume"] if resume else []))
        with open(os.path.join(out, "report.json"), encoding="utf-8") as f:
            return json.load(f), out

    def test_classes_report_and_resume_after_a_crash(self):
        rig = "meshes/actors/human/characterassets/skeleton.rig"
        files = {rig: b"rig",
                 "meshes/actors/human/animations/a_equal.af": b"equal",
                 "meshes/actors/human/animations/b_differ.af": b"differ",
                 "meshes/actors/human/animations/c_bad.af": b"unreadable",
                 "meshes/actors/human/animations/d_nosave.af": b"unsavable",
                 "meshes/lonely/e.af": b"equal"}
        rep, out = self.run_survey(files)
        by = {os.path.basename(r["af"]): r["class"] for r in rep["results"]}
        self.assertEqual(by, {"a_equal.af": "values_equal", "b_differ.af": "values_differ",
                              "c_bad.af": "load_failed", "d_nosave.af": "save_failed", "e.af": "no_rig"})
        self.assertEqual(rep["summary"]["classes"]["values_equal"], 1)
        self.assertIn("x1: [CALUMI] Error, bad preamble", open(os.path.join(out, "report.txt")).read())
        # a DLL crash kills the process on c_crash.af; --resume marks it crashed and finishes the rest
        files2 = {rig: b"rig", "meshes/actors/human/animations/a.af": b"equal",
                  "meshes/actors/human/animations/c_crash.af": b"crash",
                  "meshes/actors/human/animations/z.af": b"equal"}
        tmp = tempfile.mkdtemp()
        with self.assertRaises(SystemExit):
            self.run_survey(files2, out=tmp)
        rep, _ = self.run_survey(files2, resume=True, out=tmp)
        by = {os.path.basename(r["af"]): r["class"] for r in rep["results"]}
        self.assertEqual(by, {"a.af": "values_equal", "c_crash.af": "crashed", "z.af": "values_equal"})

    def test_refuses_output_inside_the_repository(self):
        with self.assertRaises(SystemExit):
            sv.main(["--dll", "x", "--starfield-data", ".", "--out", os.path.join(ROOT, "af_out")])


if __name__ == "__main__":
    unittest.main()
