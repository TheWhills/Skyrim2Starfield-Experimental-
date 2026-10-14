"""Top-down collision map: every placed ref of the cell as a grey dot, probe results as coloured markers.
usage: probe_map.py <cell.json> <results.csv> <out.png>"""
import csv
import json
import sys

from PIL import Image, ImageDraw

cell = json.load(open(sys.argv[1], encoding="utf-8-sig"))
rows = list(csv.DictReader(open(sys.argv[2])))
pts = [(r["pos"][0] / 70, r["pos"][1] / 70) for r in cell["refs"] if r.get("model")]
xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
W = 1000
s = (W - 40) / max(x1 - x0, y1 - y0)
H = int((y1 - y0) * s) + 40
im = Image.new("RGB", (W, H), (18, 20, 26))
d = ImageDraw.Draw(im)
P = lambda x, y: (20 + (x - x0) * s, H - 20 - (y - y0) * s)  # noqa: E731
for x, y in pts:
    a, b = P(x, y)
    d.point((a, b), fill=(90, 90, 100))
col = {"PASS": (60, 200, 90), "FALL": (230, 60, 60), "HELD": (80, 140, 240), "UNREAD": (150, 150, 150)}
counts = {}
for r in rows:
    a, b = P(float(r["x"]), float(r["y"]))
    c = col.get(r["result"], (255, 255, 0))
    d.ellipse((a - 6, b - 6, a + 6, b + 6), fill=c, outline=(0, 0, 0))
    counts[r["result"]] = counts.get(r["result"], 0) + 1
d.text((10, 6), "  ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + "   (grey dots = placed objects)", fill=(230, 230, 230))
im.save(sys.argv[3])
print(counts)
