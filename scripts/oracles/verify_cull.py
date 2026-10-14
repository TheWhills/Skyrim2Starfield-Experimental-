"""Regenerate meshlets + cull data from triangles/positions of real meshes (using the real partition) and compare."""
import os
import random
import struct
import sys
from collections import Counter

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import sfmesh  # noqa: E402

ba2 = recon.read_ba2(os.path.join(sys.argv[3], "Starfield - Meshes01.ba2"))
idx = [i for i, n in enumerate(ba2["names"]) if n.endswith(".mesh")]
random.seed(33)
random.shuffle(idx)
res, worst = Counter(), 0.0
auto_match = 0
for i in idx[:2000]:
    m = sfmesh.parse(recon.extract_gnrl(ba2, i))
    if not m.meshlets:
        continue
    res["meshes"] += 1
    groups, s = [], 0
    for (_, _, tc, _) in m.meshlets:
        groups.append((s, tc)); s += tc
    g = sfmesh.SfMesh(**{**m.__dict__})
    sfmesh.build_meshlets(g, groups)
    res["meshlets_exact"] += g.meshlets == m.meshlets
    err = 0.0
    for a, b in zip(g.cull_data, m.cull_data):
        fa, fb = struct.unpack("<6f", a), struct.unpack("<6f", b)
        err = max(err, max(abs(x - y) for x, y in zip(fa, fb)))
    worst = max(worst, err)
    res["cull_within_1e-3"] += err < 1e-3
    # would my greedy splitter reproduce the real partition?
    res["greedy_partition_same"] += sfmesh.split_into_meshlets(m.triangles) == groups
print(dict(res), "worst cull error", worst)
