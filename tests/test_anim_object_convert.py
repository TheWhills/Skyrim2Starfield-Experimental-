"""scripts/armor/anim_object_convert.py: a converted static model turned into an animation object (root name, Prn,
no collision), on a synthetic Starfield NIF."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import nif, sfnif  # noqa: E402
import anim_object_convert as C  # noqa: E402


class AnimObjectConvertTest(unittest.TestCase):
    def test_make_anim_object(self):
        shape = sfnif.StaticShape(b"Broom", b"a" * 20 + b"\\" + b"b" * 20, 6, 4, "materials\\s2s\\broom.mat",
                                  (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        src = nif.serialize(sfnif.build_static_nif(b"Object01", [shape], collision_blob=b"blob"))
        out = nif.parse(C.make_anim_object(src, "S2S_AnimObjectBroomSkyrim", "R_AnimObject1"))
        root = out.blocks[0]
        name, count = struct.unpack_from("<iI", root, 0)
        self.assertEqual(out.strings[name], b"S2S_AnimObjectBroomSkyrim")
        refs = struct.unpack_from(f"<{count}i", root, 8)
        extras = {out.strings[struct.unpack_from("<I", out.blocks[r])[0]]: out.strings[struct.unpack_from("<I", out.blocks[r], 4)[0]]
                  for r in refs if out.type_of(r) == "NiStringExtraData"}
        self.assertEqual(extras, {b"Prn": b"R_AnimObject1"})
        self.assertIn("BSXFlags", [out.type_of(r) for r in refs])
        coll = struct.unpack_from("<i", root, 8 + 4 * count + 8 + C.NODE_TRANSFORM)[0]
        self.assertEqual(coll, -1)                                        # no collision on a held prop
        bsx = next(b for i, b in enumerate(out.blocks) if out.type_of(i) == "BSXFlags")
        self.assertEqual(struct.unpack_from("<I", bsx, 4)[0], 0)
        kids = struct.unpack_from("<I", root, 8 + 4 * count + 8 + C.NODE_TRANSFORM + 4)[0]
        self.assertEqual(kids, 1)                                         # the shape is still there
        again = nif.parse(C.make_anim_object(nif.serialize(out), "X", "R_AnimObject2"))   # one Prn, replaced
        r2 = again.blocks[0]
        c2 = struct.unpack_from("<I", r2, 4)[0]
        prns = [r for r in struct.unpack_from(f"<{c2}i", r2, 8) if again.type_of(r) == "NiStringExtraData"]
        self.assertEqual(len(prns), 1)


    def test_skyrim_prn_picks_the_bone(self):
        """2026-11-16 (forge props): a Skyrim animation object's root Prn names its prop bone; mapped to Starfield's."""
        shape = sfnif.StaticShape(b"Hammer", b"a" * 20 + b"\\" + b"b" * 20, 6, 4, "m.mat", (0, 0, 0, 1),
                                  (0, 0, 0, 1, 1, 1))
        src = nif.serialize(sfnif.build_static_nif(b"Object01", [shape]))
        self.assertIsNone(C.skyrim_prn(src))
        tagged = C.make_anim_object(src, "AnimObjectBlacksmithForgeHammer", "AnimObjectR")
        self.assertEqual(C.skyrim_prn(tagged), "AnimObjectR")
        self.assertEqual(C.bone_for("AnimObjectR", "x"), "R_AnimObject1")
        self.assertEqual(C.bone_for("animobjectl", "x"), "L_AnimObject1")
        self.assertEqual(C.bone_for(None, "L_AnimObject1"), "L_AnimObject1")
        import stance_plugin
        for e, _v, _m in stance_plugin.PROP_OBJECTS:
            self.assertIn(e, C.PROP_SOURCES)


if __name__ == "__main__":
    unittest.main()
