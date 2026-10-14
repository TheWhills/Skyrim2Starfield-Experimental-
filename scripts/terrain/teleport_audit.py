"""Teleports of finished terrain tests, by how many cells they moved the player along an axis (docs/terrain/core64c.md,
"Teleport rule").

    python scripts/terrain/teleport_audit.py <queue dir> [<queue dir> ...] [--json <out.json>]

A queue dir is a runner queue (scripts/game/testqueue.py plan-terrain --out ...): tests\\<id>\\a<n>\\spec.json + obs.json.
Every teleport qstep.ps1 made is rebuilt from the spec (the merge offset from obs.json, hops as qstep makes them: none
before the first point, ceil(d / hop_m) equal teleports per later leg) and judged by the read that follows it:
  RELOC   the read is more than 500 m from the target in x or y ("Boundary Reached" moved the player)
  HUNG    the read is at the drop height (no ground under the player)
  LANDED  anything else (the player fell from the drop height at the target; the height itself is not judged here)
  NOREAD  no position read
A hop is judged by the read after the point it leads to. Only teleports that start where the previous one LANDED
are counted (after a RELOC or HUNG the player's place is not where the plan thought). Cells are counted in the
world frame the runner read (100 m cells): qstep types setpos x, then y, then z, so each setpos moves one axis.
"""
import argparse
import collections
import glob
import json
import math
import os
import sys

CELL_M = 100.0


def load(path):
    with open(path, encoding="utf-8-sig") as f:              # the runner writes obs.json with a BOM
        return json.load(f)


def parse3(text):
    try:
        v = [float(t) for t in str(text).split()]
    except ValueError:
        return None
    return v if len(v) == 3 else None


def cells(a, b):
    """Cell change along x and y from a to b (x, y), world frame."""
    return (math.floor(b[0] / CELL_M) - math.floor(a[0] / CELL_M), math.floor(b[1] / CELL_M) - math.floor(a[1] / CELL_M))


def outcome(read, target, drop_z):
    r = parse3(read)
    if r is None:
        return "NOREAD"
    if abs(r[0] - target[0]) > 500.0 or abs(r[1] - target[1]) > 500.0:
        return "RELOC"
    if abs(r[2] - drop_z) < 0.05:
        return "HUNG"
    return "LANDED"


def test_teleports(spec, obs):
    """Every teleport of one terrain attempt: [{"to", "hop", "from", "target", "dx", "dy", "cells", "result",
    "start_landed"}] in the order qstep made them (empty when the attempt has no spawn read or offset)."""
    spawn = parse3(obs.get("spawn_read"))
    off = list(obs.get("offset") or [])
    if spawn is None or len(off) < 2 or not spec.get("points"):
        return []
    ox, oy = off[0], off[1]
    oz = off[2] if len(off) > 2 else 0.0
    drop_z = float(spec.get("drop_z", 80.0)) + oz
    if spec.get("drop_above_spawn"):
        drop_z = spawn[2] + float(spec["drop_above_spawn"])
    hop = spec.get("hop_m") or 0
    pts, reads = spec["points"], obs.get("points") or []
    out, cur, landed = [], (spawn[0], spawn[1]), True
    hx, hy = pts[0]["x"] + ox, pts[0]["y"] + oy
    for k, p in enumerate(pts):
        if k >= len(reads):
            break
        tx, ty = p["x"] + ox, p["y"] + oy
        legs = []
        if hop:
            n = math.ceil(math.hypot(tx - hx, ty - hy) / hop)
            legs += [(None, hx + (tx - hx) * h / n, hy + (ty - hy) * h / n) for h in range(1, n)]
        legs.append((p["label"], tx, ty))
        hx, hy = tx, ty
        read = reads[k].get("read") if isinstance(reads[k], dict) else None
        res = outcome(read, (tx, ty), drop_z)
        for label, x, y in legs:
            c = cells(cur, (x, y))
            out.append({"to": label or "hop", "hop": label is None, "from": [round(cur[0], 2), round(cur[1], 2)],
                        "target": [round(x, 2), round(y, 2)], "dx": round(x - cur[0], 2), "dy": round(y - cur[1], 2),
                        "cells": [c[0], c[1]], "result": res, "start_landed": landed})
            cur = (x, y)
        r = parse3(read)
        if r is not None:
            cur = (r[0], r[1])
        landed = res == "LANDED"
    return out


def audit(queue_dirs):
    """Teleports of every terrain attempt in the queue dirs and a summary of those that start where the previous one
    landed, split at MAX cells per axis <= 2 / >= 3."""
    rows = []
    for q in queue_dirs:
        for d in sorted(glob.glob(os.path.join(q, "tests", "*", "a*"))):
            try:
                spec, obs = load(os.path.join(d, "spec.json")), load(os.path.join(d, "obs.json"))
            except (OSError, ValueError):
                continue
            if spec.get("kind") != "terrain":
                continue
            for t in test_teleports(spec, obs):
                rows.append(dict(t, queue=os.path.basename(os.path.normpath(q)), attempt=os.path.relpath(d, q)))
    counted = [r for r in rows if r["start_landed"]]
    summary = {}
    for name, sel in (("at_most_2_cells", lambda r: max(map(abs, r["cells"])) <= 2),
                      ("3_or_more_cells", lambda r: max(map(abs, r["cells"])) >= 3)):
        group = [r for r in counted if sel(r)]
        axis = [max(abs(r["dx"]), abs(r["dy"])) for r in group]
        summary[name] = {"teleports": len(group), "hops": sum(r["hop"] for r in group),
                         "results": dict(collections.Counter(r["result"] for r in group)),
                         "by_queue": {q: dict(collections.Counter(r["result"] for r in group if r["queue"] == q))
                                      for q in sorted({r["queue"] for r in group})},
                         "largest_axis_move_landed_m": max((m for m, r in zip(axis, group) if r["result"] == "LANDED"),
                                                           default=None),
                         "smallest_axis_move_failed_m": min((m for m, r in zip(axis, group)
                                                             if r["result"] in ("RELOC", "HUNG")), default=None)}
    return rows, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("queues", nargs="+")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    rows, summary = audit(a.queues)
    for r in rows:
        if r["start_landed"] and (max(map(abs, r["cells"])) >= 3 or r["result"] in ("RELOC", "HUNG")):
            print(f"  {r['queue']:<20} {r['attempt']:<44} {r['to']:<20} dx {r['dx']:>8.1f} dy {r['dy']:>8.1f} "
                  f"cells {r['cells'][0]:>3} {r['cells'][1]:>3}  {r['result']}")
    print(json.dumps(summary, indent=1))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "teleports": rows}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
