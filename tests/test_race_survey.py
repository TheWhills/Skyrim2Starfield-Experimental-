"""src/fo4sf/skyrimtri.py and scripts/npc/race_survey.py on synthetic files: a FRTRI003 file with difference and stat
morphs; a Skyrim.esm with NordRace and HighElfRace (same head topology, the elf's base head moved, an ears extra part,
an extra chargen slider), NPC counts, tints; a Starfield.esm HumanRace with chargen data and head parts."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_fo4land import grup, rec  # noqa: E402
from fo4sf import skyrimtri  # noqa: E402
import race_survey as S  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731
I = lambda v: struct.pack("<I", v)                                  # noqa: E731


def tri(base, morphs=(), stats=(), tris=((0, 1, 2),)):
    V = len(base)
    tris = [tuple(t) for t in tris]
    head = b"FRTRI003" + struct.pack("<10i", V, len(tris), 0, 0, 0, 0, 0, len(morphs), len(stats), 0) + bytes(16)
    body = np.asarray(base, "<f4").tobytes() + np.asarray(tris, "<i4").tobytes()
    for name, scale, deltas in morphs:
        n = name.encode() + b"\0"
        body += struct.pack("<i", len(n)) + n + struct.pack("<f", scale) + np.asarray(deltas, "<i2").tobytes()
    for name, verts in stats:
        n = name.encode() + b"\0"
        body += struct.pack("<i", len(n)) + n + struct.pack("<i", len(verts)) + np.asarray(verts, "<i4").tobytes()
    return head + body


class TriTests(unittest.TestCase):
    def test_parse(self):
        base = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        d = tri(base, [("NoseLong", 0.5, [(2, 0, 0), (0, 0, 0), (0, -4, 0)]), ("BrowUp", 1.0, [(0, 0, 1)] * 3)],
                [("Stat", [1, 2])])
        t = skyrimtri.parse(d)
        self.assertTrue(t["complete"])
        self.assertEqual((t["vertices"], [m["name"] for m in t["morphs"]], t["stat_morphs"]),
                         (3, ["NoseLong", "BrowUp"], [{"name": "Stat", "vertices": 2}]))
        self.assertEqual(t["morphs"][0]["max_offset"], 2.0)                 # 4 x 0.5
        self.assertFalse(skyrimtri.parse(d + b"x")["complete"])
        with self.assertRaises(skyrimtri.TriError):
            skyrimtri.parse(b"NOTATRI!" + bytes(80))


def race(fid, edid, face, extra=(), height=1.0, flags=0x3, tints=()):
    data = bytes(16) + struct.pack("<4fI", height, height * 0.98, 1.0, 1.0, flags) + bytes(40)
    f = [(b"EDID", Z(edid)), (b"DATA", data), (b"MNAM", b""), (b"ANAM", Z("Actors\\Character\\skeleton.nif")),
         (b"FNAM", b""), (b"ANAM", Z("Actors\\Character\\skeleton_female.nif")),
         (b"NAM1", b""), (b"MNAM", b""), (b"INDX", I(0)), (b"MODL", Z("Body.nif")), (b"FNAM", b""),
         (b"INDX", I(0)), (b"MODL", Z("BodyF.nif")), (b"HNAM", I(0x60) + I(0x61)), (b"ENAM", I(0x70)),
         (b"NAM3", b""), (b"MNAM", b""), (b"MODL", Z("behavior.hkx")),
         (b"NAM0", b""), (b"MNAM", b""), (b"INDX", I(0)), (b"HEAD", I(face))]
    for e in extra:
        f += [(b"INDX", I(1)), (b"HEAD", I(e))]
    f += [(b"MPAI", b""), (b"MPAV", bytes(32)), (b"RPRM", I(0x300)), (b"AHCM", I(0x80))]
    for i, (file, typ) in enumerate(tints):
        f += [(b"TINI", struct.pack("<H", i)), (b"TINT", Z(file)), (b"TINP", struct.pack("<H", typ)),
              (b"TINC", I(0x80)), (b"TINV", struct.pack("<f", 1.0)), (b"TIRS", struct.pack("<H", 0))]
    f += [(b"NAM0", b""), (b"FNAM", b""), (b"INDX", I(0)), (b"HEAD", I(face))]
    return rec(b"RACE", fid, f)


def hdpt(fid, edid, typ, model, tris=(), extra=()):
    f = [(b"EDID", Z(edid)), (b"MODL", Z(model)), (b"DATA", b"\x01"), (b"PNAM", I(typ))]
    f += [(b"HNAM", I(e)) for e in extra]
    for k, path in tris:
        f += [(b"NAM0", I(k)), (b"NAM1", Z(path))]
    return rec(b"HDPT", fid, f)


class RaceSurveyTests(unittest.TestCase):
    def test_survey(self):
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "Skyrim")
            os.makedirs(os.path.join(data, "meshes", "actors"))
            base = [(0, 0, 0), (70, 0, 0), (0, 70, 0)]
            files = {"nord.tri": tri(base, [("Aah", 1.0, [(0, 0, 0)] * 3)]),
                     "nord_cg.tri": tri(base, [("NoseLong", 1.0, [(1, 0, 0)] * 3)]),
                     "elf.tri": tri([(0, 0, 0), (70, 0, 0), (0, 70, 7)], [("Aah", 1.0, [(0, 0, 0)] * 3)]),
                     "elf_cg.tri": tri(base, [("NoseLong", 1.0, [(1, 0, 0)] * 3), ("EarTip", 1.0, [(0, 0, 2)] * 3)])}
            for n, b in files.items():
                with open(os.path.join(data, "meshes", "actors", n), "wb") as fh:
                    fh.write(b)
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            parts = [hdpt(0x200, "MaleHeadNord", 1, "actors\\nordhead.nif", [(1, "actors\\nord.tri"),
                                                                             (2, "actors\\nord_cg.tri")]),
                     hdpt(0x201, "MaleHeadElf", 1, "actors\\elfhead.nif", [(1, "actors\\elf.tri"),
                                                                          (2, "actors\\elf_cg.tri")], extra=[0x202]),
                     hdpt(0x202, "MaleEarsElf", 0, "actors\\elfears.nif")]
            races = [race(0x100, "NordRace", 0x200, height=1.03, tints=[("SkinTone.dds", 6), ("Paint01.dds", 7)]),
                     race(0x101, "HighElfRace", 0x201, height=1.1, tints=[("SkinTone.dds", 6)])]
            npcs = [rec(b"NPC_", 0x400 + i, [(b"EDID", Z(f"N{i}")), (b"RNAM", I(0x100 if i < 3 else 0x101))])
                    for i in range(4)]
            with open(os.path.join(data, "Skyrim.esm"), "wb") as fh:
                fh.write(tes4 + grup(b"HDPT", 0, parts) + grup(b"RACE", 0, races) + grup(b"NPC_", 0, npcs))
            sf = os.path.join(d, "Starfield")
            os.makedirs(os.path.join(sf, "Data"))
            sf_race = rec(b"RACE", 0x500, [(b"EDID", Z("HumanRace")), (b"MNAM", b""), (b"ANAM", Z("skel.nif")),
                                            (b"MNAM", b""), (b"NAM0", b""), (b"RPRM", I(0x600)),
                                            (b"MPGN", Z("Nose")), (b"MPGM", Z("NoseA")), (b"MPGM", Z("NoseB")),
                                            (b"FMRI", I(3)), (b"FMRU", Z("male_eu_md2")),
                                            (b"FDSI", I(18)), (b"FDSI", I(24)), (b"BSTT", Z("bodytones")),
                                            (b"MNAM", b""), (b"INDX", I(0)), (b"HEAD", I(0x510))])
            sf_parts = [rec(b"HDPT", 0x510, [(b"EDID", Z("HumanHead")), (b"MODL", Z("head.nif")), (b"PNAM", I(1)),
                                             (b"MNAM", I(0x700))]),
                        rec(b"HDPT", 0x511, [(b"EDID", Z("CreatureHeadX")), (b"MODL", Z("ch.nif")), (b"PNAM", I(14))])]
            sf_npc = rec(b"NPC_", 0x520, [(b"EDID", Z("Joe")), (b"RNAM", I(0x500))])
            with open(os.path.join(sf, "Data", "Starfield.esm"), "wb") as fh:
                fh.write(tes4 + grup(b"RACE", 0, [sf_race]) + grup(b"HDPT", 0, sf_parts) + grup(b"NPC_", 0, [sf_npc]))
            out = os.path.join(d, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(S.main(["--skyrim-data", data, "--starfield", sf, "--out", out]), 0)
            with open(os.path.join(out, "race_survey.json")) as fh:
                r = json.load(fh)
            sky = {x["edid"]: x for x in r["skyrim"]}
            nord, elf = sky["NordRace"], sky["HighElfRace"]
            self.assertEqual((nord["npcs"], elf["npcs"], nord["height"]["male"], nord["flags"]),
                             (3, 1, 1.03, ["Playable", "FaceGen Head"]))
            self.assertEqual(nord["skeleton"], {"male": "Actors\\Character\\skeleton.nif",
                                                "female": "Actors\\Character\\skeleton_female.nif"})
            self.assertEqual((nord["hairs"], nord["body_parts"]["male"]), (2, ["Body.nif"]))
            h = nord["head"]["male"]
            self.assertEqual([(t["type"], t["file"]) for t in h["tints"]],
                             [("Skin Tone", "SkinTone.dds"), ("Paint", "Paint01.dds")])
            self.assertEqual((h["presets"], h["morph_variants"], h["hair_colors"]), (1, 1, 1))
            v = elf["head"]["male"]["vs_nord"]
            self.assertTrue(v["same_topology"])
            self.assertAlmostEqual(v["base_diff_max_m"], 0.1, places=3)          # 7 units on one vertex
            self.assertEqual((v["chargen_sliders"], v["chargen_only_here"], v["chargen_missing_here"]),
                             (2, ["EarTip"], []))
            self.assertEqual(v["parts_not_in_nord"], ["Misc: MaleEarsElf"])
            self.assertEqual(elf["head"]["male"]["parts"][0]["tris"][1]["morphs"], ["NoseLong", "EarTip"])
            sfr = r["starfield"]["races"][0]
            self.assertEqual((sfr["edid"], sfr["npcs"], sfr["skeleton"]["male"]), ("HumanRace", 1, "skel.nif"))
            c = sfr["chargen"]["male"]
            self.assertEqual((c["presets"], c["morph_groups"], c["dials"], c["phenotypes"], c["BSTT"]),
                             (1, [{"name": "Nose", "morphs": ["NoseA", "NoseB"]}], 2,
                              [{"index": 3, "id": "male_eu_md2"}], "bodytones"))
            self.assertEqual(sfr["head_parts"]["male"], [{"edid": "HumanHead", "type": "Face", "model": "head.nif"}])
            self.assertEqual(r["starfield"]["head_parts_by_type"], {"Face": 1, "Creature Head": 1})
            self.assertEqual(r["starfield"]["head_parts_with_morph"], {"Face": 1})
            with open(os.path.join(out, "race_survey.md")) as fh:
                self.assertIn("## NordRace (3 NPCs", fh.read())


if __name__ == "__main__":
    unittest.main()
