"""scripts/interior/furniture_survey.py on synthetic plugins: a Skyrim chair (record markers + NIF BSFurnitureMarkerNode)
and idle marker placed in the batch cell; Starfield chairs with SNAM marker parameters (record version 582: 28-byte
elements), one marker-only; reference counts; candidates by marker kind and name."""
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
from test_fo4land import grup, rec, refr  # noqa: E402
from fo4sf import nif  # noqa: E402
import furniture_survey as S  # noqa: E402

Z = lambda s: s.encode() + b"\0"                                     # noqa: E731


def rec_v(typ, fid, fields, version, flags=0):
    data = b"".join(sig + struct.pack("<H", len(d)) + d for sig, d in fields)
    return typ + struct.pack("<IIIIH2x", len(data), flags, fid, 0, version) + data


def chair_nif():
    n = nif.NifFile(user_version=12, bs_version=100)
    n.strings = [b"Scene Root", b"FRN"]
    n.max_string_len = 10
    n.add_block("NiNode", b"\0" * 8)                                  # opaque: the survey only reads the marker block
    marker = struct.pack("<II", 1, 2) + struct.pack("<4fHH", 1.5, -20.0, 0.0, 3.14159265, 1, 0b1001) \
        + struct.pack("<4fHH", 0.0, 30.0, 0.0, 0.0, 1, 0b0001)
    n.add_block("BSFurnitureMarkerNode", marker)
    return nif.serialize(n)


