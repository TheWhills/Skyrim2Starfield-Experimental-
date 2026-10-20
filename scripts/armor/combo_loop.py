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

--free-movement (with --actions-graph; EXPERIMENT): bFreeMovement open over all of A / B / C. Owner, in game, with the
layered combo: attacking while moving keeps moving (and turning), but a swing started standing still holds the player
until it ends - vanilla opens bFreeMovement only late in each clip, so this tests whether that window is what holds
him (Skyrim lets you start moving during any swing).

--upper-body (with --actions-graph; EXPERIMENT): flag the layered combo "Force Copy Bone Weights", as vanilla flags
Equip / Unequip. Owner, in game, with --free-movement: a combo started standing does start moving, but slowly
(inching, then walk, jog, run over several swings) and sometimes not at all. Supported hypothesis: Player_Melee's
Copy Bone Weights uses the BoneWeights masks only while walking / turning / jumping (its inputs), so a standing swing
is layered full body - legs and root included - and Starfield's momentum locomotion (Biped_IdleLocomotion: Momentum
nodes, StandToWalk / StandToRun on CurrentSpeed vs Speed) barely accelerates under it until the walking mask takes
over. Forcing the mask keeps the legs on locomotion always: instant movement, but a standing swing loses Skyrim's
leg work (the step-in).

--no-pivot (with --actions-graph; EXPERIMENT): owner, with --free-movement --upper-body: moving off mid-combo is
instant but only sometimes ("if you time it right") and only straight ahead. Supported hypothesis: the swing's
facing controls fight Starfield's move-start, which turns the body with the start clip (Set Orient "Turn Animation
Modify Translation", bPlayerMoveStartActive): the combo machine and MeleeAttack_A carry "Should Pivot to Camera",
and each swing holds bAlignWithAimAssistTarget early and DisableAllowRotation late. This clears the pivot flags on
the layered copy and drops those two windows from A / B / C.

--no-attack-events (with --actions-graph; EXPERIMENT): owner, in game: with the plain layered combo (and every
variant above) the player keeps moving in the last pushed direction for as long as attacks continue, even with the
stick released. Vanilla's combo states send AttackStart on enter and AttackStop on exit (Enter / Exit Events); the
SFBM mod's layered A / B / C send neither (read 2026-10-19), and vanilla's own layered MeleeAttackInAir_A sends
AttackStart only. Supported hypothesis: AttackStart puts the game's movement into its attacking mode, which holds the
last input. This removes both events from the layered copy's states.

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


def layer_combo(actions_raw: bytes, combo_node, upper_body: bool = False, no_pivot: bool = False,
                no_attack_events: bool = False):
    """MeleeActions with the combo state added as a layered action (see the module docstring)."""
    root = agx_edit.load(actions_raw)
    top = agx_edit.machine(root, None)
    idle = agx_edit.state(top, IDLE_STATE)
    if MACHINE in [agx_edit._rows(n).get("State Machine Name") for n in top.findall("node")]:
        raise agx_edit.AgxEditError(f"{MACHINE} is already in this MeleeActions")
    k = agx_edit.clone_state(combo_node, top)
    if upper_body:
        agx_edit.add_flag(top.findall("node")[k], "Force Copy Bone Weights")
    if no_attack_events:
        for st in top.findall("node")[k].find("graph").findall("node"):
            agx_edit.remove_state_events(st, {"AttackStart", "AttackStop"})
    if no_pivot:
        node = top.findall("node")[k]
        agx_edit.remove_flag(node, "Should Pivot to Camera")
        for st in node.find("graph").findall("node"):
            agx_edit.remove_flag(st, "Should Pivot to Camera")
    agx_edit.add_transition(root, top, k, k, "MeleeAttackStart", blend=0.15)      # from any state, as vanilla
    agx_edit.add_transition(root, top, k, idle, "", blend=0.3)                     # back to idle when it ends
    return agx_edit.dump(root, actions_raw), [f"{MACHINE} added as action {k} (any state -> it on MeleeAttackStart, "
                                              f"-> {IDLE_STATE} at its end)"]


def last_frame(afx: bytes) -> int:
    import re
    return max([int(x) for x in re.findall(rb"<(?:frame|start|end)>(\d+)<", afx)] or [0])


PIVOT_WINDOWS = {"bAlignWithAimAssistTarget", "DisableAllowRotation"}


def fix_descriptors(folder: str, free_movement: bool = False, no_pivot: bool = False):
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
    for f in ((a, b, c) if no_pivot else ()):
        if f:
            p = os.path.join(folder, f)
            with open(p, "rb") as fh:
                data, dropped = af_writer.drop_variables(fh.read(), PIVOT_WINDOWS)
            with open(p, "wb") as fh:
                fh.write(data)
            done.append(f"{f}: dropped {', '.join(dropped) or 'nothing'}")
    for f in ((a, b, c) if free_movement else ()):
        if f:
            p = os.path.join(folder, f)
            with open(p, "rb") as fh:
                data = fh.read()
            with open(p, "wb") as fh:
                fh.write(af_writer.set_variable_window(data, "bFreeMovement", 0, last_frame(data)))
            done.append(f"{f}: bFreeMovement over the whole clip")
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
    ap.add_argument("--free-movement", action="store_true", help="experiment, see above (needs --actions-graph)")
    ap.add_argument("--upper-body", action="store_true", help="experiment, see above (needs --actions-graph)")
    ap.add_argument("--no-pivot", action="store_true", help="experiment, see above (needs --actions-graph)")
    ap.add_argument("--no-attack-events", action="store_true", help="experiment, see above (needs --actions-graph)")
    a = ap.parse_args(argv)
    if (a.upper_body or a.no_pivot or a.no_attack_events) and not a.actions_graph:
        sys.exit("--upper-body / --no-pivot / --no-attack-events need --actions-graph")
    if a.free_movement and not a.actions_graph:
        sys.exit("--free-movement needs --actions-graph (a full-body swing never moves, whatever bFreeMovement says)")
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    with open(a.graph, "rb") as fh:
        data, combo, added = loop_graph(fh.read(), layered=bool(a.actions_graph))
    print(f"graph: {_write(out, GRAPH_REL, data)}; {added or 'nothing changed (already looping)'}")
    if a.actions_graph:
        with open(a.actions_graph, "rb") as fh:
            data, rep = layer_combo(fh.read(), combo, a.upper_body, a.no_pivot, a.no_attack_events)
        print(f"graph: {_write(out, ACTIONS_REL, data)}; {rep}")
    for folder in a.clips:
        print(f"{folder}: {fix_descriptors(folder, a.free_movement, a.no_pivot) or 'no A / B / C descriptors'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
