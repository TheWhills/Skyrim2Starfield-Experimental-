"""scripts/npc/face_fit.py end to end on synthetic games: records, sample, race dials, fit, report, test plugin.
Head geometry comes from the synthetic heads of test_facefit (the NIF / .mesh loaders have their own tests)."""
import json
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import facefit, sfplugin  # noqa: E402
import face_fit as S  # noqa: E402
import test_facefit as T  # noqa: E402
import test_skyrimnpc as TN  # noqa: E402

TRUTH = {"HousecarlWhiterun": {40: 0.7, 60: -0.3}, "Ysolda": {50: 0.5}}


def skyrim_esm(path):
    hdr = struct.pack("<4sIII", b"NPC_", 0, 0, 0) + bytes(8)
    rh = struct.pack("<4sIII", b"RACE", 0, 0, 0) + bytes(8)
    recs = [(b"RACE", rh, [(b"EDID", b"NordRace\0")], 0x13746),
            (b"NPC_", hdr, TN.npc_subs("HousecarlWhiterun"), 0xA2C94),
            (b"NPC_", hdr, TN.npc_subs("Ysolda"), 0x13BAB),
            (b"NPC_", hdr, TN.npc_subs("Templated", template=0xA2C94, tflags=1), 0x99999)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 1.71, "form_version": 44}, masters=()))


def starfield_esm(path):
    h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)   # noqa: E731
    race = [(b"EDID", b"HumanRace\0"), (b"MNAM", b""), (b"FDSI", struct.pack("<I", 40)), (b"FDSL", b"x\0"),
            (b"FDSI", struct.pack("<I", 60)), (b"FNAM", b""), (b"FDSI", struct.pack("<I", 41))]
    tpl = [(b"EDID", b"SettlerM01\0"), (b"ACBS", bytes(24)), (b"RNAM", struct.pack("<I", 0x3CDB)),
           (b"MRSV", bytes(20)), (b"FMSI", struct.pack("<I", 41)), (b"FMRS", struct.pack("<f", 0.9)),
           (b"FMRI", struct.pack("<I", 2)), (b"FMRG", b"Nose\0"), (b"FMRS", struct.pack("<f", 0.5)),
           (b"ATTX", b"\0"), (b"HCOL", b"Brown\0")]
    recs = [(b"RACE", h(b"RACE"), race, 0x3CDB), (b"NPC_", h(b"NPC_"), tpl, 0x10001)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))


class FaceFitScriptTests(unittest.TestCase):
    def test_end_to_end(self):
        sliders = facefit.load_regions(json.dumps(T.REGIONS))
        sf_head = T.make_head(T.head_points())
        sky_base = T.head_points(3000, seed=5) * 70.0
        sky_head = T.make_head(sky_base / 70.0)
        faces = {k: facefit.deform(sky_head, sliders, v) * 70.0 for k, v in TRUTH.items()}
        ids = {"0A2C94": "HousecarlWhiterun", "013BAB": "Ysolda"}

        def read_any(path, _sky=None):
            low = path.lower()
            if "facegeom" in low:
                return ("face:" + ids[path[-10:-4].upper()]).encode()
            return b"base"

        def skyrim_head(data):
            d = data.decode()
            return sky_base.copy() if d == "base" else faces[d.split(":")[1]]

        saved = (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head, S.bsa.SkyrimArchives)
        S.hkx_to_af.read_any = read_any
        S.hkx_to_af.vanilla_file = lambda p, d: (json.dumps(T.REGIONS).encode(), p)
        S.skyrim_head = skyrim_head
        S.starfield_head = lambda d, f, h=None: (sf_head, {"face_bones": 6})
        S.bsa.SkyrimArchives = lambda d: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sky = os.path.join(tmp, "sky")
                sf = os.path.join(tmp, "sf")
                os.makedirs(sky)
                os.makedirs(os.path.join(sf, "Data"))
                skyrim_esm(os.path.join(sky, "Skyrim.esm"))
                starfield_esm(os.path.join(sf, "Data", "Starfield.esm"))
                out = os.path.join(tmp, "out")
                self.assertEqual(S.main(["--skyrim-data", sky, "--starfield", sf, "--out", out, "--count", "2",
                                         "--test-plugin"]), 0)
                with open(os.path.join(out, "faces.json"), encoding="utf-8") as fh:
                    rep = json.load(fh)
                rows = {r["edid"]: r for r in rep["npcs"]}
                self.assertEqual(sorted(rows), ["HousecarlWhiterun", "Ysolda"])          # the template user is not
                for edid, truth in TRUTH.items():
                    got = {int(k): v for k, v in rows[edid]["dials"].items()}
                    for k, v in truth.items():
                        self.assertAlmostEqual(got.get(k, 0.0), v, delta=0.15, msg=(edid, got))
                    self.assertLess(rows[edid]["rms_after"], rows[edid]["rms_before"])
                self.assertEqual(rep["sexes"]["male"]["race_dials"], {"count": 2, "also_slider_ids": 2,
                                                                     "slider_ids_not_dials": 4})
                plugin = os.path.join(out, S.PLUGIN)
                recs = sfplugin.records(plugin, [b"NPC_"])
                self.assertEqual(len(recs), 2)
                subs = dict((sfplugin.edid(s), s) for _t, _h, s, _f in recs)["S2SFace_HousecarlWhiterun"]
                sigs = [sg for sg, _d in subs]
                self.assertNotIn(b"FMRI", sigs)                                          # phenotype cleared
                self.assertNotIn(b"FMRG", sigs)
                dials = [struct.unpack("<I", d)[0] for sg, d in subs if sg == b"FMSI"]
                self.assertEqual(dials, sorted(int(k) for k in rows["HousecarlWhiterun"]["dials"]))
                self.assertLess(sigs.index(b"MRSV"), sigs.index(b"FMSI"))                # where the face data was
                self.assertLess(sigs.index(b"FMSI"), sigs.index(b"ATTX"))
                self.assertEqual(dict(subs)[b"FULL"], b"HousecarlWhiterun (S2S)\0")
                self.assertIn("console", rows["HousecarlWhiterun"]["test_npc"])
        finally:
            (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head,
             S.bsa.SkyrimArchives) = saved


if __name__ == "__main__":
    unittest.main()
