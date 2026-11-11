"""scripts/npc/race_probe.py on synthetic data: region masks from phenotype x region morph keys (other keys apart,
the 128-key budget), per-region move statistics, HumanRace references in a plugin (GetIsRace conditions by parameter,
other fields, a compressed record), and the viewer page."""
import os
import struct
import sys
import tempfile
import unittest
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_fo4land import grup, rec  # noqa: E402
from fo4sf import sfmorph  # noqa: E402
import race_probe as P  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731


def ctda(func, p1, p2=0, value=0):
    return struct.pack("<B3xIHxxII", 0, value, func, p1, p2) + bytes(12)


class RaceProbeTests(unittest.TestCase):
    def test_regions(self):
        keys = ["male_eu_md2_Nose", "male_eu_md2_Ears", "male_af_md1_Nose", "Overweight"]
        deltas = {"male_eu_md2_Nose": {0: (0.01, 0, 0), 1: (0, 0.002, 0)}, "male_eu_md2_Ears": {3: (0, 0, 0.01),
                                                                                                 1: (0, 0, 0.001)},
                  "male_af_md1_Nose": {2: (0.001, 0, 0)}, "Overweight": {0: (0.01, 0, 0), 4: (0.01, 0, 0)}}
        m = sfmorph.parse(sfmorph.build(5, keys, deltas))
        regions, phenos, other = P.morph_regions(m)
        self.assertEqual({k: sorted(v) for k, v in regions.items()}, {"Nose": [0, 1, 2], "Ears": [1, 3]})
        self.assertEqual(dict(phenos), {"male_eu_md2": ["Nose", "Ears"], "male_af_md1": ["Nose"]})
        self.assertEqual(other, ["Overweight"])
        self.assertEqual(P.region_overlap(regions), {"Ears&Nose": 1})
        disp = np.zeros((6, 3))
        disp[3] = (0, 0, 0.02)
        disp[5] = (0.01, 0, 0)                                      # vertex 5 in no region
        r = P.per_region(disp, {k: np.array(sorted(v)) for k, v in regions.items()}, 6)
        self.assertEqual((r["Ears"]["max_m"], r["Nose"]["max_m"], r["outside"]["max_m"]), (0.02, 0.0, 0.01))
        self.assertAlmostEqual(r["outside"]["share_of_total"], 0.333, places=3)

    def test_human_race_refs(self):
        with tempfile.TemporaryDirectory() as d:
            hr = 0x3CDC
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.0, 0, 0x800))])
            race = rec(b"RACE", hr, [(b"EDID", Z("HumanRace"))])
            info = [rec(b"INFO", 0x10 + i, [(b"EDID", Z(f"I{i}")), (b"CTDA", ctda(69, hr))]) for i in range(3)]
            info.append(rec(b"INFO", 0x20, [(b"EDID", Z("Other")), (b"CTDA", ctda(69, 0x999))]))
            arma = rec(b"ARMA", 0x30, [(b"EDID", Z("AA")), (b"RNAM", struct.pack("<I", hr))])
            body = [(b"EDID", Z("Packed")), (b"CTDA", ctda(254, 0, hr))]
            data = b"".join(s + struct.pack("<H", len(x)) + x for s, x in body)
            comp = struct.pack("<I", len(data)) + zlib.compress(data)
            crec = b"PERK" + struct.pack("<IIIIH2x", len(comp), 0x40000, 0x40, 0, 0) + comp
            path = os.path.join(d, "x.esm")
            with open(path, "wb") as fh:
                fh.write(tes4 + grup(b"RACE", 0, [race]) + grup(b"INFO", 0, info) + grup(b"ARMA", 0, [arma])
                         + grup(b"PERK", 0, [crec]))
            r = P.human_race_refs(path)
            self.assertEqual(r["records"], {"INFO": 3, "ARMA": 1, "PERK": 1})
            self.assertEqual(r["conditions_get_is_race"], 3)
            self.assertIn({"record": "PERK", "function": 254, "where": "param2", "count": 1}, r["conditions"])
            self.assertEqual(r["fields"], [{"record": "ARMA", "field": "RNAM", "count": 1}])

    def test_transfer(self):
        # the Starfield head stores its mesh x-up (C_Head's frame); in model space it is the Skyrim head / 70 (metres).
        # The race morph (+7 units up at the crown vertex) must arrive as +0.1 m along the LOCAL x axis.
        from test_race_survey import tri
        import types
        from fo4sf import facefit
        rng = np.random.default_rng(1)
        base = rng.normal(size=(300, 3)) * [60, 70, 80] + [0, 0, 100]
        base[-1] = (0, 0, 200)
        delta = np.zeros((300, 3), int)
        delta[-1] = (0, 0, 7)
        files = {"races": tri(base, [("HighElfRace", 1.0, delta)]), "head": tri(base)}
        node = np.eye(4)
        node[:3, :3] = [[0, 0, -1], [0, 1, 0], [1, 0, 0]]      # columns: local x (up) -> model z, local z -> model -x
        node[:3, 3] = (0, 0, 1.5)

        class H:
            vertices = facefit.apply4(np.linalg.inv(node), base / 70.0)
            triangles = np.array([[0, 1, 2]])
            model_xf = node
        ff = types.SimpleNamespace(
            starfield_head=lambda sf, female: (H(), {}), SKY_HEADS={False: "nif", True: "nif"},
            skyrim_head=lambda d, model=False: base, skyrim_head_matrix=lambda d: np.eye(4),
            head_alignment=lambda head, d, legacy=False: (base, facefit.align_to_local(base, head.vertices,
                                                                                         head.model_xf), True),
            hkx_to_af=types.SimpleNamespace(read_any=lambda p, sky: files["races"] if "races" in p else
                                            files["head"] if p.endswith(".tri") else b""))
        head, b, races, al, out, rep = P.race_transfer(None, "", False, 0, ff, method="nearest")
        self.assertEqual(rep["transfer"], "nearest")
        self.assertLess(rep["alignment"]["rms_m"], 1e-6)
        self.assertTrue(rep["alignment"]["model_space"])
        np.testing.assert_allclose(out["HighElfRace"][-1], (0.1, 0, 0), atol=1e-6)    # up = local +x
        self.assertLess(float(np.abs(out["HighElfRace"][:-1]).max()), 1e-6)
        self.assertAlmostEqual(rep["races"]["HighElfRace"]["skyrim_max_m"], 0.1, places=5)

    def test_transfer_surface(self):
        # the same set-up on a closed mesh (a UV sphere head): the surface transfer, through the node rotation
        from test_race_survey import tri
        import types
        from fo4sf import facefit
        nu, nv = 24, 12
        th, ph = np.meshgrid(np.linspace(0, 2 * np.pi, nu, endpoint=False), np.linspace(0, np.pi, nv + 1)[1:-1])
        ring = np.stack([np.sin(ph) * np.cos(th), np.sin(ph) * np.sin(th), np.cos(ph)], -1).reshape(-1, 3)
        unit = np.concatenate([[(0, 0, 1)], ring, [(0, 0, -1)]])
        tris = []
        for i in range(nu):
            j = (i + 1) % nu
            tris.append((0, 1 + j, 1 + i))
            for r in range(nv - 2):
                a, b, c, d = 1 + r * nu + i, 1 + r * nu + j, 1 + (r + 1) * nu + i, 1 + (r + 1) * nu + j
                tris += [(a, b, d), (a, d, c)]
            last = 1 + (nv - 2) * nu
            tris.append((last + i, last + j, len(unit) - 1))
        base = unit * [60, 70, 80] + [0, 0, 120]
        delta = np.zeros((len(base), 3), int)
        delta[0] = (0, 0, 7)                                  # the crown up 7 units
        files = {"races": tri(base, [("HighElfRace", 1.0, delta)], tris=tris), "head": tri(base, tris=tris)}
        node = np.eye(4)
        node[:3, :3] = [[0, 0, -1], [0, 1, 0], [1, 0, 0]]
        node[:3, 3] = (0, 0, 1.5)

        class H:
            vertices = facefit.apply4(np.linalg.inv(node), base / 70.0)
            triangles = np.array(tris)
            model_xf = node
        ff = types.SimpleNamespace(
            starfield_head=lambda sf, female: (H(), {}), SKY_HEADS={False: "nif", True: "nif"},
            skyrim_head=lambda d, model=False: base, skyrim_head_matrix=lambda d: np.eye(4),
            head_alignment=lambda head, d, legacy=False: (base, facefit.align_to_local(base, head.vertices,
                                                                                         head.model_xf), True),
            hkx_to_af=types.SimpleNamespace(read_any=lambda p, sky: files["races"] if "races" in p else
                                            files["head"] if p.endswith(".tri") else b"",
                                            vanilla_file=lambda p, sf: (_ for _ in ()).throw(SystemExit("none"))))
        head, b, races, al, out, rep = P.race_transfer(None, "", False, 0, ff)
        self.assertNotIn("ears", rep)                           # the ear fit is opt-in (2026-11-10)
        rep_e = P.race_transfer(None, "", False, 0, ff, ears=True)[5]
        self.assertIn("error", rep_e["ears"])                   # no head morph to find the ears in: skipped
        dump = P.geometry_dump(head, b, races, al, out, {"Ears": np.array([1, 2])})
        self.assertEqual(dump["sf_v"].shape, (len(H.vertices), 3))
        self.assertEqual(dump["sky_delta_HighElfRace"].shape, (len(base), 3))
        self.assertEqual(list(dump["sf_region_Ears"]), [1, 2])
        np.testing.assert_allclose(dump["model_xf"], node)
        self.assertEqual(rep["transfer"], "surface")
        self.assertIsNone(rep["correspondence"]["mouth"])      # no mouth on a sphere
        np.testing.assert_allclose(out["HighElfRace"][0], (0.1, 0, 0), atol=1e-6)      # up = local +x
        self.assertLess(float(np.abs(out["HighElfRace"][nu + 1:]).max()), 1e-6)       # below the first ring: still

    def test_ear_fit(self):
        """2026-11-10 (owner: the female Orc's ear a flat blade): Skyrim's ear 15 mm off Starfield's is moved onto it,
        the face far from the ear stays."""
        g = np.linspace(-0.02, 0.02, 9)
        ear = np.array([(0.09 + 8 * (y * y + z * z), y, z) for y in g for z in g])   # a cupped flap off the right
        face = np.array([(x, 0.09, z) for x in np.linspace(-0.04, 0.04, 9) for z in g] +
                        [(-0.09, y, z) for y in g for z in g])           # and the left side of the head
        dst = np.concatenate([ear, face])
        ears = np.arange(len(ear))
        src = np.concatenate([ear + (0.012, -0.006, 0.004), face])
        fits, rep = P.ear_fit(src, dst, ears, np.eye(4))
        self.assertEqual(rep["left"], "no ear vertices")
        self.assertLess(rep["right"]["gap_m"][1], 0.002)
        self.assertGreater(rep["right"]["gap_m"][0], 0.008)
        moved = P.warp(src, fits)
        near = np.linalg.norm(moved[:len(ear)][:, None, :] - ear[None, :, :], axis=2).min(1)
        self.assertLess(float(np.median(near)), 0.0015)                 # on the ear (5 mm grid: it may slide)
        np.testing.assert_allclose(moved[len(ear):], face)                # 9 cm away: untouched
        vec = P.warp(np.tile((0.0, 0.0, 0.01), (len(src), 1)), fits, vectors=True)
        np.testing.assert_allclose(np.linalg.norm(vec[:len(ear)], axis=1), 0.01, atol=1e-3)   # turned, not moved

    def test_viewer(self):
        class H:
            vertices = np.random.rand(4, 3)
            triangles = np.array([[0, 1, 2], [1, 2, 3]])
        races = {"faces": np.array([[0, 1, 2]]), "morphs": [{"name": "OrcRace", "deltas": np.ones((3, 3))}]}
        al = (1.0, np.eye(3), np.zeros(3), 0.0)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "v.html")
            P.viewer(p, {"male": (H(), np.zeros((3, 3)), races, al, {"OrcRace": np.zeros((4, 3))})})
            with open(p, encoding="utf-8") as fh:
                t = fh.read()
            self.assertIn('"names": ["OrcRace"]', t)
            self.assertNotIn("__DATA__", t)


if __name__ == "__main__":
    unittest.main()
