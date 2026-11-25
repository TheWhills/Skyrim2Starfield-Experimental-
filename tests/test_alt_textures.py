"""Skyrim alternate textures (2026-11-25, docs/terrain/skyrim-objects.md "Snowy roads"): MODS read as the game loads it,
the same mesh with swapped textures as a model of its own, the swap applied per shape, and the in-place plugin patch
that puts the variants on an already staged exterior (esm_patch, alt_textures_patch). Synthetic plugins only."""
import json
import os
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import esm_patch, exterior, fo4land, skyrimconvert, skyrimrefs  # noqa: E402

REC = struct.Struct("<4sIIIIHH")


def field(sig, data):
    return sig + struct.pack("<H", len(data)) + data


def z(s):
    return s.encode() + b"\0"


def record(typ, fid, *fields, flags=0):
    body = b"".join(fields)
    return REC.pack(typ, len(body), flags, fid, 0, 576, 0) + body


def group(label, *items, gtype=0):
    body = b"".join(items)
    return struct.pack("<4sI4sIII", b"GRUP", 24 + len(body), label, gtype, 0, 0) + body


def tes4(masters=(), count=0, nxt=0x800):
    return record(b"TES4", 0, field(b"HEDR", struct.pack("<fII", 0.96, count, nxt)),
                  *[field(b"MAST", z(m)) + field(b"DATA", bytes(8)) for m in masters])


def mods(*entries):
    out = struct.pack("<I", len(entries))
    for name, fid, index in entries:
        out += struct.pack("<I", len(name)) + name.encode() + struct.pack("<II", fid, index)
    return out


def txst(fid, *tex):
    return record(b"TXST", fid, field(b"EDID", z(f"T{fid:X}")),
                  *[field(b"TX%02d" % i, z(t)) for i, t in enumerate(tex) if t])


