"""Score route_run.ps1 results against the expectations from routes.py.

usage: python route_eval.py routes.json results.jsonl
stairs: PASS if the end height is at least low + min_rise and the player did not drop below the start floor;
        STUCK if it rose less; FALL if it ended more than 0.5 m below the ramp's low end.
door:   PASS if the end point is min_past metres beyond the door plane (dot with the plane normal) and this
        attempt opened it (prompt missing in older runs, or the recorded verb contains OPEN).
        UNOPENED if it is past the plane but the prompt was absent or was not OPEN: the leaf was already open.
        Otherwise NOPROMPT if the activation prompt was never seen, else BLOCKED.
A start more than 3 m off in X/Y, or more than 2 m off in Z, is UNREAD: the route was not begun.
A drop of more than 6 m after a matched start is FALL, including a door that opens onto the void.
Any other move no walk of this length could make is UNREAD.
Prints one line per route, a summary, and a door tally: both OPEN, one side, geometry, load failures.
Exit code 1 unless the file records results, every one is PASS, no load door was passed,
walked through, or fallen through, and no hinged pair is geometry (crossed with no recorded OPEN).
That exit does not mean every hinged door opened from both sides. A one-route file can exit 0.
"""
import json
import math
import sys


def parse(s):
    try:
        v = [float(x) for x in s.split()]
        return v if len(v) == 3 else None
    except (AttributeError, ValueError):
        return None


def judge(route, res):
    end = parse(res.get("end_read"))
    start = parse(res.get("start_read"))
    if end is None:
        return "UNREAD", ""
    target = route.get("start")
    moved_xy = moved_z = None
    if start is not None:
        moved_xy = abs(end[0] - start[0]) + abs(end[1] - start[1])
        moved_z = end[2] - start[2]
        # Under the floor, or sent to the cell entrance: this route never started.
        # Height too: Vault 81 19DA36 was read 4 m below its door and is not a blocked swing.
        if target and (abs(start[0] - target[0]) + abs(start[1] - target[1]) > 3 or abs(start[2] - target[2]) > 2):
            return "UNREAD", f"start not reached: read {res.get('start_read')}"
        if moved_xy > 15:
            return "UNREAD", f"implausible read {res.get('start_read')} -> {res.get('end_read')}"
        # A long drop from a start that matches the route is the player falling, not a swapped OCR column.
        # The Parsons load door did this: 10.97 51.41 7.31 -> 11.22 57.95 -69.15.
        if target and moved_z < -6:
            return "FALL", f"dropped {-moved_z:.1f} m"
        if abs(moved_z) > 6:
            return "UNREAD", f"implausible read {res.get('start_read')} -> {res.get('end_read')}"
    e = route["expect"]
    if route["kind"] == "stairs":
        low, high = e["low"], e["high"]
        rise = end[2] - low[2]
        top_rise = high[2] - low[2]
        if rise > top_rise + 2.0:                     # higher than the stair goes: a misread, not a climb
            return "UNREAD", f"implausible rise {rise:.2f} (stair top is {top_rise:.2f})"
        dx, dy = high[0] - low[0], high[1] - low[1]
        span = math.hypot(dx, dy) or 1.0
        off_axis = abs((end[0] - low[0]) * dy - (end[1] - low[1]) * dx) / span
        if off_axis > 3.0:                            # not on this stair's line: a shifted OCR column
            return "UNREAD", f"end {off_axis:.1f} m off the stair"
        if end[2] < low[2] - 0.5:
            return "FALL", f"z {end[2]:.2f} < floor {low[2]:.2f}"
        return ("PASS" if rise >= e["min_rise"] else "STUCK"), f"rise {rise:.2f} / need {e['min_rise']:.2f}"
    normal = e["plane_normal"]
    length = math.hypot(*normal)
    if length < 1e-6:
        return "UNREAD", "door normal missing"
    unit = tuple(part / length for part in normal)
    delta = tuple(end[i] - e["plane_point"][i] for i in range(3))
    past = sum(delta[i] * unit[i] for i in range(3))
    # Lateral in the horizontal plane only. A door centre is above the floor, so Z is not "off to the side".
    ux, uy = unit[0], unit[1]
    horizontal = math.hypot(ux, uy) or 1.0
    ux, uy = ux / horizontal, uy / horizontal
    side = abs((end[0] - e["plane_point"][0]) * uy - (end[1] - e["plane_point"][1]) * ux)
    if past > 12.0 or side > 3.0:
        return "UNREAD", f"implausible door end past {past:.1f} m, {side:.1f} m off the opening"
    if past >= e["min_past"]:
        verb = res.get("verb")
        verb_text = verb.upper() if isinstance(verb, str) else ""
        # The far side of a pair often walks through a leaf the near side already opened. That is not this side opening.
        if res.get("prompt") is False or (verb_text and "OPEN" not in verb_text):
            return "UNOPENED", f"past plane {past:.2f} m without OPEN"
        return "PASS", f"past plane {past:.2f} m"
    if res.get("prompt") is False:                    # never saw "OPEN (E)": activation, not collision, is the problem
        return "NOPROMPT", f"past plane {past:.2f} m, no activation prompt"
    return "BLOCKED", f"past plane {past:.2f} m"


