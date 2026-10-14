"""Follow-up to recon.py: Havok format inside NIF collision, Starfield .mesh and material containers.

usage: python -I recon_physics.py <fo4 Meshes.ba2> <sf Meshes01.ba2> <sf Materials.ba2>
"""
import os
import re
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recon  # noqa: E402

HAVOK_MARKERS = re.compile(rb"hk_20[0-9.\-r]+|TAG0|SDKV|hkxHeader|hkRootLevelContainer")


def grab(ba2, needle, limit=1):
    found = []
    for i, n in enumerate(ba2["names"]):
        if needle in n.lower().replace("/", "\\"):
            found.append((n, recon.extract_gnrl(ba2, i)))
            if len(found) >= limit:
                break
    return found


def main():
    fo4 = recon.read_ba2(sys.argv[1])
    sf = recon.read_ba2(sys.argv[2])
    sfmat = recon.read_ba2(sys.argv[3])

    for lab, ba2, needle in [("FO4", fo4, "setdressing\\patiofurniture\\chairpatio01.nif"),
                             ("SF", sf, "architecture\\")]:
        for n, d in grab(ba2, needle):
            markers = sorted({m.decode("ascii", "replace") for m in HAVOK_MARKERS.findall(d or b"")})
            print(f"{lab} {n}: havok markers {markers}")

    for n, d in grab(sf, ".mesh", limit=3):
        print(f"SF mesh {n}: {len(d) if d else None} bytes, first u32s {struct.unpack_from('<4I', d, 0) if d else None}")

    exts = Counter(recon.ext_of(x) for x in sfmat["names"])
    print(f"SF Materials.ba2: {sfmat['file_count']} files, extensions {dict(exts)}")
    print("  samples:", sfmat["names"][:6])


if __name__ == "__main__":
    main()