class AlternateTexturesTest(unittest.TestCase):
    def test_parse_mods(self):
        # RoadChunkM01Snow 000B23F4 as Skyrim.esm stores it
        d = bytes.fromhex("020000000e000000526f61644368756e6b4d30313a3291080000010000000e000000526f61644368756e6b4d"
                          "30313a301806100000000000")
        self.assertEqual(skyrimrefs.parse_mods(d), [("RoadChunkM01:2", 0x00000891, 1),
                                                    ("RoadChunkM01:0", 0x00100618, 0)])
        self.assertEqual(skyrimrefs.parse_mods(b""), [])

    def test_load_order_and_masters(self):
        with tempfile.TemporaryDirectory() as d:
            sky = tes4() + group(b"STAT",
                                 record(b"STAT", 0x0B23F4, field(b"EDID", z("RoadSnow")), field(b"MODL", z("r.nif")),
                                        field(b"MODS", mods(("Road:0", 0x100, 0), ("Road:2", 0x101, 1)))),
                                 record(b"STAT", 0x0B23F5, field(b"MODS", mods(("Rock:0", 0x100, 0)))),
                                 record(b"STAT", 0x0B23F6, field(b"MODS", mods(("Rock:0", 0x999, 0))))) \
                + group(b"TXST", txst(0x100, "Landscape\\Road01Snow01.dds", "Landscape\\Road01Snow01_n.dds"),
                        txst(0x101, "Landscape\\Dirt02.dds", "Landscape\\Dirt02_n.dds"))
            # Update.esm: the road's second shape gets Update's own set (01 = itself), the rock loses its swaps
            upd = tes4(["Skyrim.esm"]) + group(b"STAT",
                                               record(b"STAT", 0x0B23F4, field(b"MODS", mods(
                                                   ("Road:0", 0x100, 0), ("Road:2", 0x01000800, 1)))),
                                               record(b"STAT", 0x0B23F5, field(b"EDID", z("Rock")))) \
                + group(b"TXST", txst(0x01000800, "Landscape\\Snow01Landscape.dds", "Landscape\\Snow01_n.dds"))
            for name, data in (("Skyrim.esm", sky), ("Update.esm", upd)):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(data)
            alt = skyrimrefs.alternate_textures(d)
        self.assertEqual(set(alt), {"0B23F4:Skyrim.esm"})          # 0B23F5 removed, 0B23F6's set does not exist
        road = {e["name"]: e for e in alt["0B23F4:Skyrim.esm"]}
        self.assertEqual(road["Road:0"]["textures"][:2], ["textures\\Landscape\\Road01Snow01.dds",
                                                          "textures\\Landscape\\Road01Snow01_n.dds"])
        self.assertEqual(road["Road:2"]["textures"][0], "textures\\Landscape\\Snow01Landscape.dds")
        self.assertEqual(road["Road:2"]["index"], 1)
        self.assertEqual(len(road["Road:2"]["textures"]), 8)

    def test_identity(self):
        a = [{"name": "A:0", "index": 0, "textures": ["x.dds", "x_n.dds"]},
             {"name": "A:2", "index": 1, "textures": ["Y.dds", ""]}]
        b = list(reversed(a))
        self.assertEqual(skyrimrefs.alt_id(a), skyrimrefs.alt_id(b))
        self.assertEqual(len(skyrimrefs.alt_id(a)), 8)
        self.assertEqual(skyrimrefs.alt_id(None), "")
        self.assertEqual(exterior.source_key("Landscape/Roads/R.nif"), "meshes\\landscape\\roads\\r.nif")
        self.assertEqual(exterior.source_key("Landscape\\Roads\\R.nif", a),
                         "meshes\\landscape\\roads\\r.nif|alt:" + skyrimrefs.alt_id(a))
        self.assertEqual(exterior.mesh_of(exterior.source_key("R.nif", a)), "meshes\\r.nif")

    def test_convert_jobs(self):
        import make_skyrim_objects as M
        a = [{"name": "R:0", "index": 0, "textures": ["s.dds", "s_n.dds"]}]
        jobs = M.convert_jobs([{"model": "Landscape\\R.nif"},
                               {"model": "Landscape\\R.nif", "alt_textures": a, "base_editor_id": "RSnow"},
                               {"model": "Landscape\\R.nif", "alt_textures": a, "base_editor_id": "RSnowCopy"}])
        self.assertEqual(sorted(jobs), ["meshes\\Landscape\\R.nif", "meshes\\Landscape\\R.nif|alt:"
                                        + skyrimrefs.alt_id(a)])
        alt = jobs["meshes\\Landscape\\R.nif|alt:" + skyrimrefs.alt_id(a)]
        self.assertEqual((alt["nif"], alt["edid_from"]), ("meshes\\Landscape\\R.nif", "RSnow"))
        self.assertIsNone(jobs["meshes\\Landscape\\R.nif"]["alt"])
        # the variant's key is what exterior.place looks a reference up by
        self.assertEqual(("meshes\\Landscape\\R.nif|alt:" + skyrimrefs.alt_id(a)).lower(),
                         exterior.source_key("Landscape\\R.nif", a))


class SwapTest(unittest.TestCase):
    def test_blocks_by_name_then_index(self):
        shapes = [NS(name=b"RoadChunkM01:0", block=7), NS(name=b"RoadChunkM01:2", block=10)]
        alt = [{"name": "roadchunkm01:2", "index": 0, "textures": ["snow.dds", "snow_n.dds"]},   # name decides
               {"name": "Renamed", "index": 0, "textures": ["road.dds", "road_n.dds"]},          # index fallback
               {"name": "Gone", "index": 5, "textures": ["x.dds", ""]}]                         # neither: unused
        got = skyrimconvert.alt_texture_blocks(shapes, alt)
        self.assertEqual(got, {10: ["snow.dds", "snow_n.dds"], 7: ["road.dds", "road_n.dds"]})

    def test_swap_textures(self):
        own = ["textures\\road01.dds", "textures\\road01_n.dds", "", ""]
        self.assertEqual(skyrimconvert.swap_textures(own, None), own)
        self.assertEqual(skyrimconvert.swap_textures(own, ["s.dds", "s_n.dds"] + [""] * 6)[:2], ["s.dds", "s_n.dds"])
        self.assertEqual(skyrimconvert.swap_textures(own, ["s.dds", ""] + [""] * 6)[:2],
                         ["s.dds", "textures\\road01_n.dds"])                    # no normal: the shape's own
        self.assertEqual(skyrimconvert.swap_textures(own, [""] * 8), own)        # an empty set changes nothing


