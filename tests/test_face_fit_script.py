"""scripts/npc/face_fit.py end to end on synthetic games: records, sample, race dials, fit, report, test plugin.
Head geometry comes from the synthetic heads of test_facefit (the NIF / .mesh loaders have their own tests)."""
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

    def test_skyrim_mod_load_order(self):
        """2026-11-19 (children from RS Children mods): --skyrim-mod folders over Skyrim.esm: a mod's override of an
        NPC is the one read; the run records the mods in its fit settings."""
        sliders = facefit.load_regions(json.dumps(T.REGIONS))
        sf_head = T.make_head(T.head_points())
        sky_base = T.head_points(3000, seed=5) * 70.0
        sky_head = T.make_head(sky_base / 70.0)
        faces = {k: facefit.deform(sky_head, sliders, v) * 70.0 for k, v in TRUTH.items()}
        ids = {"0A2C94": "HousecarlWhiterun", "013BAB": "Ysolda"}
        seen = []

        def read_any(path, _sky=None):
            if "facegeom" in path.lower():
                seen.append(path)
                return ("face:" + ids[path[-10:-4].upper()]).encode()
            return b"base"

        def skyrim_head(data, model=False):
            d = data.decode()
            return sky_base.copy() if d == "base" else faces[d.split(":")[1]]

        saved = (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head)
        S.hkx_to_af.read_any = read_any
        S.hkx_to_af.vanilla_file = lambda p, d: (json.dumps(T.REGIONS).encode(), p)
        S.skyrim_head = skyrim_head
        S.starfield_head = lambda d, f, h=None, r=None: (sf_head, {"face_bones": 6})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sky = os.path.join(tmp, "sky")
                sf = os.path.join(tmp, "sf")
                mods = os.path.join(tmp, "mods")
                os.makedirs(sky)
                os.makedirs(os.path.join(sf, "Data"))
                os.makedirs(os.path.join(mods, "Kids"))
                skyrim_esm(os.path.join(sky, "Skyrim.esm"))
                starfield_esm(os.path.join(sf, "Data", "Starfield.esm"))
                ys = [r for r in sfplugin.records(os.path.join(sky, "Skyrim.esm"), [b"NPC_"])
                      if sfplugin.edid(r[2]) == "Ysolda"]
                over = [(t, h, sfplugin.edit(sb, {b"EDID": b"YsoldaKid\0"}), f) for t, h, sb, f in ys]
                with open(os.path.join(mods, "Kids", "Kids.esp"), "wb") as fh:
                    fh.write(sfplugin.build(over, {"hedr_version": 1.71, "form_version": 44}, masters=("Skyrim.esm",)))
                out = os.path.join(tmp, "out")
                self.assertEqual(S.main(["--skyrim-data", sky, "--starfield", sf, "--out", out, "--npc", "YsoldaKid",
                                         "--skyrim-mods-dir", mods, "--skyrim-mod", "Kids"]), 0)
                with open(os.path.join(out, "faces.json"), encoding="utf-8") as fh:
                    rep = json.load(fh)
                self.assertEqual([r["edid"] for r in rep["npcs"]], ["YsoldaKid"])
                self.assertTrue(any("skyrim.esm" in p.lower() and p.upper().endswith("00013BAB.NIF") for p in seen))
                with open(os.path.join(out, S.FIT_CACHE), encoding="utf-8") as fh:
                    cache = json.load(fh)
                self.assertIn("ysoldakid", cache)
        finally:
            (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head) = saved


