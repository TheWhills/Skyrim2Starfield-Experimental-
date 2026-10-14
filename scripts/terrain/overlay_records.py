"""Overlay record fixes for the terrain experiments (docs/terrain/overlay-records.md): exp1d builder, overlay mask
writer and the offline check shared with make_exp2.py.

    python scripts/terrain/overlay_records.py exp1d --sf-data <Starfield Data> --out C:\\Modding\\staging\\terrain_exp1d
    dotnet run --project dotnet/TerrainExp1 -c Release -- <Starfield.esm> <out>      (reads <out>/exp1_params.json)
    python scripts/terrain/overlay_records.py check --out <staging dir>              (exp1d or exp2b)

A worldspace's own BTD applies only when it is an activated overlay on a planet. Compared with vanilla unique overlays
the first experiment plugins lacked: a vanilla-sized SFBK FNAM (one u16 per BTD cell), a Location (keyword
LocTypeOverlay, parent = the planet's surface location) on the WRLD's XLCN, and an overlay mask
(textures/terrain/overlaymasks/<edid>.dds, BC4, 100 px per cell). exp1d is experiment 1's World01 with those three
fixes (Relative alignment, as LC172World) plus the Mars registration plugin and a persistent anchor ref.

Everything is written to the staging folder (derived game data never enters the repo); nothing is deployed.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))
sys.path.insert(0, HERE)
from fo4sf import ba2, btd, fo4land, overlay  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402

TEXCONV = r"C:\Modding\tools\xedit\Edit Scripts\Texconvx64.exe"
LOC_TYPE_OVERLAY = 0x2CA99D         # KYWD LocTypeOverlay (Starfield.esm)
MARS_SURFACE = 0x01B736             # LCTN SSol_PMars_Surface: parent of LC172WorldLocation
MARS_PNDT = 0x03F59A                # PNDT MarsPlanetData
XMARKER = 0x00003B                  # STAT XMarker
PERSISTENT = 0x400
ANCHOR_ID = 0x800                   # the builders give the anchor the plugin's first FormID
# Load-order byte of the experiment plugin at run time. Plugins.txt [FO4TerrainExpN.esm, FO4TerrainExpN_Mars.esm,
# FO4Port.esm] most likely makes it 02 (unverified: depends on the official masters loaded first). The runner falls
# back to spawn_local when prid fails.
ANCHOR_LOAD_BYTE = "02"
PLAN_KEYS = ("coc", "label", "anchor", "spawn_local", "drop_z", "settle_ms", "points")


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def mask_rel(world):
    """Staged path of a worldspace's overlay mask (the --pack installer puts Data\\textures into Main.ba2)."""
    return f"Data/textures/terrain/overlaymasks/{world.lower()}.dds"


def anchor_ref(form_id=ANCHOR_ID, load_byte=ANCHOR_LOAD_BYTE):
    return f"{load_byte}{form_id:06X}"


# ---------------------------------------------------------------------------------------------------------- mask
def write_mask(out, world, n, writer="texconv", texconv=TEXCONV):
    """Ring mask (0 inside, 255 on the outer cell ring) for an n x n-cell BTD as a BC4 DDS without mips, legacy
    header (like the vanilla masks). writer 'texconv' (default) or 'builtin' (overlay.dds_bc4, lossless for 0/255)."""
    img = overlay.mask_array(n)
    dst = os.path.join(out, *mask_rel(world).split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if writer == "builtin":
        data = overlay.dds_bc4(img)
    else:
        from PIL import Image
        if not os.path.isfile(texconv):
            sys.exit(f"texconv not found at {texconv} (or use --mask-writer builtin)")
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, world.lower() + ".png")
            Image.fromarray(img, "L").save(png)
            r = subprocess.run([texconv, "-nologo", "-y", "-f", "BC4_UNORM", "-m", "1", "-o", tmp, png],
                               capture_output=True, text=True)
            made = os.path.join(tmp, world.lower() + ".dds")
            if r.returncode != 0 or not os.path.isfile(made):
                sys.exit("texconv failed:\n" + r.stdout + r.stderr)
            data = read_bytes(made)
    with open(dst, "wb") as f:
        f.write(data)
    return mask_report(out, world, n)


