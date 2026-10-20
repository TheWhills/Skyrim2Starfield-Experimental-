"""Make the player's melee combo work as in Skyrim: right, left, right, left ... for as long as attack is pressed, and
(with --actions-graph) while walking or running, instead of Starfield's three standing hits
(docs/armor/animation-port.md, "only three hits" and "moving attacks").

Vanilla (verified 2026-10-19 on the owner's MeleeAttacks.agx, MeleeActions.agx, Player_Melee.agx and the player
one-handed descriptors):
  * MeleeAttacks: the embedded state machine MeleeAttackCombo, entered from any state on MeleeAttackStart, goes
    None -> MeleeAttack_A -> MeleeAttack_B on MeleeAttackStart and B -> C on MeleeAttackFinisherStart; nothing leaves C.
    A and B open a bCanComboAttack window, B also bAllowFinisher (so the game sends the finisher event); C has no combo
    window and bDontAllowAttack over almost all of it.
  * Player_Melee plays MeleeAttacks FULL BODY (a Switch away from locomotion) but layers MeleeActions (block, casts,
    equip) over locomotion through Copy Bone Weights. With the swing in MeleeAttacks the player stops until it ends,
    even with bFreeMovement open over the whole swing (owner, in game: the --move-while-attacking experiment of
    2026-10-19, since removed).

This writes:
  * <out>/.../graphs/meleeattacks.agx: the vanilla graph plus C -> B and B -> C on MeleeAttackStart; with
    --actions-graph its combo is no longer entered on MeleeAttackStart (event renamed to MeleeAttackStartFullBody,
    which nothing sends);
  * with --actions-graph, <out>/.../graphs/meleeactions.agx: the vanilla MeleeActions plus a copy of that (looping)
    combo machine as one more action, entered from any state on MeleeAttackStart and left for IdleTimer when it ends,
    so the swing is layered over walking like a block or a cast (the approach of the SW SFBM mod, Nexus 16022, which
    the owner pointed to; built here from the vanilla files, nothing copied from the mod);
  * in each --clips folder holding our MeleeAttack_A / _B / _C descriptors (the Skyrim replacements, where A and C
    are both Skyrim's right swing): C takes A's timing (hit, combo window, attack locks), B loses bAllowFinisher.
Starfield's finisher is dropped on purpose: Skyrim has none. Power and sprint attacks stay full body.

    python -I scripts\\armor\\combo_loop.py --graph <extract>\\meleeattacks.agx [--actions-graph <extract>\\meleeactions.agx]
        --clips <pack>\\meshes\\actors\\human\\animations\\melee\\onehanded\\player [--clips ...\\player\\sword ...]
        --out <pack>
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import af_writer, agx_edit  # noqa: E402

GRAPHS = ("meshes", "animtextdata", "tables", "graphs")
GRAPH_REL = GRAPHS + ("meleeattacks.agx",)
ACTIONS_REL = GRAPHS + ("meleeactions.agx",)
MACHINE = "MeleeAttackCombo"
LOOP = (("MeleeAttack_C", "MeleeAttack_B"), ("MeleeAttack_B", "MeleeAttack_C"))
UNUSED_EVENT = "MeleeAttackStartFullBody"
IDLE_STATE = "IdleTimer"


def loop_graph(raw: bytes, layered: bool = False):
    """(edited MeleeAttacks bytes, the looping combo state <node>, report lines)."""
    root = agx_edit.load(raw)
    g = agx_edit.machine(root, MACHINE)
    tpl = None
    b = agx_edit.state(g, "MeleeAttack_B")
    for link in agx_edit._links_into(g.findall("node")[b]):     # the vanilla A -> B link: same blend and layout
        tpl = link
    added = []
    for s, d in LOOP:
        if agx_edit.add_transition(root, g, agx_edit.state(g, s), agx_edit.state(g, d), "MeleeAttackStart",
                                   blend=0.15, template=tpl):
            added.append(f"{s} -> {d}")
    top = agx_edit.machine(root, None)
    k = agx_edit.state(top, MACHINE)
    combo_node = top.findall("node")[k]
    if layered:
        n = agx_edit.set_event(top, k, k, UNUSED_EVENT, old="MeleeAttackStart")
        added.append(f"full-body combo no longer entered on MeleeAttackStart ({n} transition)")
    return agx_edit.dump(root, raw), combo_node, added


def layer_combo(actions_raw: bytes, combo_node):
    """MeleeActions with the combo state added as a layered action (see the module docstring)."""
    root = agx_edit.load(actions_raw)
    top = agx_edit.machine(root, None)
    idle = agx_edit.state(top, IDLE_STATE)
    if MACHINE in [agx_edit._rows(n).get("State Machine Name") for n in top.findall("node")]:
        raise agx_edit.AgxEditError(f"{MACHINE} is already in this MeleeActions")
    k = agx_edit.clone_state(combo_node, top)
    agx_edit.add_transition(root, top, k, k, "MeleeAttackStart", blend=0.15)      # from any state, as vanilla
    agx_edit.add_transition(root, top, k, idle, "", blend=0.3)                     # back to idle when it ends
    return agx_edit.dump(root, actions_raw), [f"{MACHINE} added as action {k} (any state -> it on MeleeAttackStart, "
                                              f"-> {IDLE_STATE} at its end)"]


def fix_descriptors(folder: str):
    names = {f.lower(): f for f in os.listdir(folder)}
    a, b, c = (names.get(f"meleeattack_{x}.afx") for x in "abc")
    done = []
    if a and c:
        with open(os.path.join(folder, a), "rb") as fh:
            src = fh.read()
        with open(os.path.join(folder, c), "rb") as fh:
            dst = fh.read()
        with open(os.path.join(folder, c), "wb") as fh:
            fh.write(af_writer.copy_timing(src, dst))
        done.append(f"{c}: timing of {a}")
    if b:
        with open(os.path.join(folder, b), "rb") as fh:
            data, dropped = af_writer.drop_variables(fh.read(), {"bAllowFinisher"})
        with open(os.path.join(folder, b), "wb") as fh:
            fh.write(data)
        if dropped:
            done.append(f"{b}: dropped {', '.join(dropped)}")
    return done


def _write(out, rel, data):
    dst = os.path.join(out, *rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(data)
    return dst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, help="the vanilla MeleeAttacks.agx")
    ap.add_argument("--actions-graph", help="the vanilla MeleeActions.agx: also layer the combo over walking")
    ap.add_argument("--clips", action="append", default=[], help="folder with MeleeAttack_A/B/C.afx (repeatable)")
    ap.add_argument("--out", required=True, help="pack root (Data layout) for the edited graphs")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    with open(a.graph, "rb") as fh:
        data, combo, added = loop_graph(fh.read(), layered=bool(a.actions_graph))
    print(f"graph: {_write(out, GRAPH_REL, data)}; {added or 'nothing changed (already looping)'}")
    if a.actions_graph:
        with open(a.actions_graph, "rb") as fh:
            data, rep = layer_combo(fh.read(), combo)
        print(f"graph: {_write(out, ACTIONS_REL, data)}; {rep}")
    for folder in a.clips:
        print(f"{folder}: {fix_descriptors(folder) or 'no A / B / C descriptors'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
