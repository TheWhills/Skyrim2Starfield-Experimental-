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
    def test_face_npc(self):
        faces = {"npcs": [{"edid": "Ralof", "test_npc": {"form_id": "03000805", "template_form_id": "0001ABCD"}},
                          {"edid": "Orgnar", "test_npc": "no vanilla template NPC of this sex"}]}
        p = os.path.join("C:", "Mods", "S2S Face Test", "faces.json")
        f = M.face_npc(faces, "ralof", p)
        self.assertEqual((f["plugin"], f["form_id"]), ("S2SFaceTest.esm", "03000805"))
        self.assertEqual(os.path.dirname(f["path"]), os.path.dirname(os.path.abspath(p)))
        self.assertIsNone(M.face_npc(faces, "Orgnar", p))
        self.assertEqual(M.face_npc(faces, "Ralof", p, "X/Other.esm")["plugin"], "Other.esm")

    def test_sf_schedule(self):
        s = {"month": -1, "day_of_week": -1, "date": 0, "hour": 6, "minute": 0, "duration_min": 60}
        self.assertEqual(M.sf_schedule(s), dict(s, month=0))
        self.assertEqual(M.sf_schedule(dict(s, month=0))["month"], 1)       # Skyrim January -> Starfield 1
        self.assertIsNone(M.sf_schedule(None))

    def test_orgnar(self):
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            npc = rec(b"NPC_", 0x100, [(b"EDID", Z("Orgnar")), (b"FULL", Z("Orgnar")), (b"ACBS", bytes(24)),
                                       (b"PKID", struct.pack("<I", 0x202)), (b"PKID", struct.pack("<I", 0x200)),
                                       (b"PKID", struct.pack("<I", 0x203))])
            quest = rec(b"PACK", 0x202, [(b"EDID", Z("MQSomething")), (b"PKDT", struct.pack("<IBBBBHH", 0, 18, 0, 0, 0, 0, 0)),
                                         (b"CTDA", bytes(32)), (b"PKCU", struct.pack("<III", 0, 0x201, 0))])
            eat_t = pack(0x204, "Eat", 19, 0, None, [("Location", b"PLDT", struct.pack("<iIi", 3, 0, 0))], [0],
                         [(0, "Location")])
            eat = pack(0x203, "OrgnarEat7x1", 18, 0x204, (7, 0, 60), [("Location", b"PLDT", struct.pack("<iIi", 3, 0, 512))], [0])
            tpl = pack(0x201, "SandboxWorking", 19, 0, None,
                       [("Location", b"PLDT", struct.pack("<iIi", 3, 0, 0)), ("Bool", *B(0)), ("Bool", *B(0)),
                        ("Float", b"CNAM", struct.pack("<f", 50))],
                       [0, 14, 1, 7], [(0, "Location"), (1, "Allow Eating"), (14, "Unlock On Arrival?"),
                                       (25, "Prefered Path Only?"), (7, "Energy")],
                       [("Procedure", "Sandbox")])
            pk = pack(0x200, "OrgnarWorkInn0x24", 18, 0x201, (-1, -1, 0),
                      [("Location", b"PLDT", struct.pack("<iIi", 0, 0x601, 256)), ("Bool", *B(0)), ("Bool", *B(1)),
                       ("Float", b"CNAM", struct.pack("<f", 50))],
                      [0, 14, 1, 7])
            cell = rec(b"CELL", 0x500, [(b"EDID", Z("RiverwoodSleepingGiantInn"))])
            achr = rec(b"ACHR", 0x600, [(b"NAME", struct.pack("<I", 0x100)), (b"DATA", struct.pack("<6f", -1312.8, 18.3, 0, 0, 0, 1.5))])
            marker = rec(b"REFR", 0x601, [(b"NAME", struct.pack("<I", 0x3B)), (b"DATA", struct.pack("<6f", -1250, 40, 0, 0, 0, 0))])
            xm = rec(b"STAT", 0x3B, [(b"EDID", Z("XMarker"))])
            body = (grup(b"STAT", 0, [xm]) + grup(b"NPC_", 0, [npc]) + grup(b"PACK", 0, [pk, tpl, quest, eat_t, eat])
                    + grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [cell, grup(0x500, 6, [grup(0x500, 8, [achr, marker])])])])]))
            sky = os.path.join(d, "Skyrim.esm")
            with open(sky, "wb") as fh:
                fh.write(tes4 + body)
            sf = os.path.join(d, "Starfield.esm")
            with open(sf, "wb") as fh:
                fh.write(tes4 + grup(b"PACK", 0, [pack(
                    0x2CB1, "Sandbox", 19, 0, None,
                    [("Location", b"PLDT", struct.pack("<iIfI", 3, 0, 0, 0)), ("Bool", *B(0)), ("Bool", *B(0)),
                     ("Float", b"CNAM", struct.pack("<f", 0.5))],
                    [2, 12, 5, 18], [(0, "Location"), (2, "Location"), (5, "Allow Eating"), (12, "Unlock on Arrival?"),
                                     (18, "Energy")],
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
            self.assertIsNone(r["xmarker"])                       # the synthetic Starfield.esm has none
            self.assertEqual((ac["cell"], ac["template_npc"], ac["pos"][0]), ("RiverwoodSleepingGiantInn", "0001ABCD", -1312.8))
            p = ac["packages"][0]
            self.assertEqual((p["sf_template"], p["sf_template_form"], p["edid"]), ("Sandbox", "00002CB1", "S2S_OrgnarWorkInn0x24"))
            self.assertEqual(p["schedule"]["hour"], -1)
            # Skyrim's month -1 ("any") is Starfield's 0 (form version >= 122 stores month + 1); the Skyrim one kept
            self.assertEqual((p["schedule"]["month"], p["skyrim_schedule"]["month"]), (0, -1))
            self.assertEqual(ac["packages"][1]["schedule"]["month"], 0)
            # Skyrim Energy 50 (0-100) -> Starfield 0.5 (0-1)
            self.assertAlmostEqual(p["inputs"]["18"]["value"], 0.5)
            ins = p["inputs"]
            self.assertEqual(ins["2"]["type"], "near_reference")
            self.assertEqual(ins["2"]["source"], "000601:Skyrim.esm")
            self.assertAlmostEqual(ins["2"]["radius_m"], 256 / 70, places=3)
            self.assertEqual(ins["2"]["pos"], [-1250.0, 40.0, 0.0])
            self.assertEqual((ins["12"]["value"], ins["5"]["value"]), (False, True))
            self.assertIn("Orgnar in RiverwoodSleepingGiantInn", out.getvalue())
            # no face-test NPC of its own: generic copy, said so
            self.assertNotIn("face_npc", ac)
            self.assertTrue(any("Orgnar: no face-test NPC" in n for n in r["notes"]))
            # the quest-conditioned package is left out; Eat becomes Sandbox near the editor location, eating allowed
            self.assertEqual([q["skyrim"] for q in ac["packages"]], ["OrgnarWorkInn0x24", "OrgnarEat7x1"])
            self.assertTrue(any("MQSomething: left out" in n for n in r["notes"]))
            e = ac["packages"][1]
            self.assertEqual((e["sf_template"], e["inputs"]["2"]["type"], e["inputs"]["5"]["value"]),
                             ("Sandbox", "near_editor_location", True))



class ExteriorTests(unittest.TestCase):
    def test_exterior_locations(self):
        """2026-11-12 (owner: NPCs walk around Riverwood, in and out): with --exterior, a package near a reference in
        a converted exterior cell is kept as near_exterior_reference (its Skyrim spot); a reference outside it is still
        left out; without --exterior both are left out, as before."""
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            npc = rec(b"NPC_", 0x100, [(b"EDID", Z("Alvor")), (b"ACBS", bytes(24)),
                                       (b"PKID", struct.pack("<I", 0x200)), (b"PKID", struct.pack("<I", 0x210))])
            tpl = pack(0x201, "Sandbox", 19, 0, None, [("Location", b"PLDT", struct.pack("<iIi", 3, 0, 0))], [0],
                       [(0, "Location")], [("Procedure", "Sandbox")])
            forge = pack(0x200, "AlvorWorkForge", 18, 0x201, (8, 0, 600),
                         [("Location", b"PLDT", struct.pack("<iIi", 0, 0x701, 512))], [0])
            far = pack(0x210, "AlvorVisitWhiterun", 18, 0x201, (20, 0, 60),
                       [("Location", b"PLDT", struct.pack("<iIi", 0, 0x801, 512))], [0])
            house = rec(b"CELL", 0x500, [(b"EDID", Z("AlvorAndSigridsHouse")), (b"DATA", b"\x01\x00")])
            achr = rec(b"ACHR", 0x600, [(b"NAME", struct.pack("<I", 0x100)), (b"DATA", struct.pack("<6f", 1, 2, 3, 0, 0, 0))])
            ext = rec(b"CELL", 0x510, [(b"DATA", b"\x00\x00")])
            forge_mk = rec(b"REFR", 0x701, [(b"NAME", struct.pack("<I", 0x3B)),
                                             (b"DATA", struct.pack("<6f", 2000, 3000, 100, 0, 0, 1))])
            anvil = rec(b"REFR", 0x702, [(b"NAME", struct.pack("<I", 0x3B)), (b"DATA", struct.pack("<6f", 2010, 3000, 100, 0, 0, 0))])
            ext2 = rec(b"CELL", 0x520, [(b"DATA", b"\x00\x00")])
            far_mk = rec(b"REFR", 0x801, [(b"NAME", struct.pack("<I", 0x3B)), (b"DATA", struct.pack("<6f", 9e4, 9e4, 0, 0, 0, 0))])
            wrld = rec(b"WRLD", 0x3C, [(b"EDID", Z("Tamriel"))])
            body = (grup(b"NPC_", 0, [npc]) + grup(b"PACK", 0, [forge, far, tpl])
                    + grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [house, grup(0x500, 6, [grup(0x500, 8, [achr])])])])])
                    + grup(b"WRLD", 0, [wrld, grup(0x3C, 1, [
                        ext, grup(0x510, 6, [grup(0x510, 9, [forge_mk, anvil])]),
                        ext2, grup(0x520, 6, [grup(0x520, 9, [far_mk])])])]))
            sky = os.path.join(d, "Skyrim.esm")
            with open(sky, "wb") as fh:
                fh.write(tes4 + body)
            sf = os.path.join(d, "Starfield.esm")
            with open(sf, "wb") as fh:
                fh.write(tes4 + grup(b"PACK", 0, [pack(
                    0x2CB1, "Sandbox", 19, 0, None, [("Location", b"PLDT", struct.pack("<iIfI", 3, 0, 0, 0))], [2],
                    [(2, "Location")], [("Procedure", "Sandbox")])]))
            work = os.path.join(d, "work")
            os.makedirs(work)
            cj = os.path.join(work, "cell.json")
            with open(cj, "w") as fh:
                json.dump({"cell": "AlvorAndSigridsHouse"}, fh)
            with open(os.path.join(work, "cells.txt"), "w") as fh:
                fh.write(cj + "\n")
            exterior = os.path.join(d, "skyrim_all")
            os.makedirs(exterior)
            with open(os.path.join(exterior, "formids.json"), "w") as fh:
                json.dump({"plugin": "SkyrimAll.esm", "world": "Tamriel", "refs": {"000702:Skyrim.esm": "00001234"}}, fh)
            args = ["--skyrim", sky, "--starfield", sf, "--npc", "Alvor", "--work", work, "--template-npc", "0001ABCD"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(M.main(args + ["--exterior", exterior]), 0)
            with open(os.path.join(work, "actors.json")) as fh:
                r = json.load(fh)
            pk = r["actors"][0]["packages"]
            self.assertEqual([p["skyrim"] for p in pk], ["AlvorWorkForge"])
            loc = pk[0]["inputs"]["2"]
            self.assertEqual((loc["type"], loc["source"], loc["pos"], loc["cell"]),
                             ("near_exterior_reference", "000701:Skyrim.esm", [2000.0, 3000.0, 100.0], "exterior"))
            self.assertTrue(any("AlvorVisitWhiterun: left out" in n for n in r["notes"]))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(M.main(args), 0)
            with open(os.path.join(work, "actors.json")) as fh:
                self.assertEqual(json.load(fh)["actors"][0]["packages"], [])


if __name__ == "__main__":
    unittest.main()
