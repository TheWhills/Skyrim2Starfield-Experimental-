"""scripts/interior/make_items.py: Skyrim's placed food / drink / potions as Starfield items (a donor ALCH of the same
kind and closest size, its physics body on our model). Synthetic records and NIFs only."""
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))

from fo4sf import nif as nifmod, sfnif, sfplugin  # noqa: E402
import item_test  # noqa: E402
import make_items as M  # noqa: E402

z = sfplugin.zs
H = bytes(24)


def enit(value, flags):
    return struct.pack("<iI", value, flags) + bytes(12)


def sf_alch(fid, edid, model, flags, bounds, vmad=False):
    subs = [(b"EDID", z(edid)), (b"OBND", struct.pack("<6f", *bounds[0], *bounds[1])), (b"MODL", z(model)),
            (b"ENIT", enit(10, flags))]
    if vmad:
        subs.insert(1, (b"VMAD", b"\0" * 6))
    return (b"ALCH", H, subs, fid)


def shape(name):
    return sfnif.StaticShape(name=name, mesh_path=b"aa\\bb", indices_size=3, num_verts=3,
                             material_path="Materials\\s2s\\wine.mat", sphere=(0, 0, 0, 1), box=(0, 0, 0, 1, 1, 1))


class FakeIndex:
    def __init__(self, recs):
        self.recs = recs                               # fid -> (sig, flags, subs)
        self.records = {f: (s.encode(), 0, fl) for f, (s, fl, _subs) in recs.items()}

    def subs(self, fid):
        return self.recs.get(fid, ("", 0, []))[2]

    def kind(self, fid):
        return self.recs[fid][0] if fid in self.recs else None

    def edid(self, fid):
        return next((d.rstrip(b"\0").decode() for s, d in self.subs(fid) if s == b"EDID"), None)


class KindTests(unittest.TestCase):
    def test_skyrim_kinds(self):
        self.assertEqual(M.skyrim_kind("ALCH", "FoodWineAlto", "clutter\\bottles\\winebottle01.nif", M.FOOD), "drink")
        self.assertEqual(M.skyrim_kind("ALCH", "MeadHoningbrew", "honningbrewmeadbottle.nif", M.FOOD), "drink")
        self.assertEqual(M.skyrim_kind("ALCH", "FoodCabbage", "clutter\\food\\cabbage01.nif", M.FOOD), "food")
        self.assertEqual(M.skyrim_kind("ALCH", "RestoreHealth01", "potionhealth.nif", M.MEDICINE), "potion")
        self.assertEqual(M.skyrim_kind("ALCH", "DamageHealth01", "poison01.nif", M.POISON), "potion")
        self.assertEqual(M.skyrim_kind("INGR", "Garlic", "garlic01.nif", 0), "food")
        self.assertEqual(M.skyrim_kind("ALCH", "FoodBread", "clutter\\food\\breadloaf01.nif", M.FOOD), "food")

    def test_starfield_kinds(self):
        self.assertEqual(M.starfield_kinds("Drink_Alc_Bottle_SpaceWine", "a.nif", M.FOOD), {"drink"})
        self.assertEqual(M.starfield_kinds("Food_Pear", "pear.nif", M.FOOD), {"food"})
        self.assertEqual(M.starfield_kinds("Aid_MedPack", "medpack.nif", M.MEDICINE), {"potion"})
        self.assertEqual(M.starfield_kinds("Food_Test_Pear", "pear.nif", M.FOOD), set())       # test records out
        self.assertEqual(M.starfield_kinds("Credits", "credits.nif", 0), set())
        # owner's first run (2026-11-21): model paths and flags misfiled these; the EditorID prefix decides now
        self.assertEqual(M.starfield_kinds("Food_Pack_Oishii_Seaweed_Combo", "SetDressing\\Drinks\\pack.nif", M.FOOD),
                         {"food"})
        self.assertEqual(M.starfield_kinds("ShipRepairKit", "repairkit.nif", M.MEDICINE), set())
        self.assertEqual(M.starfield_kinds("LegendaryCatalyst", "catalyst.nif", M.MEDICINE), set())
        self.assertEqual(M.starfield_kinds("Med_MedPack", "medpack.nif", 0), {"potion"})


