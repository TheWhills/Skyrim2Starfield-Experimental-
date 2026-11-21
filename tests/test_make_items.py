"""scripts/interior/make_items.py: Skyrim's placed food / drink / potions as Starfield items (a donor ALCH of the same
kind and closest size, its physics body on our model). Synthetic records and NIFs only."""
import json
import math
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


class ClutterTests(unittest.TestCase):
    """2026-11-21 (owner: "lets do clutter next"): Skyrim MiscItem references -> copies of Starfield MISC items."""

    def misc(self, fid, edid, model="plate.nif", extra=()):
        return (b"MISC", H, [(b"EDID", z(edid)), (b"OBND", struct.pack("<6f", -0.1, -0.1, 0, 0.1, 0.1, 0.02)),
                             (b"MODL", z(model)), *extra, (b"DATA", struct.pack("<if", 5, 1.0))], fid)

    def test_misc_donors(self):
        kw = {0x50: "ResourceTypeInorganic", 0x51: "ContrabandKeyword", 0x52: "ObjectTypeClutter"}
        recs = [self.misc(1, "Clutter_Plate01"),
                self.misc(2, "InorgCommonIron"),                                  # a resource
                self.misc(3, "Credits"),
                self.misc(4, "MQ101_Artifact"),                                   # a quest item
                self.misc(5, "Plate_Scripted", extra=[(b"VMAD", b"\0" * 6)]),
                self.misc(6, "Plate_Featured", extra=[(b"FIMD", struct.pack("<I", 9))]),
                self.misc(7, "Clutter_Mug", extra=[(b"KSIZ", struct.pack("<I", 1)), (b"KWDA", struct.pack("<I", 0x52))]),
                self.misc(8, "Clutter_Smuggled", extra=[(b"KSIZ", struct.pack("<I", 1)), (b"KWDA", struct.pack("<I", 0x51))]),
                self.misc(9, "Clutter_Ore", extra=[(b"KSIZ", struct.pack("<I", 1)), (b"KWDA", struct.pack("<I", 0x50))]),
                sf_alch(10, "Drink_Alc_Wine", "wine.nif", M.FOOD, [[-0.04, -0.04, 0], [0.04, 0.04, 0.3]])]
        got = {d["edid"]: (d["sig"], d["kinds"]) for d in M.starfield_donors(recs, kw)}
        self.assertEqual(got, {"Clutter_Plate01": ("MISC", {"misc"}), "Clutter_Mug": ("MISC", {"misc"}),
                               "Drink_Alc_Wine": ("ALCH", {"drink"})})

    def test_first_clutter_run_fixes(self):
        # owner's run 2026-11-21: mission cargo / FF quest donors out, dishes and tools to their Starfield families
        recs = [self.misc(1, "MissionCargoType15"), self.misc(2, "FFParadisoZ01_Parts"), self.misc(3, "RobotMachinePart01"),
                self.misc(4, "Kitchen_Mug01"), self.misc(5, "Tool_Hammer01")]
        donors = M.starfield_donors(recs)
        self.assertEqual([d["edid"] for d in donors], ["RobotMachinePart01", "Kitchen_Mug01", "Tool_Hammer01"])
        self.assertEqual(M.skyrim_family("misc", "BasicTankard01"), "kitchen")
        self.assertEqual(M.skyrim_family("misc", "CastIronPotSmall01"), "kitchen")
        self.assertEqual(M.skyrim_family("misc", "Hammer01"), "tool")
        self.assertEqual(M.skyrim_family("misc", "Basket01"), "")
        tankard = [[-0.08, -0.08, 0], [0.08, 0.08, 0.17]]
        self.assertEqual(M.rank_donors(tankard, "misc", donors, "kitchen")[0]["edid"], "Kitchen_Mug01")
        self.assertEqual(M.pretty_name("BasicFork01"), "Fork")
        self.assertEqual(M.pretty_name("BasicWoodenBowl01"), "Wooden Bowl")
        self.assertEqual(M.pretty_name("Quill01"), "Quill")

    def test_plate_takes_a_thin_donor(self):
        with tempfile.TemporaryDirectory() as tmp:
            conv = os.path.join(tmp, "convert")
            os.makedirs(os.path.join(conv, "meshes", "s2s"))
            with open(os.path.join(conv, "meshes", "s2s", "plate.nif"), "wb") as fh:
                fh.write(nifmod.serialize(sfnif.build_static_nif(b"P", [shape(b"A")], collision_blob=b"BOX")))
            sky = {0x20: ("MISC", 0, [(b"EDID", z("BasicWoodenPlate01")), (b"MODL", z("Clutter\\Plate.nif"))]),
                   0x200: ("REFR", 0, [(b"NAME", struct.pack("<I", 0x20))])}
            cell = {"cell": "Inn", "refs": [{"formkey": "000200:Skyrim.esm", "type": "MiscItem",
                                             "model": "Clutter\\Plate.nif", "pos": [0, 0, 0], "rot": [0, 0, 0],
                                             "scale": 1.0}]}
            def tray(fid, edid, h):
                return (b"MISC", H, [(b"EDID", z(edid)), (b"OBND", struct.pack("<6f", -0.15, -0.3, 0, 0.15, 0.3, h)),
                                     (b"MODL", z(edid + ".nif"))], fid)
            donors = M.starfield_donors([tray(1, "Kitchen_TrayDeep", 0.057), tray(2, "Kitchen_TrayFlat", 0.015)])
            out, _ = M.build([cell], FakeIndex(sky), {"meshes\\clutter\\plate.nif": "s2s\\plate.nif"}, donors, {},
                             conv, lambda d: (b"DYN", 0x41, 7, 11), lambda m: [[-0.15, -0.3, 0], [0.15, 0.3, 0.057]])
        b = out["bases"]["000020:Skyrim.esm"]
        self.assertEqual((b["family"], b["donor_edid"]), ("kitchen", "Kitchen_TrayFlat"))
        self.assertEqual(b["hull_m"], [[-0.15, -0.3, 0.0], [0.15, 0.3, 0.015]])

    def test_skyrim_misc_kind_and_data(self):
        self.assertEqual(M.skyrim_kind("MISC", "BasicPlate01", "clutter\\plate.nif", 0), "misc")
        info = M.skyrim_base([(b"EDID", z("BasicTankard01")), (b"MODL", z("Clutter\\Tankard.nif")),
                              (b"DATA", struct.pack("<if", 3, 2.5))])
        self.assertEqual((info["value"], info["weight"]), (3, 2.5))                 # MISC DATA: value, weight

    def test_build_clutter_and_gold(self):
        with tempfile.TemporaryDirectory() as tmp:
            conv = os.path.join(tmp, "convert")
            os.makedirs(os.path.join(conv, "meshes", "s2s"))
            with open(os.path.join(conv, "meshes", "s2s", "tankard.nif"), "wb") as fh:
                fh.write(nifmod.serialize(sfnif.build_static_nif(b"T", [shape(b"A")], collision_blob=b"BOX")))
            sky = {0x20: ("MISC", 0, [(b"EDID", z("BasicTankard01")), (b"MODL", z("Clutter\\Tankard.nif")),
                                      (b"DATA", struct.pack("<if", 3, 2.5))]),
                   0x21: ("MISC", 0, [(b"EDID", z("Gold001")), (b"MODL", z("Clutter\\Tankard.nif"))]),
                   0x200: ("REFR", 0, [(b"NAME", struct.pack("<I", 0x20))]),
                   0x201: ("REFR", 0, [(b"NAME", struct.pack("<I", 0x21))])}
            cell = {"cell": "RiverwoodRiverwoodTrader", "refs": [
                {"formkey": "000200:Skyrim.esm", "type": "MiscItem", "model": "Clutter\\Tankard.nif",
                 "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0},
                {"formkey": "000201:Skyrim.esm", "type": "MiscItem", "model": "Clutter\\Tankard.nif",
                 "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0}]}
            donors = M.starfield_donors([self.misc(0x40, "Clutter_Mug", "mug.nif"),
                                         sf_alch(0x41, "Drink_Alc_Wine", "wine.nif", M.FOOD,
                                                 [[-0.1, -0.1, 0], [0.1, 0.1, 0.02]])])
            out, _nifs = M.build([cell], FakeIndex(sky), {"meshes\\clutter\\tankard.nif": "s2s\\tankard.nif"},
                                 donors, {}, conv, lambda d: (b"DYN", 0x41, 7, 11),
                                 lambda m: [[-0.1, -0.1, 0], [0.1, 0.1, 0.02]])
        b = out["bases"]["000020:Skyrim.esm"]
        self.assertEqual((b["kind"], b["record"], b["donor_edid"], b["name"]),
                         ("misc", "MISC", "Clutter_Mug", "Tankard"))          # no FULL: a name from the EditorID          # a MISC donor, never the drink
        self.assertEqual([r["formkey"] for r in out["refs"]], ["000200:Skyrim.esm"])
        self.assertIn("credits", out["skipped"][0]["why"])                           # gold left static for now


class StackTests(unittest.TestCase):
    """2026-11-21 (owner, in game: "the food is spawning slightly under the plates")."""

    def ref(self, fk, base, pos_m, rot=(0, 0, 0), cell="Inn"):
        return {"formkey": fk, "cell": cell, "base": base, "pos": [v * M.U for v in pos_m], "rot": list(rot),
                "scale": 1.0}

    def test_holder_target_is_a_thin_base(self):
        self.assertEqual(M.holder_target([[-0.15, -0.3, 0.0], [0.15, 0.3, 0.057]]),
                         [[-0.15, -0.3, 0.0], [0.15, 0.3, M.HOLDER_HEIGHT_M]])

    def test_world_box_turns_and_skips_tipped(self):
        r = self.ref("a", "b", (1.0, 2.0, 0.5), rot=(0, 0, math.pi / 2))
        box = M.world_box(r, [[-0.1, -0.3, 0.0], [0.1, 0.3, 0.05]])
        for g, w in zip(box, (0.7, 1.9, 0.5, 1.3, 2.1, 0.55)):
            self.assertAlmostEqual(g, w, places=6)
        self.assertIsNone(M.world_box(self.ref("a", "b", (0, 0, 0), rot=(1.2, 0, 0)), [[0, 0, 0], [1, 1, 1]]))

    def test_food_on_a_plate_is_lifted(self):
        bases = {"plate": {"hull_m": [[-0.15, -0.3, 0.0], [0.15, 0.3, 0.015]]},
                 "salmon": {"hull_m": [[-0.1, -0.13, 0.0], [0.1, 0.13, 0.033]]}}
        refs = [self.ref("p", "plate", (1.0, 1.0, 1.0)), self.ref("f", "salmon", (1.0, 1.05, 1.008)),
                self.ref("g", "salmon", (5.0, 5.0, 1.0)),                        # on the table: left alone
                self.ref("h", "salmon", (1.0, 1.0, 1.008), cell="Other")]       # another cell: no plate there
        got = M.settle_stacks(refs, bases)
        self.assertEqual([(x["formkey"], x["on"]) for x in got["lifted"]], [("f", "p")])
        self.assertAlmostEqual(refs[1]["pos"][2] / M.U, 1.015 + M.STACK_GAP_M, places=4)
        self.assertEqual(refs[2]["pos"][2], 1.0 * M.U)
        self.assertEqual(got["kept_static"], [])

    def test_basket_of_potatoes_stays_static(self):
        bases = {"basket": {"hull_m": [[-0.25, -0.25, 0.0], [0.25, 0.25, 0.5]]},
                 "potato": {"hull_m": [[-0.08, -0.08, 0.0], [0.08, 0.08, 0.17]]}}
        refs = [self.ref("b", "basket", (2.0, 2.0, 0.0)), self.ref("p1", "potato", (2.0, 2.0, 0.05)),
                self.ref("p2", "potato", (2.05, 2.0, 0.2))]
        got = M.settle_stacks(refs, bases)
        self.assertEqual(got["kept_static"], [{"formkey": "b", "holds": "p2"}])
        self.assertEqual([r["formkey"] for r in refs], ["p1", "p2"])           # the basket stays a static
        # with the basket a static, p2 (bottom 0.2) starts inside p1 (0.05 .. 0.22): lifted onto it
        self.assertEqual([(x["formkey"], x["on"]) for x in got["lifted"]], [("p2", "p1")])


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
                 "pos": [400, 500, 6], "rot": [0, 0, 0], "scale": 1.0, "disabled": 1},   # apart: not a stack
                {"formkey": "000102:Skyrim.esm", "type": "Ingestible", "model": "Clutter\\Unconverted.nif",
                 "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0},
                {"formkey": "000103:Skyrim.esm", "type": "Static", "model": "Clutter\\Table.nif",
                 "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0}]}
            manifest = {"meshes\\clutter\\winebottle01.nif": "s2s\\wine.nif"}
            donors = M.starfield_donors([
                sf_alch(0x30, "Drink_Alc_NoBody", "nobody.nif", M.FOOD, [[-0.04, -0.04, 0], [0.04, 0.04, 0.3]]),
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
        self.assertEqual(b["donors_without_body"], ["Drink_Alc_NoBody"])    # better fit but no body: passed over
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