def _opened(res):
    """True when this result recorded an activation, not only a crossing.

    Prompt True with no verb is the runner that pressed E whenever the prompt bar was visible.
    A later run records the verb and only counts OPEN. A file that never stored either is geometry.
    """
    if res.get("prompt") is True:
        verb = res.get("verb")
        if isinstance(verb, str) and verb.strip() and "OPEN" not in verb.upper():
            return False
        return True
    verb = res.get("verb")
    return isinstance(verb, str) and "OPEN" in verb.upper()


def _unit_normal(route):
    """Unit door normal, or None when the route has no usable plane."""
    expect = route.get("expect") if isinstance(route, dict) else None
    normal = expect.get("plane_normal") if isinstance(expect, dict) else None
    if not isinstance(normal, (list, tuple)) or len(normal) != 3:
        return None
    try:
        length = math.hypot(normal[0], normal[1], normal[2])
    except TypeError:
        return None
    if length < 1e-6:
        return None
    return (normal[0] / length, normal[1] / length, normal[2] / length)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _opposite_opens(entries):
    """True when two different routes passed, recorded OPEN, and faced opposite ways.

    `entries` are `(verdict, result, side, route)`. When any of those routes recorded
    `side`, the OPEN crossings must include side 1 and side -1. Two OPEN crossings on
    the same side are still one side. Their plane normals must also point opposite
    ways: labels 1 and -1 on two walks in the same direction are still one side.
    Routes that never stored `side` still count two visits only when those normals
    point opposite ways. A route with no normal cannot contradict that.
    """
    chosen = []
    for verdict, res, side, route in entries:
        if verdict == "PASS" and _opened(res):
            chosen.append((side, _unit_normal(route)))
    if len(chosen) < 2:
        return False
    present = [side for side, _normal in chosen if side is not None]
    if present and set(present) != {1, -1}:
        return False
    normals = [(side, normal) for side, normal in chosen if normal is not None]
    if len(normals) < 2:
        return True
    if present:
        forward = [normal for side, normal in normals if side == 1]
        back = [normal for side, normal in normals if side == -1]
        return any(_dot(a, b) < 0 for a in forward for b in back)
    for i, (_side, a) in enumerate(normals):
        for _other, b in normals[i + 1:]:
            if _dot(a, b) < 0:
                return True
    return False


