"""Synthetic floor/doorway opening diagnostic. No game assets or runtime claims.

Exit 1 means collision occupies a nominated source-empty point. The fixture uses
four rectangles around a square hole, tested at every production surface grid.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from fo4sf import sfcollision


def blocked_probes(boxes, probes, axis=2, plane=0.0):
    """Check projected box interiors on a nominated surface plane.

    Probes must be known source-empty positions in the two remaining axes.
    Boundary contact within 1e-6 m is excluded. This is a point diagnostic,
    not a player capsule sweep or proof that the rest of a mesh is sound.
    """
    if axis not in (0, 1, 2) or not math.isfinite(plane):
        raise ValueError("invalid surface plane")
    axes = [a for a in range(3) if a != axis]
    result = []
    for point in probes:
        if len(point) != 2 or not all(math.isfinite(v) for v in point):
            raise ValueError("probe must contain two finite coordinates")
        for center, half in boxes:
            if len(center) != 3 or len(half) != 3 or not all(math.isfinite(v) for v in (*center, *half)) or min(half) < 0:
                raise ValueError("invalid collision box")
            # Slabs end on the source surface, so the normal-axis boundary counts.
            if abs(plane - center[axis]) <= half[axis] + 1e-6 and all(
                    abs(point[i] - center[a]) < half[a] - 1e-6 for i, a in enumerate(axes)):
                result.append(list(point))
                break
    return result


def ring(width=0.4):
    if not math.isfinite(width) or not 0 < width < 3:
        raise ValueError("opening width must be between 0 and 3 metres")
    lo, hi = 1.5 - width / 2, 1.5 + width / 2
    points, triangles = [], []
    for x0, y0, x1, y1 in [(0, 0, 3, lo), (0, hi, 3, 3), (0, lo, lo, hi), (hi, lo, 3, hi)]:
        b = len(points)
        points.extend([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)])
        triangles.extend([(b, b + 1, b + 2), (b, b + 2, b + 3)])
    probes = [(lo + width * u, lo + width * v) for u in (.125, .5, .875) for v in (.125, .5, .875)]
    return points, triangles, probes


def diagnose(width=0.4):
    points, triangles, probes = ring(width)
    results = []
    for cell in (.25, .5, 1.0):
        boxes = sfcollision.surface_boxes(points, triangles, min_area=.01, cell=cell)
        results.append({"cell": cell, "boxes": len(boxes), "blocked_void_probes": blocked_probes(boxes, probes)})
    return {"opening_width": width, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=float, default=.4)
    args = parser.parse_args()
    report = diagnose(args.width)
    print(json.dumps(report, indent=2))
    return int(any(r["blocked_void_probes"] for r in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
