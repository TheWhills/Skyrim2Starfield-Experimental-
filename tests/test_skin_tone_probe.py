"""skin_tone_probe: Skyrim skin tone presets (tint mask type 6) and Starfield skin tone groups (2026-11-11, owner:
test the Orc's skin tone before building every race)."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

from fo4sf import sfplugin  # noqa: E402
import skin_tone_probe as P  # noqa: E402

Z = sfplugin.zs
I = lambda v: struct.pack("<I", v)          # noqa: E731
H = lambda v: struct.pack("<H", v)          # noqa: E731
F = lambda v: struct.pack("<f", v)          # noqa: E731


def hdr(t):
    return struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 44, 0)


class ProbeTests(unittest.TestCase):
    def test_skyrim_and_starfield(self):
        race = [(b"EDID", Z("OrcRace")), (b"MNAM", b""),
                (b"TINI", H(1)), (b"TINT", Z("Actors\\Character\\Character Assets\\TintMasks\\SkinTone.dds")),
                (b"TINP", H(6)), (b"TIND", I(0x100)),
                (b"TINC", I(0x100)), (b"TINV", F(1.0)), (b"TIRS", H(0)),
                (b"TINC", I(0x101)), (b"TINV", F(0.8)), (b"TIRS", H(1)),
                (b"TINI", H(2)), (b"TINT", Z("x.dds")), (b"TINP", H(1)),
                (b"FNAM", b""), (b"TINI", H(1)), (b"TINP", H(6)), (b"TINC", I(0x101)), (b"TINV", F(0.5))]
        recs = [(b"RACE", hdr(b"RACE"), race, 0x13746),
                (b"CLFM", hdr(b"CLFM"), [(b"EDID", Z("SkinToneOrc01")), (b"CNAM", bytes([90, 120, 60, 0]))], 0x100),
                (b"CLFM", hdr(b"CLFM"), [(b"EDID", Z("SkinToneOrc02")), (b"CNAM", bytes([80, 100, 50, 0]))], 0x101)]
        avmd = [(b"AVMD", hdr(b"AVMD"), [(b"EDID", Z("SimpleGroup_Naked_Body_Skin_Tones")),
                                         (b"YNAM", Z("Naked_Body_Skin_Tones")),
                                         (b"TNAM", Z("Male_Naked_Body_Skin_Tones")),
                                         (b"LNAM", Z("sk0")), (b"VNAM", Z("textures/a/sk0_color.dds"))], 0x163F4),
                (b"AVMD", hdr(b"AVMD"), [(b"EDID", Z("SimpleGroup_Hair")), (b"YNAM", Z("Hair"))], 0x163F5)]
        with tempfile.TemporaryDirectory() as d:
            sky = os.path.join(d, "Skyrim.esm")
            with open(sky, "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 1.7, "form_version": 44}, masters=()))
            with open(os.path.join(d, "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build(avmd, {"hedr_version": 0.96, "form_version": 555}, masters=()))

            class Arcs:
                def header(self, p):
                    return {"width": 2048, "height": 2048, "dxgi": 98, "path": p}
            rep = P.probe(sky, d, Arcs())
        orc = rep["skyrim"]["OrcRace"]
        self.assertEqual(orc["male"]["default"], "SkinToneOrc01")
        self.assertEqual([p["rgb"] for p in orc["male"]["presets"]], [(90, 120, 60), (80, 100, 50)])
        self.assertEqual([p["value"] for p in orc["female"]["presets"]], [0.5])
        (g,) = rep["starfield_groups"]
        self.assertEqual(g["tnam"], "Male_Naked_Body_Skin_Tones")
        self.assertEqual(g["first_texture"]["path"], "textures/a/sk0_color.dds")


if __name__ == "__main__":
    unittest.main()
