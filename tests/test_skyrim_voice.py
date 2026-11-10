"""src/fo4sf/skyrimdialog.py and scripts/npc/skyrim_voice.py on synthetic Skyrim files."""
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

from fo4sf import bsa, sfplugin, skyrimdialog as SD  # noqa: E402
import skyrim_voice as SV  # noqa: E402


def sub(sig, data):
    return sig + struct.pack("<H", len(data)) + data


def rec(typ, fid, subs):
    data = b"".join(sub(s, d) for s, d in subs)
    return struct.pack("<4sIII", typ, len(data), 0, fid) + bytes(8) + data


def grup(label, gtype, body):
    return struct.pack("<4sI4si", b"GRUP", 24 + len(body), label, gtype) + bytes(8) + body


def ctda(func, p1, value=1.0, run_on=0):
    return bytes([0, 0, 0, 0]) + struct.pack("<fHHIIII", value, func, 0, p1, 0, run_on, 0) + struct.pack("<i", 0)


def trdt(n):
    return struct.pack("<II", 0, 50) + bytes(4) + bytes([n]) + bytes(3) + struct.pack("<I", 0) + bytes(4)


RALOF, VOICE, OTHER = 0x2BF9F, 0x13AD3, 0x1234


def skyrim_esm(path):
    hello = rec(b"DIAL", 0x500, [(b"EDID", b"HelloTopic\0"), (b"QNAM", struct.pack("<I", 0x600)),
                                  (b"DATA", struct.pack("<BBH", 0, 0, 1)), (b"SNAM", b"HELO")])
    infos = (rec(b"INFO", 0xA01, [(b"TRDT", trdt(1)), (b"NAM1", struct.pack("<I", 0x900)),
                                   (b"CTDA", ctda(SD.GET_IS_ID, RALOF))])
             + rec(b"INFO", 0xA02, [(b"TRDT", trdt(1)), (b"NAM1", struct.pack("<I", 0x901)),
                                     (b"CTDA", ctda(SD.GET_IS_VOICE_TYPE, VOICE))])
             + rec(b"INFO", 0xA03, [(b"TRDT", trdt(1)), (b"NAM1", struct.pack("<I", 0x902)),
                                     (b"CTDA", ctda(SD.GET_IS_ID, OTHER))])
             + rec(b"INFO", 0xA05, [(b"TRDT", trdt(1)), (b"NAM1", struct.pack("<I", 0x903)),
                                     (b"CTDA", ctda(SD.GET_IS_VOICE_TYPE, VOICE)),
                                     (b"CTDA", ctda(SD.GET_IS_RACE, 0x13749, run_on=1))]))
    quest = rec(b"DIAL", 0x501, [(b"EDID", b"MQ101Talk\0"), (b"DATA", struct.pack("<BBH", 0, 0, 0)),
                                  (b"SNAM", b"CUST")])
    qinfo = rec(b"INFO", 0xA04, [(b"TRDT", trdt(1)), (b"NAM1", b"Hey, you. You're finally awake.\0"),
                                  (b"CTDA", ctda(SD.GET_IS_ID, RALOF))])
    dial = grup(b"DIAL", 0, hello + grup(struct.pack("<I", 0x500), 7, infos)
                + quest + grup(struct.pack("<I", 0x501), 7, qinfo))
    npc = rec(b"NPC_", RALOF, [(b"EDID", b"Ralof\0"), (b"ACBS", struct.pack("<I", 0) + bytes(20)),
                               (b"VTCK", struct.pack("<I", VOICE))])
    vt = rec(b"VTYP", VOICE, [(b"EDID", b"MaleNord\0")])
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 5, 0x800))])
    qust = rec(b"QUST", 0x600, [(b"EDID", b"DialogueRiverwood\0"), (b"DNAM", struct.pack("<HBB", 1, 50, 0) + bytes(8))])
    with open(path, "wb") as fh:
        fh.write(tes4 + grup(b"NPC_", 0, npc) + grup(b"VTYP", 0, vt) + grup(b"QUST", 0, qust) + dial)


def dlstrings(entries):
    data, idx = b"", b""
    for sid, text in entries.items():
        idx += struct.pack("<II", sid, len(data))
        b = text.encode() + b"\0"
        data += struct.pack("<I", len(b)) + b
    return struct.pack("<II", len(entries), len(data)) + idx + data


def fuz(lip, xwm):
    return b"FUZE" + struct.pack("<II", 1, len(lip)) + lip + xwm


