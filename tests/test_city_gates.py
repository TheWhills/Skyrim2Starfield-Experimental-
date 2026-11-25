"""Walled cities reached through their gates (2026-11-25, Whiterun first): a child world with "Use Land Data" takes its
parent's land even with some LAND of its own; a city's terrain is cut from the installed Tamriel's terrain file; the
gates are new persistent load doors in the registration plugin (both worlds' persistent cells, XTEL to each other),
the city world's own FormIDs remapped; the installer hides the gate statics in place and puts them back. No game data."""
import contextlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import btd, fo4land, sfplugin, skyrimland, worldgates  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
import test_skyrim_objects as T  # noqa: E402
from test_skyrimland import hills  # noqa: E402
import register_worlds as RW  # noqa: E402
import make_skyrim_overlay as MSO  # noqa: E402
import deploy_skyrim_city as DSC  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                         # noqa: E731
I = lambda v: struct.pack("<I", v)                                       # noqa: E731
INFO = {"hedr_version": 0.96, "form_version": 555}


def hdr(t, flags=0):
    return struct.pack("<4sIII", t, 0, flags, 0) + bytes(4) + struct.pack("<HH", 576, 0)


def rec(t, subs, fid, flags=0):
    return sfplugin.record_bytes(t, hdr(t, flags), subs, fid)


def grp(label, gtype, body: bytes):
    lab = struct.pack("<I", label) if isinstance(label, int) else label
    return struct.pack("<4sI4si", b"GRUP", 24 + len(body), lab, gtype) + bytes(8) + body


def world_plugin(path, masters, own_recs, world, cell, static=None, extra_tail=b""):
    """A Starfield-shaped plugin: top records (one group per type), then a WRLD group with the world, its persistent
    cell (no children) and one exterior cell holding `static` (a REFR record) in its temporary children."""
    wsubs, wfid = world
    csubs, cfid = cell
    ext = b""
    if static is not None:
        ecell = cfid + 1
        ext = grp(b"\0\0\0\0", 4, grp(b"\0\0\0\0", 5, rec(b"CELL", [(b"XCLC", struct.pack("<iiI", 2, -1, 0))], ecell)
                                       + grp(ecell, 6, grp(ecell, 9, static))))
    kids = rec(b"CELL", csubs, cfid, 0x400) + grp(cfid, 6, grp(cfid, 8, b"")) + ext
    wgroup = grp(b"WRLD", 0, rec(b"WRLD", wsubs, wfid) + grp(wfid, 1, kids))
    data = sfplugin.build([(t, hdr(t), s, f) for t, s, f in own_recs], INFO, masters=masters, tail=wgroup + extra_tail)
    with open(path, "wb") as fh:
        fh.write(data)


def static_ref(fid, base, pos, rz):
    return rec(b"REFR", [(b"NAME", I(base)), (b"DATA", struct.pack("<6f", *pos, 0.0, 0.0, rz))], fid)


class CityLandTests(unittest.TestCase):
    def test_use_land_data_wins_over_a_few_own_land_records(self):
        cells = [(x, y) for x in range(2, 5) for y in range(1, 4)]
        with tempfile.TemporaryDirectory() as tmp:
            esm = os.path.join(tmp, "Skyrim.esm")
            c, persistent = T.world_refs()
            with open(esm, "wb") as f:
                f.write(F.build_esm(c, hills, T.EXTENT, persistent_refs=persistent,
                                    extra_worlds=[(0x50, "WhiterunWorld", 0x3C, 0x1, cells, {}, {(3, 2): -9999.0}),
                                                  (0x51, "MarkarthWorld", 0x3C, 0x0, cells, {}, {(3, 2): -9999.0})]))
            land = skyrimland.SkyrimLand(esm, "WhiterunWorld")
            own = skyrimland.SkyrimLand(esm, "MarkarthWorld")
        self.assertEqual(land.land_source, "Tamriel")              # the flag: parent's land, own LAND left out
        self.assertEqual(land.own_land_ignored, 1)
        self.assertEqual(land.extent, (2, 4, 1, 3))
        _, want = __import__("test_skyrimland").cell_vhgt(3, 2)
        self.assertTrue((land.grids[(3, 2)] == want).all())
        self.assertEqual(land.summary()["own_land_ignored"], 1)
        self.assertEqual(own.land_source, "MarkarthWorld")          # no flag: its own LAND, as before
        self.assertEqual(set(own.grids), {(3, 2)})