class ElderTemplateTests(unittest.TestCase):
    def test_pick_elder_template(self):
        """2026-11-13 (owner: Elder NPCs should look old): a plain european old-skin NPC with the most wrinkle accents
        and no one-person layers (scars, make-up, dirt)."""
        I = lambda v: struct.pack("<I", v)                                          # noqa: E731
        Z = lambda t: t.encode() + b"\0"                                            # noqa: E731

        def npc(fid, edid, derma, layers=(), female=True, extra=()):
            subs = [(b"EDID", Z(edid)), (b"ACBS", I(1 if female else 0) + bytes(12)), (b"RNAM", I(0x347D)),
                    (b"FMSI", b""), (b"VTCK", I(1)), (b"TNAM", Z("Dermaesthetic")), (b"QNAM", Z(derma)),
                    (b"INTV", I(64))]
            for n, t, i in layers:
                subs += [(b"TNAM", Z(n)), (b"QNAM", Z(t)), (b"INTV", I(i))]
            return (b"NPC_", b"", subs + list(extra), fid)
        recs = [npc(1, "Young", "European_Female_md2_Sk1"),
                npc(2, "OldScarred", "European_Female_ol1_Sk2", [("Accents1", "Accents_Fullface_Wrinkles", 60),
                                                                 ("Scars", "Scar_X", 30)]),
                npc(3, "OldLight", "European_Female_ol1_Sk2", [("Accents1", "Accents_CrowsFeet", 20)]),
                npc(4, "OldStrong", "European_Female_ol1_Sk3", [("Accents1", "Accents_Fullface_Wrinkles", 40),
                                                                ("Accents2", "Accents_RoughFace_Dark", 30)]),
                npc(5, "OldAfrican", "African_Female_ol1_Sk8", [("Accents1", "Accents_Fullface_Wrinkles", 99)]),
                npc(6, "OldMale", "European_Male_ol1_Sk1", [("Accents1", "Accents_Fullface_Wrinkles", 99)], False),
                npc(7, "OldScripted", "European_Female_ol1_Sk1", [("Accents1", "Accents_Fullface_Wrinkles", 99)],
                    extra=[(b"VMAD", b"x")])]
        self.assertEqual(S.pick_elder_template(recs, 0x347D, True)[3], 4)
        self.assertEqual(S.pick_elder_template(recs, 0x347D, False)[3], 6)
        self.assertEqual(S.pick_elder_template(recs, 0x347D, True, baked={3})[3], 3)
        self.assertIsNone(S.pick_elder_template(recs[:1], 0x347D, True))
        self.assertEqual(S.face_layers(recs[3][2])[1], ("Accents1", "Accents_Fullface_Wrinkles", 40))


class GenericTemplateTests(unittest.TestCase):
    def test_one_template_per_sex(self):
        """2026-11-12 (owner: Faendal on another template than the others): every NPC of a sex copies the generic
        template when the game has it; --template-by-tone the old pick (the plain SettlerM01 here)."""
        sliders = facefit.load_regions(json.dumps(T.REGIONS))
        sf_head = T.make_head(T.head_points())
        sky_base = T.head_points(3000, seed=5) * 70.0
        sky_head = T.make_head(sky_base / 70.0)
        faces = {k: facefit.deform(sky_head, sliders, v) * 70.0 for k, v in TRUTH.items()}
        ids = {"0A2C94": "HousecarlWhiterun", "013BAB": "Ysolda"}
        saved = (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head, S.bsa.SkyrimArchives,
                 S.GENERIC_TEMPLATE)
        S.hkx_to_af.read_any = lambda p, _s=None: (("face:" + ids[p[-10:-4].upper()]).encode()
                                                   if "facegeom" in p.lower() else b"base")
        S.hkx_to_af.vanilla_file = lambda p, d: (json.dumps(T.REGIONS).encode(), p)
        S.skyrim_head = lambda d, model=False: sky_base.copy() if d == b"base" else faces[d.decode().split(":")[1]]
        S.starfield_head = lambda d, f, h=None, r=None: (sf_head, {"face_bones": 6})
        S.bsa.SkyrimArchives = lambda d: None
        S.GENERIC_TEMPLATE = ("QuestGuyM", "NoSuchFemale")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sky, sf, out = (os.path.join(tmp, x) for x in ("sky", "sf", "out"))
                os.makedirs(sky)
                os.makedirs(os.path.join(sf, "Data"))
                skyrim_esm(os.path.join(sky, "Skyrim.esm"))
                starfield_esm(os.path.join(sf, "Data", "Starfield.esm"))

                def run(*extra):
                    with mock.patch("builtins.print"):
                        S.main(["--skyrim-data", sky, "--starfield", sf, "--out", out, "--npc", "HousecarlWhiterun",
                                "--test-plugin", "--refit"] + list(extra))
                    with open(os.path.join(out, "faces.json"), encoding="utf-8") as fh:
                        return json.load(fh)["npcs"][0]["test_npc"]["template"]
                self.assertEqual(run(), "QuestGuyM")
                self.assertEqual(run("--template-by-tone"), "SettlerM01")
        finally:
            (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head, S.bsa.SkyrimArchives,
             S.GENERIC_TEMPLATE) = saved


