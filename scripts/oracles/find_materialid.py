import itertools
import os
import random
import struct
import sys
import zlib

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import nif  # noqa: E402

ba2 = recon.read_ba2(os.path.join(sys.argv[3], "Starfield - Meshes01.ba2"))
idx = [i for i, n in enumerate(ba2["names"]) if n.lower().endswith(".nif")]
random.seed(9)
random.shuffle(idx)
pairs = {}
for i in idx[:800]:
    f = nif.parse(recon.extract_gnrl(ba2, i))
    if f.bs_version != 173:
        continue
    mid = mat = None
    for k, b in enumerate(f.blocks):
        t = f.type_of(k)
        if t == "NiIntegerExtraData":
            ni, val = struct.unpack("<iI", b[:8])
            if ni >= 0 and f.strings[ni] == b"MaterialID":
                mid = val
        if t == "BSLightingShaderProperty" and len(b) == 12:
            ni, = struct.unpack_from("<i", b, 0)
            if ni >= 0:
                mat = f.strings[ni].decode("latin-1")
    if mid is not None and mat and len(mat) > 12:
        pairs[mat] = mid


def crc(data, init, xorout, poly_reflected=0xEDB88320):
    table = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ poly_reflected if c & 1 else c >> 1
        table.append(c)
    c = init
    for b in data:
        c = table[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ xorout


def variants(s):
    base = s.replace("/", "\\")
    outs = {}
    for lower in (False, True):
        t = base.lower() if lower else base
        for fwd in (False, True):
            u = t.replace("\\", "/") if fwd else t
            for prefix in ("keep", "strip"):
                v = u
                if prefix == "strip":
                    lo = v.lower()
                    k = lo.find("materials")
                    v = v[k + 10:] if k >= 0 else v
                for noext in (False, True):
                    w = v.rsplit(".", 1)[0] if noext else v
                    for enc in ("latin-1", "utf-16-le"):
                        outs[f"lower={lower},fwd={fwd},{prefix},noext={noext},{enc}"] = w.encode(enc)
    return outs


hits = {}
modes = {"std": (0xFFFFFFFF, 0xFFFFFFFF), "init0": (0, 0), "initFF": (0xFFFFFFFF, 0), "init0_xorFF": (0, 0xFFFFFFFF)}
sample = list(pairs.items())[:60]
for mat, mid in sample:
    for vname, data in variants(mat).items():
        for mname, (ini, xo) in modes.items():
            if crc(data, ini, xo) == mid:
                hits[(vname, mname)] = hits.get((vname, mname), 0) + 1
        # crc32c-like polynomial (Castagnoli, reflected)
        if crc(data, 0xFFFFFFFF, 0xFFFFFFFF, 0x82F63B78) == mid:
            hits[(vname, "crc32c")] = hits.get((vname, "crc32c"), 0) + 1
print("pairs", len(pairs), "tested", len(sample))
print("hits:", hits if hits else "none")
