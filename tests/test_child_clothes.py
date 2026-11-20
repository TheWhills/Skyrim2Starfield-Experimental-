"""Children's clothes (2026-11-20): Skyrim armor read through a load order (RS Children Overhaul over Skyrim.esm), a
child race's own body and head as the fit's source (gear_fit.race_skin_models), its torso without the underwear
shapes, children's addons on ChildRace (os_export.item_records race), item_convert's load-order options and fit keys.
Synthetic plugins only."""
import os
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fo4sf import sfplugin, skyrimarmor, skyrimload as SL  # noqa: E402
import gear_fit  # noqa: E402
import item_convert as IC  # noqa: E402
import os_export as E  # noqa: E402

INFO = {"hedr_version": 1.71, "form_version": 44}
HDR = bytes(24)
z = sfplugin.zs


def u32(v):
    return struct.pack("<I", v)


def arma(edid, race, male, female=None, slots=(32,), extra=(), slider=True):
    flags = sum(1 << (s - 30) for s in slots)
    subs = [(b"EDID", z(edid)), (b"BOD2", struct.pack("<II", flags, 2)), (b"RNAM", u32(race)),
            (b"DNAM", bytes([2, 2, 2 if slider else 0, 2 if slider else 0]) + bytes(8)), (b"MOD2", z(male))]
    if female:
        subs.append((b"MOD3", z(female)))
    return subs + [(b"MODL", u32(r)) for r in extra]


def armo(edid, addons, slots=(32,)):
    flags = sum(1 << (s - 30) for s in slots)
    return [(b"EDID", z(edid)), (b"BOD2", struct.pack("<II", flags, 2)), (b"RNAM", u32(0x19))] + \
        [(b"MODL", u32(a)) for a in addons]


def race(edid, skin, male_parts=(), female_parts=()):
    return ([(b"EDID", z(edid)), (b"WNAM", u32(skin)), (b"NAM0", b""), (b"MNAM", b"")]
            + [(b"HEAD", u32(p)) for p in male_parts] + [(b"FNAM", b"")] + [(b"HEAD", u32(p)) for p in female_parts])


def hdpt(edid, model, typ):
    return [(b"EDID", z(edid)), (b"MODL", z(model)), (b"PNAM", u32(typ))]


class Fixture:
    """Skyrim.esm: DefaultRace, NordRace, NordRaceChild (its vanilla skin), an adult body addon, the vanilla child
    torso / outfit, Dorthe; mods/RS/RS.esm (masters Skyrim): the child race's own skin (torso, hands, feet addons on
    DefaultRace naming the child race), its head part, the vanilla child torso's addon pointed at RS's mesh, an outfit
    through a leveled list and Frodnar's outfit."""

    def __init__(self, d):
        self.data = os.path.join(d, "Data")
        self.rs = os.path.join(d, "mods", "RS")
        os.makedirs(self.data)
        os.makedirs(self.rs)
        sky = [(b"RACE", HDR, [(b"EDID", z("DefaultRace"))], 0x19),
               (b"RACE", HDR, race("NordRace", 0x100), 0x13746),
               (b"RACE", HDR, race("NordRaceChild", 0x100), 0x2C65B),
               (b"ARMA", HDR, arma("NakedTorsoNord", 0x13746, "Actors\\Character\\Character Assets\\MaleBody_1.nif"),
                0x101),
               (b"ARMO", HDR, armo("SkinNaked", [0x101]), 0x100),
               (b"ARMA", HDR, arma("ChildTorso01AA", 0x19, "Clothes\\Child\\M\\Torso01_1.nif",
                                   "Clothes\\Child\\F\\Torso01_1.nif", extra=[0x2C65B]), 0x6D92D),
               (b"ARMO", HDR, armo("ClothesChild01", [0x6D92D]), 0x6D92C),
               (b"OTFT", HDR, [(b"EDID", z("ChildOutfit01")), (b"INAM", u32(0x6D92C))], 0x6D92E),
               (b"NPC_", HDR, [(b"EDID", z("Dorthe")), (b"ACBS", u32(1) + bytes(20)), (b"RNAM", u32(0x2C65B)),
                               (b"DOFT", u32(0x6D92E))], 0x13477),
               (b"NPC_", HDR, [(b"EDID", z("Frodnar")), (b"ACBS", bytes(24)), (b"RNAM", u32(0x2C65B)),
                               (b"DOFT", u32(0x6D92E))], 0x1347E)]
        self.write(self.data, "Skyrim.esm", sky, ())
        rs = [(b"ARMA", HDR, arma("0RCONakedTorsoChild", 0x19, "actors\\character\\ranaline\\character assets\\malebody_0.nif",
                                  "actors\\character\\ranaline\\character assets\\femalebody_0.nif",
                                  extra=[0x2C65B]), 0x01000801),
              (b"ARMA", HDR, arma("0RCONakedHandsChild", 0x19, "actors\\character\\ranaline\\character assets\\childhands.nif",
                                  "actors\\character\\ranaline\\character assets\\childhands.nif", slots=(33,),
                                  extra=[0x2C65B], slider=False), 0x01000802),
              (b"ARMA", HDR, arma("0RCONakedFeetChild", 0x19, "actors\\character\\ranaline\\character assets\\childfeet.nif",
                                  slots=(37,), extra=[0x2C65B], slider=False), 0x01000803),
              (b"ARMO", HDR, armo("0RCOSkinNakedChildren", [0x101, 0x01000801, 0x01000802, 0x01000803],
                                  slots=(32, 33, 37)), 0x01000800),
              (b"HDPT", HDR, hdpt("RSChildHead", "actors\\character\\ranaline\\character assets\\childhead.nif", 1),
               0x01000810),
              (b"HDPT", HDR, hdpt("RSChildBrows", "actors\\character\\ranaline\\character assets\\childbrows.nif", 6),
               0x01000811),
              (b"RACE", HDR, race("NordRaceChild", 0x01000800, [0x01000811, 0x01000810], [0x01000810]), 0x2C65B),
              (b"ARMA", HDR, arma("ChildTorso01AA", 0x19, "Clothes\\ChildrenClothes\\M\\Torso01_1.nif",
                                  "Clothes\\ChildrenClothes\\F\\Torso01_1.nif", extra=[0x2C65B]), 0x6D92D),
              (b"ARMA", HDR, arma("0RCOClothesBlacksmith", 0x19, "clothes\\ranaline\\m\\children\\blacksmith_1.nif",
                                  extra=[0x2C65B]), 0x01000820),
              (b"ARMO", HDR, armo("0RCOClothesChildBlacksmith", [0x01000820]), 0x01000821),
              (b"LVLI", HDR, [(b"EDID", z("RSLeveled")), (b"LVLF", b"\x04"),
                              (b"LVLO", struct.pack("<HHIHH", 1, 0, 0x01000821, 1, 0))], 0x01000822),
              (b"OTFT", HDR, [(b"EDID", z("0RCOClothesOBlacksmith")), (b"INAM", u32(0x01000822))], 0x01000823),
              (b"NPC_", HDR, [(b"EDID", z("Frodnar")), (b"ACBS", bytes(24)), (b"RNAM", u32(0x2C65B)),
                              (b"DOFT", u32(0x01000823))], 0x1347E)]
        self.write(self.rs, "RS.esm", rs, ("Skyrim.esm",))

    @staticmethod
    def write(folder, name, recs, masters):
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(sfplugin.build(recs, INFO, masters=masters))


class LoadOrderArmorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Fixture(self.tmp.name)
        self.lo = SL.LoadOrder(self.f.data, [self.f.rs])

    def tearDown(self):
        self.tmp.cleanup()

    def test_inventory_through_the_mod(self):
        inv = skyrimarmor.read_armor_load_order(self.lo)
        torso = inv["arma"][0x6D92D]
        self.assertEqual(torso["male"], "Clothes\\ChildrenClothes\\M\\Torso01_1.nif")      # RS's override wins
        self.assertEqual((torso["race"], torso["extra_races"]), ("DefaultRace", ["NordRaceChild"]))
        self.assertEqual(inv["armo"][0x01000800]["addons"], [0x101, 0x01000801, 0x01000802, 0x01000803])
        plain = skyrimarmor.read_armor(os.path.join(self.f.data, "Skyrim.esm"))
        self.assertEqual(plain["arma"][0x6D92D]["male"], "Clothes\\Child\\M\\Torso01_1.nif")

    def test_child_race_body_and_head(self):
        recs = SL.records(self.lo, [b"RACE", b"ARMO", b"ARMA", b"HDPT"])
        m = gear_fit.race_skin_models(recs, "NordRaceChild", False)
        base = "meshes\\actors\\character\\ranaline\\character assets\\"
        self.assertEqual(m["skin"], "0RCOSkinNakedChildren")
        self.assertEqual(m["torso"], base + "malebody_1.nif")             # the _1 weight variant; not Nord's body
        self.assertEqual(m["limbs"], [base + "childhands.nif", base + "childfeet.nif"])
        self.assertEqual(m["head"], base + "childhead.nif")                # the Face part, not the brows
        f = gear_fit.race_skin_models(recs, "NordRaceChild", True)
        self.assertEqual(f["torso"], base + "femalebody_1.nif")
        self.assertEqual(f["limbs"], [base + "childhands.nif", base + "childfeet.nif"])   # male model when no female
        self.assertEqual(gear_fit.race_skin_models(recs, "NoSuchRace", False)["torso"], None)
        vanilla = gear_fit.race_skin_models(SL.records(os.path.join(self.f.data, "Skyrim.esm"),
                                                       [b"RACE", b"ARMO", b"ARMA", b"HDPT"]), "NordRaceChild", False)
        self.assertEqual(vanilla["torso"], None)                           # the adult body addon is not for children
        self.assertTrue(gear_fit.is_child_race("BretonRaceChildVampire"))
        self.assertFalse(gear_fit.is_child_race("NordRace"))

    def test_outfits_through_the_mod_and_leveled_lists(self):
        outfits, notes = IC.skyrim_outfits(self.lo, npc_edids=["Frodnar", "Dorthe"])
        by = {o["edid"]: o for o in outfits}
        self.assertEqual(by["0RCOClothesOBlacksmith"]["armor"], [0x01000821])   # through RS's leveled list
        self.assertEqual(by["0RCOClothesOBlacksmith"]["npcs"], ["Frodnar"])
        self.assertEqual(by["ChildOutfit01"]["armor"], [0x6D92C])
        self.assertEqual(notes, [])

    def test_leveled_entry_rewritten(self):
        flat = {fid: subs for _t, _h, subs, fid in SL.records(self.lo, [b"LVLI"])}
        lvlo = dict(flat[0x01000822])[b"LVLO"]
        self.assertEqual(struct.unpack_from("<I", lvlo, 4)[0], 0x01000821)
        self.assertEqual(SL.rewrite(b"LVLI", [(b"LVLO", b"\0" * 6)], lambda f: f + 1), [(b"LVLO", b"\0" * 6)])


