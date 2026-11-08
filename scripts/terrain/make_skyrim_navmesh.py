"""Skyrim's exterior navmeshes on the Starfield exterior, and a comparison of the two (docs/terrain/exterior-navmesh.md).

    python -I scripts\\terrain\\make_skyrim_navmesh.py export  --skyrim <Skyrim.esm> --exterior <staged exterior>
           --out <work> [--around Riverwood --radius 2] [--navmesh-defaults <navmesh_defaults.json>] [--no-split]
    python -I scripts\\terrain\\make_skyrim_navmesh.py compare --skyrim <Skyrim.esm> --work <work>
           --plugin <FO4Port.esm> [--source-map <source_map.json>]

export   the NAVM records of the Skyrim cells around --around, moved into the exterior's frame (overlays_params.json:
         Skyrim units / 70 - origin_cw_m, z + height_offset_m) and split at Starfield's 100 m cells
         (exteriornavmesh.split_to_cells) -> <out>/exterior_navmesh.json, which PluginSpike writes into FO4Port.esm
         (EXTERIOR_NAVMESH=<that file>, with EXTERIOR_DIR). Also <out>/export_report.json.
compare  reads the navmeshes back out of the built plugin and Skyrim's again: vertex offsets against Skyrim's (moved into
         the frame), triangle counts, parent cell (the navmesh's grid against its CELL's XCLC), triangles outside
         their cell, edge links that do not meet the triangle they name, door links, the height above the terrain
         (Skyrim's LAND + height_offset_m, which the exterior's BTD is built from) on both sides; and the pathing
         registration: each navmesh's NAVI entry (present, same parent / edge-link navmeshes / doors as its NVNM)
         and each load door's XNDP (names a navmesh triangle that lists that door)
         -> <work>/compare.json and <work>/compare.html (top-down: Skyrim's navmesh, ours, the cell grids, problems).
Everything this writes stays outside the repo (derived game data).
"""
import argparse
import html
import json
import math
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import exteriornavmesh as en, fo4land, skyrimnavmesh  # noqa: E402

U = en.UNITS


def frame_of(exterior):
    """(origin_cw_m, height_offset_m) of the installed exterior (overlays_params.json, first overlay)."""
    with open(os.path.join(exterior, "overlays_params.json"), encoding="utf-8") as fh:
        ov = json.load(fh)["overlays"][0]
    return [float(v) for v in ov["origin_cw_m"]], float(ov.get("height_offset_m") or 0.0)


def skyrim_rect(esm, around, radius):
    from make_skyrim_objects import around_cells
    return around_cells(esm, around, radius)


