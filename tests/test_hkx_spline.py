"""fo4sf.hkxspline (Havok spline-compressed track decoding) and skyrimhkx.Layout on synthetic data (no game files).
The real-file check is scripts/armor/hkx_decode_check.py."""
import math
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import hkxspline as S, skyrimhkx  # noqa: E402


def enc40(q):
    """Encode a unit quaternion as threecomp40 (the inverse of the decoder; largest component dropped)."""
    i = max(range(4), key=lambda k: abs(q[k]))
    rest = [q[k] for k in range(4) if k != i]
    k = (1.0 / math.sqrt(2.0)) / 2047.0
    v = 0
    for n, c in enumerate(rest):
        v |= (int(round(c / k)) + 2047) << (12 * n)
    v |= i << 36
    v |= (1 if q[i] < 0 else 0) << 38
    return v.to_bytes(5, "little")


def norm(q):
    s = math.sqrt(sum(c * c for c in q))
    return tuple(c / s for c in q)


def qclose(a, b, tol):
    return min(max(abs(x - y) for x, y in zip(a, b)), max(abs(x + y) for x, y in zip(a, b))) < tol


class Builder:
    def __init__(self):
        self.b = bytearray()

    def put(self, fmt, *v):
        self.b += struct.pack(fmt, *v)

    def raw(self, x):
        self.b += x

    def align(self, a):
        while len(self.b) % a:
            self.b.append(0)


def block(tracks, n_float=0):
    """tracks: list of dicts {pos: ("static", (x,y,z)) | ("spline", knots, degree, [(x,y,z)...]) | None,
    rot: ("static", q) | ("spline", knots, degree, [q...]) | None}; scale always identity."""
    w = Builder()
    for t in tracks:
        pt = 0
        if t["pos"] and t["pos"][0] == "static":
            pt = 0x07
        elif t["pos"]:
            pt = 0x70
        rt = 0x0F if t["rot"] and t["rot"][0] == "static" else (0xF0 if t["rot"] else 0)
        w.put("<4B", 1 | (1 << 2), pt, rt, 0)          # 16-bit positions, threecomp40 rotations
    w.raw(bytes(n_float))
    w.align(4)
    for t in tracks:
        p = t["pos"]
        if p and p[0] == "static":
            w.put("<3f", *p[1])
        elif p:
            _, knots, deg, pts = p
            w.put("<HB", len(pts) - 1, deg)
            w.raw(bytes(knots))
            w.align(4)
            for a in range(3):
                w.put("<2f", -10.0, 10.0)
            for cp in pts:
                for a in range(3):
                    w.put("<H", int(round((cp[a] + 10.0) / 20.0 * 65535)))
            w.align(4)
        r = t["rot"]
        if r and r[0] == "static":
            w.raw(enc40(r[1]))
            w.align(4)
        elif r:
            _, knots, deg, qs = r
            w.put("<HB", len(qs) - 1, deg)
            w.raw(bytes(knots))
            for q in qs:
                w.raw(enc40(q))
            w.align(4)
        else:
            w.align(4)
    w.align(16)
    return bytes(w.b)


class SplineTests(unittest.TestCase):
    def test_threecomp40_roundtrip(self):
        for q in [(0, 0, 0, 1), norm((0.3, -0.5, 0.2, 0.78)), norm((-0.9, 0.1, 0.2, -0.3)), norm((0.1, 0.8, -0.5, 0.2))]:
            self.assertTrue(qclose(S.quat_threecomp40(enc40(q)), q, 1e-3), q)

    def test_threecomp48_identity(self):
        b = struct.pack("<3H", 16383 | 0x8000, 16383 | 0x8000, 16383)      # w dropped (shift 3), positive
        self.assertTrue(qclose(S.quat_threecomp48(b), (0, 0, 0, 1), 1e-4))

    def test_bspline_degree1_is_linear_and_clamped_cubic_hits_ends(self):
        self.assertEqual(S.evaluate(2.5, 1, [0, 0, 5, 5], [(0.0,), (10.0,)]), [5.0])
        knots = [0, 0, 0, 0, 10, 10, 10, 10]
        pts = [(1.0,), (4.0,), (-2.0,), (7.0,)]
        self.assertAlmostEqual(S.evaluate(0.0, 3, knots, pts)[0], 1.0)
        self.assertAlmostEqual(S.evaluate(10.0, 3, knots, pts)[0], 7.0)

    def test_decode_static_spline_and_identity_tracks_over_two_blocks(self):
        q0, q1 = norm((0, 0, 0, 1)), norm((0, 0.6, 0, 0.8))
        b0 = block([{"pos": ("static", (1.0, 2.0, 3.0)), "rot": ("static", q1)},
                    {"pos": ("spline", [0, 0, 4, 4], 1, [(0, 0, 0), (4, -2, 8)]),
                     "rot": ("spline", [0, 0, 4, 4], 1, [q0, q1])},
                    {"pos": None, "rot": None}], n_float=1)
        b1 = block([{"pos": ("static", (1.0, 2.0, 3.0)), "rot": ("static", q1)},
                    {"pos": ("static", (4.0, -2.0, 8.0)), "rot": ("static", q1)},
                    {"pos": None, "rot": None}], n_float=1)
        data = b0 + b1
        st = {}
        fr = S.decode(data, [0, len(b0)], 3, 1, 7, 5, st)        # 5 frames per block, shared frame 4
        self.assertEqual(len(fr), 7)
        self.assertEqual(st["rotation_encodings"], {"threecomp40": 6})
        t, q, s = fr[0][0]
        self.assertEqual(t, (1.0, 2.0, 3.0))
        self.assertTrue(qclose(q, q1, 1e-3))
        self.assertEqual(s, (1.0, 1.0, 1.0))
        mid = fr[2][1]                                             # halfway along the linear spline
        self.assertTrue(all(abs(a - b) < 1e-3 for a, b in zip(mid[0], (2.0, -1.0, 4.0))))
        self.assertTrue(qclose(mid[1], norm((0, 0.3, 0, 0.9)), 2e-3))
        self.assertEqual(fr[6][1][0], (4.0, -2.0, 8.0))            # second block
        self.assertEqual(fr[3][2], ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0)))

    def test_unsupported_rotation_encoding_is_reported(self):
        data = struct.pack("<4B", 0 | (3 << 2), 0, 0x0F, 0) + bytes(12)
        with self.assertRaises(S.SplineError):
            S.decode(data, [0], 1, 0, 1, 2)

    def test_layout_offsets(self):
        L = skyrimhkx.Layout(8)                     # 64-bit: the documented SE offsets
        self.assertEqual((L.sk_parents, L.sk_bones, L.sk_pose, L.an_annot, L.an_base), (24, 40, 56, 40, 56))
        self.assertEqual((L.sp_block_offsets, L.sp_data, L.bi_tracks), (88, 152, 32))
        L = skyrimhkx.Layout(4)                     # 32-bit LE
        self.assertEqual((L.sk_parents, L.sk_bones, L.sk_pose, L.an_annot, L.an_base), (12, 24, 36, 28, 40))
        self.assertEqual((L.sp_block_offsets, L.sp_data, L.bi_tracks, L.bone_size, L.annot_size), (68, 116, 16, 8, 8))


if __name__ == "__main__":
    unittest.main()
