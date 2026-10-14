"""Report manifest swinging doors that a route file never visits.

A swinging door is a placed ref whose manifest item has a door record. Doorways and
load doors have no door record and are not this list. A hinged ref with only one door
route is single-sided. Two routes on the same side are still one side. Exit 1 when any
swinging door is missing or single-sided. This does not score a walk.

usage: python scripts/oracles/route_coverage.py --cell cell.json --manifest manifest.json --routes routes.json
"""
import argparse
import json
import sys


def _items(manifest):
    return {item.get("source", "").lower(): item for item in manifest.get("items", [])}


def unrouted(cell, items, routes):
    """Form keys of swinging doors in the cell that the route list does not visit."""
    routed = {route.get("ref") for route in routes if route.get("kind") == "door"}
    missing = []
    for ref in cell.get("refs", []):
        model = ref.get("model") or ""
        key = "meshes\\" + model.lstrip("\\").lower()
        item = items.get(key)
        if not item or not item.get("door"):
            continue
        form = ref.get("formkey") or ref.get("ref")
        if form not in routed:
            missing.append(form)
    return missing


def single_sided(routes):
    """Hinged door refs that do not have routes on both sides.

    One visit cannot show both sides. When `side` is recorded, the two routes must be
    side 1 and side -1. Two routes on the same side are still one side. A route file
    that never stored `side` still counts two visits as both sides.
    Load doors stay out of this list. Their model name contains "load".
    """
    grouped = {}
    order = []
    for route in routes:
        if route.get("kind") != "door":
            continue
        if "load" in route.get("model", "").lower():
            continue
        ref = route.get("ref")
        if ref not in grouped:
            order.append(ref)
            grouped[ref] = []
        grouped[ref].append(route.get("side"))
    bad = []
    for ref in order:
        sides = grouped[ref]
        present = [side for side in sides if side is not None]
        if len(sides) < 2 or (present and set(present) != {1, -1}):
            bad.append(ref)
    return bad


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--routes", required=True)
    args = parser.parse_args(argv)
    cell = json.load(open(args.cell, encoding="utf-8-sig"))
    items = _items(json.load(open(args.manifest, encoding="utf-8-sig")))
    routes = json.load(open(args.routes, encoding="utf-8-sig"))["routes"]
    missing = unrouted(cell, items, routes)
    ones = single_sided(routes)
    print(json.dumps({"cell": cell.get("cell"), "unrouted": missing, "single_sided": ones}, indent=2))
    return 1 if missing or ones else 0


if __name__ == "__main__":
    raise SystemExit(main())
