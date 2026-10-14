"""Synthetic stair-tread collision diagnostic; not an in-game walking test.

Runs all production surface-grid sizes against known source tread heights.
Exit 1 indicates missing support or a different step's collision at a probe.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from fo4sf import sfcollision


def support_errors(boxes, probes, tolerance=.01):
    """Compare highest box top with explicit source surface heights (metres).

    Use only an isolated stair fixture without ceilings/overhead objects. Box
    tops alone cannot establish player clearance, step climbing or settling.
    """
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("invalid height tolerance")
    errors = []
    for x, y, expected in probes:
        if not all(math.isfinite(v) for v in (x, y, expected)):
            raise ValueError("nonfinite stair probe")
        tops = []
        for center, half in boxes:
            if len(center) != 3 or len(half) != 3 or not all(math.isfinite(v) for v in (*center, *half)) or min(half) < 0:
                raise ValueError("invalid collision box")
            if abs(x - center[0]) < half[0] - 1e-6 and abs(y - center[1]) < half[1] - 1e-6:
                tops.append(center[2] + half[2])
        actual = max(tops) if tops else None
        if actual is None or abs(actual - expected) > tolerance:
            errors.append({"probe": [x, y], "expected": expected, "actual": actual})
    return errors


def stairs():
    points, triangles, probes = [], [], []
    for step in range(6):
        x0, x1, z = step * .3, (step + 1) * .3, (step + 1) * .2
        b = len(points)
        points.extend([(x0, 0, z), (x1, 0, z), (x1, 1, z), (x0, 1, z)])
        triangles.extend([(b, b + 1, b + 2), (b, b + 2, b + 3)])
        probes.append((x0 + .15, .5, z))
    return points, triangles, probes


def diagnose():
    points, triangles, probes = stairs()
    results = []
    for cell in (.25, .5, 1.0):
        boxes = sfcollision.surface_boxes(points, triangles, min_area=.01, cell=cell)
        results.append({"cell": cell, "boxes": len(boxes), "support_errors": support_errors(boxes, probes)})
    return {"fixture": "six treads, 0.3 m run, 0.2 m rise, 1 m width", "results": results}


def main():
    report = diagnose()
    print(json.dumps(report, indent=2))
    return int(any(r["support_errors"] for r in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
