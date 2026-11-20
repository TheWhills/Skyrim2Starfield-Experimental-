"""scripts/interior/item_test.py: one Skyrim item as a Starfield item (record copied from a vanilla drink, our model
with the donor's physics body). Synthetic records and NIFs only."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))

from fo4sf import nif as nifmod, sfnif, sfplugin  # noqa: E402
import item_test as T  # noqa: E402

z = sfplugin.zs
H = bytes(24)


def shape(name=b"Bottle"):
    return sfnif.StaticShape(name=name, mesh_path=b"aa\\bb", indices_size=3, num_verts=3,
                             material_path="Materials\\s2s\\wine.mat", sphere=(0, 0, 0, 1), box=(0, 0, 0, 1, 1, 1))


class RecordTests(unittest.TestCase):
    def test_skyrim_items_bottles_first(self):
        recs = [(b"ALCH", H, [(b"EDID", z("FoodWineAlto")), (b"FULL", struct.pack("<I", 77)),
                              (b"MODL", z("Clutter\\Food\\WineJug.nif"))], 1),
                (b"ALCH", H, [(b"EDID", z("FoodWineBottle02")), (b"FULL", z("Wine")),
                              (b"MODL", z("Clutter\\Bottles\\WineBottle02.nif"))], 2),
                (b"ALCH", H, [(b"EDID", z("FoodBread")), (b"MODL", z("bread.nif"))], 3),
                (b"ALCH", H, [(b"EDID", z("FoodWineNoModel"))], 4)]
        got = T.skyrim_items(recs)
        self.assertEqual([r[0] for r in got], ["FoodWineBottle02", "FoodWineAlto"])
        self.assertEqual((got[0][3], got[1][3]), ("Wine", 77))

    def test_donors_in_pattern_order(self):
        recs = [(b"ALCH", H, [(b"EDID", z("Drink_Whiskey")), (b"MODL", z("Items\\whiskey.nif"))], 1),
                (b"ALCH", H, [(b"EDID", z("Drink_RedWine")), (b"MODL", z("Items\\wine_bottle.nif"))], 2),
                (b"ALCH", H, [(b"EDID", z("Food_Pear")), (b"MODL", z("Items\\pear.nif"))], 3)]
        self.assertEqual([c[0] for c in T.donor_candidates(recs)], ["Drink_RedWine", "Drink_Whiskey"])

    def test_item_record(self):
        donor = (b"ALCH", H, [(b"EDID", z("Drink_RedWine")), (b"FULL", struct.pack("<I", 5)),
                              (b"MODL", z("Items\\wine.nif")), (b"ENIT", b"\1\2")], 0x123)
        rec = T.item_record(donor, "S2S_FoodWineBottle02", "Wine", "s2s\\clutter\\wine.nif", 0x01000800)
        d = dict(rec[2])
        self.assertEqual((d[b"EDID"], d[b"FULL"], d[b"MODL"], d[b"ENIT"]),
                         (z("S2S_FoodWineBottle02"), z("Wine"), z("s2s\\clutter\\wine.nif"), b"\1\2"))
        self.assertEqual(rec[3], 0x01000800)


class PhysicsTests(unittest.TestCase):
    def test_donor_body_on_our_model(self):
        donor = sfnif.build_static_nif(b"Donor", [shape()], collision_blob=b"DYNAMICBODY")
        for i in range(len(donor.blocks)):                    # a dynamic item's flags / BSX, as vanilla
            if donor.type_of(i) == "bhkNPCollisionObject":
                donor.blocks[i] = struct.pack("<iHiI", 0, 0x41, 3, 7)
            if donor.type_of(i) == "BSXFlags":
                donor.blocks[i] = donor.blocks[i][:4] + struct.pack("<I", 11)
        got = T.donor_physics(nifmod.serialize(donor))
        self.assertEqual(got, (b"DYNAMICBODY", 0x41, 7, 11))
        ours = nifmod.serialize(sfnif.build_static_nif(b"Wine", [shape(b"A"), shape(b"B")]))
        self.assertIsNone(T.donor_physics(ours))
        out = nifmod.parse(T.with_physics(ours, *got))
        back = T.donor_physics(nifmod.serialize(out))
        self.assertEqual(back, got)
        root = out.blocks[0]
        _n, n_extra = struct.unpack_from("<iI", root, 0)
        coll, = struct.unpack_from("<i", root, 8 + 4 * n_extra + 8 + 52)
        self.assertEqual(out.type_of(coll), "bhkNPCollisionObject")
        self.assertEqual(sum(1 for i in range(len(out.blocks)) if out.type_of(i) == "BSGeometry"), 2)


if __name__ == "__main__":
    unittest.main()
