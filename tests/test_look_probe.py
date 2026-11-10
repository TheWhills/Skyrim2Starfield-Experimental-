"""look_probe: skin-tone / eye-colour records followed from HumanRace and the eye head parts (2026-11-10)."""
import contextlib
import io
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

from fo4sf import sfplugin  # noqa: E402
import look_probe as L  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                 # noqa: E731
I = lambda v: struct.pack("<I", v)                               # noqa: E731


def esm(path, recs):
    h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)   # noqa: E731
    with open(path, "wb") as fh:
        fh.write(sfplugin.build([(t, h(t), s, f) for t, s, f in recs], {"hedr_version": 0.96, "form_version": 555},
                                masters=()))


class ProbeTests(unittest.TestCase):
    def test_probe(self):
        with tempfile.TemporaryDirectory() as d:
            sf = os.path.join(d, "Data")
            os.makedirs(sf)
            esm(os.path.join(sf, "Starfield.esm"), [
                (b"RACE", [(b"EDID", Z("HumanRace")), (b"MNAM", b""), (b"FDDS", Z("SkinTones_Human")),
                           (b"BSTT", Z("BodySkin_Human")), (b"FNAM", b""), (b"FDDS", Z("SkinTones_Human"))], 0x347D),
                (b"AVMD", [(b"EDID", Z("SkinTones_Human")), (b"MNAM", I(2)), (b"YNAM", Z("Skin")),
                           (b"TNAM", Z("Tones")), (b"ITMC", I(2)), (b"LNAM", Z("Simple_Tone01")),
                           (b"LNAM", Z("Unlinked"))], 0x900),
                (b"AVMD", [(b"EDID", Z("Tone01")), (b"MNAM", I(1)), (b"YNAM", Z("x")), (b"TNAM", Z("y")),
                           (b"VNAM", Z("textures\\skin01.dds"))], 0x901),
                (b"FLST", [(b"EDID", Z("HeadPartsHumanRace")), (b"LNAM", I(0x347D))], 0x24A),
                (b"TXST", [(b"EDID", Z("EyeTex")), (b"TX00", Z("textures\\eye_d.dds"))], 0x950),
                (b"HDPT", [(b"EDID", Z("Human_Eye_R")), (b"PNAM", I(2)), (b"NAM2", Z("EyeColors")),
                           (b"TNAM", I(0x950)), (b"RNAM", I(0x24A))], 0x960),
                (b"HDPT", [(b"EDID", Z("Alien_Eye")), (b"PNAM", I(12)), (b"RNAM", I(0x777))], 0x961),
                (b"AVMD", [(b"EDID", Z("EyeColors")), (b"MNAM", I(2)), (b"YNAM", Z("a")), (b"TNAM", Z("b"))], 0x902)])
            mod = os.path.join(d, "aliens.esm")
            esm(mod, [(b"RACE", [(b"EDID", Z("TwilekRace")), (b"MNAM", b""), (b"FDDS", Z("GreenSkin"))], 0x800),
                      (b"AVMD", [(b"EDID", Z("GreenSkin")), (b"MNAM", I(1)), (b"YNAM", Z("g")), (b"TNAM", Z("h"))],
                       0x801)])
            out = os.path.join(d, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(L.main(["--starfield", d, "--plugin", mod, "--out", out]), 0)
            rep = L.probe([os.path.join(sf, "Starfield.esm"), mod])
        hr = rep["races"]["HumanRace"]
        self.assertEqual(hr["strings"], {"male": {"FDDS": "SkinTones_Human", "BSTT": "BodySkin_Human"},
                                         "female": {"FDDS": "SkinTones_Human"}})
        t = hr["avmd"]["male"]["FDDS"][0]
        self.assertEqual(t["edid"], "SkinTones_Human")
        self.assertEqual(t["links"]["Simple_Tone01"]["edid"], "Tone01")             # "<Prefix>_<Name>" followed
        self.assertIn(("VNAM", "textures\\skin01.dds"), t["links"]["Simple_Tone01"]["fields"])
        self.assertEqual(hr["avmd"]["male"]["BSTT"], [])
        self.assertEqual(rep["races"]["TwilekRace"]["avmd"]["male"]["FDDS"][0]["edid"], "GreenSkin")
        self.assertEqual(list(rep["eyes"]), ["Human_Eye_R"])                        # the alien eye: not on the list
        self.assertEqual(rep["eyes"]["Human_Eye_R"]["colour_mapping"][0]["edid"], "EyeColors")
        self.assertIn(("TX00", "textures\\eye_d.dds"), rep["eyes"]["Human_Eye_R"]["texture_set"])
        md = L.markdown(rep)
        self.assertIn("AVMD Tone01", md)

    def test_missing_plugin_message(self):
        """2026-11-10: the owner's --plugin "<aliens mod>.esm" (the placeholder) gave an OSError traceback."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Data"))
            esm(os.path.join(d, "Data", "Starfield.esm"), [])
            with self.assertRaises(SystemExit) as cm:
                L.main(["--starfield", d, "--out", d, "--plugin", "<aliens mod>.esm"])
            self.assertIn("plugin not found: <aliens mod>.esm", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