class FitCacheTests(unittest.TestCase):
    def test_unchanged_npcs_reused(self):
        """2026-11-12 (owner: an NPC that changed is the only one rebuilt): a second run reuses every fit (no head
        setup at all) and still writes the plugin; a changed FaceGen head refits that NPC only; --refit refits all."""
        sliders = facefit.load_regions(json.dumps(T.REGIONS))
        sf_head = T.make_head(T.head_points())
        sky_base = T.head_points(3000, seed=5) * 70.0
        sky_head = T.make_head(sky_base / 70.0)
        faces = {k: facefit.deform(sky_head, sliders, v) * 70.0 for k, v in TRUTH.items()}
        ids = {"0A2C94": "HousecarlWhiterun", "013BAB": "Ysolda"}
        version = {"Ysolda": "1"}
        setups = []

        def read_any(path, _sky=None):
            if "facegeom" in path.lower():
                e = ids[path[-10:-4].upper()]
                return f"face:{e}:{version.get(e, '1')}".encode()
            return b"base"

        def skyrim_head(data, model=False):
            d = data.decode()
            return sky_base.copy() if d == "base" else faces[d.split(":")[1]]

        def starfield_head(d, f, h=None, r=None):
            setups.append(f)
            return sf_head, {"face_bones": 6}
        saved = (S.hkx_to_af.read_any, S.hkx_to_af.vanilla_file, S.skyrim_head, S.starfield_head, S.bsa.SkyrimArchives)
        S.hkx_to_af.read_any = read_any
        S.hkx_to_af.vanilla_file = lambda p, d: (json.dumps(T.REGIONS).encode(), p)
        S.skyrim_head = skyrim_head
        S.starfield_head = starfield_head
        S.bsa.SkyrimArchives = lambda d: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sky, sf, out = (os.path.join(tmp, x) for x in ("sky", "sf", "out"))
                os.makedirs(sky)
                os.makedirs(os.path.join(sf, "Data"))
                skyrim_esm(os.path.join(sky, "Skyrim.esm"))
                starfield_esm(os.path.join(sf, "Data", "Starfield.esm"))

                def run(*extra):
                    with mock.patch("builtins.print"):
                        self.assertEqual(S.main(["--skyrim-data", sky, "--starfield", sf, "--out", out,
                                                 "--npc", "HousecarlWhiterun", "--npc", "Ysolda", "--test-plugin"]
                                                + list(extra)), 0)
                    with open(os.path.join(out, "faces.json"), encoding="utf-8") as fh:
                        return {r["edid"]: r for r in json.load(fh)["npcs"]}
                first = run()
                self.assertEqual(len(setups), 1)
                os.remove(os.path.join(out, S.PLUGIN))
                second = run()
                self.assertEqual(len(setups), 1)                                    # no head setup at all
                self.assertTrue(all(r.get("fit_reused") for r in second.values()))
                for e in TRUTH:
                    self.assertEqual(second[e]["dials"], first[e]["dials"])
                self.assertTrue(os.path.isfile(os.path.join(out, S.PLUGIN)))        # the plugin is written anyway
                version["Ysolda"] = "2"                                             # her FaceGen head changed
                third = run()
                self.assertEqual((third["Ysolda"].get("fit_reused"), third["HousecarlWhiterun"].get("fit_reused")),
                                 (None, True))
                fourth = run("--refit")
                self.assertFalse(any(r.get("fit_reused") for r in fourth.values()))
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


