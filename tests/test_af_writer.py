"""fo4sf.af_writer: key reduction and descriptors (pure), and an optional CALUMI round trip when CALUMI_LIB points at
a CALUMI build (scripts/armor/build_calumi_linux.sh, or the Windows DLL); skipped otherwise."""
import math
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import af_writer as AF  # noqa: E402


def qa(axis, deg):
    a = math.radians(deg) / 2
    ax = np.asarray(axis, float) / np.linalg.norm(axis)
    return np.r_[ax * math.sin(a), math.cos(a)]


class AfWriterTests(unittest.TestCase):
    def test_keys_needed_linear_and_corner(self):
        lin = np.linspace(0, 1, 11)[:, None]
        self.assertEqual(AF._keys_needed(lin, 1e-6), [0, 10])
        corner = np.r_[np.linspace(0, 1, 6), np.linspace(0.8, 0, 5)][:, None]
        keys = AF._keys_needed(corner, 1e-6)
        self.assertIn(5, keys)
        self.assertEqual((keys[0], keys[-1]), (0, 10))

    def test_descriptor(self):
        r = ET.fromstring(AF.descriptor("IdleBook", "idlebook.af"))
        self.assertEqual((r.find("tag").text, r.find("filename").text, r.find("is_state").text),
                         ("IdleBook", "idlebook.af", "0"))

    def test_events_mapped_into_descriptor(self):
        mapped, rest = AF.map_events([{"time": 0.3, "text": "preHitFrame"}, {"time": 0.5, "text": "HitFrame"},
                                      {"time": 0.0, "text": "SoundPlay.WPNBowNockSD"}], 30.0)
        self.assertEqual(mapped, [(9, "PreHitFrame", ""), (15, "HitFrame", "")])
        self.assertEqual([r["text"] for r in rest], ["SoundPlay.WPNBowNockSD"])
        from fo4sf import agx
        d = agx.read_descriptor(AF.descriptor("MeleeAttack_A", "a.af", False, mapped, [("bDontAllowBlock", 0, 30)], 6))
        self.assertEqual((d["events"], d["variables"], d["rampout"]),
                         ([(9, "PreHitFrame", ""), (15, "HitFrame", "")], [("bDontAllowBlock", 0, 30)], 6))

    def test_refuses_output_inside_repo(self):
        with self.assertRaises(ValueError):
            AF.write("nolib", os.path.join(ROOT, "tmp_af"), "x", ["Root"], [-1], [[0, 0, 0]], [[0, 0, 0, 1]],
                     np.zeros((1, 1, 3)), np.tile([0, 0, 0, 1.0], (1, 1, 1)))

    def test_keys_are_relative_to_rest(self):
        rest_q = np.array([qa((0, 0, 1), 90), [0, 0, 0, 1.0]])
        rest_t = np.array([[0, 0, 1.0], [0.5, 0, 0]])
        key_q = np.array([[qa((1, 0, 0), 30), qa((0, 1, 0), -20)]])
        key_t = np.array([[[0, 0.1, -0.4], [0, 0, 0]]])
        loc_t, loc_q = AF.from_rest_relative(rest_t, rest_q, key_t, key_q)
        self.assertTrue(np.allclose(loc_t[0, 0], [0, 0.1, 0.6]))
        back_q, back_t = AF.rest_relative(rest_t, rest_q, loc_t, loc_q)
        self.assertTrue(np.allclose(back_q, key_q) and np.allclose(back_t, key_t))
        rest_only, _ = AF.rest_relative(rest_t, rest_q, rest_t[None], rest_q[None])   # rest pose -> identity keys
        self.assertTrue(np.allclose(np.abs(rest_only[..., 3]), 1))

    def test_retime_vanilla_descriptor(self):
        vanilla = (b"<root>\r\n\t<is_state>0</is_state>\r\n\t<tag>MeleeAttack01</tag>\r\n\t<filename>MeleeAttack01.af"
                   b"</filename>\r\n\t<rampout>9</rampout>\r\n\t<events>\r\n"
                   b"\t\t<event><frame>10</frame><name>HitFrame</name><payload></payload></event>\r\n"
                   b"\t\t<event><frame>4</frame><name>CameraShake</name><payload>0.8,0.1</payload></event>\r\n"
                   b"\t</events>\r\n\t<variables>\r\n\t\t<variable><name>bNoHeadTrack</name><start>0</start>"
                   b"<end>30</end></variable>\r\n\t</variables>\r\n</root>\r\n")
        out, rep = AF.retime_descriptor(vanilla, 60, "MeleeAttack01.af", own_events=[(42, "HitFrame", "")])
        self.assertEqual((rep["old_last"], rep["old_last_estimated"], rep["scale"]), (30, True, 2.0))
        self.assertEqual(rep["events_from_clip"], ["HitFrame"])
        root = ET.fromstring(out)
        frames = {e.findtext("name"): int(e.findtext("frame")) for e in root.iter("event")}
        self.assertEqual(frames, {"HitFrame": 42, "CameraShake": 8})          # ours / scaled
        v = root.find("variables/variable")
        self.assertEqual((v.findtext("start"), v.findtext("end")), ("0", "60"))
        self.assertEqual((root.findtext("tag"), root.findtext("rampout")), ("MeleeAttack01", "9"))   # kept
        self.assertIn(b"\r\n", out)
        self.assertNotIn(b"\r\r", out)
        self.assertIn(b"<payload></payload>", out)                # as shipped: no self-closing empty elements
        out2, rep2 = AF.retime_descriptor(vanilla, 15, "X.af", old_last=60)    # known vanilla length: shorter clip
        self.assertEqual(ET.fromstring(out2).find("variables/variable").findtext("end"), "8")
        self.assertEqual(ET.fromstring(out2).findtext("filename"), "X.af")

    @unittest.skipUnless(os.environ.get("CALUMI_LIB"), "set CALUMI_LIB to a CALUMI build to run the round trip")
    def test_omitted_bones_get_no_track(self):
        q = np.tile([0, 0, 0, 1.0], (3, 3, 1))
        t = np.zeros((3, 3, 3))
        q[:, 2] = qa((0, 0, 1), 40)                                         # would tilt the "camera"
        with tempfile.TemporaryDirectory() as d:
            w = AF.write(os.environ["CALUMI_LIB"], d, "omit", ["Root", "Bone", "Camera"], [-1, 0, 0],
                         np.zeros((3, 3)), [[0, 0, 0, 1.0]] * 3, t, q, omit=("Camera", "Absent"))
            rb = AF.read_back(os.environ["CALUMI_LIB"], w["af"], w["rig"])
        self.assertEqual(w["omitted"], ["Camera"])
        self.assertNotIn("Camera", rb["bones"])
        self.assertIn("Bone", rb["bones"])

    @unittest.skipUnless(os.environ.get("CALUMI_LIB"), "set CALUMI_LIB to a CALUMI build to run the round trip")
    def test_round_trip_large_rotations(self):
        angles = [0, 60, 120, 150, 179, -170]
        q = np.zeros((len(angles), 3, 4))
        t = np.zeros((len(angles), 3, 3))
        q[:, 0] = [0, 0, 0, 1]
        q[:, 2] = [0, 0, 0, 1]
        for f, a in enumerate(angles):
            q[f, 1] = qa((1, 0, 0), a)
        t[:, 1] = [0, 0, 1]
        with tempfile.TemporaryDirectory() as d:
            w = AF.write(os.environ["CALUMI_LIB"], d, "probe", ["Root", "Bone", ""], [-1, 0, 1],
                         [[0, 0, 0], [0, 0, 1], [0, 0, 0]], [[0, 0, 0, 1]] * 3, t, q, tolerance=0.0)
            self.assertEqual((w["bones"], w["dropped_unnamed"]), (2, 1))   # the unnamed leaf is dropped
            rb = AF.read_back(os.environ["CALUMI_LIB"], w["af"], w["rig"])
            rig = AF.load_rig(os.environ["CALUMI_LIB"], w["rig"])           # the rig as the converter reads it
        self.assertEqual((rig["names"], rig["parents"]), (["Root", "Bone"], [-1, 0]))
        self.assertTrue(np.allclose(rig["t"][1], [0, 0, 1], atol=1e-5))
        self.assertTrue(np.allclose(np.abs(rig["q"][1]), [0, 0, 0, 1], atol=1e-5))
        for f, v in rb["rotations"]["Bone"]:
            v = np.array(v)
            self.assertLess(min(np.max(np.abs(v - q[f, 1])), np.max(np.abs(v + q[f, 1]))), 1e-3, (f, v))


if __name__ == "__main__":
    unittest.main()
