"""scripts/npc/npc_voice.py: the NPCs' Skyrim greetings as Starfield records and voice files."""
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

from fo4sf import sfplugin  # noqa: E402
import npc_voice as NV  # noqa: E402
import dialogue_probe as DP  # noqa: E402

HDR = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(8)


class VoiceRecordTests(unittest.TestCase):
    def test_greetings_built_and_files_placed(self):
        with tempfile.TemporaryDirectory() as d:
            vdir = os.path.join(d, "voice")
            os.makedirs(os.path.join(vdir, "lines", "MaleNord"))
            for stem in ("000D2C26_1", "000A9B29_1"):
                open(os.path.join(vdir, "lines", "MaleNord", stem + ".wem"), "wb").write(b"wem" + stem.encode())
            open(os.path.join(vdir, "lines", "MaleNord", "000D2C26_1.ffxanim"), "wb").write(b"lip")
            json.dump({"npcs": [{"npc": "Ralof", "voice_type": "MaleNord", "male": True, "lines": [
                {"info": "000D2C26", "number": 1, "text": "Hmph.", "result": "wem"},
                {"info": "000A9B29", "number": 1, "text": "Aye.", "result": "wem"},
                {"info": "00000001", "number": 1, "text": "No audio.", "result": "no voice file"}]}]},
                open(os.path.join(vdir, "lines.json"), "w"))
            masters = 3
            npc = (b"NPC_", HDR(b"NPC_"), [(b"EDID", sfplugin.zs("S2SFace_Ralof")),
                                           (b"VTCK", struct.pack("<I", 0x13AD2))], sfplugin.new_form_id(0, masters))
            recs = [npc]
            vt = (b"VTYP", HDR(b"VTYP"), [(b"EDID", sfplugin.zs("GenericMaleEvenToned"))], 0x13AD2)
            qt = (b"QUST", HDR(b"QUST"), [(b"EDID", sfplugin.zs("DialogueGeneric")), (b"FULL", b"\1\2\3\4"),
                                          (b"DNAM", bytes.fromhex("110100000500000000000000")),
                                          (b"CTDA", bytes(32)), (b"NEXT", b""), (b"ANAM", bytes(4))], 0x1234)
            rows = [{"edid": "Ralof", "female": False}]
            rep = {}
            out = os.path.join(d, "mod")
            top, children = NV.add_voices(recs, {"Ralof": 0}, rows, vdir, masters, "S2SFaceTest.esm", out, vt, qt,
                                          rep)
            self.assertEqual(rep["voice"]["responses"], 2)
            vtcks = [struct.unpack_from("<I", dd, 0)[0] for s, dd in recs[0][2] if s == b"VTCK"]
            self.assertEqual(vtcks, [rows[0]["voice"] and int(rows[0]["voice"]["form_id"], 16)])
            q = next(r for r in top if r[0] == b"QUST")
            self.assertNotIn(b"CTDA", [s for s, _d in q[2]])
            self.assertIn((b"FULL", sfplugin.zs("S2S Skyrim greetings")), q[2])
            vrec = next(r for r in top if r[0] == b"VTYP")
            self.assertIn((b"DNAM", b"\0"), vrec[2])
            greet = rows[0]["voice"]["greetings"]
            folder = os.path.join(out, "Sound", "Voice", "S2SFaceTest.esm", "S2S_MaleNord_Ralof")
            self.assertEqual(sorted(os.listdir(folder)), sorted([greet[0]["file"] + ".wem", greet[0]["file"] + ".ffxanim",
                                                                 greet[1]["file"] + ".wem"]))
            self.assertEqual(greet[0]["file"], "00" + greet[0]["info"][2:].lower())   # no load-order byte
            plugin = os.path.join(d, "S2SFaceTest.esm")
            open(plugin, "wb").write(sfplugin.build(recs + top, {"hedr_version": 0.96, "form_version": 555},
                                                    masters=("Starfield.esm", "A.esm", "B.esm"), children=children))
            probe = DP.probe(plugin)
            t = probe["greeting_topics"][0]
            self.assertEqual((t["edid"], t["info_count"]), ("S2S_SkyrimGreetings_Hellos", 2))
            self.assertEqual(probe["info_group_path"], ["type 0", "type 10", "type 7"])
            info = t["infos"][0]["subs"]
            ctda = bytes.fromhex(next(x["hex"] for x in info if x["sig"] == "CTDA"))
            self.assertEqual(struct.unpack_from("<fHHI", ctda, 4), (1.0, 72, 0, npc[3]))
            self.assertEqual(next(x["text"] for x in info if x["sig"] == "NAM1"), "Hmph.")
            tifl = next(x for x in t["subs"] if x["sig"] == "TIFL")
            self.assertEqual(tifl["size"], 8)


if __name__ == "__main__":
    unittest.main()
