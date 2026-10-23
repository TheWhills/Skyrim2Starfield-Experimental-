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


POWER_EVENT = "MeleeAttackPowerStart"          # vanilla: None / PowerB -> MeleeAttackPower_A on this event
POWER_TOP = "MeleeAttackPower_A"
OUTER_OFF = "S2S_ComboPowerInside"              # an event nothing sends


def build(raw: bytes, routing: dict, tags=None, power=None):
    """(graph bytes, report) for routing {k: next k} over attacks 1..N; tags {k: clip tag} overrides the default
    BFCO_Attack<k> (e.g. the vanilla MeleeAttack_A for attack 1).
    power (optional, MCO / BFCO power routing): {"tags": {p: clip tag}, "attack_power": {k: p},
    "power_attack": {p: k}, "power_power": {p: p'}}: every power attack p with a tag becomes a state inside the combo
    machine (a copy of attack 2's state), entered from normal attacks and other power attacks on
    MeleeAttackPowerStart and leaving to the next normal attack on MeleeAttackStart; targets without a tag go to the
    first tagged power attack. The top-level vanilla power attack (the power attack from standing) also gets
    MeleeAttackStart -> the combo, so a normal press after it continues the chain.
    power["inner_only"]: every combo state has its own power transition, so the vanilla top-level transition
    combo -> MeleeAttackPower_A on MeleeAttackPowerStart is switched off (its event renamed to OUTER_OFF): it caught
    the power press before the combo's own states (owner, 2026-10-23: every mid-combo power attack played
    MeleeAttackPower_A although the graph took the event)."""
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
    if power and power.get("tags"):
        ptags = power["tags"]
        first = min(ptags)
        pidx = {}
        for p in sorted(ptags):
            i = agx_edit.clone_state(b_node, g, root)
            agx_edit.set_tag(g.findall("node")[i], ptags[p])
            pidx[p] = i
        to_p = lambda p: p if p in pidx else first                     # noqa: E731
        to_a = lambda k: k if k in idx else min(idx)                   # noqa: E731
        for k, p in sorted(power.get("attack_power", {}).items()):
            if k in idx and agx_edit.add_transition(root, g, idx[k], pidx[to_p(p)], POWER_EVENT, blend=0.15,
                                                    template=tpl):
                added.append(f"{tag(k, tags)} =power=> {ptags[to_p(p)]}")
        for p, k in sorted(power.get("power_attack", {}).items()):
            if p in pidx and agx_edit.add_transition(root, g, pidx[p], idx[to_a(k)], "MeleeAttackStart", blend=0.15,
                                                     template=tpl):
                added.append(f"{ptags[p]} -> {tag(to_a(k), tags)}")
        for p, q in sorted(power.get("power_power", {}).items()):
            if p in pidx and agx_edit.add_transition(root, g, pidx[p], pidx[to_p(q)], POWER_EVENT, blend=0.15,
                                                     template=tpl):
                added.append(f"{ptags[p]} =power=> {ptags[to_p(q)]}")
        try:                                                            # top level: standing power attack -> combo
            top_power = agx_edit.state(root, POWER_TOP)
            combo = agx_edit.state(root, MACHINE)
        except agx_edit.AgxEditError:
            top_power = combo = None
        if top_power is not None and agx_edit.add_transition(root, root, top_power, combo, "MeleeAttackStart",
                                                             blend=0.15):
            added.append(f"{POWER_TOP} -> {MACHINE}")
        if top_power is not None and power.get("inner_only"):
            n_off = agx_edit.set_event(root, combo, top_power, OUTER_OFF, POWER_EVENT)
            added.append(f"{MACHINE} =power=> {POWER_TOP} switched off ({n_off})")
    return agx_edit.dump(root, raw), added


def _marks(folder: str, files: dict) -> dict:
    marks = {}
    for k, fn in files.items():
        with open(os.path.join(folder, fn), "rb") as fh:
            try:
                d = skyrimhkx.describe(fh.read())
            except skyrimhkx.HkxError:
                d = {}
        anns = d["animations"][0]["annotations"] if d.get("animations") else []
        marks[k] = bfco.markers(anns)
    return marks


def routes_of(folder: str) -> dict:
    """bfco.routes over the folder's normal and power attacks (see there)."""
    g = bfco.attack_files(sorted(os.listdir(folder)))
    return bfco.routes(_marks(folder, g["attack"]), _marks(folder, g["power"]))


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
    ap.add_argument("--power-tag", action="append", default=[], metavar="P=NAME",
                    help="clip tag of power attack P; given ones get states and the power routing (repeatable)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    routing = routes_of(a.moveset)["attack"] if a.power_tag else routing_of(a.moveset)
    if not routing:
        sys.exit("no BFCO_AttackN / mco_attackN clips in the moveset")
    tags, ptags = {}, {}
    for spec, into in [(t, tags) for t in a.tag] + [(t, ptags) for t in a.power_tag]:
        k, _, name = spec.partition("=")
        if not (k.isdigit() and name):
            sys.exit(f"--tag / --power-tag want K=NAME, got {spec}")
        into[int(k)] = name
    if tags:                                   # attacks without a slot are left out: their incoming edges go to 1
        first = min(tags)
        routing = {k: (n if n in tags else first) for k, n in routing.items() if k in tags}
    power = None
    if ptags:
        r = routes_of(a.moveset)
        power = {"tags": ptags, "attack_power": r["attack_power"], "power_attack": r["power_attack"],
                 "power_power": r["power_power"]}
    with open(a.graph, "rb") as fh:
        data, added = build(fh.read(), routing, tags, power)
    dst = os.path.join(out, *GRAPH_REL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(data)
    print(f"routing {routing}; graph {dst}; added {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
