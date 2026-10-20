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
            (b"WEAP", wp, [(b"EDID", b"Melee_Knife\0"), (b"KWDA", struct.pack("<I", 0x000A0002)),
                           (b"MODL", b"Weapons\\Knife\\Knife.nif\0")], 0x000B0001),
            (b"WEAP", wp, [(b"EDID", b"Melee_Sword\0"), (b"FULL", struct.pack("<I", 1234)),
                           (b"DESC", struct.pack("<I", 99)), (b"KWDA", struct.pack("<2I", 0x000A0002, 0x000A0001)),
                           (b"MODL", b"Weapons\\Sword\\Sword.nif\0"), (b"DNAM", b"\x01" * 16)], 0x000B0002)]
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
            self.assertEqual([w["key"] for w in ok], ["sword"])                    # only the sword is in the archive
            sword = ok[0]
            self.assertEqual(sword["skyrim"]["damage"], 7)                         # read from Skyrim.esm
            self.assertEqual(sword["scabbard_shapes_dropped"], 1)
            self.assertEqual(sword["starfield_model"], "s2s\\weapons\\iron\\longsword.nif")
            self.assertEqual(rep["template"]["edid"], "Melee_Sword")
            self.assertIn("loose", rep["packing"])                                 # no Archive2 here
            n = nif.parse(open(os.path.join(out, "meshes", "s2s", "weapons", "iron", "longsword.nif"), "rb").read())
            geo = [sfnif.parse_bsgeometry(n.blocks[i]) for i in range(len(n.blocks)) if n.type_of(i) == "BSGeometry"]
            self.assertEqual(len(geo), 1)                                          # blade only
            (wid,) = [w for w in sfplugin.records(os.path.join(out, "S2SWeapons.esm"), [b"WEAP"])]
            self.assertEqual(sfplugin.edid(wid[2]), "S2S_IronSword")
            self.assertTrue(os.path.isfile(os.path.join(out, "README.txt")))
            self.assertFalse(os.path.exists(os.path.join(out, "_staging")))
            # the blade tip is along +Z from the grip in the written mesh
            mesh_files = [os.path.join(r, f) for r, _d, fs in os.walk(os.path.join(out, "geometries")) for f in fs]
            m = sfmesh.parse(open(mesh_files[0], "rb").read())
            pts = np.array([sfmesh.decode_position(p, m.scale) for p in m.positions])
            span = pts.max(0) - pts.min(0)
            self.assertEqual(int(np.argmax(span)), 2)                              # longest along Z
            self.assertAlmostEqual(float(span[2]), 70 * W.UNIT, places=2)          # 60 + 10 units of sword


if __name__ == "__main__":
    unittest.main()
