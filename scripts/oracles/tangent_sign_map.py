"""Learn how Starfield's tangent w bits map to UV-derived handedness."""
import os
import random
import sys
from collections import Counter

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import sfmesh  # noqa: E402


def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


ba2 = recon.read_ba2(os.path.join(sys.argv[3], "Starfield - Meshes01.ba2"))
idx = [i for i, n in enumerate(ba2["names"]) if n.endswith(".mesh")]
random.seed(4)
random.shuffle(idx)
joint = Counter()
for i in idx[:300]:
    m = sfmesh.parse(recon.extract_gnrl(ba2, i))
    if not (m.tangents and m.normals and m.uv1) or m.weights_per_vertex:
        continue
    pos = [sfmesh.decode_position(p, m.scale) for p in m.positions]
    uv = [(sfmesh.half_to_float(u), sfmesh.half_to_float(v)) for u, v in m.uv1]
    seen = set()
    for (a, b, c) in m.triangles[:200]:
        e1, e2 = sub(pos[b], pos[a]), sub(pos[c], pos[a])
        du1, dv1 = uv[b][0] - uv[a][0], uv[b][1] - uv[a][1]
        du2, dv2 = uv[c][0] - uv[a][0], uv[c][1] - uv[a][1]
        det = du1 * dv2 - du2 * dv1
        if abs(det) < 1e-9:
            continue
        B = tuple((e2[k] * du1 - e1[k] * du2) / det for k in range(3))
        for v in (a,):
            if v in seen:
                continue
            seen.add(v)
            n = sfmesh.decode_packed(m.normals[v])[:3]
            tt = sfmesh.decode_packed(m.tangents[v])
            T = tt[:3]
            h = dot(cross(n, T), B)
            if abs(h) < 1e-12:
                continue
            joint[(m.tangents[v] >> 30, "pos" if h > 0 else "neg")] += 1
print(dict(joint))
