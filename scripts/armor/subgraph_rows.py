"""Every row of Starfield's generated HumanRace subgraph table that names given keywords, whatever its role (read-only).

2026-11-15, owner: seated Hilde still played Starfield's talk gesture (hand to chin, arm across) although our Sit set
answers the furniture graph's 38 talk tags (verified on the owner's PC: the descriptors and the Creation Kit cache).
stance_plugin copies only the Furniture-role rows; a row of another role (dialogue, face, additive) that also matches
AnimFurnChair / AnimFurnBench would play from its own folders. This lists them all: role, perspective, actor and target
keywords, graph, folders.

    python -I scripts\\armor\\subgraph_rows.py --starfield "<Starfield>" --keyword AnimFurnChair --keyword AnimFurnBench
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stance_plugin  # noqa: E402

TALKY = ("dialog", "talk", "convers", "gesture")


def matching(rows, keywords, talky=True):
    """Rows naming any of `keywords` (actor or target, case ignored), plus with talky every row whose role or graph
    looks like dialogue."""
    want = {k.lower() for k in keywords}
    out = []
    for r in rows:
        names = {x.lower() for x in r["actor"] + r["target"]}
        text = (r["role"] + " " + r["graph"]).lower()
        if names & want or (talky and any(t in text for t in TALKY)):
            out.append(r)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", help="the Starfield folder (the table is read from its archives)")
    ap.add_argument("--table", help="a humanrace.txt already extracted (instead of --starfield)")
    ap.add_argument("--keyword", action="append", default=[], help="keyword EditorID (repeatable)")
    ap.add_argument("--no-talky", dest="talky", action="store_false", help="leave out the dialogue-looking rows")
    a = ap.parse_args(argv)
    if a.table:
        with open(a.table, "rb") as fh:
            text = fh.read().decode("utf-8", "replace")
    elif a.starfield:
        text = stance_plugin.read_table(os.path.join(a.starfield, "Data"))
        if text is None:
            sys.exit(f"{stance_plugin.GENERATED_TABLE} not found in the archives")
    else:
        ap.error("--starfield or --table")
    rows = stance_plugin.parse_table(text)
    got = matching(rows, a.keyword, a.talky)
    by_role = {}
    for r in got:
        by_role[r["role"]] = by_role.get(r["role"], 0) + 1
    print(f"{len(rows)} rows; {len(got)} match: " + ", ".join(f"{k} {v}" for k, v in sorted(by_role.items())))
    for r in got:
        print(f"{r['role']} | {r['perspective']} | actor {','.join(r['actor']) or '-'} | target "
              f"{','.join(r['target']) or '-'} | {r['graph'].split(chr(92))[-1]} | {', '.join(r['paths'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
