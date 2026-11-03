"""scripts/npc/skyrim_hairs.py: Skyrim hair head parts read across plugins, chosen, and exported as Starfield looks-menu
hairstyles, on synthetic games only."""
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import nif, sfnif, sfplugin, smpcloth  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
from test_smpcloth import hair_nif_bytes, template_root  # noqa: E402
import skyrim_hairs as SH  # noqa: E402

INFO = {"hedr_version": 1.7, "form_version": 44}


def hdpt(edid, model, kind, flags, extra=(), races=None):
    subs = [(b"EDID", edid.encode() + b"\0"), (b"MODL", model.encode() + b"\0"), (b"DATA", bytes([flags])),
            (b"PNAM", struct.pack("<I", kind))]
    subs += [(b"HNAM", struct.pack("<I", x)) for x in extra]
    if races is not None:
        subs.append((b"RNAM", struct.pack("<I", races)))
    return subs


def rec(t, subs, fid):
    return (t, struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 44, 0), subs, fid)


def skyrim_esms(d):
    """Skyrim.esm: a woman's hair with a hairline extra part, a man's hair, a Khajiit hair, a beard; Dawnguard.esm:
    a hair whose extra part is Skyrim.esm's hairline."""
    sky = [rec(b"FLST", [(b"EDID", b"HeadPartsHumansandVampires\0")], 0x000A0001),
           rec(b"FLST", [(b"EDID", b"HeadPartsKhajiitandVampire\0")], 0x000A0002),
           rec(b"HDPT", hdpt("HairLineFemaleNord01", "Actors\\Character\\Hair\\HairLineF01.nif", 3, 0x0C), 0x000B0001),
           rec(b"HDPT", hdpt("HairFemaleNord01", "Actors\\Character\\Hair\\HairF01.nif", 3, 0x05, [0x000B0001],
                             0x000A0001), 0x000B0002),
           rec(b"HDPT", hdpt("HairMaleNord01", "Actors\\Character\\Hair\\HairM01.nif", 3, 0x03, (), 0x000A0001),
               0x000B0003),
           rec(b"HDPT", hdpt("HairKhajiitFemale01", "Actors\\Character\\Hair\\HairKF01.nif", 3, 0x05, (),
                             0x000A0002), 0x000B0004),
           rec(b"HDPT", hdpt("BeardNord01", "Actors\\Character\\Hair\\Beard01.nif", 4, 0x03, (), 0x000A0001),
               0x000B0005)]
    with open(os.path.join(d, "Skyrim.esm"), "wb") as fh:
        fh.write(sfplugin.build(sky, INFO, masters=()))
    dg = [rec(b"HDPT", hdpt("HairFemaleSerana", "DLC01\\Hair\\Serana.nif", 3, 0x04, [0x000B0001], 0x000A0001),
              0x01000801)]
    with open(os.path.join(d, "Dawnguard.esm"), "wb") as fh:
        fh.write(sfplugin.build(dg, INFO, masters=("Skyrim.esm",)))


class PartTests(unittest.TestCase):
    def test_load_choose_and_merge_across_plugins(self):
        with tempfile.TemporaryDirectory() as d:
            skyrim_esms(d)
            self.assertEqual(SH.plugin_masters(os.path.join(d, "Dawnguard.esm")), ["skyrim.esm"])
            parts, lists = SH.load_parts(d)
        by = {p["edid"]: p for p in parts.values()}
        serana = by["HairFemaleSerana"]
        self.assertEqual(serana["key"], ("dawnguard.esm", 0x801))
        self.assertEqual(serana["extra_parts"], [("skyrim.esm", 0xB0001)])        # resolved through its master
        self.assertEqual(SH.part_models(serana["key"], parts),
                         ["DLC01\\Hair\\Serana.nif", "Actors\\Character\\Hair\\HairLineF01.nif"])
        chosen = sorted(p["edid"] for p in parts.values() if SH.wanted(p, lists))
        self.assertEqual(chosen, ["HairFemaleNord01", "HairFemaleSerana", "HairMaleNord01"])   # no extra / beast
        self.assertIn("BeardNord01", [p["edid"] for p in parts.values()
                                      if SH.wanted(p, lists, (SH.HAIR, SH.FACIAL_HAIR))])
        self.assertEqual(sorted(p["edid"] for p in parts.values() if SH.wanted(p, lists, playable_only=True)),
                         ["HairFemaleNord01", "HairMaleNord01"])                 # Serana's is not playable
        self.assertTrue(SH.is_female(by["HairFemaleNord01"]))
        self.assertFalse(SH.is_female(by["HairMaleNord01"]))
        self.assertFalse(SH.is_female(by["BeardNord01"]))
        self.assertTrue(SH.is_female({"type": 3, "flags": 0, "edid": "HairFemaleOdd"}))
        self.assertFalse(SH.is_female({"type": 3, "flags": 0, "edid": "HairMaleOdd"}))


