"""scripts/interior/make_furniture.py on a synthetic Skyrim batch: a chair (NIF marker -> SNAM offset in metres, z 0,
entry sides minus the record's disabled ones), the bar-lean marker (template markers, made persistent because an NPC
package names it), a sweeping idle marker, a crafting station left out; references outside the batch ignored."""
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
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_fo4land import grup, rec  # noqa: E402
from test_furniture_survey import chair_nif  # noqa: E402
import furniture_survey as S  # noqa: E402
import make_furniture as M  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731


def ref(fid, base, pos, rot=(0, 0, 0), scale=None):
    f = [(b"NAME", struct.pack("<I", base)), (b"DATA", struct.pack("<6f", *pos, *rot))]
    if scale:
        f.append((b"XSCL", struct.pack("<f", scale)))
    return rec(b"REFR", fid, f)


class MakeFurnitureTests(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            kws = [rec(b"KYWD", 0x10 + i, [(b"EDID", Z(n))]) for i, n in
                   enumerate(["FurnitureCounterLeanMarker", "isBarCounter", "WICraftingAlchemy"])]
            chair = rec(b"FURN", 0x20, [(b"EDID", Z("CommonChair01R")), (b"MODL", Z("Furniture\\CommonChair01.nif")),
                                        (b"MNAM", struct.pack("<I", 0x40000001)),
                                        (b"ENAM", struct.pack("<I", 0)), (b"NAM0", struct.pack("<2xH", 0b1000)),
                                        (b"FNMK", struct.pack("<I", 0)), (b"ENAM", struct.pack("<I", 1)),
                                        (b"NAM0", struct.pack("<2xH", 0)), (b"FNMK", struct.pack("<I", 0)),
                                        (b"FNPR", struct.pack("<HH", 1, 0b1001))])
            lean = rec(b"FURN", 0x21, [(b"EDID", Z("CounterBarLeanMarker")), (b"MODL", Z("Furniture\\CounterLeanMarker.nif")),
                                       (b"KWDA", struct.pack("<2I", 0x10, 0x11)), (b"FNPR", struct.pack("<HH", 1, 2))])
            lean_raw = bytearray(lean)
            struct.pack_into("<I", lean_raw, 8, S.IS_MARKER)
            alch = rec(b"FURN", 0x22, [(b"EDID", Z("CraftingAlchemyWorkbench")), (b"KWDA", struct.pack("<I", 0x12)),
                                       (b"FNPR", struct.pack("<HH", 1, 2))])
            idle = rec(b"IDLE", 0x31, [(b"EDID", Z("IdleLooseSweepingStart"))])
            sweep = rec(b"IDLM", 0x30, [(b"EDID", Z("SweepIdleMarker")), (b"IDLA", struct.pack("<I", 0x31))])
            cell = rec(b"CELL", 0x500, [(b"EDID", Z("RiverwoodSleepingGiantInn"))])
            other = rec(b"CELL", 0x501, [(b"EDID", Z("Elsewhere"))])
            refs = [ref(0x600, 0x20, (700, 140, 0), (0, 0, 1.5), scale=1.1), ref(0x601, 0x21, (-1250, 40, 0)),
                    ref(0x602, 0x30, (0, 0, 0)), ref(0x603, 0x22, (10, 10, 0))]
            body = (grup(b"KYWD", 0, kws) + grup(b"FURN", 0, [chair, bytes(lean_raw), alch]) + grup(b"IDLE", 0, [idle])
                    + grup(b"IDLM", 0, [sweep])
                    + grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [cell, grup(0x500, 6, [grup(0x500, 8, refs)]), other,
                                                                grup(0x501, 6, [grup(0x501, 8, [ref(0x604, 0x20, (0, 0, 0))])])])])]))
            sky = os.path.join(d, "Skyrim.esm")
            with open(sky, "wb") as fh:
                fh.write(tes4 + body)
            data = os.path.join(d, "Data")
            os.makedirs(os.path.join(data, "meshes", "furniture"))
            with open(os.path.join(data, "meshes", "furniture", "commonchair01.nif"), "wb") as fh:
                fh.write(chair_nif())
            work = os.path.join(d, "work")
            os.makedirs(work)
            cj = os.path.join(work, "cell.json")
            with open(cj, "w") as fh:
                json.dump({"cell": "RiverwoodSleepingGiantInn"}, fh)
            with open(os.path.join(work, "cells.txt"), "w") as fh:
                fh.write(cj + "\n")
            with open(os.path.join(work, "actors.json"), "w") as fh:
                json.dump({"actors": [{"packages": [{"inputs": {"2": {"type": "near_reference",
                                                                       "source": "000601:Skyrim.esm"}}}]}]}, fh)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(M.main(["--skyrim", sky, "--skyrim-data", data, "--work", work]), 0)
            with open(os.path.join(work, "furniture.json")) as fh:
                r = json.load(fh)
            b = r["bases"]
            ch = b["000020:Skyrim.esm"]
            self.assertEqual((ch["kind"], ch["template"], ch["model"]), ("chair", "001BF52D", "Furniture\\CommonChair01.nif"))
            # NIF marker 0: (1.5, -20, 0) units, heading pi, entry Front+Left minus the record's disabled Left
            self.assertEqual(ch["markers"][0], {"offset_m": [round(1.5 / 70, 3), round(-20 / 70, 3), 0.0],
                                                "rot_deg": 180.0, "entry": ["Front"]})
            self.assertEqual(ch["markers"][1]["entry"], ["Front"])
            ln = b["000021:Skyrim.esm"]
            self.assertEqual((ln["kind"], ln["template_edid"], ln["model"], ln["markers"]),
                             ("bartender", "NPCBartender_Standing", None, []))
            self.assertEqual((b["000030:Skyrim.esm"]["kind"], b["000030:Skyrim.esm"]["template_edid"]),
                             ("sweep", "NPCSweeping"))
            self.assertNotIn("000022:Skyrim.esm", b)                  # crafting station: left as it is
            self.assertTrue(any("CraftingAlchemyWorkbench" in s for s in r["skipped"]))
            byref = {x["formkey"]: x for x in r["refs"]}
            self.assertEqual(sorted(byref), ["000600:Skyrim.esm", "000601:Skyrim.esm", "000602:Skyrim.esm"])
            self.assertEqual((byref["000600:Skyrim.esm"]["scale"], byref["000600:Skyrim.esm"]["rot"][2]), (1.1, 1.5))
            self.assertEqual([k for k, v in byref.items() if v["persistent"]], ["000601:Skyrim.esm"])
            self.assertIn("chair -> FoundCanvasChair01_Free: CommonChair01R x1", buf.getvalue())
            self.assertEqual(ln["shift_m"], [0.0, 0.30, 0.0])          # measured default: onto the counter face

            with contextlib.redirect_stdout(io.StringIO()):
                M.main(["--skyrim", sky, "--skyrim-data", data, "--work", work, "--marker-z", "skyrim",
                        "--shift", "bartender=0,0.25,0"])
            with open(os.path.join(work, "furniture.json")) as fh:
                r2 = json.load(fh)
            self.assertEqual(r2["bases"]["000020:Skyrim.esm"]["markers"][0]["offset_m"][2], 0.0)
            self.assertEqual(r2["bases"]["000021:Skyrim.esm"]["shift_m"], [0.0, 0.25, 0.0])
            self.assertNotIn("shift_m", r2["bases"]["000020:Skyrim.esm"])
            self.assertEqual(M.parse_shift(["bartender=0,0,0"])["bartender"], [0.0, 0.0, 0.0])
            with self.assertRaises(ValueError):
                M.parse_shift(["nosuchkind=0,0,0"])

    def test_kinds(self):
        self.assertEqual(M.kind_of({"type": "FURN", "edid": "CommonBed01", "keywords": [], "mnam": {"flags": ["Has Sleep Marker"]}}), "bed")
        self.assertEqual(M.kind_of({"type": "FURN", "edid": "FarmTableBench01", "keywords": ["IsTable"],
                                    "entry_points": [{"type": "Sit"}]}), "bench")
        self.assertIsNone(M.kind_of({"type": "FURN", "edid": "MQ203_EsbernTable", "keywords": []}))
        self.assertEqual(M.kind_of({"type": "FURN", "edid": "CounterLeanMarker", "keywords": ["FurnitureCounterLeanMarker"]}),
                         "lean_counter")
        self.assertEqual(M.kind_of({"type": "FURN", "edid": "LeanTableMarker", "keywords": ["isLeanTable"]}), "lean_table")
        self.assertEqual(M.kind_of({"type": "IDLM", "edid": "X", "animations": ["IdleOffsetArmsCrossedStart"]}), "arms_crossed")
        self.assertEqual(M.kind_of({"type": "IDLM", "edid": "X", "animations": ["IdleSomething"]}), "stand")

    def test_crafting_kinds(self):
        pot = {"type": "FURN", "edid": "CraftingCookingPotSm", "bench_type": 1,
               "keywords": ["FurnitureSpecial", "isSmallCookingPot", "CraftingCookpot"]}
        self.assertEqual(M.kind_of(pot), "cook")
        self.assertIsNone(M.kind_of(pot, crafting=False))                       # --no-crafting: a static
        cases = {"CraftingAlchemyWorkbench": (["isAlchemy", "WICraftingAlchemy"], 5, "alchemy"),
                 "CraftingEnchantingWorkbenchTabletop": (["isEnchanting"], 3, "workbench"),
                 "CraftingSmithingForge": (["CraftingSmithingForge"], 1, "workbench"),
                 "CraftingSmithingSharpeningWheel": (["CraftingSmithingSharpeningWheel"], 2, "weapon_bench"),
                 "CraftingSmithingArmorTable": (["CraftingSmithingArmorTable"], 7, "armor_bench"),
                 "CraftingTanningRack": (["CraftingTanningRack"], 1, "scrape"),
                 "CraftingSmithingAnvil": ([], 1, "hammer"),
                 "CraftingSomethingNew": ([], 1, None)}                         # a bench we do not know: static
        for edid, (kw, bt, want) in cases.items():
            self.assertEqual(M.kind_of({"type": "FURN", "edid": edid, "keywords": kw, "bench_type": bt}), want, edid)
        for k in ("cook", "alchemy", "workbench", "weapon_bench", "armor_bench", "scrape"):
            self.assertIn(k, M.TEMPLATES)
        self.assertIn("scrape", M.SPECIAL)                                      # the wall-wipe marker's own offset
        self.assertNotIn("cook", M.SPECIAL)                                     # the pot's Skyrim marker
        self.assertEqual(M.kind_of({"type": "FURN", "edid": "HammerTableMarker", "keywords": ["isHammerTable"]}),
                         "hammer")


if __name__ == "__main__":
    unittest.main()
