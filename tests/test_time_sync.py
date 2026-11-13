"""time_sync: the quest that keeps Nirn's local time on the game hour (2026-11-13)."""
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

import time_sync as T  # noqa: E402
from fo4sf import sfplugin  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                 # noqa: E731


def vmad(scripts, tail=b""):
    """VMAD: version 6, object format 2, scripts [(name, flags, [property bytes])], then tail."""
    out = struct.pack("<hhH", 6, 2, len(scripts))
    for name, flags, props in scripts:
        out += T.wstr(name) + bytes([flags]) + struct.pack("<H", len(props)) + b"".join(props)
    return out + tail


def rec(typ, fid, subs):
    data = b"".join(sfplugin.subrecord_bytes(s, d) for s, d in subs)
    return struct.pack("<4sIIIIHH", typ, len(data), 0, fid, 0, 131, 0) + data


class TimeSyncTests(unittest.TestCase):
    def test_vmad_template_and_ours(self):
        short = (b"QUST", b"", [(b"EDID", Z("A")), (b"VMAD", vmad([("ScriptA", 1, [])], b"\x03\x00\x00\x00\x00"))], 1)
        longer = (b"QUST", b"", [(b"EDID", Z("B")), (b"VMAD", vmad([("ScriptB", 1, [])], b"\x03\x01\x00" + b"x" * 9))], 2)
        props = (b"QUST", b"", [(b"EDID", Z("C")), (b"VMAD", vmad([("ScriptC", 1, [b"pp"])]))], 3)
        two = (b"QUST", b"", [(b"EDID", Z("D")), (b"VMAD", vmad([("S1", 1, []), ("S2", 1, [])]))], 4)
        edid, parts = T.vmad_template([longer, props, two, short])
        self.assertEqual((edid, parts[1]), ("A", "ScriptA"))
        ours = T.our_vmad(parts)
        self.assertEqual(ours, vmad([(T.SCRIPT, 1, [])], b"\x03\x00\x00\x00\x00"))
        self.assertEqual(T.one_script_vmad(ours)[1], T.SCRIPT)
        self.assertIsNone(T.one_script_vmad(b"\x06\x00"))

    def test_quest_and_plugin(self):
        tmpl_subs = [(b"EDID", Z("DialogueGeneric")), (b"VMAD", b"old"), (b"FULL", struct.pack("<I", 5)),
                     (b"DNAM", struct.pack("<HBB", 0x0100, 50, 0) + bytes(8)), (b"CTDA", b"c" * 32), (b"NEXT", b"")]
        sv = [(b"EDID", Z("SomeQuest")), (b"VMAD", vmad([("SQ_Script", 1, [])], b"\x03\x00\x00\x00\x00")),
              (b"DNAM", bytes(12))]
        with tempfile.TemporaryDirectory() as d:
            sf = os.path.join(d, "SF")
            os.makedirs(os.path.join(sf, "Data"))
            tes4_data = sfplugin.subrecord_bytes(b"HEDR", struct.pack("<fII", 0.96, 2, 0x800))
            tes4 = struct.pack("<4sIIIIHH", b"TES4", len(tes4_data), 1, 0, 0, 131, 0) + tes4_data
            body = rec(b"QUST", 0x100, tmpl_subs) + rec(b"QUST", 0x200, sv)
            with open(os.path.join(sf, "Data", "Starfield.esm"), "wb") as fh:
                fh.write(tes4 + struct.pack("<4sI4si", b"GRUP", 24 + len(body), b"QUST", 0) + bytes(8) + body)
            out = os.path.join(d, "mod")
            self.assertEqual(T.main(["--starfield", sf, "--out", out]), 0)
            (q,) = sfplugin.records(os.path.join(out, T.PLUGIN), [b"QUST"])
            subs = dict(q[2])
            self.assertEqual(sfplugin.edid(q[2]), "S2S_LocalTimeSync")
            self.assertEqual(T.one_script_vmad(subs[b"VMAD"])[1], T.SCRIPT)
            self.assertEqual(struct.unpack_from("<H", subs[b"DNAM"], 0)[0], 0x0101)        # start game enabled
            self.assertNotIn(b"CTDA", subs)
            self.assertEqual(q[3], 0x01000800)
            with open(os.path.join(out, "time_sync.json")) as fh:
                self.assertEqual(json.load(fh)["vmad_from"], "SomeQuest")

    def test_script_source(self):
        with open(os.path.join(ROOT, "scripts", "terrain", "papyrus", T.SCRIPT + ".psc")) as fh:
            src = fh.read()
        self.assertTrue(src.startswith(f"ScriptName {T.SCRIPT} extends Quest"))
        for call in ("Game.SetLocalTime(", "Game.GetLocalTime()", "Utility.GetCurrentGameTime()",
                     "StartTimer(", "GetCurrentPlanet()", '"SkyrimTerrainTamriel_Mars.esm"'):
            self.assertIn(call, src)


if __name__ == "__main__":
    unittest.main()
