"""Plan a short walk across floor pieces and score whether the player actually arrived.

The teleport probe drops the player onto each piece with god mode, so a stair or door
can look fine without anyone walking it. A leg here is one aimed step a person could
take: close horizontally, and no taller than a single step. Issue #29.
"""
import json
import math
import sys

FLOOR = r"floor|stair|ramp|walkway|catwalk|plat"
MAX_STEP = 3.0
MIN_STEP = 0.75
MAX_RISE = 0.45
WALK_SPEED = 2.0


def facing_yaw_degrees(start, target):
    """Creation Engine Z angle: 0 north (+Y), 90 east (+X), degrees."""
    dx, dy = target[0] - start[0], target[1] - start[1]
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError("nonfinite facing")
    return math.degrees(math.atan2(dx, dy)) % 360.0


def floor_points(cell):
    import re
    points = []
    for ref in cell.get("refs") or []:
        model = ref.get("model") or ""
        if ref.get("type") not in ("Static", "MovableStatic"):
            continue
        if not re.search(FLOOR, model, re.I):
            continue
        pos = ref.get("pos")
        if not isinstance(pos, (list, tuple)) or len(pos) != 3:
            raise ValueError("floor ref is missing a position")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in pos):
            raise ValueError("nonfinite floor position")
        name = model.replace("/", "\\").rsplit("\\", 1)[-1].replace(",", "")
        points.append((pos[0] / 70.0, pos[1] / 70.0, pos[2] / 70.0, name))
    points.sort(key=lambda p: (round(p[2], 3), round(p[0], 3), round(p[1], 3), p[3]))
    return points


def _flat(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _link(a, b, max_step, min_step, max_rise):
    distance = _flat(a, b)
    return min_step <= distance <= max_step and abs(a[2] - b[2]) <= max_rise


def route(points, max_step=MAX_STEP, min_step=MIN_STEP, max_rise=MAX_RISE, limit=30):
    """Longest walkable chain. A rise above max_rise ends the chain instead of being teleported."""
    for value, label in ((max_step, "max_step"), (min_step, "min_step"), (max_rise, "max_rise")):
        if not math.isfinite(value) or value < 0 or (label != "max_rise" and value <= 0):
            raise ValueError("invalid route limit")
    if min_step > max_step:
        raise ValueError("invalid route limit")
    count = len(points)
    neighbors = [[] for _ in range(count)]
    for i in range(count):
        for j in range(i + 1, count):
            if _link(points[i], points[j], max_step, min_step, max_rise):
                neighbors[i].append(j)
                neighbors[j].append(i)
    seen = [False] * count
    largest = []
    for seed in range(count):
        if seen[seed]:
            continue
        stack, component = [seed], []
        seen[seed] = True
        while stack:
            current = stack.pop()
            component.append(current)
            for other in neighbors[current]:
                if not seen[other]:
                    seen[other] = True
                    stack.append(other)
        if len(component) > len(largest):
            largest = component
    if len(largest) < 2:
        return []

    def farthest(origin):
        return max(largest, key=lambda j: _flat(points[origin], points[j]))

    begin = farthest(largest[0])
    goal = farthest(begin)
    if (points[goal][2], points[goal][0], points[goal][1]) < (points[begin][2], points[begin][0], points[begin][1]):
        begin, goal = goal, begin
    remaining = set(largest)
    order = [begin]
    remaining.remove(begin)
    while remaining and len(order) < limit:
        current = order[-1]
        choices = [j for j in neighbors[current] if j in remaining]
        if not choices:
            break
        order.append(min(choices, key=lambda j: (_flat(points[j], points[goal]), _flat(points[current], points[j]), j)))
        remaining.remove(order[-1])
    return [points[i] for i in order]


def legs(points, speed=WALK_SPEED):
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("invalid walk speed")
    planned = []
    for start, target in zip(points, points[1:]):
        distance = _flat(start, target)
        hold_ms = int(min(2500, max(400, distance / speed * 1000 + 250)))
        planned.append({"start": start[:3], "target": target[:3], "yaw": facing_yaw_degrees(start, target),
                        "hold_ms": hold_ms, "name": target[3]})
    return planned


def write_route(path, planned):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("start_x start_y start_z target_x target_y target_z yaw hold_ms name\n")
        for leg in planned:
            sx, sy, sz = leg["start"]
            tx, ty, tz = leg["target"]
            handle.write(f"{sx:.3f} {sy:.3f} {sz:.3f} {tx:.3f} {ty:.3f} {tz:.3f} "
                         f"{leg['yaw']:.2f} {leg['hold_ms']} {leg['name']}\n")


def score_leg(start, end, target, fall=1.25, arrive=0.45):
    """ARRIVED is the only walking pass. A drop past the lower of the two floors is FELL."""
    if fall <= 0 or arrive <= 0 or not math.isfinite(fall) or not math.isfinite(arrive):
        raise ValueError("invalid score limits")
    for point in (start, end, target):
        if len(point) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point):
            raise ValueError("nonfinite leg position")
    floor = min(start[2], target[2])
    if end[2] < floor - fall:
        return "FELL"
    moved = _flat(start, end)
    before = _flat(start, target)
    after = _flat(end, target)
    close_enough = after <= arrive and abs(end[2] - target[2]) <= 0.6
    if before <= arrive and close_enough and moved <= arrive:
        return "ARRIVED"
    if moved < 0.2:
        return "STUCK"
    if close_enough:
        return "ARRIVED"
    if after + 0.3 < before and end[2] >= floor - 0.5:
        return "PROGRESSED"
    if after > before + 0.4:
        return "MISSED"
    return "DRIFTED"


def score_rows(rows):
    labels = []
    for row in rows:
        end = row.get("end")
        if end is None:
            labels.append("UNREAD")
            continue
        labels.append(score_leg(tuple(row["start"]), tuple(end), tuple(row["target"])))
    return labels


def route_failed(labels):
    return (not labels) or any(label != "ARRIVED" for label in labels)


def score_csv(path):
    rows = []
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("leg,"):
                continue
            parts = line.split(",")
            if len(parts) < 10:
                raise ValueError("walk result is missing columns")
            def num(index):
                text = parts[index].strip()
                if not text:
                    return None
                value = float(text)
                if not math.isfinite(value):
                    raise ValueError("nonfinite walk result")
                return value
            end_values = [num(7), num(8), num(9)]
            rows.append({"start": (num(1), num(2), num(3)), "target": (num(4), num(5), num(6)),
                         "end": None if any(v is None for v in end_values) else tuple(end_values)})
    return score_rows(rows)


def main(argv):
    if len(argv) == 3 and argv[1] == "--score":
        labels = score_csv(argv[2])
        print(json.dumps({"legs": labels, "arrived": labels.count("ARRIVED")}, indent=2))
        return int(route_failed(labels))
    if len(argv) != 3:
        raise SystemExit("usage: walk_route.py <cell.json> <route.txt> | walk_route.py --score <results.csv>")
    with open(argv[1], encoding="utf-8-sig") as handle:
        ordered = route(floor_points(json.load(handle)))
    write_route(argv[2], legs(ordered))
    print(f"{max(0, len(ordered) - 1)} legs from {len(ordered)} connected floor pieces")
    return int(len(ordered) < 2)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
