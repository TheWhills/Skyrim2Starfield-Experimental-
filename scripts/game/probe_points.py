"""Pick probe points from an exported FO4 cell: floor-like pieces, converted to Starfield metres. Writes 'x y z name' lines.
usage: probe_points.py <cell.json> <out.txt> [max_points=40]"""
import json
import random
import re
import sys

cell = json.load(open(sys.argv[1], encoding="utf-8-sig"))
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 40
pts = []
for r in cell["refs"]:
    m = r.get("model") or ""
    if r["type"] in ("Static", "MovableStatic") and re.search(r"floor|stair|ramp|walkway|catwalk|plat", m, re.I):
        x, y, z = (v / 70.0 for v in r["pos"])
        pts.append((x, y, z, m.rsplit("\\", 1)[-1]))
random.seed(1)
random.shuffle(pts)
# spread: drop points within 2 m of an already chosen one
chosen = []
for p in pts:
    if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2 > 4 for q in chosen):
        chosen.append(p)
    if len(chosen) >= limit:
        break
with open(sys.argv[2], "w") as f:
    for x, y, z, n in chosen:
        f.write(f"{x:.2f} {y:.2f} {z:.2f} {n}\n")
print(len(chosen), "probe points from", len(pts), "floor-like refs")
