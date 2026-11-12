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


class RidgeSymmetryTests(unittest.TestCase):
    """2026-11-05: with More Sliders' 307 sliders Ralof came out deformed (73 dials at +-1)."""

    def test_ridge_stops_opposed_near_duplicates(self):
        head = make_head(head_points())
        # two sliders that almost undo each other: up, and up a little less with a slight tilt
        sl = F.load_regions(json.dumps({"Regions": [{"ID": 1, "Name": "Nose", "SculptRegion": True, "SlidersA": [
            {"ID": 1, "Name": "a", "BonesA": [bone("faceBone_C_NoseMaster", mn=(0, 0, -1.0), mx=(0, 0, 1.0))]},
            {"ID": 2, "Name": "b", "BonesA": [bone("faceBone_C_NoseMaster", mn=(0, 0, 0.98), mx=(0, 0, -0.98),
                                                   rmn=(2, 0, 0), rmx=(-2, 0, 0))]}]}]}))
        target = F.deform(head, sl, {1: 1.0, 2: 1.0})          # a small change only the pair at full makes
        loose, rep0 = F.fit(head, sl, target, F.face_weights(head), ridge=1e-6)
        tight, rep1 = F.fit(head, sl, target, F.face_weights(head), ridge=0.05)
        self.assertGreater(max(abs(v) for v in loose.values()), 0.3)          # bought with the cancelling pair
        self.assertLess(max([abs(v) for v in tight.values()] + [0.0]), 0.1)
        self.assertLess(rep1["max_change_m"], rep0["max_change_m"])
        self.assertIn("max_error_m", rep1)

    def test_symmetrize(self):
        v = head_points(800)
        v = np.vstack([v, v * np.array([-1.0, 1.0, 1.0])])                # exactly mirrored halves
        field = np.zeros_like(v)
        field[:800, 0] = 0.002                                            # one half pushed out (+x) ...
        field[:800, 1] = 0.001
        sym = F.symmetrize(field, v)
        m = F.mirror_index(v)
        self.assertTrue(np.allclose(sym[m] * [-1, 1, 1], sym))           # ... the result is a mirror image of itself
        self.assertAlmostEqual(float(np.abs(sym[:, 1]).max()), 0.0005, places=6)

    def test_symmetrize_other_lip(self):
        """2026-11-11 (the Orc mouth's strands): a vertex whose mirror partner lies on the other lip (interleaved lip
        surfaces facing the other way) keeps its own move; partners on the same surface still share the stronger."""
        A, B = np.array([0.01, 0.0, 0.0002]), np.array([-0.01, 0.0, -0.0002])
        dx, dy = np.array([0.001, 0.0, 0.0]), np.array([0.0, 0.001, 0.0])
        v = np.array([A, A + dy, A + dx, B, B + dy, B - dx,                 # upper lip (faces down) / lower (up)
                      (0.03, 0, 0.01), (0.03, 0.001, 0.01), (0.031, 0, 0.01),       # an ear and its twin
                      (-0.03, 0, 0.01), (-0.03, 0.001, 0.01), (-0.031, 0, 0.01)])
        f = np.array([[0, 1, 2], [3, 4, 5], [6, 8, 7], [9, 10, 11]])
        field = np.zeros_like(v)
        field[:3, 2], field[3:6, 2] = 0.005, -0.009        # upper lip up, lower lip down (further)
        field[6:9, 0] = 0.03                               # one ear's point; the other lost it
        plain = F.symmetrize(field, v, 0, "stronger")
        self.assertAlmostEqual(plain[0, 2], -0.009)                         # without faces: torn
        fixed = F.symmetrize(field, v, 0, "stronger", faces=f)
        np.testing.assert_allclose(fixed[:6], field[:6])                    # each lip keeps its own
        np.testing.assert_allclose(fixed[9:12, 0], -0.03)                   # the ear still gets its twin's point


RECIPE = "\n".join([
    "MORESLIDERSFACEBONES\t1", "# comment",
    "NODE\tmeshes\\skeleton_facebones.nif\tfaceBone_MS_A\tfaceBone_C_Chin\t0\t0\t0",
    "MESH\tgeometries\\AB12\\CD34.mesh\t3\t3\tdeadbeef",
    "W\t0\t1\t2\t32768", "W\t1\t1\t2\t65535", "W\t2\t0\t2\t65535",
    "MESH\tgeometries\\ee\\ff.mesh\t1\t1\t0", "W\t0\t0\t1\t1",
    "FOLLOW\tmeshes\\beard.nif", "W\t9\t9\t9\t9"])


