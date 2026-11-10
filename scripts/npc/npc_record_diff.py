"""Which subrecords of an NPC differ between two plugins (owner, 2026-11-09: Delphine's dress shows skin at the
shoulders in the Riverwood build, Ysolda's - the same mesh and texture, outfit_probe - does not when spawned from
S2SFaceTest.esm; the Riverwood build's Delphine is FO4Port.esm's copy of her face-test NPC, written through Mutagen).
Read-only.

    python -I scripts\\npc\\npc_record_diff.py --a "$mods\\S2S Face Test\\S2SFaceTest.esm" --b C:\\Modding\\work\\s2s\\riverwood_doors\\convert\\FO4Port.esm --npc Delphine

2026-11-09: any record type (--type FURN) and records with different EditorIDs (--pair A=B): our alchemy lab
(S2S_Furn_CraftingAlchemyWorkbenchTabletop in FO4Port.esm, E does nothing even on open floor) against the Starfield
workbench it copies (WorkbenchChem in Starfield.esm, works once moved to open floor):

    python -I scripts\\npc\\npc_record_diff.py --type FURN --a "$sf\\Data\\Starfield.esm" --b C:\\Modding\\work\\s2s\\riverwood_doors\\convert\\FO4Port.esm --pair WorkbenchChem=S2S_Furn_CraftingAlchemyWorkbenchTabletop

2026-11-10: --find SUBSTR lists the EditorIDs of --type in --a that contain it, and --show falls back to the first
such match (the showlooksmenu crash when hovering facial hair as S2S_OrcRace: what a vanilla beard head part names):

    python -I scripts\\npc\\npc_record_diff.py --type HDPT --a "$sf\\Data\\Starfield.esm" --b "$sf\\Data\\Starfield.esm" --find beard --show beard

Matches records by EditorID (the face-test NPCs' EditorIDs; FO4Port.esm keeps them in its override). Per
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


def npc_by_edid(path, rtype=b"NPC_"):
    out = {}
    for _t, _h, subs, fid in sfplugin.records(path, [rtype]):
        out.setdefault(sfplugin.edid(subs).lower(), (fid, subs))
    return out


def show(sig, d):
    d = bytes(d)
    if sig == b"SNAM" and len(d) % 4 == 0 and len(d) <= 64:      # FURN marker: offset, rotation, keyword, sides
        f = struct.unpack(f"<{len(d) // 4}f", d)
        return "floats [" + ", ".join(f"{x:.4g}" for x in f) + "] hex " + d.hex()
    if len(d) == 4 and sig not in FLOATS:
        return f"{struct.unpack('<I', d)[0]:08X}"
    if d and d[-1:] == b"\0" and all(32 <= c < 127 for c in d[:-1]):
        return repr(d[:-1].decode("latin-1"))[:80]
    if sig in FLOATS and len(d) % 4 == 0 and len(d) <= 64:
        return "[" + ", ".join(f"{x:.4g}" for x in struct.unpack(f"<{len(d) // 4}f", d)) + "]"
    return f"{len(d)} bytes {d[:24].hex()}{'...' if len(d) > 24 else ''}"


def outline(subs, keep=6):
    """Lines for a record's subrecords in order, a run of one signature longer than `keep` as one line."""
    out, i = [], 0
    subs = [(s, bytes(d)) for s, d in subs]
    while i < len(subs):
        j = i
        while j + 1 < len(subs) and subs[j + 1][0] == subs[i][0]:
            j += 1
        n = j - i + 1
        sig = subs[i][0].decode("latin-1")
        if n > keep:
            out.append(f"{sig} x{n}: {show(subs[i][0], subs[i][1])} ... {show(subs[j][0], subs[j][1])}")
        else:
            out += [f"{sig}: {show(s, d)}" for s, d in subs[i:j + 1]]
        i = j + 1
    return out


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


def find(recs, sub):
    """EditorIDs (lower case) in recs containing sub, sorted."""
    return sorted(e for e in recs if sub.lower() in e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--npc", action="append", default=[], help="EditorID (repeat)")
    ap.add_argument("--pair", action="append", default=[], help="EDID_A=EDID_B: two records with different EditorIDs")
    ap.add_argument("--type", default="NPC_", help="record type (default NPC_; e.g. FURN)")
    ap.add_argument("--show", action="append", default=[],
                    help="EDID: list that record's subrecords in order from --a (or --b if not there), runs of one "
                         "signature collapsed (2026-11-09: S2S_OrcRace against MannequinRace / HumanRace)")
    ap.add_argument("--find", action="append", default=[],
                    help="SUBSTR: list the EditorIDs of --type in --a containing it (2026-11-10)")
    a = ap.parse_args(argv)
    rtype = a.type.encode("ascii")[:4].ljust(4, b"_")
    A, B = npc_by_edid(a.a, rtype), npc_by_edid(a.b, rtype)
    for f in a.find:
        hits = find(A, f)
        print(f"{a.type} containing {f!r}: {len(hits)}")
        for e in hits[:60]:
            print(f"  {A[e][0]:08X} {e}")
    for e in a.show:
        k = e.lower()
        src = A.get(k) or B.get(k)
        if src is None and find(A, e):
            k = find(A, e)[0]
            src = A[k]
            e = k
        if src is None:
            print(f"{e}: not found")
            continue
        print(f"{e} {src[0]:08X}: {len(src[1])} subrecords")
        for line in outline(src[1]):
            print("  " + line)
    for pair in a.pair:
        ka, _, kb = pair.partition("=")
        ka, kb = ka.strip().lower(), kb.strip().lower()
        if ka not in A or kb not in B:
            print(f"{pair}: in A {ka in A}, in B {kb in B} {[e for e in B if kb[:12] in e][:8]}")
            continue
        (fa, sa), (fb, sb) = A[ka], B[kb]
        rows = diff(sa, sb)
        print(f"{ka} {fa:08X} vs {kb} {fb:08X}; {len(sa)} / {len(sb)} subrecords; {len(rows)} signatures differ")
        for sig, kind, text in rows:
            print(f"  {sig.decode('latin-1')}: {kind}: {text}")
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
