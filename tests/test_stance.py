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
z_ = sfplugin.zs


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

    def test_dual_stance_keeps_the_three_stance_ids(self):
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Starfield.esm")
            starfield_esm(esm, big=True)
            _data, rep3 = SP.build(esm)
            _data, rep4 = SP.build(esm, stances=SP.STANCES_DUAL)
            self.assertEqual(SP.STANCES_DUAL[-1], "Dual")
            for k, v in rep3["keywords"].items():                              # saves keep their keywords
                self.assertEqual(rep4["keywords"][k], v)
            self.assertIn("S2S_StanceDual", rep4["keywords"])
            self.assertEqual(rep4["folders"]["Dual"], "actors\\human\\animations\\melee\\s2s_stances\\dual")
            self.assertEqual(rep4["added_entries"], 4)

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


TABLE = ("Role\tPerspective\tActor Keyword(s)\tTarget Keyword(s)\tBehavior Path\tAnimation Path(s)\n"
         "MT\t3rd\t\t\tAnimTextData\\Tables\\Graphs\\NPC_MT_Wrapping.agx\tactors\\human\\animations\\melee\\unarmed\n"
         "Weapon\t3rd\tAnimArchetypePlayer\tAnimOneHanded, AnimSword\tAnimTextData\\Tables\\Graphs\\Player_Melee.agx\t"
         "actors\\human\\animations\\melee\\onehanded\\player\\sword, actors\\human\\animations\\melee\\onehanded\\player\r\n"
         "Weapon\t3rd\tAnimArchetypePlayer, Female\tAnimOneHanded\tAnimTextData\\Tables\\Graphs\\Player_Melee.agx\t"
         "actors\\human\\animations\\melee\\onehanded\\player\\female\n"
         "Weapon\t1st\tAnimArchetypePlayer\tAnimOneHanded\tAnimTextData\\Tables\\Graphs\\1stPerson_Melee.agx\tx\n"
         "Weapon\t3rd\t\tAnimOneHanded, AnimSword\tAnimTextData\\Tables\\Graphs\\NPC_Melee.agx\ty\n"
         "Weapon\t3rd\tAnimArchetypePlayer\tAnimGripRifle\tAnimTextData\\Tables\\Graphs\\Player_Gun.agx\tz\n")


