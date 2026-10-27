"""fo4sf.skyrimweapon, fo4sf.sfplugin and scripts/armor/weapon_test_pack.py on synthetic games (no game data)."""
import contextlib
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import bsa, fo4land, nif, retarget as R, sfmesh, sfnif, sfplugin, skeletonmap as M, skyrimnif  # noqa: E402
from fo4sf import skyrimweapon as W, textures  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
import weapon_test_pack as P  # noqa: E402

import numpy as np  # noqa: E402

HAND = M.SKYRIM_HAND_IN_WEAPON


def sword_nif():
    """A Skyrim one-handed sword: a blade along +Y from the grip, and a scabbard under a node named Scb."""
    n = F.SseNif()
    root = n.reserve("BSFadeNode")
    scb_node = n.reserve("NiNode")
    blade = n.trishape(b"IronSword", [(0, 0, 0), (2, 60, 0), (-2, 60, 0), (0, -10, 1)], [(0, 0), (1, 0), (0, 1), (1, 1)],
                       [(0, 1, 2), (0, 2, 3)],
                       shader=n.lighting("textures\\weapons\\iron\\sword.dds", "textures\\weapons\\iron\\sword_n.dds"))
    scb = n.trishape(b"IronSwordScabbard", [(0, 0, 0), (3, 62, 0), (-3, 62, 0)], [(0, 0), (1, 0), (0, 1)],
                     [(0, 1, 2)],
                     shader=n.lighting("textures\\weapons\\iron\\sword.dds", "textures\\weapons\\iron\\sword_n.dds"))
    n.node(scb_node, b"Scb", [scb])
    n.node(root, b"WeaponSword", [blade, scb_node])
    return n.bytes()


def skyrim_esm(path):
    subs = [(b"EDID", b"IronSword\0"), (b"MODL", b"Weapons\\Iron\\LongSword.nif\0"),
            (b"DATA", struct.pack("<IfH", 25, 9.0, 7)), (b"DNAM", bytes([1, 0, 0, 0]) + struct.pack("<ff", 1.0, 1.0))]
    header = struct.pack("<4sIII", b"WEAP", 0, 0, 0) + bytes(8)
    data = sfplugin.build([(b"WEAP", header, subs, 0x00012EB7)], {"hedr_version": 1.71, "form_version": 44}, masters=())
    with open(path, "wb") as fh:
        fh.write(data)


