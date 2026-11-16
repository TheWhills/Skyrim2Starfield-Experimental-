"""What Starfield.esm's own sandbox packages use for Energy (read-only).

2026-11-16 (owner, in game): Hilde "still chooses the chair over everything when she can"; Alvor stands at one idle spot
most of the day. make_schedule converts Skyrim's sandbox Energy (0-100, usually 50) x 0.01, to 0.5, on the scale
seen in ShopkeeperSchedules.esm (a mod: 0.1-0.8 in 186 of 191 sandboxes); Starfield.esm's own values were never read.
If vanilla sandboxes use 0-100 too, 0.5 is next to no energy and NPCs would hardly switch activities. This prints,
for every package whose template has an input named Energy, the value histogram per template, and the extremes.

    python -I scripts\\npc\\energy_survey.py --starfield "<Starfield>"
"""
import argparse
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)


def energy_of(pack, template) -> object:
    """The package's Energy value (its template names the inputs), or None."""
    import make_schedule as MS
    names = MS.definitions(template)
    for idx, inp in zip(MS.value_indexes(pack), pack["inputs"]):
        if MS.norm(names.get(idx)) == "energy":
            return inp["value"]
    return None


def bucket(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return repr(v)
    return f"{f:g}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    a = ap.parse_args(argv)
    from fo4sf import packages
    ix = packages.Index(os.path.join(a.starfield, "Data", "Starfield.esm"))
    try:
        packs = {fid: packages.parse_pack(ix.subs(fid), starfield=True) for fid in ix.by_type.get(b"PACK", [])}
    finally:
        ix.close()
    templates = {fid: p for fid, p in packs.items() if p["type"] == packages.TEMPLATE}
    hist, examples = defaultdict(Counter), defaultdict(list)
    for fid, p in packs.items():
        t = templates.get(p.get("template"))
        if t is None:
            continue
        v = energy_of(p, t)
        if v is None:
            continue
        b = bucket(v)
        hist[t["edid"]][b] += 1
        if len(examples[(t["edid"], b)]) < 3:
            examples[(t["edid"], b)].append(p["edid"])
    for tname in sorted(hist, key=lambda k: -sum(hist[k].values())):
        h = hist[tname]
        print(f"== {tname}: {sum(h.values())} packages")
        for b, n in sorted(h.items(), key=lambda kv: -kv[1])[:15]:
            print(f"   {b}: {n}  e.g. {', '.join(examples[(tname, b)])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