def sf_plugin():
    """A Starfield plugin as TerrainOverlays writes it: TES4, STAT, WRLD (world record, cell children with REFRs)."""
    stat = record(b"STAT", 0x01000800, field(b"EDID", z("SKY_Road")), field(b"OBND", bytes(24)),
                  field(b"MODL", z("skyrim\\road.nif")), field(b"DNAM", bytes(16)))
    other = record(b"STAT", 0x01000801, field(b"EDID", z("SKY_Rock")), field(b"MODL", z("skyrim\\rock.nif")))
    refs = [record(b"REFR", 0x01000900 + i, field(b"NAME", struct.pack("<I", 0x01000800)),
                   field(b"DATA", bytes(24))) for i in range(3)]
    wrld = group(b"WRLD", record(b"WRLD", 0x01000700, field(b"EDID", z("SKY_Tamriel"))),
                 group(struct.pack("<I", 0x01000700), record(b"CELL", 0x01000701),
                       group(struct.pack("<I", 0x01000701), *refs, gtype=9), gtype=1))
    return tes4(["Starfield.esm"], count=7, nxt=0x903) + group(b"STAT", stat, other) + wrld


def walk_ok(buf):
    """Every group's size adds up; returns {fid: (type, fields)}."""
    out = {}

    def walk(s, e):
        n = s
        for it in fo4land.iter_items(buf, s, e):
            if it[0] == "GRUP":
                walk(it[1] + 24, it[2])
                n = it[2]
            else:
                out[it[3]] = (it[0], dict(fo4land.iter_subrecords(fo4land.record_data(buf, it[1]))))
                n = it[1] + 24 + struct.unpack_from("<I", buf, it[1] + 4)[0]
        assert n == e, (n, e)
    walk(esm_patch.len_tes4(buf), len(buf))
    return out


class EsmPatchTest(unittest.TestCase):
    def test_add_and_point(self):
        src = sf_plugin()
        out, fids = esm_patch.add_records(src, b"STAT", [(0x01000800, {b"EDID": z("SKY_RoadSnow"),
                                                                       b"MODL": z("skyrim\\road_alt12345678.nif")})])
        self.assertEqual(fids, [0x01000903])                     # HEDR's next object ID, with the self index
        self.assertEqual(esm_patch.header(out)[:2], (8, 0x904))
        recs = walk_ok(out)
        typ, f = recs[0x01000903]
        self.assertEqual(typ, b"STAT")
        self.assertEqual(fo4land.zstring(f[b"MODL"]), "skyrim\\road_alt12345678.nif")
        self.assertEqual(f[b"OBND"], bytes(24))                  # the rest of the template kept
        out2, n, missing = esm_patch.set_ref_bases(out, {0x01000901: 0x01000903, 0x01000999: 0x01000903})
        self.assertEqual((n, missing), (1, [0x01000999]))
        self.assertEqual(len(out2), len(out))
        recs = walk_ok(out2)
        self.assertEqual(struct.unpack("<I", recs[0x01000901][1][b"NAME"])[0], 0x01000903)
        self.assertEqual(struct.unpack("<I", recs[0x01000900][1][b"NAME"])[0], 0x01000800)
        # the world record and everything after the STAT group: same bytes, shifted only by the new record
        w = esm_patch.len_tes4(src) + struct.unpack_from("<I", src, esm_patch.len_tes4(src) + 4)[0]
        self.assertEqual(out[w + (len(out) - len(src)):], src[w:])

    def test_refuses(self):
        with self.assertRaises(esm_patch.PatchError):
            esm_patch.add_records(sf_plugin(), b"STAT", [(0x01000800, {b"XXXX": b""})])
        with self.assertRaises(esm_patch.PatchError):
            esm_patch.add_records(sf_plugin(), b"STAT", [(0x01000123, {})])


