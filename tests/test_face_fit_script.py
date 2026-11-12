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
    quest = [(b"EDID", b"QuestGuyM\0"), (b"VMAD", b"script"), (b"QSTA", struct.pack("<I", 5))] + tpl[1:]
    recs = [(b"RACE", h(b"RACE"), race, 0x3CDB), (b"NPC_", h(b"NPC_"), quest, 0x10000),
            (b"NPC_", h(b"NPC_"), tpl, 0x10001),
            (b"OTFT", h(b"OTFT"), [(b"EDID", b"SomeOutfit\0"), (b"INAM", struct.pack("<I", 0x10001))], 0x20000)]
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

        def skyrim_head(data, model=False):
            d = data.decode()
            return sky_base.copy() if d == "base" else faces[d.split(":")[1]]

        saved = (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head, S.bsa.SkyrimArchives)
        S.hkx_to_af.read_any = read_any
        S.hkx_to_af.vanilla_file = lambda p, d: (json.dumps(T.REGIONS).encode(), p)
        S.skyrim_head = skyrim_head
        S.starfield_head = lambda d, f, h=None, r=None: (sf_head, {"face_bones": 6})
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
                                         "--test-plugin", "--control-npcs"]), 0)
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
                self.assertEqual(len(recs), 4)                                   # + the two control copies
                by = dict((sfplugin.edid(s), s) for _t, _h, s, _f in recs)
                subs = by["S2SFace_HousecarlWhiterun"]
                ctl = by["S2SFaceControl_HousecarlWhiterun"]
                self.assertIn((b"FMRG", b"Nose\0"), ctl)                        # the template's face data kept
                self.assertIn("control_npc", rows["HousecarlWhiterun"])
                sigs = [sg for sg, _d in subs]
                self.assertNotIn(b"FMRI", sigs)                                          # phenotype cleared
                self.assertNotIn(b"FMRG", sigs)
                dials = [struct.unpack("<I", d)[0] for sg, d in subs if sg == b"FMSI"]
                self.assertEqual(dials, sorted(int(k) for k in rows["HousecarlWhiterun"]["dials"]))
                self.assertLess(sigs.index(b"MRSV"), sigs.index(b"FMSI"))                # where the face data was
                self.assertLess(sigs.index(b"FMSI"), sigs.index(b"ATTX"))
                self.assertEqual(dict(subs)[b"FULL"], b"HousecarlWhiterun (S2S)\0")
                self.assertIn("console", rows["HousecarlWhiterun"]["test_npc"])
                self.assertEqual(rows["HousecarlWhiterun"]["test_npc"]["template_console"].split()[1], "10001")
                self.assertEqual(rows["HousecarlWhiterun"]["test_npc"]["template"], "SettlerM01")   # the plain one
                self.assertNotIn(b"VMAD", sigs)
                # an empty outfit of our own as default and space outfit (2026-11-06: spacesuits without one)
                otft = sfplugin.records(plugin, [b"OTFT"])
                self.assertEqual([(sfplugin.edid(o[2]), dict(o[2])[b"INAM"]) for o in otft], [("S2S_NoOutfit", b"")])
                self.assertEqual(dict(subs)[b"DOFT"], struct.pack("<I", otft[0][3]))
                self.assertEqual(dict(subs)[b"SOFT"], struct.pack("<I", otft[0][3]))
        finally:
            (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head,
             S.bsa.SkyrimArchives) = saved


def egg_mesh(nu=48, nv=28):
    """test_facefit's egg head as a closed UV-sphere mesh (vertices, triangles): the surface transfer needs triangles."""
    th, ph = np.meshgrid(np.linspace(0, 2 * np.pi, nu, endpoint=False), np.linspace(0, np.pi, nv + 1)[1:-1])
    ring = np.stack([np.sin(ph) * np.cos(th), np.sin(ph) * np.sin(th), np.cos(ph)], -1).reshape(-1, 3)
    p = np.concatenate([[(0, 0, 1)], ring, [(0, 0, -1)]]) * np.array([0.075, 0.1, 0.12])
    nose = np.exp(-((p[:, 0] / 0.012) ** 2 + (p[:, 2] / 0.03) ** 2)) * (p[:, 1] > 0)
    brow = np.exp(-(((p[:, 2] - 0.045) / 0.01) ** 2)) * (p[:, 1] > 0.05) * (np.abs(p[:, 0]) < 0.05)
    p[:, 1] += 0.025 * nose + 0.008 * brow
    tris = []
    for i in range(nu):
        j = (i + 1) % nu
        tris.append((0, 1 + i, 1 + j))
        for r in range(nv - 2):
            a, b, c, d = 1 + r * nu + i, 1 + r * nu + j, 1 + (r + 1) * nu + i, 1 + (r + 1) * nu + j
            tris += [(a, c, d), (a, d, b)]
        last = 1 + (nv - 2) * nu
        tris.append((last + i, len(p) - 1, last + j))
    return p, np.array(tris, int)