class RaceHeadsStaleTests(unittest.TestCase):
    def test_warns_when_json_older_than_plugin(self):
        with tempfile.TemporaryDirectory() as d:
            esm, js = os.path.join(d, "S2SRaceTest.esm"), os.path.join(d, "race_heads.json")
            for f in (esm, js):
                open(f, "w").close()
            os.utime(js, (1000, 1000))
            os.utime(esm, (100000, 100000))
            self.assertIn("older than", S.race_heads_stale(esm))
            os.utime(js, (100000, 100000))
            self.assertEqual(S.race_heads_stale(esm), "")
            os.remove(js)
            self.assertEqual(S.race_heads_stale(esm), "")


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
        self.assertIsNone(c["tones"])
        # the type function the run uses (2026-11-12: it raised TypeError on the owner's first every-race run)
        self.assertEqual([S.hdpt_type(sf_hdpt[f]) for f in (0x510, 0x520, 0x530)], [1, 2, 9])
        self.assertIsNone(S.hdpt_type(None))
        out2, n2 = S.on_race(subs, c, False, 3, sf_hdpt, S.hdpt_type)
        self.assertEqual((out2, n2), (out, n))                      # no skin tones in that race_heads.json

    def test_converted_races_from_the_plugin(self):
        """2026-11-19 (Faendal human again): a race_heads.json that lists none of the plugin's races (older than it)
        no longer loses them - the plugin's RACE records give the races and their FormIDs."""
        Z = lambda t: t.encode() + b"\0"                                                # noqa: E731
        h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)   # noqa: E731
        with tempfile.TemporaryDirectory() as d:
            plug = os.path.join(d, "S2SRaceTest.esm")
            recs = [(b"RACE", h(b"RACE"), [(b"EDID", Z("S2S_BosmerRace"))], 0x01000820),
                    (b"RACE", h(b"RACE"), [(b"EDID", Z("S2S_BosmerChildRace"))], 0x01000821),
                    (b"HDPT", h(b"HDPT"), [(b"EDID", Z("S2S_BosmerRace_male_Head"))], 0x01000810)]
            with open(plug, "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}))
            with open(os.path.join(d, "race_heads.json"), "w") as fh:
                json.dump({"new_races": {"WoodElfRace": {"form_id": "01000999", "edid": "S2S_BosmerRace"},
                                         "OrcRace": {"form_id": "01000900", "edid": "S2S_OrcRace"}}}, fh)
            conv = S.converted_races(plug)
            self.assertEqual(conv["WoodElfRace"]["form_id"], 0x820)          # the plugin's, not the stale file's
            self.assertNotIn("OrcRace", conv)                                 # listed, but not in the plugin
            self.assertEqual(conv["WoodElfRace"]["head"], {False: 0x810})
            os.remove(os.path.join(d, "race_heads.json"))
            self.assertEqual(list(S.converted_races(plug)), ["WoodElfRace"])  # no race_heads.json at all

    def test_npc_changes(self):
        """Each run reports which test NPCs differ from the last one (record, own head parts, head files)."""
        Z = lambda t: t.encode() + b"\0"                                                # noqa: E731
        I = lambda v: struct.pack("<I", v)                                              # noqa: E731
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "meshes"))
            with open(os.path.join(d, "meshes", "kid.nif"), "wb") as fh:
                fh.write(b"head v1")

            def run(kid_bytes, ralof_name):
                with open(os.path.join(d, "meshes", "kid.nif"), "wb") as fh:
                    fh.write(kid_bytes)
                recs = [(b"HDPT", b"", [(b"EDID", Z("KidHead"))], 0x0A000800),
                        (b"NPC_", b"", [(b"EDID", Z("S2SFace_Kid")), (b"PNAM", I(0x0A000800))], 0x0A000801),
                        (b"NPC_", b"", [(b"EDID", Z(ralof_name))], 0x0A000802)]
                rows = [{"edid": "Kid", "test_npc": {}, "child": {"files": ["meshes/kid.nif"]}},
                        {"edid": "Ralof", "test_npc": {}}, {"edid": "Skipped", "test_npc": "none"}]
                rep = S.npc_changes(rows, recs, {"Kid": 1, "Ralof": 2}, d, S.previous_rows(d))
                with open(os.path.join(d, "faces.json"), "w") as fh:
                    json.dump({"npcs": rows}, fh)
                return rep
            self.assertEqual(run(b"head v1", "S2SFace_Ralof")["new"], ["Kid", "Ralof"])
            self.assertEqual(run(b"head v1", "S2SFace_Ralof"), {"changed": [], "unchanged": ["Kid", "Ralof"],
                                                                "new": []})
            self.assertEqual(run(b"head v2", "S2SFace_Ralof")["changed"], ["Kid"])      # its head file changed
            self.assertEqual(run(b"head v2", "S2SFace_Ralof2")["changed"], ["Ralof"])

    def test_adult_own_head(self):
        """--shape-npc: an adult's own head baked on its race's head (the race plugin's mesh) by the children's fit;
        the NPC's face part swapped for a copy of the vanilla head part with that model."""
        import types as _types
        from unittest import mock
        Z = lambda t: t.encode() + b"\0"                                                # noqa: E731
        I = lambda v: struct.pack("<I", v)                                              # noqa: E731
        a = _types.SimpleNamespace(shape_npc=["Faendal"])
        self.assertTrue(S.uses_adult_shape(a, {"edid": "faendal"}))
        self.assertFalse(S.uses_adult_shape(a, {"edid": "Ralof"}))
        v_van = np.zeros((4, 3))
        v_race = np.full((4, 3), 0.001)
        tris = np.array([[0, 1, 2], [0, 2, 3]])
        seen = {}
        with tempfile.TemporaryDirectory() as d:
            plug = os.path.join(d, "races", "S2SRaceTest.esm")
            os.makedirs(os.path.dirname(plug))
            open(plug, "wb").close()
            race_nif = os.path.join(d, "races", "meshes", "s2s", "races", "bosmer", "malehead.nif")
            os.makedirs(os.path.dirname(race_nif))
            with open(race_nif, "wb") as fh:
                fh.write(b"race nif")

            def head_mesh(nif, read):
                return ("geo\\head", v_race if nif == b"race nif" else v_van, tris)

            def disp_fn(ctx, fg, fg_bytes, tilt=False):
                seen["on"] = ctx["head"].vertices.copy()
                seen["tilt"] = tilt
                return np.full((4, 3), 0.002), {"version": 13}

            def baked(nif, read, mpath, src, disp, out_nif):
                seen.setdefault("baked", []).append((out_nif, src.copy(), disp.copy()))
                return {out_nif: b"nif", "geometries/x/y.mesh": b"mesh"}
            with mock.patch.object(S.hkx_to_af, "vanilla_file", lambda r, sf: (b"van nif", r)), \
                    mock.patch("race_heads.vanilla_head_model", lambda esm, f: "Actors\\Human\\MaleHead.nif"), \
                    mock.patch.object(S, "head_mesh", head_mesh), \
                    mock.patch.object(S, "starfield_head_node", lambda b: np.eye(4)), \
                    mock.patch.object(S, "skyrim_head_triangles", lambda b: tris), \
                    mock.patch.object(S, "child_shape_disp", disp_fn), \
                    mock.patch("fo4sf.headbake.baked_head_files", baked), \
                    mock.patch.object(S, "child_preview", lambda *x: {"png": "p"}):
                own = S.adult_own_head({"edid": "Faendal", "female": False}, np.zeros((5, 3)), b"fg", "al", True,
                                       np.zeros((5, 3)), b"base", {"name": "Bosmer"}, plug, "sf", d, a, {})
                self.assertTrue(os.path.isfile(os.path.join(d, "geometries", "x", "y.mesh")))
        np.testing.assert_allclose(seen["on"], v_race)                       # fitted on the race's head
        self.assertTrue(seen["tilt"])                                        # with his own eye slant
        out_nif, src, total = seen["baked"][0]
        self.assertEqual(out_nif, "meshes/s2s/faces/faendalhead.nif")
        np.testing.assert_allclose(src, v_van)                               # baked onto the vanilla mesh ...
        np.testing.assert_allclose(total, v_race + 0.002 - v_van)            # ... with race shape + own fit
        self.assertEqual(own["model"], "S2S\\Faces\\FaendalHead.nif")
        self.assertIn("Bosmer", own["on"])
        # the NPC: its race head part (after on_race) swapped for the new head part
        van = (b"HDPT", b"", [(b"EDID", Z("Human_Male_Head")), (b"PNAM", I(1)), (b"MODL", Z("v.nif"))], 0x123)
        eyes = (b"HDPT", b"", [(b"EDID", Z("Eyes")), (b"PNAM", I(2))], 0x124)
        recs = [None] * 5
        subs = [(b"EDID", Z("S2SFace_Faendal")), (b"PNAM", I(0x03000810)), (b"PNAM", I(0x124))]
        out, hd = S.with_own_head(subs, {"edid": "Faendal", "female": False, "own_head": own}, recs,
                                  ["Starfield.esm", "a", "b", "S2SRaceTest.esm"], {0x123: van, 0x124: eyes},
                                  0x03000810)
        new = recs[-1]
        self.assertEqual(f"{new[3]:08X}", hd)
        self.assertEqual(dict(new[2])[b"MODL"], Z("S2S\\Faces\\FaendalHead.nif"))
        self.assertEqual(dict(new[2])[b"PNAM"], I(1))                        # still a face part (vanilla's)
        self.assertEqual([struct.unpack("<I", d_)[0] for s_, d_ in out if s_ == b"PNAM"], [new[3], 0x124])
        # 2026-11-19: the NPC's FormID, handed out before the head part is added, is not reused for it
        from fo4sf import sfplugin
        recs = [None] * 5
        npc_fid = sfplugin.new_form_id(5, masters=4)
        _o, hd = S.with_own_head(subs, {"edid": "Faendal", "female": False, "own_head": own}, recs,
                                 ["Starfield.esm", "a", "b", "S2SRaceTest.esm"], {0x123: van, 0x124: eyes},
                                 0x03000810, taken={npc_fid})
        self.assertNotEqual(int(hd, 16), npc_fid)
        recs.append((b"NPC_", b"", [(b"EDID", Z("S2SFace_Faendal"))], npc_fid))
        S.check_new_form_ids([r for r in recs if r], 4)                      # no clash

    def test_check_new_form_ids(self):
        Z = lambda t: t.encode() + b"\0"                                                # noqa: E731
        recs = [(b"HDPT", b"", [(b"EDID", Z("S2S_Head_Faendal"))], 0x06000808),
                (b"NPC_", b"", [(b"EDID", Z("S2SFace_Faendal"))], 0x06000808),
                (b"NPC_", b"", [(b"EDID", Z("Override"))], 0x00012345),
                (b"NPC_", b"", [(b"EDID", Z("Override2"))], 0x00012345)]          # overrides may repeat a master's
        with self.assertRaises(ValueError) as cm:
            S.check_new_form_ids(recs, 6)
        self.assertIn("06000808", str(cm.exception))
        self.assertIn("S2S_Head_Faendal", str(cm.exception))
        S.check_new_form_ids(recs[1:], 6)

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

    def test_human_face_colour(self):
        """2026-11-12: templates chosen by face ethnicity first; a template whose skin tone is TONE_GAP or more from
        the NPC's gets its baked face recoloured to the NPC's body tone (Starfield's body tone texture at its STON)."""
        from fo4sf import skintone
        Z = lambda t: t.encode() + b"\0"                                                # noqa: E731
        body = {S.HUMAN_BODY_TONE[False].format(k=k): skintone.raw_dds(skintone.solid(
            np.full((4, 4, 4), 255, np.uint8), (220 - 20 * k, 170 - 15 * k, 140 - 12 * k))) for k in range(9)}
        tpl = [(b"EDID", Z("t")), (b"STON", b"\x01")]
        self.assertEqual(S.human_face_colour(tpl, 2, False, body.__getitem__), (None, None))       # 1 step: kept
        colour, info = S.human_face_colour(tpl, 7, False, body.__getitem__)
        self.assertEqual((info["template_ston"], info["ston"]), (1, 7))
        face = skintone.raw_dds(skintone.solid(np.full((4, 4, 4), 255, np.uint8), (200, 160, 130)))
        got = skintone.median_colour(skintone.decode_dds(colour(face)))
        self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(got, (80, 65, 56))), got)
        self.assertEqual(S.human_face_colour(tpl, None, False, body.__getitem__), (None, None))
