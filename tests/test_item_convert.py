"""scripts/armor/item_convert.py and os_export.item_records: clothing per item with a male and a female version
(MOD2 + NAM4 / MOD3 + NAM6), outfits of converted items, ids kept across runs, test NPCs, and face_fit's
--items-plugin lookup (synthetic plugins, gear_fit's fit stubbed)."""
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import sfplugin  # noqa: E402
import face_fit  # noqa: E402
import gear_fit  # noqa: E402
import item_convert as IC  # noqa: E402
import os_export as E  # noqa: E402
import test_os_convert  # noqa: E402

z = sfplugin.zs
u32 = lambda v: struct.pack("<I", v)       # noqa: E731
HDR = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(8)       # noqa: E731
TCMP = struct.pack("<H", 12) + b"Meshes\\NW\\M" + b"\0"


def sf_esm(path):
    """Starfield.esm stand-in: the nightwear armor / addons (with a morph record) and the two body NPCs."""
    recs = [(b"ARMA", HDR(b"ARMA"), [(b"EDID", z("Nightwear_AA")), (b"BO64", (1 << 3).to_bytes(8, "little")),
                                     (b"MOD2", z("Clothes\\nw_m.nif")), (b"MOD3", z("Clothes\\nw_f.nif")),
                                     (b"MOD4", z("Clothes\\nw_1st.nif")), (b"NAM4", u32(0x4000)),
                                     (b"NAM6", u32(0x4000))], 0x1000),
            (b"ARMO", HDR(b"ARMO"), [(b"EDID", z(E.TEMPLATE_ARMOR)), (b"FULL", z("Nightwear")),
                                     (b"BO64", (1 << 3).to_bytes(8, "little")),
                                     (b"INDX", b"\0\0"), (b"MODL", u32(0x1000))], 0x2000),
            (b"OTFT", HDR(b"OTFT"), [(b"EDID", z("SomeOutfit")), (b"INAM", u32(0x2000))], 0x3000),
            (b"ARMA", HDR(b"ARMA"), [(b"EDID", z(E.SKIN_TEMPLATE_ADDON)), (b"BO64", (1 << 13).to_bytes(8, "little")),
                                     (b"MOD2", z("Clothes\\skin_m.nif")), (b"MOD3", z("Clothes\\skin_f.nif"))],
             0x1001),
            (b"MRPH", HDR(b"MRPH"), [(b"EDID", z("MORPH_NW")), (b"TCMP", TCMP), (b"MOBC", struct.pack("<II", 7, 2792))],
             0x4000)]
    for i, e in enumerate(face_fit.BODY_NPC):
        recs.append((b"NPC_", HDR(b"NPC_"), [(b"EDID", z(e)), (b"FULL", z(e)), (b"ACBS", bytes(14) + b"\x13\x6c" + bytes(4)),
                                             (b"TPLT", u32(0x5555)), (b"DOFT", u32(0x3000)), (b"CNTO", bytes(8))],
                     0x6000 + i))
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}))


def row(shape, sex, slots=(3, 5), skin=False, n=100, item="Cuirass"):
    nif = f"S2S\\Items\\{item}_{IC.TAG[sex]}\\{E.part_slug(shape)}.nif"
    return {"shape": shape, "nif": nif, "vertices": n, "slots": None if skin else list(slots), "skin": skin,
            "morph_folder": E.morph_folder(nif, shape)}


class IdMapTests(unittest.TestCase):
    def test_ids_kept_and_never_reused(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, IC.IDS)
            ids = IC.IdMap(p)
            a, b = ids("S2S_A"), ids("S2S_B")
            self.assertEqual((a, b), (0x01000800, 0x01000801))
            self.assertEqual(ids("S2S_A"), a)
            ids.save()
            again = IC.IdMap(p)
            self.assertEqual((again("S2S_B"), again("S2S_C")), (b, 0x01000802))
            seeded = IC.IdMap(os.path.join(d, "none.json"), seed=[("S2S_X", 0x01000900)])
            self.assertEqual((seeded("S2S_X"), seeded("S2S_Y")), (0x01000900, 0x01000901))   # plugin without map


