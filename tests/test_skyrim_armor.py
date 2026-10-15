"""Skyrim armor inventory (ARMO / ARMA) and skinned armor NIFs, on synthetic plugins and meshes (no game data)."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import skyrimarmor  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402

NORD, KHAJIIT, NORD_VAMP = 0x13746, 0x13745, 0x88794


def z(s):
    return s.encode() + b"\0"


def bod2(flags, kind):
    return (b"BOD2", struct.pack("<II", flags, kind))


def dnam(male_slider, female_slider, prio=(5, 5)):
    return (b"DNAM", bytes([prio[0], prio[1], male_slider, female_slider, 0, 0, 1, 0]) + struct.pack("<f", 0.0))


def armor_esm():
    races = [rec(b"RACE", NORD, [(b"EDID", z("NordRace"))]), rec(b"RACE", KHAJIIT, [(b"EDID", z("KhajiitRace"))]),
             rec(b"RACE", NORD_VAMP, [(b"EDID", z("NordRaceVampire"))])]
    arma = [
        rec(b"ARMA", 0x100, [(b"EDID", z("IronCuirassAA")), bod2(0x4 | 0x10 | 0x100, 1), (b"RNAM", struct.pack("<I", NORD)),
                             dnam(0x2, 0x2), (b"MOD2", z("Armor\\Iron\\Male\\CuirassLight_1.nif")),
                             (b"MOD3", z("Armor\\Iron\\F\\CuirassLight_1.nif")),
                             (b"MOD4", z("Armor\\Iron\\Male\\1stPersonCuirass_1.nif")),
                             (b"MODL", struct.pack("<I", NORD_VAMP))], compress=True),
        rec(b"ARMA", 0x101, [(b"EDID", z("IronHelmetAA")), bod2(0x2 | 0x2000, 1), (b"RNAM", struct.pack("<I", NORD)),
                             dnam(0, 0), (b"MOD2", z("Armor\\Iron\\Male\\Helmet.nif")),
                             (b"MOD3", z("Armor\\Iron\\Male\\Helmet.nif"))]),
        rec(b"ARMA", 0x102, [(b"EDID", z("IronHelmetKhajiitAA")), bod2(0x2, 1), (b"RNAM", struct.pack("<I", KHAJIIT)),
                             dnam(0, 0), (b"MOD2", z("Armor\\Iron\\Male\\HelmetKhajiit.nif"))]),
    ]
    armo = [
        rec(b"ARMO", 0x200, [(b"EDID", z("ArmorIronCuirass")), (b"MOD2", z("Armor\\Iron\\Male\\CuirassGND.nif")),
                             bod2(0x4, 1), (b"RNAM", struct.pack("<I", NORD)), (b"MODL", struct.pack("<I", 0x100)),
                             (b"DATA", struct.pack("<if", 125, 30.0)), (b"DNAM", struct.pack("<i", 2500))]),
        rec(b"ARMO", 0x201, [(b"EDID", z("ArmorIronHelmet")), (b"BODT", struct.pack("<IB3xI", 0x2, 0, 1)),
                             (b"MODL", struct.pack("<I", 0x101)), (b"MODL", struct.pack("<I", 0x102)),
                             (b"DATA", struct.pack("<if", 60, 5.0)), (b"DNAM", struct.pack("<i", 1500))]),
        rec(b"ARMO", 0x202, [(b"EDID", z("EnchArmorIronCuirassHealth01")), bod2(0x4, 1),
                             (b"MODL", struct.pack("<I", 0x100)), (b"TNAM", struct.pack("<I", 0x200))]),
        rec(b"ARMO", 0x203, [(b"EDID", z("SkinNaked")), bod2(0x4 | 0x8 | 0x80, 2),
                             (b"MODL", struct.pack("<I", 0x999))], ),
    ]
    armo[3] = armo[3][:8] + struct.pack("<I", skyrimarmor.NON_PLAYABLE_RECORD) + armo[3][12:]   # record flag
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800))])
    return tes4 + grup(b"RACE", 0, races) + grup(b"ARMO", 0, armo) + grup(b"ARMA", 0, arma)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esm = os.path.join(self.tmp.name, "Skyrim.esm")
        with open(self.esm, "wb") as f:
            f.write(armor_esm())

    def tearDown(self):
        self.tmp.cleanup()

    def test_records(self):
        inv = skyrimarmor.read_armor(self.esm)
        cu = inv["armo"][0x200]
        self.assertEqual((cu["edid"], cu["slots"], cu["armor_type"], cu["rating"], cu["value"], cu["weight"]),
                         ("ArmorIronCuirass", [32], "heavy", 25.0, 125, 30.0))
        self.assertEqual((cu["world_model"], cu["race"], cu["addons"]), ("Armor\\Iron\\Male\\CuirassGND.nif", "NordRace", [0x100]))
        helm = inv["armo"][0x201]                                      # older BODT form
        self.assertEqual((helm["slots"], helm["armor_type"], helm["addons"]), ([31], "heavy", [0x101, 0x102]))
        self.assertEqual(inv["armo"][0x202]["template"], 0x200)
        self.assertTrue(inv["armo"][0x203]["non_playable"])
        aa = inv["arma"][0x100]                                        # compressed record
        self.assertEqual((aa["slots"], aa["race"], aa["extra_races"], aa["weight_slider"], aa["priority"]),
                         ([32, 34, 38], "NordRace", ["NordRaceVampire"], (True, True), (5, 5)))
        self.assertEqual(aa["male_1st"], "Armor\\Iron\\Male\\1stPersonCuirass_1.nif")
        self.assertEqual(skyrimarmor.worn_models(aa), [
            "Armor\\Iron\\Male\\CuirassLight_0.nif", "Armor\\Iron\\Male\\CuirassLight_1.nif",
            "Armor\\Iron\\F\\CuirassLight_0.nif", "Armor\\Iron\\F\\CuirassLight_1.nif"])
        self.assertEqual(skyrimarmor.worn_models(inv["arma"][0x101]), ["Armor\\Iron\\Male\\Helmet.nif"])

    def test_summary(self):
        s = skyrimarmor.summary(skyrimarmor.read_armor(self.esm))
        self.assertEqual((s["armo"], s["armo_playable"], s["arma"]), (4, 3, 3))
        self.assertEqual(s["armor_types"], {"heavy": 3})
        self.assertEqual(s["slots"], {"32 Body": 2, "31 Hair": 1})
        self.assertEqual((s["armo_with_template"], s["addons_not_in_plugin"], s["arma_weight_slider"]), (1, 1, 1))
        self.assertEqual(s["arma_races"], {"NordRace": 2, "KhajiitRace": 1})
        self.assertEqual((s["worn_meshes"], s["first_person_meshes"], s["female_specific_arma"]), (6, 1, 1))
        self.assertEqual(skyrimarmor.slot_label(61), "61 FX01")


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------------------------------------------ skinned meshes
from fo4sf import nif, skyrimskin  # noqa: E402
import skyrim_fixtures as F  # noqa: E402

BONES = [b"NPC Spine2 [Spn2]", b"NPC L UpperArm [LUar]", b"NPC L Forearm [LLar]"]
# a sleeve: 6 vertices; partition 0 (body part 32) = vertices 0-2, partition 1 (34, forearms) = vertices 3-5
VERTS = [(0, 0, 100), (10, 0, 100), (0, 10, 100), (20, 0, 100), (30, 0, 100), (20, 10, 100)]
WEIGHTS = [[(0, 1.0)], [(0, 0.5), (1, 0.5)], [(1, 1.0)], [(1, 0.25), (2, 0.75)], [(2, 1.0)], [(2, 1.0)]]
PARTS = [(32, [0, 1, 2], [0, 1]), (34, [3, 4, 5], [2, 1])]       # (body part, vertices, palette: global bone ids)


def skinned_nif_bytes(store_weights=True):
    n = F.SseNif()
    root = n.reserve("NiNode")
    bone_blocks = []
    for name in BONES:
        b = n.reserve("NiNode")
        n.node(b, name, [])
        bone_blocks.append(b)
    shader = n.lighting("textures\\armor\\iron\\cuirass.dds", "textures\\armor\\iron\\cuirass_n.dds")
    # skin data: identity rotation, bind translation = -bone position; weights per bone if stored
    sd = struct.pack("<9f3ff", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0) + struct.pack("<IB", len(BONES), int(store_weights))
    for b in range(len(BONES)):
        sd += struct.pack("<9f3ff", 1, 0, 0, 0, 1, 0, 0, 0, 1, -5.0 * b, 0, -100, 1.0) + struct.pack("<4f", 0, 0, 0, 50)
        lst = [(v, w) for v, ws in enumerate(WEIGHTS) for bb, w in ws if bb == b]
        sd += struct.pack("<H", len(lst)) + (b"".join(struct.pack("<Hf", v, w) for v, w in lst) if store_weights else b"")
    data = n.add("NiSkinData", sd)
    # global vertex buffer: pos(12) + bitangent x(4) + uv(4) + normal(4) + tangent(4) + skin(12) = 40 bytes
    desc = 10 | (4 << 8) | (5 << 16) | (6 << 20) | (7 << 28) | (0x5B << 44)
    vb = b""
    owner = {v: pal for _bp, vs, pal in PARTS for v in vs}
    for v, (x, y, zz) in enumerate(VERTS):
        pal = owner[v]
        local = [(pal.index(b), w) for b, w in WEIGHTS[v]] + [(0, 0.0)] * (4 - len(WEIGHTS[v]))
        vb += struct.pack("<3ff", x, y, zz, 0.0) + struct.pack("<2e", v / 6, 0.5) + bytes([127, 127, 255, 0]) \
            + bytes([255, 127, 127, 0]) + struct.pack("<4e", *[w for _, w in local]) + bytes(i for i, _ in local)
    sp = struct.pack("<IIIQ", len(PARTS), len(vb), 40, desc) + vb
    for _bp, vs, pal in PARTS:
        sp += struct.pack("<5H", len(vs), 1, len(pal), 0, 4) + struct.pack(f"<{len(pal)}H", *pal)
        sp += b"\x01" + struct.pack(f"<{len(vs)}H", *vs)                     # vertex map
        sp += b"\x01" + b"".join(struct.pack("<4f", 1, 0, 0, 0) for _ in vs)  # weights (unused here)
        sp += b"\x01" + struct.pack("<3H", 0, 1, 2)                            # local triangle
        sp += b"\x01" + bytes(4 * len(vs))                                     # bone indices
        sp += b"\x00\x01" + struct.pack("<Q", desc) + struct.pack("<3H", *vs)  # LOD, global VB, desc, global tri
    part = n.add("NiSkinPartition", sp)
    inst = n.add("BSDismemberSkinInstance", struct.pack("<iiiI", data, part, root, len(BONES))
                 + struct.pack(f"<{len(BONES)}i", *bone_blocks) + struct.pack("<I", len(PARTS))
                 + b"".join(struct.pack("<HH", 257, bp) for bp, _v, _p in PARTS))
    body = n.av(n.s(b"Sleeve")) + struct.pack("<4f", 0, 0, 0, 1) + struct.pack("<iii", inst, shader, -1) \
        + struct.pack("<Q", desc) + struct.pack("<HHI", 2, len(VERTS), 0) + struct.pack("<I", 0)
    sh = n.add("BSTriShape", body)
    n.node(root, b"Armor", bone_blocks + [sh])
    return n.bytes()


def skinned_nif(store_weights=True):
    return nif.parse(skinned_nif_bytes(store_weights))


class SkinnedTests(unittest.TestCase):
    def check_shape(self, s, source):
        self.assertEqual(s.bones, BONES)
        self.assertEqual(s.positions, [tuple(map(float, v)) for v in VERTS])
        self.assertEqual(s.triangles, [(0, 1, 2), (3, 4, 5)])
        self.assertEqual(s.weight_source, source)
        for v, want in enumerate(WEIGHTS):
            got = dict(s.weights[v])
            self.assertEqual(set(got), {b for b, _ in want}, v)
            for b, w in want:
                self.assertAlmostEqual(got[b], w, places=3)
        self.assertEqual(s.body_parts, [32, 34])
        self.assertEqual([p["bones"] for p in s.partitions], [[BONES[0], BONES[1]], [BONES[2], BONES[1]]])
        self.assertEqual(s.binds[2].translation, (-10.0, 0.0, -100.0))
        self.assertAlmostEqual(s.uvs[3][0], 0.5, places=2)
        c = skyrimskin.check(s)
        self.assertEqual((c["unweighted_vertices"], c["max_influences"], c["out_of_range_triangles"]), (0, 2, 0))

    def test_weights_from_skin_data(self):
        s, = skyrimskin.skinned_shapes(skinned_nif(store_weights=True))
        self.check_shape(s, "skin_data")

    def test_weights_from_partition_vertices_use_each_partitions_palette(self):
        s, = skyrimskin.skinned_shapes(skinned_nif(store_weights=False))
        self.check_shape(s, "partition_vertices")

    def test_unskinned_meshes_have_no_skinned_shapes(self):
        self.assertEqual(skyrimskin.skinned_shapes(nif.parse(F.rock_nif())), [])
