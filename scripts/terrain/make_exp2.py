"""Terrain experiment 2: real Commonwealth heights around Red Rocket as one native Starfield BTD (docs/terrain/experiment2.md).

    python scripts/terrain/make_exp2.py build --fo4 <Fallout4.esm> --sf-data <Starfield Data dir> --out <staging dir>
    python scripts/terrain/make_exp2.py restage --from <staged exp2 dir> --sf-data <Starfield Data dir> --out <dir>
    dotnet run --project dotnet/TerrainExp2 -c Release -- <Starfield.esm> <staging dir>      (reads exp2_params.json)
    python scripts/terrain/make_exp2.py check --sf-data <Starfield Data dir> --out <staging dir>

build writes, all OUTSIDE the repo (derived game data); restage takes the BTD, points and spawn of an already staged
experiment 2 instead of reading Fallout4.esm (exp2b, docs/terrain/overlay-records.md):
  Data/Terrain/FO4CW_Commonwealth.btd   n x n cells, FO4 heights / 70 at absolute positions (FO4 x, y / 70)
  Data/textures/terrain/overlaymasks/fo4cw_commonwealth.dds   overlay mask (BC4, 100 px per cell, 255 outer ring)
  plan.json         runner format: coc, label, anchor, spawn_local, drop_z, settle_ms, points (worldspace's own frame)
  expected.json     hypothesis, grid, height range, every point with its metadata and offline verification
  exp2_params.json  what the dotnet plugin builder needs: n, height range, spawn, FNAM (one raw u16 per BTD cell),
                    alignment / HNAM, location, anchor, Mars registration
  README.txt        manual console steps;  preview.png  heightmap with the check points (north up)
check re-reads the staged files: decoded heights at every plan point and a raw record walk of both plugins
(scripts/terrain/overlay_records.py check_staging).

Rules (supported hypotheses until the game shows them, see experiment 1): BTD grid starts n // 2 cells west / south of the
world origin, 100 m cells, 128 samples per cell, row 0 = south; BTD height = world z in metres (hypothesis H).
"""
import argparse
import json
import math
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from fo4sf import ba2, btd, fo4land, overlay  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overlay_records  # noqa: E402

WORLD = "FO4CW_Commonwealth"
PLUGIN = "FO4TerrainExp2.esm"
MARS_PLUGIN = "FO4TerrainExp2_Mars.esm"
ANCHOR_EDID = "FO4CW_Anchor"
BTD_NAME = WORLD + ".btd"
COC = "FO4CW_RedRocketSpawn"
PATCH = (-18, -17, 18, 19)              # FO4 cells x0, x1, y0, y1 of the PR #56 patch
STRUCTURE = 0x000211C0                  # RedRExt_Workshop01, the Red Rocket building
LTEX_TEMPLATE = "terrain/tempjemisonworld.btd"   # vanilla 100 x 100-cell BTD, one base texture everywhere
PLAIN_GROUND = 0x001235C2               # LDirtFootprints01: base texture of 2.33 M of the quadrants in 753 vanilla BTDs
SPAWN_ABOVE = 2.0
MAX_SLOPE = 30.0                        # steeper: the player may slide off the point
MIN_SLOPE = 5.0


def m(units):
    return units / tg.UNITS_PER_METRE


