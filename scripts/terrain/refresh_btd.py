"""New ground-texture layers in an already staged exterior, its heights untouched (2026-11-21, owner: "spots in the
terrain that are supposed to fade or have a snow texture or blend ... got off like squares into each other").

    python -I scripts\\terrain\\refresh_btd.py recompute --staging C:\\Modding\\staging\\skyrim_all --skyrim "$sky\\Skyrim.esm" --sf-data "$sf\\Data"

recompute (2026-11-21; the installed exterior was built before builds kept their command): the texture part of every
staged BTD again from Skyrim.esm, with the staging's own choices (ltex_mapping.json, the ltex_overrides in
overlays_params.json, each BTD's LTEX table, the tiles in overlays_params.json), heights untouched. First a spot check:
a sample of bands encoded "solid" (what the staging was built with) must match the staged BTD (--min-match, default
0.98 of samples drawing the same texture), else nothing is written: the inputs are not the build's. Without
ltex_mapping.json (the October build kept none) the mapping is learnt off the installed BTDs (infer_mapping).

rebuild: runs the staging's own build (its build_command.txt) again into --fresh, with --ltex-blend / --ltex-warp
(default noise / 3.5: landtex "noise") added last so they win. Nothing in --staging is written.
splice: every .btd of the staging takes the texture part (LTEX table, quadrant map, sample weights) of the fresh BTD at
the same path, and keeps its own heights, height range and everything else (plugins, FormIDs, objects, grass, LOD,
water, the planet). A BTD whose fresh twin has another size or LTEX table is left alone and reported. Then reinstall
the staging (deploy_skyrim_exterior.py uninstall, install; tools\\owner\\terrain_blend.ps1 does all of it).
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from fo4sf import btd  # noqa: E402


BACKUP = "btd_before_blend"     # recompute: the staged BTDs as built, copied here the first time they are rewritten


def build_args(staging, fresh, blend="noise", warp=1.5):
    """The staging's make_skyrim_overlay.py build arguments (from "build" on), with --out fresh and the blend options
    appended (argparse: the last one wins)."""
    from make_skyrim_overlay import split_cmdline
    path = os.path.join(staging, "build_command.txt")
    if not os.path.isfile(path):
        sys.exit(f"no {path}: not a make_skyrim_overlay.py build folder")
    with open(path, encoding="utf-8") as fh:
        args = split_cmdline(fh.read().strip())
    k = next((i for i, x in enumerate(args) if x == "build"), None)
    if k is None:
        sys.exit(f"{path} is not a build command")
    return args[k:] + ["--out", fresh, "--ltex-blend", blend, "--ltex-warp", str(warp)]


def btd_files(root):
    """{path relative to root\\Data (lower case, "\\\\"): absolute path} of every .btd under root\\Data."""
    out = {}
    data = os.path.join(root, "Data")
    for dirpath, _dirs, files in os.walk(data):
        for f in files:
            if f.lower().endswith(".btd"):
                p = os.path.join(dirpath, f)
                out[os.path.relpath(p, data).replace("/", "\\").lower()] = p
    return out


def splice_one(old: bytes, new: bytes):
    """(bytes, None) with old's heights and new's textures, or (None, why) when they do not fit together."""
    a, b = btd.read(old), btd.read(new)
    if a.heights_raw.shape != b.heights_raw.shape:
        return None, f"size {a.heights_raw.shape} vs fresh {b.heights_raw.shape}"
    if list(a.ltex) != list(b.ltex):
        return None, f"LTEX table differs ({len(a.ltex)} vs fresh {len(b.ltex)} entries)"
    out = btd.Btd(a.version, a.hmin, a.hmax, list(a.ltex), a.heights_raw, b.weights, b.quad_map)
    return btd.write(out), None


def cmd_splice(a):
    old, new = btd_files(a.staging), btd_files(a.fresh)
    if not old:
        sys.exit(f"no .btd under {a.staging}\\Data")
    done, kept, missing = 0, [], []
    for rel, p in sorted(old.items()):
        q = new.get(rel)
        if q is None:
            missing.append(rel)
            continue
        with open(p, "rb") as fh:
            ob = fh.read()
        with open(q, "rb") as fh:
            nb = fh.read()
        data, why = splice_one(ob, nb)
        if data is None:
            kept.append(f"{rel}: {why}")
            continue
        before = btd.read(ob)
        after = btd.read(data)
        assert np.array_equal(before.heights_raw, after.heights_raw)          # heights exactly as installed
        if not a.dry_run:
            with open(p, "wb") as fh:
                fh.write(data)
        done += 1
    print(f"{'would splice' if a.dry_run else 'spliced'} {done} of {len(old)} BTDs (heights kept, textures from "
          f"{a.fresh}); {len(missing)} with no fresh twin, {len(kept)} left alone")
    for m in missing[:10]:
        print(f"  no fresh twin: {m}")
    for k in kept[:10]:
        print(f"  left alone: {k}")
    return 0 if done else 1


def cmd_rebuild(a):
    if os.path.abspath(a.fresh).lower() == os.path.abspath(a.staging).lower():
        sys.exit("--fresh must be another folder than --staging")
    args = build_args(a.staging, a.fresh, a.blend, a.warp)
    cmd = [sys.executable, "-I", os.path.join(HERE, "make_skyrim_overlay.py")] + args
    print("running:", subprocess.list2cmdline(cmd))
    if a.dry_run:
        return 0
    return subprocess.call(cmd)


def staged_textures(staging, skyrim_esm, sf_data, world="Tamriel", consistent_edges=True):
    """(planes {form id: uint8 vertex grid}, ox, oy, sp, Starfield LTEX names {form id: name}) from Skyrim.esm and the
    staging's own mapping (ltex_mapping.json) and converted-ground slots (overlays_params.json ltex_overrides)."""
    import json
    from fo4sf import landtex, skyrimland
    from fo4sf import terrain_grid as tg
    with open(os.path.join(staging, "ltex_mapping.json"), encoding="utf-8") as fh:
        saved = json.load(fh)
    with open(os.path.join(staging, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    sf = landtex.starfield_ltex(os.path.join(sf_data, "Starfield.esm"))
    overrides = prm.get("ltex_overrides")
    if overrides is None and os.path.exists(os.path.join(staging, "skyrim_source.json")):
        with open(os.path.join(staging, "skyrim_source.json"), encoding="utf-8") as fh:
            overrides = (json.load(fh).get("land_textures") or {}).get("ltex_overrides")
    for o in overrides or []:
        fid = o["form_id"]
        sf["SKYG_" + o["skyrim"]] = int(fid, 16) if isinstance(fid, str) else int(fid)
    mapping = {"skyrim": {int(k): v for k, v in saved["skyrim"].items()}}
    missing = sorted({v["starfield"] for v in mapping["skyrim"].values() if v["starfield"] not in sf})
    if missing:
        sys.exit(f"ltex_mapping.json names Starfield LTEX not found: {missing[:8]}")
    land = skyrimland.SkyrimLand(skyrim_esm, world)
    cells, _ltex = landtex.read_world_textures(skyrim_esm, land.land_source, {})
    cells_t, used = landtex.target_cells(cells, mapping, sf)
    default_sf = sf[mapping["skyrim"][landtex.DEFAULT_LTEX]["starfield"]]
    used = sorted(set(used) | {default_sf})
    x0, x1, y0, y1 = land.grid_bounds
    planes = {fid: np.rint(np.clip(landtex.merged_grid(cells_t, fid, x0, x1, y0, y1, 1.0 if fid == default_sf else 0.0,
                                                       consistent_edges), 0, 1) * 255).astype(np.uint8) for fid in used}
    return planes, x0 * tg.FO4_CELL_UNITS, y0 * tg.FO4_CELL_UNITS, tg.FO4_VERTEX_UNITS, {v: k for k, v in sf.items()}


def sample_rows(size, bands):
    """Every k-th 64-row band start of a size x size BTD, about `bands` of them."""
    starts = list(range(0, size, 64))
    return starts[::max(1, len(starts) // max(1, bands))]


def skyrim_at(cells, xs_m, ys_m):
    """(Skyrim LTEX with the most weight at the nearest LAND vertex, that weight) [len(ys), len(xs)] at CW positions
    (metres; Skyrim units = metres x 70); -1 / 0 where Skyrim has no texture data."""
    from fo4sf import terrain_grid as tg
    xu = np.asarray(xs_m, np.float64) * tg.UNITS_PER_METRE
    yu = np.asarray(ys_m, np.float64) * tg.UNITS_PER_METRE
    cx = np.floor(xu / tg.FO4_CELL_UNITS).astype(np.int64)
    cy = np.floor(yu / tg.FO4_CELL_UNITS).astype(np.int64)
    vj = np.rint((xu - cx * tg.FO4_CELL_UNITS) / tg.FO4_VERTEX_UNITS).astype(np.int64).clip(0, 32)
    vi = np.rint((yu - cy * tg.FO4_CELL_UNITS) / tg.FO4_VERTEX_UNITS).astype(np.int64).clip(0, 32)
    fid = np.full((len(yu), len(xu)), -1, np.int64)
    wmax = np.zeros((len(yu), len(xu)), np.float32)
    for cyv in np.unique(cy):
        rsel = cy == cyv
        for cxv in np.unique(cx):
            d = cells.get((int(cxv), int(cyv)))
            if not d:
                continue
            csel = cx == cxv
            ids = list(d)
            stack = np.stack([d[i] for i in ids])                   # [k, 33, 33]
            best = np.argmax(stack, axis=0)
            r_idx, c_idx = vi[rsel], vj[csel]
            sub_b = best[np.ix_(r_idx, c_idx)]
            sub_w = stack.max(axis=0)[np.ix_(r_idx, c_idx)]
            fid[np.ix_(rsel, csel)] = np.asarray(ids)[sub_b]
            wmax[np.ix_(rsel, csel)] = sub_w
    return fid, wmax


def infer_mapping(cells, overlays, staging, bands=48):
    """{Skyrim LTEX: Starfield LTEX form id} read off the installed terrain (no ltex_mapping.json: the October build did
    not keep one): for each Skyrim texture, what the staged BTD draws most where Skyrim paints that texture almost alone
    (95 %; else where it is the largest layer). Returns (mapping, {Skyrim LTEX: samples behind it}, the texture drawn
    most where Skyrim has no texture data or None)."""
    from collections import Counter
    from fo4sf import overlay_grid as og
    strong, weak, outside = Counter(), Counter(), Counter()
    for o in overlays:
        t = og.Tile(o["ix"], o["iy"], o["cells_cw"]["x"][0], o["cells_cw"]["y"][0], o["n"])
        with open(as_built(staging, o["btd_file"]), "rb") as fh:
            old = btd.read(fh.read())
        xs, ys = t.sample_coords()
        for r0 in sample_rows(len(xs), bands):
            drawn = dominant(old.weights[r0:r0 + 64], old.quad_map[r0 // 64:r0 // 64 + 1], list(old.ltex))
            fid, w = skyrim_at(cells, xs, ys[r0:r0 + 64])
            f, d, wv = fid.ravel(), drawn.ravel().astype(np.int64), w.ravel()
            for sel, tally in ((f < 0, None), ((f >= 0) & (wv >= 0.95), strong), ((f >= 0) & (wv >= 0.5) & (wv < 0.95), weak)):
                if tally is None:
                    vals, counts = np.unique(d[sel], return_counts=True)
                    for v, c in zip(vals.tolist(), counts.tolist()):
                        outside[v] += c
                    continue
                pairs, counts = np.unique(np.stack([f[sel], d[sel]], axis=1), axis=0, return_counts=True)
                for (fv, dv), c in zip(pairs.tolist(), counts.tolist()):
                    tally[(fv, dv)] += c
    mapping, support = {}, {}
    for tally in (strong, weak):
        best = {}
        for (f, d), n in tally.items():
            if f in mapping:
                continue
            if n > best.get(f, (0, None))[0]:
                best[f] = (n, d)
        for f, (n, d) in best.items():
            mapping[f], support[f] = d, n
    return mapping, support, (outside.most_common(1)[0][0] if outside else None)


def planes_from(cells, mapping, default_sf, table, land, consistent_edges=True):
    """{Starfield form id: uint8 merged vertex grid} for the table, Skyrim's weights summed per mapped texture."""
    from fo4sf import landtex
    from fo4sf import terrain_grid as tg
    cells_t = {}
    for xy, ws in cells.items():
        d = {}
        for f, w in ws.items():
            t = mapping.get(f, default_sf)
            d[t] = d.get(t, 0) + w.astype(np.float32)
        cells_t[xy] = d
    x0, x1, y0, y1 = land.grid_bounds
    planes = {fid: np.rint(np.clip(landtex.merged_grid(cells_t, fid, x0, x1, y0, y1, 1.0 if fid == default_sf else 0.0,
                                                       consistent_edges), 0, 1) * 255).astype(np.uint8) for fid in table}
    return planes, x0 * tg.FO4_CELL_UNITS, y0 * tg.FO4_CELL_UNITS, tg.FO4_VERTEX_UNITS


def dominant(words, qmap, table):
    """The texture drawn at each sample (form id) of a BTD texture part, for comparing two encodings."""
    from fo4sf import landtex
    dec = landtex.decode_quadrants(qmap, words, table)
    ids = sorted(dec)
    return np.asarray(ids)[np.argmax(np.stack([dec[i] for i in ids]), axis=0)]


def as_built(staging, rel):
    """The BTD as the build wrote it: its copy in BACKUP if an earlier recompute replaced it, else the staged file."""
    keep = os.path.join(staging, BACKUP, *rel.split("/"))
    return keep if os.path.exists(keep) else os.path.join(staging, *rel.split("/"))


def read_table(staging, o):
    with open(as_built(staging, o["btd_file"]), "rb") as fh:
        return btd.read(fh.read()).ltex


def cmd_recompute(a):
    import json
    from fo4sf import overlay_grid as og
    from make_skyrim_overlay import tile_layers
    with open(os.path.join(a.staging, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    if os.path.exists(os.path.join(a.staging, "ltex_mapping.json")):
        print("reading Skyrim's ground layers and the staging's texture mapping ...")
        planes, ox, oy, sp, names = staged_textures(a.staging, a.skyrim, a.sf_data, a.world)
        check_planes = staged_textures(a.staging, a.skyrim, a.sf_data, a.world, consistent_edges=False)[0]
    else:
        from fo4sf import landtex, skyrimland
        print("no ltex_mapping.json in the staging: reading which texture the installed terrain draws for each Skyrim "
              "texture ...")
        land = skyrimland.SkyrimLand(a.skyrim, a.world)
        cells, ltex = landtex.read_world_textures(a.skyrim, land.land_source, {})
        mapping, support, outside = infer_mapping(cells, prm["overlays"], a.staging, a.infer_bands)
        table = sorted({x for o in prm["overlays"] for x in read_table(a.staging, o)})
        default_sf = mapping.get(landtex.DEFAULT_LTEX) or outside or table[0]
        used = {f for ws in cells.values() for f in ws}
        unseen = sorted(used - set(mapping))
        print(f"  {len(mapping)} of {len(used)} Skyrim textures read off the terrain; {len(unseen)} not seen in the "
              f"sampled bands (drawn as the default {default_sf:08X})")
        for f in sorted(mapping, key=lambda f: -support[f])[:12]:
            print(f"    {ltex.get(f, {}).get('edid', f'{f:08X}'):28} -> {mapping[f]:08X} ({support[f]} samples)")
        planes, ox, oy, sp = planes_from(cells, mapping, default_sf, table, land)
        # the build stitched cell edges the old way (landtex.merged_grid consistent_edges): the spot check does too
        check_planes = planes_from(cells, mapping, default_sf, table, land, consistent_edges=False)[0]
    done = 0
    for o in prm["overlays"]:
        t = og.Tile(o["ix"], o["iy"], o["cells_cw"]["x"][0], o["cells_cw"]["y"][0], o["n"])
        paths = [os.path.join(a.staging, *o["btd_file"].split("/"))]
        paths += [os.path.join(a.staging, *c.split("/")) for c in o.get("btd_copies") or []]
        with open(as_built(a.staging, o["btd_file"]), "rb") as fh:      # what the build drew (the backup once replaced)
            old = btd.read(fh.read())
        table = list(old.ltex)
        lack = [x for x in table if x not in planes]
        if lack:            # in the table but painted nowhere by this mapping: an empty plane (the spot check decides)
            print(f"  {o['world']}: its LTEX table has {[f'{x:08X}' for x in lack[:6]]} that the mapping does not paint")
            shape = next(iter(planes.values())).shape
            for x in lack:
                planes[x] = np.zeros(shape, np.uint8)
                check_planes[x] = np.zeros(shape, np.uint8)
        size = old.weights.shape[0]
        # the spot check uses other bands than the mapping was learnt from (offset by half a step)
        rows = [r for r in (x + 64 * max(1, len(range(0, size, 64)) // (2 * a.check_bands))
                            for x in sample_rows(size, a.check_bands)) if r < size]
        sw, sq, _ = tile_layers(check_planes, table, ox, oy, sp, t, a.check_blend, "head", 0.0, rows=rows)
        sel = np.concatenate([np.arange(r, r + 64) for r in rows])
        qsel = sorted({r // 64 for r in rows})
        mine = dominant(sw[sel], sq[qsel], table)
        theirs = dominant(old.weights[sel], old.quad_map[qsel], table)
        match = float((mine == theirs).mean())
        print(f"  {o['world']}: spot check of {len(rows)} bands, encoded the old way: {match:.1%} of samples draw the "
              f"same texture as the terrain as built")
        if match < a.min_match:
            print(f"  {o['world']}: below {a.min_match:.0%}: these inputs are not the build's; nothing written")
            continue
        words, qmap, beyond = tile_layers(planes, table, ox, oy, sp, t, a.blend, "head", a.warp)
        data = btd.write(btd.Btd(old.version, old.hmin, old.hmax, table, old.heights_raw, words, qmap))
        assert np.array_equal(btd.read(data).heights_raw, old.heights_raw)      # heights exactly as installed
        if not a.dry_run:
            backup = os.path.join(a.staging, BACKUP)
            for p in paths:
                if not os.path.exists(p):
                    continue
                keep = os.path.join(backup, os.path.relpath(p, a.staging))
                if not os.path.exists(keep):                    # the first time only: the build's own terrain
                    os.makedirs(os.path.dirname(keep), exist_ok=True)
                    shutil.copy2(p, keep)
                with open(p, "wb") as fh:
                    fh.write(data)
        done += 1
        print(f"  {o['world']}: {'would write' if a.dry_run else 'wrote'} {a.blend} blend (warp {a.warp:g} m) into "
              f"{len(paths)} file(s); heights kept; weight past the five layers per quadrant at most {max(beyond):.1%}")
    return 0 if done else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("recompute", "rebuild", "splice"))
    ap.add_argument("--staging", required=True, help="the installed exterior's staging (C:\\Modding\\staging\\skyrim_all)")
    ap.add_argument("--fresh", help="rebuild / splice: where the fresh build goes / is (another folder)")
    ap.add_argument("--skyrim", help="recompute: Skyrim.esm")
    ap.add_argument("--sf-data", help="recompute: Starfield's Data folder (Starfield.esm's LTEX names)")
    ap.add_argument("--world", default="Tamriel", help="recompute: the Skyrim worldspace (default Tamriel)")
    ap.add_argument("--min-match", type=float, default=0.98, help="recompute: spot-check agreement needed to write")
    ap.add_argument("--check-bands", type=int, default=24, help="recompute: 64-row bands in the spot check")
    ap.add_argument("--infer-bands", type=int, default=48,
                    help="recompute without ltex_mapping.json: 64-row bands read to learn the mapping")
    ap.add_argument("--check-blend", choices=("solid", "dither"), default="solid",
                    help="recompute: the blend the staging was built with (the spot check encodes this way)")
    ap.add_argument("--blend", choices=("solid", "dither", "noise"), default="noise", help="rebuild: --ltex-blend")
    ap.add_argument("--warp", type=float, default=1.5, help="--ltex-warp (m)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "recompute":
        if not (a.skyrim and a.sf_data):
            ap.error("recompute needs --skyrim and --sf-data")
        return cmd_recompute(a)
    if not a.fresh:
        ap.error(f"{a.cmd} needs --fresh")
    return cmd_rebuild(a) if a.cmd == "rebuild" else cmd_splice(a)


if __name__ == "__main__":
    sys.exit(main())
