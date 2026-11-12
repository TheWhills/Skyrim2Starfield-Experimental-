"""preset_probe: where the looks menu's presets come from (2026-11-12, owner: profiles / Body Type 2 show a human
head with our tusks)."""
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
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))

from fo4sf import sfplugin  # noqa: E402
import preset_probe as P  # noqa: E402

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
                (b"RACE", [(b"EDID", Z("HumanRace")), (b"MNAM", b""), (b"RPRM", I(0x500)), (b"FNAM", b""),
                           (b"RPRF", I(0x501))], 0x347D),
                (b"FLST", [(b"EDID", Z("ChargenPresetList")), (b"LNAM", I(0x501)), (b"LNAM", I(0x77))], 0x900),
                (b"FLST", [(b"EDID", Z("Unrelated")), (b"LNAM", I(0x77))], 0x901),
                (b"HDPT", [(b"EDID", Z("HumanFemaleHead")), (b"MODL", Z("FemaleHead.nif")), (b"PNAM", I(1))], 0x12),
                (b"NPC_", [(b"EDID", Z("ChargenPresetMale01")), (b"PNAM", I(0x12))], 0x500),
                (b"NPC_", [(b"EDID", Z("ChargenPresetFemale01")), (b"PNAM", I(0x12)), (b"TNAM", Z("Dermaesthetic")),
                           (b"QNAM", Z("European_Female_md1_Sk3")), (b"STON", b"\x03")], 0x501)])
            plug = os.path.join(d, "Race.esm")
            esm(plug, [(b"RACE", [(b"EDID", Z("S2S_OrcRace")), (b"FNAM", b""), (b"RPRF", I(0x501))], 0x1000),
                       (b"NPC_", [(b"EDID", Z("Player")), (b"RNAM", I(0x1000)), (b"PNAM", I(0x12))], 0x7)])
            out = os.path.join(d, "o")
            with contextlib.redirect_stdout(io.StringIO()) as so:
                P.main(["--starfield", d, "--plugin", plug, "--out", out])
            rep = json.load(open(os.path.join(out, "preset_probe.json")))
        self.assertEqual(rep["humanrace_presets"], {"male": ["00000500"], "female": ["00000501"]})
        refs = {(r[1], r[3]) for r in rep["references"]}
        self.assertIn(("ChargenPresetList", "LNAM"), refs)
        self.assertNotIn(("Unrelated", "LNAM"), refs)
        self.assertEqual(rep["Race.esm"]["Player"]["face"], [["00000012", "HumanFemaleHead", "FemaleHead.nif"]])
        self.assertIn("ChargenPresetList", so.getvalue())
        self.assertEqual(rep["humanrace_preset_faces"]["ChargenPresetFemale01"],
                         [["TNAM", "Dermaesthetic"], ["QNAM", "European_Female_md1_Sk3"], ["STON", "3"]])


if __name__ == "__main__":
    unittest.main()
