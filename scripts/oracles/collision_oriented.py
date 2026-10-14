"""Independent geometric checks for rotated collision boxes; no runtime claims.

Run directly to test the source-empty opening fixture against oriented_surface_boxes.
Exit 1 means an empty source point is occupied by generated collision.
"""
import json
import math
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parent)]
from fo4sf import sfcollision
from collision_openings import ring


def local_point(box, point):
    center, half, rotation = box
    if len(center) != 3 or len(half) != 3 or len(rotation) != 9 or len(point) != 3:
        raise ValueError("invalid oriented box dimensions")
    if not all(math.isfinite(v) for v in (*center, *half, *rotation, *point)) or min(half) < 0:
        raise ValueError("invalid oriented box values")
    for i in range(3):
        for j in range(3):
            dot = sum(rotation[3 * k + i] * rotation[3 * k + j] for k in range(3))
            if abs(dot - int(i == j)) > 1e-4:
                raise ValueError("box axes must be orthonormal")
    # Rotation's columns are box axes; the inverse is its transpose.
    return tuple(sum(rotation[3 * a + k] * (point[a] - center[a]) for a in range(3)) for k in range(3))


def contains(box, point, epsilon=1e-6):
    return all(abs(v) <= h + epsilon for v, h in zip(local_point(box, point), box[1]))


def vertical_interval(box, x, y):
    """Exact intersection of the vertical line (x,y,z) with an oriented box."""
    q = local_point(box, (x, y, 0))
    lo, hi = -math.inf, math.inf
    for k in range(3):
        slope = box[2][6 + k]
        h = box[1][k]
        if abs(slope) < 1e-12:
            if abs(q[k]) > h + 1e-6:
                return None
            continue
        a, b = (-h - q[k]) / slope, (h - q[k]) / slope
        lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
        if lo > hi + 1e-6:
            return None
    return lo, hi


def diagnose():
    if not hasattr(sfcollision, "oriented_surface_boxes"):
        raise RuntimeError("oriented collision generator is not available in this checkout")
    points, triangles, probes = ring()
    results = []
    for cell in (.2, .25, .5, 1.0):
        boxes = sfcollision.oriented_surface_boxes(points, triangles, cell=cell, min_area=.01)
        blocked = [list(p) for p in probes if any(contains(b, (*p, 0)) for b in boxes)]
        results.append({"cell": cell, "boxes": len(boxes), "blocked_void_probes": blocked})
    return {"fixture": "0.4 m source-empty floor opening", "results": results}


if __name__ == "__main__":
    try:
        report = diagnose()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(report, indent=2))
    raise SystemExit(int(any(r["blocked_void_probes"] for r in report["results"])))
