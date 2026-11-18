"""scripts/npc/critter_roundtrip.py on synthetic data: sparse CALUMI keys made dense, and a fake run of both modes
(vanilla critter clips / rig through CALUMI, no chicken)."""
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import critter_roundtrip as R  # noqa: E402


class DenseTests(unittest.TestCase):
    def test_vector_track(self):
        t = R.dense_track([(1, (0, 0, 0)), (3, (2, 0, 0))], 5, (9, 9, 9), False)
        np.testing.assert_allclose(t[:, 0], [0, 0, 1, 2, 2])

    def test_no_keys_is_rest(self):
        np.testing.assert_allclose(R.dense_track([], 2, (1, 2, 3), False), [[1, 2, 3]] * 2)

    def test_quat_track_normalised_shortest(self):
        s = np.sin(np.pi / 4)
        q = R.dense_track([(0, (0, 0, 0, 1)), (2, (0, 0, -s, -s))], 3, (0, 0, 0, 1), True)   # -q90: same as +q90
        np.testing.assert_allclose(np.linalg.norm(q, axis=1), 1)
        self.assertGreater(q[1, 3], 0.9)                                                  # halfway: 45 deg, not 135

    def test_densify_omits_untracked(self):
        read = {"frames": 2, "bones": ["Root"], "rotations": {"Root": [(0, (0, 0, 0, 1))]},
                "translations": {"Root": [(0, (0, 1, 0)), (1, (0, 2, 0))]}}
        ct, cq, untracked = R.densify(read, ["Root", "COM"], np.zeros((2, 3)), np.tile([0, 0, 0, 1.0], (2, 1)))
        self.assertEqual(ct.shape, (2, 2, 3))
        np.testing.assert_allclose(ct[:, 0, 1], [1, 2])
        self.assertEqual(untracked, ["COM"])


class MainTests(unittest.TestCase):
    def run_main(self, what):
        import sf_anim_survey as SAS
        from fo4sf import af_writer
        hdr = bytearray(64)
        struct.pack_into("<4f", hdr, 8, 1, 0, 0, 0)
        files = {R.RIG: b"vanilla rig", R.ANIMS + "walkforward.af": bytes(hdr), R.ANIMS + "walkforward.afx": b"d"}

        class Ba2:
            names = list(files)

            def read(self, i):
                return files[self.names[i]]
        rig = {"names": ["Root", "COM"], "parents": [-1, 0], "t": np.zeros((2, 3)), "q": np.tile([0, 0, 0, 1.0], (2, 1))}
        read = {"frames": 2, "bones": ["Root"], "rotations": {"Root": [(0, (0, 0, 0, 1))]},
                "translations": {"Root": [(0, (0, 0, 0)), (1, (0, 0.5, 0))]}}
        calls = []

        def fake_write(lib, out_dir, name, bones, parents, rest_t, rest_q, clip_t, clip_q, rig_path=None, **kw):
            calls.append((name, bones, rig_path, kw.get("omit")))
            os.makedirs(out_dir, exist_ok=True)
            open(os.path.join(out_dir, name + ".af"), "wb").write(bytes(64))
            return {}

        def fake_prefix(lib, src, count, out_path):
            calls.append(("prefix", count))
            open(out_path, "wb").write(b"copied rig")
            return out_path
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(SAS, "archives", lambda _d: [("Starfield - Animations.ba2", Ba2())]), \
                mock.patch.object(af_writer, "load_rig", lambda _l, _r: rig), \
                mock.patch.object(af_writer, "read_back", lambda *_a, **_k: read), \
                mock.patch.object(af_writer, "write", fake_write), \
                mock.patch.object(af_writer, "rig_prefix", fake_prefix):
            out = os.path.join(d, "mod")
            self.assertEqual(R.main(["--starfield-data", d, "--calumi", "x.dll", "--what", what, "--out", out]), 0)
            with open(os.path.join(out, "critter_roundtrip.json")) as fh:
                rep = json.load(fh)
            listing = sorted(os.path.relpath(os.path.join(p, f), out).replace(os.sep, "/")
                             for p, _d, fs in os.walk(out) for f in fs)
        return rep, calls, listing

    def test_clips_mode(self):
        rep, calls, listing = self.run_main("clips")
        self.assertEqual(rep["errors"], {})
        self.assertEqual(calls[0][0], "walkforward")
        self.assertTrue(calls[0][2].endswith("critter_vanilla.rig"))        # written against the vanilla rig
        self.assertEqual(calls[0][3], ["COM"])
        self.assertEqual(listing, ["critter_roundtrip.json", R.ANIMS + "walkforward.af"])   # .afx and rig stay vanilla

    def test_rig_mode(self):
        rep, calls, listing = self.run_main("rig")
        self.assertEqual(calls, [("prefix", 2)])
        self.assertEqual(listing, ["critter_roundtrip.json", "critter_vanilla.rig", R.RIG])


if __name__ == "__main__":
    unittest.main()