class FurnitureSurveyTests(unittest.TestCase):
    def test_survey(self):
        with tempfile.TemporaryDirectory() as d:
            tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.7, 0, 0x800))])
            kw = rec(b"KYWD", 0x10, [(b"EDID", Z("FurnitureSpecial"))])
            chair = rec(b"FURN", 0x20, [(b"EDID", Z("CommonChair01")), (b"MODL", Z("Furniture\\CommonChair01.nif")),
                                        (b"KWDA", struct.pack("<I", 0x10)), (b"MNAM", struct.pack("<I", 0x40000003)),
                                        (b"ENAM", struct.pack("<I", 0)), (b"NAM0", struct.pack("<2xH", 0b10)),
                                        (b"FNMK", struct.pack("<I", 0)), (b"FNPR", struct.pack("<HH", 1, 0b1001))])
            idle = rec(b"IDLE", 0x31, [(b"EDID", Z("IdleLeanTable"))])
            idlm = rec(b"IDLM", 0x30, [(b"EDID", Z("LeanTableMarker")), (b"IDLF", b"\x01"), (b"IDLC", b"\x01"),
                                       (b"IDLT", struct.pack("<f", 20.0)), (b"IDLA", struct.pack("<I", 0x31))])
            cell = rec(b"CELL", 0x500, [(b"EDID", Z("RiverwoodSleepingGiantInn"))])
            other = rec(b"CELL", 0x501, [(b"EDID", Z("Elsewhere"))])
            refs = [refr(0x600, 0x20, (0, 0, 0)), refr(0x601, 0x20, (100, 0, 0)), refr(0x602, 0x30, (0, 50, 0))]
            body = (grup(b"KYWD", 0, [kw]) + grup(b"FURN", 0, [chair]) + grup(b"IDLE", 0, [idle])
                    + grup(b"IDLM", 0, [idlm])
                    + grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [cell, grup(0x500, 6, [grup(0x500, 8, refs)]),
                                                                other, grup(0x501, 6, [grup(0x501, 8, [
                                                                    refr(0x603, 0x20, (0, 0, 0))])])])])]))
            sky = os.path.join(d, "Skyrim.esm")
            with open(sky, "wb") as fh:
                fh.write(tes4 + body)
            data = os.path.join(d, "SkyData")
            os.makedirs(os.path.join(data, "meshes", "furniture"))
            with open(os.path.join(data, "meshes", "furniture", "commonchair01.nif"), "wb") as fh:
                fh.write(chair_nif())

            snam = lambda x, k, e, ex: struct.pack("<4fIB3xB3x", x, 0.0, 0.0, 0.0, k, e, ex)   # noqa: E731
            sfkw = rec(b"KYWD", 0x40, [(b"EDID", Z("AnimFurnChairSitAnims"))])
            sf_chair = rec_v(b"FURN", 0x50, [(b"EDID", Z("NPCChairCommon01")), (b"MODL", Z("Furniture\\Chair.nif")),
                                             (b"MNAM", struct.pack("<I", 0x40000001)),
                                             (b"FNPR", struct.pack("<HH", 1, 1)),
                                             (b"SNAM", snam(0.0, 0x40, 1, 1) + snam(0.6, 0x40, 1, 3))], 582)
            sf_mark = rec_v(b"FURN", 0x51, [(b"EDID", Z("NPCChairMarker")), (b"FNPR", struct.pack("<HH", 1, 1)),
                                            (b"SNAM", snam(0.0, 0x40, 1, 1))], 582, flags=S.IS_MARKER)
            sf_bed = rec_v(b"FURN", 0x52, [(b"EDID", Z("NPCBedSingle")), (b"FNPR", struct.pack("<HH", 2, 1))], 582)
            sf_idlm = rec_v(b"IDLM", 0x60, [(b"EDID", Z("LeanRailingMarker")), (b"PNAM", struct.pack("<I", 0x40))], 582)
            sf_refs = [refr(0x700, 0x51, (0, 0, 0)), refr(0x701, 0x51, (1, 0, 0)), refr(0x702, 0x50, (0, 0, 0)),
                       refr(0x703, 0x60, (0, 0, 0))]
            sf = os.path.join(d, "Starfield.esm")
            with open(sf, "wb") as fh:
                fh.write(tes4 + grup(b"KYWD", 0, [sfkw]) + grup(b"FURN", 0, [sf_chair, sf_mark, sf_bed])
                         + grup(b"IDLM", 0, [sf_idlm])
                         + grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, [rec(b"CELL", 0x800, [(b"EDID", Z("X"))]),
                                                                     grup(0x800, 6, [grup(0x800, 8, sf_refs)])])])]))
            out = os.path.join(d, "out")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(S.main(["--skyrim", sky, "--skyrim-data", data, "--starfield", sf, "--cell",
                                         "RiverwoodSleepingGiantInn", "--cell", "NoSuchCell", "--out", out]), 0)
            with open(os.path.join(out, "furniture_survey.json")) as fh:
                r = json.load(fh)
            self.assertEqual(r["cells_not_found"], ["NoSuchCell"])
            ch = next(b for b in r["skyrim"] if b["type"] == "FURN")
            self.assertEqual(ch["placed"], {"RiverwoodSleepingGiantInn": 2})          # the other cell's not counted
            self.assertEqual(ch["keywords"], ["FurnitureSpecial"])
            self.assertEqual(ch["mnam"], {"points": [0, 1], "flags": ["Has Sit Marker"]})
            self.assertEqual(ch["markers"], [{"index": 0, "disabled": ["Behind"], "keyword": None}])
            self.assertEqual(ch["entry_points"], [{"type": "Sit", "entry": ["Front", "Left"]}])
            m0, m1 = ch["nif_markers"]
            self.assertEqual((m0["offset"], m0["heading_deg"], m0["anim"], m0["entry"]),
                             ([1.5, -20.0, 0.0], 180.0, "Sit", ["Front", "Left"]))
            self.assertEqual(m1["offset_m"], [0.0, round(30 / 70, 3), 0.0])
            il = next(b for b in r["skyrim"] if b["type"] == "IDLM")
            self.assertEqual((il["animations"], il["idle_timer"], il["placed"]),
                             (["IdleLeanTable"], 20.0, {"RiverwoodSleepingGiantInn": 1}))
            sfc = {b["edid"]: b for b in r["starfield_furniture"]}
            self.assertEqual(sfc["NPCChairCommon01"]["marker_params"][1],
                             {"offset_m": [0.6, 0.0, 0.0], "rot_z_deg": 0.0, "keyword": "AnimFurnChairSitAnims",
                              "entry": ["Front"], "exit": ["Front", "Rear"]})
            self.assertEqual((sfc["NPCChairMarker"]["is_marker"], sfc["NPCChairMarker"]["uses"],
                              sfc["NPCChairCommon01"]["uses"], sfc["NPCBedSingle"]["uses"]), (True, 2, 1, 0))
            self.assertEqual(r["starfield_idle_markers"][0]["archetype"], "AnimFurnChairSitAnims")
            self.assertEqual(r["starfield_idle_markers"][0]["uses"], 1)
            self.assertEqual(r["starfield_marker_keywords"], [["AnimFurnChairSitAnims", 3]])
            # candidates: sit furniture only (the bed is left out), the chair-named one first
            self.assertEqual([c["edid"] for c in ch["starfield_candidates"]], ["NPCChairCommon01", "NPCChairMarker"])
            self.assertIn("FURN CommonChair01 x2", buf.getvalue())

    def test_snam_size(self):
        self.assertEqual((S.snam_size(582), S.snam_size(200), S.snam_size(100)), (28, 24, 20))


if __name__ == "__main__":
    unittest.main()
