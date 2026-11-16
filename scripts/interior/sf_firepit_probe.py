"""How Starfield builds its fire pits and campfires (read-only): the models that carry fire materials, and their records.

2026-11-16, owner on hearths with Starfield's FireMed02 spread along the logs: "looks a little silly, very clearly a few
fireballs thrown in there, compared to Skyrim's that looks like a hearth burning. Do we need to figure out how Starfield
fire pits work". A placed particle fire (MSTT FireMed01 / 02) is a standalone fire; Starfield's own pits likely burn
with flame geometry on its layered fire materials (LayeredFireV2 / V3, Fire_Layered_ArmisticeArchive_01,
FiresGeneric_*: flame_probe found them) plus particles. This prints:
  1. every NIF in the Starfield mesh archives whose text names a fire material (--mat-match): the materials, its
     BSGeometry shapes (name, material, LOD 0 vertex count and size in metres, translation) via flame_probe's layout;
  2. the Starfield.esm records (STAT, MSTT, ACTI, FURN, MISC, LIGH, CONT ...) whose model is one of those NIFs, with
     their size and any particle system (.psfx) they carry.

    python -I scripts\\interior\\sf_firepit_probe.py --starfield "<Starfield>"
"""
import argparse
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import ba2, nif as nifmod, sfplugin  # noqa: E402

MAT = r"layeredfire|fire_layered|firesgeneric|firesprite|firewispy|embers|firecandle|campfire|firepit"
TYPES = "STAT,MSTT,ACTI,FURN,MISC,LIGH,CONT,BNDS,PKIN,GBFM"


def fire_materials(nif_bytes: bytes, pattern: str = MAT) -> list:
    """The .mat paths named in a NIF that look like fire materials."""
    mats = {m.decode("latin-1") for m in re.findall(rb"[\w\\/ .-]+\.mat", nif_bytes)}
    return sorted(m for m in mats if re.search(pattern, m, re.I))


def norm(path: str) -> str:
    p = path.lower().replace("/", "\\").lstrip("\\")
    return p[7:] if p.startswith("meshes\\") else p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--mat-match", default=MAT)
    ap.add_argument("--layouts", type=int, default=12, help="NIFs laid out shape by shape")
    ap.add_argument("--types", default=TYPES)
    a = ap.parse_args(argv)
    import flame_probe
    data = os.path.join(a.starfield, "Data")
    arcs = [ba2.Ba2(os.path.join(data, f)) for f in sorted(os.listdir(data))
            if f.lower().endswith(".ba2") and ("mesh" in f.lower() or "main" in f.lower())]

    def read_any(name):
        for arc in arcs:
            i = arc.find(name)
            if i is not None:
                return arc.read(i)
        return None

    print("== 1. NIFs naming a fire material")
    found, seen = {}, set()
    for arc in arcs:
        for i, n in enumerate(arc.names):
            low = n.lower().replace("/", "\\")
            if not low.endswith(".nif") or low in seen or "\\lod" in low or "lodmeshes" in low:
                continue
            seen.add(low)
            try:
                b = arc.read(i)
            except Exception:                                       # noqa: BLE001
                continue
            mats = fire_materials(b, a.mat_match)
            if mats:
                found[norm(n)] = (n, mats, b)
    print(f"  {len(found)} NIFs of {len(seen)}")
    for k, (n, mats, _b) in sorted(found.items()):
        print(f"  {n}: {mats}")
    shown = 0
    for k, (n, mats, b) in sorted(found.items(), key=lambda kv: (not re.search("pit|camp|hearth|brazier|bonfire",
                                                                             kv[0]), kv[0])):
        if shown >= a.layouts:
            break
        shown += 1
        print(f"== layout {n}")
        try:
            for row in flame_probe.sf_nif_layout(nifmod.parse(b), read_any):
                if row["type"] in ("BSGeometry", "NiNode", "BSLightingShaderProperty", "BSEffectShaderProperty") \
                        or "ParticleSystem" in row["type"]:
                    print("  " + str({k2: v for k2, v in row.items() if k2 not in ("extra", "mesh_flags", "flags")}))
        except Exception as e:                                      # noqa: BLE001
            print(f"  not laid out: {type(e).__name__}: {e}")

    print("== 2. records whose model is one of those NIFs")
    types = [t.strip().encode() for t in a.types.split(",") if t.strip()]
    for typ, _h, subs, fid in sfplugin.records(os.path.join(data, "Starfield.esm"), types):
        model = next((d for s, d in subs if s == b"MODL"), b"").rstrip(b"\0").decode("latin-1")
        if not model or norm(model) not in found:
            continue
        ob = next((d for s, d in subs if s == b"OBND" and len(d) == 24), None)
        size = ""
        if ob:
            lo, hi = struct.unpack_from("<3f", ob, 0), struct.unpack_from("<3f", ob, 12)
            size = " size " + "x".join(f"{h - l:.2f}" for l, h in zip(lo, hi)) + " m"
        psfx = sorted({m.decode("latin-1") for s, d in subs for m in re.findall(rb"[\w\\/.-]+\.psfx", d)})
        print(f"  {typ.decode()} {fid:08X} {sfplugin.edid(subs)}: {model}{size}{' psfx ' + str(psfx) if psfx else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