def mask_report(out, world, n):
    data = read_bytes(os.path.join(out, *mask_rel(world).split("/")))
    info = overlay.dds_info(data)
    differ, worst = overlay.mask_check(overlay.bc4_decode(data), n)
    return {"file": mask_rel(world), "bytes": len(data), "width": info["width"], "height": info["height"],
            "mips": info["mips"], "format": info["format"], "legacy_header": info["data_offset"] == 128,
            "fourcc": data[84:88].decode("latin1"), "pixels_differ": differ, "max_diff": worst}


# ---------------------------------------------------------------------------------------------------------- raw walk
def walk_plugin(path):
    """Every record of a plugin, raw (independent of Mutagen): masters and [{sig, fid, flags, fields}]."""
    buf = read_bytes(path)
    hsize = struct.unpack_from("<I", buf, 4)[0]
    masters = [fo4land.zstring(d) for s, d in fo4land.iter_subrecords(buf[24:24 + hsize]) if s == b"MAST"]
    recs = []

    def walk(start, end):
        for item in fo4land.iter_items(buf, start, end):
            if item[0] == "GRUP":
                walk(item[1] + 24, item[2])
                continue
            typ, off, flags, fid = item
            recs.append({"sig": typ.decode(), "fid": fid, "flags": flags,
                         "fields": list(fo4land.iter_subrecords(fo4land.record_data(buf, off)))})
    walk(24 + hsize, len(buf))
    return {"bytes": len(buf), "masters": masters, "records": recs}


def field(rec, sig, default=None):
    return next((d for s, d in rec["fields"] if s == sig.encode()), default)


def edid(rec):
    d = field(rec, "EDID")
    return fo4land.zstring(d) if d is not None else ""


def overlay_block_ref(wrld):
    """The SFBK FormID inside the WRLD's BGSWorldSpaceOverlay_Component (the first BNAM after that BFCB)."""
    inside = False
    for s, d in wrld["fields"]:
        if s == b"BFCB":
            inside = fo4land.zstring(d) == "BGSWorldSpaceOverlay_Component"
        elif s == b"BFCE":
            inside = False
        elif inside and s == b"BNAM":
            return struct.unpack("<I", d)[0]
    return None


def pndt_entries(rec):
    """PNDT CNAM master-worldspace entries: (f64, f64, WRLD FormID) each 20 bytes (the long CNAM, not the 1-byte one)."""
    d = next((d for s, d in rec["fields"] if s == b"CNAM" and len(d) % 20 == 0 and len(d) >= 20), b"")
    return [struct.unpack_from("<ddI", d, i) for i in range(0, len(d), 20)]