class PairTests(unittest.TestCase):
    def test_pairs_by_skin_name_then_slots(self):
        male = [row("Cuirass", "male"), row("Boots", "male", (7,)), row("Cape", "male", (10,)),
                row("S2S_Skin", "male", skin=True)]
        female = [row("CUIRASS", "female"), row("BootsF", "female", (7,)), row("Belt", "female", (10,)),
                  row("S2S_Skin", "female", skin=True)]
        pairs, notes = IC.pair_parts(male, female)
        by = {p["key"]: p for p in pairs}
        self.assertTrue(by["S2S_Skin"]["skin"])
        self.assertEqual((by["S2S_Skin"]["male"]["shape"], by["S2S_Skin"]["female"]["shape"]), ("S2S_Skin",) * 2)
        self.assertEqual(by["Cuirass"]["female"]["shape"], "CUIRASS")                 # same name, any case
        self.assertEqual(by["Boots"]["female"]["shape"], "BootsF")                    # same slots
        self.assertEqual(by["Cape"]["female"]["shape"], "Belt")                       # same (spare) slot
        self.assertEqual(sorted(by), ["Boots", "Cape", "Cuirass", "S2S_Skin"])
        pairs, notes = IC.pair_parts([row("Cuirass", "male"), row("Cape", "male", (3, 5))],
                                     [row("Cuirass", "female"), row("Belt", "female", (11,))])
        by = {p["key"]: p for p in pairs}
        self.assertEqual((by["Cape_M"]["female"], by["Belt_F"]["male"]), (None, None))   # one sex each
        self.assertEqual(by["Cuirass"]["slots"], [3, 5])
        self.assertNotEqual(by["Cape_M"]["slots"], [3, 5])                            # moved off the cuirass' slots
        self.assertTrue(notes)


