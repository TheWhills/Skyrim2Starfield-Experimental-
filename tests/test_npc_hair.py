"""scripts/npc/npc_hair.py (Skyrim NPC hair on the converted test NPCs) and the no-physics / bind-anchor paths of
fo4sf.skyrimhair, on synthetic data only."""
import os
import struct
import sys
import tempfile
import types
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import nif, sfnif, sfplugin, skyrimhair  # noqa: E402
import npc_hair as NH  # noqa: E402
from test_smpcloth import hair_nif_bytes, sf_world  # noqa: E402


def hdpt(fid, edid, kind, model=None, extras=(), flags=0x4):
    subs = [(b"EDID", sfplugin.zs(edid))] + ([(b"MODL", sfplugin.zs(model))] if model else [])
    subs += [(b"DATA", bytes([flags])), (b"PNAM", struct.pack("<I", kind))]
    subs += [(b"HNAM", struct.pack("<I", x)) for x in extras]
    return (b"HDPT", b"\0" * 24, subs, fid)


class NoPhysicsTests(unittest.TestCase):
    def test_rigid_hair_on_the_head(self):
        w = sf_world()
        hair = skyrimhair.convert(hair_nif_bytes(), None, w)
        self.assertEqual(hair.bones, [])
        self.assertEqual({b for vw in hair.shapes[0].weights for b, _w in vw}, {"C_Head"})   # all follow the head
        files = skyrimhair.nif_files(hair, ["materials\\x.mat"], None, w, "s2s/npc/hair/x")
        n = nif.parse(files["meshes/s2s/npc/hair/x.nif"])
        self.assertNotIn("BSClothExtraData", [n.type_of(i) for i in range(len(n.blocks))])
        self.assertEqual(sfnif.parse_skin(n)["bones"], [b"C_Head"])

    def test_bind_frame_wins_over_shifted_nodes(self):
        """A NIF whose node tree sits away from its skinning frame (KS Amor / Kikyo: 3.3 units up) is placed by the
        binds, the frame the game draws it in."""
        import skyrim_fixtures as F
        import test_smpcloth as TS
        w = sf_world()
        good = skyrimhair.convert(hair_nif_bytes(), None, w)
        node = F.SseNif.node
        F.SseNif.node = lambda self, i, name, children, t=(0, 0, 0), **k: node(
            self, i, name, children, t=(t[0], t[1], t[2] + 3.3) if name == TS.SKY_BONES[0] else t, **k)
        try:
            shifted = skyrimhair.convert(hair_nif_bytes(), None, w)
        finally:
            F.SseNif.node = node
        np.testing.assert_allclose(shifted.shapes[0].positions, good.shapes[0].positions, atol=1e-9)