class TorsoShapeTests(unittest.TestCase):
    def test_largest_shape_only(self):
        S = lambda n, k: types.SimpleNamespace(name=n, points=[0] * k)      # noqa: E731
        shapes = [S(b"malebody_0", 3177), S(b"Trousers 2", 1342), S(b"MaleUnderwear_1", 5000)]
        with mock.patch.object(gear_fit, "sky_shapes", return_value=shapes):
            self.assertEqual([s.name for s in gear_fit.body_shapes(b"", True)], [b"malebody_0"])
            self.assertEqual([s.name for s in gear_fit.body_shapes(b"")], [b"malebody_0", b"Trousers 2"])


class ChildRaceRecordTests(unittest.TestCase):
    def test_addons_and_armor_on_the_race(self):
        import test_item_convert as T
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Starfield.esm")
            T.sf_esm(p)
            ids = IC.IdMap(os.path.join(d, IC.IDS))
            pairs, _n = IC.pair_parts([T.row("Torso", "male", item="ClothesChild01")],
                                      [T.row("Torso", "female", item="ClothesChild01")])
            items = [{"edid": "ClothesChild01", "full": "Child clothes", "pairs": pairs}]
            recs, _rep = E.item_records(p, items, [], ids, template_vertices=2792, race=0x002AABCD)
            plain, _r = E.item_records(p, items, [], IC.IdMap(os.path.join(d, "b.json")), template_vertices=2792)
        by = {sfplugin.edid(r[2]): dict(r[2]) for r in recs}
        self.assertEqual(by["S2S_ClothesChild01_Torso_AA"][b"RNAM"], u32(0x002AABCD))
        child = by["S2S_ClothesChild01_Torso_AA"]
        for sig in (b"NAM4", b"NAM6", b"MODL"):                            # as the vanilla child addons: none
            self.assertNotIn(sig, child)
        self.assertFalse([e for e in by if e.endswith("_Morph")])
        adult = {sfplugin.edid(r[2]): dict(r[2]) for r in plain}
        self.assertIn(b"NAM4", adult["S2S_ClothesChild01_Torso_AA"])     # adults' addons unchanged
        self.assertTrue([e for e in adult if e.endswith("_Morph")])
        self.assertNotIn(b"RNAM", {sfplugin.edid(r[2]): dict(r[2]) for r in plain}["S2S_ClothesChild01_Torso_AA"])


class ItemConvertArgsTests(unittest.TestCase):
    def test_mod_args_and_keys(self):
        a = types.SimpleNamespace(race="NordRaceChild", helmets=False, skyrim_mods_dir="C:\\mods",
                                  skyrim_mod=["RS Children", "C:\\x\\Realistic RS Children"])
        self.assertEqual(IC.mod_args(a), ["--skyrim-mods-dir", "C:\\mods", "--skyrim-mod", "RS Children",
                                          "--skyrim-mod", "C:\\x\\Realistic RS Children"])
        plain = types.SimpleNamespace(race="NordRace", helmets=False)
        self.assertEqual(IC.mod_args(plain), [])
        with_none = types.SimpleNamespace(race="NordRace", helmets=False, skyrim_mods_dir="", skyrim_mod=[])
        self.assertEqual(IC.fit_key(with_none, "X", "male", []), IC.fit_key(plain, "X", "male", []))
        a.race = "NordRace"
        self.assertNotEqual(IC.fit_key(a, "X", "male", []), IC.fit_key(plain, "X", "male", []))


if __name__ == "__main__":
    unittest.main()