class RecordTests(unittest.TestCase):
    def records(self, d, ids=None):
        p = os.path.join(d, "Starfield.esm")
        sf_esm(p)
        ids = ids or IC.IdMap(os.path.join(d, IC.IDS))
        pairs, _n = IC.pair_parts([row("Cuirass", "male", n=120), row("S2S_Skin", "male", skin=True, n=50)],
                                  [row("Cuirass", "female", n=130), row("Belt", "female", (10,), n=20)])
        items = [{"edid": "Cuirass", "full": "Iron Cuirass", "pairs": pairs},
                 {"edid": "Boots", "full": "Boots", "pairs": IC.pair_parts([row("Boots", "male", (7,), item="Boots")],
                                                                           [row("Boots", "female", (7,),
                                                                                item="Boots")])[0]}]
        return E.item_records(p, items, [{"edid": "RalofOutfit", "items": ["Cuirass", "Boots", "Helmet"]}], ids,
                              template_vertices=2792), ids

    def test_both_sexes_in_one_addon(self):
        with tempfile.TemporaryDirectory() as d:
            recs, rep = self.records(d)[0]
        by = {sfplugin.edid(r[2]): r for r in recs}
        a = dict(by["S2S_Cuirass_Cuirass_AA"][2])
        self.assertEqual(a[b"MOD2"], z("S2S\\Items\\Cuirass_M\\Cuirass.nif"))       # male model
        self.assertEqual(a[b"MOD3"], z("S2S\\Items\\Cuirass_F\\Cuirass.nif"))       # female model
        self.assertEqual(a[b"MOD4"], z("Clothes\\nw_1st.nif"))                      # first person kept
        m, f = by["S2S_Cuirass_Cuirass_M_Morph"], by["S2S_Cuirass_Cuirass_F_Morph"]
        self.assertEqual((a[b"NAM4"], a[b"NAM6"]), (u32(m[3]), u32(f[3])))           # a morph per sex
        path = E.morph_folder("S2S\\Items\\Cuirass_F\\Cuirass.nif", "Cuirass").encode()
        self.assertEqual(dict(f[2])[b"TCMP"], struct.pack("<H", len(path) + 1) + path + b"\0")
        self.assertEqual((dict(m[2])[b"MOBC"], dict(f[2])[b"MOBC"]), (struct.pack("<II", 7, 120), struct.pack("<II", 7, 130)))
        belt = dict(by["S2S_Cuirass_Belt_F_AA"][2])
        self.assertNotIn(b"MOD2", belt)                                              # female only
        self.assertNotIn(b"NAM4", belt)
        self.assertEqual(belt[b"MOD3"], z("S2S\\Items\\Cuirass_F\\Belt.nif"))
        skin = dict(by["S2S_Cuirass_S2S_Skin_AA"][2])
        self.assertEqual(skin[b"MOD2"], z("S2S\\Items\\Cuirass_M\\S2S_Skin.nif"))
        self.assertNotIn(b"MOD3", skin)
        armo = by["S2S_Cuirass"][2]
        self.assertEqual(dict(armo)[b"FULL"], z("Iron Cuirass"))
        self.assertEqual([bytes(d_)[:4] for s, d_ in armo if s == b"MODL"],
                         [u32(by[k][3]) for k in ("S2S_Cuirass_S2S_Skin_AA", "S2S_Cuirass_Cuirass_AA",
                                                  "S2S_Cuirass_Belt_F_AA")])
        otft = dict(by["S2S_RalofOutfit"][2])
        self.assertEqual(otft[b"INAM"], u32(by["S2S_Cuirass"][3]) + u32(by["S2S_Boots"][3]))   # both items
        self.assertEqual(rep["outfits"][0]["missing"], ["Helmet"])
        part = next(p for p in rep["items"][0]["parts"] if p["key"] == "Belt_F")
        self.assertEqual(part["one_sex"], "female")

    def test_skin_piece_of_shoes_keeps_their_slot(self):
        """2026-11-09 (Orgnar): a skin piece on an item that does not cover the body takes the item's slots, not the
        vanilla skin addon's 13, which the shirt's skin piece holds."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Starfield.esm")
            sf_esm(p)
            ids = IC.IdMap(os.path.join(d, IC.IDS))
            shoes = IC.pair_parts([row("Shoes", "male", (7,), item="Shoes"),
                                   row("S2S_Skin", "male", skin=True, item="Shoes")], [])[0]
            shirt = IC.pair_parts([row("Shirt", "male", (3, 5), item="Shirt"),
                                   row("S2S_Skin", "male", skin=True, item="Shirt")], [])[0]
            recs, rep = E.item_records(p, [{"edid": "Shoes", "pairs": shoes}, {"edid": "Shirt", "pairs": shirt}],
                                       [], ids, template_vertices=2792)
        by = {i["edid"]: i for i in rep["items"]}
        self.assertEqual(by["Shoes"]["slots"], [7])
        self.assertEqual(next(p_ for p_ in by["Shoes"]["parts"] if p_["key"] == "S2S_Skin")["slots"], [7])
        skin = next(p_ for p_ in by["Shirt"]["parts"] if p_["key"] == "S2S_Skin")
        self.assertNotEqual(skin["slots"], [3, 5])                    # the body item's skin keeps the skin addon's
        self.assertFalse(set(by["Shoes"]["slots"]) & set(by["Shirt"]["slots"]))

    def test_ids_stable_across_runs(self):
        with tempfile.TemporaryDirectory() as d:
            (recs, _r), ids = self.records(d)
            ids.save()
            (recs2, _r2), _ids = self.records(d, IC.IdMap(os.path.join(d, IC.IDS)))
        self.assertEqual({sfplugin.edid(r[2]): r[3] for r in recs}, {sfplugin.edid(r[2]): r[3] for r in recs2})


def stub_fit(rows_by):
    def fit(a, edid, sex, fit_args):
        rows = rows_by.get((edid, sex))
        return {"rows": rows} if rows is not None else {"error": "no worn armor meshes"}
    return fit


class MainTests(unittest.TestCase):
    def run_main(self, d, argv, rows_by):
        sky, sf = os.path.join(d, "Skyrim"), os.path.join(d, "SF")
        os.makedirs(sky, exist_ok=True)
        os.makedirs(os.path.join(sf, "Data"), exist_ok=True)
        if not os.path.isfile(os.path.join(sky, "Skyrim.esm")):
            test_os_convert.esm(os.path.join(sky, "Skyrim.esm"))
            sf_esm(os.path.join(sf, "Data", "Starfield.esm"))
        out = os.path.join(d, "out")
        with mock.patch.object(IC, "fit_item", stub_fit(rows_by)), \
                mock.patch.object(E, "template_model", lambda sf_data: ("mat", 2792)), \
                mock.patch.object(IC.bsa, "SkyrimArchives", lambda p: object()), \
                mock.patch("npc_records.skyrim_names", lambda sky: {}), mock.patch("builtins.print"):
            code = IC.main(["--skyrim-data", sky, "--starfield", sf, "--out", out] + argv)
        self.assertEqual(code, 0)
        recs = sfplugin.records(os.path.join(out, IC.PLUGIN), [b"ARMA", b"MRPH", b"ARMO", b"OTFT", b"NPC_"])
        return {sfplugin.edid(r[2]): r for r in recs}, out

    def test_outfit_items_and_test_npcs_then_rebuilds(self):
        rows_by = {("Cuirass", "male"): [row("Cuirass", "male"), row("S2S_Skin", "male", skin=True)],
                   ("Cuirass", "female"): [row("Cuirass", "female"), row("S2S_Skin", "female", skin=True)],
                   ("Boots", "male"): [row("Boots", "male", (7,), item="Boots")],
                   ("Boots", "female"): [row("Boots", "female", (7,), item="Boots")]}
        with tempfile.TemporaryDirectory() as d:
            by, out = self.run_main(d, ["--npc", "Ralof", "--test-npcs"], rows_by)
            otft = by["S2S_RalofOutfit"]
            self.assertEqual(dict(otft[2])[b"INAM"], u32(by["S2S_Cuirass"][3]) + u32(by["S2S_Boots"][3]))
            for tag in "MF":
                npc = dict(by[f"{IC.TEST_NPC}_{tag}"][2])
                self.assertEqual((npc[b"DOFT"], npc[b"SOFT"]), (u32(otft[3]),) * 2)    # wears the converted outfit
                self.assertNotIn(b"TPLT", npc)
                self.assertNotIn(b"CNTO", npc)
            first = {k: r[3] for k, r in by.items()}
            # the boots again, the cuirass now without its skin piece: the cuirass stays, the ids do not move
            rows_by[("Boots", "male")] = [row("Boots", "male", (7,), n=300, item="Boots")]
            by2, _o = self.run_main(d, ["--armor", "Boots"], rows_by)
            self.assertEqual({k: r[3] for k, r in by2.items()}, first)
            rows_by[("Cuirass", "male")] = [row("Cuirass", "male")]
            rows_by[("Cuirass", "female")] = [row("Cuirass", "female")]
            by3, _o = self.run_main(d, ["--armor", "Cuirass"], rows_by)
            self.assertNotIn("S2S_Cuirass_S2S_Skin_AA", by3)                          # its old part dropped
            self.assertEqual(by3["S2S_Cuirass"][3], first["S2S_Cuirass"])
            self.assertIn("S2S_RalofOutfit", by3)
            with open(os.path.join(out, IC.IDS), encoding="utf-8") as fh:
                ids = json.load(fh)
            self.assertIn("S2S_Cuirass_S2S_Skin_AA", ids["ids"])                        # id stays reserved
            by4, _o = self.run_main(d, ["--armor", "Boots", "--replace-all"], rows_by)
            self.assertNotIn("S2S_Cuirass", by4)

    def test_one_sex_failing_leaves_the_other(self):
        rows_by = {("Boots", "male"): [row("Boots", "male", (7,), item="Boots")]}
        with tempfile.TemporaryDirectory() as d:
            by, out = self.run_main(d, ["--armor", "Boots"], rows_by)
            with open(os.path.join(out, "item_convert.json"), encoding="utf-8") as fh:
                rep = json.load(fh)
        a = dict(by["S2S_Boots_Boots_M_AA"][2])
        self.assertIn(b"MOD2", a)
        self.assertNotIn(b"MOD3", a)
        self.assertEqual(rep["items"]["Boots"]["fits"]["female"]["error"], "no worn armor meshes")


class ReuseTests(unittest.TestCase):
    def test_unchanged_fits_reused_shared_outfit_once(self):
        """2026-11-12 (owner: one conversion per outfit, whoever wears it; done steps not redone): two NPCs with the
        same Skyrim outfit fit its items once per sex; a later run reuses those fits (same records and ids), --refit
        or other --fit-args fit again."""
        rows_by = {("Cuirass", s): [row("Cuirass", s)] for s in IC.SEXES}
        rows_by.update({("Boots", s): [row("Boots", s, (7,), item="Boots")] for s in IC.SEXES})
        calls = []

        def fit(a, edid, sex, fit_args):
            calls.append((edid, sex))
            name = f"Items\\{edid}_{IC.TAG[sex]}"
            os.makedirs(os.path.join(a.out, "_staging"), exist_ok=True)
            with open(IC.stage_report(a.out, name), "w", encoding="utf-8") as fh:
                json.dump({"records": {"stage": rows_by[(edid, sex)]}, "meshes": []}, fh)
            return {"rows": rows_by[(edid, sex)]}

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(IC, "fit_item", fit):
                run = lambda argv: self.run_plain(d, argv)                              # noqa: E731
                by, _o = run(["--npc", "Ralof", "--npc", "Ralof"])
                self.assertEqual(sorted(calls), sorted((e, s) for e in ("Cuirass", "Boots") for s in IC.SEXES))
                first = {k: r[3] for k, r in by.items()}
                calls.clear()
                by2, _o = run(["--npc", "Ralof"])
                self.assertEqual(calls, [])                                           # nothing fitted again
                self.assertEqual({k: r[3] for k, r in by2.items()}, first)
                run(["--npc", "Ralof", "--refit"])
                self.assertEqual(len(calls), 4)
                calls.clear()
                run(["--armor", "Boots", "--fit-args=--conform"])
                self.assertEqual(sorted(calls), [("Boots", "female"), ("Boots", "male")])

    def run_plain(self, d, argv):
        sky, sf = os.path.join(d, "Skyrim"), os.path.join(d, "SF")
        os.makedirs(sky, exist_ok=True)
        os.makedirs(os.path.join(sf, "Data"), exist_ok=True)
        if not os.path.isfile(os.path.join(sky, "Skyrim.esm")):
            test_os_convert.esm(os.path.join(sky, "Skyrim.esm"))
            sf_esm(os.path.join(sf, "Data", "Starfield.esm"))
        out = os.path.join(d, "out")
        with mock.patch.object(E, "template_model", lambda sf_data: ("mat", 2792)), \
                mock.patch.object(IC.bsa, "SkyrimArchives", lambda p: object()), \
                mock.patch("npc_records.skyrim_names", lambda sky: {}), mock.patch("builtins.print"), \
                mock.patch("hair_pack.pack", lambda *x, **k: None):
            self.assertEqual(IC.main(["--skyrim-data", sky, "--starfield", sf, "--out", out] + argv), 0)
        recs = sfplugin.records(os.path.join(out, IC.PLUGIN), [b"ARMA", b"MRPH", b"ARMO", b"OTFT", b"NPC_"])
        return {sfplugin.edid(r[2]): r for r in recs}, out


class FaceFitLookupTests(unittest.TestCase):
    def test_npc_wears_its_converted_skyrim_outfit(self):
        sky_otft = {0x930: "RalofOutfit"}
        items = {"s2s_ralofoutfit": 0x02000805}
        self.assertEqual(face_fit.npc_item_outfit({"edid": "Ralof", "outfit": 0x930}, sky_otft, items),
                         (0x02000805, "RalofOutfit"))
        fid, why = face_fit.npc_item_outfit({"edid": "Hadvar", "outfit": 0x931}, sky_otft, items)
        self.assertIsNone(fid)
        self.assertIn("no default outfit", why)
        fid, why = face_fit.npc_item_outfit({"edid": "Ralof", "outfit": 0x930}, sky_otft, {})
        self.assertIn("item_convert.py --npc Ralof", why)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, IC.PLUGIN)
            with open(p, "wb") as fh:
                fh.write(sfplugin.build([(b"OTFT", HDR(b"OTFT"), [(b"EDID", z("S2S_RalofOutfit")), (b"INAM", b"")],
                                          0x01000805)], {"hedr_version": 0.96, "form_version": 555}))
            self.assertEqual(face_fit.item_outfits(p, 3), {"s2s_ralofoutfit": 0x03000805})


class GearFitStageTests(unittest.TestCase):
    def test_stage_writes_parts_and_no_plugin(self):
        import numpy as np
        from fo4sf import skyrimhair
        import test_os_export
        sh = skyrimhair.HairShape(b"Dress", np.array([[0, 0, 1.0], [0.1, 0, 1.0], [0, 0.1, 1.0]]),
                                  np.tile([0, 0, 1.0], (3, 1)), np.tile([1.0, 0, 0], (3, 1)), [(0.0, 0.0)] * 3,
                                  [(0, 1, 2)], [[("C_Chest", 1.0)]] * 3, -1, -1, -1, colors=[(255, 255, 255, 255)] * 3)
        rep = {"_body_pts": np.zeros((3, 3)), "joint_rms_m": 0.01, "global_scale": 1.0, "body": {},
               "shapes": {"Dress": {"not_finite": 0, "far_outside": 0, "vertices": 3, "skin_piece": False,
                                    "pushed_out": 0, "max_body_shift_mm": 0.0, "bones": ["C_Chest"],
                                    "box_m": [[0, 0, 1], [0.1, 0.1, 1]], "unweighted": 0}}}
        mesh = {"armor": "ClothesFarmClothes03", "addon": "AA", "slots": [32], "mesh": "meshes\\dress_1.nif"}
        fake = mock.Mock()
        fake._read = lambda p: b"nif"
        with tempfile.TemporaryDirectory() as d:
            sf_esm(os.path.join(d, "Starfield.esm"))
            out = os.path.join(d, "out")
            with mock.patch.object(gear_fit.skyrimarmor, "read_armor", lambda esm: {"armo": {}, "arma": {}}), \
                    mock.patch.object(gear_fit, "armor_by_edid", lambda inv, e: ([1], [])), \
                    mock.patch.object(gear_fit.os_convert, "worn_meshes",
                                      lambda inv, fids, race, female: [dict(mesh, female=female)]), \
                    mock.patch.object(gear_fit.bsa, "SkyrimArchives", lambda p: fake), \
                    mock.patch.object(gear_fit, "shape_textures", lambda gb: {}), \
                    mock.patch.object(gear_fit, "double_sided_shapes", lambda gb: set()), \
                    mock.patch.object(gear_fit, "slots_by_shape", lambda gb, m: {"Dress": [3, 5]}), \
                    mock.patch.object(gear_fit, "run", lambda *a_, **k: ([sh], {"C_Chest": test_os_export.SKIN["binds"][0]},
                                                                         dict(rep))), \
                    mock.patch.object(gear_fit.os_export, "template_model", lambda sf_data: ("mat", None)), \
                    mock.patch("builtins.print"):
                code = gear_fit.main(["--skyrim-data", d, "--starfield", d, "--armor", "ClothesFarmClothes03",
                                      "--sex", "female", "--name", "Items\\ClothesFarmClothes03_F", "--out", out,
                                      "--stage", "--no-textures", "--no-morphs"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(os.path.join(out, "meshes", "S2S", "Items", "ClothesFarmClothes03_F",
                                                        "Dress.nif")))
            self.assertFalse(os.path.exists(os.path.join(out, E.PLUGIN)))                  # no records
            with open(IC.stage_report(out, "Items\\ClothesFarmClothes03_F"), encoding="utf-8") as fh:
                got = json.load(fh)
        self.assertEqual((got["sex"], got["race"]), ("female", "NordRace"))
        st = got["records"]["stage"]
        self.assertEqual([(r["shape"], r["nif"], r["slots"]) for r in st],
                         [("Dress", "S2S\\Items\\ClothesFarmClothes03_F\\Dress.nif", [3, 5])])
        self.assertEqual(st[0]["morph_folder"], E.morph_folder(st[0]["nif"], "Dress"))


class GearFitArgsTests(unittest.TestCase):
    def test_sex_mode_needs_armor_and_stage_refuses_record_tests(self):
        base = ["--skyrim-data", "x", "--starfield", "y", "--name", "n", "--out", tempfile.gettempdir()]
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                gear_fit.main(base + ["--sex", "male"])                                   # no --armor
            with self.assertRaises(SystemExit):
                gear_fit.main(base)                                                        # neither --npc nor --sex
            with self.assertRaises(SystemExit):
                gear_fit.main(base + ["--sex", "male", "--armor", "A", "--stage", "--one-nif"])
        self.assertEqual(os.path.basename(IC.stage_report("o", "Items\\Boots_M")), "gear_fit_Items_Boots_M.json")


if __name__ == "__main__":
    unittest.main()
