"""How Starfield builds its own fires (read-only): the records and files behind a real Starfield flame.

2026-11-15, owner on flames v3 (Skyrim textures on cards): "still looked low quality, like moving pngs compared to
flames". Cards cannot do what particles do, and particle_scan.py found no Gamebryo particle block in any of 79,344
Starfield NIFs; Starfield's fire ADDN records point at Effects\\fxemptynode.nif. So its particles live elsewhere.
This prints what is needed to place Starfield's own fire where Skyrim's burns:
  1. records whose EditorID looks like fire (ADDN, MSTT, ACTI, STAT, LIGH, EFSH, ARTO, PDCL ... --types): every
     subrecord with its size, the text it holds and short ones in hex (a particle-file path or a link shows here);
  2. archive file types: extension counts over every Starfield archive, and the fire-named files of every extension
     that is not a plain model / material / texture / mesh / sound (a particle asset format shows here);
  3. fire-named NIFs under meshes\\effects: block types and strings (what an effect NIF carries instead of particles).

    python -I scripts\\interior\\sf_fire_probe.py --starfield "<Starfield>"
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, nif as nifmod, sfplugin  # noqa: E402

FIRE = re.compile(r"fire|flame|campfire|brazier|torch|candle|hearth|burn|ember|bonfire", re.I)
NOT_FIRE = re.compile(r"firearm|fireext|firestation|firing|firework|firebolt|campfire_?sit", re.I)
PLAIN = {".nif", ".mat", ".dds", ".mesh", ".wem", ".bnk", ".lip", ".ffxanim", ".af", ".agx", ".hkx", ".txt",
         ".json", ".xml", ".pex", ".psc"}
TYPES = "ADDN,MSTT,ACTI,STAT,LIGH,EFSH,ARTO,PDCL,SPEL,MGEF,EXPL,HAZD,IMOD,FURN,MISC,PTFX"


def printable(b: bytes) -> str:
    """Text runs of 4+ printable characters in a field (paths, names)."""
    return " | ".join(x.decode("latin-1") for x in re.findall(rb"[ -~]{4,}", b))[:240]


def is_fire_name(name: str) -> bool:
    return bool(FIRE.search(name) and not NOT_FIRE.search(name))


def describe_record(typ: bytes, fid: int, subs) -> list:
    lines = [f"{typ.decode()} {fid:08X} {sfplugin.edid(subs)}"]
    for sig, d in subs:
        text = printable(d)
        small = d.hex() if len(d) <= 32 else ""
        lines.append(f"    {sig.decode('latin-1')} [{len(d)}] {small} {text}".rstrip())
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--types", default=TYPES)
    ap.add_argument("--per-type", type=int, default=12, help="records printed in full per type")
    ap.add_argument("--files", type=int, default=40, help="fire-named files listed per extension")
    ap.add_argument("--psfx-types", default="MSTT,ACTI,ARTO,HAZD,EXPL,STAT,ADDN,LIGH,PROJ,MGEF,EFSH,IMPF,IPCT",
                    help="record types searched for .psfx users (section 1b)")
    ap.add_argument("--only-psfx", action="store_true", help="section 1b only")
    a = ap.parse_args(argv)
    data = os.path.join(a.starfield, "Data")

    if a.only_psfx:
        a.per_type = 0
    print("== 1. fire records in Starfield.esm")
    types = [t.strip().encode() for t in a.types.split(",") if t.strip()]
    try:
        recs = sfplugin.records(os.path.join(data, "Starfield.esm"), types)
    except Exception as e:                                          # noqa: BLE001
        recs = []
        print(f"  not read: {type(e).__name__}: {e}")
    shown, counts = Counter(), Counter()
    for typ, _h, subs, fid in recs:
        e = sfplugin.edid(subs)
        if not is_fire_name(e):
            continue
        counts[typ] += 1
        if shown[typ] < a.per_type:
            shown[typ] += 1
            print("\n".join("  " + x for x in describe_record(typ, fid, subs)))
    print(f"  fire-named records per type: { {k.decode(): v for k, v in counts.items()} }")

    print("== 1b. records using a particle system (.psfx), fire-like by name or path")
    users = sfplugin.records(os.path.join(data, "Starfield.esm"), [t.strip().encode() for t in a.psfx_types.split(",")])
    n_users = 0
    for typ, _h, subs, fid in users:
        paths = sorted({m.decode("latin-1") for _s, d in subs if _s in (b"PTCL", b"PSDF")
                        for m in re.findall(rb"[\w\\/.-]+\.psfx", d)})
        if not paths:
            continue
        n_users += 1
        e = sfplugin.edid(subs)
        if FIRE.search(e) or any(FIRE.search(p) or re.search("smoke|spark|ember", p, re.I) for p in paths):
            ob = next((d for _s, d in subs if _s == b"OBND" and len(d) == 24), None)
            size = ""
            if ob:
                import struct as _st
                lo, hi = _st.unpack_from("<3f", ob, 0), _st.unpack_from("<3f", ob, 12)
                size = " size " + "x".join(f"{h - l:.2f}" for l, h in zip(lo, hi)) + " m"
            model = next((d for _s, d in subs if _s == b"MODL"), b"").rstrip(b"\0").decode("latin-1")
            print(f"  {typ.decode()} {fid:08X} {e}: {paths}{size} model {model}")
    print(f"  records with a particle system: {n_users}")
    if a.only_psfx:
        return 0
    print("== 2. archive file types")
    ext, fire_files, effect_nifs = Counter(), defaultdict(list), []
    archives = sorted(f for f in os.listdir(data) if f.lower().endswith(".ba2"))
    opened = {}
    for f in archives:
        try:
            arc = ba2.Ba2(os.path.join(data, f))
        except Exception as e:                                      # noqa: BLE001
            print(f"  {f}: not read ({type(e).__name__})")
            continue
        opened[f] = arc
        for i, n in enumerate(arc.names):
            low = n.lower().replace("\\", "/")
            x = os.path.splitext(low)[1]
            ext[x] += 1
            base = low.rsplit("/", 1)[-1]
            if x not in PLAIN and is_fire_name(base) and len(fire_files[x]) < a.files:
                fire_files[x].append(f"{f}: {n}")
            if x == ".nif" and "/effects/" in low and is_fire_name(base) and len(effect_nifs) < 25:
                effect_nifs.append((f, i, n))
    print(f"  extensions: {dict(ext.most_common(60))}")
    for x, files in sorted(fire_files.items()):
        print(f"  fire-named {x or '(none)'}: {len(files)} shown")
        for p in files:
            print(f"    {p}")

    print("== 3. fire-named effect NIFs")
    for f, i, n in effect_nifs:
        try:
            nf = nifmod.parse(opened[f].read(i))
        except Exception as e:                                      # noqa: BLE001
            print(f"  {n}: not parsed ({type(e).__name__})")
            continue
        blocks = Counter(nf.type_of(k) for k in range(len(nf.blocks)))
        strings = [s.decode("latin-1") if isinstance(s, bytes) else str(s) for s in nf.strings]
        print(f"  {n}: blocks {dict(blocks)}; strings {strings[:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
