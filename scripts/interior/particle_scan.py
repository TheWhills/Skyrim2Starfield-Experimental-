"""Does any Starfield model carry a Gamebryo particle system? (read-only; decides whether Skyrim particles can convert
directly).

2026-11-15, owner: "was it more worth it to directly convert the effect from Skyrim ... when converting Skyrim mods?"
Flames v1 - v3 rebuild Skyrim's particle flames as cards because none of the 60 fire-named Starfield models read so far
had a particle block. If ANY vanilla Starfield NIF still holds NiParticleSystem / NiPSys* / BSPSys* blocks, the
engine can draw them and Skyrim's particle systems could be written into converted models as they are; if none does,
the next step is one test model with a Skyrim particle system copied in.

Every .nif in Starfield's mesh archives is read and its header's block-type names checked (they are plain strings in
the NIF header, so no full parse). Prints the count, the block types found and up to --show paths per type.

    python -I scripts\\interior\\particle_scan.py --starfield "<Starfield>"
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2  # noqa: E402

PARTICLE_TYPES = re.compile(rb"(?:NiPSys\w+|BSPSys\w+|NiParticleSystem|NiMeshParticleSystem|BSStripParticleSystem"
                            rb"|NiParticles\w*|BSStripPSysData)")


def particle_types(nif_bytes: bytes, header_bytes: int = 65536) -> set:
    """Particle block-type names in a NIF's header (the block-type string table comes before any block data)."""
    return {m.decode("latin-1") for m in PARTICLE_TYPES.findall(nif_bytes[:header_bytes])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True, help="Starfield install folder (with Data)")
    ap.add_argument("--show", type=int, default=15)
    a = ap.parse_args(argv)
    data = os.path.join(a.starfield, "Data")
    arcs = [os.path.join(data, f) for f in sorted(os.listdir(data)) if f.lower().endswith(".ba2")]
    seen, total, failed = set(), 0, 0
    types, where, with_any = Counter(), defaultdict(list), 0
    for path in arcs:
        try:
            arc = ba2.Ba2(path)
        except Exception as e:                                      # noqa: BLE001
            print(f"  {os.path.basename(path)}: not read ({type(e).__name__})")
            continue
        names = [(i, n) for i, n in enumerate(arc.names) if n.lower().endswith(".nif")]
        if not names:
            continue
        print(f"  {os.path.basename(path)}: {len(names)} NIFs")
        for i, n in names:
            key = n.lower().replace("\\", "/")
            if key in seen:
                continue
            seen.add(key)
            total += 1
            try:
                found = particle_types(arc.read(i))
            except Exception:                                       # noqa: BLE001
                failed += 1
                continue
            with_any += bool(found)
            for t in found:
                types[t] += 1
                if len(where[t]) < a.show:
                    where[t].append(n)
    print(f"== {total} NIFs read ({failed} unreadable); with particle blocks: {with_any}")
    if not types:
        print("   none: no vanilla Starfield model carries a Gamebryo particle system")
    for t, c in types.most_common():
        print(f"  {t}: {c} NIFs, e.g. {where[t][:a.show]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
