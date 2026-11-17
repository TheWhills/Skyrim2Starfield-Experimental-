"""How Starfield itself sends NPCs to its work spots (read-only).

2026-11-16 (owner, in game): with energy fixed, the forge on a template of its own, FurnitureSpecial added, invisible
markers and Starfield's own walk-in all tried, neither Alvor nor Hilde ever chooses the forge or a tanning rack on
their sandbox; forced in, both play. So maybe Starfield's sandbox never picks these work spots and its own NPCs are
sent to them some other way. This finds, in Starfield.esm, the placed references of the work spots in --base (default:
the welder, wall-wipe, sweeping, bartender, standing repair) and then what points at them:
  - packages naming one as a location or target (their template, and the input),
  - actors linking to one (XLKR, with the link keyword: packages often say "near / use my linked reference"),
  - the references' own owner (XOWN) and linked references.

    python -I scripts\\npc\\work_spot_usage.py --starfield "<Starfield>"
"""
import argparse
import os
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

BASES = ("NPCWelder", "NPCStanding_WipeWall", "NPCStanding_WipeWall_ExitToTalk", "NPCSweeping", "NPCSweeping_ExitToTalk",
         "NPCBartender_Standing", "NPCRepairImpactWrench_Standing")


def linked_refs(subs) -> list:
    """[(keyword, ref)] of a record's XLKR subrecords."""
    out = []
    for s, d in subs:
        if s == b"XLKR" and len(d) >= 8:
            for i in range(0, len(d) - 7, 8):
                out.append(struct.unpack_from("<II", d, i))
    return out


def form_values(pack) -> list:
    """[(input index in value order, input type, form)] of a parsed package's location / target inputs naming a form."""
    out = []
    for i, inp in enumerate(pack.get("inputs") or []):
        v = inp.get("value")
        if isinstance(v, dict) and v.get("is_form") and v.get("value"):
            out.append((i, inp.get("type"), v["value"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--base", action="append", default=[])
    ap.add_argument("--max", type=int, default=15)
    a = ap.parse_args(argv)
    from fo4sf import packages
    ix = packages.Index(os.path.join(a.starfield, "Data", "Starfield.esm"))
    try:
        want = {}
        for e in a.base or BASES:
            fid = ix.find_edid(b"FURN", e)
            if fid is not None:
                want[fid] = e
        print("bases: " + ", ".join(f"{e} {f:08X}" for f, e in want.items()))
        refs = {}
        for fid in ix.by_type.get(b"REFR", []):
            subs = ix.subs(fid)
            base = next((struct.unpack_from("<I", d)[0] for s, d in subs if s == b"NAME" and len(d) == 4), None)
            if base in want:
                refs[fid] = (want[base], subs)
        per_base = Counter(b for b, _s in refs.values())
        print(f"placed: {dict(per_base)}")
        owned = Counter(b for b, s in refs.values() if any(sg == b"XOWN" for sg, _d in s))
        linked_from_ref = Counter(b for b, s in refs.values() if linked_refs(s))
        print(f"with an owner (XOWN): {dict(owned)}; with linked refs of their own: {dict(linked_from_ref)}")
        # actors linking to them
        kw_use = defaultdict(Counter)
        examples = defaultdict(list)
        for fid in ix.by_type.get(b"ACHR", []):
            for kw, r in linked_refs(ix.subs(fid)):
                if r in refs:
                    b = refs[r][0]
                    k = ix.edid(kw) or f"{kw:08X}"
                    kw_use[b][k] += 1
                    if len(examples[b]) < a.max:
                        examples[b].append(f"{ix.edid(fid) or f'{fid:08X}'} -[{k}]-> {r:08X}")
        print("== actors linking to a work spot (XLKR keyword: count)")
        for b, c in kw_use.items():
            print(f"  {b}: {dict(c.most_common(8))}")
            for ex in examples[b]:
                print(f"     {ex}")
        # packages naming them
        tpl_names = {}
        hits = defaultdict(Counter)
        pex = defaultdict(list)
        for fid in ix.by_type.get(b"PACK", []):
            p = packages.parse_pack(ix.subs(fid), starfield=True)
            for _i, typ, form in form_values(p):
                if form in refs:
                    b = refs[form][0]
                    t = p.get("template")
                    if t and t not in tpl_names:
                        tpl_names[t] = ix.edid(t) or f"{t:08X}"
                    tn = tpl_names.get(t, "(no template)") if t else "(no template)"
                    hits[b][f"{tn} ({typ})"] += 1
                    if len(pex[b]) < a.max:
                        pex[b].append(f"{p['edid']}: {tn}, {typ} -> {form:08X}")
        print("== packages naming a work spot reference (template (input type): count)")
        for b, c in hits.items():
            print(f"  {b}: {dict(c.most_common(8))}")
            for ex in pex[b]:
                print(f"     {ex}")
        print("(references neither linked from an actor nor named by a package are used, if at all, by sandboxes)")
    finally:
        ix.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