# ---------------------------------------------------------------------------------------------------------------- FO4
def read_fo4(esm, cells):
    """Merged vertex grid (FO4 units) for the inclusive cell range, its origin, the seam report and the structure ref."""
    x0, x1, y0, y1 = cells
    wanted = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    with fo4land.Plugin(esm) as p:
        world = p.read_world("Commonwealth", cells=wanted, refs=False)
        rr_cell = fo4land.cell_of(-69232.0, 80304.0)
        refs = p.read_world("Commonwealth", cells={rr_cell}, refs=True)["cells"][rr_cell]["refs"]
    grids = {xy: fo4land.decode_vhgt(c["vhgt"]) for xy, c in world["cells"].items() if c["vhgt"]}
    missing = sorted(wanted - set(grids))
    if missing:
        sys.exit(f"FO4 cells without VHGT: {missing[:10]} ({len(missing)})")
    merged, inside = fo4land.merge_cells(grids, x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    seams = fo4land.edge_mismatches(grids)
    seams["mismatches"] = sorted(seams["mismatches"], key=lambda s: -s["max_abs"])[:5]
    structure = next(r for r in refs if r["fid"] == STRUCTURE)
    return merged, (x0 * tg.FO4_CELL_UNITS, y0 * tg.FO4_CELL_UNITS), seams, structure


# ---------------------------------------------------------------------------------------------------------- points
def vertex_point(grid, origin, r, c, kind, label, **meta):
    xu, yu = origin[0] + c * tg.FO4_VERTEX_UNITS, origin[1] + r * tg.FO4_VERTEX_UNITS
    return dict(label=label, kind=kind, row=int(r), col=int(c), x=round(m(xu), 4), y=round(m(yu), 4),
                expect=round(m(float(grid[r, c])), 4), fo4_units=[xu, yu, float(grid[r, c])],
                fo4_cell=list(fo4land.cell_of(xu, yu)), sf_cell=list(tg.sf_cell_of(m(xu), m(yu))), **meta)


def select_points(grid, origin, structure_xy, err, tol):
    """About a dozen FO4 vertices (rows/cols of the merged grid) for the in-game check. Only vertices where the
    decoded BTD gives back the vertex height within `tol` under every interpolation rule (err(r, c) = worst of
    bilinear and both triangle splits, metres) are eligible, so the expectation does not depend on how the engine
    interpolates. FO4's own triangle split does not matter either: these are vertices."""
    ox, oy = origin
    sp = tg.FO4_VERTEX_UNITS

    def rc(xu, yu):
        return (yu - oy) / sp, (xu - ox) / sp

    px0, px1, py0, py1 = PATCH
    r_lo, c_lo = (int(round(v)) for v in rc(px0 * tg.FO4_CELL_UNITS, py0 * tg.FO4_CELL_UNITS))
    r_hi, c_hi = (int(round(v)) for v in rc((px1 + 1) * tg.FO4_CELL_UNITS, (py1 + 1) * tg.FO4_CELL_UNITS))
    cache = {}

    def ok(r, c):
        if (r, c) not in cache:
            cache[(r, c)] = err(r, c)
        return cache[(r, c)] <= tol

    def slope(r, c):
        return tg.local_slope_deg(grid, r, c, sp)

    pts, used = [], []

    def far(r, c, d=8):
        return all(abs(r - a) + abs(c - b) >= d for a, b in used)

    def take(r, c, kind, label, **meta):
        pts.append(vertex_point(grid, origin, r, c, kind, label, slope_deg=round(slope(r, c), 2),
                                predicted_error_m=round(cache[(r, c)], 6), **meta))
        used.append((r, c))

    # Red Rocket: the two eligible vertices nearest the building origin
    sr, sc = rc(*structure_xy)
    near = sorted(((r, c) for r in range(int(sr) - 4, int(sr) + 6) for c in range(int(sc) - 4, int(sc) + 6)),
                  key=lambda t: (t[0] - sr) ** 2 + (t[1] - sc) ** 2)
    for k, (r, c) in enumerate([t for t in near if ok(*t)][:2]):
        take(r, c, "redrocket", f"redrocket_{k + 1}",
             dist_from_origin_m=round(m(math.hypot((c - sc) * sp, (r - sr) * sp)), 2))

    inner = [(r, c) for r in range(r_lo + 2, r_hi - 1) for c in range(c_lo + 2, c_hi - 1)]
    # flat: all 5 x 5 (else 3 x 3) neighbours at the same height; two far apart
    for radius in (2, 1):
        flats = [t for t in inner if tg.is_flat(grid, *t, radius) and ok(*t) and far(*t)]
        if len(flats) >= 2:
            break
    a = flats[0]
    b = max(flats, key=lambda t: abs(t[0] - a[0]) + abs(t[1] - a[1]))
    take(*a, "flat", "flat_1", flat_radius=radius)
    take(*b, "flat", "flat_2", flat_radius=radius)

    # slopes: the steepest eligible vertex (MIN_SLOPE..MAX_SLOPE) in each of the four patch cells
    for k, (cx, cy) in enumerate([(px0, py0), (px1, py0), (px0, py1), (px1, py1)]):
        r0, c0 = (int(round(v)) for v in rc(cx * tg.FO4_CELL_UNITS, cy * tg.FO4_CELL_UNITS))
        cand = [(r, c) for r in range(r0 + 2, r0 + 31) for c in range(c0 + 2, c0 + 31)
                if MIN_SLOPE <= slope(r, c) <= MAX_SLOPE and far(r, c) and ok(r, c)]
        r, c = max(cand, key=lambda t: slope(*t))
        take(r, c, "slope", f"slope_{k + 1}_cell_{cx}_{cy}")

    # seams: a west and an east vertex at most 2 steps from the border and at most 3 rows apart; prefer sloped pairs
    def pair(border_col, on_border, kind, what):
        west = [border_col - 1, border_col - 2] if on_border else [border_col, border_col - 1]
        east = [border_col + 1, border_col + 2]
        best = None
        for r in range(r_lo + 2, r_hi - 1):
            for cw in west:
                if not (far(r, cw, 4) and slope(r, cw) <= MAX_SLOPE and ok(r, cw)):
                    continue
                for dr in range(-3, 4):
                    re_ = r + dr
                    for ce in east:
                        if r_lo + 2 <= re_ < r_hi - 1 and slope(re_, ce) <= MAX_SLOPE and far(re_, ce, 4) and ok(re_, ce):
                            score = (min(slope(r, cw), slope(re_, ce), 15.0), -abs(dr) - (ce - cw))
                            if best is None or score > best[0]:
                                best = (score, (r, cw), (re_, ce))
        take(*best[1], kind, f"{kind}_west", border=what)
        take(*best[2], kind, f"{kind}_east", border=what)

    cb = int(round(rc(px1 * tg.FO4_CELL_UNITS, 0)[1]))
    pair(cb, True, "seam_fo4", f"FO4 cell border x = {px1 * 4096} units ({m(px1 * 4096):.3f} m)")
    sb = int(math.floor((-1000.0 * tg.UNITS_PER_METRE - ox) / sp))
    pair(sb, False, "seam_sf", "Starfield cell border x = -1000 m (BTD LOD0 block border)")

    # resampled area: about 200 m south-west and north-east of the patch, outside it
    for kind, (xu, yu) in (("resampled_sw", (px0 * 4096 - 200 * 70, py0 * 4096 - 200 * 70)),
                           ("resampled_ne", ((px1 + 1) * 4096 + 200 * 70, (py1 + 1) * 4096 + 200 * 70))):
        r0, c0 = (int(round(v)) for v in rc(xu, yu))
        cand = sorted(((r, c) for r in range(r0 - 32, r0 + 33) for c in range(c0 - 32, c0 + 33)),
                      key=lambda t: (t[0] - r0) ** 2 + (t[1] - c0) ** 2)
        r, c = next(t for t in cand if MIN_SLOPE <= slope(*t) <= 20.0 and ok(*t))
        take(r, c, kind, kind)
    return pts


# ---------------------------------------------------------------------------------------------------------- build
def ltex_template(sf_data):
    """LTEX table and the single-texture quadrant pattern of vanilla TempJemisonWorld (base = LDirtFootprints01)."""
    for arc in ("Terrain01", "Terrain02", "Terrain03", "Terrain04"):
        a = ba2.Ba2(os.path.join(sf_data, f"Starfield - {arc}.ba2"))
        if a.find(LTEX_TEMPLATE) is not None:
            raw = a.read(LTEX_TEMPLATE)
            break
    nlt = struct.unpack_from("<I", raw, 0x28)[0]
    table = list(struct.unpack_from(f"<{nlt}I", raw, 0x2C))
    rx, ry = struct.unpack_from("<II", raw, 0x10)
    quad = bytes(raw[0x2C + 4 * nlt + 8 * (rx // 128) * (ry // 128):][:8])
    valid = [b for b in quad if 0 < b <= nlt]
    base = table[nlt - valid[-1]]               # fo76utils getCellTextureSet: last valid byte = default texture
    if base != PLAIN_GROUND:
        sys.exit(f"{LTEX_TEMPLATE}: base texture {base:08X}, expected {PLAIN_GROUND:08X}")
    return table, quad


def build(a):
    px0, px1, py0, py1 = PATCH
    region = (m(px0 * 4096) - a.margin, m((px1 + 1) * 4096) + a.margin,
              m(py0 * 4096) - a.margin, m((py1 + 1) * 4096) + a.margin)
    n = tg.choose_n(*region)
    xs = tg.sample_coords(n)
    foot = (xs[0], xs[-1], xs[0], xs[-1])
    cells = tg.fo4_cells_covering(*(foot if a.extract == "footprint" else region))
    print(f"region {region}, n = {n}, BTD samples {xs[0]:.2f}..{xs[-1]:.2f} m, FO4 cells {cells}")

    merged, origin, seams, structure = read_fo4(a.fo4, cells)
    heights = tg.resample_bilinear(merged, origin[0], origin[1], tg.FO4_VERTEX_UNITS,
                                   xs * tg.UNITS_PER_METRE, xs * tg.UNITS_PER_METRE) / tg.UNITS_PER_METRE
    hmin, hmax = float(math.floor(heights.min()) - 1), float(math.ceil(heights.max()) + 1)
    step = (hmax - hmin) / 65535.0
    table, quad = ltex_template(a.sf_data)
    raw = btd.quantize(heights, hmin, hmax)
    t = btd.Btd(6, hmin, hmax, table, raw, np.zeros_like(raw),
                np.tile(np.frombuffer(quad, np.uint8), (2 * n, 2 * n, 1)))
    data = btd.write(t)
    out_btd = os.path.join(a.out, "Data", "Terrain", BTD_NAME)
    os.makedirs(os.path.dirname(out_btd), exist_ok=True)
    with open(out_btd, "wb") as f:
        f.write(data)
    print(f"wrote {out_btd} ({len(data):,} bytes), heights {heights.min():.2f}..{heights.max():.2f} m, "
          f"range {hmin}..{hmax}, step {step * 1000:.2f} mm")

    back = btd.read(data)
    dec = back.heights_m()
    o = tg.grid_origin(n)

    def err(r, c):     # worst |decoded BTD - FO4 vertex| over the three interpolation rules, metres
        xu, yu = origin[0] + c * tg.FO4_VERTEX_UNITS, origin[1] + r * tg.FO4_VERTEX_UNITS
        hs = tg.point_interp(dec, o, o, tg.SF_STEP_M, m(xu), m(yu))
        return max(abs(h - m(float(merged[r, c]))) for h in hs.values())

    sx, sy, sz = structure["pos"]
    pts = select_points(merged, origin, (sx, sy), err, step)
    spawn = [round(m(sx), 4), round(m(sy), 4)]
    spawn_ground = tg.btd_height_at(t.heights_m(), n, *spawn)
    spawn.append(round(spawn_ground + SPAWN_ABOVE, 4))
    top = max(p["expect"] for p in pts)
    drop_z = float(math.ceil((top + 25.0) / 5.0) * 5.0)
    west = tg.grid_origin(n)
    beyond = {"x": west - 100.0, "y": spawn[1]}

    # offline verification against the BTD bytes just written
    for p in pts:
        hs = tg.point_interp(dec, o, o, tg.SF_STEP_M, p["x"], p["y"])
        p["btd_decoded"] = {k: round(v, 5) for k, v in hs.items()}
        p["error_m"] = round(max(abs(v - p["expect"]) for v in hs.values()), 6)
        p["shift_sensitivity_m"] = round(0.5 * tg.SF_STEP_M * math.tan(math.radians(p["slope_deg"])), 3)
    worst = max(p["error_m"] for p in pts)
    # honest context: resampling error at every FO4 vertex of the patch (not only the chosen planar ones)
    rr0 = int((py0 * 4096 - origin[1]) / 128)
    cc0 = int((px0 * 4096 - origin[0]) / 128)
    sub = merged[rr0:rr0 + 65, cc0:cc0 + 65]
    vx = m(origin[0] + (cc0 + np.arange(65)) * 128.0)
    vy = m(origin[1] + (rr0 + np.arange(65)) * 128.0)
    at_vertices = tg.resample_bilinear(dec, o, o, tg.SF_STEP_M, vx, vy)
    verr = np.abs(at_vertices - sub / tg.UNITS_PER_METRE)
    check = {"points": len(pts), "max_error_m": worst, "quantisation_step_m": step, "pass": bool(worst <= step),
             "all_patch_vertices": {"n": int(verr.size), "median_m": float(np.median(verr)),
                                    "p99_m": float(np.percentile(verr, 99)), "max_m": float(verr.max())}}
    print(json.dumps(check, indent=1))
    if not check["pass"]:
        sys.exit("a plan point's decoded height differs from its expectation by more than one quantisation step")

    cr = tg.cell_range(n)
    expected = {
        "experiment": "terrain_exp2", "plugin": PLUGIN, "worldspace": WORLD, "btd": f"Data\\Terrain\\{BTD_NAME}",
        "btd_lookup": "record path (SFBK ANAM Data\\TERRAIN\\" + BTD_NAME + ") and name (WRLD EditorID) both match",
        "hypothesis": "H: BTD height = world z in metres, and FO4 positions/heights convert at 70 units per metre, so a "
                      "player dropped at FO4 vertex (x, y) / 70 lands at FO4 height / 70 (within 0.5 m: runner tolerance)",
        "grid_rule": f"BTD SW sample at ({west}, {west}) m, {tg.SF_STEP_M} m spacing, rows south to north (supported)",
        "n_cells": n, "sf_cells": [cr[0], cr[1]], "btd_samples": n * 128, "btd_bytes": len(data),
        "covered_m": [float(xs[0]), float(xs[-1])],
        "region_of_interest_m": {"xmin": region[0], "xmax": region[1], "ymin": region[2], "ymax": region[3]},
        "fo4_cells": {"x": [cells[0], cells[1]], "y": [cells[2], cells[3]],
                      "count": (cells[1] - cells[0] + 1) * (cells[3] - cells[2] + 1), "extract": a.extract},
        "fo4_seams_in_extracted_cells": seams,
        "height_range_m": [hmin, hmax], "heights_m": [float(heights.min()), float(heights.max())],
        "quantisation_step_m": step, "ltex": {"table": ["%08X" % x for x in table], "quadrant_bytes": list(quad),
                                              "base": "%08X LDirtFootprints01" % PLAIN_GROUND},
        "structure": {"fid": "%08X" % STRUCTURE, "fo4_pos": structure["pos"], "pos_m": [m(sx), m(sy), m(sz)]},
        "spawn": {"coc": COC, "pos_m": spawn, "ground_m": spawn_ground, "sf_cell": list(tg.sf_cell_of(*spawn[:2]))},
        "drop_z": drop_z, "beyond": beyond, "points": pts, "offline_check": check,
        "reading": {"all points within 0.5 m": "terrain loads, H and the grid rule hold for real terrain",
                    "heights off by a constant": "vertical offset (e.g. a world height origin)",
                    "heights scaled": "compare read/expect ratio: x8 = fo76utils FIXME scale, 70/100 = other unit",
                    "seam pair differs while others pass": "LOD0 block stitching or FO4 cell border handling",
                    "slopes off by ~slope x 0.4 m": "half-sample grid shift (shift_sensitivity_m per point)",
                    "fell (NOTERRAIN)": "BTD not loaded: compare with experiment 1"}}
    stage(a, data, raw, pts, spawn, spawn_ground, drop_z, expected)


def stage(a, data, raw, pts, spawn, spawn_ground, drop_z, expected):
    """Everything after the BTD: overlay records in the params (FNAM per cell, alignment, Location, anchor, Mars
    registration), the overlay mask, plan.json in the runner format, expected.json, README.txt and the preview."""
    n = raw.shape[1] // 128
    cr = tg.cell_range(n)
    hmin, hmax = expected["height_range_m"]
    ground = round(float(spawn_ground), 4)
    anchor = {"edid": ANCHOR_EDID, "local": [spawn[0], spawn[1], ground], "ref": overlay_records.anchor_ref()}
    mars = None if a.no_mars else {"plugin": MARS_PLUGIN, "latitude": a.mars_lat, "longitude": a.mars_lon}
    params = {"plugin": PLUGIN, "world": WORLD, "btd_path": f"Data\\TERRAIN\\{BTD_NAME}",
              "btd_file": f"Data/Terrain/{BTD_NAME}", "n": n,
              "cell_min": cr[0], "cell_max": cr[1], "hmin": hmin, "hmax": hmax,
              "fnam": overlay.fnam_values(raw), "alignment": a.alignment, "hnam": a.hnam, "location": True,
              "anchor": anchor, "mars": mars, "mask": overlay_records.mask_rel(WORLD), "coc": COC, "spawn": spawn,
              "spawn_cell": list(tg.sf_cell_of(*spawn[:2])),
              "bounds_min_m": tg.grid_origin(n), "bounds_max_m": tg.grid_origin(n) + n * tg.SF_CELL_M}
    plan = [{"coc": COC,
             "label": f"terrain exp2b: Commonwealth heights around Red Rocket ({n}x{n}-cell BTD) + overlay records "
                      f"({a.alignment}, HNAM {a.hnam}{', Mars' if mars else ''})",
             "anchor": {"ref": anchor["ref"], "local": anchor["local"]}, "spawn_local": [spawn[0], spawn[1], ground],
             "drop_z": drop_z, "settle_ms": 8000,
             "points": [{k: p[k] for k in ("label", "x", "y", "expect")} for p in pts]}]
    expected = dict(expected, experiment="terrain_exp2b", anchor=anchor, spawn_local=plan[0]["spawn_local"],
                    overlay_records={"fnam": f"{n * n} raw u16 = SW-corner sample of every BTD cell ({n * n * 2} B)",
                                     "alignment": a.alignment, "hnam": a.hnam,
                                     "location": WORLD + "Location (LocTypeOverlay 2CA99D, parent SSol_PMars_Surface)",
                                     "mask": overlay_records.mask_rel(WORLD), "mars": mars})
    expected.pop("beyond", None)
    mk = overlay_records.write_mask(a.out, WORLD, n, a.mask_writer)
    for name, obj in (("plan.json", plan), ("expected.json", expected), ("exp2_params.json", params)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1)
    overlay_records.readme(a.out, "experiment 2b", params, plan[0], mk, [
        f"Real Commonwealth heights around Red Rocket as a native Starfield BTD ({n} x {n} cells, {len(data):,} bytes;",
        "the same BTD as experiment 2) with the overlay record fixes: SFBK FNAM = one raw cell-corner height per cell",
        f"({n * n * 2} B, was 16 B), Location {WORLD}Location (LocTypeOverlay, parent SSol_PMars_Surface), overlay mask,",
        f"alignment {a.alignment} (INAM {1 if a.alignment == 'absolute' else 0}, HNAM {a.hnam}), "
        + (f"registered on Mars by {MARS_PLUGIN} (latitude {a.mars_lat}, longitude {a.mars_lon})" if mars
           else "no planet registration") + ",",
        f"and a persistent anchor {ANCHOR_EDID}. Points are FO4 vertices: expect = FO4 height / 70 (hypothesis H).",
        "Never install together with experiment 1 (both Mars plugins override MarsPlanetData)."])
    t = btd.read(data)
    preview(t.heights_m(), n, pts, spawn, os.path.join(a.out, "preview.png"))
    print(f"plan: {len(pts)} points, drop_z {drop_z}, spawn_local {plan[0]['spawn_local']}, anchor {anchor}, "
          f"mask {mk['bytes']:,} B ({mk['pixels_differ']} px differ)")


def restage(a):
    """exp2b from an already staged experiment 2 (same BTD, points and spawn; no Fallout4.esm needed)."""
    exp = json.load(open(os.path.join(a.source, "expected.json")))
    data = open(os.path.join(a.source, "Data", "Terrain", BTD_NAME), "rb").read()
    if exp.get("btd_bytes") not in (None, len(data)):
        sys.exit("expected.json does not belong to this BTD")
    t = btd.read(data)
    os.makedirs(os.path.join(a.out, "Data", "Terrain"), exist_ok=True)
    with open(os.path.join(a.out, "Data", "Terrain", BTD_NAME), "wb") as f:
        f.write(data)
    stage(a, data, t.heights_raw, exp["points"], exp["spawn"]["pos_m"], exp["spawn"]["ground_m"], exp["drop_z"], exp)


def preview(dec, n, pts, spawn, path, size=928):
    from PIL import Image, ImageDraw
    k = dec.shape[0] // size
    img = dec[::k, ::k][::-1]
    lo, hi = float(img.min()), float(img.max())
    im = Image.fromarray(((img - lo) / max(hi - lo, 1e-6) * 255).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(im)
    o = tg.grid_origin(n)

    def px(x, y):
        return (x - o) / tg.SF_STEP_M / k, im.size[1] - 1 - (y - o) / tg.SF_STEP_M / k

    for i in range(n + 1):
        v = i * 128 / k
        d.line([(v, 0), (v, im.size[1])], fill=(70, 70, 90))
        d.line([(0, v), (im.size[0], v)], fill=(70, 70, 90))
    for p in pts:
        x, y = px(p["x"], p["y"])
        d.ellipse([x - 3, y - 3, x + 3, y + 3], outline=(255, 60, 60))
    x, y = px(*spawn[:2])
    d.rectangle([x - 4, y - 4, x + 4, y + 4], outline=(60, 220, 255))
    d.text((4, 4), f"N up, {n}x{n} cells, {lo:.0f}..{hi:.0f} m; red: check points, cyan: spawn", fill=(255, 255, 0))
    im.save(path)


# ---------------------------------------------------------------------------------------------------------- check
def check(a):
    """BTD summary, then the overlay check: decoded heights at every plan point and a raw record walk of both plugins
    (WRLD XLCN, LCTN keyword/parent, SFBK FNAM/INAM/HNAM, anchor, PNDT CNAM entry) plus the mask."""
    exp = json.load(open(os.path.join(a.out, "expected.json")))
    data = open(os.path.join(a.out, "Data", "Terrain", BTD_NAME), "rb").read()
    t = btd.read(data)
    n = t.ncx
    step = (t.hmax - t.hmin) / 65535.0
    print(f"BTD {len(data):,} B, {n} x {t.ncy} cells, range {t.hmin}..{t.hmax}, step {step * 1000:.3f} mm, "
          f"LTEX {['%08X' % x for x in t.ltex]}, quad {[int(v) for v in t.quad_map[0, 0]]}, "
          f"weights max {int(t.weights.max())}")
    sp = exp["spawn"]["pos_m"]
    print(f"spawn {sp}: ground {tg.btd_height_at(t.heights_m(), n, sp[0], sp[1]):.4f}")
    return overlay_records.run_check(a.out, "exp2_params.json", a.sf_data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "restage", "check"))
    ap.add_argument("--from", dest="source", help="restage: an already staged experiment 2 folder (BTD + expected.json)")
    ap.add_argument("--alignment", choices=("relative", "absolute"), default="absolute",
                    help="SFBK INAM: absolute (1, like NewAtlantis; default) or relative (0, like the LC overlays)")
    ap.add_argument("--hnam", type=int, default=0, help="SFBK HNAM height offset (NewAtlantis: -239)")
    ap.add_argument("--no-mars", action="store_true", help="no Mars registration plugin")
    ap.add_argument("--mars-lat", type=float, default=-1.2, help="Mutagen MasterWorldspace.Latitude (2nd f64 of the entry)")
    ap.add_argument("--mars-lon", type=float, default=0.3, help="Mutagen MasterWorldspace.Longitude (1st f64)")
    ap.add_argument("--mask-writer", choices=("texconv", "builtin"), default="texconv")
    ap.add_argument("--fo4", help="Fallout4.esm")
    ap.add_argument("--sf-data", required=True, help="Starfield Data folder (terrain BA2s)")
    ap.add_argument("--out", required=True, help="staging folder, e.g. C:\\Modding\\staging\\terrain_exp2")
    ap.add_argument("--margin", type=float, default=300.0, help="metres around the patch that must hold real heights")
    ap.add_argument("--extract", choices=("footprint", "region"), default="footprint",
                    help="FO4 cells to read: the whole BTD footprint (default) or only the region of interest "
                         "(the rest of the BTD then repeats the nearest FO4 edge height)")
    a = ap.parse_args()
    if a.cmd == "build":
        if not a.fo4:
            sys.exit("--fo4 is required for build")
        os.makedirs(a.out, exist_ok=True)
        return build(a)
    if a.cmd == "restage":
        if not a.source:
            sys.exit("--from is required for restage")
        os.makedirs(a.out, exist_ok=True)
        return restage(a)
    return check(a)


if __name__ == "__main__":
    sys.exit(main())