# ---------------------------------------------------------------------------------------------------------- check
def check_staging(out, prm, plan, vanilla_mars_entries=None):
    """Offline verification of a staged overlay experiment. Returns (ok, report)."""
    checks, rep = [], {}

    def need(cond, what):
        checks.append([what, bool(cond)])

    n = prm["n"]
    world = prm["world"]
    data = read_bytes(os.path.join(out, *prm["btd_file"].split("/")))
    t = btd.read(data)
    dec = t.heights_m()
    step = (t.hmax - t.hmin) / 65535.0
    o = tg.grid_origin(n)
    need(t.ncx == n and t.ncy == n, f"BTD {t.ncx} x {t.ncy} cells = DNAM {n} x {n}")

    # plan: runner format, points decoded from the written BTD (worst of bilinear and both triangle splits)
    pts = []
    for w in plan:
        need(all(k in w for k in PLAN_KEYS), f"plan entry {w.get('coc')} has {', '.join(PLAN_KEYS)}")
        need(re.fullmatch(r"[0-9A-Fa-f]{8}", str(w.get("anchor", {}).get("ref", ""))), "anchor.ref is 8 hex digits")
        need(len(w.get("spawn_local", [])) == 3, "spawn_local is [x, y, z]")
        sx, sy, sz = w["spawn_local"]
        g = tg.point_interp(dec, o, o, tg.SF_STEP_M, sx, sy)
        need(max(abs(v - sz) for v in g.values()) <= step, f"spawn_local z {sz} = ground under the COC marker")
        ax, ay, az = w["anchor"]["local"]
        g = tg.point_interp(dec, o, o, tg.SF_STEP_M, ax, ay)
        need(max(abs(v - az) for v in g.values()) <= step, f"anchor local z {az} = ground under the anchor")
        need(w["drop_z"] > max(p["expect"] for p in w["points"]) + 10, "drop_z above every point")
        for p in w["points"]:
            hs = tg.point_interp(dec, o, o, tg.SF_STEP_M, p["x"], p["y"])
            e = max(abs(v - p["expect"]) for v in hs.values())
            pts.append({"label": p["label"], "x": p["x"], "y": p["y"], "expect": p["expect"],
                        "decoded": {k: round(v, 4) for k, v in hs.items()}, "error_mm": round(e * 1000, 3)})
            need(e <= step, f"point {p['label']}: decoded within one quantisation step ({step * 1000:.2f} mm)")
    rep["points"] = pts

    # plugin
    d = walk_plugin(os.path.join(out, prm["plugin"]))
    own = len(d["masters"]) << 24
    recs = d["records"]
    by_fid = {r["fid"]: r for r in recs}
    wr = [r for r in recs if r["sig"] == "WRLD" and edid(r) == world]
    need(len(wr) == 1, f"one WRLD {world}")
    w = wr[0]
    xlcn = field(w, "XLCN")
    loc = by_fid.get(struct.unpack("<I", xlcn)[0]) if xlcn else None
    need(loc is not None and loc["sig"] == "LCTN", "WRLD XLCN -> an LCTN in the plugin")
    kw = list(struct.unpack(f"<{len(field(loc, 'KWDA', b'')) // 4}I", field(loc, "KWDA", b""))) if loc else []
    parent = struct.unpack("<I", field(loc, "PNAM"))[0] if loc and field(loc, "PNAM") else None
    need(LOC_TYPE_OVERLAY in kw, "LCTN keyword LocTypeOverlay 002CA99D")
    need(parent == MARS_SURFACE, "LCTN parent SSol_PMars_Surface 0001B736")
    sfbk = by_fid.get(overlay_block_ref(w))
    need(sfbk is not None and sfbk["sig"] == "SFBK", "WRLD overlay component -> SFBK in the plugin")
    fn = field(sfbk, "FNAM", b"")
    dnam = list(struct.unpack("<2I", field(sfbk, "DNAM")))
    inam = field(sfbk, "INAM", b"\0")[0]
    hnam = struct.unpack("<h", field(sfbk, "HNAM", b"\0\0"))[0]
    exact, cells, worst = overlay.fnam_match(fn, t.heights_raw)
    need(fo4land.zstring(field(sfbk, "ANAM", b"")) == prm["btd_path"], f"SFBK ANAM {prm['btd_path']}")
    need(dnam == [n, n], f"SFBK DNAM {dnam}")
    need(len(fn) == n * n * 2, f"SFBK FNAM {len(fn)} B = cells x 2 ({n * n * 2})")
    need(exact == cells, f"SFBK FNAM = SW-corner raw height of every BTD cell ({exact}/{cells})")
    want_inam = 1 if prm["alignment"] == "absolute" else 0
    need(inam == want_inam and hnam == prm["hnam"], f"SFBK INAM {inam} ({prm['alignment']}), HNAM {hnam}")
    anchors = [r for r in recs if r["sig"] == "REFR" and edid(r) == prm["anchor"]["edid"]]
    need(len(anchors) == 1, f"one anchor REFR {prm['anchor']['edid']}")
    a = anchors[0]
    ar = fo4land.parse_ref(a["fields"])
    need(ar["base"] == XMARKER, "anchor base XMarker 0000003B")
    need(a["flags"] & PERSISTENT, "anchor has the persistent flag")
    need(a["fid"] == own | ANCHOR_ID and prm["anchor"]["ref"][2:].upper() == "%06X" % ANCHOR_ID,
         f"anchor FormID {a['fid']:08X} matches plan ref {prm['anchor']['ref']}")
    need(max(abs(p - q) for p, q in zip(ar["pos"], prm["anchor"]["local"])) < 1e-3, f"anchor at {ar['pos']}")
    for wplan in plan:
        need(wplan["anchor"]["ref"] == prm["anchor"]["ref"] and wplan["anchor"]["local"] == prm["anchor"]["local"],
             "plan anchor = plugin anchor")
    coc = [r for r in recs if r["sig"] == "CELL" and edid(r) == prm["coc"]]
    need(len(coc) == 1, f"COC cell {prm['coc']}")
    rep["plugin"] = {"file": prm["plugin"], "bytes": d["bytes"], "masters": d["masters"],
                     "records": {s: sum(1 for r in recs if r["sig"] == s) for s in sorted({r["sig"] for r in recs})},
                     "wrld": {"fid": "%08X" % w["fid"], "edid": world, "xlcn": "%08X" % struct.unpack("<I", xlcn)[0] if xlcn else None},
                     "lctn": {"fid": "%08X" % loc["fid"], "edid": edid(loc), "keywords": ["%08X" % k for k in kw],
                              "parent": "%08X" % parent if parent is not None else None} if loc else None,
                     "sfbk": {"fid": "%08X" % sfbk["fid"], "edid": edid(sfbk), "ANAM": fo4land.zstring(field(sfbk, "ANAM", b"")),
                              "DNAM": dnam, "ENAM": list(struct.unpack("<2f", field(sfbk, "ENAM"))), "FNAM_bytes": len(fn),
                              "FNAM_first": list(np.frombuffer(fn, "<u2")[:6].tolist()), "INAM": inam, "HNAM": hnam},
                     "anchor": {"fid": "%08X" % a["fid"], "edid": edid(a), "base": "%08X" % ar["base"], "flags": "%08X" % a["flags"],
                                "pos": ar["pos"]}}

    # Mars registration plugin
    if prm.get("mars"):
        m = walk_plugin(os.path.join(out, prm["mars"]["plugin"]))
        pl = [r for r in m["records"] if r["sig"] == "PNDT"]
        need(len(pl) == 1 and pl[0]["fid"] == MARS_PNDT and edid(pl[0]) == "MarsPlanetData",
             "Mars plugin overrides PNDT MarsPlanetData 0003F59A")
        need(m["masters"][:1] == ["Starfield.esm"] and prm["plugin"] in m["masters"], f"Mars plugin masters {m['masters']}")
        idx = m["masters"].index(prm["plugin"]) << 24 if prm["plugin"] in m["masters"] else -1
        ents = pndt_entries(pl[0]) if pl else []
        ours = [e for e in ents if e[2] == idx | (w["fid"] & 0xFFFFFF)]
        need(len(ours) == 1, "PNDT CNAM has one entry for the experiment WRLD")
        if vanilla_mars_entries is not None:
            need(len(ents) == vanilla_mars_entries + 1, f"PNDT CNAM {len(ents)} entries = vanilla {vanilla_mars_entries} + 1")
        rep["mars"] = {"file": prm["mars"]["plugin"], "bytes": m["bytes"], "masters": m["masters"], "entries": len(ents),
                       "ours": [{"raw_f64_0": e[0], "raw_f64_1": e[1], "wrld": "%08X" % e[2], "index": ents.index(e)} for e in ours],
                       "params": {"latitude": prm["mars"]["latitude"], "longitude": prm["mars"]["longitude"]}}

    # overlay mask
    mk = mask_report(out, world, n)
    need(mk["format"] == "BC4" and mk["mips"] == 1 and mk["width"] == mk["height"] == n * 100,
         f"mask {mk['file']} BC4 {mk['width']} x {mk['height']} px, {mk['mips']} mip")
    need(mk["pixels_differ"] == 0, "mask decodes to 0 inside, 255 on the outer cell ring")
    rep["mask"] = mk
    rep["btd"] = {"file": prm["btd_file"], "bytes": len(data), "cells": [t.ncx, t.ncy], "range": [t.hmin, t.hmax],
                  "step_mm": round(step * 1000, 4)}
    rep["checks"] = checks
    ok = all(c[1] for c in checks)
    rep["pass"] = ok
    return ok, rep


