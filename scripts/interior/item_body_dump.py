"""Decode the physics bodies of a few vanilla Starfield loose items in full (docs/interior/items.md step 1). Read-only.

2026-11-20 (owner's item_physics_probe run, verified): the 10 box-layout item bodies it compared were all static
cargo crates (motion word as the static template); the loose items use hknpConvexShape (2967 bodies; tagfiles of
7088 / 7376 bytes most often). Our own convex bodies (meshcollision) are written static ("no mass properties"), so
the fields that make a body dynamic are read here from vanilla items, decoded with hktagfile (every object, every
field, by the file's own type table) instead of fixed offsets.

    python -I scripts\\interior\\item_body_dump.py --sf-data "<Starfield>\\Data" --out C:\\Modding\\work\\items

Picks: the items named by --edid, else up to --per kinds of each: ALCH whose EditorID has wine / beer / bottle /
whiskey, food (ALCH with food / bread / apple), MISC with a convex body; plus the static template. Writes
item_bodies.json (decoded roots, long arrays cut to their first --keep entries) and item_bodies.md (per item: model,
blob size, shape classes, the motion / body / material entries).
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import hktagfile, sfplugin  # noqa: E402
import item_physics_probe as P  # noqa: E402

KINDS = {"drink": (b"ALCH", r"wine|beer|bottle|whiskey|whisky|liquor|spirits"),
         "food": (b"ALCH", r"food|bread|apple|fruit|meat|cheese|melon"),
         "misc": (b"MISC", r".")}


def cut(v, keep):
    """v with every list cut to its first `keep` entries (and their length noted)."""
    if isinstance(v, list):
        out = [cut(x, keep) for x in v[:keep]]
        if len(v) > keep:
            out.append(f"... {len(v)} in all")
        return out
    if isinstance(v, dict):
        return {k: cut(x, keep) for k, x in v.items()}
    if isinstance(v, float):
        return round(v, 6)
    return v


def decode(blob, keep):
    try:
        return cut(hktagfile.Tagfile(blob).root(), keep)
    except Exception as e:                               # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}


def picks(sf_data, arcs, edids, per):
    want = {e.lower() for e in edids}
    got, counts = [], {k: 0 for k in KINDS}
    for t, _h, subs, fid in sfplugin.records(os.path.join(sf_data, "Starfield.esm"), (b"ALCH", b"MISC")):
        e = sfplugin.edid(subs)
        modl = next((P.text_of(d) for s, d in subs if s == b"MODL"), "")
        if not modl:
            continue
        kind = None
        if want:
            if e.lower() not in want:
                continue
            kind = "named"
        else:
            for k, (sig, rx) in KINDS.items():
                if t == sig and counts[k] < per and re.search(rx, e, re.I):
                    kind = k
                    break
            if kind is None:
                continue
        try:
            bs = P.bodies(arcs.read("meshes\\" + modl))
        except Exception:                                # noqa: BLE001
            continue
        if not bs or not any(b"hknpConvexShape" in b or b"hknpConvexPolytopeShape" in b for _n, b in bs):
            continue
        if kind in counts:
            counts[kind] += 1
        got.append({"kind": kind, "type": t.decode(), "edid": e, "form_id": f"{fid:08X}", "model": modl,
                    "bodies": bs})
        if not want and all(c >= per for c in counts.values()):
            break
    return got


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--edid", action="append", default=[])
    ap.add_argument("--per", type=int, default=2)
    ap.add_argument("--keep", type=int, default=6)
    a = ap.parse_args(argv)
    arcs = P.Archives(a.sf_data)
    rows = picks(a.sf_data, arcs, a.edid, a.per)
    try:
        rows.append({"kind": "static template", "type": "STAT", "edid": "", "form_id": "",
                     "model": P.STATIC_TEMPLATE, "bodies": P.bodies(arcs.read(P.STATIC_TEMPLATE))})
    except FileNotFoundError:
        pass
    out = []
    for r in rows:
        out.append({k: v for k, v in r.items() if k != "bodies"} | {
            "bodies": [{"node": nm, "bytes": len(b), "shapes": [s.decode() for s in P.SHAPES if s in b],
                        "decoded": decode(b, a.keep)} for nm, b in r["bodies"]]})
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "item_bodies.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    L = ["# Vanilla item bodies, decoded", ""]
    for r in out:
        L.append(f"## {r['kind']}: {r['type']} {r['edid']} {r['form_id']} - {r['model']}")
        for b in r["bodies"]:
            L.append(f"- body {b['node']}: {b['bytes']} bytes, {', '.join(b['shapes'])}")
            L.append("```")
            L.append(json.dumps(b["decoded"], indent=1, default=str)[:6000])
            L.append("```")
        L.append("")
    with open(os.path.join(a.out, "item_bodies.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"{len(out)} models -> {os.path.join(a.out, 'item_bodies.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