class ApplyPlanTest(unittest.TestCase):
    def test_apply_plan(self):
        import alt_textures_patch as P
        a = [{"name": "R:0", "index": 0, "textures": ["s.dds", "s_n.dds"]}]
        key = exterior.source_key("Landscape\\Road.nif", a)
        objects = {"bases": [{"edid": "SKY_Road", "model": "skyrim\\road.nif", "source": "meshes\\Landscape\\Road.nif",
                              "collision": "skyrim-native", "bounds": [[0, 0, 0], [1, 1, 1]]},
                             {"edid": "SKY_Grass", "model": "skyrim\\grass.nif"}],
                   "refs": [{"src": f"00000{i}:Skyrim.esm", "base": 0} for i in range(3)]}
        export = [{"formkey": "000000:Skyrim.esm", "base_formkey": "0B23F4:Skyrim.esm", "model": "Landscape\\Road.nif",
                   "type": "Static", "base_editor_id": "RoadSnow"},
                  {"formkey": "000001:Skyrim.esm", "base_formkey": "0B23F4:Skyrim.esm", "model": "Landscape\\Road.nif",
                   "type": "Static", "base_editor_id": "RoadSnow"},
                  {"formkey": "000002:Skyrim.esm", "base_formkey": "000AAA:Skyrim.esm", "model": "Landscape\\Road.nif",
                   "type": "Static", "base_editor_id": "Road"}]
        models, refs, n = P.plan_variants(objects, export, {"0B23F4:Skyrim.esm": a})
        self.assertEqual(len(models), 1)
        self.assertEqual(refs, {"000000:Skyrim.esm": key, "000001:Skyrim.esm": key})
        formids = {"plugin": "P.esm", "bases": {"SKY_Road": "000800", "SKY_Rock": "000801"},
                   "refs": {f"00000{i}:Skyrim.esm": f"00090{i}" for i in range(3)}}
        items = {key: {"editor_id": "RoadSnow", "model": "skyrim\\road_alt.nif", "source": key}}
        plugin, obj2, fid2, rep = P.apply_plan(objects, formids, refs, items, sf_plugin())
        self.assertEqual((rep["new bases"], rep["references moved"]), (1, 2))
        self.assertEqual(obj2["bases"][2], {"edid": "SKY_RoadSnow", "model": "skyrim\\road_alt.nif", "source": key,
                                            "collision": "skyrim-native", "bounds": [[0, 0, 0], [1, 1, 1]]})
        self.assertEqual([r["base"] for r in obj2["refs"]], [2, 2, 0])
        self.assertEqual(fid2["bases"]["SKY_RoadSnow"], "000903")
        self.assertEqual(objects["refs"][0]["base"], 0)            # inputs untouched
        recs = walk_ok(plugin)
        self.assertEqual(struct.unpack("<I", recs[0x01000900][1][b"NAME"])[0], 0x01000903)
        self.assertEqual(struct.unpack("<I", recs[0x01000902][1][b"NAME"])[0], 0x01000800)
        # planning again after the apply gives the same plan (references already on their variant)
        self.assertEqual(P.plan_variants(obj2, export, {"0B23F4:Skyrim.esm": a})[:2], (models, refs))
        # again: nothing more to do
        plugin2, _o, _f, rep2 = P.apply_plan(obj2, fid2, refs, items, plugin)
        self.assertEqual((rep2["new bases"], rep2["references moved"]), (0, 0))
        self.assertEqual(plugin2, plugin)


if __name__ == "__main__":
    unittest.main()
