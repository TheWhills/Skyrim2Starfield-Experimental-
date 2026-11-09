"""src/fo4sf/packages.py and scripts/npc/package_survey.py on synthetic Skyrim / Starfield plugins."""
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
from fo4sf import packages  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402
import package_survey as S  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731


def pack(fid, edid, kind, template=0, schedule=None, inputs=(), names=(), tree=(), radius_float=False):
    f = [(b"EDID", Z(edid)), (b"PKDT", struct.pack("<IBBBBHH", 0x100, kind, 0, 0, 0, 0, 0))]
    if schedule:
        f.append((b"PSDT", struct.pack("<5b3xI", -1, -1, 0, *schedule)))
    f.append((b"PKCU", struct.pack("<III", len(inputs), template, 0)))
    for typ, sig, val in inputs:
        f += [(b"ANAM", Z(typ)), (sig, val)]
    for i, n in enumerate(names):
        f += [(b"UNAM", struct.pack("<b", i)), (b"BNAM", Z(n))]
    f.append((b"XNAM", b"\0"))
    for branch, proc in tree:
        f += [(b"ANAM", Z(branch)), (b"PNAM", Z(proc))]
    return rec(b"PACK", fid, f)


class PackageTests(unittest.TestCase):
    def test_parse_both_layouts(self):
        sky = pack(1, "OrgnarSandbox", 18, 2, (8, 0, 720), [("Location", b"PLDT", struct.pack("<iIi", 1, 0x500, 300))],
                   ["Location"])
        p = packages.parse_pack(list(_subs(sky)))
        self.assertEqual((p["type"], p["template"], p["schedule"]["hour"], p["schedule"]["duration_min"]), (18, 2, 8, 720))
        self.assertEqual(p["inputs"][0]["value"]["radius"], 300)
        self.assertEqual(p["input_names"], [{"index": 0, "name": "Location"}])
        sf = pack(3, "Sandbox", 19, 0, None, [("Location", b"PLDT", struct.pack("<iIfI", 1, 0, 2.5, 0))], ["Location"],
                  [("Procedure", "Sandbox")])
        q = packages.parse_pack(list(_subs(sf)), starfield=True)
        self.assertEqual(q["inputs"][0]["value"]["radius"], 2.5)
        self.assertEqual(q["procedures"], [{"branch": "Procedure", "procedure": "Sandbox", "inputs": []}])
        # PKC2 after a branch: the inputs it uses
        r = packages.parse_pack(list(_subs(sf)) + [(b"PKC2", b"\x02")], starfield=True)
        self.assertEqual(r["procedures"][0]["inputs"], [2])

    def test_survey(self):
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            npc = rec(b"NPC_", 0x100, [(b"EDID", Z("Orgnar")), (b"ACBS", bytes(24)), (b"PKID", struct.pack("<I", 0x200))])
            tpl = pack(0x201, "Sandbox", 19, 0, None, [("Location", b"PLDT", struct.pack("<iIi", 3, 0, 0))],
                       ["Location"], [("Procedure", "Sandbox")])
            pk = pack(0x200, "OrgnarSandbox", 18, 0x201, (8, 0, 720),
                      [("Location", b"PLDT", struct.pack("<iIi", 0, 0x601, 300))], ["Location"])
            bed = rec(b"FURN", 0x300, [(b"EDID", Z("BedSingle01"))])
            cell = rec(b"CELL", 0x500, [(b"EDID", Z("RiverwoodSleepingGiantInn"))])
            achr = rec(b"ACHR", 0x600, [(b"NAME", struct.pack("<I", 0x100)), (b"DATA", struct.pack("<6f", 1, 2, 3, 0, 0, 0))])
            bedref = rec(b"REFR", 0x601, [(b"NAME", struct.pack("<I", 0x300)), (b"DATA", struct.pack("<6f", 4, 5, 6, 0, 0, 0)),
                                          (b"XOWN", struct.pack("<I", 0x100))])
            body = (grup(b"NPC_", 0, [npc]) + grup(b"PACK", 0, [pk, tpl]) + grup(b"FURN", 0, [bed])
                    + grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [cell, grup(0x500, 6, [grup(0x500, 8, [achr, bedref])])])])]))
            esm = os.path.join(d, "Skyrim.esm")
            with open(esm, "wb") as fh:
                fh.write(tes4 + body)
            sf = os.path.join(d, "Starfield.esm")
            with open(sf, "wb") as fh:
                fh.write(tes4 + grup(b"PACK", 0, [
                    pack(0x900, "Sandbox", 19, 0, None, [("Location", b"PLDT", struct.pack("<iIfI", 3, 0, 0, 0))],
                         ["Location"], [("Procedure", "Sandbox")]),
                    pack(0x901, "SomeSandbox", 18, 0x900, (0, 0, 1440))]))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(S.main(["--skyrim", esm, "--npc", "Orgnar", "--starfield", sf, "--out", d]), 0)
            with open(os.path.join(d, "package_survey.json")) as fh:
                r = json.load(fh)
            n = r["npcs"][0]
            self.assertEqual(n["packages"][0]["template"]["edid"], "Sandbox")
            v = n["packages"][0]["inputs"][0]["value"]
            self.assertEqual(v["form"]["base"]["edid"], "BedSingle01")
            self.assertEqual(v["form"]["cell"]["edid"], "RiverwoodSleepingGiantInn")
            self.assertEqual(n["placed"][0]["pos"], [1.0, 2.0, 3.0])
            self.assertEqual(n["owned_in_its_cells"][0]["base"]["edid"], "BedSingle01")
            self.assertEqual(r["template_match"]["Sandbox"]["same_edid"]["used_by"], 1)
            self.assertIn("OrgnarSandbox", out.getvalue())


def _subs(record):
    from fo4sf import fo4land
    return [(s, bytes(dd)) for s, dd in fo4land.iter_subrecords(record[24:])]


if __name__ == "__main__":
    unittest.main()
