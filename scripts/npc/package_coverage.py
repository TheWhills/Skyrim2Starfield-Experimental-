"""Which furniture each NPC's packages can reach: the package's area (a reference and radius, or a cell) against the
furniture references we place (read-only).

2026-11-16 (owner): "do we know if their schedules are aligned to even work with that, why isn't she using the tanning
rack anymore, or leaning on the railing". A sandbox only picks furniture inside its location's radius; Skyrim's radius
is converted as is (make_schedule radius_m). This prints, per NPC and package (hours, Skyrim template -> Starfield's),
the location (where, radius) and every furniture reference inside it with its kind and animation set, so an area
that misses the forge, the tanning rack or the rail is seen.

    python -I scripts\\npc\\package_coverage.py --work "<work>\\riverwood_doors"     (actors.json + furniture.json)
"""
import argparse
import json
import math
import os
import sys

U = 0.0142875                     # metres per Skyrim unit


def location_inputs(pkg) -> list:
    return [v for v in (pkg.get("inputs") or {}).values() if isinstance(v, dict) and v.get("kind") == "location"]


def furniture_in(loc, refs, bases, home_cell=None) -> list:
    """[(distance m or None, kind, set, base edid, ref)] of the furniture references inside a location: near a
    reference (same cell, or both outdoors) within radius_m, or anywhere in its cell."""
    out = []
    t = loc.get("type")
    for r in refs:
        b = bases.get(r["base"], {})
        row = (b.get("kind"), b.get("anim_set"), b.get("edid"), r["formkey"])
        if t == "in_cell":
            if r["cell"] == loc.get("cell"):
                out.append((None,) + row)
        elif t in ("near_reference", "near_exterior_reference") and loc.get("pos"):
            cell = "exterior" if t == "near_exterior_reference" else loc.get("cell")
            if r["cell"] != cell:
                continue
            d = math.dist(loc["pos"][:2], r["pos"][:2]) * U
            if d <= (loc.get("radius_m") or 0):
                out.append((round(d, 1),) + row)
    return sorted(out, key=lambda x: (x[0] is None, x[0] or 0))


def report(actors, furn, names=None) -> list:
    lines = []
    bases, refs = furn["bases"], furn["refs"]
    for a in actors:
        if names and a.get("name") not in names and a.get("skyrim") not in names:
            continue
        lines.append(f"== {a.get('name')} ({a.get('skyrim')})")
        for p in a.get("packages", []):
            s = p.get("schedule") or {}
            locs = location_inputs(p)
            lines.append(f"  {p['edid']}: {p.get('skyrim_template')} -> {p.get('sf_template')}, "
                         f"schedule {json.dumps(s)}")
            for loc in locs:
                where = loc.get("type")
                if loc.get("pos"):
                    where += f" {loc.get('base')} {loc.get('source')} in {loc.get('cell')}"
                elif loc.get("cell"):
                    where += f" {loc['cell']}"
                hits = furniture_in(loc, refs, bases)
                lines.append(f"    {loc.get('skyrim')}: {where}, radius {loc.get('radius_m')} m -> {len(hits)} furniture")
                for d, kind, st, edid, fk in hits:
                    lines.append(f"      {'' if d is None else f'{d} m '}{kind} {edid}{' [' + st + ']' if st else ''} {fk}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True, help="the build's work folder holding actors.json and furniture.json")
    ap.add_argument("--npc", action="append", default=[], help="only these NPCs (name or Skyrim EditorID; repeatable)")
    a = ap.parse_args(argv)
    with open(os.path.join(a.work, "actors.json"), encoding="utf-8") as fh:
        actors = json.load(fh)
    actors = actors.get("actors", actors) if isinstance(actors, dict) else actors
    with open(os.path.join(a.work, "furniture.json"), encoding="utf-8") as fh:
        furn = json.load(fh)
    print("\n".join(report(actors, furn, set(a.npc) or None)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
