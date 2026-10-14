"""Oracle: parse real NIFs (FO4 + Starfield), re-serialize, require byte-identical. Prints block-type stats too.
usage: roundtrip_nif.py <repo/src> <repo/scripts> <FO4 Meshes.ba2> <SF Meshes01.ba2> [n]"""
import os
import random
import sys
from collections import Counter

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import nif  # noqa: E402

want = int(sys.argv[5]) if len(sys.argv) > 5 else 500
for label, path in (("FO4", sys.argv[3]), ("SF", sys.argv[4])):
    ba2 = recon.read_ba2(path)
    idx = [i for i, n in enumerate(ba2["names"]) if n.lower().endswith(".nif")]
    random.seed(3)
    random.shuffle(idx)
    res, bad, types = Counter(), [], Counter()
    for i in idx[:want]:
        raw = recon.extract_gnrl(ba2, i)
        if raw is None:
            res["unpack_fail"] += 1
            continue
        try:
            f = nif.parse(raw)
        except Exception as e:
            res["parse_error"] += 1
            bad.append((ba2["names"][i], str(e)))
            continue
        res[f"bs{f.bs_version}"] += 1
        types.update(f.block_types)
        if nif.serialize(f) == raw:
            res["identical"] += 1
        else:
            res["DIFFERENT"] += 1
            bad.append((ba2["names"][i], "roundtrip differs"))
    print(label, dict(res))
    print("   common block types:", ", ".join(f"{t}:{c}" for t, c in types.most_common(12)))
    for b in bad[:5]:
        print("   BAD", b)