def door_rows(routes, results):
    """`both` is two different routes for one ref that each recorded an OPEN.

    When those routes record `side`, the sides must be 1 and -1, and the two OPEN
    crossings must face opposite directions. Two OPEN crossings on the same side, or
    on labels 1 and -1 with the same plane normal, are `one`. Two crossings with no
    prompt stored are `geometry`: both sides ended past the plane, and the file cannot
    show that either side opened. One recorded OPEN is `one`. A walk through an
    already-open leaf is UNOPENED and does not make a pair. Load doors (the model name
    contains "load") are not swing rows. Passing one, walking through it, or falling
    at it is a load failure: those doors stay shut.
    """
    by_ref = {}
    load_fail = set()
    for res in results:
        route = routes[res["index"]]
        if route.get("kind") != "door":
            continue
        verdict, _why = judge(route, res)
        if "load" in route.get("model", "").lower():
            if verdict in ("PASS", "UNOPENED", "FALL"):
                load_fail.add(route.get("ref"))
            continue
        # one line per route index: a repeated index is a rerun, not the other side
        by_ref.setdefault(route.get("ref"), {})[res["index"]] = (verdict, res, route.get("side"), route)
    both = one = none = geometry = 0
    for verdicts in by_ref.values():
        passes = activated = 0
        for verdict, res, _side, _route in verdicts.values():
            if verdict != "PASS":
                continue
            passes += 1
            if _opened(res):
                activated += 1
        if _opposite_opens(verdicts.values()):
            both += 1
        elif passes >= 2 and activated == 0:
            geometry += 1
        elif passes >= 1:
            one += 1
        else:
            none += 1
    return {"both": both, "one": one, "none": none, "geometry": geometry, "load_fail": len(load_fail)}


def unproven(routes, results):
    """Hinged refs that lack two OPEN crossings, and load doors that were crossed or fallen through.

    `door_rows` counts only the refs that appear in the results. A file can be all PASS, exit 0,
    and still leave every other door untested. This lists those refs too. One recorded OPEN does
    not prove the other side. Two OPEN crossings on the same recorded side stay unproven.
    Two OPEN crossings whose plane normals point the same way stay unproven, even when
    the routes are labeled side 1 and side -1. Two crossings with no OPEN stay unproven.
    """
    by_ref = {}
    order = []
    for route in routes:
        if route.get("kind") != "door":
            continue
        if "load" in str(route.get("model", "")).lower():
            continue
        ref = route.get("ref")
        if ref not in by_ref:
            order.append(ref)
            by_ref[ref] = {}
    load_fail = []
    seen_load = set()
    for res in results:
        if not isinstance(res, dict):
            continue
        index = res.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(routes):
            continue
        route = routes[index]
        if route.get("kind") != "door":
            continue
        verdict, _why = judge(route, res)
        ref = route.get("ref")
        if "load" in str(route.get("model", "")).lower():
            if verdict in ("PASS", "UNOPENED", "FALL") and ref not in seen_load:
                seen_load.add(ref)
                load_fail.append(ref)
            continue
        if ref not in by_ref:
            order.append(ref)
            by_ref[ref] = {}
        by_ref[ref][index] = (verdict, res, route.get("side"), route)
    missing = []
    for ref in order:
        if not _opposite_opens(by_ref[ref].values()):
            missing.append(ref)
    return {"unproven": missing, "load_fail": load_fail}


def finished(counts, rows, result_count):
    """True only when every recorded route passed, no load door was crossed or fallen through,
    and no hinged pair is geometry.

    Geometry is two crossings with no recorded OPEN. That is not both sides opening.
    An empty file is not a pass: Red Rocket has no stair or door routes, and a run that
    writes nothing must not exit 0. A partial file with one recorded OPEN can still pass
    this check. `unproven` lists the hinged refs that file does not show opening from both sides.
    """
    return (result_count > 0 and set(counts) <= {"PASS"} and rows["load_fail"] == 0
            and rows.get("geometry", 0) == 0)


def main():
    routes = json.load(open(sys.argv[1], encoding="utf-8-sig"))["routes"]
    results = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8-sig") if l.strip()]
    counts = {}
    for res in results:
        r = routes[res["index"]]
        verdict, why = judge(r, res)
        counts[verdict] = counts.get(verdict, 0) + 1
        print(f"{res['index']:3d} {verdict:8s} {r['kind']:6s} {r['ref']} {r['model'].split(chr(92))[-1]:40s} {why}")
    print("summary:", counts)
    rows = door_rows(routes, results)
    print("doors:", rows)
    sys.exit(0 if finished(counts, rows, len(results)) else 1)


if __name__ == "__main__":
    main()