def load_defaults(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return {k: d[k] for k in ("vertex_unknown", "triangle_unknown", "triangle_height", "tail",
                             "exterior_triangle_height", "grid_order") if k in d}


def exported_geometry(geo):
    """The geometry as PluginSpike reads it (WriteNavmeshes: positions in units, grid_raw, tail_int32)."""
    g = dict(geo)
    g["grid_raw"], g["tail_int32"] = skyrimnavmesh.grid_shorts(g), skyrimnavmesh.tail_int32(g)
    g["grid"] = dict(g["grid"], cells=None)
    g.pop("dropped", None)
    return g


def cmd_export(a):
    t0 = time.time()
    rect = skyrim_rect(a.skyrim, a.around, a.radius)
    origin, hoff = frame_of(a.exterior)
    defaults = load_defaults(a.navmesh_defaults) or {}
    ext_height = defaults.pop("exterior_triangle_height", None)
    order = a.grid_order or defaults.pop("grid_order", None) or "yx"
    defaults.pop("grid_order", None)
    navs, bad = en.read_skyrim(a.skyrim, a.world_edid, rect, defaults=defaults)
    height = a.triangle_height if a.triangle_height is not None else (ext_height if ext_height is not None
                                                                      else en.FLT_MAX)
    moved = []
    for n in navs:
        g = en.frame_shift(n["geometry"], origin, hoff)
        g["triangles"] = [dict(t, height=height) for t in g["triangles"]]
        moved.append({"formkey": n["formkey"], "geometry": g})
    res = en.split_to_cells(moved, split=not a.no_split, order=order)
    # vanilla exterior grids: bounds = the vertices' box except the top, which is FLT_MAX (navmesh_survey.py
    # grid_bounds_samples, 2026-11-08: 8 of 8 samples, the rest "cell square" ones the same way)
    for p in res["navmeshes"]:
        b = list(p["geometry"]["grid"]["bounds"])
        if len(b) == 6:
            p["geometry"]["grid"] = dict(p["geometry"]["grid"], bounds=tuple(b[:5]) + (en.FLT_MAX,))
    with open(os.path.join(a.exterior, "formids.json"), encoding="utf-8") as fh:
        world = json.load(fh).get("world")
    out = {"schema": 1, "world": world, "frame": {"origin_cw_m": origin, "height_offset_m": hoff},
           "skyrim_cells": list(rect), "split": not a.no_split, "grid_order": order,
           "triangle_height": height,
           "navmeshes": [{"key": p["key"], "cell": p["cell"], "source": p["source"],
                          "geometry": exported_geometry(p["geometry"])} for p in res["navmeshes"]]}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "exterior_navmesh.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    links = en.edge_link_problems({p["key"]: p["geometry"] for p in res["navmeshes"]}, tol=2.0)
    before = en.edge_link_problems({n["formkey"]: n["geometry"] for n in moved}, tol=2.0)   # Skyrim's own, unsplit
    report = {"skyrim_cells": list(rect), "skyrim_navmeshes": len(navs), "unreadable": bad,
              "problems": {n["formkey"]: n["problems"] for n in navs if n["problems"]},
              "stats": res["stats"], "edge_links_after_split": dict(links, examples=links["examples"][:5]),
              "edge_links_skyrim": dict(before, examples=before["examples"][:5]),
              "triangles": sum(len(p["geometry"]["triangles"]) for p in res["navmeshes"]),
              "cells": sorted({tuple(p["cell"]) for p in res["navmeshes"]}), "seconds": round(time.time() - t0, 1)}
    with open(os.path.join(a.out, "export_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    s = res["stats"]
    print(f"{len(navs)} Skyrim navmeshes in cells {rect} -> {s['navmeshes']} Starfield navmeshes in {s['cells']} cells "
          f"({s['split']} split; links kept {s['links_kept']}, added {s['links_added']}, cut at the region edge "
          f"{s['links_cut']}; door links {s['doors']}); {report['triangles']} triangles; edge links more than 2 units "
          f"off their triangle: ours {links['mismatch']} of {links['links']} (split seams "
          f"{links['by_kind']['seam']['mismatch']} of {links['by_kind']['seam']['links']}), Skyrim's own "
          f"{before['mismatch']} of {before['links']} (gap median {before['gaps']['median']}, max "
          f"{before['gaps']['max']}); unreadable {len(bad)} -> {a.out}\\exterior_navmesh.json")
    return 0


# --------------------------------------------------------------------------------------------------------- compare
def terrain(esm, world, rect):
    """(merged heights in units, origin x, origin y) of the Skyrim cells in rect (plus one ring)."""
    x0, x1, y0, y1 = rect[0] - 1, rect[1] + 1, rect[2] - 1, rect[3] + 1
    want = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    with fo4land.Plugin(esm) as p:
        w = p.read_world(world, cells=want, refs=False)
    grids = {xy: fo4land.decode_vhgt(c["vhgt"]) for xy, c in w["cells"].items() if c.get("vhgt")}
    from fo4sf import skyrimland
    fill = min(float(g.min()) for g in grids.values()) if grids else 0.0
    g = skyrimland.merge_with_fill(grids, x0, x1, y0, y1, fill)
    return g, x0 * en.SKY_CELL, y0 * en.SKY_CELL


def above_ground(verts, ground, dz=0.0):
    """Vertex height above the terrain (units); vertices given in Skyrim's own frame plus dz."""
    g, ox, oy = ground
    out = []
    for v in verts:
        h = fo4land.height_at(g, ox, oy, v[0], v[1])
        if h is not None:
            out.append(v[2] - dz - h)
    return out


def dist(vals):
    if not vals:
        return None
    s = sorted(vals)
    q = lambda f: round(s[min(len(s) - 1, int(f * (len(s) - 1)))], 3)        # noqa: E731
    return {"n": len(s), "min": round(s[0], 3), "p5": q(0.05), "median": q(0.5), "p95": q(0.95), "max": round(s[-1], 3)}


def cmd_compare(a):
    with open(os.path.join(a.work, "exterior_navmesh.json"), encoding="utf-8") as fh:
        exp = json.load(fh)
    origin, hoff = exp["frame"]["origin_cw_m"], exp["frame"]["height_offset_m"]
    rect = exp["skyrim_cells"]
    smap_path = a.source_map or os.path.join(os.path.dirname(os.path.abspath(a.plugin)), "source_map.json")
    with open(smap_path, encoding="utf-8") as fh:
        smap = json.load(fh)
    # our FormIDs (low 24 bits; FO4Port's own records) -> export key
    key_of = {}
    for k, v in smap.items():
        try:
            key_of[int(str(v).split(":")[0], 16) & 0xFFFFFF] = k
        except ValueError:
            pass
    sky, _bad = en.read_skyrim(a.skyrim, a.world_edid, rect)
    sky_moved = {n["formkey"]: en.frame_shift(n["geometry"], origin, hoff) for n in sky}
    ours = {}
    raw = {}                    # our key -> (navmesh FormID, parent, edge-link FormIDs, door FormIDs, door triangles)
    parent_bad, parse_bad = [], []
    for r in en.read_starfield_exterior(a.plugin):
        key = key_of.get(r["navmesh"] & 0xFFFFFF, f"{r['navmesh']:08X}")
        nm = r["nm"]
        if "error" in nm:
            parse_bad.append({"navmesh": key, "error": nm["error"]})
            continue
        par = nm["parent"]
        if "grid" not in par or tuple(par["grid"]) != tuple(r["cell_xy"] or ()):
            parent_bad.append({"navmesh": key, "parent": par.get("grid"), "cell_xclc": r["cell_xy"]})
        raw[key] = (r["navmesh"], par, {l["navmesh"] for l in nm["edge_links"]} - {r["navmesh"]},
                    {d["door"] for d in nm["door_links"]}, {(d["door"], d["triangle"]) for d in nm["door_links"]})
        for l in nm["edge_links"]:
            l["navmesh"] = key_of.get(l["navmesh"] & 0xFFFFFF, f"{l['navmesh']:08X}")
        ours[key] = dict(nm, cell=r["cell_xy"])
    # metres -> units for one comparison space (Starfield frame, Skyrim units)
    ours_u = {k: dict(g, vertices=[(v[0] * U, v[1] * U, v[2] * U) for v in g["vertices"]]) for k, g in ours.items()}
    sky_pts = [v for g in sky_moved.values() for v in g["vertices"]]
    our_pts = [v for g in ours_u.values() for v in g["vertices"]]
    off = en.nearest_offsets(sky_pts, our_pts)
    back = en.nearest_offsets(our_pts, sky_pts)
    expected = {p["key"] for p in exp["navmeshes"]}
    ground = terrain(a.skyrim, a.world_edid, rect)
    dz = hoff * U
    sky_h = above_ground([v for n in sky for v in n["geometry"]["vertices"]], ground)
    # ours are in the Starfield frame: back into Skyrim's for the terrain lookup (x + origin, z - height offset)
    our_h = above_ground([(v[0] + origin[0] * U, v[1] + origin[1] * U, v[2]) for v in our_pts], ground, dz)
    out_frac = {k: round(en.outside_cell(g, g["cell"], tg_cell_units()), 3) for k, g in ours_u.items() if g["cell"]}
    sky_out = {n["formkey"]: round(en.outside_cell(n["geometry"], n["skyrim_cell"], en.SKY_CELL), 3) for n in sky}
    rep = {
        "plugin": os.path.basename(a.plugin), "skyrim_cells": rect, "frame": exp["frame"],
        "navmeshes": {"skyrim": len(sky), "exported": len(expected), "in_plugin": len(ours),
                      "missing": sorted(expected - set(ours))[:20], "unexpected": sorted(set(ours) - expected)[:20]},
        "triangles": {"skyrim": sum(len(g["triangles"]) for g in sky_moved.values()),
                      "plugin": sum(len(g["triangles"]) for g in ours.values())},
        "vertex_offset_m": {"skyrim_to_ours": dist([d / U for d in off]), "ours_to_skyrim": dist([d / U for d in back])},
        "parent_cell_mismatch": {"count": len(parent_bad), "examples": parent_bad[:10]},
        "unreadable": parse_bad[:10],
        "outside_parent_cell": {"ours_max": max(out_frac.values(), default=0.0),
                                "ours_navmeshes_over_5pct": sum(v > 0.05 for v in out_frac.values()),
                                "skyrim_max": max(sky_out.values(), default=0.0)},
        "edge_links": {"ours": en.edge_link_problems(ours_u, tol=2.0),
                       "skyrim": en.edge_link_problems({k: g for k, g in sky_moved.items()}, tol=2.0)},
        "door_links": {"skyrim": sum(len(g["door_links"]) for g in sky_moved.values()),
                       "plugin": sum(len(g["door_links"]) for g in ours.values())},
        "height_above_terrain_m": {"skyrim": dist([h / U for h in sky_h]), "ours": dist([h / U for h in our_h])},
    }
    rep["pathing"] = pathing_checks(a.plugin, raw)
    with open(os.path.join(a.work, "compare.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    write_html(os.path.join(a.work, "compare.html"), sky_moved, ours_u, rep, rect, origin)
    o = rep["vertex_offset_m"]["skyrim_to_ours"] or {}
    print(f"navmeshes: Skyrim {len(sky)}, exported {len(expected)}, in the plugin {len(ours)} "
          f"(missing {len(expected - set(ours))}); triangles {rep['triangles']['skyrim']} / {rep['triangles']['plugin']}; "
          f"vertex offset median {o.get('median')} m, max {o.get('max')} m; parent cell wrong {len(parent_bad)}; "
          f"edge links not meeting their triangle: ours {rep['edge_links']['ours']['mismatch']}, Skyrim "
          f"{rep['edge_links']['skyrim']['mismatch']}; door links {rep['door_links']['skyrim']} / "
          f"{rep['door_links']['plugin']}; height above ground median Skyrim "
          f"{(rep['height_above_terrain_m']['skyrim'] or {}).get('median')} m, ours "
          f"{(rep['height_above_terrain_m']['ours'] or {}).get('median')} m; NAVI entries "
          f"{rep['pathing']['navi']['ours_listed']} / {len(raw)} (wrong {rep['pathing']['navi']['mismatch']}); load doors "
          f"with XNDP to a door triangle {rep['pathing']['xndp']['to_door_triangle']} / {rep['pathing']['xndp']['load_doors']} "
          f"-> {a.work}\\compare.html")
    return 0


def pathing_checks(plugin, raw):
    """NAVI entries and load-door XNDP of the built plugin against its navmeshes (raw FormIDs as written)."""
    navi = en.read_navi(plugin)
    infos = {i["navmesh"]: i for r in navi for i in r["infos"] if "error" not in i}
    by_id = {v[0]: k for k, v in raw.items()}
    listed, mismatch, examples = 0, 0, []
    for key, (fid, par, edges, doors, _dt) in raw.items():
        i = infos.get(fid)
        if i is None:
            continue
        listed += 1
        problems = []
        if i["parent"] != ({"world": par["world"], "grid": tuple(par["grid"])} if "grid" in par else par):
            problems.append(f"parent {i['parent']} vs NVNM {par}")
        if set(i["edge_links"]) | set(i["preferred_edge_links"]) != edges:
            problems.append(f"edge links {len(i['edge_links'])} vs NVNM {len(edges)} navmeshes")
        if {d for _c, d in i["door_links"]} != doors:
            problems.append(f"doors {len(i['door_links'])} vs NVNM {len(doors)}")
        if i["tail"] != "0000000000":                 # what 79 % of vanilla NVMI end with (survey)
            problems.append(f"tail {i['tail']}")
        if i["crc"] != skyrimnavmesh.PATHING_CELL:
            problems.append(f"pathing cell CRC {i['crc']:08X}")
        if problems:
            mismatch += 1
            if len(examples) < 10:
                examples.append({"navmesh": key, "problems": problems})
    door_tris, all_navs = {}, set()           # every navmesh of the plugin (interiors too): door -> (navmesh, triangle)
    for _t, nfid, _flags, subs in en.iter_records(plugin, (b"NAVM",)):
        data = next((d for sig, d in subs if sig == b"NVNM"), None)
        try:
            nm = skyrimnavmesh.parse_starfield(data or b"")
        except skyrimnavmesh.NavmeshError:
            continue
        all_navs.add(nfid)
        for dl in nm["door_links"]:
            door_tris.setdefault(dl["door"], set()).add((nfid, dl["triangle"]))
    x = {"load_doors": 0, "with_xndp": 0, "to_our_navmesh": 0, "to_door_triangle": 0, "examples": []}
    for _t, fid, _flags, subs in en.iter_records(plugin, (b"REFR",)):
        sigs = {sig: d for sig, d in subs}
        if b"XTEL" not in sigs:
            continue
        x["load_doors"] += 1
        d = sigs.get(b"XNDP")
        if d is None or len(d) < 6:
            continue
        x["with_xndp"] += 1
        nav, tri = struct.unpack_from("<Ih", d)
        if nav in all_navs:
            x["to_our_navmesh"] += 1
        if (nav, tri) in door_tris.get(fid, ()):
            x["to_door_triangle"] += 1
        elif len(x["examples"]) < 10:
            x["examples"].append({"door": f"{fid:08X}", "navmesh": by_id.get(nav, f"{nav:08X}"), "triangle": tri})
    x["navmeshes_in_plugin"] = len(all_navs)
    x["navmeshes_without_navi"] = len(all_navs - set(infos))
    return {"navi": {"records": [f"{r['form']:08X}" for r in navi], "entries": sum(len(r["infos"]) for r in navi),
                     "ours_listed": listed, "mismatch": mismatch, "examples": examples}, "xndp": x}


def tg_cell_units():
    return en.tg.SF_CELL_M * U


COLOURS = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#76b7b2", "#edc948", "#9c755f", "#e15759"]


def write_html(path, sky, ours, rep, rect, origin):
    """Top-down SVG (north up, metres in the Starfield frame) with toggles: Skyrim's triangles (outlines), ours (filled
    per navmesh), the Skyrim and Starfield cell grids, door triangles, edge links that miss their triangle."""
    pts = [v for g in list(sky.values()) + list(ours.values()) for v in g["vertices"]]
    if not pts:
        pts = [(0, 0, 0)]
    xs, ys = [p[0] / U for p in pts], [p[1] / U for p in pts]
    x0, x1, y0, y1 = min(xs) - 5, max(xs) + 5, min(ys) - 5, max(ys) + 5
    W = 1400
    s = W / max(1e-6, x1 - x0)
    H = int((y1 - y0) * s) + 1
    X = lambda x: round((x / U - x0) * s, 1)            # noqa: E731
    Y = lambda y: round((y1 - y / U) * s, 1)            # noqa: E731

    def tri_path(g):
        V = g["vertices"]
        return "".join(f"M{X(V[a][0])} {Y(V[a][1])}L{X(V[b][0])} {Y(V[b][1])}L{X(V[c][0])} {Y(V[c][1])}Z"
                       for a, b, c in (t["v"] for t in g["triangles"]))

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
             '<rect width="100%" height="100%" fill="#1b1d21"/>']
    parts.append('<g class="ours">')
    for i, (k, g) in enumerate(sorted(ours.items())):
        parts.append(f'<path d="{tri_path(g)}" fill="{COLOURS[i % len(COLOURS)]}" fill-opacity="0.45" stroke="none">'
                     f'<title>{html.escape(k)} cell {g.get("cell")}: {len(g["triangles"])} triangles</title></path>')
    parts.append('</g><g class="sky">')
    for k, g in sorted(sky.items()):
        parts.append(f'<path d="{tri_path(g)}" fill="none" stroke="#f4f4f4" stroke-width="0.5"><title>'
                     f'{html.escape(k)}</title></path>')
    parts.append('</g><g class="doors">')
    for g in ours.values():
        V = g["vertices"]
        for d in g["door_links"]:
            if 0 <= d["triangle"] < len(g["triangles"]):
                a, b, c = g["triangles"][d["triangle"]]["v"]
                parts.append(f'<path d="M{X(V[a][0])} {Y(V[a][1])}L{X(V[b][0])} {Y(V[b][1])}L{X(V[c][0])} '
                             f'{Y(V[c][1])}Z" fill="#ffd400"/>')
    parts.append('</g><g class="bad">')
    for ex in rep["edge_links"]["ours"]["examples"]:
        g = ours.get(ex["navmesh"])
        if g:
            t = g["triangles"][ex["triangle"]]
            a, b = g["vertices"][t["v"][ex["edge"]]], g["vertices"][t["v"][(ex["edge"] + 1) % 3]]
            parts.append(f'<line x1="{X(a[0])}" y1="{Y(a[1])}" x2="{X(b[0])}" y2="{Y(b[1])}" stroke="#ff2020" '
                         f'stroke-width="4"/>')
    parts.append('</g><g class="sfgrid" stroke="#00e0ff" stroke-width="1" stroke-dasharray="6 4">')
    for gx in range(int(math.floor(x0 / 100)), int(math.ceil(x1 / 100)) + 1):
        parts.append(f'<line x1="{X(gx * 100 * U)}" y1="0" x2="{X(gx * 100 * U)}" y2="{H}"/>')
    for gy in range(int(math.floor(y0 / 100)), int(math.ceil(y1 / 100)) + 1):
        parts.append(f'<line x1="0" y1="{Y(gy * 100 * U)}" x2="{W}" y2="{Y(gy * 100 * U)}"/>')
    parts.append('</g><g class="skygrid" stroke="#ff9de2" stroke-width="1">')
    sc = en.SKY_CELL / U
    for cx in range(rect[0], rect[1] + 2):
        x = (cx * sc - origin[0]) * U
        parts.append(f'<line x1="{X(x)}" y1="0" x2="{X(x)}" y2="{H}"/>')
    for cy in range(rect[2], rect[3] + 2):
        y = (cy * sc - origin[1]) * U
        parts.append(f'<line x1="0" y1="{Y(y)}" x2="{W}" y2="{Y(y)}"/>')
    parts.append("</g></svg>")
    toggles = "".join(f'<label><input type="checkbox" checked data-g="{c}"> {t}</label>' for c, t in (
        ("ours", "ours (Starfield, one colour per navmesh)"), ("sky", "Skyrim (white outlines)"),
        ("doors", "door triangles"), ("bad", "edge links that miss"), ("sfgrid", "Starfield cells (100 m)"),
        ("skygrid", "Skyrim cells (58.5 m)")))
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Navmesh compare</title>
<style>body{{background:#111;color:#ddd;font:14px system-ui;margin:16px}}label{{margin-right:14px}}
pre{{background:#1b1d21;padding:8px;overflow:auto;max-height:260px}}svg{{max-width:100%;height:auto}}</style></head><body>
<h3>Skyrim navmesh vs converted (top-down, north up)</h3><div>{toggles}</div>
<pre>{html.escape(json.dumps({k: rep[k] for k in ("navmeshes", "triangles", "vertex_offset_m", "parent_cell_mismatch",
                                                  "outside_parent_cell", "door_links", "height_above_terrain_m")},
                                indent=1))}</pre>
{''.join(parts)}
<script>for(const c of document.querySelectorAll('input[data-g]'))c.onchange=()=>{{for(const g of document.querySelectorAll('g.'+c.dataset.g))g.style.display=c.checked?'':'none'}}</script>
</body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("export", "compare"))
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--world-edid", default="Tamriel")
    ap.add_argument("--around", default="Riverwood", help="export: exterior cell EditorID or X,Y (default Riverwood)")
    ap.add_argument("--radius", type=int, default=2, help="export: Skyrim cells each side (default 2: 5 x 5)")
    ap.add_argument("--exterior", help="export: the installed staged exterior (formids.json, overlays_params.json)")
    ap.add_argument("--out", help="export: work folder")
    ap.add_argument("--navmesh-defaults", default="", help="export: navmesh_survey.py's navmesh_defaults.json")
    ap.add_argument("--triangle-height", type=float, default=None,
                    help="export: clear height over every triangle (default: the survey's exterior value, else none)")
    ap.add_argument("--no-split", action="store_true", help="export: keep each Skyrim navmesh whole (A/B)")
    ap.add_argument("--grid-order", choices=en.GRID_ORDERS, default=None,
                    help="export: grid cell order of rebuilt grids (default: the survey's, else yx)")
    ap.add_argument("--work", help="compare: the export's work folder")
    ap.add_argument("--plugin", help="compare: the built FO4Port.esm")
    ap.add_argument("--source-map", default="", help="compare: PluginSpike's source_map.json (default: next to it)")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        if not (a.exterior and a.out):
            ap.error("export needs --exterior and --out")
        return cmd_export(a)
    if not (a.work and a.plugin):
        ap.error("compare needs --work and --plugin")
    return cmd_compare(a)


if __name__ == "__main__":
    sys.exit(main())
