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
        head, b, races, al, out, rep = P.race_transfer(None, "", False, 0, ff)
        self.assertLess(rep["alignment"]["rms_m"], 1e-6)
        self.assertTrue(rep["alignment"]["model_space"])
        np.testing.assert_allclose(out["HighElfRace"][-1], (0.1, 0, 0), atol=1e-6)    # up = local +x
        self.assertLess(float(np.abs(out["HighElfRace"][:-1]).max()), 1e-6)
        self.assertAlmostEqual(rep["races"]["HighElfRace"]["skyrim_max_m"], 0.1, places=5)

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