class CropTests(unittest.TestCase):
    def tamriel(self, n=6):
        rng = np.random.default_rng(3)
        h = rng.integers(0, 65535, (n * 128, n * 128), dtype=np.uint16)
        w = rng.integers(0, 65535, (n * 128, n * 128), dtype=np.uint16)
        q = rng.integers(0, 9, (n * 2, n * 2, 8), dtype=np.uint8)
        return btd.Btd(6, -100.0, 900.0, [0x10861, 0x364E7, 0x1D229], h, w, q)

    def test_crop_is_the_same_cells(self):
        t = self.tamriel()
        c = btd.crop(t, 1, 2, 3, 2)
        self.assertEqual((c.ncx, c.ncy), (3, 2))
        self.assertTrue(np.array_equal(c.heights_raw, t.heights_raw[256:512, 128:512]))
        self.assertTrue(np.array_equal(c.weights, t.weights[256:512, 128:512]))
        self.assertTrue(np.array_equal(c.quad_map, t.quad_map[4:8, 2:8]))
        self.assertEqual((c.hmin, c.hmax, c.ltex), (t.hmin, t.hmax, t.ltex))
        back = btd.read(btd.write(c))
        self.assertTrue(np.array_equal(back.heights_raw, c.heights_raw))
        with self.assertRaises(btd.BtdError):
            btd.crop(t, 4, 0, 3, 1)

    def test_terrain_from_cuts_the_city_out_of_tamriel(self):
        t = self.tamriel()
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "skyrim_all"), os.path.join(d, "city")
            for root in (src, out):
                os.makedirs(os.path.join(root, "Data", "Terrain"))
            with open(os.path.join(src, "Data", "Terrain", "SKY_Tamriel.btd"), "wb") as fh:
                fh.write(btd.write(t))
            with open(os.path.join(src, "overlays_params.json"), "w") as fh:
                json.dump({"overlays": [{"world": "SKY_Tamriel", "cells_cw": {"x": [-3, 2], "y": [-3, 2]},
                                         "origin_cw_m": [0.0, 0.0], "height_offset_m": 385.0,
                                         "btd_file": "Data/Terrain/SKY_Tamriel.btd"}]}, fh)
            own = btd.crop(t, 0, 0, 2, 2)                       # this build's own terrain: anything 2 x 2
            with open(os.path.join(out, "Data", "Terrain", "SKY_City.btd"), "wb") as fh:
                fh.write(btd.write(own))
            prm = {"ltex_overrides": [{"form_id": 1}], "overlays": [
                {"world": "SKY_City", "cells_cw": {"x": [0, 1], "y": [-1, 0]}, "origin_cw_m": [100.0, -100.0],
                 "height_offset_m": 385.0, "btd_file": "Data/Terrain/SKY_City.btd",
                 "btd_copies": ["Data/Terrain/copy.btd"]}]}
            rep = MSO.crop_from(prm, out, src)
            cut = btd.read(open(os.path.join(out, "Data", "Terrain", "SKY_City.btd"), "rb").read())
            copy = open(os.path.join(out, "Data", "Terrain", "copy.btd"), "rb").read()
            # cells_cw are shared-frame cells: city x 0..1 = Tamriel columns 3..4, y -1..0 = rows 2..3
            self.assertTrue(np.array_equal(cut.heights_raw, t.heights_raw[2 * 128:4 * 128, 3 * 128:5 * 128]))
            self.assertEqual(copy, btd.write(cut))
            self.assertNotIn("ltex_overrides", prm)
            self.assertEqual((prm["hmin"], prm["hmax"]), (-100.0, 900.0))
            self.assertEqual(rep["source_cells"], {"x": [0, 1], "y": [-1, 0]})
            prm["overlays"][0]["height_offset_m"] = 0.0
            with self.assertRaises(SystemExit):
                MSO.crop_from(prm, out, src)