class FitTests(unittest.TestCase):
    def test_dims_sort_flat_sides(self):
        self.assertEqual(M.dims([[0, 0, 0], [0.3, 0.1, 0.5]]), (0.1, 0.3, 0.5))
        self.assertEqual(M.dims([[0, 0, 0], [0, 0, 0]]), (0.005, 0.005, 0.005))

    def test_fit_and_rank(self):
        bottle = [[-0.04, -0.04, 0], [0.04, 0.04, 0.3]]
        donors = M.starfield_donors([
            sf_alch(1, "Drink_Big", "big.nif", M.FOOD, [[-0.1, -0.1, 0], [0.1, 0.1, 0.6]]),
            sf_alch(2, "Drink_Wine", "wine.nif", M.FOOD, [[-0.05, -0.04, 0], [0.04, 0.05, 0.32]]),
            sf_alch(3, "Drink_Scripted", "s.nif", M.FOOD, [[-0.04, -0.04, 0], [0.04, 0.04, 0.3]], vmad=True),
            sf_alch(4, "Food_Pear", "pear.nif", M.FOOD, [[-0.04, -0.04, 0], [0.04, 0.04, 0.3]]),
            (b"ALCH", H, [(b"EDID", z("Drink_NoModel")), (b"ENIT", enit(1, M.FOOD))], 5)])
        self.assertEqual([d["edid"] for d in donors], ["Drink_Big", "Drink_Wine", "Drink_Scripted", "Food_Pear"])
        self.assertEqual(M.fit(bottle, bottle), 0.0)
        got = [d["edid"] for d in M.rank_donors(bottle, "drink", donors)]
        self.assertEqual(got, ["Drink_Wine", "Drink_Big", "Drink_Scripted"])    # same kind only, unscripted first
        self.assertEqual([d["edid"] for d in M.rank_donors(bottle, "potion", donors)][0], "Food_Pear")  # no potions: any

    def test_family_preferred(self):
        self.assertEqual(M.skyrim_family("drink", "FoodWineAlto"), "alcohol")
        self.assertEqual(M.skyrim_family("drink", "FoodMead"), "alcohol")
        self.assertEqual(M.skyrim_family("drink", "MilkBottle"), "")
        self.assertEqual(M.skyrim_family("food", "FoodCabbage"), "produce")
        self.assertEqual(M.skyrim_family("food", "FoodPotatoesBaked"), "")          # cooked: not raw produce
        self.assertEqual(M.skyrim_family("food", "FoodBread01A"), "")
        wine = [[-0.12, -0.12, 0], [0.12, 0.12, 0.4]]
        donors = M.starfield_donors([
            sf_alch(1, "Drink_NonAlc_ToGoCup_TerraBrew", "cup.nif", M.FOOD, [[-0.06, -0.06, 0], [0.06, 0.06, 0.2]]),
            sf_alch(2, "Drink_Alc_Bottle_Generic_SpaceWine", "wine.nif", M.FOOD, [[-0.04, -0.04, 0], [0.04, 0.04, 0.33]])])
        self.assertEqual(M.rank_donors(wine, "drink", donors)[0]["edid"], "Drink_NonAlc_ToGoCup_TerraBrew")
        self.assertEqual(M.rank_donors(wine, "drink", donors, "alcohol")[0]["edid"],
                         "Drink_Alc_Bottle_Generic_SpaceWine")
        self.assertEqual(M.rank_donors(wine, "food", donors, "produce")[0]["edid"],   # no produce donor: the kind's pool
                         "Drink_NonAlc_ToGoCup_TerraBrew")

    def test_align_offset(self):
        ours = [[-0.1, -0.1, -0.05], [0.1, 0.1, 0.05]]          # origin at the centre
        donor = [[-0.09, -0.11, 0.0], [0.11, 0.09, 0.1]]       # origin at the base
        self.assertEqual(M.align_offset(ours, donor), (0.01, -0.01, 0.05))

    def test_obnd_floats_only(self):
        self.assertEqual(M.obnd(struct.pack("<6f", -1, -2, 0, 1, 2, 3)), [[-1, -2, 0], [1, 2, 3]])
        self.assertIsNone(M.obnd(struct.pack("<6h", -1, -2, 0, 1, 2, 3)))


