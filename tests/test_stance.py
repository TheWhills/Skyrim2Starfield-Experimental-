"""Stances: scripts/armor/stance_plugin.py (S2SStances.esm from a synthetic Starfield.esm), stance_pack.plan on
synthetic folders, and sfplugin's XXXX fields (no game files)."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import fo4land, sfplugin, subgraph  # noqa: E402
import stance_plugin as SP  # noqa: E402

try:
    import stance_pack as PK  # noqa: E402  (imports numpy through hkx_to_af)
except ImportError:                                   # pragma: no cover
    PK = None

PLAYER, MELEE1H, GUN = 0x000A0010, 0x000A0011, 0x000A0012


def entry(actor, target, graph, paths):
    return subgraph.build({"actor_keywords": actor, "target_keywords": target, "graph": graph, "paths": paths})


def starfield_esm(path, big=False):
    hdr = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)  # noqa: E731
    race = [(b"EDID", b"HumanRace\0"), (b"NAM6", b"Human_Root.agx\0")]
    if big:
        race.append((b"BIGD", bytes(70000)))           # a field over 64 KiB (XXXX)
    race += entry([PLAYER], [MELEE1H], "AnimTextData\\Tables\\Graphs\\Player_Melee.agx",
                  ["actors\\human\\animations\\melee\\onehanded\\player\\sword", "actors\\human\\animations\\melee\\onehanded\\player"])
    race += entry([PLAYER], [MELEE1H], "AnimTextData\\Tables\\Graphs\\1stPerson_Melee.agx",
                  ["actors\\human\\_1stperson\\animations\\melee\\onehanded"])
    race += entry([PLAYER], [GUN], "AnimTextData\\Tables\\Graphs\\Gun.agx", ["actors\\human\\animations\\gun\\common"])
    race.append((b"DNAM", b"actors\\human\\animations\\common\0"))
    recs = [(b"KYWD", hdr(b"KYWD"), [(b"EDID", b"ActorTypeHuman\0"), (b"FULL", struct.pack("<I", 5))], 0x000A0001),
            (b"RACE", hdr(b"RACE"), race, 0x00003CDB)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))


class StancePluginTests(unittest.TestCase):
    def test_keywords_and_race_entries(self):
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Starfield.esm")
            starfield_esm(esm, big=True)
            data, rep = SP.build(esm)
            out = os.path.join(d, SP.PLUGIN)
            with open(out, "wb") as fh:
                fh.write(data)
            kw = {sfplugin.edid(s): fid for _t, _h, s, fid in sfplugin.records(out, [b"KYWD"])}
            self.assertEqual(sorted(kw), ["S2S_StanceHigh", "S2S_StanceLow", "S2S_StanceMid"])
            self.assertTrue(all(fid >> 24 == 1 for fid in kw.values()))          # new records of this plugin
            race = sfplugin.records(out, [b"RACE"])[0]
            self.assertEqual(race[3], 0x00003CDB)                               # an override of the game's race
            subs = race[2]
            self.assertEqual(len(dict(subs)[b"BIGD"]), 70000)                  # the big field survives (XXXX)
            ents = subgraph.parse(subs)
            self.assertEqual(rep["melee_entries"], 1)                          # third person only by default
            self.assertEqual(len(ents), 3 + 3)
            for e, stance in zip(ents[:3], SP.STANCES):                         # copies come first
                self.assertEqual(e["actor_keywords"], [PLAYER, kw[SP.keyword_edid(stance)]])
                self.assertEqual(e["paths"][0], SP.stance_folder(stance))
                self.assertEqual(e["paths"][1:], ents[3]["paths"])
                self.assertEqual(e["target_keywords"], [MELEE1H])
            self.assertEqual([e["actor_keywords"] for e in ents[3:]], [[PLAYER]] * 3)   # originals unchanged
            self.assertEqual(dict(subs)[b"DNAM"], b"actors\\human\\animations\\common\0")
            data1, rep1 = SP.build(esm, first_person=True)
            self.assertEqual(rep1["added_entries"], 6)

    def test_no_melee_entries(self):
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Starfield.esm")
            hdr = struct.pack("<4sIII", b"RACE", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
            kh = struct.pack("<4sIII", b"KYWD", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
            with open(esm, "wb") as fh:
                fh.write(sfplugin.build([(b"KYWD", kh, [(b"EDID", b"K\0")], 1),
                                         (b"RACE", hdr, [(b"EDID", b"HumanRace\0")], 2)],
                                        {"hedr_version": 0.96, "form_version": 555}, masters=()))
            with self.assertRaises(SystemExit):
                SP.build(esm)

    def test_entry_race_field_kept(self):
        subs = [(b"SADD", struct.pack("<I", 0x3CDB))] + entry([PLAYER], [MELEE1H], "G.agx", ["actors\\human\\animations\\melee"])
        e = subgraph.parse(subs)
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["race"], 0x3CDB)
        self.assertEqual(subgraph.build(e[0])[0], (b"SADD", struct.pack("<I", 0x3CDB)))
        out, _rep = SP.race_with_stances(subs, {"High": 0x01000800})
        copies = subgraph.parse(out)
        self.assertEqual([c["race"] for c in copies], [0x3CDB, 0x3CDB])

    def test_xxxx_round_trip(self):
        raw = sfplugin.subrecord_bytes(b"BIGD", b"x" * 70000) + sfplugin.subrecord_bytes(b"EDID", b"A\0")
        self.assertEqual(list(fo4land.iter_subrecords(raw)), [(b"BIGD", b"x" * 70000), (b"EDID", b"A\0")])


@unittest.skipIf(PK is None, "numpy not installed")
class StancePackPlanTests(unittest.TestCase):
    def test_unroll(self):
        self.assertEqual(PK.unroll({1: 2, 2: 3, 3: 4, 4: 5, 5: 2}, 7), [1, 2, 3, 4, 5, 2, 3])
        self.assertEqual(PK.unroll({1: 2, 2: 1}, 3), [1, 2, 1])

    def test_plan_on_synthetic_folders(self):
        with tempfile.TemporaryDirectory() as d:
            anims = os.path.join(d, "anims")
            folder = "melee/onehanded/player/sword"
            fdir = os.path.join(anims, *"meshes/actors/human/animations".split("/"), *folder.split("/"))
            os.makedirs(fdir)
            for stem in ["meleeattack_a", "meleeattack_b", "meleeattack_c", "meleeattackpower_a",
                         "meleeattacksprint"] + PK.animslots.HOSTS[:2]:
                open(os.path.join(fdir, stem + ".afx"), "w").close()
            sets = {}
            for name, n in (("Neutral", 3), ("High", 5)):
                m = os.path.join(d, name)
                os.makedirs(m)
                for k in range(1, n + 1):
                    open(os.path.join(m, f"mco_attack{k}.hkx"), "wb").close()  # unreadable: in-order chain
                open(os.path.join(m, "mco_powerattack1.hkx"), "wb").close()
                sets[name] = m
            p, n, tags = PK.plan(sets, [folder], anims)
            self.assertEqual(n, 5)                                   # the longest chain, if the slots hold it
            self.assertEqual(len(tags), 5)
            self.assertEqual(p["High"]["sequence"], [1, 2, 3, 4, 5])
            self.assertIsNone(p["High"]["wrap"])
            self.assertEqual(p["Neutral"]["sequence"], [1, 2, 3, 1, 2])   # a shorter chain repeats around the ring
            self.assertEqual(len(p["High"]["replace"]), 5 + 1)           # 5 attacks + the power attack
            self.assertTrue(all("::" in r for r in p["High"]["replace"]))

    def test_stance_clips_keep_the_weapon_subpath(self):
        """Stance clips go to s2s_stances/<stance>/onehanded/player/sword (the game adds the weapon subfolders under
        each root folder; clips at the stance root lost to the vanilla sword folder in the owner's run)."""
        self.assertEqual(PK.stance_subpath("melee/onehanded/player/sword"), ["onehanded", "player", "sword"])
        self.assertEqual(PK.stance_subpath("Melee\\OneHanded\\Player"), ["OneHanded", "Player"])
        with tempfile.TemporaryDirectory() as d:
            folder = "melee/onehanded/player/sword"
            src = os.path.join(d, "tmp", *PK.bfco_pack.ANIMS.split("/"), *folder.split("/"))
            os.makedirs(src)
            for fn in ("MeleeAttack_A.af", "MeleeAttack_A.afx", "notes.txt"):
                open(os.path.join(src, fn), "w").close()
            self.assertEqual(PK._move_into_stance(os.path.join(d, "tmp"), folder, os.path.join(d, "out"), "High"), 2)
            dst = os.path.join(d, "out", "meshes", *SP.stance_folder("High").split("\\"), "onehanded", "player", "sword")
            self.assertEqual(sorted(os.listdir(dst)), ["MeleeAttack_A.af", "MeleeAttack_A.afx"])


if __name__ == "__main__":
    unittest.main()
