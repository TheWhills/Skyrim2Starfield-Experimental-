"""fo4sf.rootmotion and retarget.resample on synthetic data (no game or mod files)."""
import math
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import retarget as R  # noqa: E402
from fo4sf import rootmotion as M  # noqa: E402


class RootMotionTests(unittest.TestCase):
    def test_sparse_keys_interpolate_and_hold(self):
        ann = [{"time": 0.0, "text": "animmotion 0 0 0"}, {"time": 0.9, "text": "animmotion 0 333.4 0"},
               {"time": 0.5, "text": "HitFrame"}]
        m = M.from_annotations(ann, 28, 30.0)                      # 0 .. 0.9 s: the last key is the clip's end
        self.assertAlmostEqual(m["t"][27, 1], 333.4)
        self.assertAlmostEqual(m["t"][9, 1], 333.4 * 0.3 / 0.9)    # two keys: a straight line (BFCO_JumpAttack)
        self.assertTrue(np.allclose(m["yaw"], 0))
        longer = M.from_annotations(ann, 31, 30.0)["t"][:, 1]       # clip goes on: eased into the hold
        self.assertAlmostEqual(longer[27], 333.4)
        self.assertTrue(np.allclose(longer[27:], 333.4) and np.all(np.diff(longer) >= -1e-9))

    def test_dense_keys_implicit_zero_and_rotation(self):
        ann = [{"time": (k + 1) / 60, "text": f"animmotion 1.0 {k + 1}.0 0.0"} for k in range(60)]
        ann += [{"time": 0.5, "text": "animrotation 90"}, {"time": 1.0, "text": "animrotation 90"}]
        m = M.from_annotations(ann, 31, 30.0)
        self.assertTrue(np.allclose(m["t"][0], 0))                 # implicit zero at the start
        self.assertAlmostEqual(m["t"][15, 1], 30.0)                # 0.5 s = key 30
        self.assertAlmostEqual(m["yaw"][15], 90.0)
        self.assertTrue(0 < m["yaw"][5] < 90 and np.all(np.diff(m["yaw"]) >= -1e-9))   # 0 -> 90, no overshoot
        t, q = M.root_track(m, 0.0142875, scale=2.0)
        self.assertAlmostEqual(t[15, 1], 30.0 * 0.0142875 * 2.0)
        self.assertAlmostEqual(M.yaw_degrees(q[15]), 90.0, places=4)
        fwd = R.qrot(q[15], np.array([0, 1.0, 0]))                 # +90 = counter-clockwise: forward turns to -X
        self.assertTrue(np.allclose(fwd, [-1, 0, 0], atol=1e-9))
        self.assertTrue(M.moves(t, q))
        self.assertFalse(M.moves(np.zeros((3, 3)), np.tile([0, 0, 0, 1.0], (3, 1))))
        self.assertIsNone(M.from_annotations([{"time": 0, "text": "HitFrame"}], 3, 30.0))
        self.assertTrue(M.is_motion_annotation("AnimMotion 0 1 0") and not M.is_motion_annotation("HitFrame"))

    def test_sparse_keys_keep_speed_continuous(self):
        # a Nordic-style attack: still, lunge in two steps, hold, a slow drift, hold (keys in game units)
        keys = [(0.17, 0), (0.33, 50), (0.47, 160), (1.0, 160), (1.67, 200), (1.83, 200)]
        ann = [{"time": t, "text": f"animmotion 0 {y} 0"} for t, y in keys]
        m = M.from_annotations(ann, 56, 30.0)
        y = m["t"][:, 1]
        for t, v in keys:                                                      # passes through every key
            if abs(t * 30 - round(t * 30)) < 1e-6:
                self.assertAlmostEqual(y[int(round(t * 30))], v, places=6)
        v = np.diff(y)
        self.assertTrue(np.all(v >= -1e-9))                                    # never goes backwards
        self.assertTrue(np.allclose(y[15:30], 160, atol=1e-6))                 # the hold (0.47-1.0 s) stays a hold
        self.assertLess(np.max(np.abs(np.diff(v))), 0.6 * np.max(v))           # no jump in speed frame to frame
        lin = np.interp(np.arange(56) / 30.0, [0] + [k[0] for k in keys], [0] + [k[1] for k in keys])
        self.assertGreater(np.max(np.abs(np.diff(np.diff(lin)))), np.max(np.abs(np.diff(v))))   # smoother than linear

    def test_motion_comes_to_rest_after_the_last_key(self):
        ann = [{"time": 0.0, "text": "animmotion 0 0 0"}, {"time": 0.2, "text": "animmotion 0 40 0"},
               {"time": 0.43, "text": "animmotion 0 100 0"}]               # last key mid-clip, still moving fast
        y = M.from_annotations(ann, 30, 30.0)["t"][:, 1]
        v = np.diff(y)
        k = int(0.43 * 30)
        self.assertLess(v[k], 0.35 * np.max(v))                            # slowing into the key, not cut off
        self.assertTrue(np.allclose(y[14:], 100, atol=1e-6))

    def test_motion_data_blocks(self):
        text = ("TKDodgeForward\n1656\n1\n0\n0\n0\n\n"            # a clip entry (name, id, ...): not motion
                "1656\n0.8\n3\n0.1 0 -38.0 0\n0.4 0 -200 0\n0.8 0 -300.0 0\n1\n0.8 0 0 0.7071068 0.7071068\n\n"
                "1657\n0.7\n2\n0.06667 -23.0 0 0\n0.7 -251.7 0 0\n1\n0.7 0 0 0 1\n")
        b = M.parse_motion_data(text)
        self.assertEqual(sorted(b), ["1656", "1657"])
        self.assertEqual(b["1656"]["duration"], 0.8)
        self.assertEqual(b["1656"]["translations"][-1], (0.8, 0.0, -300.0, 0.0))
        self.assertEqual(len(b["1657"]["translations"]), 2)
        ann = M.motion_annotations(b["1656"])
        m = M.from_annotations(ann, 25, 30.0)
        self.assertAlmostEqual(m["t"][24, 1], -300.0)                       # 0.8 s: the last key
        self.assertAlmostEqual(m["yaw"][24], 90.0, places=4)                  # +90 about Z: counter-clockwise
        self.assertTrue(np.all(np.diff(m["t"][:, 1]) <= 1e-9))               # backwards all the way
        self.assertEqual(M.parse_motion_data("1656\n0.8\n2\n0.1 0 1 0\n"), {})   # cut short: not a block

    def test_header_patch(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.af")
            with open(p, "wb") as fh:
                fh.write(struct.pack("<Q", 0x1234) + struct.pack("<4f", 1, 0, 0, 0) + struct.pack("<3f", 0, 0, 0)
                         + b"\xaa" * 28)
            q = (0.0, 0.0, math.sin(math.radians(30)), math.cos(math.radians(30)))
            M.patch_header(p, (0.1, 1.85, 0.0), q)
            with open(p, "rb") as fh:
                data = fh.read()
        self.assertEqual(struct.unpack_from("<Q", data, 0)[0], 0x1234)        # magic untouched
        rq, rt = M.read_header(data)
        self.assertTrue(np.allclose(rq, q, atol=1e-6) and np.allclose(rt, (0.1, 1.85, 0.0), atol=1e-6))
        self.assertEqual(struct.unpack_from("<f", data, 8)[0], np.float32(q[3]))   # stored w first
        self.assertEqual(data[36:], b"\xaa" * 28)                                 # the rest untouched

    def test_play_speed(self):
        F = 31                                                                     # 1 s at 30 fps
        tr = [((k * 1.0, 0, 0), (0, 0, 0, 1.0), (1, 1, 1)) for k in range(F)]
        clip = {"frames": F, "fps": 30.0, "duration": 1.0, "tracks": [tr], "bones": ["b"],
                "annotations": [{"time": 0.5, "text": "HitFrame"}]}
        slow = R.play_speed(clip, 0.8)
        self.assertAlmostEqual(slow["duration"], 1.25)
        self.assertAlmostEqual(slow["annotations"][0]["time"], 0.625)
        r = R.resample(slow, 30.0)
        self.assertEqual(r["frames"], 39)                                          # 1.25 s at 30 fps
        self.assertAlmostEqual(r["tracks"][0][-1][0][0], 30.0)                     # same motion, just slower
        self.assertAlmostEqual(r["tracks"][0][24][0][0], 24 * 0.8, places=6)
        self.assertIs(R.play_speed(clip, 1.0), clip)

    def test_resample_to_30(self):
        F = 7                                                                      # 60 fps, 0.1 s
        ang = np.linspace(0, 60, F)
        tr = [((k * 1.0, 0, 0), (0, 0, math.sin(math.radians(a / 2)), math.cos(math.radians(a / 2))), (1, 1, 1))
              for k, a in enumerate(ang)]
        clip = {"frames": F, "fps": 60.0, "duration": 0.1, "tracks": [tr], "bones": ["b"], "annotations": []}
        r = R.resample(clip, 30.0)
        self.assertEqual((r["frames"], r["fps"], r["resampled_from"]), (4, 30.0, 60.0))
        self.assertTrue(np.allclose([f[0][0] for f in r["tracks"][0]], [0, 2, 4, 6]))
        self.assertAlmostEqual(M.yaw_degrees(r["tracks"][0][1][1]), 20.0, places=5)
        self.assertIs(R.resample(dict(clip, fps=30.0), 30.0)["tracks"], clip["tracks"])   # already 30: unchanged


if __name__ == "__main__":
    unittest.main()