class NifTests(unittest.TestCase):
    def test_shift_children_moves_geometry_not_root(self):
        n = nifmod.serialize(sfnif.build_static_nif(b"Cabbage", [shape(b"A"), shape(b"B")]))
        out = nifmod.parse(M.shift_children(n, (0.0, 0.0, 0.05)))
        self.assertEqual(nifmod._av_transform(out.blocks[0])[0], (0.0, 0.0, 0.0))
        kids = nifmod.node_children(out, 0)
        geo = [c for c in kids if out.type_of(c) == "BSGeometry"]
        self.assertEqual(len(geo), 2)
        for c in geo:
            self.assertAlmostEqual(nifmod._av_transform(out.blocks[c])[0][2], 0.05, places=6)
        self.assertEqual(M.shift_children(n, (0, 0, 0)), n)

    def test_geometry_bounds(self):
        a = sfnif.StaticShape(name=b"A", mesh_path=b"aa\\bb", indices_size=3, num_verts=3,
                              material_path="Materials\\x.mat", sphere=(0, 0, 0.15, 0.2), box=(0, 0, 0.15, 0.04, 0.05, 0.15))
        b = sfnif.StaticShape(name=b"B", mesh_path=b"aa\\cc", indices_size=3, num_verts=3,
                              material_path="Materials\\x.mat", sphere=(0, 0, 0, 1), box=(0.1, 0, 0.02, 0.02, 0.02, 0.02))
        got = M.geometry_bounds(nifmod.serialize(sfnif.build_static_nif(b"Bottle", [a, b])))
        want = [[-0.04, -0.05, 0.0], [0.12, 0.05, 0.3]]
        for g, w in zip(got[0] + got[1], want[0] + want[1]):
            self.assertAlmostEqual(g, w, places=5)
        skinned = sfnif.StaticShape(name=b"S", mesh_path=b"aa\\bb", indices_size=3, num_verts=3,
                                    material_path="Materials\\x.mat", sphere=(0, 0, 0, 1), box=(sfnif.FLT_MAX,) * 6)
        self.assertIsNone(M.geometry_bounds(nifmod.serialize(sfnif.build_static_nif(b"S", [skinned]))))

    def test_item_model_name(self):
        self.assertEqual(M.item_model_name("s2s\\clutter\\wine.nif"), "s2s\\clutter\\wine_item.nif")