class SurfaceTransferTests(unittest.TestCase):
    def test_surface_transfer_recovers_dials(self):
        sliders = facefit.load_regions(json.dumps(T.REGIONS))
        sf_v, sf_t = egg_mesh(64, 36)                       # Starfield: finer
        sky_v, sky_t = egg_mesh(32, 18)                     # Skyrim: coarser, in its units (x 70)
        sf_head = T.make_head(sf_v)
        sf_head.triangles = sf_t
        sky_head = T.make_head(sky_v)
        sky_base = sky_v * 70.0
        faces = {k: facefit.deform(sky_head, sliders, v) * 70.0 for k, v in TRUTH.items()}
        ids = {"0A2C94": "HousecarlWhiterun", "013BAB": "Ysolda"}

        def read_any(path, _sky=None):
            return ("face:" + ids[path[-10:-4].upper()]).encode() if "facegeom" in path.lower() else b"base"
        saved = (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head, S.bsa.SkyrimArchives,
                 S.skyrim_head_triangles)
        S.hkx_to_af.read_any = read_any
        S.hkx_to_af.vanilla_file = lambda p, d: (json.dumps(T.REGIONS).encode(), p)
        S.skyrim_head = lambda data, model=False: (sky_base.copy() if data == b"base"
                                                   else faces[data.decode().split(":")[1]])
        S.skyrim_head_triangles = lambda data: sky_t
        S.starfield_head = lambda d, f, h=None, r=None: (sf_head, {"face_bones": 6})
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
                self.assertEqual(S.main(["--skyrim-data", sky, "--starfield", sf, "--out", out, "--count", "2"]), 0)
                with open(os.path.join(out, "faces.json"), encoding="utf-8") as fh:
                    rep = json.load(fh)
        finally:
            (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head, S.bsa.SkyrimArchives,
             S.skyrim_head_triangles) = saved
        self.assertEqual(rep["sexes"]["male"]["transfer"], "surface (headcorr)")
        self.assertEqual(rep["sexes"]["male"]["correspondence"]["src_triangles"], len(sky_t))
        rows = {r["edid"]: r for r in rep["npcs"]}
        for edid, truth in TRUTH.items():
            got = {int(k): v for k, v in rows[edid]["dials"].items()}
            for k, v in truth.items():
                self.assertAlmostEqual(got.get(k, 0.0), v, delta=0.15, msg=(edid, got))


if __name__ == "__main__":
    unittest.main()


class BodyTests(unittest.TestCase):
    def test_with_body(self):
        import struct as st
        tpl = [(b"EDID", b"T\0"), (b"MWGT", st.pack("<3f", 0.1, 0.8, 0.1)), (b"MRSV", st.pack("<5f", *[0.9] * 5)),
               (b"FMSI", b"\0" * 4)]
        body = [(b"EDID", b"B\0"), (b"MWGT", st.pack("<3f", 0.3, 0.3, 0.4)), (b"MRSV", st.pack("<5f", *[0.5] * 5))]
        out, got = S.with_body(tpl, body)
        self.assertEqual(got, ["MRSV", "MWGT"])
        self.assertEqual([s for s, _d in out], [b"EDID", b"MWGT", b"MRSV", b"FMSI"])        # order kept
        self.assertEqual(dict(out)[b"MWGT"], st.pack("<3f", 0.3, 0.3, 0.4))
        # a field the template lacks is not added (it would land after EDID, out of order)
        out2, got2 = S.with_body([(b"EDID", b"T\0"), (b"MWGT", b"x" * 12)], body)
        self.assertEqual((got2, [s for s, _d in out2]), (["MWGT"], [b"EDID", b"MWGT"]))