class RecordTests(unittest.TestCase):
    def test_parts_follow_extra_parts(self):
        parts = {1: {"model": "hair\\a.nif", "extra_parts": [2], "type": 3, "edid": "HairA"},
                 2: {"model": "hair\\a_line.nif", "extra_parts": [1], "type": 0, "edid": "HairALine"}}
        self.assertEqual(NH.part_models(1, parts), ["hair\\a.nif", "hair\\a_line.nif"])        # loop-safe
        npc = {"head_parts": [9, 1]}
        self.assertEqual(list(NH.npc_parts(npc, parts)), [3])

    def test_tint(self):
        clfm = {7: {"rgba": (255, 128, 0, 0)}}
        self.assertEqual(NH.tint({"hair_color": 7}, clfm), (1.0, 128 / 255, 0.0))
        self.assertEqual(NH.tint({"hair_color": 7}, clfm, 2.0), (1.0, 1.0, 0.0))
        self.assertIsNone(NH.tint({"hair_color": None}, clfm))

    def test_template_and_swap(self):
        sf = {r[3]: r for r in (hdpt(0x10, "SFHairM", 3, flags=0x2), hdpt(0x11, "SFHairF", 3, flags=0x4),
                                hdpt(0x12, "SFBeard", 4, flags=0x2), hdpt(0x13, "SFEyes", 2))}
        npc = [(b"EDID", b"T\0"), (b"RNAM", struct.pack("<I", 1)), (b"PNAM", struct.pack("<I", 0x13)),
               (b"PNAM", struct.pack("<I", 0x10)), (b"HCOL", b"Brown\0")]
        self.assertEqual(NH.starfield_part_template(npc, sf, 3, False)[3], 0x10)             # the NPC's own
        self.assertEqual(NH.starfield_part_template(npc, sf, 4, False)[3], 0x12)             # any beard
        self.assertEqual(NH.starfield_part_template([], sf, 3, True)[3], 0x11)               # by sex
        out = NH.with_head_parts(npc, sf, {3: 0x0100_0800, 4: 0x0100_0801})
        pn = [struct.unpack("<I", d)[0] for s, d in out if s == b"PNAM"]
        self.assertEqual(pn, [0x13, 0x0100_0800, 0x0100_0801])                               # eyes kept
        self.assertEqual(out[-1], (b"HCOL", b"Brown\0"))
        rec = NH.head_part_record(hdpt(0x10, "SFHairM", 3, "x.nif", extras=(5,)), 0x0100_0800, "S2S_HairA",
                                  "s2s\\npc\\hair\\haira.nif")
        d = dict(rec[2])
        self.assertEqual((d[b"EDID"], d[b"MODL"]), (b"S2S_HairA\0", b"s2s\\npc\\hair\\haira.nif\0"))
        self.assertNotIn(b"HNAM", d)

    def test_add_hair(self):
        sky_parts = {0x100: {"form_id": 0x100, "edid": "HairFemaleNord01", "model": "Actors\\Hair\\f01.nif",
                             "type": 3, "extra_parts": [0x101]},
                     0x101: {"form_id": 0x101, "edid": "HairLine01", "model": "Actors\\Hair\\line.nif", "type": 0,
                             "extra_parts": []}}
        clfm = {0x50: {"rgba": (100, 50, 25, 0)}}
        npcs = {0xA: {"form_id": 0xA, "edid": "Ysolda", "female": True, "head_parts": [0x100], "hair_color": 0x50,
                      "template": None, "template_flags": 0},
                0xB: {"form_id": 0xB, "edid": "Twin", "female": True, "head_parts": [0x100], "hair_color": 0x50,
                      "template": None, "template_flags": 0}}
        sf = {r[3]: r for r in (hdpt(0x11, "SFHairF", 3, "sf.nif", flags=0x4),)}
        npc_rec = (b"NPC_", b"\0" * 24, [(b"EDID", b"S2SFace_Ysolda\0"), (b"PNAM", struct.pack("<I", 0x11))],
                   sfplugin.new_form_id(0))
        twin_rec = (b"NPC_", b"\0" * 24, [(b"EDID", b"S2SFace_Twin\0"), (b"PNAM", struct.pack("<I", 0x11))],
                    sfplugin.new_form_id(1))
        recs = [npc_rec, twin_rec]
        rows = [{"edid": "Ysolda"}, {"edid": "Twin"}]
        src = types.SimpleNamespace(mesh=lambda rel: hair_nif_bytes() if "f01" in rel.lower() else None)
        tints = []

        class Conv:
            def _shape_material(self, n, sh, albedo_tint=None):
                tints.append(albedo_tint)
                return "materials\\s2s\\hair.mat"
        with tempfile.TemporaryDirectory() as d:
            NH.add_hair(rows, npcs, [npcs[0xA], npcs[0xB]], recs, {"Ysolda": 0, "Twin": 1},
                        types.SimpleNamespace(hair_tint_gain=1.0), src, Conv(), sf_world(), sf, sky_parts, clfm, d)
            nifs = [os.path.join(r, f) for r, _ds, fs in os.walk(d) for f in fs if f.endswith(".nif")]
            self.assertEqual(len(nifs), 1)                                     # the twin shares the converted hair
        self.assertEqual(len(recs), 3)
        new = recs[2]
        self.assertEqual(new[0], b"HDPT")
        self.assertTrue(sfplugin.edid(new[2]).startswith("S2S_HairFemaleNord01_643219"))
        for k in (0, 1):
            pn = [struct.unpack("<I", d)[0] for s, d in recs[k][2] if s == b"PNAM"]
            self.assertEqual(pn, [new[3]])
        self.assertEqual(rows[0]["hair"]["hair"]["skipped"], ["Actors\\Hair\\line.nif: not in the archives"])
        self.assertTrue(rows[1]["hair"]["hair"]["shared_with_an_earlier_npc"])
        np.testing.assert_allclose(tints[0], (100 / 255, 50 / 255, 25 / 255))


class ScriptArgsTests(unittest.TestCase):
    def test_hair_needs_texconv(self):
        import face_fit
        with self.assertRaises(SystemExit):
            face_fit.main(["--skyrim-data", "x", "--starfield", "y", "--out", "z", "--hair"])


if __name__ == "__main__":
    unittest.main()
