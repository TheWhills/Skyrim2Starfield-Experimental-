"""scripts/npc/make_schedule.py on synthetic Skyrim / Starfield plugins: a SandboxWorking package -> Starfield Sandbox,
inputs matched by name, the near-reference location kept with its spot, the NPC's spot in the batch's cell."""
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
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_fo4land import grup, rec  # noqa: E402
import make_schedule as M  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731


def pack(fid, edid, kind, template, schedule, values, value_idx, names=(), tree=()):
    f = [(b"EDID", Z(edid)), (b"PKDT", struct.pack("<IBBBBHH", 0, kind, 0, 1, 0, 0, 0))]
    if schedule:
        f.append((b"PSDT", struct.pack("<5b3xI", -1, -1, 0, *schedule)))
    f.append((b"PKCU", struct.pack("<III", len(values), template, 0)))
    for typ, sig, val in values:
        f += [(b"ANAM", Z(typ)), (sig, val)]
    f += [(b"UNAM", struct.pack("<b", i)) for i in value_idx]
    f.append((b"XNAM", b"\x20"))
    for branch, proc in tree:
        f += [(b"ANAM", Z(branch)), (b"PNAM", Z(proc))]
    for i, n in names:
        f += [(b"UNAM", struct.pack("<b", i)), (b"BNAM", Z(n))]
    return rec(b"PACK", fid, f)


B = lambda v: (b"CNAM", bytes([v]))                                   # noqa: E731


class ScheduleTests(unittest.TestCase):
    def test_orgnar(self):
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            npc = rec(b"NPC_", 0x100, [(b"EDID", Z("Orgnar")), (b"FULL", Z("Orgnar")), (b"ACBS", bytes(24)),
                                       (b"PKID", struct.pack("<I", 0x200))])
            tpl = pack(0x201, "SandboxWorking", 19, 0, None,
                       [("Location", b"PLDT", struct.pack("<iIi", 3, 0, 0)), ("Bool", *B(0)), ("Bool", *B(0))],
                       [0, 14, 1], [(0, "Location"), (1, "Allow Eating"), (14, "Unlock On Arrival?"), (25, "Prefered Path Only?")],
                       [("Procedure", "Sandbox")])
            pk = pack(0x200, "OrgnarWorkInn0x24", 18, 0x201, (-1, -1, 0),
                      [("Location", b"PLDT", struct.pack("<iIi", 0, 0x601, 256)), ("Bool", *B(0)), ("Bool", *B(1))],
                      [0, 14, 1])
            cell = rec(b"CELL", 0x500, [(b"EDID", Z("RiverwoodSleepingGiantInn"))])
            achr = rec(b"ACHR", 0x600, [(b"NAME", struct.pack("<I", 0x100)), (b"DATA", struct.pack("<6f", -1312.8, 18.3, 0, 0, 0, 1.5))])
            marker = rec(b"REFR", 0x601, [(b"NAME", struct.pack("<I", 0x3B)), (b"DATA", struct.pack("<6f", -1250, 40, 0, 0, 0, 0))])
            xm = rec(b"STAT", 0x3B, [(b"EDID", Z("XMarker"))])
            body = (grup(b"STAT", 0, [xm]) + grup(b"NPC_", 0, [npc]) + grup(b"PACK", 0, [pk, tpl])
                    + grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [cell, grup(0x500, 6, [grup(0x500, 8, [achr, marker])])])])]))
            sky = os.path.join(d, "Skyrim.esm")
            with open(sky, "wb") as fh:
                fh.write(tes4 + body)
            sf = os.path.join(d, "Starfield.esm")
            with open(sf, "wb") as fh:
                fh.write(tes4 + grup(b"PACK", 0, [pack(
                    0x2CB1, "Sandbox", 19, 0, None,
                    [("Location", b"PLDT", struct.pack("<iIfI", 3, 0, 0, 0)), ("Bool", *B(0)), ("Bool", *B(0))],
                    [2, 12, 5], [(0, "Location"), (2, "Location"), (5, "Allow Eating"), (12, "Unlock on Arrival?")],
                    [("Procedure", "Sandbox")])]))
            work = os.path.join(d, "work")
            os.makedirs(work)
            cj = os.path.join(work, "cell.json")
            with open(cj, "w") as fh:
                json.dump({"cell": "RiverwoodSleepingGiantInn"}, fh)
            with open(os.path.join(work, "cells.txt"), "w") as fh:
                fh.write(cj + "\n")
            faces = os.path.join(d, "faces.json")
            with open(faces, "w") as fh:
                json.dump({"npcs": [{"edid": "Ralof", "female": False, "test_npc": {"template_form_id": "0001ABCD"}}]}, fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(M.main(["--skyrim", sky, "--starfield", sf, "--npc", "Orgnar", "--work", work,
                                         "--faces", faces]), 0)
            with open(os.path.join(work, "actors.json")) as fh:
                r = json.load(fh)
            ac = r["actors"][0]
            self.assertEqual((ac["cell"], ac["template_npc"], ac["pos"][0]), ("RiverwoodSleepingGiantInn", "0001ABCD", -1312.8))
            p = ac["packages"][0]
            self.assertEqual((p["sf_template"], p["sf_template_form"], p["edid"]), ("Sandbox", "00002CB1", "S2S_OrgnarWorkInn0x24"))
            self.assertEqual(p["schedule"]["hour"], -1)
            ins = p["inputs"]
            self.assertEqual(ins["2"]["type"], "near_reference")
            self.assertEqual(ins["2"]["source"], "000601:Skyrim.esm")
            self.assertAlmostEqual(ins["2"]["radius_m"], 256 / 70, places=3)
            self.assertEqual(ins["2"]["pos"], [-1250.0, 40.0, 0.0])
            self.assertEqual((ins["12"]["value"], ins["5"]["value"]), (False, True))
            self.assertIn("Orgnar in RiverwoodSleepingGiantInn", out.getvalue())


if __name__ == "__main__":
    unittest.main()
