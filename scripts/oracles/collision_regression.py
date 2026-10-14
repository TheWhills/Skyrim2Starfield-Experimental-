"""S6 oracle: which numbers in a vanilla Starfield box-collision Havok blob depend on the box?

Collects every plain-box `bhkPhysicsSystem` blob of 6,168 bytes from setdressing NIFs, keeps the identity-rotation ones, recovers
each box's centre / half-extents from the 8 corner points at blob offset 592, and fits every varying float word as a linear
function of (1, cx, cy, cz, hx, hy, hz). The words that fit exactly are the table in src/fo4sf/sfcollision.py.
Needs numpy. usage: collision_regression.py <repo/src> <repo/scripts> <Starfield Data dir> [max NIFs to scan]
"""
import os
import random
import re
import struct
import sys

import numpy as np

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import nif  # noqa: E402

limit = int(sys.argv[4]) if len(sys.argv) > 4 else 6000
ba2 = recon.read_ba2(os.path.join(sys.argv[3], "Starfield - Meshes01.ba2"))
idx = [i for i, n in enumerate(ba2["names"]) if n.lower().endswith(".nif") and "setdressing" in n.lower()]
random.seed(6)
random.shuffle(idx)
good = []
for i in idx[:limit]:
    f = nif.parse(recon.extract_gnrl(ba2, i))
    if f.bs_version != 173:
        continue
    types = [f.type_of(k) for k in range(len(f.blocks))]
    if types.count("bhkPhysicsSystem") != 1:
        continue
    b = f.blocks[types.index("bhkPhysicsSystem")]
    n, = struct.unpack_from("<I", b, 0)
    blob = b[4:4 + n]
    if n != 6168 or set(re.findall(rb"hknp[A-Za-z]*Shape", blob)) != {b"hknpBoxShape", b"hknpConvexShape", b"hknpShape"}:
        continue
    if not (struct.unpack_from("<3f", blob, 528) == (1.0, 0.0, 0.0) and struct.unpack_from("<3f", blob, 544) == (0.0, 1.0, 0.0)
            and struct.unpack_from("<3f", blob, 560) == (0.0, 0.0, 1.0)):
        continue
    pts = [struct.unpack_from("<3f", blob, 592 + 12 * k) for k in range(8)]
    lo = [min(p[a] for p in pts) for a in range(3)]
    hi = [max(p[a] for p in pts) for a in range(3)]
    good.append((blob, [(lo[a] + hi[a]) / 2 for a in range(3)], [(hi[a] - lo[a]) / 2 for a in range(3)]))
print("identity-rotation box blobs:", len(good))
F = np.array([[1.0] + g[1] + g[2] for g in good])
labels = ["1", "cx", "cy", "cz", "hx", "hy", "hz"]
varying = [o for o in range(0, 6168 - 3, 4) if len({g[0][o:o + 4] for g in good}) > 1]
linear, other = 0, []
for o in varying:
    y = np.array([struct.unpack_from("<f", g[0], o)[0] for g in good], dtype=np.float64)
    if not np.all(np.isfinite(y)) or np.abs(y).max() > 1e6:
        other.append(o)
        continue
    coef, *_ = np.linalg.lstsq(F, y, rcond=None)
    if np.abs(F @ coef - y).max() < 3e-4 * max(1.0, np.abs(y).max()):
        linear += 1
        print(f"@{o}: " + " ".join(f"{c:+.2f}*{l}" for c, l in zip(coef, labels) if abs(c) > 1e-3))
    else:
        other.append(o)
print(f"{linear} linear words; {len(other)} others (mass/inertia/padding): {other}")
