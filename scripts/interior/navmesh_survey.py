"""Survey vanilla Starfield navmeshes: the values of the fields Skyrim's navmeshes do not have, so converted navmeshes
can use what the game itself uses (src/fo4sf/skyrimnavmesh.py DEFAULTS).

    python -I scripts\\interior\\navmesh_survey.py --esm "<Starfield>\\Data\\Starfield.esm" --out <folder> [--max 300]

Reads NAVM records inside interior cells (CELL top group -> blocks -> sub-blocks -> cell children) and writes
<out>\\navmesh_survey.json (value histograms, how triangle height relates to flags, edge-link types, grid divisors,
the trailing u16 pair) and <out>\\navmesh_defaults.json (the most common value of each unknown field), which
make_skyrim_interior.py export --navmesh-defaults reads.
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

from fo4sf import fo4land, skyrimnavmesh  # noqa: E402


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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esm", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=300)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
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
