"""Left-hand worn versions of Starfield weapon models (fo4sf.sfweaponleft) and the pack's --left-hand-mod pass."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "armor"))
sys.path.insert(0, HERE)

from fo4sf import ba2, nif, sfmesh, sfnif, sfplugin, sfweaponleft as L, skyrimweapon as W, textures  # noqa: E402


def gnrl_ba2(path, files):
    """A version-1 general BA2 holding `files` {name: bytes} uncompressed (enough for fo4sf.ba2.Ba2)."""
    names = list(files)
    head = 24
    table = 36 * len(names)
    data_off = head + table
    blobs, entries, off = [], [], data_off
    for n in names:
        d = files[n]
        entries.append(struct.pack("<I4sIIQIII", 0, b"bin\0", 0, 0, off, 0, len(d), 0xBAADF00D))
        blobs.append(d)
        off += len(d)
    name_tab = b"".join(struct.pack("<H", len(n)) + n.encode() for n in names)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<4sI4sIQ", b"BTDX", 1, b"GNRL", len(names), off))
        fh.write(b"".join(entries) + b"".join(blobs) + name_tab)


def blade_mesh():
    """A thin blade along +Z (0 .. 1 m) with normals +X and tangents +Y."""
    pts = [(0.0, 0.0, 0.0), (0.01, 0.0, 0.0), (0.0, 0.0, 1.0), (0.01, 0.0, 1.0)]
    m = sfmesh.SfMesh(version=2)
    m.scale, m.positions = sfmesh.encode_positions(pts)
    m.triangles = [(0, 1, 2), (1, 3, 2)]
    m.uv1 = [(0, 0)] * 4
    m.normals = [sfmesh.encode_packed(1.0, 0.0, 0.0, 1.0 / 3.0)] * 4
    m.tangents = [sfmesh.encode_packed(0.0, 1.0, 0.0, 1.0)] * 4
    sfmesh.build_meshlets(m)
    return m


def weapon_nif(shape_t=(0.0, 0.0, 0.0), shape_rot=L.IDENT, light=False):
    n = sfnif.build_static_nif(b"WEAPON", [sfnif.StaticShape(b"blade:0", b"mymod\\blade", 6, 4, "materials\\mymod\\b.mat",
                                                             (0, 0, 0.5, 0.6), (0, 0, 0.5, 0.01, 0.01, 0.5))])
    g = sfnif.parse_bsgeometry(n.blocks[2])
    g.translation, g.rotation = tuple(shape_t), tuple(shape_rot)
    n.blocks[2] = sfnif.build_bsgeometry(g)
    if light:
        n.add_block("NiAmbientLight", struct.pack("<iIi", n.string_index(b"Light01"), 0, -1))
    return nif.serialize(n)


ROT_X90 = (1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0)          # +Z -> -Y, +Y -> +Z


class LeftHandModelTests(unittest.TestCase):
    def files(self, **kw):
        store = {"geometries/mymod/blade.mesh": sfmesh.serialize(blade_mesh())}
        return L.left_hand_model(weapon_nif(**kw), store.get, "s2s/lefthand/t/blade_left", W.left_grip_metres())

    def test_shapes_move_into_the_left_wrist_frame_and_skin_to_it(self):
        files, rep = self.files(shape_t=(0.0, 0.0, 0.1), shape_rot=ROT_X90, light=True)
        self.assertEqual(rep["left_out"], ["NiAmbientLight"])
        n = nif.parse(files["meshes/s2s/lefthand/t/blade_left.nif"])
        skin = sfnif.parse_skin(n)
        self.assertEqual(skin["bones"], [b"L_Wrist"])
        self.assertEqual(skin["binds"][0][1], L.IDENT)                       # identity bind: vertices bone-local
        g = sfnif.parse_bsgeometry(n.blocks[2])
        self.assertEqual(n.strings[struct.unpack_from("<i", n.blocks[3], 0)[0]], b"materials\\mymod\\b.mat")
        mesh_rel = "geometries/" + g.meshes[0].path.decode().replace("\\", "/") + ".mesh"
        m = sfmesh.parse(files[mesh_rel])
        self.assertEqual(m.weights_per_vertex, 4)
        self.assertEqual(m.weights[:4], [(0, 65535), (0, 0), (0, 0), (0, 0)])
        rot, tr = W.left_grip_metres()
        R_ = np.array(rot).reshape(3, 3)
        got = np.array([sfmesh.decode_position(p, m.scale) for p in m.positions])
        src = np.array([(0.0, 0.0, 0.0), (0.01, 0.0, 0.0), (0.0, 0.0, 1.0), (0.01, 0.0, 1.0)])
        in_weapon = src @ np.array(ROT_X90).reshape(3, 3).T + np.array([0.0, 0.0, 0.1])   # node: R p + t
        want = in_weapon @ R_.T + np.array(tr)                                          # then the grip
        self.assertTrue(np.allclose(got, want, atol=2e-4))
        nx = np.array(sfmesh.decode_packed(m.normals[0])[:3])
        self.assertTrue(np.allclose(nx, R_ @ np.array([1.0, 0.0, 0.0]), atol=0.01))      # normals turned, not moved
        tw = sfmesh.decode_packed(m.tangents[0])
        self.assertAlmostEqual(tw[3], 1.0)                                                # bitangent sign kept
        self.assertEqual(m.triangles, blade_mesh().triangles)

    def test_grip_tuning_turns_about_the_grip_point(self):
        rot0, t0 = W.left_grip_metres()
        rot1, t1 = W.left_grip_metres(move_cm=(1.0, 0.0, 0.0), turn_deg=(0.0, 0.0, 90.0))
        self.assertTrue(np.allclose(np.array(t1) - np.array(t0), [0.01, 0.0, 0.0]))
        Rz = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
        self.assertTrue(np.allclose(np.array(rot1).reshape(3, 3), Rz @ np.array(rot0).reshape(3, 3)))

    def test_missing_mesh_is_reported_and_no_mesh_at_all_fails(self):
        with self.assertRaises(nif.NifError):
            L.left_hand_model(weapon_nif(), {}.get, "x/y", W.left_grip_metres())
        self.assertEqual(L.mesh_archive_path(b"Geometries\\A\\B"), "geometries/a/b.mesh")
        self.assertEqual(L.mesh_archive_path(b"0123\\4567"), "geometries/0123/4567.mesh")


class PackLeftHandModTests(unittest.TestCase):
    def test_another_mods_weapons_become_left_hand_blades(self):
        import test_weapon_test_pack as T
        import weapon_test_pack as P
        from fo4sf import bsa
        with tempfile.TemporaryDirectory() as d, mock.patch.object(textures, "texconv", lambda *a, **k: None):
            sky = os.path.join(d, "Skyrim", "Data")
            os.makedirs(sky)
            with open(os.path.join(sky, "Skyrim - Meshes0.bsa"), "wb") as fh:
                fh.write(bsa.build({"meshes\\weapons\\iron\\longsword.nif": T.sword_nif()}))
            tex = {t: T.F.rgba_dds() for t in ("textures\\weapons\\iron\\sword.dds", "textures\\weapons\\iron\\sword_n.dds")}
            with open(os.path.join(sky, "Skyrim - Textures0.bsa"), "wb") as fh:
                fh.write(bsa.build(tex, compress=False, embed_names=True))
            T.skyrim_esm(os.path.join(sky, "Skyrim.esm"))
            sf = os.path.join(d, "Starfield")
            os.makedirs(os.path.join(sf, "Data"))
            os.makedirs(os.path.join(sf, "Tools"))
            T.starfield_esm(os.path.join(sf, "Data", "Starfield.esm"))
            T.F.content_resources(os.path.join(sf, "Tools", "ContentResources.zip"))
            mod = os.path.join(d, "MyMod")
            os.makedirs(mod)
            wp = struct.pack("<4sIII", b"WEAP", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
            with open(os.path.join(mod, "MySabers.esm"), "wb") as fh:
                fh.write(sfplugin.build([(b"WEAP", wp, [(b"EDID", b"BlueSaber\0"), (b"FULL", b"Blue Saber\0"),
                                                        (b"MODL", b"Weapons\\MyMod\\Blue.nif\0")], 0x01000800),
                                         (b"WEAP", wp, [(b"EDID", b"Broken\0"), (b"MODL", b"Weapons\\MyMod\\No.nif\0")],
                                          0x01000801)],
                                        {"hedr_version": 0.96, "form_version": 555}, masters=("Starfield.esm",)))
            gnrl_ba2(os.path.join(mod, "MySabers - Main.ba2"),
                     {"meshes/weapons/mymod/blue.nif": weapon_nif(),
                      "geometries/mymod/blade.mesh": sfmesh.serialize(blade_mesh())})
            out = os.path.join(d, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = P.main(["--skyrim-data", sky, "--starfield", sf, "--texconv", "texconv.exe", "--out", out,
                             "--left-hand-mod", os.path.join(mod, "MySabers.esm")])
            self.assertEqual(rc, 0)
            rep = json.load(open(os.path.join(out, "weapon_test_pack.json")))
            rows = {w["key"]: w for w in rep["weapons"]}
            blue = rows["mysabers:BlueSaber"]
            self.assertTrue(blue["ok"], blue)
            self.assertEqual(blue["name"], "Blue Saber (left hand)")
            self.assertFalse(rows["mysabers:Broken"]["ok"])
            self.assertIn("not in the mod's archives", rows["mysabers:Broken"]["reason"])
            recs = {sfplugin.edid(r[2]): r for r in sfplugin.records(os.path.join(out, "S2SWeapons.esm"),
                                                                     [b"ARMO", b"ARMA", b"KYWD"])}
            ao = recs["S2S_LH_BlueSaber"]
            kw = recs[P.LEFT_BLADE_KEYWORD]
            self.assertIn(kw[3], sfplugin.keywords(ao[2]))                         # the dual keyword, as the iron one
            tag = recs[P.BLADE_TAG.format(ao[3] & 0xFFFFFF)]                         # its own keyword, named by its ID
            self.assertIn(tag[3], sfplugin.keywords(ao[2]))
            iron = recs["S2S_IronSword_Left"]
            self.assertIn(recs[P.BLADE_TAG.format(iron[3] & 0xFFFFFF)][3], sfplugin.keywords(iron[2]))
            self.assertEqual(dict(recs["S2S_LH_BlueSaber_AA"][2])[b"MOD2"],
                             b"s2s\\lefthand\\mysabers\\bluesaber_left.nif\0")
            n = nif.parse(open(os.path.join(out, "meshes", "s2s", "lefthand", "mysabers", "bluesaber_left.nif"),
                               "rb").read())
            self.assertEqual(sfnif.parse_skin(n)["bones"], [b"L_Wrist"])


if __name__ == "__main__":
    unittest.main()
