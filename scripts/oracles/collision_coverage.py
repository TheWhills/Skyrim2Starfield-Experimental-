"""Audit collision-generation reports; absence of reported drops is not in-game verification.

Usage: python scripts/oracles/collision_coverage.py --manifest <staging/manifest.json>
Returns nonzero for reported coverage loss or malformed reports. Empty reports are
listed as unassessed; --require-assessed also makes those a failure.
"""
import argparse
import json
import math

COUNTS = ("floor_dropped", "surface_dropped", "voxel_dropped")


def audit(manifest):
    result = {"assets": 0, "reported_without_drops": 0, "incomplete": [],
              "unassessed": [], "coarsened": [], "fallbacks": [], "errors": []}
    items = manifest.get("items") if isinstance(manifest, dict) else None
    if not isinstance(items, list) or not items:
        result["errors"].append("manifest contains no asset list")
        return result
    for item in items:
        result["assets"] += 1
        if not isinstance(item, dict):
            result["errors"].append("asset entry must be an object")
            continue
        source = item.get("source", "<unnamed>")
        report = item.get("collision_report")
        if report is None or report == {}:
            result["unassessed"].append(source)
            continue
        if not isinstance(report, dict):
            result["errors"].append(f"{source}: report must be an object")
            continue
        invalid = [key for key in (*COUNTS, "boxes") if key in report and
                   (type(report[key]) is not int or report[key] < 0)]
        if invalid:
            result["errors"].append(f"{source}: invalid counts {invalid}")
            continue
        failure = report.get("fo4_collision_error")
        if failure is not None:
            if not isinstance(failure, str) or not failure.strip():
                result["errors"].append(f"{source}: invalid source collision error")
                continue
            result["fallbacks"].append({"source": source, "reason": failure})
        cell = report.get("surface_cell", 0.25)
        if type(cell) not in (int, float) or not math.isfinite(cell) or cell <= 0:
            result["errors"].append(f"{source}: invalid surface_cell")
            continue
        elif cell > 0.25:
            result["coarsened"].append({"source": source, "surface_cell": cell})
        if "boxes" not in report and not any(key in report for key in COUNTS):
            result["unassessed"].append(source)
            continue
        counts = {key: report.get(key, 0) for key in COUNTS}
        if any(counts.values()):
            result["incomplete"].append({"source": source, **counts})
        elif failure is not None or report.get("boxes") == 0:
            result["unassessed"].append(source)
        else:
            result["reported_without_drops"] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--require-assessed", action="store_true")
    args = parser.parse_args()
    with open(args.manifest, encoding="utf-8-sig") as f:
        result = audit(json.load(f))
    print(json.dumps(result, indent=2))
    return int(bool(result["errors"] or result["incomplete"] or
                    (args.require_assessed and result["unassessed"])))


if __name__ == "__main__":
    raise SystemExit(main())
