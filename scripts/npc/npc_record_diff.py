"""Which subrecords of an NPC differ between two plugins (owner, 2026-11-09: Delphine's dress shows skin at the
shoulders in the Riverwood build, Ysolda's - the same mesh and texture, outfit_probe - does not when spawned from
S2SFaceTest.esm; the Riverwood build's Delphine is FO4Port.esm's copy of her face-test NPC, written through Mutagen).
Read-only.

    python -I scripts\\npc\\npc_record_diff.py --a "$mods\\S2S Face Test\\S2SFaceTest.esm" --b C:\\Modding\\work\\s2s\\riverwood_doors\\convert\\FO4Port.esm --npc Delphine

Matches NPC_ records by EditorID (the face-test NPCs' EditorIDs; FO4Port.esm keeps them in its override). Per
signature: only in A, only in B, or different (count and bytes; MWGT is printed as floats). Writes nothing.
"""
import argparse
import struct
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import sfplugin  # noqa: E402

FLOATS = (b"MWGT", b"MRSV", b"NAM6", b"NAM7")


def npc_by_edid(path):
    out = {}
    for _t, _h, subs, fid in sfplugin.records(path, [b"NPC_"]):
        out.setdefault(sfplugin.edid(subs).lower(), (fid, subs))
    return out


def show(sig, d):
    d = bytes(d)
    if sig in FLOATS and len(d) % 4 == 0 and len(d) <= 64:
        return "[" + ", ".join(f"{x:.4g}" for x in struct.unpack(f"<{len(d) // 4}f", d)) + "]"
    return f"{len(d)} bytes {d[:24].hex()}{'...' if len(d) > 24 else ''}"


def diff(a_subs, b_subs):
    """[(sig, kind, text)] kind: 'only A', 'only B', 'differs' (subrecords compared in order per signature)."""
    def group(subs):
        g = {}
        for s, d in subs:
            g.setdefault(s, []).append(bytes(d))
        return g
    ga, gb = group(a_subs), group(b_subs)
    rows = []
    for sig in list(ga) + [s for s in gb if s not in ga]:
        xa, xb = ga.get(sig, []), gb.get(sig, [])
        if not xb:
            rows.append((sig, "only A", "; ".join(show(sig, d) for d in xa[:3])))
        elif not xa:
            rows.append((sig, "only B", "; ".join(show(sig, d) for d in xb[:3])))
        elif xa != xb:
            rows.append((sig, "differs", f"A {len(xa)}x {show(sig, xa[0])} | B {len(xb)}x {show(sig, xb[0])}"))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--npc", action="append", required=True, help="EditorID (repeat)")
    a = ap.parse_args(argv)
    A, B = npc_by_edid(a.a), npc_by_edid(a.b)
    for who in a.npc:
        k = who.lower()
        hits = [e for e in A if k in e]
        key = k if k in A else (hits[0] if len(hits) == 1 else None)
        if key is None or key not in B:
            near = [e for e in B if k in e][:10]
            print(f"{who}: in A {key is not None and key in A} ({hits[:5]}), in B {key in B if key else False} {near}")
            continue
        fa, sa = A[key]
        fb, sb = B[key]
        rows = diff(sa, sb)
        print(f"{key}: A {fa:08X}, B {fb:08X}; {len(sa)} / {len(sb)} subrecords; {len(rows)} signatures differ")
        for sig, kind, text in rows:
            print(f"  {sig.decode('latin-1')}: {kind}: {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