class RemapTests(unittest.TestCase):
    def test_world_fields_and_large_references(self):
        rnam = struct.pack("<hhI", -7, -35, 2) + I(0x01036AA6) + struct.pack("<hh", -4, -33) + I(0x00001234) + bytes(4)
        subs = [(b"EDID", Z("W")), (b"BNAM", I(0x01000801)), (b"XLCN", I(0x01000802)), (b"BNAM", I(0x001CBD6A)),
                (b"CNAM", I(0x0024E982)), (b"RNAM", rnam), (b"DNAM", struct.pack("<ff", -2048, -200)),
                (b"OFST", b"x" * 8), (b"CLSZ", b"y" * 8)]
        got = dict((s, d) for s, d in worldgates.remap_world_subs(subs, 1, 3) if s != b"BNAM")
        bn = [d for s, d in worldgates.remap_world_subs(subs, 1, 3) if s == b"BNAM"]
        self.assertEqual(bn, [I(0x03000801), I(0x001CBD6A)])
        self.assertEqual(got[b"XLCN"], I(0x03000802))
        self.assertEqual(got[b"CNAM"], I(0x0024E982))
        self.assertEqual(struct.unpack_from("<II", got[b"RNAM"], 8)[0], 0x03036AA6)
        self.assertEqual(struct.unpack_from("<I", got[b"RNAM"], 16)[0], 0x00001234)
        self.assertNotIn(b"OFST", got)
        self.assertNotIn(b"CLSZ", got)

    def test_xtel_layout(self):
        x = worldgates.xtel(0x04000803, (1.0, 2.0, 3.0), (0.0, 0.0, 1.5), 0)
        self.assertEqual(len(x), 36)
        self.assertEqual(struct.unpack("<I3f3fII", x)[0], 0x04000803)
        self.assertEqual(x[-4:], bytes(4))


GATE_MAIN = {"src": "01B1F1:Skyrim.esm", "edid": "WRDoorMainGate01", "pos": [19312.0, -7424.0, -3520.0],
             "rot": [0, 0, 3.14], "xtel": {"door": "01B1F3:Skyrim.esm", "pos": [19516.0, -7428.0, -3640.0],
                                           "rot": [0, 0, 1.5708], "flags": 0}}
GATE_CITY = {"src": "01B1F3:Skyrim.esm", "edid": "WRDoorMainGate01", "pos": [19367.0, -7433.0, -3547.0],
             "rot": [0, 0, 0], "xtel": {"door": "01B1F1:Skyrim.esm", "pos": [19244.0, -7427.0, -3595.0],
                                        "rot": [0, 0, -1.5708], "flags": 0}}


