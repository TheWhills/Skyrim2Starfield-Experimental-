import os
import random
import sys
from collections import Counter

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import sfmesh  # noqa: E402

ba2 = recon.read_ba2(os.path.join(sys.argv[3], "Starfield - Meshes01.ba2"))
idx = [i for i, n in enumerate(ba2["names"]) if n.endswith(".mesh")]
random.seed(21)
random.shuffle(idx)
res = Counter()
fails = []
for i in idx[:4000]:
    m = sfmesh.parse(recon.extract_gnrl(ba2, i))
    ml = m.meshlets
    if not ml:
        continue
    res["meshes"] += 1
    tri_start, vo_cum, to_cum = 0, 0, 0
    ok_vc = ok_vo = ok_to = True
    for (vc, vo, tc, to) in ml:
        tris = m.triangles[tri_start:tri_start + tc]
        uniq = len({v for t in tris for v in t})
        ok_vc &= uniq == vc
        ok_vo &= vo == vo_cum
        ok_to &= to == to_cum
        tri_start += tc
        vo_cum += vc
        to_cum += -(-(3 * tc) // 4) * 4
    ok_sum = tri_start == len(m.triangles)
    res["vc==unique_verts_of_tris"] += ok_vc
    res["vo_cumulative"] += ok_vo
    res["to_padded_bytes"] += ok_to
    res["all_tris_covered"] += ok_sum
    res["limits_ok(vc<=96,tc<=128)"] += all(x[0] <= 96 and x[2] <= 128 for x in ml)
    if not (ok_vc and ok_vo and ok_to and ok_sum) and len(fails) < 4:
        fails.append((len(m.triangles), len(m.positions), ml[:4], ok_vc, ok_vo, ok_to, ok_sum))
print(dict(res))
for f in fails:
    print("FAIL", f)
