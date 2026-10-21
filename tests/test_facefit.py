"""src/fo4sf/facefit.py on synthetic heads: sliders recovered from a deformed head, and the Skyrim -> Starfield
transfer through a differently sampled, scaled and turned copy."""
import json
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import facefit as F  # noqa: E402

BONES = {"faceBone_C_NoseMaster": (0, 0.11, 0.02), "faceBone_C_Chin": (0, 0.07, -0.08),
         "faceBone_L_EyeDef": (0.035, 0.09, 0.04), "faceBone_R_EyeDef": (-0.035, 0.09, 0.04),
         "faceBone_C_MouthPivot": (0, 0.1, -0.03), "faceBone_L_Cheek": (0.05, 0.07, 0.0)}


def head_points(n=1600, seed=0):
    """An egg-shaped head (metres, facing +Y, Z up)."""
    rng = np.random.default_rng(seed)
    p = rng.normal(size=(n, 3))
    p /= np.linalg.norm(p, axis=1, keepdims=True)
    p = p * np.array([0.075, 0.1, 0.12])
    # a nose and a brow ridge: features that fix the facing, as on a real head
    nose = np.exp(-((p[:, 0] / 0.012) ** 2 + ((p[:, 2] - 0.0) / 0.03) ** 2)) * (p[:, 1] > 0)
    brow = np.exp(-(((p[:, 2] - 0.045) / 0.01) ** 2)) * (p[:, 1] > 0.05) * (np.abs(p[:, 0]) < 0.05)
    p[:, 1] += 0.025 * nose + 0.008 * brow
    return p


def make_head(verts):
    names = list(BONES)
    piv = np.array([BONES[b] for b in names])
    d2 = np.sum((verts[:, None, :] - piv[None]) ** 2, axis=2)
    w = np.exp(-d2 / (2 * 0.03 ** 2))
    w[w < 1e-3] = 0
    frames = np.repeat(np.eye(3)[None], len(names), 0)
    frames[2] = F._rot(0.2, 0, 0.1)                       # one bone with its own axes
    return F.Head(verts, names, w, piv, frames)


def bone(name, mn=(0, 0, 0), mx=(0, 0, 0), rmn=(0, 0, 0), rmx=(0, 0, 0), smn=(0, 0, 0), smx=(0, 0, 0)):
    v = lambda a: dict(zip("xyz", a))      # noqa: E731
    return {"Bone": name, "Minima": {"Position": v(mn), "Rotation": v(rmn), "Scale": v(smn)},
            "Maxima": {"Position": v(mx), "Rotation": v(rmx), "Scale": v(smx)}}


REGIONS = {"Constraints": None, "Regions": [
    {"ID": 1, "Name": "male_eu_md2", "SculptRegion": False, "SlidersA": [
        {"ID": 13, "Name": "", "ZeroToOne": True, "BonesA": [
            bone(b, mx=(0.3, 0.1, -0.2)) for b in BONES]}]},
    {"ID": 30, "Name": "Nose", "SculptRegion": True, "SlidersA": [
        {"ID": 40, "Name": "down - up", "ZeroToOne": False, "BonesA": [
            bone("faceBone_C_NoseMaster", mn=(0, 0, -1.0), mx=(0, 0, 1.0))]},
        {"ID": 41, "Name": "nose width", "ZeroToOne": False, "BonesA": [
            bone("faceBone_C_NoseMaster", smn=(-0.2, 0, 0), smx=(0.3, 0, 0))]}]},
    {"ID": 31, "Name": "Jaw", "SculptRegion": True, "SlidersA": [
        {"ID": 50, "Name": "chin forward", "ZeroToOne": False, "BonesA": [
            bone("faceBone_C_Chin", mn=(0, -0.8, 0), mx=(0, 1.2, 0.2))]},
        {"ID": 51, "Name": "mouth tilt", "ZeroToOne": False, "BonesA": [
            bone("faceBone_C_MouthPivot", rmn=(0, -8, 0), rmx=(0, 8, 0))]}]},
    {"ID": 32, "Name": "Eyes", "SculptRegion": True, "SlidersA": [
        {"ID": 60, "Name": "eye spacing", "ZeroToOne": False, "BonesA": [
            bone("faceBone_L_EyeDef", mn=(-0.5, 0, 0), mx=(0.5, 0, 0)),
            bone("faceBone_R_EyeDef", mn=(0.5, 0, 0), mx=(-0.5, 0, 0))]}]}]}