def vanilla_mars_count(sf_data):
    """Number of PNDT CNAM entries of vanilla MarsPlanetData (raw read of Starfield.esm; None if not readable)."""
    p = os.path.join(sf_data, "Starfield.esm") if sf_data else ""
    if not os.path.isfile(p):
        return None
    buf = read_bytes(p)
    off = 24 + struct.unpack_from("<I", buf, 4)[0]
    for item in fo4land.iter_items(buf, off, len(buf)):
        if item[0] == "GRUP" and item[3] == b"PNDT":
            for r in fo4land.iter_items(buf, item[1] + 24, item[2]):
                if r[0] != "GRUP" and r[3] == MARS_PNDT:
                    rec = {"fields": list(fo4land.iter_subrecords(fo4land.record_data(buf, r[1])))}
                    return len(pndt_entries(rec))
    return None


def run_check(out, params_name, sf_data=None):
    prm = json.load(open(os.path.join(out, params_name)))
    plan = json.load(open(os.path.join(out, "plan.json")))
    ok, rep = check_staging(out, prm, plan, vanilla_mars_count(sf_data))
    for what, good in rep["checks"]:
        print(("  ok   " if good else "  FAIL ") + what)
    for p in rep["points"]:
        print(f"  {p['label']:<22} expect {p['expect']:9.4f} decoded {p['decoded']['bilinear']:9.4f} error {p['error_mm']:7.3f} mm")
    with open(os.path.join(out, "offline_check.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    print(json.dumps({k: rep[k] for k in ("plugin", "mars", "mask", "btd") if k in rep}, indent=1))
    print("CHECK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ---------------------------------------------------------------------------------------------------------- exp1d
EXP1_PLUGIN = "FO4TerrainExp1.esm"
EXP1_WORLD = "FO4TX_World01"
EXP1_COC = "FO4TX_W01Spawn"


def exp1d(a):
    import make_exp1_btd as m1
    out = a.out
    ref = btd.read(ba2.Ba2(os.path.join(a.sf_data, "Starfield - Terrain01.ba2")).read("terrain/landingoverlay01.btd"))
    n = m1.N
    quad = np.tile(ref.quad_map[0:1, 0:1, :], (n * 2, n * 2, 1))
    weights = np.tile(ref.weights[:128, :128], (n, n))
    d = m1.PADS["FO4TX_World01.btd"]
    h = m1.heights(d)
    t = btd.Btd(6, m1.HMIN, m1.HMAX, list(ref.ltex), btd.quantize(h, m1.HMIN, m1.HMAX), weights, quad)
    data = btd.write(t)
    rel = "Data/Terrain/FO4TX_World01.btd"
    os.makedirs(os.path.join(out, "Data", "Terrain"), exist_ok=True)
    with open(os.path.join(out, *rel.split("/")), "wb") as f:
        f.write(data)
    back = btd.read(data)
    ground = 10.0
    spawn_local = [50.0, 50.0, ground]                # COC marker (50, 50, 12) of experiment 1, ground 10 m
    anchor = {"edid": "FO4TX_W01Anchor", "local": [50.0, 50.0, ground], "ref": anchor_ref()}
    prm = {"plugin": EXP1_PLUGIN, "world": EXP1_WORLD, "coc": EXP1_COC, "btd_path": "Data\\TERRAIN\\FO4TX_World01.btd",
           "btd_file": rel, "n": n, "cell_min": -(n // 2), "cell_max": n - n // 2 - 1,
           "fnam": overlay.fnam_values(back.heights_raw), "alignment": a.alignment, "hnam": a.hnam, "location": True,
           "anchor": anchor, "mars": {"plugin": "FO4TerrainExp1_Mars.esm", "latitude": 1.2, "longitude": 0.2},
           "mask": mask_rel(EXP1_WORLD)}
    e = {"ground": ground, "padA": 10.0 + d, "padB": 10.0 + d / 2, "pitC": 5.0}
    points = [{"label": "ground", "x": -60.0, "y": -60.0, "expect": e["ground"]},
              {"label": "padA", "x": 30.0, "y": 30.0, "expect": e["padA"]},
              {"label": "padB", "x": 70.0, "y": 30.0, "expect": e["padB"]},
              {"label": "pitC", "x": 30.0, "y": 70.0, "expect": e["pitC"]},
              {"label": "padA_edge_in", "x": 39.0, "y": 30.0, "expect": e["padA"]},
              {"label": "padA_edge_out", "x": 41.0, "y": 30.0, "expect": e["ground"]}]
    plan = [{"coc": EXP1_COC,
             "label": f"terrain exp1d: World01 + overlay records (FNAM {n * n} values, Location, mask; "
                      f"{a.alignment}), registered on Mars",
             "anchor": {"ref": anchor["ref"], "local": anchor["local"]}, "spawn_local": spawn_local,
             "drop_z": 80.0, "settle_ms": 8000, "points": points}]
    mk = write_mask(out, EXP1_WORLD, n, a.mask_writer)
    for name, obj in (("exp1_params.json", prm), ("plan.json", plan)):
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1)
    readme(out, "exp1d", prm, plan[0], mk, [
        "Experiment 1 World01 (flat 10 m ground, pad A 35 m, pad B 22.5 m, pit C 5 m) with the overlay record fixes:",
        f"SFBK FNAM = {n * n} raw cell-corner heights ({n * n * 2} B, was 16 B), Location FO4TX_World01Location",
        "(LocTypeOverlay, parent SSol_PMars_Surface), overlay mask, alignment " + a.alignment + ".",
        "Compare with exp1c (same BTD, same Mars registration, no fixes)."])
    print(f"exp1d staged in {out}: BTD {len(data):,} B, FNAM {len(prm['fnam'])} values, mask {mk['bytes']:,} B "
          f"({mk['pixels_differ']} px differ); next: dotnet run --project dotnet/TerrainExp1 -c Release -- "
          f"<Starfield.esm> {out}")


def readme(out, name, prm, plan, mk, intro):
    pl = [prm["plugin"]] + ([prm["mars"]["plugin"]] if prm.get("mars") else [])
    base = os.path.splitext(prm["plugin"])[0]
    lines = [f"Terrain {name} (Claude, 2026-10-11). NOT deployed. Recipe: docs/terrain/overlay-records.md",
             "(branch claude/terrain-overlay-records)."] + intro + [
        "",
        "Install (game closed). The runner does it:",
        f"  scripts/game/exp_install.py install --exp-dir <this folder> --starfield <game> --plugins {','.join(pl)} --pack",
        f"  --pack puts every folder under Data\\ (Terrain, textures) into \"{base} - Main.ba2\" (loose files are not read).",
        "By hand: build that BA2 with Archive2 from Data\\ (root = Data), copy it and the esm files to Starfield\\Data and add",
        "to Plugins.txt, in this order, before FO4Port.esm:  " + "  ".join("*" + p for p in pl),
        "",
        "In game (test save), console:",
        "  tgm",
        f"  coc {prm['coc']}",
        f"  the anchor (persistent XMarker {prm['anchor']['edid']}, local {prm['anchor']['local']}):",
        f"    prid {prm['anchor']['ref']}   then  getpos x / getpos y / getpos z   -> A",
        f"    {prm['anchor']['ref'][:2]} is the assumed load-order byte of {prm['plugin']}; if prid fails, find the real one",
        "    (e.g. click a placed object of the plugin in the console) or use the arrival instead:",
        f"  player.getpos x/y/z right after the coc -> S; the COC marker stands at local {plan['spawn_local']} (ground).",
        "  offset O = A - anchor local  (or S - spawn_local). Alignment " + prm["alignment"] +
        (": if Absolute means world z = BTD height + HNAM (hypothesis), the Z offset is 0" if prm["alignment"] == "absolute" else
         ": the Z offset is whatever the merge applies") + ".",
        f"  For every point: player.setpos x <x + O.x> / player.setpos y <y + O.y> / player.setpos z <{plan['drop_z']:g} + O.z>,",
        f"  wait {plan['settle_ms'] / 1000:g} s, player.getpos z -> expect + O.z (+-0.5 m):",
    ]
    for p in plan["points"]:
        lines.append(f"    {p['label']:<22} x {p['x']:>10.4f}  y {p['y']:>10.4f}  -> {p['expect']:.4f}")
    lines += [
        "  Screenshots at the spawn (north, east): planet ground or our heights? rocks inside the mask?",
        "",
        "Files: " + ", ".join(pl) + f", {prm['btd_file']}, {mk['file']} (BC4 {mk['width']} px, 0 inside, 255 outer ring),",
        "plan.json (runner input, points in the worldspace's own frame), offline_check.json (raw record walk, BTD decode).",
        "Uninstall: exp_install.py uninstall.",
    ]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("exp1d", "check"))
    ap.add_argument("--out", required=True, help="staging folder")
    ap.add_argument("--sf-data", help="Starfield Data folder (exp1d: terrain BA2 for the LTEX template; check: "
                                      "Starfield.esm for the vanilla Mars entry count)")
    ap.add_argument("--alignment", choices=("relative", "absolute"), default="relative")
    ap.add_argument("--hnam", type=int, default=0)
    ap.add_argument("--mask-writer", choices=("texconv", "builtin"), default="texconv")
    ap.add_argument("--params", help="params file for check (default: exp1_params.json or exp2_params.json)")
    a = ap.parse_args()
    if a.cmd == "exp1d":
        if not a.sf_data:
            sys.exit("--sf-data is required for exp1d")
        os.makedirs(a.out, exist_ok=True)
        return exp1d(a)
    name = a.params or next((p for p in ("exp1_params.json", "exp2_params.json")
                             if os.path.exists(os.path.join(a.out, p))), None)
    if not name:
        sys.exit("no params file in " + a.out)
    return run_check(a.out, name, a.sf_data)


if __name__ == "__main__":
    sys.exit(main())
