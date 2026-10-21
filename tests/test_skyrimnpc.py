"""src/fo4sf/skyrimnpc.py on synthetic records (no game files)."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import sfplugin, skyrimnpc as N  # noqa: E402


def acbs(flags=0, template_flags=0):
    return struct.pack("<IhhHHHHhHhH", flags, 0, 0, 1, 1, 10, 100, 0, template_flags, 0, 0)


def npc_subs(edid, female=False, template=None, tflags=0):
    subs = [(b"EDID", edid.encode() + b"\0"), (b"FULL", struct.pack("<I", 0x1234)),
            (b"ACBS", acbs(N.FEMALE if female else 0, tflags)),
            (b"SNAM", struct.pack("<Ib3x", 0x13794, 2)), (b"VTCK", struct.pack("<I", 0x13AD3)),
            (b"RNAM", struct.pack("<I", 0x13746))]
    if template:
        subs.append((b"TPLT", struct.pack("<I", template)))
    subs += [(b"PKID", struct.pack("<I", 0x1000)), (b"PKID", struct.pack("<I", 0x1001)),
             (b"CNAM", struct.pack("<I", 0x13176)), (b"PNAM", struct.pack("<I", 0x2001)),
             (b"PNAM", struct.pack("<I", 0x2002)), (b"HCLF", struct.pack("<I", 0x3001)),
             (b"NAM6", struct.pack("<f", 1.03)), (b"NAM7", struct.pack("<f", 40.0)),
             (b"DOFT", struct.pack("<I", 0x4001)), (b"QNAM", struct.pack("<3f", 0.9, 0.8, 0.7)),
             (b"NAM9", struct.pack("<19f", *[i / 10.0 for i in range(19)])),
             (b"NAMA", struct.pack("<IiII", 1, -1, 2, 3)),
             (b"TINI", struct.pack("<H", 7)), (b"TINC", bytes([10, 20, 30, 255])), (b"TINV", struct.pack("<I", 55)),
             (b"TIAS", struct.pack("<h", -1)),
             (b"TINI", struct.pack("<H", 9)), (b"TINC", bytes([1, 2, 3, 4])), (b"TINV", struct.pack("<I", 100))]
    return subs


class NpcTests(unittest.TestCase):
    def test_parse_npc(self):
        n = N.parse_npc(npc_subs("BanditMelee", female=True), 0x0001A67D)
        self.assertEqual(n["edid"], "BanditMelee")
        self.assertTrue(n["female"])
        self.assertEqual(n["race"], 0x13746)
        self.assertEqual(n["head_parts"], [0x2001, 0x2002])
        self.assertEqual(n["packages"], [0x1000, 0x1001])
        self.assertEqual(n["factions"], [(0x13794, 2)])
        self.assertEqual(n["hair_color"], 0x3001)
        self.assertAlmostEqual(n["height"], 1.03, places=5)
        self.assertEqual(n["outfit"], 0x4001)
        self.assertAlmostEqual(n["face_morph"]["nose up/down"], 0.1, places=5)
        self.assertAlmostEqual(n["face_morph"]["vampire"], 1.8, places=5)
        self.assertEqual(n["face_parts"], {"nose": 1, "unknown": -1, "eyes": 2, "mouth": 3})
        self.assertEqual(len(n["tints"]), 2)
        self.assertEqual(n["tints"][0], {"index": 7, "color": (10, 20, 30, 255), "value": 0.55, "preset": -1})
        self.assertEqual(n["full_name_id"], 0x1234)

    def test_head_part_and_color(self):
        hp = N.parse_head_part([(b"EDID", b"HairMaleNord01\0"), (b"MODL", b"Actors\\Character\\Hair\\Hair01.nif\0"),
                                (b"DATA", bytes([0x3])), (b"PNAM", struct.pack("<I", 3)),
                                (b"HNAM", struct.pack("<I", 0x2003)), (b"TNAM", struct.pack("<I", 0x5000))], 0x2001)
        self.assertEqual((hp["type_name"], hp["model"], hp["extra_parts"], hp["flags"]),
                         ("hair", "Actors\\Character\\Hair\\Hair01.nif", [0x2003], 3))
        c = N.parse_color([(b"EDID", b"HairColor01\0"), (b"CNAM", bytes([40, 30, 20, 255]))], 0x3001)
        self.assertEqual(c["rgba"], (40, 30, 20, 255))

    def test_facegen_paths(self):
        p = N.facegen_paths("Skyrim.esm", 0x0001A67D)
        self.assertEqual(p["mesh"], "meshes\\actors\\character\\facegendata\\facegeom\\Skyrim.esm\\0001A67D.nif")
        self.assertEqual(N.facegen_paths("Dawnguard.esm", 0x02003456)["tint"],
                         "textures\\actors\\character\\facegendata\\facetint\\Dawnguard.esm\\00003456.dds")

    def test_templates_and_plugin_round_trip(self):
        hdr = struct.pack("<4sIII", b"NPC_", 0, 0, 0) + bytes(8)
        recs = [(b"NPC_", hdr, npc_subs("Base"), 0x100),
                (b"NPC_", hdr, npc_subs("UsesBase", template=0x100, tflags=N.TEMPLATE_TRAITS), 0x101),
                (b"NPC_", hdr, npc_subs("Chain", template=0x101, tflags=N.TEMPLATE_TRAITS), 0x102),
                (b"NPC_", hdr, npc_subs("OwnFace", template=0x100, tflags=N.TEMPLATE_INVENTORY), 0x103),
                (b"NPC_", hdr, npc_subs("LoopA", template=0x105, tflags=N.TEMPLATE_TRAITS), 0x104),
                (b"NPC_", hdr, npc_subs("LoopB", template=0x104, tflags=N.TEMPLATE_TRAITS), 0x105)]
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Skyrim.esm")
            with open(esm, "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 1.71, "form_version": 44}, masters=()))
            npcs = {fid: N.parse_npc(subs, fid) for _t, _h, subs, fid in sfplugin.records(esm, [b"NPC_"])}
        self.assertEqual(len(npcs), 6)
        faces = N.faces_by_template(npcs)
        self.assertEqual(faces[0x101], 0x100)
        self.assertEqual(faces[0x102], 0x100)              # followed down the chain
        self.assertEqual(faces[0x103], 0x103)              # template for inventory only: own face
        self.assertIn(faces[0x104], (0x104, 0x105))        # a loop ends without hanging

    def test_head_shape_pick(self):
        class S:
            def __init__(self, name, n):
                self.name, self.positions = name, [(0, 0, 0)] * n
        shapes = [S(b"HairMale01", 900), S(b"MaleHeadNord", 600), S(b"MaleEyesBrown", 100)]
        self.assertEqual(N.head_shape(shapes).name, b"MaleHeadNord")
        self.assertEqual(N.head_shape([S(b"A", 5), S(b"B", 9)]).name, b"B")
        self.assertIsNone(N.head_shape([]))


if __name__ == "__main__":
    unittest.main()
