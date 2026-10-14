import os
import random
import sys
from collections import Counter

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import nif, sfnif  # noqa: E402

ba2 = recon.read_ba2(os.path.join(sys.argv[3], "Starfield - Meshes01.ba2"))
idx = [i for i, n in enumerate(ba2["names"]) if n.lower().endswith(".nif")]
random.seed(8)
random.shuffle(idx)
res, bad, paths = Counter(), [], []
for i in idx[:3000]:
    f = nif.parse(recon.extract_gnrl(ba2, i))
    for k, b in enumerate(f.blocks):
        if f.type_of(k) != "BSGeometry":
            continue
        res["blocks"] += 1
        try:
            g = sfnif.parse_bsgeometry(b)
        except Exception as e:
            res["parse_error"] += 1
            if len(bad) < 4:
                bad.append(str(e))
            continue
        if sfnif.build_bsgeometry(g) == b:
            res["identical"] += 1
        else:
            res["DIFFERENT"] += 1
        m = g.meshes[0]
        if m and len(paths) < 3:
            paths.append(m.path)
        if m:
            res["lod_slots_used_%d" % sum(1 for x in g.meshes if x)] += 1
            res["mesh_flags_%#x" % m.flags] += 1
print(dict(res))
print("sample mesh paths:", paths)
print(bad)
