import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import nif, objectlod as ol, sfnif  # noqa: E402


def objects():
    return {"bases": [{"edid": "SKY_A", "model": "skyrim\\landscape\\roads\\roadchunkl03.nif"},
                      {"edid": "SKY_B", "model": "skyrim\\furniture\\largecookingpot.nif"},
                      {"edid": "Marker", "model": "x.nif"}],
            "refs": [{"base": 0, "pos": [202.18, -689.31, 183.1], "rot": [0, 0, 0.3], "scale": 1.0},
                     {"base": 0, "pos": [205.0, -690.0, 183.0], "rot": [0, 0, 0], "scale": 1.25},
                     {"base": 1, "pos": [278.11, -676.61, 182.99], "rot": [0, 0, 1.0]},
                     {"base": 1, "pos": [-3301.0, -2450.0, 10.0], "rot": [0, 0, 0]},
                     {"base": 2, "pos": [0.0, 0.0, 0.0], "rot": [0, 0, 0]}]}


class ObjectLod(unittest.TestCase):
    def test_hashes_match_creation_kit(self):
        # from the owner's CK output: SKY_RoadChunkL03 entry hashes 0x625B2754 / 0x50B75708
        self.assertEqual(ol.model_hashes("skyrim\\landscape\\roads\\roadchunkl03.nif"), (0x625B2754, 0x50B75708))

    def test_plan_layout_and_round_trip(self):
        lodset, levels = ol.plan(objects(), {0: 0x1D6F, 1: 0x23FE})      # base 2 (a vanilla marker) left out
        self.assertEqual(lodset, (-34, -25, 37))                           # cells x -34..2, y -25..-7
        self.assertEqual(sorted(levels), [1, 2, 4, 8])
        for level, blocks in levels.items():
            self.assertEqual(sum(len(i) for e in blocks.values() for _h, i in e.values()), 4)   # every ref, each level
            for (bx, by) in blocks:
                self.assertEqual(((bx - lodset[0]) % level, (by - lodset[1]) % level), (0, 0))
        e = levels[1][(2, -7)]
        self.assertEqual(sorted(e), [0x01001D6F, 0x010023FE])
        inst = struct.unpack("<16f", e[0x01001D6F][1][1])
        self.assertAlmostEqual(inst[15], 1.25, 5)                          # scale separate, rotation unscaled
        self.assertAlmostEqual(inst[12], 205.0, 3)
        block = ol.node_bytes(e)
        self.assertEqual(ol.parse_node(block), e)
        self.assertTrue(block.endswith(b"\0" * 10))
        f = nif.parse(ol.nif_bytes(block))
        self.assertEqual((f.bs_version, f.type_of(0), f.strings), (175, "BSWeakReferenceNode", [b""]))

    def test_write_and_rerun_cleans(self):
        lodset, levels = ol.plan(objects(), {0: 0x1D6F, 1: 0x23FE})
        with tempfile.TemporaryDirectory() as d:
            mf = os.path.join(d, "w.objectlod.json")
            n = ol.write(d, ["SKYTamriel", "SKY_Tamriel"], lodset, levels, mf)
            self.assertTrue(os.path.isfile(os.path.join(d, "meshes", "terrain", "skytamriel", "objects",
                                                        "SKYTamriel.1.2.-7.nif")))
            self.assertEqual(struct.unpack("<5i", open(os.path.join(d, "lodsettings", "sky_tamriel.lod"), "rb").read()),
                             (*lodset, 0, 0))
            self.assertEqual(n, len(json.load(open(mf))))
            self.assertEqual(ol.remove(d, mf), n)


if __name__ == "__main__":
    unittest.main()