class MainTests(unittest.TestCase):
    def test_main_on_synthetic_games(self):
        from fo4sf import textures
        import hair_pack
        with tempfile.TemporaryDirectory() as d:
            sky = os.path.join(d, "Skyrim", "Data")
            os.makedirs(sky)
            skyrim_esms(sky)
            for rel in ("meshes/actors/character/hair/hairf01.nif", "meshes/actors/character/hair/hairlinef01.nif",
                        "meshes/actors/character/hair/hairm01.nif", "meshes/dlc01/hair/serana.nif"):
                p = os.path.join(sky, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(hair_nif_bytes())
            for rel in ("textures/hair/h.dds", "textures/hair/h_n.dds"):
                p = os.path.join(sky, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(F.rgba_dds(alpha=100))
            sf = os.path.join(d, "Starfield")
            os.makedirs(os.path.join(sf, "Data"))
            os.makedirs(os.path.join(sf, "Tools"))
            bob = hdpt("Human_Female_Hair_Bob", "Actors\\Human\\Mesh\\hairs\\bob\\bob_f.nif", 3, 0x01)
            short = hdpt("Human_Male_Hair_Short", "Actors\\Human\\Mesh\\hairs\\short\\short_m.nif", 3, 0x01)
            lnam = lambda *ids: [(b"LNAM", struct.pack("<I", i)) for i in ids]     # noqa: E731
            sfr = [rec(b"HDPT", bob, 0x00002311), rec(b"HDPT", short, 0x00002312),
                   rec(b"FLST", [(b"EDID", b"HeadPartsChargenOptionsFemale\0")] + lnam(0x2311), 0x0003D9B0),
                   rec(b"FLST", [(b"EDID", b"HeadPartsChargenOptionsMale\0")] + lnam(0x2312), 0x0003D9AF)]
            with open(os.path.join(sf, "Data", "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build(sfr, {"hedr_version": 0.96, "form_version": 555}, masters=()))
            F.content_resources(os.path.join(sf, "Tools", "ContentResources.zip"))
            ident = (1, 0, 0, 0, 1, 0, 0, 0, 1)

            def game_nif(bones, binds):
                sh = sfnif.SkinnedShape(b"Hair", b"aa\\bb", 3, 3, "materials\\hair.mat", bones,
                                        [((0.0, 0.0, 0.0, 1.0), ident, t, 1.0) for t in binds])
                return nif.serialize(sfnif.build_skinned_nif(b"Hair", [sh]))
            fbn = game_nif([b"faceBone_C_Chin", b"faceBone_C_HeadTop"], [(0, -0.1, -1.55), (0, 0, -1.75)])
            game = {"meshes/actors/human/mesh/hairs/bob/bob_f_facebones.nif": fbn,
                    "meshes/actors/human/mesh/hairs/short/short_m_facebones.nif": fbn}
            ks_dir = os.path.join(d, "S2S Hair")                                  # the KS hairstyles next to it
            os.makedirs(ks_dir)
            ks = [rec(b"HDPT", hdpt("S2S_Hair_Anna", "s2s\\hair\\anna.nif", 3, 0x01), 0x01000800),
                  rec(b"FLST", [(b"EDID", b"HeadPartsChargenOptionsFemale\0")] + lnam(0x2311, 0x01000800), 0x0003D9B0)]
            with open(os.path.join(ks_dir, "S2SHair.esm"), "wb") as fh:
                fh.write(sfplugin.build(ks, {"hedr_version": 0.96, "form_version": 555}))
            out = os.path.join(d, "mod")
            with mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                    mock.patch.object(hair_pack, "read_game_file",
                                      lambda sfp, rel: game.get(rel.replace("\\", "/").lower())), \
                    mock.patch.object(hair_pack, "read_template", lambda spec: b"cloth"), \
                    mock.patch.object(smpcloth, "check_template", lambda blob: template_root()), \
                    contextlib.redirect_stdout(io.StringIO()):
                rc = SH.main(["--skyrim-data", sky, "--starfield", sf, "--texconv", "texconv.exe", "--out", out,
                              "--cloth-template", "bob/bob_f.nif"])
            self.assertEqual(rc, 0)
            rep = json.load(open(os.path.join(out, "skyrim_hairs.json")))
            rows = {r["skyrim"]: r for r in rep["parts"]}
            self.assertEqual(sorted(rows), ["HairFemaleNord01", "HairFemaleSerana", "HairMaleNord01"])
            for r in rows.values():
                self.assertTrue(r["ok"], r)
                self.assertTrue(r["facebones"])
            self.assertEqual(len(rows["HairFemaleNord01"]["models"]), 2)            # the hairline merged in
            self.assertFalse(rows["HairMaleNord01"]["female"])
            self.assertEqual(rep["templates"], {"female type 3": "Human_Female_Hair_Bob",
                                                "male type 3": "Human_Male_Hair_Short"})
            hair_dir = os.path.join(out, "meshes", "s2s", "skyrimhair")
            self.assertTrue(os.path.isfile(os.path.join(hair_dir, "hairfemalenord01.nif")))
            fb = sfnif.parse_skin(nif.parse(open(os.path.join(hair_dir, "hairfemalenord01_facebones.nif"),
                                                 "rb").read()))
            self.assertNotIn(b"C_Head", fb["bones"])
            got = sfplugin.records(os.path.join(out, SH.PLUGIN), [b"HDPT", b"FLST"])
            parts = {sfplugin.edid(r[2]): r for r in got if r[0] == b"HDPT"}
            self.assertEqual(sorted(parts), ["S2S_HairFemaleNord01", "S2S_HairFemaleSerana", "S2S_HairMaleNord01"])
            nord = dict(parts["S2S_HairFemaleNord01"][2])
            self.assertEqual(nord[b"MODL"], b"s2s\\skyrimhair\\hairfemalenord01.nif\0")
            self.assertEqual(nord[b"FULL"], b"HairFemaleNord01 (Skyrim)\0")
            lists = {sfplugin.edid(r[2]): r for r in got if r[0] == b"FLST"}
            fem = [struct.unpack("<I", x)[0] for s, x in lists["HeadPartsChargenOptionsFemale"][2] if s == b"LNAM"]
            self.assertEqual(fem[0], 0x2311)                                        # the vanilla entry kept
            self.assertEqual(fem[1], 0x01000800)                                    # the KS hairstyle kept (master 1)
            self.assertEqual(set(fem[2:]), {parts["S2S_HairFemaleNord01"][3], parts["S2S_HairFemaleSerana"][3]})
            self.assertEqual({parts[k][3] >> 24 for k in parts}, {2})               # ours after both masters
            self.assertEqual(rep["masters"], ["Starfield.esm", "S2SHair.esm"])
            male = [struct.unpack("<I", x)[0] for s, x in lists["HeadPartsChargenOptionsMale"][2] if s == b"LNAM"]
            self.assertEqual(male, [0x2312, parts["S2S_HairMaleNord01"][3]])
            mats = rows["HairFemaleNord01"]["materials"]
            self.assertTrue(all(m and m.lower().endswith(".mat") for m in mats))
            self.assertTrue(any("_hair" in m for m in mats))                       # the hair shader
            self.assertTrue(np.isfinite(rows["HairMaleNord01"]["vertices"]))


if __name__ == "__main__":
    unittest.main()
