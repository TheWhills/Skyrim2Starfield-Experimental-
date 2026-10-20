"""Make the player's melee combo keep going, as in Skyrim (right, left, right, left ... while attack is pressed),
instead of Starfield's three hits (docs/armor/animation-port.md, "only three hits").

Vanilla (verified 2026-10-19 on the owner's MeleeAttacks.agx and the player one-handed descriptors): the embedded state
machine MeleeAttackCombo goes None -> MeleeAttack_A -> MeleeAttack_B on MeleeAttackStart and B -> C on
MeleeAttackFinisherStart; nothing leaves C. A and B open a bCanComboAttack window, B also bAllowFinisher (so the game
sends the finisher event); C has no combo window and bDontAllowAttack over almost all of it.

This writes:
  * <out>/meshes/animtextdata/tables/graphs/meleeattacks.agx: the vanilla graph plus C -> B and B -> C on
    MeleeAttackStart (byte-identical otherwise);
  * in each --clips folder holding our MeleeAttack_A / _B / _C descriptors (the Skyrim replacements, where A and C
    are both Skyrim's right swing): C takes A's timing (hit, combo window, attack locks), B loses bAllowFinisher.
Starfield's finisher is dropped on purpose: Skyrim has none.

    python -I scripts\\armor\\combo_loop.py --graph <extract>\\meshes\\animtextdata\\tables\\graphs\\meleeattacks.agx
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

GRAPH_REL = ("meshes", "animtextdata", "tables", "graphs", "meleeattacks.agx")
MACHINE = "MeleeAttackCombo"
LOOP = (("MeleeAttack_C", "MeleeAttack_B"), ("MeleeAttack_B", "MeleeAttack_C"))


def loop_graph(raw: bytes):
    root = agx_edit.load(raw)
    g = agx_edit.machine(root, MACHINE)
    tpl = None
    b = agx_edit.state(g, "MeleeAttack_B")
    for link in g.findall("node")[b].iter("link"):              # the vanilla A -> B link: same blend and layout
        tpl = link
    added = []
    for s, d in LOOP:
        if agx_edit.add_transition(root, g, agx_edit.state(g, s), agx_edit.state(g, d), "MeleeAttackStart",
                                   blend=0.15, template=tpl):
            added.append(f"{s} -> {d}")
    return agx_edit.dump(root, raw), added


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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, help="the vanilla MeleeAttacks.agx")
    ap.add_argument("--clips", action="append", default=[], help="folder with MeleeAttack_A/B/C.afx (repeatable)")
    ap.add_argument("--out", required=True, help="pack root (Data layout) for the edited graph")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    with open(a.graph, "rb") as fh:
        data, added = loop_graph(fh.read())
    dst = os.path.join(out, *GRAPH_REL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(data)
    print(f"graph: {dst}; added {added or 'nothing (already looping)'}")
    for folder in a.clips:
        print(f"{folder}: {fix_descriptors(folder) or 'no A / B / C descriptors'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