def starfield_esm(path):
    kw = struct.pack("<4sIII", b"KYWD", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
    wp = struct.pack("<4sIII", b"WEAP", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
    recs = [(b"KYWD", kw, [(b"EDID", b"AnimSword\0")], 0x000A0001),
            (b"KYWD", kw, [(b"EDID", b"WeaponTypeMelee1H\0")], 0x000A0002),
            (b"KYWD", kw, [(b"EDID", b"ArmorTypeApparelOrNakedBody\0")], 0x000A0003),
            (b"KYWD", kw, [(b"EDID", b"ArmorTypeSpacesuitBody\0")], 0x000A0004),
            (b"KYWD", kw, [(b"EDID", b"ArmorTypeSpacesuitBackpack\0")], 0x000A0005),
            (b"WEAP", wp, [(b"EDID", b"Melee_Knife\0"), (b"KWDA", struct.pack("<I", 0x000A0002)),
                           (b"MODL", b"Weapons\\Knife\\Knife.nif\0")], 0x000B0001),
            (b"WEAP", wp, [(b"EDID", b"Melee_Sword\0"), (b"FULL", struct.pack("<I", 1234)),
                           (b"DESC", struct.pack("<I", 99)), (b"KWDA", struct.pack("<2I", 0x000A0002, 0x000A0001)),
                           (b"MODL", b"Weapons\\Sword\\Sword.nif\0"), (b"DNAM", b"\x01" * 16)], 0x000B0002)]
    ar = struct.pack("<4sIII", b"ARMA", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
    ao = struct.pack("<4sIII", b"ARMO", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
    recs += [(b"ARMA", ar, [(b"EDID", b"AA_Nightwear_01\0"), (b"BO64", struct.pack("<Q", 1 << 3)),
                            (b"MOD2", b"Clothes\\Nightwear_M.nif\0"), (b"MOD3", b"Clothes\\Nightwear_F.nif\0"),
                            (b"MOD4", b"Clothes\\Nightwear_M_1st.nif\0"), (b"RNAM", struct.pack("<I", 0x347D))],
              0x000C0001),
             (b"ARMO", ao, [(b"EDID", b"Clothes_Nightwear_01\0"), (b"FULL", struct.pack("<I", 77)),
                            (b"KSIZ", struct.pack("<I", 1)), (b"KWDA", struct.pack("<I", 0x000A0003)),
                            (b"INDX", struct.pack("<H", 0)), (b"MODL", struct.pack("<I", 0x000C0001))], 0x000C0002)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))


class WeaponFrameTests(unittest.TestCase):
    def test_handle_into_the_fist_and_blade_along_z(self):
        rot, trans = W.weapon_frame()
        apply = lambda p: tuple(sum(rot[3 * r + c] * p[c] for c in range(3)) + trans[r] for r in range(3))  # noqa
        _h, gt, gq = M.GRIP["weapon"]
        gq = np.array(gq) / np.linalg.norm(gq)
        wrist_sf = -R.qrot(R.qinv(gq), np.array(gt)) / W.UNIT                  # Starfield wrist in WEAPON frame
        self.assertTrue(np.allclose(apply(HAND), wrist_sf, atol=1e-6))          # Skyrim's hand -> Starfield's wrist
        tip = np.array(apply((0, 60, 0))) - np.array(apply((0, 0, 0)))
        self.assertTrue(np.allclose(tip / np.linalg.norm(tip), [0, 0, 1], atol=1e-9))   # blade +Y -> +Z
        # consistent with the clips: Starfield WEAPON = Skyrim Weapon * WEAPON_AXES
        a = np.array(M.WEAPON_AXES["weapon"][1], float)
        a /= np.linalg.norm(a)
        for v in np.eye(3):
            self.assertTrue(np.allclose(R.qrot(a, np.array(apply(tuple(v * 10)) - np.array(apply((0, 0, 0))))),
                                        v * 10, atol=1e-9))

    def test_scabbard_dropped_and_geometry_moved(self):
        n = nif.parse(sword_nif())
        shapes = skyrimnif.trishapes(n)
        rep = {}
        out = W.weapon_shapes(n, shapes, rep)
        self.assertEqual(rep["scabbard_shapes_dropped"], 1)
        self.assertEqual([s.name for s in out], [b"IronSword"])
        rot, trans = W.weapon_frame()
        self.assertTrue(np.allclose(out[0].translation, trans))                 # the blade node sat at the origin


class LeftBladeTests(unittest.TestCase):
    def test_left_frame_hand_onto_wrist_and_blade_along_z(self):
        rot, trans = W.left_weapon_frame()
        apply = lambda p: np.array([sum(rot[3 * r + c] * p[c] for c in range(3)) + trans[r] for r in range(3)])  # noqa
        _h, gt, gq = M.LEFT_GRIP["weaponleft"]
        gq = np.array(gq) / np.linalg.norm(gq)
        wrist = -R.qrot(R.qinv(gq), np.array(gt)) / W.UNIT
        self.assertTrue(np.allclose(apply(M.SKYRIM_HAND_IN_SHIELD), wrist, atol=1e-6))
        tip = apply((0, 60, 0)) - apply((0, 0, 0))                                  # Shield +Y: the blade
        self.assertTrue(np.allclose(tip / np.linalg.norm(tip), [0, 0, 1], atol=1e-3))   # +Z, as the right blade

    def test_left_grip_adjust(self):
        base = W.left_wrist_frame()
        self.assertEqual(W.adjusted_left_wrist_frame(), base)
        rot, trans = W.adjusted_left_wrist_frame(move_cm=(1.0, 0.0, -2.0))
        self.assertTrue(np.allclose(rot, base[0]))
        self.assertTrue(np.allclose(np.array(trans) - np.array(base[1]), [0.7, 0.0, -1.4]))   # 1 cm = 0.7 units
        _h, gt, _q = M.LEFT_GRIP["weaponleft"]
        c = np.array(gt) / W.UNIT
        rot2, trans2 = W.adjusted_left_wrist_frame(turn_deg=(0.0, 0.0, 90.0))
        R0, R2 = np.array(base[0]).reshape(3, 3), np.array(rot2).reshape(3, 3)
        Rz = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
        self.assertTrue(np.allclose(R2, Rz @ R0, atol=1e-9))
        p = np.array([3.0, -1.0, 2.0])                                         # any blade point
        before = R0 @ p + np.array(base[1])
        after = R2 @ p + np.array(trans2)
        self.assertTrue(np.allclose(after - c, Rz @ (before - c), atol=1e-9))  # turned about the grip point

    def test_left_wrist_frame_is_the_weaponleft_frame_at_its_grip(self):
        rot, trans = W.left_weapon_frame()
        rot2, trans2 = W.left_wrist_frame()
        app = lambda R_, T, p: np.array([sum(R_[3 * r + c] * p[c] for c in range(3)) + T[r] for r in range(3)])  # noqa
        _h, gt, gq = M.LEFT_GRIP["weaponleft"]
        gq = np.array(gq) / np.linalg.norm(gq)
        for p in [(0, 0, 0), (0, 60, 0), (3, -2, 7), M.SKYRIM_HAND_IN_SHIELD]:
            in_weapon = app(rot, trans, p)                                       # Skyrim units, WeaponLeft frame
            in_wrist = R.qrot(gq, in_weapon * W.UNIT) + np.array(gt)              # metres, L_Wrist frame
            self.assertTrue(np.allclose(app(rot2, trans2, p) * W.UNIT, in_wrist, atol=1e-6))
        # the hand point lands on the wrist's own origin
        self.assertTrue(np.allclose(app(rot2, trans2, M.SKYRIM_HAND_IN_SHIELD), 0, atol=1e-4))

    def test_skinned_nif_layout(self):
        sh = sfnif.SkinnedShape(b"Blade", b"a" * 20 + b"\\" + b"b" * 20, 6, 4, "materials\\s2s\\x.mat", [b"WeaponLeft"],
                                [((0.1, 0.0, 0.3, 0.5), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)])
        f = sfnif.build_skinned_nif(b"Root", [sh, sh])
        raw = nif.serialize(f)
        n = nif.parse(raw)
        self.assertEqual(nif.serialize(n), raw)                                    # round trip
        types = [n.type_of(i) for i in range(len(n.blocks))]
        self.assertEqual(types[:8], ["NiNode", "BSXFlags", "BSGeometry", "BSLightingShaderProperty",
                                     "NiIntegerExtraData", "SkinAttach", "BSSkin::Instance", "BSSkin::BoneData"])
        self.assertEqual(len(types), 14)                                           # 2 + 6 per shape
        g = sfnif.parse_bsgeometry(n.blocks[2])
        self.assertEqual((g.skin, g.shader, g.extra_refs), (6, 3, [4, 5]))
        self.assertEqual(g.box, (sfnif.FLT_MAX,) * 6)
        sk = sfnif.parse_skin(n)
        self.assertEqual(sk["bones"], [b"WeaponLeft"])
        self.assertEqual(sk["instance"][:3], (0, 13, 1))                          # the last shape's BoneData
        self.assertEqual(struct.unpack_from("<i", n.blocks[6], 12)[0], -1)          # one empty bone ref per bone
        self.assertEqual(struct.unpack_from("<iI", n.blocks[1], 0)[1], 0x10000)     # BSXFlags as vanilla bodies
        self.assertAlmostEqual(sk["binds"][0][0][3], 0.5)
        with self.assertRaises(ValueError):
            sfnif.build_skinned_nif(b"R", [sfnif.SkinnedShape(b"x", b"p", 3, 3, "m", [b"A"], [])])


class PluginTests(unittest.TestCase):
    def test_build_read_back_and_edit(self):
        with tempfile.TemporaryDirectory() as d:
            sf = os.path.join(d, "Starfield.esm")
            starfield_esm(sf)
            info = sfplugin.header_info(sf)
            self.assertEqual(info["form_version"], 555)
            self.assertAlmostEqual(info["hedr_version"], 0.96, places=5)
            recs = sfplugin.records(sf, [b"WEAP", b"KYWD"])
            weaps = [r for r in recs if r[0] == b"WEAP"]
            names = {fid: sfplugin.edid(s) for t, _h, s, fid in recs if t == b"KYWD"}
            tpl, why = P.pick_template(weaps, names)
            self.assertEqual(sfplugin.edid(tpl[2]), "Melee_Sword")                # AnimSword preferred
            self.assertIn("AnimSword", why)
            rec = P.weapon_record(tpl, 0, "S2S_IronSword", "Iron Sword (Skyrim)", "s2s\\weapons\\iron\\longsword.nif")
            out = os.path.join(d, "S2SWeapons.esm")
            with open(out, "wb") as fh:
                fh.write(sfplugin.build([rec], info))
            raw = open(out, "rb").read()
            t, size, flags, fid = struct.unpack_from("<4sIII", raw, 0)
            self.assertEqual((t, flags & 1, struct.unpack_from("<H", raw, 20)[0]), (b"TES4", 1, 555))
            tes4 = dict((s, bytes(v)) for s, v in fo4land.iter_subrecords(raw[24:24 + size]))
            self.assertEqual(tes4[b"MAST"], b"Starfield.esm\0")
            version, count, next_id = struct.unpack("<fII", tes4[b"HEDR"])
            self.assertEqual((count, next_id), (1, 0x801))
            (typ, _h, subs, rid), = sfplugin.records(out, [b"WEAP"])
            self.assertEqual(rid, 0x01000800)
            got = {s: v for s, v in subs}
            self.assertEqual(got[b"EDID"], b"S2S_IronSword\0")
            self.assertEqual(got[b"FULL"], b"Iron Sword (Skyrim)\0")              # text: this plugin is not localized
            self.assertEqual(got[b"MODL"], b"s2s\\weapons\\iron\\longsword.nif\0")
            self.assertNotIn(b"DESC", got)
            self.assertEqual(got[b"DNAM"], b"\x01" * 16)                         # everything else as the template
            self.assertEqual(got[b"KWDA"], struct.pack("<2I", 0x000A0002, 0x000A0001))
            with self.assertRaises(SystemExit):
                P.pick_template(weaps, {}, prefer=("Nope",))


class LeftBladeKeywordTests(unittest.TestCase):
    def test_keyword_added_with_count(self):
        subs = [(b"EDID", b"A\0"), (b"FULL", b"x\0"), (b"KSIZ", struct.pack("<I", 1)), (b"KWDA", struct.pack("<I", 5))]
        out = P.with_keyword(subs, 9)
        self.assertEqual(dict(out)[b"KWDA"], struct.pack("<2I", 5, 9))
        self.assertEqual(dict(out)[b"KSIZ"], struct.pack("<I", 2))
        self.assertEqual(P.with_keyword(out, 9), out)                          # already there
        bare = P.with_keyword([(b"EDID", b"A\0"), (b"FULL", b"x\0"), (b"DATA", b"")], 7)
        self.assertEqual([s for s, _ in bare], [b"EDID", b"FULL", b"KSIZ", b"KWDA", b"DATA"])
        self.assertEqual(dict(bare)[b"KWDA"], struct.pack("<I", 7))
        nosize = P.with_keyword([(b"EDID", b"A\0"), (b"KWDA", struct.pack("<I", 5))], 6)
        self.assertEqual([s for s, _ in nosize], [b"EDID", b"KSIZ", b"KWDA"])

    def test_free_slot_and_records_on_it(self):
        def rec(t, bits):
            return (t, bytes(24), [(b"EDID", b"x\0"), (b"BO64", struct.pack("<Q", bits))], 1)
        recs = [rec(b"ARMO", 1 << 3), rec(b"ARMA", (1 << 61) | (1 << 3)), rec(b"ARMO", 1 << 60)]
        self.assertEqual(P.used_slots(recs), (1 << 61) | (1 << 60) | (1 << 3))
        self.assertEqual(P.free_slot(recs), 59)
        self.assertEqual(P.free_slot([]), 61)
        with self.assertRaises(SystemExit):
            P.free_slot([rec(b"ARMO", (1 << 64) - 1)])
        arma = (b"ARMA", bytes(24), [(b"EDID", b"AA\0"), (b"BO64", struct.pack("<Q", 1 << 3))], 0x100)
        armo = (b"ARMO", bytes(24), [(b"EDID", b"O\0"), (b"BO64", struct.pack("<Q", 1 << 3)),
                                     (b"MODL", struct.pack("<I", 0x100))], 0x200)
        aa, ao = P.left_blade_records(armo, arma, 1, "S2S_Left", "Left", "l.nif", slot=59)
        self.assertEqual(dict(aa[2])[b"BO64"], struct.pack("<Q", 1 << 59))
        self.assertEqual(dict(ao[2])[b"BO64"], struct.pack("<Q", 1 << 59))

    def test_left_blade_has_an_outfit_and_a_spacesuit_addon(self):
        def rec(t, bits):
            return (t, bytes(24), [(b"EDID", b"x\0"), (b"BO64", struct.pack("<Q", bits))], 1)
        vanilla = [rec(b"ARMO", (1 << 31) | (1 << 30) | (1 << 61))]
        self.assertEqual(P.slot_in(vanilla, P.OUTFIT_SLOTS), (29, False))
        self.assertEqual(P.slot_in(vanilla, P.SUIT_SLOTS), (60, False))
        full = [rec(b"ARMO", (1 << 32) - 1)]
        self.assertEqual(P.slot_in(full, P.OUTFIT_SLOTS), (15, True))           # shares "Misc 3"
        arma = (b"ARMA", bytes(24), [(b"EDID", b"AA\0"), (b"BO64", struct.pack("<Q", 1 << 3)), (b"MOD2", b"a.nif\0")],
                0x100)
        armo = (b"ARMO", bytes(24), [(b"EDID", b"O\0"), (b"BO64", struct.pack("<Q", 1 << 3)),
                                     (b"INDX", struct.pack("<H", 0)), (b"MODL", struct.pack("<I", 0x100)),
                                     (b"DATA", b"d")], 0x200)
        aa, ao, ss = P.left_blade_records(armo, arma, 1, "S2S_Left", "Left", "l.nif", slot=29, suit_slot=60)
        self.assertEqual(dict(aa[2])[b"BO64"], struct.pack("<Q", 1 << 29))
        self.assertEqual(dict(ss[2])[b"BO64"], struct.pack("<Q", 1 << 60))
        self.assertEqual(dict(ss[2])[b"EDID"], b"S2S_Left_SS_AA\0")
        self.assertEqual(dict(ss[2])[b"MOD2"], b"l.nif\0")                       # the same blade
        self.assertEqual(dict(ao[2])[b"BO64"], struct.pack("<Q", (1 << 29) | (1 << 60)))
        self.assertEqual([(s_, d) for s_, d in ao[2] if s_ in (b"INDX", b"MODL")],
                         [(b"INDX", struct.pack("<H", 0)), (b"MODL", struct.pack("<I", aa[3])),
                          (b"INDX", struct.pack("<H", 0)), (b"MODL", struct.pack("<I", ss[3]))])
        self.assertEqual(len({aa[3], ao[3], ss[3]}), 3)

    def test_outfit_layer_keyword_is_dropped(self):
        subs = [(b"EDID", b"O\0"), (b"KSIZ", struct.pack("<I", 2)), (b"KWDA", struct.pack("<2I", 5, 6)),
                (b"MODL", struct.pack("<I", 0x100))]
        out = P.without_keywords(subs, {6})
        self.assertEqual(dict(out)[b"KWDA"], struct.pack("<I", 5))
        self.assertEqual(dict(out)[b"KSIZ"], struct.pack("<I", 1))
        self.assertEqual([s_ for s_, _ in P.without_keywords(subs, {5, 6})], [b"EDID", b"MODL"])
        self.assertEqual(P.without_keywords(subs, {9}), subs)
        arma = (b"ARMA", bytes(24), [(b"EDID", b"AA\0")], 0x100)
        armo = (b"ARMO", bytes(24), subs, 0x200)
        _aa, ao = P.left_blade_records(armo, arma, 1, "S2S_Left", "Left", "l.nif", keyword=0x01000800,
                                       drop_keywords={6})
        self.assertEqual(sfplugin.keywords(ao[2]), [5, 0x01000800])        # apparel category kept, layer gone

    def test_spacesuit_check_lists_both_records(self):
        def rec(edid, bits, kws, fid):
            return (b"ARMO", b"ARMO" + struct.pack("<II", 0, 0x4) + bytes(12),
                    [(b"EDID", edid + b"\0"), (b"BO64", struct.pack("<Q", bits)),
                     (b"KSIZ", struct.pack("<I", len(kws))), (b"KWDA", struct.pack(f"<{len(kws)}I", *kws))], fid)
        outfit = rec(b"Clothes_Nightwear_01", 1 << 3, [7], 0x10)
        armo = [outfit, rec(b"Helmet_X", 1 << 36, [8], 0x11), rec(b"Spacesuit_Body_X", (1 << 35) | (1 << 40), [8, 9], 0x12)]
        got = P.spacesuit_check(outfit, armo, {7: "ArmorTypeApparel", 8: "ArmorTypeSpacesuit"})
        self.assertEqual(got["outfit"]["keywords"], ["ArmorTypeApparel"])
        self.assertEqual(got["outfit"]["biped_slots"], [3])
        self.assertEqual(got["spacesuit"]["edid"], "Spacesuit_Body_X")
        self.assertEqual(got["spacesuit"]["keywords"], ["ArmorTypeSpacesuit", "00000009"])
        self.assertEqual(got["spacesuit"]["record_flags"], "00000004")
        self.assertIsNone(P.spacesuit_check(outfit, armo[:2], {})["spacesuit"])

    def test_only_the_left_blade_addon_is_kept(self):
        subs = [(b"EDID", b"O\0"), (b"INDX", struct.pack("<H", 0)), (b"MODL", struct.pack("<I", 0x100)),
                (b"INDX", struct.pack("<H", 1)), (b"MODL", struct.pack("<I", 0x101)), (b"DATA", b"x")]
        out = P.only_addon(subs, 0x101)
        self.assertEqual(out, [(b"EDID", b"O\0"), (b"INDX", struct.pack("<H", 0)), (b"MODL", struct.pack("<I", 0x101)),
                               (b"DATA", b"x")])
        arma = (b"ARMA", bytes(24), [(b"EDID", b"AA\0")], 0x100)
        armo = (b"ARMO", bytes(24), [(b"EDID", b"O\0"), (b"INDX", struct.pack("<H", 0)), (b"MODL", struct.pack("<I", 0x100)),
                                     (b"INDX", struct.pack("<H", 1)), (b"MODL", struct.pack("<I", 0x555))], 0x200)
        aa, ao = P.left_blade_records(armo, arma, 1, "S2S_Left", "Left", "l.nif")
        self.assertEqual([d for s_, d in ao[2] if s_ == b"MODL"], [struct.pack("<I", aa[3])])      # the pants part gone

    def test_left_blade_records_carry_the_keyword(self):
        arma = (b"ARMA", bytes(24), [(b"EDID", b"AA\0"), (b"MOD2", b"old.nif\0")], 0x100)
        armo = (b"ARMO", bytes(24), [(b"EDID", b"O\0"), (b"FULL", b"n\0"), (b"MODL", struct.pack("<I", 0x100))], 0x200)
        aa, ao = P.left_blade_records(armo, arma, 1, "S2S_Left", "Left", "s2s\\left.nif", keyword=0x01000800)
        self.assertEqual(sfplugin.keywords(ao[2]), [0x01000800])
        self.assertEqual(dict(ao[2])[b"MODL"], struct.pack("<I", aa[3]))
        _aa, ao2 = P.left_blade_records(armo, arma, 1, "S2S_Left", "Left", "s2s\\left.nif")
        self.assertEqual(sfplugin.keywords(ao2[2]), [])


class PairModelTests(unittest.TestCase):
    def test_skinned_shapes_join_a_static_model(self):
        st = sfnif.build_static_nif(b"longsword", [sfnif.StaticShape(b"Blade", b"aa\\bb", 36, 8, "materials\\r.mat",
                                                                     (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))])
        sk = sfnif.build_skinned_nif(b"longsword_left", [sfnif.SkinnedShape(
            b"BladeL", b"cc\\dd", 24, 6, "materials\\l.mat", [b"L_Wrist"],
            [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)])])
        m = nif.parse(nif.serialize(sfnif.merge_skinned(st, sk)))
        types_ = [m.type_of(i) for i in range(len(m.blocks))]
        self.assertEqual(types_[:5], ["NiNode", "BSXFlags", "BSGeometry", "NiIntegerExtraData",
                                      "BSLightingShaderProperty"])
        self.assertEqual(types_[5:], ["BSGeometry", "BSLightingShaderProperty", "NiIntegerExtraData", "SkinAttach",
                                      "BSSkin::Instance", "BSSkin::BoneData"])
        root = m.blocks[0]
        n_child, = struct.unpack_from("<I", root, 76)
        self.assertEqual(struct.unpack_from(f"<{n_child}i", root, 80), (2, 5))     # both blades under the root
        g = sfnif.parse_bsgeometry(m.blocks[5])
        self.assertEqual((g.shader, g.skin, g.extra_refs), (6, 9, [7, 8]))
        self.assertEqual(m.strings[g.name_idx], b"BladeL")
        self.assertEqual(struct.unpack_from("<iiI", m.blocks[9], 0), (0, 10, 1))     # skeleton root = the root
        self.assertEqual(m.strings[struct.unpack_from("<i", m.blocks[6], 0)[0]], b"materials\\l.mat")
        self.assertEqual(m.strings[struct.unpack_from("<i", m.blocks[8], 0)[0]], b"SkinBMP")
        self.assertEqual(sfnif.parse_skin(m)["bones"], [b"L_Wrist"])
        self.assertEqual(sfnif.parse_bsgeometry(m.blocks[2]).meshes[0].path, b"aa\\bb")   # the right blade as before


class LeftHandNodeTests(unittest.TestCase):
    def test_static_shapes_go_under_a_new_node(self):
        def model(name, mesh, mat):
            return sfnif.build_static_nif(name, [sfnif.StaticShape(b"Blade", mesh, 36, 8, mat, (0, 0, 0, 1),
                                                                   (0, 0, 0, 1, 1, 1))])
        m = nif.parse(nif.serialize(sfnif.merge_under_node(model(b"longsword", b"aa\\bb", "materials\\r.mat"),
                                                           model(b"left", b"cc\\dd", "materials\\l.mat"),
                                                           b"S2S_LeftHand")))
        types_ = [m.type_of(i) for i in range(len(m.blocks))]
        self.assertEqual(types_[5:], ["NiNode", "BSGeometry", "NiIntegerExtraData", "BSLightingShaderProperty"])
        root = m.blocks[0]
        n_child, = struct.unpack_from("<I", root, 76)
        self.assertEqual(struct.unpack_from(f"<{n_child}i", root, 80), (2, 5))     # right blade, the left node
        node = m.blocks[5]
        self.assertEqual(m.strings[struct.unpack_from("<i", node, 0)[0]], b"S2S_LeftHand")
        self.assertEqual(struct.unpack_from("<iI", node, 68), (-1, 1))             # no collision, one child
        self.assertEqual(struct.unpack_from("<i", node, 76)[0], 6)
        self.assertEqual(struct.unpack_from("<13f", node, 16), (0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0))
        g = sfnif.parse_bsgeometry(m.blocks[6])
        self.assertEqual((g.extra_refs, g.shader), ([7], 8))
        self.assertEqual(g.meshes[0].path, b"cc\\dd")
        self.assertEqual(m.strings[struct.unpack_from("<i", m.blocks[8], 0)[0]], b"materials\\l.mat")


class PackTests(unittest.TestCase):
    def test_end_to_end_on_synthetic_games(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(textures, "texconv", lambda *a, **k: None):
            sky = os.path.join(d, "Skyrim", "Data")
            os.makedirs(sky)
            with open(os.path.join(sky, "Skyrim - Meshes0.bsa"), "wb") as fh:
                fh.write(bsa.build({"meshes\\weapons\\iron\\longsword.nif": sword_nif()}))
            tex = {t: F.rgba_dds() for t in ("textures\\weapons\\iron\\sword.dds", "textures\\weapons\\iron\\sword_n.dds")}
            with open(os.path.join(sky, "Skyrim - Textures0.bsa"), "wb") as fh:
                fh.write(bsa.build(tex, compress=False, embed_names=True))
            skyrim_esm(os.path.join(sky, "Skyrim.esm"))
            sf = os.path.join(d, "Starfield")
            os.makedirs(os.path.join(sf, "Data"))
            os.makedirs(os.path.join(sf, "Tools"))
            starfield_esm(os.path.join(sf, "Data", "Starfield.esm"))
            F.content_resources(os.path.join(sf, "Tools", "ContentResources.zip"))
            out = os.path.join(d, "mod")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = P.main(["--skyrim-data", sky, "--starfield", sf, "--texconv", "texconv.exe", "--out", out])
            self.assertEqual(rc, 0)
            rep = json.load(open(os.path.join(out, "weapon_test_pack.json")))
            ok = [w for w in rep["weapons"] if w["ok"]]
            self.assertEqual([w["key"] for w in ok], ["sword", "sword_left", "sword_pair"])   # only the sword in the archive
            left = ok[1]
            self.assertEqual(left["apparel_template"]["armo"], "Clothes_Nightwear_01")
            ln = nif.parse(open(os.path.join(out, "meshes", "s2s", "weapons", "iron", "longsword_left.nif"), "rb").read())
            self.assertEqual(sfnif.parse_skin(ln)["bones"], [b"L_Wrist"])
            recs = {sfplugin.edid(r[2]): r for r in sfplugin.records(os.path.join(out, "S2SWeapons.esm"),
                                                                     [b"ARMO", b"ARMA"])}
            aa, ao = recs["S2S_IronSword_Left_AA"], recs["S2S_IronSword_Left"]
            aas = dict(aa[2])
            for k in (b"MOD2", b"MOD3", b"MOD4"):
                self.assertEqual(aas[k], b"s2s\\weapons\\iron\\longsword_left.nif\0")
            suit = recs["S2S_IronSword_Left_SS_AA"]                               # the addon shown with a spacesuit
            self.assertEqual(dict(suit[2])[b"MOD2"], b"s2s\\weapons\\iron\\longsword_left.nif\0")
            self.assertEqual([d for s_, d in ao[2] if s_ == b"MODL"],              # the ARMO wears the new ARMAs
                             [struct.pack("<I", aa[3]), struct.pack("<I", suit[3])])
            self.assertEqual(left["biped_slot"]["suit_bit"], 61)
            pair = [w for w in rep["weapons"] if w["key"] == "sword_pair"][0]       # both blades in one weapon
            self.assertTrue(pair["ok"], pair)
            self.assertEqual(pair["starfield_model"], "s2s\\weapons\\iron\\longsword_pair.nif")
            pn = nif.parse(open(os.path.join(out, "meshes", "s2s", "weapons", "iron", "longsword_pair.nif"),
                                "rb").read())
            types_ = [pn.type_of(i) for i in range(len(pn.blocks))]
            self.assertEqual(types_.count("BSGeometry"), 2)
            self.assertNotIn("SkinAttach", types_)                                # rigid: S2SCombat moves it
            self.assertIn(b"S2S_LeftHand", pn.strings)
            pw = [r for r in sfplugin.records(os.path.join(out, "S2SWeapons.esm"), [b"WEAP"])
                  if sfplugin.edid(r[2]) == "S2S_IronSword_Pair"][0]
            self.assertEqual(dict(pw[2])[b"MODL"], b"s2s\\weapons\\iron\\longsword_pair.nif\0")
            kw = [r for r in sfplugin.records(os.path.join(out, "S2SWeapons.esm"), [b"KYWD"])][0]
            self.assertIn(kw[3], sfplugin.keywords(pw[2]))
            self.assertLess(left["biped_slot"]["bit"], 32)
            self.assertEqual(left["layer_keywords"], ["ArmorTypeApparelOrNakedBody", "ArmorTypeSpacesuitBackpack"])
            self.assertIn("ArmorTypeSpacesuitBody", left["armor_type_keywords"])
            self.assertEqual(dict(ao[2])[b"FULL"], b"Iron Sword (Skyrim, left hand)\0")
            self.assertEqual(aas[b"RNAM"], struct.pack("<I", 0x347D))               # race etc. kept
            sword = ok[0]
            self.assertEqual(sword["skyrim"]["damage"], 7)                         # read from Skyrim.esm
            self.assertEqual(sword["scabbard_shapes_dropped"], 1)
            self.assertEqual(sword["starfield_model"], "s2s\\weapons\\iron\\longsword.nif")
            self.assertEqual(rep["template"]["edid"], "Melee_Sword")
            self.assertIn("loose", rep["packing"])                                 # no Archive2 here
            n = nif.parse(open(os.path.join(out, "meshes", "s2s", "weapons", "iron", "longsword.nif"), "rb").read())
            geo = [sfnif.parse_bsgeometry(n.blocks[i]) for i in range(len(n.blocks)) if n.type_of(i) == "BSGeometry"]
            self.assertEqual(len(geo), 1)                                          # blade only
            wid, _pair = [w for w in sfplugin.records(os.path.join(out, "S2SWeapons.esm"), [b"WEAP"])]
            mesh_left = [r for r in rep["weapons"] if r["key"] == "sword_left"][0]["starfield_model"]
            self.assertTrue(mesh_left.endswith("longsword_left.nif"))
            self.assertEqual(sfplugin.edid(wid[2]), "S2S_IronSword")
            self.assertTrue(os.path.isfile(os.path.join(out, "README.txt")))
            self.assertFalse(os.path.exists(os.path.join(out, "_staging")))
            # the blade tip is along +Z from the grip in the written mesh
            mesh_files = [os.path.join(r, f) for r, _d, fs in os.walk(os.path.join(out, "geometries")) for f in fs]
            _h, _gt, gq = M.LEFT_GRIP["weaponleft"]
            left_dir = R.qrot(np.array(gq) / np.linalg.norm(gq), np.array([0.0, 0.0, 1.0]))
            kinds = []
            for mf in mesh_files:
                m = sfmesh.parse(open(mf, "rb").read())
                pts = np.array([sfmesh.decode_position(p, m.scale) for p in m.positions])
                span = pts.max(0) - pts.min(0)
                along = pts @ left_dir
                if int(np.argmax(span)) == 2 and abs(float(span[2]) - 70 * W.UNIT) < 0.01:
                    kinds.append("right")                                          # right blade: along the bone's +Z
                elif abs(float(along.max() - along.min()) - 70 * W.UNIT) < 0.01:
                    kinds.append("left")                                           # left blade: the wrist grip's +Z
            self.assertEqual(sorted(kinds), ["left", "left", "right"])   # worn (skinned) + pair (rigid) left


if __name__ == "__main__":
    unittest.main()
