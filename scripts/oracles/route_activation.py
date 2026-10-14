"""List hinged doors a results file does not show opening from both sides.

Two different routes must each pass and record OPEN. When those routes record `side`,
the sides must be 1 and -1. Their plane normals must point opposite ways: two OPEN
crossings in the same direction stay unproven even if the labels are 1 and -1. A
crossing with no OPEN, one side only, the same side twice, or a route the file never
ran stays unproven. Load doors that were passed, walked
through, or fallen through are listed separately. Exit 1 when either list is non-empty.
A route file with no hinged doors exits 0. Doors that file never listed are not this
check; `route_coverage.py` lists those. That exit is not cell acceptance, and it does
not close `door_swing`.

usage: python scripts/oracles/route_activation.py --routes routes.json --results results.jsonl
"""
import argparse
import importlib.util
import json
from pathlib import Path


def _evaluator():
    path = Path(__file__).resolve().parents[1] / "game" / "route_eval.py"
    spec = importlib.util.spec_from_file_location("route_eval", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_results(path):
    rows = []
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", required=True)
    parser.add_argument("--results", required=True)
    args = parser.parse_args(argv)
    with open(args.routes, encoding="utf-8-sig") as handle:
        routes = json.load(handle)["routes"]
    report = _evaluator().unproven(routes, load_results(args.results))
    print(json.dumps(report, indent=2))
    return 1 if report["unproven"] or report["load_fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