class DialogTests(unittest.TestCase):
    def test_topics_infos_and_speakers(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Skyrim.esm")
            skyrim_esm(p)
            tops = SD.topics(p)
            self.assertEqual([t["edid"] for t in tops], ["HelloTopic", "MQ101Talk"])
            self.assertEqual(tops[0]["subtype_code"], "HELO")
            self.assertEqual([i["form_id"] for i in tops[0]["infos"]], [0xA01, 0xA02, 0xA03, 0xA05])
            hows = [SD.speaks(i, RALOF, VOICE) for i in tops[0]["infos"]]
            self.assertEqual(hows, ["own", "voice", None, "voice"])
            self.assertTrue(SD.about_player(tops[0]["infos"][3]["conditions"][1]))     # 'little elf'
            self.assertFalse(SD.about_player(tops[0]["infos"][1]["conditions"][0]))
            self.assertTrue(SD.about_player({"run_on": 0, "param1": 0x14}))         # relationship with PlayerRef
            self.assertTrue(SD.about_player({"function": SD.GET_PC_IS_RACE, "run_on": 0, "param1": 0x13749}))
            self.assertEqual(tops[1]["infos"][0]["responses"][0]["text"], "Hey, you. You're finally awake.")

    def test_strings_fuz_and_voice_index(self):
        st = SD.read_lstrings(dlstrings({0x900: "Hello there.", 0x901: "What?"}), True)
        self.assertEqual(st, {0x900: "Hello there.", 0x901: "What?"})
        self.assertEqual(SD.unpack_fuz(fuz(b"LIP", b"XWMDATA")), (b"LIP", b"XWMDATA"))
        with self.assertRaises(ValueError):
            SD.unpack_fuz(b"RIFF....")
        idx = SD.voice_index(["sound\\voice\\skyrim.esm\\malenord\\hellotopic__00000a01_1.fuz",
                              "sound\\voice\\skyrim.esm\\malenord\\hellotopic__00000a02_1.xwm",
                              "sound\\voice\\dawnguard.esm\\malenord\\x_00000a03_1.fuz"])
        self.assertEqual(set(idx), {("malenord", 0xA01, 1), ("malenord", 0xA02, 1)})


def cond(name, p1=0, value=1.0, op=0, run_on=0, or_=False, use_global=False):
    return {"function": SD.F[name], "param1": p1, "value": value, "op": op, "run_on": run_on, "or": or_,
            "use_global": use_global, "reference": 0}


class StartStateTests(unittest.TestCase):
    """2026-11-10 (owner: Delphine spoke of the dragon mounds before the main quest, Embry as if romanced): a line
    plays only if it would at the start of a new Skyrim game."""

    def setUp(self):
        self.world = SD.World(quests={0x600: 1, 0x601: 0}, globals_={0x700: 1.0, 0x701: 0.0},
                              npcs={0x7: {"form_id": 0x7, "factions": [(0xDB1, 0)]}},
                              lists={0x800: [0x2BF9F]}, quest_conditions={0x602: [cond("GetGlobalValue", 0x701)]})
        self.ralof = {"form_id": 0x2BF9F, "factions": [(0x1111, 2)], "race": 0x13746, "female": False, "voice": 5}
        self.v = lambda conds, quest=0x600: SD.verdict({"conditions": conds}, self.ralof, self.world, quest)[0]

    def test_story_lines_dropped(self):
        self.assertEqual(self.v([cond("GetIsID", 0x2BF9F)]), "keep")
        self.assertEqual(self.v([cond("GetIsID", 0x2BF9F)], quest=0x601), "drop")       # its quest not started
        self.assertEqual(self.v([cond("GetStage", 0x601, 10.0, op=3)]), "drop")          # GetStage MQ >= 10
        self.assertEqual(self.v([cond("GetStage", 0x601, 10.0, op=4)]), "keep")          # < 10: before it
        self.assertEqual(self.v([cond("GetRelationshipRank", 0x14, 4.0, op=3)]), "drop")  # lover of the player
        self.assertEqual(self.v([cond("GetInFaction", 0x2222)]), "drop")                  # e.g. married to the player
        self.assertEqual(self.v([cond("GetFactionRank", 0x1111, 2.0, op=3)]), "keep")
        self.assertEqual(self.v([cond("GetGlobalValue", 0x700)]), "keep")
        self.assertEqual(self.v([cond("GetIsID", 0x2BF9F)], quest=0x602), "drop")       # quest dialogue conditions
        self.assertEqual(self.v([cond("GetDead", 0x9999, 0.0)]), "keep")
        self.assertEqual(self.v([cond("IsInList", 0x800)]), "keep")
        self.assertEqual(self.v([cond("GetGlobalValue", 0x700, 0x701, use_global=True)]), "drop")   # 1 == 0?

    def test_or_groups_and_ambient(self):
        # (GetStage MQ >= 10 OR GetIsID Ralof) AND GetCurrentTime < 12
        conds = [cond("GetStage", 0x601, 10.0, op=3, or_=True), cond("GetIsID", 0x2BF9F),
                 cond("GetCurrentTime", 0, 12.0, op=4)]
        self.assertEqual(self.v(conds), "ambient")
        self.assertEqual(self.v([cond("GetPCIsRace", 0x13749)]), "drop")
        self.assertEqual(SD.verdict({"conditions": [cond("GetPCIsRace", 0x13749)]}, self.ralof, self.world, 0x600,
                                    {"ambient", "player"})[0], "ambient")
        self.assertEqual(self.v([cond("GetPCInFaction", 0xDB1)]), "keep")
        self.assertEqual(self.v([cond("GetIsAliasRef", 3)]), "drop")


class VoiceScriptTests(unittest.TestCase):
    def test_wsources_ffxcproj_and_wav(self):
        with tempfile.TemporaryDirectory() as d:
            p = SV.make_wsources("C:\\w", "00000A01_1", os.path.join(d, "x.wsources"))
            txt = open(p).read()
            self.assertIn('Path="00000A01_1.wav" Conversion="Vorbis Quality High" Destination="00000A01_1"', txt)
        self.assertEqual(SV.ffxcproj_text("A.facefx", "B.animset"),
                         "version: 10300\nitems:\n - facefx_file: A.facefx\n   mount_files:\n    - B.animset\n")
        body = b"\1\0" * 50
        bad = (b"RIFF" + struct.pack("<I", 0) + b"WAVE" + b"fmt " + struct.pack("<I", 16)
               + struct.pack("<HHIIHH", 1, 1, 22050, 999, 2, 16) + b"data" + struct.pack("<I", 0xFFFFFFFF) + body)
        good = SV.clean_wav(bad)
        self.assertEqual(len(good), 44 + len(body))
        self.assertEqual(struct.unpack_from("<I", good, 28)[0], 44100)            # byte rate recomputed
        self.assertIsNone(SV.clean_wav(b"nope"))

    def test_main_extracts_ralofs_greetings(self):
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "Data")
            os.makedirs(data)
            skyrim_esm(os.path.join(data, "Skyrim.esm"))
            files = {"sound\\voice\\skyrim.esm\\malenord\\hellotopic__00000a01_1.fuz": fuz(b"L", b"XWM-A01"),
                     "sound\\voice\\skyrim.esm\\malenord\\hellotopic__00000a02_1.fuz": fuz(b"L", b"XWM-A02"),
                     "strings\\skyrim_english.ilstrings": dlstrings({0x900: "Hello.", 0x901: "Hm?"})}
            with open(os.path.join(data, "Skyrim - Voices_en0.bsa"), "wb") as fh:
                fh.write(bsa.build(files))
            out = os.path.join(d, "out")
            SV.main(["--skyrim-data", data, "--npc", "Ralof", "--out", out])
            rep = json.load(open(os.path.join(out, "lines.json")))
            lines = rep["npcs"][0]["lines"]
            self.assertEqual(rep["npcs"][0]["voice_type"], "MaleNord")
            sk = rep["npcs"][0]["skipped"]
            self.assertEqual(sk["not_at_game_start"], 1)                    # 'little elf': the player's race
            self.assertEqual(sk["examples"][0]["why"], ["GetIsRace player"])
            self.assertEqual([(l["info"], l["how"], l["text"], l["result"]) for l in lines],
                             [("00000A01", "own", "Hello.", "xwm"), ("00000A02", "voice", "Hm?", "xwm")])
            self.assertEqual(open(os.path.join(out, "lines", "MaleNord", "00000A01_1.xwm"), "rb").read(), b"XWM-A01")
            # a line converted before (its .wem there) is reused, not converted again (2026-11-10)
            with open(os.path.join(out, "lines", "MaleNord", "00000A01_1.wem"), "wb") as fh:
                fh.write(b"WEM")
            SV.main(["--skyrim-data", data, "--npc", "Ralof", "--out", out])
            lines = json.load(open(os.path.join(out, "lines.json")))["npcs"][0]["lines"]
            self.assertEqual([l["result"] for l in lines], ["wem", "xwm"])
            # own scope: his quest line too (no voice file here)
            SV.main(["--skyrim-data", data, "--npc", "Ralof", "--out", out, "--scope", "own"])
            lines = json.load(open(os.path.join(out, "lines.json")))["npcs"][0]["lines"]
            self.assertEqual([l["info"] for l in lines], ["00000A01", "00000A04"])
            self.assertEqual(lines[1]["result"], "no voice file")

    def test_pc_tools_are_called_as_unity_did(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []

            def fake_run(cmd, timeout=120):
                calls.append(cmd)
                if "convert-external-source" in cmd:
                    os.makedirs(os.path.join(d, "scratch", "Windows"), exist_ok=True)
                    open(os.path.join(d, "scratch", "Windows", "S.wem"), "wb").write(b"wem")
                if cmd[0].endswith("LipGenerator.exe"):
                    open(cmd[5].split(":", 1)[1], "wb").write(b"animset")
                if cmd[0].endswith("ffxc.exe"):
                    reg = cmd[1][3:-1]
                    sub = os.path.join(reg, "StarfieldHumanMale", "x86", "NPCMBarrett_S")
                    os.makedirs(sub, exist_ok=True)
                    open(os.path.join(sub, "S.ffxanim"), "wb").write(b"anim")
                return mock.Mock(returncode=0)
            os.makedirs(os.path.join(d, "scratch"))
            with mock.patch.object(SV, "run", fake_run):
                wem = SV.to_wem(os.path.join(d, "S.wav"), "S", "WwiseConsole.exe", "Starfield.wproj",
                                os.path.join(d, "scratch"))
                anim = SV.to_lips(os.path.join(d, "S.wav"), "S", "Hello.", True, os.path.join(d, "SF"))
            self.assertTrue(wem.endswith("S.wem"))
            self.assertTrue(anim.endswith(os.path.join("NPCMBarrett_S", "S.ffxanim")))
            self.assertEqual(calls[0][1:3], ["convert-external-source", "Starfield.wproj"])
            self.assertIn("--platform", calls[0])
            lip = calls[1]
            self.assertEqual(lip[2], "Hello.")                                   # the text as a plain string
            self.assertTrue(lip[3].endswith("StarfieldHumanMale.facefx"))       # the male actor for a man
            self.assertIn("Slice_00", lip[5])
            self.assertEqual(calls[2][2:4], ["-p=x86", "--rebuild"])


if __name__ == "__main__":
    unittest.main()


class DialogueProbeTests(unittest.TestCase):
    def test_probe_dumps_greetings(self):
        import dialogue_probe as DP
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Starfield.esm")
            skyrim_esm(p)                                        # same record layout: DIAL + child INFO groups
            rep = DP.probe(p)
            self.assertEqual([t["edid"] for t in rep["greeting_topics"]], ["HelloTopic"])
            t = rep["greeting_topics"][0]
            self.assertEqual(t["info_count"], 4)
            self.assertEqual(len(t["infos"]), 4)
            self.assertEqual(rep["info_group_path"], ["type 0", "type 7"])
            self.assertIn({"sig": "SNAM", "size": 4, "hex": b"HELO".hex(), "u32": "4F4C4548"}, t["subs"])
            self.assertEqual(rep["infos_total"], 5)
            self.assertEqual(rep["infos_with_voice_type_condition"], 2)

    def test_probe_finds_topics_inside_quest_groups(self):
        import dialogue_probe as DP
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Starfield.esm")
            hello = rec(b"DIAL", 0x500, [(b"EDID", b"GenericHello\0"), (b"SNAM", b"HELO")])
            info = rec(b"INFO", 0xA01, [(b"TRDT", trdt(1))])
            quest = rec(b"QUST", 0x600, [(b"EDID", b"DialogueGeneric\0")])
            inner = grup(struct.pack("<I", 0x600), 10, hello + grup(struct.pack("<I", 0x500), 7, info))
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 0.96, 3, 0x800))])
            with open(p, "wb") as fh:
                fh.write(tes4 + grup(b"QUST", 0, quest + inner))
            rep = DP.probe(p)
            self.assertEqual(rep["topics_total"], 1)
            self.assertEqual(rep["greeting_topics"][0]["info_count"], 1)
            self.assertEqual(rep["greeting_topics"][0]["groups"], ["type 0: QUST", "type 10: 00000600"])
            self.assertEqual(rep["info_group_path"], ["type 0", "type 10", "type 7"])
