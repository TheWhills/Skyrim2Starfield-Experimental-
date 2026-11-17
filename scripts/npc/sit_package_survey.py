"""What Starfield's Sit packages set, input by input (read-only).

2026-11-16 (owner, in game): Alvor's Sit package naming his forge (make_schedule --sit-at, a copy of vanilla
FC_Neon_AyumiKomikoDefaultPackage with the SingleRef set to the forge) is current (GetIsCurrentPackage 1), the forge
reference exists 12.8 m away, yet he stands still wherever he is put; a passtime places him in the forge. The Sit
template's inputs are 0:SingleRef, 1:Float, 2:Bool, 4:Bool, 6:TargetSelector, 8:Bool (build log); which of them stops
him is unknown. This prints the template's input names and, for every package on the Sit template, each input's value,
with UC07_Gel_Sit_Weld (a vanilla welder worker) and the package we copy marked, and how often each value occurs.
2026-11-17: --template Sandbox showed input 24 'Restrict Sandbox Targets' (a keyword filter) set on 9 vanilla packages;
every form an input names is now printed with its EditorID, the packages using it, and (for a keyword) the
furniture / idle markers / activators / statics carrying it. --watch prints more packages in full.

    python -I scripts\\npc\\sit_package_survey.py --starfield "<Starfield>"
"""
import argparse
import os
import re
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

WATCH = ("UC07_Gel_Sit_Weld", "FC_Neon_AyumiKomikoDefaultPackage", "GG_Sit_Lizzy", "MQ201B_Sarah_Pkg")


def show(v) -> str:
    """A short text for an input value (forms as hex, dicts compact)."""
    if isinstance(v, dict):
        if v.get("is_form"):
            return f"form {v.get('value', 0):08X}" + (f" ({v['type_name']})" if v.get("type_name") else "")
        return "{" + ", ".join(f"{k}={show(x)}" for k, x in v.items() if k not in ("raw",)) + "}"
    if isinstance(v, float):
        return f"{v:g}"
    return repr(v)


def rows(packs: dict, tpl_fid: int, names: dict, value_indexes) -> list:
    """[(edid, [(index, name, type, shown value)])] of the packages on the template."""
    out = []
    for fid, p in packs.items():
        if p.get("template") != tpl_fid:
            continue
        vals = []
        for idx, inp in zip(value_indexes(p), p["inputs"]):
            vals.append((idx, names.get(idx), inp.get("type"), show(inp.get("value"))))
        out.append((p.get("edid") or f"{fid:08X}", vals))
    return sorted(out)


FORM = re.compile(r"form ([0-9A-F]{8})")


def form_uses(rs) -> dict:
    """{(input index, name, FormID): [package EditorIDs]} for every non-null form an input value names."""
    out = defaultdict(list)
    for edid, vals in rs:
        for idx, name, _typ, v in vals:
            m = FORM.match(v)
            if m and int(m.group(1), 16):
                out[(idx, name, int(m.group(1), 16))].append(edid)
    return dict(out)


def keywords_of(kwda: bytes) -> list:
    """The FormIDs in a KWDA subrecord."""
    return [struct.unpack_from("<I", kwda, i)[0] for i in range(0, len(kwda) - len(kwda) % 4, 4)]


def holders(objects, kw: int) -> list:
    """[(type, edid)] of (type, edid, kwda bytes) objects whose keywords include kw."""
    return [(t, e) for t, e, k in objects if kw in keywords_of(k)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--template", default="Sit")
    ap.add_argument("--watch", nargs="*", default=[], help="more package EditorIDs to print in full")
    a = ap.parse_args(argv)
    watch = {w.lower() for w in a.watch}
    import make_schedule as MS
    from fo4sf import packages
    ix = packages.Index(os.path.join(a.starfield, "Data", "Starfield.esm"))
    try:
        packs = {fid: packages.parse_pack(ix.subs(fid), starfield=True) for fid in ix.by_type.get(b"PACK", [])}
        objects = []
        for typ in (b"FURN", b"IDLM", b"ACTI", b"STAT", b"MSTT"):
            for fid in ix.by_type.get(typ, []):
                k = next((d for sub, d in ix.subs(fid) if sub == b"KWDA"), None)
                if k:
                    objects.append((typ.decode(), ix.edid(fid) or f"{fid:08X}", k))
    except Exception:
        ix.close()
        raise
    tpl = next(((fid, p) for fid, p in packs.items()
                if p["type"] == packages.TEMPLATE and (p["edid"] or "").lower() == a.template.lower()), None)
    if tpl is None:
        ix.close()
        sys.exit(f"no template {a.template}")
    tfid, tp = tpl
    names = MS.definitions(tp)
    print(f"template {tp['edid']} {tfid:08X}: inputs " + ", ".join(
        f"{i}:{names.get(i)!r} ({inp.get('type')}, default {show(inp.get('value'))})"
        for i, inp in zip(MS.value_indexes(tp), tp["inputs"])))
    rs = rows(packs, tfid, names, MS.value_indexes)
    print(f"{len(rs)} packages use it")
    hist = defaultdict(Counter)
    for edid, vals in rs:
        for idx, name, typ, v in vals:
            hist[(idx, name, typ)][v if typ != "SingleRef" else ("form" if v.startswith("form") else v)] += 1
    for (idx, name, typ), c in sorted(hist.items(), key=lambda kv: kv[0][0]):
        print(f"  input {idx} {name!r} ({typ}): " + "; ".join(f"{v} x{n}" for v, n in c.most_common(6)))
    uses = form_uses(rs)
    if uses:
        print("\nforms the inputs name (input, form, EditorID, type: packages; objects carrying a keyword):")
    for (idx, name, fid), eds in sorted(uses.items()):
        kind = ix.kind(fid)
        print(f"  input {idx} {name!r}: {fid:08X} {ix.edid(fid)} ({kind}) used by {len(eds)}: " + ", ".join(eds[:8]))
        if kind == "KYWD":
            hs = holders(objects, fid)
            by = Counter(t for t, _e in hs)
            print(f"      carried by {len(hs)} objects ({', '.join(f'{t} {n}' for t, n in by.items()) or 'none'}): "
                  + ", ".join(e for _t, e in hs[:12]))
    ix.close()
    for edid, vals in rs:
        if edid in WATCH or edid.lower() in watch:
            print(f"\n{edid}:")
            for idx, name, typ, v in vals:
                print(f"  {idx} {name!r} ({typ}) = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
