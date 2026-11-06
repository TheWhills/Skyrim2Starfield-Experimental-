"""scripts/npc/npc_dump.py compare(): our NPC vs its template, face dials summarised (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
from fo4sf import sfplugin  # noqa: E402
import npc_dump  # noqa: E402
import face_fit  # noqa: E402

z = sfplugin.zs


class DumpTests(unittest.TestCase):
    def test_compare(self):
        tpl = [(b"EDID", z("Tpl")), (b"DOFT", b"\x01\0\0\0"), (b"BMPN", z("female_af_md1_Mouth")),
               (b"BMPV", b"\0\0\x80\x3f"), (b"STON", b"\x06")]
        ours = [(b"EDID", z("S2SFace_Saadia")), (b"FMSI", b"\x01\0\0\0"), (b"STON", b"\x06")]
        r = npc_dump.compare(ours, tpl)
        self.assertEqual(r["only_ours"], ["EDID=S2SFace_Saadia"])
        self.assertEqual(r["only_template"], ["EDID=Tpl", "DOFT=01000000"])
        self.assertEqual(r["shape_counts"]["template"]["BMPN"], 1)

    def test_keep_blend_morphs(self):
        subs = [(b"EDID", z("T")), (b"FMSI", b"\x05\0\0\0"), (b"FMRS", b"\0" * 4), (b"BMPN", z("male_af_md1_Eyes")),
                (b"BMPV", b"\0\0\x80\x3f"), (b"STON", b"\x08")]
        gone = face_fit.with_face(subs, {13: 0.5})
        kept = face_fit.with_face(subs, {13: 0.5}, keep=(b"BMPN", b"BMPV", b"FMRI", b"FMRG"))
        self.assertNotIn(b"BMPN", [s for s, _d in gone])
        self.assertEqual([s for s, _d in kept].count(b"BMPN"), 1)
        self.assertEqual([s for s, _d in kept].count(b"FMSI"), 1)            # dials replaced, not added twice


class TemplateTests(unittest.TestCase):
    def test_without_templates(self):
        acbs = bytes.fromhex("2100000000000100000000002300136c")
        subs = [(b"EDID", z("T")), (b"ACBS", acbs), (b"TPLT", b"\1\0\0\0"), (b"TPTA", b"\0" * 48), (b"STON", b"\x08")]
        out = face_fit.without_templates(subs)
        self.assertEqual([s for s, _d in out], [b"EDID", b"ACBS", b"STON"])
        self.assertEqual(dict(out)[b"ACBS"], acbs[:14] + b"\0\0")



class BakedFaceTests(unittest.TestCase):
    def test_index_and_pick(self):
        names = {"Starfield - Textures01.ba2": ["textures\\actors\\character\\facecustomization\\starfield.esm\\0010c360_color.dds",
                                                "textures\\actors\\character\\facecustomization\\starfield.esm\\0010c360_normal.dds",
                                                "textures\\other.dds"],
                 "Starfield - TexturesPatch01.ba2": ["textures\\actors\\character\\facecustomization\\starfield.esm\\0010c360_normal.dds"]}
        idx = face_fit.baked_face_index(names)
        self.assertEqual(sorted(idx), [0x10C360])
        self.assertEqual(idx[0x10C360]["normal"][0], "Starfield - TexturesPatch01.ba2")    # the patch wins
        self.assertEqual(idx[0x10C360]["color"][0], "Starfield - Textures01.ba2")

    def test_pick_requires_baked(self):
        import struct as st
        def npc(fid, edid):
            subs = [(b"EDID", z(edid)), (b"ACBS", st.pack("<I", 0) + bytes(12)), (b"RNAM", st.pack("<I", 7)),
                    (b"FMSI", b"\0" * 4), (b"VTCK", b"\1\0\0\0"), (b"STON", b"\x08")]
            return (b"NPC_", b"", subs, fid)
        recs = [npc(1, "NoBake"), npc(2, "Baked")]
        self.assertEqual(face_fit.pick_template(recs, 7, False, None, skin=(8, None), baked={2})[3], 2)
        self.assertEqual(face_fit.pick_template(recs, 7, False, None, baked={2})[3], 2)
        self.assertEqual(face_fit.pick_template(recs, 7, False, None)[3], 1)

    def test_write(self):
        import tempfile
        from unittest import mock
        idx = {0x50569: {"color": ("a.ba2", "x_color.dds"), "ao": ("a.ba2", "x_ao.dds")}}

        class Fake:
            def __init__(self, path):
                pass

            def read(self, name):
                return name.encode()
        with tempfile.TemporaryDirectory() as d, mock.patch("fo4sf.ba2.Ba2", Fake):
            paths = face_fit.write_baked_face(idx, 0x50569, 0x03000805, d, d)
            self.assertEqual(sorted(os.path.basename(p) for p in paths), ["00000805_ao.dds", "00000805_color.dds"])
            self.assertIn(os.path.join("facecustomization", "S2SFaceTest.esm"), paths[0])
            self.assertEqual(open(paths[1], "rb").read(), b"x_color.dds")


if __name__ == "__main__":
    unittest.main()