class OutfitsPluginTests(unittest.TestCase):
    def test_outfits_by_npc(self):
        import face_fit
        from fo4sf import sfplugin
        hdr = struct.pack("<4sIII", b"OTFT", 0, 0, 0) + bytes(8)
        recs = [(b"OTFT", hdr, [(b"EDID", sfplugin.zs("S2S_Ralof_outfit_Outfit"))], 0x01000809),
                (b"OTFT", hdr, [(b"EDID", sfplugin.zs("Something"))], 0x0100080A)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "S2SArmorTest.esm")
            with open(p, "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}))
            self.assertEqual(face_fit.outfits_by_npc(p, 2), {"ralof": 0x02000809})


class BeardMatchTests(unittest.TestCase):
    def test_rank_picks_the_closest_shape(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
        import beard_match as B
        chin = np.array([[x, 0.1, z] for x in np.linspace(-0.03, 0.03, 7) for z in np.linspace(1.6, 1.64, 5)])
        full = np.array([[x, 0.08, z] for x in np.linspace(-0.07, 0.07, 15) for z in np.linspace(1.58, 1.7, 13)])
        r = B.rank(chin + [0, 0.002, 0], {"Goatee": chin, "FullBeard": full})
        self.assertEqual(r[0][0], "Goatee")
        self.assertLess(r[0][1], 0.005)
        self.assertEqual(B.chamfer(chin, np.zeros((0, 3))), float("inf"))
        self.assertEqual(len(B.sample(full, 50)), 50)


class RaceNpcTests(unittest.TestCase):
    """2026-11-10 (owner: Faendal with the Bosmer head): NPCs of a converted race go on it, and only their own
    features are fitted."""

    def test_race_delta_matches_by_position(self):
        import types
        base_skin = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        tri = {"base": base_skin[[2, 0, 1]], "morphs": [{"name": "WoodElfRace",
                                                          "deltas": np.array([[0, 0, 3], [0, 0, 1], [0, 0, 2]], float)}]}
        saved = (S.skyrim_head, S.skyrim_head_matrix)
        S.skyrim_head = lambda data, model=False: base_skin
        S.skyrim_head_matrix = lambda data: np.diag([1.0, 1.0, -1.0, 1.0])
        try:
            cache = {("tri", False): tri}
            d = S.race_delta(None, False, "WoodElfRace", b"", False, cache)
            self.assertEqual(d[:, 2].tolist(), [1, 2, 3])                 # NIF order, not the .tri's
            dm = S.race_delta(None, False, "WoodElfRace", b"", True, cache)
            self.assertEqual(dm[:, 2].tolist(), [-1, -2, -3])             # into model space
            self.assertIsNone(S.race_delta(None, False, "NordRace", b"", False, cache))
        finally:
            S.skyrim_head, S.skyrim_head_matrix = saved

    def test_converted_races_and_on_race(self):
        Z = lambda t: t.encode() + b"\0"                                                # noqa: E731
        I = lambda v: struct.pack("<I", v)                                              # noqa: E731
        h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)   # noqa: E731
        with tempfile.TemporaryDirectory() as d:
            plug = os.path.join(d, "S2SRaceTest.esm")
            recs = [(b"HDPT", h(b"HDPT"), [(b"EDID", Z(e))], f) for e, f in (
                ("S2S_BosmerRace_male_Head", 0x01000810), ("S2S_BosmerRace_Human_Male_Eyes_M", 0x01000811),
                ("S2S_BosmerRace_Human_Male_Eyes_F", 0x01000812), ("S2S_BosmerRace_Mouth_M", 0x01000813))]
            with open(plug, "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}))
            with open(os.path.join(d, "race_heads.json"), "w") as fh:
                json.dump({"new_races": {"WoodElfRace": {"form_id": "0100080F", "edid": "S2S_BosmerRace"},
                                         "OldRace": {"form_id": "01000900"}}}, fh)
            conv = S.converted_races(plug)
        self.assertEqual(list(conv), ["WoodElfRace"])
        c = conv["WoodElfRace"]
        self.assertEqual((c["name"], c["form_id"], c["head"], c["mouth"]),
                         ("Bosmer", 0x80F, {False: 0x810}, {False: 0x813}))
        self.assertEqual(c["parts"], {False: {"Human_Male_Eyes": 0x811}, True: {"Human_Male_Eyes": 0x812}})
        sf_hdpt = {0x510: (b"HDPT", b"", [(b"EDID", Z("Human_Male_Head")), (b"PNAM", I(1))], 0x510),
                   0x520: (b"HDPT", b"", [(b"EDID", Z("Human_Male_Eyes")), (b"PNAM", I(2))], 0x520),
                   0x530: (b"HDPT", b"", [(b"EDID", Z("Human_Male_Teeth")), (b"PNAM", I(9))], 0x530),
                   0x540: (b"HDPT", b"", [(b"EDID", Z("Hair_X")), (b"PNAM", I(3))], 0x540)}
        ptype = lambda rec: struct.unpack("<I", dict(rec[2])[b"PNAM"])[0]               # noqa: E731
        subs = [(b"RNAM", I(0x347D)), (b"PNAM", I(0x510)), (b"PNAM", I(0x520)), (b"PNAM", I(0x530)),
                (b"PNAM", I(0x540))]
        out, n = S.on_race(subs, c, False, 3, sf_hdpt, ptype)
        self.assertEqual([struct.unpack("<I", d_)[0] for _s, d_ in out],
                         [0x0300080F, 0x03000810, 0x03000811, 0x03000813, 0x540])
        self.assertEqual(n, 3)
        self.assertIsNone(c["tones"])                      # no skin tones in that race_heads.json

    def test_race_skin(self):
        """2026-11-12, owner: a converted NPC always matches its race and skin (Faendal: the Bosmer head with a
        human skin tone). An NPC of a race with tones of its own: STON = the race's first tone + the slot nearest its
        Skyrim skin, no Dermaesthetic layer, its baked face recoloured to that slot's body tone texture."""
        from fo4sf import skintone
        Z = lambda t: t.encode() + b"\0"                                                # noqa: E731
        with tempfile.TemporaryDirectory() as d:
            tex, rep_tex = {}, {}
            for k in range(9):
                rel = f"textures/s2s/races/bosmer/body/male_sk{k}_color.dds"
                path = os.path.join(d, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(skintone.raw_dds(skintone.solid(np.full((4, 4, 4), 255, np.uint8), (200 - 20 * k, 150 - 15 * k, 100 - 10 * k))))
                rep_tex[rel] = [200 - 20 * k, 150 - 15 * k, 100 - 10 * k]
            rep = {"new_races": {"WoodElfRace": {"skin_tones": {"method": "append", "first_index": [27]}}},
                   "skin_tone_textures": {"WoodElfRace": rep_tex}}
            t = S.race_tones(rep, "WoodElfRace", d)
            self.assertEqual(t["first"], 27)
            self.assertEqual(t["ramp"][False][3], [140, 105, 70])
            self.assertIsNone(S.race_tones(rep, "NordRace", d))
            subs = [(b"EDID", Z("x")), (b"TNAM", Z("Dermaesthetic")), (b"QNAM", Z("European_Male_md1_Sk3")),
                    (b"STON", b"\x02"), (b"HCOL", Z("Brown"))]
            out, info, colour = S.race_skin(subs, {"tones": t}, False, [142, 104, 71])
            self.assertEqual(info["slot"], 3)
            self.assertEqual(dict(out)[b"STON"], bytes([30]))
            self.assertNotIn(b"TNAM", dict(out))
            self.assertNotIn(b"QNAM", dict(out))
            face = skintone.raw_dds(skintone.solid(np.full((4, 4, 4), 255, np.uint8), (180, 140, 120)))
            got = skintone.median_colour(skintone.decode_dds(colour(face)))
            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(got, (140, 105, 70))), got)
            # no Skyrim colour: the middle tone; a race without tones: unchanged
            self.assertEqual(S.race_skin(subs, {"tones": t}, False, None)[1]["slot"], 4)
            self.assertEqual(S.race_skin(subs, {"tones": None}, False, [1, 2, 3]), (subs, None, None))
