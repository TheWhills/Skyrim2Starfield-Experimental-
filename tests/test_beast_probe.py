"""scripts/npc/beast_probe.py on synthetic heads: landmarks (eyes, mouth-hole corners, nose tip, crown, back, sides),
the thin-plate warp (landmarks land exactly; a muzzled head comes back onto the round one), the jaw check, Starfield's
morph records (BMPP), and a run of main() with the game reads stubbed."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import types
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import sfplugin  # noqa: E402
import beast_probe as B  # noqa: E402
from test_mouth_probe import sphere  # noqa: E402


def head(r=10.0, muzzle=1.0, n=48, m=36):
    """A round head (Skyrim units, +Y forward, +Z up) with a mouth hole at the front and a neck opening below; muzzle
    stretches the front half forward. Returns (vertices, triangles, eye points)."""
    v, t = sphere(n, m, r)
    c = v[t].mean(1)
    mouth = (c[:, 1] > 0.85 * r) & (np.abs(c[:, 2] + 0.35 * r) < 0.05 * r) & (np.abs(c[:, 0]) < 0.3 * r)
    neck = c[:, 2] < -0.9 * r
    t = t[~(mouth | neck)]
    v = v.copy()
    v[v[:, 1] > 0, 1] *= muzzle
    eyes = np.concatenate([np.array([(x, 0.8 * r * muzzle, 0.25 * r)]) + np.random.default_rng(1).normal(size=(20, 3))
                           * 0.2 for x in (0.35 * r, -0.35 * r)])
    return v, t, eyes


class LandmarkTests(unittest.TestCase):
    def test_landmarks_and_warp(self):
        hv, hf, he = head()
        bv, bf, be = head(muzzle=1.6)
        hl = B.landmarks(hv, hf, B.eye_centres(he))
        bl = B.landmarks(bv, bf, B.eye_centres(be))
        for k in B.LANDMARKS:
            self.assertIsNotNone(hl[k], k)
            self.assertIsNotNone(bl[k], k)
        self.assertGreater(hl["mouth_left"][0], 0)
        self.assertLess(hl["mouth_right"][0], 0)
        self.assertGreater(bl["nose_tip"][1], hl["nose_tip"][1] * 1.4)            # the muzzle
        self.assertAlmostEqual(bl["crown"][2], 10.0, delta=0.5)
        warped, used = B.warp(bv, bl, hl)
        self.assertEqual(len(used), len(B.LANDMARKS))
        src = np.array([bl[k] for k in used])
        fit = B.tps_fit(src, np.array([hl[k] for k in used]))
        self.assertLess(np.abs(B.tps_apply(src, fit, src) - np.array([hl[k] for k in used])).max(), 1e-8)
        front = bv[:, 1] > 2.0                                                     # the muzzled part
        before = np.abs(np.linalg.norm(bv[front], axis=1) - 10.0)
        after = np.abs(np.linalg.norm(warped[front], axis=1) - 10.0)
        self.assertLess(np.median(after), 0.25 * np.median(before))                 # back onto the round head
        with self.assertRaises(ValueError):
            B.warp(bv, {k: bl[k] for k in B.LANDMARKS[:3]}, hl)

    def test_jaw_check(self):
        drop = np.array([0.0, 0.0, 0.5, 1.0, 0.01])
        w = np.array([0.0, 0.1, 0.8, 1.0, 0.0])
        c = B.jaw_check(drop, w)
        self.assertEqual(c["moving_vertices"], 2)
        self.assertAlmostEqual(c["jaw_weight_moving"], 0.9)
        self.assertAlmostEqual(c["jaw_weight_still"], 0.033)          # 0, 0.1 and the 0.01 drop (< 2 %)
        self.assertIsNone(B.jaw_check(np.zeros(3), np.zeros(3)))


def esm(path):
    h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)   # noqa: E731
    Z = sfplugin.zs
    recs = [(b"MRPH", h(b"MRPH"), [(b"EDID", Z("HeadM")), (b"TCMP", Z("Meshes\\Morphs\\Human\\Male\\Chargen\\Head")),
                                   (b"BMPP", Z("Meshes\\Actors\\Human\\Regions.txt"))], 0x700),
            (b"MRPH", h(b"MRPH"), [(b"EDID", Z("Hair")), (b"BMPP", Z("Meshes\\Actors\\Human\\Regions.txt"))], 0x701),
            (b"MRPH", h(b"MRPH"), [(b"EDID", Z("Coat"))], 0x702),
            (b"HDPT", h(b"HDPT"), [(b"EDID", Z("Human_Male_Head")), (b"PNAM", struct.pack("<I", 1)),
                                   (b"MNAM", struct.pack("<I", 0x700))], 0x510)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))


class RecordTests(unittest.TestCase):
    def test_morph_records(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Starfield.esm")
            esm(p)
            r = B.morph_records(p)
        self.assertEqual(r["morph_records"], 3)
        self.assertEqual(r["bone_morph_files"], {"Meshes\\Actors\\Human\\Regions.txt": 2})
        self.assertEqual(r["head_parts"]["Human_Male_Head"]["BMPP"], "Meshes\\Actors\\Human\\Regions.txt")
        self.assertIsNone(r["head_parts"].get("Human_Female_Head"))


class MainTests(unittest.TestCase):
    def test_main_with_stubs(self):
        hv, hf, he = head()
        bv, bf, be = head(muzzle=1.6)
        sf_v = hv / 70.0
        bones = ["C_Head", "faceBone_C_Jaw"]
        Wsf = np.zeros((len(sf_v), 2))
        Wsf[:, 1] = (sf_v[:, 2] < -0.003).astype(float)                       # below the mouth: the jaw
        Wsf[:, 0] = 1 - Wsf[:, 1]
        sfhead = types.SimpleNamespace(vertices=sf_v, triangles=hf, model_xf=np.eye(4), bones=bones, weights=Wsf)
        fake_rp = types.SimpleNamespace(race_transfer=lambda sky, sf, female, smooth, ff: (
            sfhead, None, None, (1 / 70.0, np.eye(3), np.zeros(3), 0.008), {}, {"alignment": {"rms_m": 0.008}}))
        aah = np.zeros_like(bv)
        aah[bv[:, 2] < -0.4 * 10, 2] = -1.0                                    # the jaw drops
        import face_fit
        files = {}

        def read_any(p, sky):
            files[p] = files.get(p, 0) + 1
            if p.endswith("chargen.tri"):
                return b"chargen"
            if p.endswith(".tri"):
                return b"expr"
            if "eyes" in p:
                return b"heyes" if p.endswith(("eyesmale.nif", "eyesfemale.nif")) else b"beyes"
            if "tail" in p:
                raise SystemExit("no tail here")
            if "skeleton" in p:
                return b"beast skeleton" if "beast" in p else b"human skeleton"
            return b"human" if p == face_fit.SKY_HEADS[False] or p == face_fit.SKY_HEADS[True] else b"beast"
        stubs = {"skyrim_head": lambda d, model=False: hv if d == b"human" else bv,
                 "skyrim_head_triangles": lambda d: hf if d == b"human" else bf,
                 "skyrim_head_matrix": lambda d: np.eye(4)}
        saved_ff = {k: getattr(face_fit, k) for k in stubs}
        saved = (sys.modules.get("race_probe"), face_fit.hkx_to_af.read_any, B.mesh_points, B.read_tri, B.archives,
                 B.morph_records, B.node_names)
        try:
            for k, v in stubs.items():
                setattr(face_fit, k, v)
            sys.modules["race_probe"] = fake_rp
            face_fit.hkx_to_af.read_any = read_any
            B.mesh_points = lambda d: ((he if d == b"heyes" else be), None)
            B.read_tri = lambda ff, sky, p, deltas=True: (
                {"morphs": [{"name": "NoseLong"}, {"name": "JawWide"}]} if p.endswith("chargen.tri")
                else {"morphs": [{"name": "Aah", "deltas": aah}, {"name": "BlinkLeft", "deltas": aah * 0}]})
            B.archives = lambda d: None
            B.morph_records = lambda esm: {"bone_morph_files": {}}
            B.node_names = lambda d: ["NPC Root", "NPC Head"] + (["TailBone01"] if b"beast" in d else [])
            with tempfile.TemporaryDirectory() as d:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(B.main(["--skyrim-data", d, "--starfield", d, "--out", d]), 0)
                with open(os.path.join(d, "beast_probe.json")) as fh:
                    rep = json.load(fh)
                self.assertTrue(os.path.exists(os.path.join(d, "beast_view.html")))
        finally:
            for k, v in saved_ff.items():
                setattr(face_fit, k, v)
            if saved[0] is None:
                sys.modules.pop("race_probe", None)
            else:
                sys.modules["race_probe"] = saved[0]
            (face_fit.hkx_to_af.read_any, B.mesh_points, B.read_tri, B.archives, B.morph_records,
             B.node_names) = saved[1:]
        k = rep["male"]["KhajiitRace"]
        self.assertNotIn("error", k)
        self.assertEqual(rep["male"]["starfield_jaw_bones"], ["faceBone_C_Jaw"])
        self.assertEqual(len(k["landmarks_used"]), len(B.LANDMARKS))
        self.assertGreater(k["jaw_check"]["jaw_weight_moving"], 0.8)        # Aah's vertices land on the jaw
        self.assertLess(k["jaw_check"]["jaw_weight_still"], 0.2)
        self.assertEqual(k["sliders"]["distinct"], 2)
        self.assertIn("error", k["tail"])
        self.assertEqual(rep["male"]["skeleton"]["beast_only"], ["TailBone01"])


if __name__ == "__main__":
    unittest.main()