class StanceTableTests(unittest.TestCase):
    """The player's weapon sets live in the game's generated HumanRace table, not the esm (owner's archives)."""

    def test_parse_and_pick_player_one_handed_rows(self):
        rows = SP.parse_table(TABLE)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[1]["target"], ["AnimOneHanded", "AnimSword"])
        self.assertEqual(rows[1]["paths"][-1], "actors\\human\\animations\\melee\\onehanded\\player")   # \r stripped
        picked = SP.player_weapon_rows(rows)
        self.assertEqual([r["actor"] for r in picked], [["AnimArchetypePlayer"], ["AnimArchetypePlayer", "Female"]])

    def test_entries_from_table_rows(self):
        ids = {"animarchetypeplayer": PLAYER, "animonehanded": MELEE1H, "animsword": 0x000A0020}
        subs = [(b"EDID", b"HumanRace\0")] + entry([PLAYER], [GUN], "Gun.agx", ["gun"])
        rows = SP.player_weapon_rows(SP.parse_table(TABLE))
        out, rep = SP.race_with_stances(subs, {"High": 0x01000800, "Low": 0x01000802}, table_rows=rows,
                                        keyword_ids=ids)
        self.assertEqual(rep["source"], "generated table weapon rows")
        self.assertEqual((rep["melee_entries"], rep["added_entries"]), (1, 3))   # the Female row: keyword unknown here
        self.assertEqual(rep["neutral_entries"], 1)
        self.assertEqual(rep["unresolved_keywords"], ["Female"])
        ents = subgraph.parse(out)
        high = ents[0]
        self.assertEqual(high["actor_keywords"], [PLAYER, 0x01000800])
        self.assertEqual(high["target_keywords"], [MELEE1H, 0x000A0020])
        self.assertEqual(high["graph"], "AnimTextData\\Tables\\Graphs\\Player_Melee.agx")
        self.assertEqual(high["paths"], [SP.stance_folder("High"), SP.common_folder(),
                                         "actors\\human\\animations\\melee\\onehanded\\player\\sword",
                                         "actors\\human\\animations\\melee\\onehanded\\player"])
        self.assertEqual(high["flags"], "01 00 00 00")                          # role Weapon, third person
        self.assertEqual(ents[1]["actor_keywords"], [PLAYER, 0x01000802])
        neutral = ents[2]                                                     # shared folder first, no stance keyword
        self.assertEqual(neutral["actor_keywords"], [PLAYER])
        self.assertEqual(neutral["paths"][0], "actors\\human\\animations\\melee\\s2s_stances\\common")
        self.assertEqual(neutral["paths"][1:], high["paths"][2:])
        self.assertEqual(ents[3]["graph"], "Gun.agx")                           # the race's own entry kept, after
        out2, rep2 = SP.race_with_stances(subs, {"High": 0x01000800}, table_rows=rows, keyword_ids=ids, common=False)
        self.assertEqual((rep2["added_entries"], rep2["neutral_entries"]), (1, 0))
        self.assertEqual(subgraph.parse(out2)[0]["paths"][0:2], [SP.stance_folder("High"),
                                                                 "actors\\human\\animations\\melee\\onehanded\\player\\sword"])

    def test_weapon_type_entries_come_first(self):
        """A converted greatsword keeps AnimSword and carries S2S_AnimGreatsword: its entries (one keyword more on the
        weapon side) put the type folder first, per stance its stance folder before that (owner 2026-11-09)."""
        ids = {"animarchetypeplayer": PLAYER, "animonehanded": MELEE1H, "animsword": 0x000A0020}
        subs = [(b"EDID", b"HumanRace\0")] + entry([PLAYER], [GUN], "Gun.agx", ["gun"])
        rows = SP.player_weapon_rows(SP.parse_table(TABLE))
        gs, axe = 0x0100080B, 0x01000809
        out, rep = SP.race_with_stances(subs, {"High": 0x01000800}, table_rows=rows, keyword_ids=ids,
                                        types={"Greatsword": gs, "WarAxe": axe})
        ents = subgraph.parse(out)
        self.assertEqual(rep["type_entries"], 4)                    # 2 types x (1 stance + neutral), one row
        self.assertEqual(rep["added_entries"], 4 + 1 + 1)
        e = ents[0]
        self.assertEqual(e["actor_keywords"], [PLAYER, 0x01000800])
        self.assertEqual(e["target_keywords"], [MELEE1H, 0x000A0020, gs])
        self.assertEqual(e["paths"][:3], [SP.type_folder("Greatsword", "High"), SP.type_folder("Greatsword"),
                                          SP.common_folder()])
        self.assertEqual(e["paths"][3:], rows[0]["paths"])           # then the vanilla sword folders
        self.assertEqual(ents[1]["target_keywords"][-1], axe)
        neutral_gs = ents[2]
        self.assertEqual((neutral_gs["actor_keywords"], neutral_gs["target_keywords"][-1]), ([PLAYER], gs))
        self.assertEqual(neutral_gs["paths"][0], "actors\\human\\animations\\melee\\s2s_types\\greatsword")
        self.assertEqual(ents[4]["paths"][0], SP.stance_folder("High"))     # the sword stances after the types
        self.assertEqual(ents[-1]["graph"], "Gun.agx")

    def test_build_writes_type_keywords_after_the_stances(self):
        table = TABLE.replace("AnimArchetypePlayer, Female", "AnimArchetypePlayer")
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Starfield.esm")
            starfield_esm(esm)
            with open(esm, "rb") as fh:
                raw = fh.read()
            hdr = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)  # noqa: E731
            recs = sfplugin.records(esm, [b"KYWD", b"RACE"])
            recs += [(b"KYWD", hdr(b"KYWD"), [(b"EDID", z_(n))], fid) for n, fid in
                     (("AnimArchetypePlayer", PLAYER), ("AnimOneHanded", MELEE1H), ("AnimSword", 0x000A0020))]
            with open(esm, "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))
            self.assertTrue(raw)
            data, rep = SP.build(esm, stances=SP.STANCES_DUAL, table_text=table)
            data2, rep2 = SP.build(esm, stances=SP.STANCES, table_text=table)
            out = os.path.join(d, SP.PLUGIN)
            with open(out, "wb") as fh:
                fh.write(data)
            kw = {sfplugin.edid(s): fid for _t, _h, s, fid in sfplugin.records(out, [b"KYWD"])}
            _d, rep3 = SP.build(esm, table_text=table, weapon_types=())
        self.assertEqual(kw["S2S_AnimGreatsword"], sfplugin.new_form_id(SP.TYPE_INDEX + 3))
        self.assertEqual(kw["S2S_StanceHigh"], sfplugin.new_form_id(0))
        self.assertEqual(rep["type_keywords"], rep2["type_keywords"])     # the same ids with or without Dual
        self.assertEqual(len(rep["type_keywords"]), len(SP.WEAPON_TYPES))
        # 2 player rows x 6 types x (4 stances + neutral)
        self.assertEqual(rep["type_entries"], 2 * 6 * 5)
        self.assertEqual((rep3["type_keywords"], rep3["type_entries"]), ({}, 0))

    def test_build_with_a_table_whose_keywords_are_missing_stops(self):
        with tempfile.TemporaryDirectory() as d:
            esm = os.path.join(d, "Starfield.esm")
            starfield_esm(esm)
            with self.assertRaises(SystemExit):
                SP.build(esm, table_text=TABLE)


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
            p, n, tags, pslots = PK.plan(sets, [folder], anims)
            self.assertEqual(n, 5)                                   # the longest chain, if the slots hold it
            self.assertEqual(len(tags), 5)
            self.assertEqual(p["High"]["sequence"], [1, 2, 3, 4, 5])
            self.assertIsNone(p["High"]["wrap"])
            self.assertEqual(p["Neutral"]["sequence"], [1, 2, 3, 1, 2])   # a shorter chain repeats around the ring
            self.assertEqual(len(p["High"]["replace"]), 5 + 1)           # 5 attacks + the power attack
            self.assertEqual(pslots, {})                                 # no host left for power slots
            self.assertTrue(all("::" in r for r in p["High"]["replace"]))

    def test_power_slots_follow_the_attack_before(self):
        """BFCO / MCO: the power attack depends on the normal attack before it; each ring slot gets a power state
        on the hosts left after the normal slots, filled per stance (here the routing is unreadable: power 1)."""
        with tempfile.TemporaryDirectory() as d:
            anims = os.path.join(d, "anims")
            folder = "melee/onehanded/player/sword"
            fdir = os.path.join(anims, *"meshes/actors/human/animations".split("/"), *folder.split("/"))
            os.makedirs(fdir)
            for stem in ["meleeattack_a", "meleeattack_b", "meleeattack_c", "meleeattackpower_a"] + PK.animslots.HOSTS:
                open(os.path.join(fdir, stem + ".afx"), "w").close()
            m = os.path.join(d, "High")
            os.makedirs(m)
            for k in range(1, 5):
                open(os.path.join(m, f"mco_attack{k}.hkx"), "wb").close()
            for k in (1, 2):
                open(os.path.join(m, f"mco_powerattack{k}.hkx"), "wb").close()
            p, n, tags, pslots = PK.plan({"High": m}, [folder], anims)
            self.assertEqual(n, 4)
            self.assertEqual(len(pslots), 4)                             # 1 host for slot 4, 4 left for powers
            self.assertEqual(pslots[1], ("sneak_meleeattackpower_a", "MeleeAttack_E", folder))
            self.assertEqual(p["High"]["powers"], {1: 1, 2: 1, 3: 1, 4: 1})
            power_specs = [r for r in p["High"]["replace"] if "mco_powerattack1.hkx" in r and "::tag:" in r]
            self.assertEqual(len(power_specs), 4)
            r = PK.power_routing(n, pslots)
            self.assertEqual(r["attack_power"], {1: 1, 2: 2, 3: 3, 4: 4})
            self.assertEqual(r["power_attack"], {1: 2, 2: 3, 3: 4, 4: 1})
            self.assertEqual(r["power_power"], {1: 2, 2: 3, 3: 4, 4: 1})
            self.assertTrue(r["inner_only"])
            self.assertEqual(r["event"], "MeleeAttackPowerStart")
            self.assertEqual(r["cancel_event"], "ActionInterrupt")
            r6 = PK.power_routing(6, {j: pslots[j] for j in (1, 2, 3, 4)})   # slots 5, 6 without a host
            self.assertEqual(r6["tags"][5], "MeleeAttackPower_A")
            self.assertEqual((r6["attack_power"][5], r6["attack_power"][6]), (5, 5))
            self.assertEqual(r6["power_attack"][5], 1)                     # after the vanilla one: slot 1
            self.assertIsNone(PK.power_routing(n, {}))

    def test_stance_clips_go_flat_into_the_stance_folder(self):
        """The stance entries list s2s_stances/<stance> first; a subfolder below it is not searched (owner's run)."""
        with tempfile.TemporaryDirectory() as d:
            folder = "melee/onehanded/player/sword"
            src = os.path.join(d, "tmp", *PK.bfco_pack.ANIMS.split("/"), *folder.split("/"))
            os.makedirs(src)
            for fn in ("MeleeAttack_A.af", "MeleeAttack_A.afx", "notes.txt"):
                open(os.path.join(src, fn), "w").close()
            self.assertEqual(PK._move_into_stance(os.path.join(d, "tmp"), folder, os.path.join(d, "out"), "High"), 2)
            dst = os.path.join(d, "out", "meshes", *SP.stance_folder("High").split("\\"))
            self.assertEqual(sorted(os.listdir(dst)), ["MeleeAttack_A.af", "MeleeAttack_A.afx"])

    def test_weapon_type_pack_folders_and_fixed_ring(self):
        """A type pack moves every stance (Neutral too) into the type's folders and keeps the installed graph's ring:
        the tags and power hosts depend on the ring size alone."""
        self.assertEqual(PK.dest_folder("Neutral", "Greatsword"), SP.type_folder("Greatsword"))
        self.assertEqual(PK.dest_folder("High", "Greatsword"), SP.type_folder("Greatsword", "High"))
        self.assertEqual(PK.dest_folder("High"), SP.stance_folder("High"))
        with tempfile.TemporaryDirectory() as d:
            anims = os.path.join(d, "anims")
            folders = ["melee/onehanded/player/sword", "melee/onehanded/player"]
            for f in folders:
                fdir = os.path.join(anims, *"meshes/actors/human/animations".split("/"), *f.split("/"))
                os.makedirs(fdir, exist_ok=True)
                for stem in ["meleeattack_a", "meleeattack_b", "meleeattack_c", "meleeattackpower_a"] + \
                        PK.animslots.HOSTS[:4]:
                    open(os.path.join(fdir, stem + ".afx"), "w").close()
            m = os.path.join(d, "Neutral")
            os.makedirs(m)
            for k in range(1, 4):
                open(os.path.join(m, f"mco_attack{k}.hkx"), "wb").close()
            free, n_free, _t, _p = PK.plan({"Neutral": m}, folders, anims)
            p, n, tags, _ps = PK.plan({"Neutral": m}, folders, anims, exact=5, neutral_vanilla=False)
            self.assertEqual((n_free, n), (3, 5))
            self.assertEqual(p["Neutral"]["sequence"], [1, 2, 3, 1, 2])        # the short chain round the ring
            self.assertEqual(p["Neutral"]["folders"][0], folders[0])
            self.assertTrue(all(folders[0] in r for r in p["Neutral"]["replace"]))   # one folder only
            self.assertGreater(len(free["Neutral"]["replace"]), 3)              # the plain pack fills both
            p6, n6, tags6, _ = PK.plan({"Neutral": m}, folders, anims, exact=5)
            self.assertEqual(tags6, tags)                                        # same ring, same tags
            with self.assertRaises(SystemExit):
                PK.plan({"Neutral": m}, folders, anims, exact=40)
            src = os.path.join(d, "tmp", *PK.bfco_pack.ANIMS.split("/"), *folders[0].split("/"))
            os.makedirs(src)
            open(os.path.join(src, "MeleeAttack_A.af"), "w").close()
            self.assertEqual(PK._move_into_stance(os.path.join(d, "tmp"), folders[0], os.path.join(d, "out"), "Neutral",
                                                  "Greatsword"), 1)
            self.assertTrue(os.path.isfile(os.path.join(d, "out", "meshes", *SP.type_folder("Greatsword").split("\\"),
                                                        "MeleeAttack_A.af")))


if __name__ == "__main__":
    unittest.main()