def build_fixture(d):
    """Tamriel (exterior + planet plugin) and one city, staged as our builds stage them."""
    main, city = os.path.join(d, "skyrim_all"), os.path.join(d, "sky_whiterunworld")
    os.makedirs(main)
    os.makedirs(city)
    stat = (b"STAT", [(b"EDID", Z("SKY_WRDoorMainGate01")), (b"OBND", struct.pack("<6f", -1, -2, -3, 1, 2, 3)),
                      (b"ODTY", bytes(4)), (b"MODL", Z("skyrim\\architecture\\whiterun\\wrdoormaingate01.nif"))],
            0x01001ECD)
    world_plugin(os.path.join(main, "SkyrimTerrainTamriel.esm"), ["Starfield.esm"],
                 [stat, (b"LCTN", [(b"EDID", Z("SKY_TamrielLocation"))], 0x01000802)],
                 ([(b"EDID", Z("SKY_Tamriel")), (b"BNAM", I(0x01000801)), (b"XLCN", I(0x01000802)),
                   (b"OFST", b"o" * 4)], 0x01000803), ([(b"XCLC", bytes(12))], 0x01001CD6),
                 static=static_ref(0x01003CBA, 0x01001ECD, (275.9, -106.06, 334.7), 3.14159))
    # the planet plugin overrides the world and its persistent cell (make_planet.py)
    pndt = (b"PNDT", [(b"EDID", Z("NirnPlanetData")), (b"CNAM", struct.pack("<ddI", 0.785, -1.636, 0x01000803)),
                      (b"CNAM", b"\x02")], 0x02000800)
    world_plugin(os.path.join(main, "SkyrimTerrainTamriel_Mars.esm"), ["Starfield.esm", "SkyrimTerrainTamriel.esm"],
                 [pndt, (b"LCTN", [(b"EDID", Z("SNirn_PNirn_Surface"))], 0x02000803)],
                 ([(b"EDID", Z("SKY_Tamriel")), (b"BNAM", I(0x01000801)), (b"XLCN", I(0x01000802))], 0x01000803),
                 ([(b"XCLC", bytes(12))], 0x01001CD6))
    with open(os.path.join(main, "overlays_params.json"), "w") as fh:
        json.dump({"plugin": "SkyrimTerrainTamriel.esm", "mars": {"plugin": "SkyrimTerrainTamriel_Mars.esm"},
                   "overlays": [{"world": "SKY_Tamriel", "origin_cw_m": [0, 0], "height_offset_m": 385.0,
                                 "name": "Skyrim"}]}, fh)
    with open(os.path.join(main, "formids.json"), "w") as fh:
        json.dump({"plugin": "SkyrimTerrainTamriel.esm", "refs": {"01B1F1:Skyrim.esm": "003CBA"}}, fh)
    cstat = (b"STAT", [(b"EDID", Z("SKY_WRDoorMainGate01")), (b"MODL", Z("skyrim\\x.nif"))], 0x01000900)
    rnam = struct.pack("<hhI", 0, 0, 1) + I(0x01000AAE) + struct.pack("<hh", 0, 0)
    world_plugin(os.path.join(city, "SkyrimTerrainWhiterunWorld.esm"), ["Starfield.esm"],
                 [cstat, (b"LCTN", [(b"EDID", Z("SKY_WhiterunWorldLocation")), (b"PNAM", I(0x01AB2B))], 0x01000802)],
                 ([(b"EDID", Z("SKY_WhiterunWorld")), (b"BNAM", I(0x01000801)), (b"XLCN", I(0x01000802)),
                   (b"RNAM", rnam), (b"OFST", b"o" * 4)], 0x01000803), ([(b"XCLC", bytes(12))], 0x01000949),
                 static=static_ref(0x01000AAE, 0x01000900, (-123.3, -206.2, 334.3), 0.0))
    with open(os.path.join(city, "overlays_params.json"), "w") as fh:
        json.dump({"plugin": "SkyrimTerrainWhiterunWorld.esm",
                   "overlays": [{"world": "SKY_WhiterunWorld", "origin_cw_m": [400.0, 100.0], "height_offset_m": 385.0,
                                 "name": "Whiterun", "location": "SKY_WhiterunWorldLocation"}]}, fh)
    with open(os.path.join(city, "formids.json"), "w") as fh:
        json.dump({"plugin": "SkyrimTerrainWhiterunWorld.esm", "world_form_id": "000803",
                   "refs": {"01B1F3:Skyrim.esm": "000AAE"}}, fh)
    with open(os.path.join(city, "skyrim_source.json"), "w") as fh:
        json.dump({"summary": {"world": "WhiterunWorld"}}, fh)
    return main, city


def walk_records(path):
    out = []
    with fo4land.Plugin(path) as p:
        def walk(s, e, chain):
            for it in fo4land.iter_items(p.buf, s, e):
                if it[0] == "GRUP":
                    self_end = it[2]
                    assert self_end <= e
                    walk(it[1] + 24, it[2], chain + (it[4],))
                    continue
                typ, off, flags, fid = it
                out.append((typ, fid, flags, dict(fo4land.iter_subrecords(fo4land.record_data(p.buf, off))), chain))
        walk(p.body, len(p.buf), ())
        hedr = dict(fo4land.iter_subrecords(fo4land.record_data(p.buf, 0)))[b"HEDR"]
    return out, struct.unpack("<fII", bytes(hedr))