class BuildTests(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            conv = os.path.join(tmp, "convert")
            static = nifmod.serialize(sfnif.build_static_nif(b"Wine", [shape(b"A")], collision_blob=b"STATICBOX"))
            os.makedirs(os.path.join(conv, "meshes", "s2s"))
            with open(os.path.join(conv, "meshes", "s2s", "wine.nif"), "wb") as fh:
                fh.write(static)
            sky = {
                0x10: ("ALCH", 0, [(b"EDID", z("FoodWineAlto")), (b"OBND", struct.pack("<6h", -3, -3, 0, 3, 3, 21)),
                                   (b"FULL", struct.pack("<I", 77)), (b"MODL", z("Clutter\\WineBottle01.nif")),
                                   (b"DATA", struct.pack("<f", 0.5)), (b"ENIT", enit(7, M.FOOD))]),
                0x11: ("ALCH", 0, [(b"EDID", z("FoodRareThing")), (b"MODL", z("Clutter\\Unconverted.nif")),
                                   (b"ENIT", enit(1, M.FOOD))]),
                0x100: ("REFR", M.NO_SETTLE, [(b"NAME", struct.pack("<I", 0x10)), (b"XOWN", struct.pack("<I", 0x99))]),
                0x101: ("REFR", 0, [(b"NAME", struct.pack("<I", 0x10))]),
                0x102: ("REFR", 0, [(b"NAME", struct.pack("<I", 0x11))]),
            }
            cell = {"cell": "RiverwoodSleepingGiantInn", "refs": [
                {"formkey": "000100:Skyrim.esm", "type": "Ingestible", "model": "Clutter\\WineBottle01.nif",
                 "pos": [1, 2, 3], "rot": [0, 0, 1], "scale": 1.0},
                {"formkey": "000101:Skyrim.esm", "type": "Ingestible", "model": "Clutter\\WineBottle01.nif",
                 "pos": [4, 5, 6], "rot": [0, 0, 0], "scale": 1.0, "disabled": 1},
                {"formkey": "000102:Skyrim.esm", "type": "Ingestible", "model": "Clutter\\Unconverted.nif",
                 "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0},
                {"formkey": "000103:Skyrim.esm", "type": "Static", "model": "Clutter\\Table.nif",
                 "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0}]}
            manifest = {"meshes\\clutter\\winebottle01.nif": "s2s\\wine.nif"}
            donors = M.starfield_donors([
                sf_alch(0x30, "Drink_NoBody", "nobody.nif", M.FOOD, [[-0.04, -0.04, 0], [0.04, 0.04, 0.3]]),
                sf_alch(0x31, "Drink_Alc_Bottle_Generic_SpaceWine", "wine.nif", M.FOOD,
                        [[-0.05, -0.05, 0], [0.05, 0.05, 0.35]])])
            phys = {"wine.nif": (b"DYNAMICBODY", 0x41, 7, 11)}
            ours_bounds = [[-0.04, -0.04, -0.15], [0.04, 0.04, 0.15]]
            out, nifs = M.build([cell], FakeIndex(sky), manifest, donors, {77: "Alto Wine"}, conv,
                                lambda d: phys.get(d["model"]), lambda m: ours_bounds)
        self.assertEqual(list(out["bases"]), ["000010:Skyrim.esm"])
        b = out["bases"]["000010:Skyrim.esm"]
        self.assertEqual((b["name"], b["kind"], b["donor"], b["donor_edid"], b["model"]),
                         ("Alto Wine", "drink", "00000031", "Drink_Alc_Bottle_Generic_SpaceWine", "s2s\\wine_item.nif"))
        self.assertEqual(b["donors_without_body"], ["Drink_NoBody"])        # better fit but no body: passed over
        self.assertEqual(b["origin_offset_m"], [-0.0, -0.0, -0.15])          # our centre origin onto the donor's base
        self.assertEqual(b["bounds"], [[-0.04, -0.04, 0.0], [0.04, 0.04, 0.3]])
        self.assertEqual((b["skyrim_value"], b["skyrim_weight"]), (7, 0.5))
        self.assertEqual([r["formkey"] for r in out["refs"]], ["000100:Skyrim.esm", "000101:Skyrim.esm"])
        r0, r1 = out["refs"]
        self.assertEqual((r0["no_settle"], r0["owner"], r0["disabled"]), (True, "000099:Skyrim.esm", False))
        self.assertEqual((r1["no_settle"], r1["owner"], r1["disabled"]), (False, None, True))
        self.assertEqual(out["skipped"][0]["edid"], "FoodRareThing")
        self.assertIn("not converted", out["skipped"][0]["why"])
        n = nifs["s2s\\wine_item.nif"]
        self.assertEqual(item_test.donor_physics(n), (b"DYNAMICBODY", 0x41, 7, 11))   # the donor's body, not ours
        parsed = nifmod.parse(n)
        geo = [c for c in nifmod.node_children(parsed, 0) if parsed.type_of(c) == "BSGeometry"]
        self.assertAlmostEqual(nifmod._av_transform(parsed.blocks[geo[0]])[0][2], 0.15, places=6)
        json.dumps(out)                                                    # items.json is plain JSON


if __name__ == "__main__":
    unittest.main()
