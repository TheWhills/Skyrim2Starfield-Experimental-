"""Rebuild the player's melee combo from a BFCO moveset's routing (docs/armor/animation-port.md, "BFCO plan").

The vanilla MeleeAttacks.agx combo machine (None -> MeleeAttack_A -> _B on MeleeAttackStart, _B -> _C on the finisher;
see combo_loop.py) becomes BFCO_Attack1 .. BFCO_AttackN: A, B and C are retagged BFCO_Attack1 / 2 / 3, attacks 4..N are
copies of B (its enter / exit events, flags and settings), and every attack k gets a transition to its BFCO
successor (BFCO_NextIsAttackN, fo4sf.bfco.chain) on MeleeAttackStart. Nothing else in the graph changes; the clips
themselves come from hkx_to_af --replace CLIP::<vanilla meleeattack_a.afx>::BFCO_AttackK --bfco.

    python -I scripts\\armor\\bfco_combo.py --graph <extract>\\meleeattacks.agx --moveset <BFCO folder> --out <pack>
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import agx_edit, bfco, skyrimhkx  # noqa: E402

GRAPH_REL = ("meshes", "animtextdata", "tables", "graphs", "meleeattacks.agx")
MACHINE = "MeleeAttackCombo"
VANILLA = ("MeleeAttack_A", "MeleeAttack_B", "MeleeAttack_C")


def tag(k: int, tags=None) -> str:
    return (tags or {}).get(k) or f"BFCO_Attack{k}"


def build(raw: bytes, routing: dict, tags=None):
    """(graph bytes, report) for routing {k: next k} over attacks 1..N; tags {k: clip tag} overrides the default
    BFCO_Attack<k> (e.g. the vanilla MeleeAttack_A for attack 1)."""
    root = agx_edit.load(raw)
    g = agx_edit.machine(root, MACHINE)
    nodes = g.findall("node")
    idx = {}
    keys = sorted(routing)                     # attack numbers may have gaps (unreachable attacks left out)
    for vt, k in zip(VANILLA, keys):
        i = agx_edit.state(g, vt)
        agx_edit.set_tag(nodes[i], tag(k, tags))
        idx[k] = i
    second = keys[1] if len(keys) > 1 else None
    b_node = nodes[idx[second] if second is not None else agx_edit.state(g, VANILLA[1])]
    for k in sorted(routing):
        if k not in idx:
            i = agx_edit.clone_state(b_node, g, root)
            agx_edit.set_tag(g.findall("node")[i], tag(k, tags))
            idx[k] = i
    tpl = next(iter(agx_edit._links_into(g.findall("node")[idx[second]])), None) if second is not None else None
    added = []
    for k, n in sorted(routing.items()):
        if agx_edit.add_transition(root, g, idx[k], idx[n], "MeleeAttackStart", blend=0.15, template=tpl):
            added.append(f"{tag(k, tags)} -> {tag(n, tags)}")
    return agx_edit.dump(root, raw), added


def routing_of(folder: str) -> dict:
    """{k: next k} over the attacks the moveset actually plays from attack 1 (MCO_nextattack / BFCO_NextIsAttack
    routing, else in order); attacks no chain reaches are left out (Nordic's 1H attack 6)."""
    files = bfco.attack_files(sorted(os.listdir(folder)))["attack"]
    marks = {}
    for k, fn in files.items():
        with open(os.path.join(folder, fn), "rb") as fh:
            try:
                d = skyrimhkx.describe(fh.read())
            except skyrimhkx.HkxError:                      # unreadable here: no routing from it (the converter
                d = {}                                      # reports the clip itself)
        anns = d["animations"][0]["annotations"] if d.get("animations") else []
        marks[k] = bfco.markers(anns)
    if not marks:
        return {}
    r = bfco.chain(marks)
    return {k: r[k] for k in bfco.reachable(r, 1 if 1 in r else min(r))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, help="the vanilla MeleeAttacks.agx")
    ap.add_argument("--moveset", required=True, help="a BFCO moveset folder (BFCO_Attack1.hkx ...)")
    ap.add_argument("--out", required=True, help="pack root (Data layout)")
    ap.add_argument("--tag", action="append", default=[], metavar="K=NAME",
                    help="clip tag for attack K instead of BFCO_AttackK (repeatable)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    routing = routing_of(a.moveset)
    if not routing:
        sys.exit("no BFCO_AttackN / mco_attackN clips in the moveset")
    tags = {}
    for t in a.tag:
        k, _, name = t.partition("=")
        if not (k.isdigit() and name):
            sys.exit(f"--tag wants K=NAME, got {t}")
        tags[int(k)] = name
    with open(a.graph, "rb") as fh:
        data, added = build(fh.read(), routing, tags)
    dst = os.path.join(out, *GRAPH_REL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(data)
    print(f"routing {routing}; graph {dst}; added {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
