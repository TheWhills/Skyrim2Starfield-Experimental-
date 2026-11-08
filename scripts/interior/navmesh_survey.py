"""Survey vanilla Starfield navmeshes: the values of the fields Skyrim's navmeshes do not have, so converted navmeshes
can use what the game itself uses (src/fo4sf/skyrimnavmesh.py DEFAULTS).

    python -I scripts\\interior\\navmesh_survey.py --esm "<Starfield>\\Data\\Starfield.esm" --out <folder> [--max 300]

Reads NAVM records inside interior cells (CELL top group -> blocks -> sub-blocks -> cell children) and writes
<out>\\navmesh_survey.json (value histograms, how triangle height relates to flags, edge-link types, grid divisors,
the trailing u16 pair) and <out>\\navmesh_defaults.json (the most common value of each unknown field), which
make_skyrim_interior.py export --navmesh-defaults reads.

    python -I scripts\\interior\\navmesh_survey.py --esm "<Starfield>\\Data\\Starfield.esm" --out <folder> --exterior

--exterior surveys navmeshes in exterior cells instead (worldspaces) and also measures what an exterior conversion
needs to know (docs/terrain/exterior-navmesh.md): whether the parent grid in NVNM is (Y, X) as xEdit reads it (against
the cell's XCLC), how many triangles lie outside their 100 m cell, which grid cell order rebuilds the game's own grids
(exteriornavmesh.grid_agreement), whether the grid bounds are the vertices' bounding box, divisor against triangle
count; and the NAVI (navmesh info map) records that register navmeshes with the pathfinder (form, entry count, the
unknown tail after the pathing cell, flags, islands; --navi-esm adds other plugins, e.g. the DLC, to see whether an
override carries only its own entries). Writes navmesh_survey_exterior.json and navmesh_defaults_exterior.json
(make_skyrim_navmesh.py export --navmesh-defaults).
"""
import argparse
import collections
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import exteriornavmesh, fo4land, skyrimnavmesh  # noqa: E402


def interior_navmeshes(esm, limit):
    """Yield (cell fid, navmesh fid, NVNM bytes) for up to `limit` navmeshes in interior cells."""
    n = 0
    with fo4land.Plugin(esm) as p:
        top = next((it for it in fo4land.iter_items(p.buf, p.body, len(p.buf))
                    if it[0] == "GRUP" and it[3] == b"CELL"), None)
        if top is None:
            return
        stack = [(top[1] + 24, top[2], None)]
        while stack:
            start, end, cell = stack.pop()
            for it in fo4land.iter_items(p.buf, start, end):
                if it[0] == "GRUP":
                    stack.append((it[1] + 24, it[2], cell))
                    continue
                typ, off, _flags, fid = it
                if typ == b"CELL":
                    cell = fid
                elif typ == b"NAVM":
                    for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                        if sig == b"NVNM":
                            yield cell, fid, bytes(d)
                            n += 1
                            break
                    if n >= limit:
                        return


def survey(esm, limit):
    hist = {k: collections.Counter() for k in ("vertex_unknown", "triangle_unknown", "edge_link_type", "edge_index",
                                                "grid_divisor", "tail", "version")}
    heights, height_by_flag = [], collections.defaultdict(list)
    errors, count, tris = [], 0, 0
    for cell, fid, data in interior_navmeshes(esm, limit):
        try:
            nm = skyrimnavmesh.parse_starfield(data)
        except skyrimnavmesh.NavmeshError as e:
            errors.append(f"{fid:08X}: {e}")
            continue
        count += 1
        hist["version"][nm["version"]] += 1
        hist["grid_divisor"][nm["grid"]["divisor"]] += 1
        hist["tail"][str(nm["tail"])] += 1
        for v in nm["vertices"]:
            hist["vertex_unknown"][v[3]] += 1
        for t in nm["triangles"]:
            tris += 1
            hist["triangle_unknown"][t["unknown"]] += 1
            heights.append(t["height"])
            for bit in (0x10, 0x20, 0x40, 0x200, 0x400):
                if t["flags"] & bit:
                    height_by_flag[hex(bit)].append(t["height"])
        for l in nm["edge_links"]:
            hist["edge_link_type"][l["type"]] += 1
            hist["edge_index"][l["edge"]] += 1
        if nm["trailing_bytes"]:
            errors.append(f"{fid:08X}: {nm['trailing_bytes']} bytes after the grid")

    def top(c, n=12):
        return [[k, v] for k, v in c.most_common(n)]
    report = {"navmeshes": count, "triangles": tris, "errors": errors[:50],
              "histograms": {k: top(v) for k, v in hist.items()},
              "triangle_height": {"min": min(heights, default=None), "max": max(heights, default=None),
                                  "median": statistics.median(heights) if heights else None,
                                  "most_common": top(collections.Counter(round(h, 3) for h in heights), 8),
                                  "median_by_flag": {k: statistics.median(v) for k, v in height_by_flag.items()}}}
    mode = lambda c, d: c.most_common(1)[0][0] if c else d      # noqa: E731
    tail = hist["tail"].most_common(1)[0][0] if hist["tail"] else "(0, 0)"
    defaults = {"vertex_unknown": mode(hist["vertex_unknown"], 0),
                "triangle_unknown": mode(hist["triangle_unknown"], 0),
                "triangle_height": report["triangle_height"]["median"] or 0.0,
                "tail": [int(x) for x in tail.strip("()").split(",") if x.strip() not in ("", "None")] or [0, 0],
                "from": f"{count} vanilla interior navmeshes"}
    return report, defaults