class FaceFitTests(unittest.TestCase):
    def setUp(self):
        self.sliders = F.load_regions(json.dumps(REGIONS))
        self.head = make_head(head_points())

    def test_load_regions(self):
        by = {s.id: s for s in self.sliders}
        self.assertEqual(sorted(by), [13, 40, 41, 50, 51, 60])
        self.assertTrue(by[13].zero_to_one and not by[13].sculpt)
        self.assertEqual(by[60].region, "Eyes")
        mn, mx = by[40].bones["faceBone_C_NoseMaster"]
        self.assertEqual((mn[2], mx[2]), (-1.0, 1.0))

    def test_deform_moves_only_weighted_vertices(self):
        out = F.deform(self.head, self.sliders, {40: 1.0})
        moved = np.linalg.norm(out - self.head.vertices, axis=1)
        b = self.head.bones.index("faceBone_C_NoseMaster")
        self.assertAlmostEqual(moved.max(), 0.01 * self.head.weights[:, b].max(), places=6)   # 1 cm at full weight
        self.assertTrue(np.all(moved[self.head.weights[:, b] == 0] == 0))

    def test_recovers_slider_values(self):
        truth = {13: 0.6, 40: -0.5, 41: 0.4, 50: 0.7, 51: -0.6, 60: 0.3}
        target = F.deform(self.head, self.sliders, truth)
        values, rep = F.fit(self.head, self.sliders, target, F.face_weights(self.head))
        for k, v in truth.items():
            self.assertAlmostEqual(values.get(k, 0.0), v, delta=0.05, msg=(k, values))
        self.assertLess(rep["rms_after"], rep["rms_before"] * 0.02)

    def test_bounds_hold(self):
        target = F.deform(self.head, self.sliders, {40: 1.0})
        target = self.head.vertices + 3.0 * (target - self.head.vertices)       # beyond what the slider can do
        values, _rep = F.fit(self.head, self.sliders, target)
        self.assertAlmostEqual(values[40], 1.0, places=3)
        self.assertTrue(all(-1.0 - 1e-9 <= v <= 1.0 + 1e-9 for v in values.values()))
        self.assertGreaterEqual(values.get(13, 0.0), 0.0)                       # ZeroToOne never negative

    def test_transfer_through_another_mesh(self):
        truth = {40: 0.8, 50: -0.6, 60: -0.4}
        sf_target = F.deform(self.head, self.sliders, truth)
        # "Skyrim": a denser, different sampling of the same shape, in game units (x 70), turned 4 degrees, moved
        dense = head_points(5000, seed=3)
        dense_head = make_head(dense)
        dense_face = F.deform(dense_head, self.sliders, truth)
        R = F._rot(0, 0, math.radians(4))
        to_sky = lambda p: 70.0 * p @ R.T + np.array([5.0, -2.0, 120.0])   # noqa: E731
        sky_base, sky_face = to_sky(dense), to_sky(dense_face)
        al = F.align_heads(sky_base, self.head.vertices)
        s, R_found, _t, _rms = al
        self.assertAlmostEqual(s, 1 / 70.0, delta=0.002 / 70.0)                # game units back to metres
        turn = math.degrees(math.atan2(R_found[1, 0], R_found[0, 0]))
        self.assertAlmostEqual(turn, -4.0, delta=0.5)                           # the 4 degree turn undone
        disp = F.transfer(sky_base, sky_face, al, self.head.vertices)
        err = np.linalg.norm(self.head.vertices + disp - sf_target, axis=1)
        self.assertLess(float(np.mean(err)), 0.0015)
        values, rep = F.fit(self.head, self.sliders, self.head.vertices + disp, F.face_weights(self.head))
        for k, v in truth.items():
            self.assertAlmostEqual(values.get(k, 0.0), v, delta=0.12, msg=(k, values))

    def test_bounded_lsq(self):
        A = np.array([[1.0, 0.0], [0.0, 2.0], [1.0, 1.0]])
        x = F.bounded_lsq(A, A @ np.array([0.3, 0.7]))
        self.assertTrue(np.allclose(x, [0.3, 0.7], atol=1e-4))
        x = F.bounded_lsq(A, A @ np.array([-0.5, 2.0]))
        self.assertTrue(np.all(x >= 0) and np.all(x <= 1) and x[1] == 1.0)


class StarfieldHeadTests(unittest.TestCase):
    def test_head_from_skin_and_mesh(self):
        from fo4sf import sfmesh
        verts = head_points(400)
        names = ["C_Head", "faceBone_C_NoseMaster", "faceBone_C_Chin"]
        piv = {"faceBone_C_NoseMaster": np.array(BONES["faceBone_C_NoseMaster"]),
               "faceBone_C_Chin": np.array(BONES["faceBone_C_Chin"]), "C_Head": np.zeros(3)}
        Rb = F._rot(0.3, -0.2, 0.5)                   # bone axes in head space
        binds = []
        for b in names:
            Rbind = Rb.T                               # head -> bone: R v + t with R = axes^T
            t = -Rbind @ piv[b]
            binds.append(((0, 0, 0, 0), tuple(Rbind.reshape(-1)), tuple(t), 1.0))
        m = sfmesh.SfMesh()
        m.scale, raw = sfmesh.encode_positions([tuple(v) for v in verts])
        m.positions = raw
        m.weights_per_vertex = 2
        for v in verts:
            near = 1 if v[2] > -0.03 else 2
            m.weights += [(0, 32768), (near, 32767)]
        pos, ws = F.mesh_arrays(m)
        self.assertLess(float(np.max(np.abs(pos - verts))), 1e-5)
        head, rep = F.face_head(pos, ws, names, binds)
        self.assertEqual(head.bones, ["faceBone_C_NoseMaster", "faceBone_C_Chin"])
        self.assertFalse(rep["bind_read_transposed"])
        self.assertTrue(np.allclose(head.pivots[0], piv["faceBone_C_NoseMaster"], atol=1e-6))
        self.assertTrue(np.allclose(head.frames[1], Rb, atol=1e-6))
        self.assertAlmostEqual(float(head.weights.sum(1).max()), 0.5, places=3)   # half on C_Head: not a fit bone
        self.assertEqual(rep["vertices_moved_by_face_bones"], 400)


if __name__ == "__main__":
    unittest.main()
