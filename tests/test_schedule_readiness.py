"""scripts/npc/schedule_readiness.py on synthetic plugins: per NPC placed in the batch, each package converted or left
out with the reason (quest / conditions, a location outside the batch), the furniture the packages point at, the
face-test flag, the status (ready / partial / blocked) and the -Actors list."""
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
from test_make_schedule import B, Z, pack  # noqa: E402
import schedule_readiness as R  # noqa: E402

P = lambda v: struct.pack("<I", v)                                    # noqa: E731


class ReadinessTests(unittest.TestCase):
    def test_report(self):
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            tpl = pack(0x201, "SandboxWorking", 19, 0, None,
                       [("Location", b"PLDT", struct.pack("<iIi", 3, 0, 0)), ("Bool", *B(0))],
                       [0, 1], [(0, "Location"), (1, "Allow Eating")], [("Procedure", "Sandbox")])
            work_bar = pack(0x200, "OrgnarWork", 18, 0x201, (-1, -1, 0),
                            [("Location", b"PLDT", struct.pack("<iIi", 0, 0x601, 256)), ("Bool", *B(1))], [0, 1])
            quest = rec(b"PACK", 0x202, [(b"EDID", Z("MQSomething")), (b"PKDT", struct.pack("<IBBBBHH", 0, 18, 0, 0, 0, 0, 0)),
                                         (b"CTDA", struct.pack("<B3xfH2xIIIII", 0, 1.0, 72, 0x101, 0, 0, 0, 0)), (b"PKCU", struct.pack("<III", 0, 0x201, 0))])
            held = rec(b"PACK", 0x204, [(b"EDID", Z("SvenOwnSandbox")),
                                        (b"PKDT", struct.pack("<IBBBBHH", 0, 18, 0, 0, 0, 0, 0)),
                                        (b"CTDA", struct.pack("<B3xfH2xIIIII", 0, 1.0, 72, 0x102, 0, 0, 0, 0)),
                                        (b"PKCU", struct.pack("<III", 0, 0x201, 0))])
            # 2026-11-17: Hod's sawmill: GetVMScriptVariable's variable name is the CIS2 string after the CTDA
            saw = rec(b"PACK", 0x205, [(b"EDID", Z("HodSawLog")), (b"PKDT", struct.pack("<IBBBBHH", 0, 18, 0, 0, 0, 0, 0)),
                                       (b"CTDA", struct.pack("<B3xfH2xIIIII", 0, 2.0, 630, 0x601, 479521864, 0, 0, 0)),
                                       (b"CIS2", Z("::state_var")), (b"PKCU", struct.pack("<III", 0, 0x201, 0))])
            outside = pack(0x203, "HodMill", 18, 0x201, (8, 0, 600),
                           [("Location", b"PLDT", struct.pack("<iIi", 0, 0x701, 256)), ("Bool", *B(0))], [0, 1])
            npcs = [rec(b"NPC_", 0x100, [(b"EDID", Z("Orgnar")), (b"FULL", Z("Orgnar")), (b"ACBS", bytes(24)),
                                         (b"PKID", P(0x200)), (b"PKID", P(0x202))]),
                    rec(b"NPC_", 0x101, [(b"EDID", Z("Hod")), (b"FULL", Z("Hod")), (b"ACBS", bytes(24)),
                                         (b"PKID", P(0x203)), (b"PKID", P(0x205))]),
                    rec(b"NPC_", 0x102, [(b"EDID", Z("Sven")), (b"FULL", Z("Sven")), (b"ACBS", bytes(24)),
                                         (b"PKID", P(0x200)), (b"PKID", P(0x204))]),
                    rec(b"NPC_", 0x103, [(b"EDID", Z("Elsewhere")), (b"ACBS", bytes(24)), (b"PKID", P(0x200))])]
            bar = rec(b"FURN", 0x400, [(b"EDID", Z("CounterBarLeanMarker")), (b"KSIZ", P(1)), (b"KWDA", P(0x401))])
            kw = rec(b"KYWD", 0x401, [(b"EDID", Z("isBarCounter"))])
            inn = rec(b"CELL", 0x500, [(b"EDID", Z("RiverwoodSleepingGiantInn"))])
            mill = rec(b"CELL", 0x510, [(b"EDID", Z("RiverwoodMill"))])
            spot = lambda f, base: rec(b"ACHR", f, [(b"NAME", P(base)), (b"DATA", struct.pack("<6f", 1, 2, 0, 0, 0, 0))])  # noqa: E731
            in_inn = [spot(0x600, 0x100), spot(0x602, 0x101), spot(0x603, 0x102),
                      rec(b"REFR", 0x601, [(b"NAME", P(0x400)), (b"DATA", struct.pack("<6f", 3, 4, 0, 0, 0, 0))])]
            in_mill = [spot(0x700, 0x103), rec(b"REFR", 0x701, [(b"NAME", P(0x400)),
                                                                 (b"DATA", struct.pack("<6f", 0, 0, 0, 0, 0, 0))])]
            cells = grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [inn, grup(0x500, 6, [grup(0x500, 8, in_inn)]),
                                                              mill, grup(0x510, 6, [grup(0x510, 8, in_mill)])])])])
            body = (grup(b"KYWD", 0, [kw]) + grup(b"FURN", 0, [bar]) + grup(b"NPC_", 0, npcs)
                    + grup(b"PACK", 0, [work_bar, tpl, quest, outside, held, saw]) + cells)
            sky = os.path.join(d, "Skyrim.esm")
            with open(sky, "wb") as fh:
                fh.write(tes4 + body)
            sf = os.path.join(d, "Starfield.esm")
            with open(sf, "wb") as fh:
                fh.write(tes4 + grup(b"PACK", 0, [pack(0x2CB1, "Sandbox", 19, 0, None,
                                                       [("Location", b"PLDT", struct.pack("<iIfI", 3, 0, 0, 0)),
                                                        ("Bool", *B(0))], [2, 5],
                                                       [(2, "Location"), (5, "Allow Eating")],
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
                json.dump({"npcs": [{"edid": "Orgnar", "test_npc": {"form_id": "03000800"}},
                                    {"edid": "Sven", "test_npc": "no vanilla template NPC of this sex"}]}, fh)
            out = os.path.join(d, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(R.main(["--skyrim", sky, "--starfield", sf, "--work", work, "--faces", faces,
                                         "--out", out]), 0)
            with open(os.path.join(out, "readiness.json")) as fh:
                r = json.load(fh)
            by = {x["edid"]: x for x in r["npcs"]}
            self.assertEqual(sorted(by), ["Hod", "Orgnar", "Sven"])              # Elsewhere is not in the batch
            self.assertEqual((by["Orgnar"]["status"], by["Hod"]["status"], by["Sven"]["status"]),
                             ("partial", "blocked", "ready"))
            self.assertEqual(by["Orgnar"]["furniture"], {"bartender": 1})
            self.assertEqual([p["reasons"] for p in by["Orgnar"]["packages"] if not p["converted"]],
                             [["not in settled Riverwood (quest-only or intro)"]])
            # 2026-11-17: conditions decoded and read in settled Riverwood: Orgnar's (GetIsID Hod) fails and is left
            # out; Sven's own (GetIsID Sven) holds, so the package converts
            q, = [p for p in by["Orgnar"]["packages"] if not p["converted"]]
            self.assertEqual(q["conditions"], [{"text": "GetIsID(Hod) == 1", "at_start": False, "kind": "start"}])
            kept, = [p for p in by["Sven"]["packages"] if p.get("kept_conditions")]
            self.assertEqual((kept["edid"], kept["converted"]), ("SvenOwnSandbox", True))
            self.assertEqual(by["Hod"]["packages"][0]["reasons"], ["location outside the converted cells"])
            self.assertEqual((by["Orgnar"]["face_test_npc"], by["Sven"]["face_test_npc"]), (True, False))
            self.assertEqual(r["actors_ready_or_partial"], ["Sven", "Orgnar"])
            self.assertEqual(r["left_out_by_reason"], {"not in settled Riverwood (quest-only or intro)": 1,
                                                       "location outside the converted cells": 1,
                                                       "a script's state (needs the script)": 1})
            with open(os.path.join(out, "readiness.md")) as fh:
                md = fh.read()
            self.assertIn("-Actors Sven,Orgnar", md)
            self.assertIn("| Hod (Hod) | blocked | 0/2 |", md)
            self.assertIn("    - `GetVMScriptVariable(000601, '::state_var') == 2`: script", md)
            self.assertIn("  - HodMill: left out (location outside the converted cells)", md)
            self.assertIn("    - `GetIsID(Hod) == 1`: start, in settled Riverwood false", md)
            self.assertIn("SvenOwnSandbox: SandboxWorking -> Sandbox", md)
            self.assertIn("(its conditions hold in settled Riverwood)", md)
            # 2026-11-17: --exterior as the build passes it keeps the outdoor location (Hod at the mill)
            ext = os.path.join(d, "ext")
            os.makedirs(ext)
            with open(os.path.join(ext, "formids.json"), "w") as fh:
                json.dump({"refs": {"000701:Skyrim.esm": "01000800"}}, fh)
            out2 = os.path.join(d, "out2")
            with contextlib.redirect_stdout(io.StringIO()):
                R.main(["--skyrim", sky, "--starfield", sf, "--work", work, "--out", out2, "--exterior", ext])
            with open(os.path.join(out2, "readiness.json")) as fh:
                hod = {x["edid"]: x for x in json.load(fh)["npcs"]}["Hod"]
            self.assertEqual((hod["status"], hod["furniture"]), ("partial", {"bartender": 1}))   # the sawmill one stays out
            self.assertEqual(hod["packages"][0]["near"], "CounterBarLeanMarker")
            with open(os.path.join(out2, "readiness.md")) as fh:
                self.assertIn("near CounterBarLeanMarker (bartender)", fh.read())


if __name__ == "__main__":
    unittest.main()