def survey_exterior(esm, limit):
    """Exterior navmeshes of every worldspace (up to `limit`): the measurements listed in the module doc."""
    parent = collections.Counter()
    outside, heights, agree, bounds_ok, div_pairs, errors = [], [], {o: [] for o in exteriornavmesh.GRID_ORDERS}, \
        collections.Counter(), collections.Counter(), []
    bounds_samples = []
    link_types, vertex_u, tri_u, tails, count, tris = (collections.Counter(), collections.Counter(),
                                                       collections.Counter(), collections.Counter(), 0, 0)
    for r in exteriornavmesh.read_starfield_exterior(esm, limit):
        nm = r["nm"]
        if "error" in nm:
            errors.append(f"{r['navmesh']:08X}: {nm['error']}")
            continue
        count += 1
        g = nm["parent"].get("grid")
        xy = tuple(r["cell_xy"]) if r["cell_xy"] else None
        parent["no grid" if g is None else "same as XCLC" if tuple(g) == xy else
               "swapped" if xy and tuple(g) == xy[::-1] else "other"] += 1
        sf_m = {"vertices": nm["vertices"], "triangles": nm["triangles"]}
        if xy:
            outside.append(exteriornavmesh.outside_cell(sf_m, xy, 100.0))
        for o in exteriornavmesh.GRID_ORDERS:
            agree[o].append(exteriornavmesh.grid_agreement(nm, o))
        if nm["vertices"]:
            vb = [min(v[i] for v in nm["vertices"]) for i in range(3)] + [max(v[i] for v in nm["vertices"])
                                                                          for i in range(3)]
            gb = nm["grid"]["bounds"]
            kind = "bbox" if max(abs(a - b) for a, b in zip(vb, gb)) < 0.01 else "other"
            if kind == "other" and xy and abs(gb[0] - xy[0] * 100.0) < 0.01 and abs(gb[1] - xy[1] * 100.0) < 0.01 \
                    and abs(gb[3] - gb[0] - 100.0) < 0.01:
                kind = "cell square"
            bounds_ok[kind] += 1
            if len(bounds_samples) < 8:
                bounds_samples.append({"cell": xy, "bounds": [round(x, 2) for x in gb],
                                       "vertex_bbox": [round(x, 2) for x in vb], "divisor": nm["grid"]["divisor"],
                                       "size": [round(x, 3) for x in nm["grid"]["size"]]})
        div_pairs[(nm["grid"]["divisor"], min(len(nm["triangles"]) // 50 * 50, 2000))] += 1
        tails[str(nm["tail"])] += 1
        for t in nm["triangles"]:
            tris += 1
            heights.append(t["height"])
            tri_u[t["unknown"]] += 1
        for v in nm["vertices"]:
            vertex_u[v[3]] += 1
        for l in nm["edge_links"]:
            link_types[l["type"]] += 1
    mean = lambda v: round(sum(v) / len(v), 4) if v else None              # noqa: E731
    order = max(exteriornavmesh.GRID_ORDERS, key=lambda o: mean(agree[o]) or 0)
    report = {"navmeshes": count, "triangles": tris, "errors": errors[:50],
              "parent_grid_vs_xclc": dict(parent),
              "outside_own_cell": {"mean": mean(outside), "max": max(outside, default=None),
                                   "navmeshes_over_5pct": sum(o > 0.05 for o in outside)},
              "grid_agreement": {o: {"mean": mean(v), "exact": sum(x == 1.0 for x in v)} for o, v in agree.items()},
              "grid_bounds": dict(bounds_ok), "grid_bounds_samples": bounds_samples,
              "divisor_by_triangles": sorted([[d, t, n] for (d, t), n in div_pairs.items()]),
              "edge_link_types": [[k, v] for k, v in link_types.most_common(8)],
              "triangle_height": {"min": min(heights, default=None), "max": max(heights, default=None),
                                  "median": statistics.median(heights) if heights else None,
                                  "most_common": [[k, v] for k, v in collections.Counter(
                                      round(h, 3) for h in heights).most_common(8)]}}
    mode = lambda c, d: c.most_common(1)[0][0] if c else d      # noqa: E731
    tail = mode(tails, "(0, 0)")
    defaults = {"vertex_unknown": mode(vertex_u, 0), "triangle_unknown": mode(tri_u, 0),
                "exterior_triangle_height": report["triangle_height"]["median"],
                "tail": [int(x) for x in tail.strip("()").split(",") if x.strip() not in ("", "None")] or [0, 0],
                "grid_order": order, "from": f"{count} vanilla exterior navmeshes"}
    return report, defaults


def survey_navi(esms):
    """{plugin: [{form, version, entries, errors, flags, tails, islands, traversals, interior, exterior}]}"""
    out = {}
    for esm in esms:
        recs = []
        for r in exteriornavmesh.read_navi(esm):
            infos = [i for i in r["infos"] if "error" not in i]
            recs.append({"form": f"{r['form']:08X}", "version": r["version"], "entries": len(r["infos"]),
                         "errors": [i["error"] for i in r["infos"] if "error" in i][:5],
                         "crc_ok": sum(i["crc"] == skyrimnavmesh.PATHING_CELL for i in infos),
                         "flags": [[k, v] for k, v in collections.Counter(i["flags"] for i in infos).most_common(6)],
                         "tails": [[k, v] for k, v in collections.Counter(i["tail"] for i in infos).most_common(6)],
                         "islands": sum(i["island"] for i in infos), "traversals": sum(i["traversals"] for i in infos),
                         "exterior": sum("grid" in i["parent"] for i in infos),
                         "interior": sum("cell" in i["parent"] for i in infos), "has_nvpp": r["has_nvpp"]})
        out[os.path.basename(esm)] = recs
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esm", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--exterior", action="store_true", help="survey exterior (worldspace) navmeshes instead")
    ap.add_argument("--navi-esm", action="append", default=[],
                    help="--exterior: another plugin whose NAVI to survey too (repeatable; e.g. the DLC's esm)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    if a.exterior:
        report, defaults = survey_exterior(a.esm, a.max)
        report["navi"] = survey_navi([a.esm] + a.navi_esm)
        for name, obj in (("navmesh_survey_exterior.json", report), ("navmesh_defaults_exterior.json", defaults)):
            with open(os.path.join(a.out, name), "w", encoding="utf-8") as fh:
                json.dump(obj, fh, indent=1)
        print(f"{report['navmeshes']} exterior navmeshes, {report['triangles']} triangles; parent grid vs XCLC "
              f"{report['parent_grid_vs_xclc']}; outside their cell {report['outside_own_cell']}; grid order "
              f"{report['grid_agreement']}; bounds {report['grid_bounds']}; defaults {defaults}; NAVI "
              f"{ {k: [(r['form'], r['entries'], r['tails'][:1]) for r in v] for k, v in report['navi'].items()} }")
        return 0
    report, defaults = survey(a.esm, a.max)
    with open(os.path.join(a.out, "navmesh_survey.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    with open(os.path.join(a.out, "navmesh_defaults.json"), "w", encoding="utf-8") as fh:
        json.dump(defaults, fh, indent=1)
    print(f"{report['navmeshes']} navmeshes, {report['triangles']} triangles; defaults {defaults}; "
          f"{len(report['errors'])} problems")
    return 0


if __name__ == "__main__":
    sys.exit(main())
