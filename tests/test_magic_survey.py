"""scripts/magic/magic_survey.py on synthetic plugins laid out as xEdit describes: Skyrim's Firebolt (fire and forget,
aimed, missile, Destruction), Flames (concentration, aimed, flame) and Conjure Familiar (summon, target location);
Starfield's power with a Value Modifier missile; the carry-over table; projectile types (Starfield's after a
length-prefixed string, 2- or 4-byte prefix); the layout range checks."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "magic"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_fo4land import grup, rec  # noqa: E402
import magic_survey as M  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731
I = lambda v: struct.pack("<I", v)                                  # noqa: E731


def sky_mgef(fid, edid, arch, proj, cast, delivery, school):
    d = bytearray(152)
    struct.pack_into("<i", d, 12, school)
    struct.pack_into("<I", d, 64, arch)
    struct.pack_into("<I", d, 72, proj)
    struct.pack_into("<II", d, 80, cast, delivery)
    return rec(b"MGEF", fid, [(b"EDID", Z(edid)), (b"DATA", bytes(d))])


def sky_spel(fid, edid, typ, cast, delivery, effect, etyp):
    spit = struct.pack("<IIIfIIffI", 10, 0, typ, 0.5, cast, delivery, 0, 0, 0)
    return rec(b"SPEL", fid, [(b"EDID", Z(edid)), (b"ETYP", I(etyp)), (b"SPIT", spit), (b"EFID", I(effect)),
                              (b"EFIT", bytes(12))])


def sky_proj(fid, typ):
    return rec(b"PROJ", fid, [(b"EDID", Z(f"P{fid:x}")), (b"DATA", struct.pack("<HH", 0, typ) + bytes(88))])


def sf_mgef(fid, edid, arch, proj, cast, delivery):
    d = bytearray(136)
    struct.pack_into("<I", d, 60, proj)
    struct.pack_into("<I", d, 80, arch)
    d[100], d[101] = cast, delivery
    return rec(b"MGEF", fid, [(b"EDID", Z(edid)), (b"DATA", bytes(d))])


def sf_spel(fid, edid, typ, cast, delivery, effect):
    spit = struct.pack("<IIBfBBffI", 10, 0, typ, 0.0, cast, delivery, 0, 0, 0)
    return rec(b"SPEL", fid, [(b"EDID", Z(edid)), (b"SPIT", spit), (b"EFID", I(effect))])


def sf_prod(typ, prefix=2, particle=b"fx"):
    head = bytes(81)
    s = particle + b"\0"
    ln = struct.pack("<H", len(s)) if prefix == 2 else struct.pack("<I", len(s))
    return head + ln + s + struct.pack("<fI", 0.0, 2) + bytes([typ]) + bytes(20)


class MagicTests(unittest.TestCase):
    def test_proj_types(self):
        self.assertEqual(M.sf_proj_type([(b"PROD", sf_prod(2, 2))]), ("Beam", 2))
        self.assertEqual(M.sky_proj_type([(b"DATA", struct.pack("<HH", 0, 8))]), "Flame")
        four = [[(b"PROD", sf_prod(7, 4, b"abcdefgh"))], [(b"PROD", sf_prod(2, 4, b"fx_beam"))]]
        self.assertEqual(M.prod_prefix(four), 4)                     # 2-byte reads of these are not valid strings
        self.assertEqual(M.prod_prefix([[(b"PROD", sf_prod(3, 2, b"flame"))]]), 2)
        self.assertEqual(M.sf_proj_type(four[0], 4), ("Plasma", 4))
        self.assertEqual(M.sf_proj_type([(b"PROD", bytes(40))]), (None, None))

    def test_survey(self):
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            equp = [rec(b"EQUP", 0x13F42, [(b"EDID", Z("EitherHand"))]), rec(b"EQUP", 0x25BEE, [(b"EDID", Z("Voice"))])]
            sky = [sky_mgef(0x10, "FireDamageFFAimed", 0, 0x30, 1, 2, 20),
                   sky_mgef(0x11, "FireDamageConcAimed", 0, 0x31, 2, 2, 20),
                   sky_mgef(0x12, "SummonFamiliar", 18, 0, 1, 4, 19)]
            spells = [sky_spel(0x20, "Firebolt", 0, 1, 2, 0x10, 0x13F42), sky_spel(0x21, "Flames", 0, 2, 2, 0x11, 0x13F42),
                      sky_spel(0x22, "ConjureFamiliar", 0, 1, 4, 0x12, 0x13F42),
                      sky_spel(0x23, "AbResistFire", 4, 0, 0, 0x10, 0)]          # an ability: not castable
            projs = [sky_proj(0x30, 1), sky_proj(0x31, 8)]
            sk = os.path.join(d, "Skyrim.esm")
            with open(sk, "wb") as fh:
                fh.write(tes4 + grup(b"EQUP", 0, equp) + grup(b"MGEF", 0, sky) + grup(b"SPEL", 0, spells)
                         + grup(b"PROJ", 0, projs))
            sfm = [sf_mgef(0x40, "PowerSunlessSpace", 0, 0x50, 1, 2), sf_mgef(0x41, "Gravwave", 33, 0, 1, 2)]
            sfs = [sf_spel(0x60, "PowerA", 2, 1, 2, 0x40)]
            sfp = [rec(b"PROJ", 0x50, [(b"EDID", Z("PowerProj")), (b"PROD", sf_prod(0, 2))])]
            sf = os.path.join(d, "Starfield.esm")
            with open(sf, "wb") as fh:
                fh.write(tes4 + grup(b"MGEF", 0, sfm) + grup(b"SPEL", 0, sfs) + grup(b"PROJ", 0, sfp))
            out = os.path.join(d, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(M.main(["--skyrim", sk, "--starfield", sf, "--out", out]), 0)
            with open(os.path.join(out, "magic_survey.json")) as fh:
                r = json.load(fh)
            with open(os.path.join(out, "magic_survey.md")) as fh:
                md = fh.read()
        s = r["skyrim"]["castable"]
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["by_school"], {"Destruction": 2, "Conjuration": 1})
        self.assertEqual(s["by_archetype"], {"Value Modifier": 2, "Summon Creature": 1})
        self.assertEqual(s["by_projectile_type"], {"Missile": 1, "Flame": 1})
        self.assertEqual(s["by_hand"], {"EitherHand": 3})
        self.assertEqual(r["skyrim"]["spell_types"], {"Spell": 3, "Ability": 1})
        co = r["carry_over"]
        self.assertEqual(co["archetypes"]["Value Modifier"], {"skyrim_spells": 2, "in_starfield_enum": True,
                                                              "starfield_effects": 1})
        self.assertEqual(co["archetypes"]["Summon Creature"]["starfield_effects"], 0)
        self.assertEqual(co["ways"]["Fire and Forget / Aimed / Missile"]["starfield_spells"], 1)
        self.assertEqual(co["ways"]["Concentration / Aimed / Flame"]["starfield_spells"], 0)
        self.assertEqual(r["starfield"]["projectile_types"], {"Missile": 1})
        self.assertEqual(r["starfield"]["effect_archetypes"], {"Value Modifier": 1, "Stagger": 1})
        self.assertEqual(r["skyrim"]["layout_check"]["archetype_in_range"], 1.0)
        self.assertEqual(r["starfield"]["layout_check"]["projectile_string_prefix"], {"2": 1})
        self.assertIn("| Summon Creature | 1 | yes | 0 |", md)


if __name__ == "__main__":
    unittest.main()
