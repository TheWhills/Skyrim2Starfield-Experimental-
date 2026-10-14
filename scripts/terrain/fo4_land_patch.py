"""Extract and check a small Fallout 4 terrain patch (N x M exterior cells) from Fallout4.esm.

    python scripts/terrain/fo4_land_patch.py --esm <Fallout4.esm> --world Commonwealth --x0 -18 --y0 18 \
        --out <research dir>/patch_-18_18 --structure 000211C0 [--mutagen <Fo4Land json>]

Writes, all OUTSIDE the repo (derived game data):
  heights.json      per-cell 33x33 grids and the merged grid, FO4 units (row 0 = south, col 0 = west)
  merged_units.npy  merged grid, FO4 units;  merged_metres.npy  the same / 70 (repo object scale, not proven for terrain)
  refs.json         placed refs in the patch with base type/EDID and terrain height under them
  report.json       the checks: decode cross-check, ref-in-cell, shared edges, alignment, slope
  preview.png       heightmap (north up) with cell borders, the structure and the grounded refs marked
Decoding lives in src/fo4sf/fo4land.py (follows fo76utils fo4land; see docs/terrain/source-patch.md).
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from fo4sf import fo4land  # noqa: E402
from fo4sf.fo4land import CELL_UNITS, GRID, UNITS_PER_METRE  # noqa: E402

GROUNDED_DEFAULT = (r"^(RockBoulder\d|RockM\d|RockS\d|RockPileM\d|TreeMapleForest\d|TreeMapleblasted\d|TreeSapling\d|"
                    r"TreeStump\d|TreeCedarShrub\d)")
METHODS = ("bilinear", "tri_sw_ne", "tri_nw_se")


def stats(values):
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return {"n": 0}
    return {"n": int(a.size), "median": float(np.median(a)), "mean": float(a.mean()), "min": float(a.min()),
            "max": float(a.max()), "max_abs": float(np.abs(a).max()), "p10": float(np.percentile(a, 10)),
            "p90": float(np.percentile(a, 90))}


def load(args):
    xs = range(args.x0 - 1, args.x0 + args.nx + 1)  # one ring of neighbours for the outer-edge check
    ys = range(args.y0 - 1, args.y0 + args.ny + 1)
    wanted = {(x, y) for x in xs for y in ys}
    with fo4land.Plugin(args.esm) as p:
        world = p.read_world(args.world, cells=wanted)
        patch = {(args.x0 + i, args.y0 + j) for i in range(args.nx) for j in range(args.ny)}
        refs = []
        for xy in sorted(patch):
            c = world["cells"][xy]
            refs += [dict(r, cell=list(xy), group="temporary") for r in c["refs"]]
            refs += [dict(r, cell=list(xy), group="cell_persistent") for r in c["persistent_refs"]]
        for r in world.get("persistent_cell", {}).get("persistent_refs", []):
            if r["pos"] and fo4land.cell_of(*r["pos"][:2]) in patch:
                refs.append(dict(r, cell=list(fo4land.cell_of(*r["pos"][:2])), group="world_persistent"))
        bases = p.base_records(wanted={r["base"] for r in refs if r["base"] is not None})
    return world, patch, refs, bases


def world_scan(args):
    """Whole-worldspace facts: seams between all neighbouring cells, height range, VHGT sizes and pad bytes."""
    with fo4land.Plugin(args.esm) as p:
        world = p.read_world(args.world, refs=False)
    grids, sizes, pads = {}, {}, {}
    for xy, c in world["cells"].items():
        if c["vhgt"]:
            grids[xy] = fo4land.decode_vhgt(c["vhgt"])
            sizes[len(c["vhgt"])] = sizes.get(len(c["vhgt"]), 0) + 1
            pad = c["vhgt"][fo4land.VHGT_MIN_SIZE:].hex() or "-"
            pads[pad] = pads.get(pad, 0) + 1
    edges = fo4land.edge_mismatches(grids)
    worst = sorted(edges.pop("mismatches"), key=lambda m: -m["max_abs"])
    lo = min(float(g.min()) for g in grids.values())
    hi = max(float(g.max()) for g in grids.values())
    xs = [xy[0] for xy in grids]
    ys = [xy[1] for xy in grids]
    return {"cells_with_vhgt": len(grids), "cells_without_vhgt": len(world["cells"]) - len(grids),
            "cell_x_range": [min(xs), max(xs)], "cell_y_range": [min(ys), max(ys)],
            "vhgt_sizes": {str(k): v for k, v in sizes.items()}, "vhgt_pad_bytes": dict(sorted(pads.items(), key=lambda kv: -kv[1])[:5]),
            "height_min_units": lo, "height_max_units": hi,
            "fo4land_16bit_step_units": (hi - lo) / 65535.0,
            "edges": dict(edges, mismatched_pairs=len(worst), worst=worst[:10],
                          max_abs_histogram={str(v): sum(1 for m in worst if m["max_abs"] == v)
                                             for v in sorted({m["max_abs"] for m in worst})[:12]})}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--world-scan", action="store_true", help="also scan seams/height range of the whole worldspace")
    ap.add_argument("--esm", required=True)
    ap.add_argument("--world", default="Commonwealth")
    ap.add_argument("--x0", type=int, required=True)
    ap.add_argument("--y0", type=int, required=True)
    ap.add_argument("--nx", type=int, default=2)
    ap.add_argument("--ny", type=int, default=2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--structure", help="form id (hex) of the familiar structure REFR")
    ap.add_argument("--grounded-regex", default=GROUNDED_DEFAULT)
    ap.add_argument("--mutagen", help="Fo4Land (dotnet) JSON for the same cells: second, independent decode")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    world, patch, refs, bases = load(args)
    report = {"world": args.world, "world_fid": "%08X" % world["world_fid"],
              "patch": {"x0": args.x0, "y0": args.y0, "nx": args.nx, "ny": args.ny}}
    for sig, d in world["world_fields"]:
        if sig == b"DNAM" and len(d) >= 8:
            report["world_dnam_land_water"] = list(np.frombuffer(d[:8], "<f4").astype(float))

    grids = {xy: fo4land.decode_vhgt(c["vhgt"]) for xy, c in world["cells"].items() if c["vhgt"]}
    missing = sorted(xy for xy in patch if xy not in grids)
    if missing:
        sys.exit(f"cells without VHGT in the patch: {missing}")
    merged, edges = fo4land.merge_cells(grids, args.x0, args.y0, args.nx, args.ny)
    ox, oy = args.x0 * CELL_UNITS, args.y0 * CELL_UNITS

    # (c) shared borders, inside the patch and against the ring of neighbours
    report["shared_edges"] = {"inside_patch": edges, "patch_plus_ring": fo4land.edge_mismatches(grids)}
    if args.world_scan:
        report["world_scan"] = world_scan(args)

    cells_out = []
    for xy in sorted(patch, key=lambda t: (t[1], t[0])):
        c, g = world["cells"][xy], grids[xy]
        cells_out.append({"x": xy[0], "y": xy[1], "cell_fid": "%08X" % c["fid"], "land_fid": "%08X" % c["land_fid"],
                          "origin_units": [xy[0] * CELL_UNITS, xy[1] * CELL_UNITS],
                          "origin_metres": [xy[0] * CELL_UNITS / UNITS_PER_METRE, xy[1] * CELL_UNITS / UNITS_PER_METRE],
                          "vhgt_offset": float(np.frombuffer(c["vhgt"][:4], "<f4")[0]),
                          "min_units": float(g.min()), "max_units": float(g.max())})
    report["cells"] = cells_out

    # (b) every temporary ref of a cell lies inside that cell's 4096 x 4096 square
    inside = {"checked": 0, "outside": [], "min_margin_units": None}
    for r in refs:
        if r["group"] != "temporary" or not r["pos"]:
            continue
        inside["checked"] += 1
        x, y = r["pos"][:2]
        cx, cy = r["cell"]
        margin = min(x - cx * CELL_UNITS, (cx + 1) * CELL_UNITS - x, y - cy * CELL_UNITS, (cy + 1) * CELL_UNITS - y)
        inside["min_margin_units"] = margin if inside["min_margin_units"] is None else min(inside["min_margin_units"], margin)
        if fo4land.cell_of(x, y) != (cx, cy):
            inside["outside"].append({"fid": "%08X" % r["fid"], "cell": r["cell"], "pos": r["pos"]})
    report["refs_in_cells"] = inside

    # (d) alignment: terrain under refs
    for r in refs:
        b = bases.get(r["base"], ("?", "?", None))
        r["base_type"], r["base_edid"], r["obnd"] = b[0], b[1], b[2]
        if r["pos"]:
            hs = {m: fo4land.height_at(merged, ox, oy, r["pos"][0], r["pos"][1], m) for m in METHODS}
            r["terrain_units"] = hs
            r["residual_units"] = None if hs["bilinear"] is None else r["pos"][2] - hs["bilinear"]
    import re
    rx = re.compile(args.grounded_regex)
    grounded = [r for r in refs if r["group"] == "temporary" and r.get("residual_units") is not None
                and r["base_type"] in ("STAT", "TREE", "SCOL") and rx.search(r["base_edid"])]
    by_class = {}
    for r in grounded:
        by_class.setdefault(re.sub(r"\d+$", "", r["base_edid"]), []).append(r["residual_units"])
    tri_spread = [max(r["terrain_units"].values()) - min(r["terrain_units"].values()) for r in grounded]
    small = [r for r in grounded if not r["base_edid"].startswith("TreeMaple")]
    report["grounded_refs"] = {
        "regex": args.grounded_regex, "residual_units": stats([r["residual_units"] for r in grounded]),
        "residual_metres": stats([r["residual_units"] / UNITS_PER_METRE for r in grounded]),
        "excluding_large_trees_residual_units": stats([r["residual_units"] for r in small]),
        "by_class_median_units": {k: [len(v), float(np.median(v))] for k, v in sorted(by_class.items())},
        "interpolation_spread_units": stats(tri_spread)}

    # orientation control: the same refs against deliberately wrong grid orientations must fit worse
    control = {}
    for name, grid in (("as_decoded", merged), ("north_south_flipped", merged[::-1]),
                       ("east_west_flipped", merged[:, ::-1]), ("transposed", merged.T)):
        res = [r["pos"][2] - fo4land.height_at(grid, ox, oy, r["pos"][0], r["pos"][1]) for r in small]
        control[name] = {"median_abs_residual_units": float(np.median(np.abs(res)))}
    report["orientation_control"] = control

    if args.structure:
        fid = int(args.structure, 16)
        s = next(r for r in refs if r["fid"] == fid)
        x, y, z = s["pos"]
        sr = {"fid": "%08X" % fid, "base_edid": s["base_edid"], "base_type": s["base_type"], "obnd": s["obnd"],
              "pos": s["pos"], "rot": s["rot"], "cell": s["cell"], "group": s["group"],
              "terrain_at_origin_units": s["terrain_units"], "z_minus_terrain_units": s["residual_units"]}
        if s["obnd"]:
            x1, y1, z1, x2, y2, _z2 = s["obnd"]
            radius = float(min(abs(x1), abs(x2), abs(y1), abs(y2)))  # disc inside the bounds for any rotation
            pts = [(x + rr * math.cos(t), y + rr * math.sin(t)) for rr in np.linspace(0, radius, 9)
                   for t in np.linspace(0, 2 * math.pi, 24, endpoint=False)]
            th = [fo4land.height_at(merged, ox, oy, px, py) for px, py in pts]
            th = [h for h in th if h is not None]
            sr["footprint_disc"] = {"radius_units": radius, "samples": len(th),
                                    "terrain_units": stats(th), "z_minus_terrain_units": stats([z - h for h in th]),
                                    "bounds_bottom_z_units": z + z1}
        report["structure"] = sr

    # slope / relief
    slope = fo4land.slope_degrees(merged)
    report["patch_stats"] = {
        "grid_shape": list(merged.shape), "vertex_spacing_units": fo4land.VERTEX_SPACING,
        "height_units": stats(merged.ravel()), "height_metres": stats(merged.ravel() / UNITS_PER_METRE),
        "relief_units": float(merged.max() - merged.min()),
        "relief_metres": float((merged.max() - merged.min()) / UNITS_PER_METRE),
        "slope_degrees": stats(slope.ravel()), "fraction_slope_over_30deg": float((slope > 30).mean())}

    # (a) second decode via Mutagen (dotnet/Fo4Land)
    if args.mutagen:
        with open(args.mutagen, encoding="utf-8") as f:
            mj = json.load(f)
        cmp_ = {"cells": 0, "max_abs_height_diff": 0.0, "cell_fid_mismatch": [], "ref_pos_max_abs_diff": 0.0,
                "refs_compared": 0, "refs_only_python": 0, "refs_only_mutagen": 0}
        for mc in mj["cells"]:
            xy = (mc["x"], mc["y"])
            if xy not in patch:
                continue
            cmp_["cells"] += 1
            d = np.abs(np.asarray(mc["heights"], dtype=float) - grids[xy])
            cmp_["max_abs_height_diff"] = max(cmp_["max_abs_height_diff"], float(d.max()))
            if mc["cell"] != "%08X" % world["cells"][xy]["fid"]:
                cmp_["cell_fid_mismatch"].append(list(xy))
            py = {"%08X" % r["fid"]: r for r in world["cells"][xy]["refs"]}
            mu = {r["fid"]: r for r in mc["refs"] if r["pos"]}
            for k in py.keys() & mu.keys():
                cmp_["refs_compared"] += 1
                diff = np.abs(np.asarray(mu[k]["pos"]) - np.asarray(py[k]["pos"])).max()
                cmp_["ref_pos_max_abs_diff"] = max(cmp_["ref_pos_max_abs_diff"], float(diff))
            cmp_["refs_only_python"] += len(py.keys() - mu.keys())
            cmp_["refs_only_mutagen"] += len(mu.keys() - py.keys())
        report["mutagen_cross_check"] = cmp_

    # outputs
    with open(os.path.join(args.out, "heights.json"), "w", encoding="utf-8") as f:
        json.dump({"units": "FO4 units (metres = units / 70, repo object scale; terrain scale unproven)",
                   "orientation": "[row][col], row 0 = south, col 0 = west, 128 units apart",
                   "cells": [dict(c, heights=grids[(c["x"], c["y"])].tolist()) for c in cells_out],
                   "merged_origin_units": [ox, oy], "merged": merged.tolist()}, f)
    np.save(os.path.join(args.out, "merged_units.npy"), merged)
    np.save(os.path.join(args.out, "merged_metres.npy"), merged / UNITS_PER_METRE)
    with open(os.path.join(args.out, "refs.json"), "w", encoding="utf-8") as f:
        json.dump([dict(r, fid="%08X" % r["fid"], base=None if r["base"] is None else "%08X" % r["base"])
                   for r in refs], f, indent=0)
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    preview(merged, args, refs, grounded, report.get("structure"), os.path.join(args.out, "preview.png"))
    print(json.dumps(report, indent=2))


def preview(merged, args, refs, grounded, structure, path, scale=8):
    from PIL import Image, ImageDraw
    rows, cols = merged.shape
    lo, hi = float(merged.min()), float(merged.max())
    img = Image.fromarray(((merged[::-1] - lo) / max(hi - lo, 1e-6) * 255).astype(np.float32), mode="F")
    size = ((cols - 1) * scale + 1, (rows - 1) * scale + 1)
    img = img.resize(size, Image.BILINEAR).convert("L").convert("RGB")
    dr = ImageDraw.Draw(img)
    n = GRID - 1

    def px(x, y):
        u = (x - args.x0 * CELL_UNITS) / fo4land.VERTEX_SPACING
        v = (y - args.y0 * CELL_UNITS) / fo4land.VERTEX_SPACING
        return u * scale, (rows - 1 - v) * scale

    for i in range(args.nx + 1):
        dr.line([(i * n * scale, 0), (i * n * scale, size[1])], fill=(255, 200, 0), width=1)
    for j in range(args.ny + 1):
        dr.line([(0, j * n * scale), (size[0], j * n * scale)], fill=(255, 200, 0), width=1)
    for i in range(args.nx):
        for j in range(args.ny):
            dr.text((i * n * scale + 4, (args.ny - 1 - j) * n * scale + 4), f"({args.x0 + i},{args.y0 + j})",
                    fill=(255, 220, 80))
    for r in grounded:
        x, y = px(*r["pos"][:2])
        dr.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(60, 220, 255))
    if structure:
        x, y = px(*structure["pos"][:2])
        rad = structure.get("footprint_disc", {}).get("radius_units", 200) / fo4land.VERTEX_SPACING * scale
        dr.ellipse([x - rad, y - rad, x + rad, y + rad], outline=(255, 40, 40), width=2)
        dr.line([(x - 8, y), (x + 8, y)], fill=(255, 40, 40), width=2)
        dr.line([(x, y - 8), (x, y + 8)], fill=(255, 40, 40), width=2)
        dr.text((x + 10, y + 6), structure["base_edid"], fill=(255, 80, 80))
    dr.text((4, size[1] - 14), f"N up; {lo:.0f}..{hi:.0f} units ({lo / 70:.0f}..{hi / 70:.0f} m); dots: grounded refs",
            fill=(255, 255, 255))
    img.save(path)


if __name__ == "__main__":
    main()
