"""S1 oracle: parse real vanilla Starfield .mesh files, re-serialize, require byte-identical output.
usage: python -I validate_mesh.py <repo>/src <repo>/scripts <Starfield Data dir> [sample_count]"""
import math
import os
import random
import sys
from collections import Counter

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import sfmesh  # noqa: E402

data_dir, want = sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 300
random.seed(1)
cands = []
for fn in sorted(os.listdir(data_dir)):
    if fn.lower().endswith(".ba2") and ("Meshes" in fn or "Terrain" not in fn and "Meshes" in fn):
        ba2 = recon.read_ba2(os.path.join(data_dir, fn))
        if ba2["type"] != "GNRL":
            continue
        idx = [i for i, n in enumerate(ba2["names"]) if n.lower().endswith(".mesh")]
        print(f"{fn}: {len(idx)} .mesh files (v{ba2['version']})", flush=True)
        cands += [(ba2, i) for i in idx]
random.shuffle(cands)
stats = Counter()
bad = []
norm_err, scale_ratio, tail_sizes = [], [], Counter()
for ba2, i in cands[:want]:
    raw = recon.extract_gnrl(ba2, i)
    if raw is None:
        stats["unpack_fail"] += 1
        continue
    try:
        m = sfmesh.parse(raw)
    except Exception as e:
        stats["parse_error"] += 1
        bad.append((ba2["names"][i], f"parse: {e}"))
        continue
    stats[f"version{m.version}"] += 1
    if m.tail:
        stats["has_tail"] += 1
        tail_sizes[len(m.tail)] += 1
    out = sfmesh.serialize(m)
    if out == raw:
        stats["identical"] += 1
    else:
        stats["DIFFERENT"] += 1
        bad.append((ba2["names"][i], f"len {len(raw)} vs {len(out)}"))
    for n in m.normals[:50]:
        x, y, z, w = sfmesh.decode_packed(n)
        norm_err.append(abs(math.sqrt(x * x + y * y + z * z) - 1.0))
    if m.meshlets:
        stats["has_meshlets"] += 1
    if m.cull_data:
        stats["has_cull"] += 1
    if m.positions:
        mx = max(abs(c) for p in m.positions for c in p)
        scale_ratio.append(mx / 32767.0)
print(dict(stats))
print("tails:", dict(tail_sizes))
if norm_err:
    print(f"normal length error: mean {sum(norm_err)/len(norm_err):.4f} max {max(norm_err):.4f} (n={len(norm_err)})")
if scale_ratio:
    print(f"max |raw int16| / 32767 over meshes: min {min(scale_ratio):.4f} mean {sum(scale_ratio)/len(scale_ratio):.4f}")
for b in bad[:10]:
    print("BAD", b)