class RecipeTests(unittest.TestCase):
    """More Sliders' MoreSlidersFaceBones_recipe.txt: weight moves onto the new face bones (owner 2026-11-05)."""

    def test_load_recipe(self):
        r = F.load_recipe(RECIPE)
        self.assertEqual(sorted(r), ["ab12/cd34.mesh", "ee/ff.mesh"])
        b = r["ab12/cd34.mesh"]
        self.assertEqual((b["vertices"], b["count"], b["checksum"]), (3, 3, "deadbeef"))
        self.assertEqual(b["moves"], [(0, 1, 2, 32768), (1, 1, 2, 65535), (2, 0, 2, 65535)])
        self.assertEqual(len(r["ee/ff.mesh"]["moves"]), 1)           # the W after FOLLOW belongs to no block
        self.assertEqual(F._mesh_key("geometries/AB12/CD34.mesh"), "ab12/cd34.mesh")

    def test_apply_recipe_moves_part_of_the_parent_weight(self):
        ws = [[(0, 0.5), (1, 0.5)], [(1, 1.0)], [(1, 1.0)]]
        out, rep = F.apply_recipe(ws, F.load_recipe(RECIPE)["ab12/cd34.mesh"]["moves"])
        d = [dict(row) for row in out]
        self.assertAlmostEqual(d[0][1], 0.5 * (1 - 32768 / 65535))
        self.assertAlmostEqual(d[0][2], 0.5 * 32768 / 65535)
        self.assertEqual(d[1], {2: 1.0})                              # all of it: the parent drops out
        self.assertEqual(d[2], {1: 1.0})                              # no weight on bone 0 there: nothing moves
        self.assertEqual((rep["moves"], rep["skipped"]), (2, 1))
        for row in out:
            self.assertAlmostEqual(sum(w for _b, w in row), 1.0)

    def test_moved_weight_makes_the_new_bones_slider_work(self):
        verts = head_points(300)
        names = ["faceBone_C_Chin", "faceBone_MS_A"]
        piv = np.array(BONES["faceBone_C_Chin"])
        binds = [((0, 0, 0, 0), tuple(np.eye(3).reshape(-1)), tuple(-piv), 1.0)] * 2
        ws = [[(0, 1.0)] for _ in verts]
        moves = [(v, 0, 1, 65535) for v in range(len(verts)) if verts[v][2] < -0.05]
        sl = [F.Slider(1, "new", "Chin", False, True, {"faceBone_MS_A": (np.zeros(9), np.r_[0, 0, 1.0, np.zeros(6)])})]
        before, _ = F.face_head(verts, ws, names, binds)
        self.assertTrue(np.allclose(F.deform(before, sl, {1: 1.0}), verts))
        after, _ = F.face_head(verts, F.apply_recipe(ws, moves)[0], names, binds)
        moved = np.abs(F.deform(after, sl, {1: 1.0}) - verts).max(1) > 1e-6
        self.assertEqual(int(moved.sum()), len(moves))