class GateTests(unittest.TestCase):
    def test_gates_both_ways(self):
        with tempfile.TemporaryDirectory() as d:
            main, city = build_fixture(d)
            out = os.path.join(d, "reg")
            with mock.patch.object(worldgates, "skyrim_gates", return_value=[{"main": GATE_MAIN, "city": GATE_CITY}]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(RW.main(["--main", main, "--world", city, "--out", out, "--skyrim", "x.esm"]), 0)
            pl = os.path.join(out, RW.PLUGIN)
            recs, (_v, count, nxt) = walk_records(pl)
            rep = json.load(open(os.path.join(out, "register_worlds.json")))
        self.assertEqual(count, len(recs))
        by = {(t, fid): (fl, s, ch) for t, fid, fl, s, ch in recs}
        self.assertEqual(len([r for r in recs if r[0] == b"PNDT"]), 1)
        doors = sorted(fid for t, fid, *_x in recs if t == b"DOOR")
        refs = {fid: (fl, s, ch) for t, fid, fl, s, ch in recs if t == b"REFR"}
        self.assertEqual(doors, [0x04000800, 0x04000801])
        self.assertEqual(fo4land.zstring(by[(b"DOOR", 0x04000800)][1][b"MODL"]),
                         "Meshes\\skyrim\\architecture\\whiterun\\wrdoormaingate01.nif")
        self.assertEqual(fo4land.zstring(by[(b"DOOR", 0x04000800)][1][b"FULL"]), "Whiterun")
        self.assertEqual(fo4land.zstring(by[(b"DOOR", 0x04000801)][1][b"FULL"]), "Skyrim")
        (fm, sm, chm), (fc, sc, chc) = refs[0x04000802], refs[0x04000803]
        self.assertTrue(fm & worldgates.PERSISTENT and fc & worldgates.PERSISTENT)
        self.assertEqual(chm, (0, 1, 6, 8))                       # WRLD > world children > cell children > persistent
        tm = struct.unpack("<I3f3fII", bytes(sm[b"XTEL"]))
        tc = struct.unpack("<I3f3fII", bytes(sc[b"XTEL"]))
        self.assertEqual(tm[0], 0x04000803)
        self.assertEqual(tc[0], 0x04000802)
        self.assertAlmostEqual(tm[1], 19516.0 / 70 - 400.0, places=3)       # landing in the city's frame
        self.assertAlmostEqual(tm[3], -3640.0 / 70 + 385.0, places=3)
        self.assertAlmostEqual(tc[1], 19244.0 / 70, places=3)               # landing in Tamriel's frame
        self.assertAlmostEqual(tc[6], -1.5708, places=4)
        self.assertEqual(struct.unpack("<3f", bytes(sm[b"DATA"])[:12])[0], np.float32(275.9))   # at the static
        self.assertEqual(struct.unpack("<I", bytes(sm[b"NAME"]))[0], 0x04000800)
        self.assertEqual(struct.unpack("<I", bytes(sc[b"NAME"]))[0], 0x04000801)
        # the worlds: Tamriel's from the planet plugin as is; the city's remapped to its master index (3)
        worlds = {fid: s for t, fid, _fl, s, _c in recs if t == b"WRLD"}
        self.assertEqual(set(worlds), {0x01000803, 0x03000803})
        self.assertEqual(bytes(worlds[0x03000803][b"XLCN"]), I(0x03000802))
        self.assertEqual(struct.unpack_from("<I", bytes(worlds[0x03000803][b"RNAM"]), 8)[0], 0x03000AAE)
        self.assertNotIn(b"OFST", worlds[0x03000803])
        cells = sorted(fid for t, fid, *_x in recs if t == b"CELL")
        self.assertEqual(cells, [0x01001CD6, 0x03000949])
        self.assertEqual(nxt, 0x804)                              # doors 800-801, refs 802-803
        self.assertEqual([(h["plugin"], h["local_id"]) for h in rep["hide"]],
                         [("SkyrimTerrainTamriel.esm", "003CBA"), ("SkyrimTerrainWhiterunWorld.esm", "000AAE")])
        self.assertEqual(rep["gates"][0]["main_ref"], "04000802")

    def test_only_the_world_list_cnam_changes(self):
        with tempfile.TemporaryDirectory() as d:
            main, city = build_fixture(d)
            recs, _masters, _rep = RW.plan(main, [city])
        pn = [s for t, _h, s, _f in recs if t == b"PNDT"][0]
        self.assertEqual([d for s, d in pn if s == b"CNAM"][1], b"\x02")

    def test_hide_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            main, city = build_fixture(d)
            data = os.path.join(d, "Data")
            os.makedirs(data)
            for src in (os.path.join(main, "SkyrimTerrainTamriel.esm"), os.path.join(city, "SkyrimTerrainWhiterunWorld.esm")):
                shutil.copy2(src, data)
            orig = open(os.path.join(data, "SkyrimTerrainTamriel.esm"), "rb").read()
            out = os.path.join(d, "reg")
            with mock.patch.object(worldgates, "skyrim_gates", return_value=[{"main": GATE_MAIN, "city": GATE_CITY}]), \
                    contextlib.redirect_stdout(io.StringIO()):
                RW.main(["--main", main, "--world", city, "--out", out, "--skyrim", "x.esm"])
            hide = json.load(open(os.path.join(out, "register_worlds.json")))["hide"]
            state = {"files": ["SkyrimTerrainWhiterunWorld.esm"], "hide": hide}
            with contextlib.redirect_stdout(io.StringIO()):
                DSC.hide(data, hide, state)
                flags, dd = DSC.ref_state(os.path.join(data, "SkyrimTerrainTamriel.esm"), 0x3CBA)
                self.assertTrue(flags & worldgates.DISABLED)
                self.assertAlmostEqual(struct.unpack("<3f", dd[:12])[2], np.float32(334.7) - 1000.0, places=3)
                cflags, _cd = DSC.ref_state(os.path.join(data, "SkyrimTerrainWhiterunWorld.esm"), 0xAAE)
                self.assertTrue(cflags & worldgates.DISABLED)
                self.assertEqual(list(state["restore"]), ["SkyrimTerrainTamriel.esm:003CBA"])   # not the city's
                self.assertTrue(os.path.exists(os.path.join(data, "SkyrimTerrainTamriel.esm.before_ref_overrides")))
                DSC.hide(data, hide, state)                                    # again: nothing changes
                # a staging whose plugin was hidden in place: register_worlds reads the static from its backup
                for ext in ("", ".before_ref_overrides"):
                    shutil.copy2(os.path.join(data, "SkyrimTerrainTamriel.esm" + ext),
                                 os.path.join(main, "SkyrimTerrainTamriel.esm" + ext))
                got = RW._ref_with_place(os.path.join(main, "SkyrimTerrainTamriel.esm"), 0x3CBA)
                self.assertFalse(got[0] & worldgates.DISABLED)
                left = DSC.restore_exterior(data, state)
            self.assertEqual(left, [])
            self.assertEqual(open(os.path.join(data, "SkyrimTerrainTamriel.esm"), "rb").read(), orig)


class PackTests(unittest.TestCase):
    def test_files_the_exterior_holds_are_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            for rel in ("Terrain/SKY_City.btd", "meshes/skyrim/a.nif", "meshes/skyrim/b.nif", "textures/t.dds"):
                p = os.path.join(d, "Data", *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(b"x" * 10)
            keep, skip = DSC.pack_plan(d, {"meshes\\skyrim\\a.nif", "textures\\t.dds"})
        self.assertEqual(sorted(r.replace("\\", "/") for r, _s in keep), ["Terrain/SKY_City.btd", "meshes/skyrim/b.nif"])
        self.assertEqual(skip, {"skipped": 2, "skipped_bytes": 20, "replaced": 0})

    def test_a_newer_version_of_an_exterior_file_is_packed(self):
        class Arc:                                   # stands in for ba2.Ba2: two general entries, one texture
            entries = [mock.Mock(kind="GNRL", unpacked=10), mock.Mock(kind="GNRL", unpacked=10),
                       mock.Mock(kind="DX10")]

            def read(self, i):
                return [b"x" * 10, b"y" * 10][i]
        arc = Arc()
        with tempfile.TemporaryDirectory() as d:
            for rel, body in (("meshes/skyrim/same.nif", b"x" * 10), ("meshes/skyrim/newer.nif", b"x" * 10),
                              ("meshes/skyrim/longer.nif", b"x" * 12), ("textures/t.dds", b"z")):
                p = os.path.join(d, "Data", *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(body)
            have = {"meshes\\skyrim\\same.nif": (arc, 0), "meshes\\skyrim\\newer.nif": (arc, 1),
                    "meshes\\skyrim\\longer.nif": (arc, 0), "textures\\t.dds": (arc, 2)}
            keep, skip = DSC.pack_plan(d, have)
        self.assertEqual(sorted(r.replace("\\", "/") for r, _s in keep),
                         ["meshes/skyrim/longer.nif", "meshes/skyrim/newer.nif"])
        self.assertEqual(skip, {"skipped": 2, "skipped_bytes": 11, "replaced": 2})


if __name__ == "__main__":
    unittest.main()