class BlendFitTests(unittest.TestCase):
    """2026-11-12 (owner: are we using Starfield's shape blends, not just the sliders): blends fitted with the dials."""

    def blends(self, v):
        """Three shape blends a slider cannot make: a cheek bulge, a forehead slope, a nose hump (V, 3 each)."""
        cheek = np.exp(-((np.abs(v[:, 0]) - 0.05) ** 2 + v[:, 2] ** 2) / (2 * 0.02 ** 2))[:, None] * np.array(
            [0, 0.006, 0])
        fore = np.clip(v[:, 2:3] - 0.05, 0, None) * np.array([0, 0.08, 0]) * (v[:, 1:2] > 0)
        hump = np.exp(-(v[:, 0] ** 2 + (v[:, 2] - 0.01) ** 2) / (2 * 0.01 ** 2))[:, None] * np.array([0, 0.004, 0])
        return ["male_eu_md2_Cheeks", "male_eu_ol1_Forehead", "male_eu_ol1_Nose"], np.stack([cheek, fore, hump])

    def test_recovers_blends_and_sliders(self):
        sliders = F.load_regions(json.dumps(REGIONS))
        head = make_head(head_points())
        names, D = self.blends(head.vertices)
        truth_b = np.array([0.6, 0.0, 0.8])
        shaped = F._with_vertices(head, head.vertices + np.tensordot(truth_b, D, axes=1))
        target = F.deform(shaped, sliders, {40: 0.5}, 0.01)
        only, rep0 = F.fit(head, sliders, target)
        vals, rep = F.fit(head, sliders, target, blends=(names, D), ridge=1e-6)
        self.assertLess(rep["rms_after"], 0.25 * rep0["rms_after"])          # far closer than sliders alone
        got = np.array([rep["blends"].get(n, 0.0) for n in names])
        self.assertTrue(np.allclose(got, truth_b, atol=0.08), got)
        self.assertAlmostEqual(vals.get(40, 0.0), 0.5, delta=0.08)
        self.assertEqual(rep["blends_offered"], 3)
        # nothing given: the old fit, unchanged
        v2, r2 = F.fit(head, sliders, target)
        self.assertEqual((v2, r2), (only, rep0))

    def test_region_cap(self):
        """Blends of one region (both nose keys here) add up to at most region_max; the sliders refit round them."""
        sliders = F.load_regions(json.dumps(REGIONS))
        head = make_head(head_points())
        _n, D = self.blends(head.vertices)
        names = ["male_eu_ol1_Nose", "male_eu_md2_Nose"]
        D2 = np.stack([D[2], D[2] * 0.9])
        target = head.vertices + 1.6 * D[2]                                   # more than one key alone can give
        _v, rep = F.fit(head, sliders, target, blends=(names, D2), blend_groups=["Nose", "Nose"], region_max=1.0)
        self.assertLessEqual(sum(rep["blends"].values()), 1.0 + 1e-6)
        self.assertTrue(rep["blend_regions_capped"])


if __name__ == "__main__":
    unittest.main()


class ModelSpaceAlignmentTests(unittest.TestCase):
    def test_skin_to_model_matrix(self):
        import types
        from fo4sf import skyrimhair
        st = types.SimpleNamespace(rotation=[0, -1, 0, 1, 0, 0, 0, 0, 1], translation=[3.0, -2.0, 5.0], scale=2.0)
        shape = types.SimpleNamespace(skin_transform=st)
        pts = np.random.default_rng(2).normal(size=(5, 3)) * 10
        f, _r = skyrimhair.skin_to_model(shape)
        np.testing.assert_allclose(F.apply4(F.skin_to_model_matrix(st), pts), f(pts), atol=1e-9)
        np.testing.assert_allclose(F.skin_to_model_matrix(None), np.eye(4))

    def test_align_to_local_through_node(self):
        # Starfield head = Skyrim head x 0.015 in model space, stored rotated (x up) with a longer neck below;
        # the alignment must recover the scale, give ~0 rms, and map into the local frame
        def ellipsoid(n_u, n_v):
            u, v = np.meshgrid(np.linspace(0, 2 * np.pi, n_u, endpoint=False), np.linspace(0.05, np.pi - 0.05, n_v))
            return np.column_stack([60 * np.sin(v).ravel() * np.cos(u).ravel(), 70 * np.sin(v).ravel() *
                                    np.sin(u).ravel(), 80 * np.cos(v).ravel()]) + [0, 0, 100]
        sky = ellipsoid(30, 20)
        model = ellipsoid(90, 60) * 0.015 + [0.01, -0.02, 1.6]
        zlow = model[:, 2].min()
        rng = np.random.default_rng(3)
        neck = np.column_stack([rng.normal(size=(150, 2)) * 0.3, zlow - 0.05 - rng.random(150) * 1.5])
        node = np.eye(4)
        node[:3, :3] = [[0, 0, -1], [0, 1, 0], [1, 0, 0]]
        node[:3, 3] = (0, 0, 1.5)
        local = F.apply4(np.linalg.inv(node), np.concatenate([model, neck]))
        s, R, t, rms = F.align_to_local(sky, local, node)
        self.assertAlmostEqual(s / 0.015, 1.0, places=2)
        self.assertLess(rms, 0.08)          # the sparse 30 x 20 sampling (~0.18 m apart) sets the floor; neck left out
        moved = F.apply4(node, s * sky @ R.T + t)
        np.testing.assert_allclose(moved.mean(0), model.mean(0), atol=0.01)
        # up in Skyrim model space is +x in the local frame
        np.testing.assert_allclose(R @ [0, 0, 1], [1, 0, 0], atol=1e-9)
